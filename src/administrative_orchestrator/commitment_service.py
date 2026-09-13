from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

import httpx
from sqlalchemy.exc import IntegrityError

from .authority import AuthorityRepository
from .commitment_models import (
    CandidateCommitment,
    CandidateCommitmentClassification,
    CandidateCommitmentStatus,
    CommitmentFulfillmentAttestation,
    CommitmentFulfillmentKind,
    CommitmentRecord,
    CommitmentState,
    CommunicationDeliveryState,
    CommunicationDraftRecord,
    CommunicationEffectRecord,
    SpeakerPrincipalResolution,
)
from .commitment_repository import CommitmentConflict, CommitmentRepository
from .config import Settings, get_settings
from .domain import (
    AdministrativeCase,
    AdministrativeRequest,
    AuthorityClass,
    CaseStatus,
    Decision,
    DecisionDisposition,
    EffectReversibility,
    FactAuthority,
    FactSnapshot,
    utcnow,
)
from .execution_repository import ExecutionConflict, ExecutionRepository
from .fact_transitions import replace_facts_for_reevaluation
from .intake.artifacts import ArtifactStore, FilesystemArtifactStore
from .intake.interpretation import MeetingInterpretationPayload
from .intake.models import EvidenceSpan, InterpretationRecord
from .integrations.kernel.bridge import KernelExecutionBridge
from .integrations.kernel.client import KernelSubmissionError
from .integrations.kernel.effect_provider import KernelCutoverEffectProvider
from .obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationFulfillmentKind,
    ObligationRepository,
)
from .policy import AuthorizedEffectTemplate, PolicyDisposition, PolicyEvaluation
from .policy_plane import PolicyRepository, default_commitment_policy_version
from .service import (
    apply_policy_evaluation,
    create_case,
    mint_execution_authorization_from_approval,
    record_decision,
    start_policy_evaluation,
)
from .unit_of_work import AdministrativeUnitOfWork

_M9_NAMESPACE = UUID("7c4f2b4a-7ed5-4c72-a45c-4ecbcb1a46a3")
_REVIEW_ROLES = {"administrative_operator", "administrative_admin"}


class _NoCommunicationFallback:
    """Keep Kernel cutover fail-closed if a non-Kernel path is ever selected."""

    def execute(self, effect, payload):  # type: ignore[no-untyped-def]
        del effect, payload
        raise CommitmentIntakeError("Kernel-owned communication cannot use a fallback provider")

    def observe(self, effect):  # type: ignore[no-untyped-def]
        del effect
        raise CommitmentIntakeError("Kernel-owned communication cannot use a fallback verifier")


class CommitmentIntakeError(ValueError):
    """The candidate cannot cross the M9 human-qualification boundary."""


@dataclass(frozen=True, slots=True)
class ResponsibilityRefs:
    responsibility_ref: str
    responsibility_version: int
    admission_ref: str | None = None
    assessment_ref: str | None = None
    proposal_ref: str | None = None


class ResponsibilityProvisioner(Protocol):
    def provision(
        self,
        *,
        case: AdministrativeCase,
        commitment: CommitmentRecord,
        governance_basis: Any,
    ) -> ResponsibilityRefs: ...


class KernelCommitmentResponsibilityProvisioner:
    """Submit the generic responsibility prefix without admitting Work."""

    def __init__(self, store, *, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def provision(
        self,
        *,
        case: AdministrativeCase,
        commitment: CommitmentRecord,
        governance_basis: Any,
    ) -> ResponsibilityRefs:
        if case.policy_ref is None:
            raise CommitmentIntakeError("Kernel responsibility requires a current policy")
        bridge = KernelExecutionBridge(
            self.store,
            settings=self.settings,
            require_responsibility_discharge=True,
        )
        identity = bridge.compatibility()
        root = uuid5(_M9_NAMESPACE, f"kernel-responsibility:{commitment.commitment_id}")
        responsibility_ref = f"m9resp_{root.hex}"
        admission_ref = f"m9admission_{uuid5(_M9_NAMESPACE, f'admission:{root}').hex}"
        assessment_ref = f"m9assessment_{uuid5(_M9_NAMESPACE, f'assessment:{root}').hex}"
        proposal_ref = f"m9proposal_{uuid5(_M9_NAMESPACE, f'proposal:{root}').hex}"
        created_at = commitment.created_at.isoformat()
        policy_ref = f"{case.policy_ref.policy_id}:{case.policy_ref.version}"
        responsibility = {
            "id": responsibility_ref,
            "object_type": "StandingResponsibility",
            "created_at": created_at,
            "responsibility_kind": "administrative-commitment",
            "statement": "Maintain one admitted administrative responsibility until explicit discharge.",
            "scope": {
                "administrative_case_id": str(case.case_id),
                "authority_epoch": str(case.authority_epoch),
                "commitment_ref": str(commitment.commitment_id),
                "governance_basis_id": str(governance_basis.basis_id),
                "policy_ref": policy_ref,
            },
            "schema_version": identity.persistent_responsibility_contract,
        }
        admission = {
            "id": admission_ref,
            "object_type": "ResponsibilityAdmission",
            "created_at": created_at,
            "responsibility_ref": responsibility_ref,
            "responsibility_version": 1,
            "principal_ref": commitment.committer_principal_id,
            "basis_refs": [
                f"commitment:{commitment.commitment_id}",
                f"governance-basis:{governance_basis.basis_id}",
                f"approval-satisfaction:{governance_basis.approval_satisfaction_id}",
            ],
            "admitted_at": created_at,
        }
        assessment = {
            "id": assessment_ref,
            "object_type": "ResponsibilityAssessment",
            "created_at": created_at,
            "responsibility_ref": responsibility_ref,
            "responsibility_version": 1,
            "subject_ref": commitment.committer_principal_id,
            "assessment_kind": "administrative-commitment-ready",
            "basis_refs": [
                f"commitment:{commitment.commitment_id}",
                f"governance-basis:{governance_basis.basis_id}",
            ],
            "assessed_at": created_at,
            "rationale": "Administrative policy, identity, approval and due time are qualified.",
        }
        proposal = {
            "id": proposal_ref,
            "object_type": "WorkProposal",
            "created_at": created_at,
            "responsibility_ref": responsibility_ref,
            "responsibility_version": 1,
            "assessment_ref": assessment_ref,
            "subject_ref": commitment.committer_principal_id,
            "work_kind": "administrative-commitment",
            "title": "Maintain admitted administrative responsibility",
            "description": "Proposal prefix only; M9 does not admit Kernel Work for a meeting commitment.",
            "requested_resources": {
                "compute_units": 0,
                "api_calls": 0,
                "money_minor": 0,
                "human_attention_units": 0,
                "concurrency_slots": 0,
                "domain_quota": {},
            },
            "requested_capabilities": [],
            "expected_result": "explicit responsibility discharge after fulfillment assessment",
            "stop_conditions": [f"administrative-authority-epoch-changed:{case.case_id}"],
            "escalation_conditions": ["responsibility-discharge-basis-insufficient"],
            "effect_class": "read-only",
        }
        try:
            receipt = bridge.client().submit_payload(
                responsibility_payload=responsibility,
                admission_payload=admission,
                assessment_payload=assessment,
                proposal_payload=proposal,
            )
        except KernelSubmissionError as exc:
            raise CommitmentIntakeError(
                "Kernel responsibility proposal was not recorded"
            ) from exc
        return ResponsibilityRefs(
            responsibility_ref=receipt.responsibility_ref,
            responsibility_version=1,
            admission_ref=receipt.admission_ref,
            assessment_ref=receipt.assessment_ref,
            proposal_ref=receipt.proposal_ref,
        )


class MeetingCommitmentService:
    """M9 candidate qualification and commitment lifecycle boundary.

    Model output enters here as a candidate only.  The service is the first
    place where an authorized Feishu identity, a qualified due time, policy,
    approval, and the persistent responsibility record are joined.
    """

    def __init__(
        self,
        store,
        *,
        repository: CommitmentRepository | None = None,
        authority: AuthorityRepository | None = None,
        uow: AdministrativeUnitOfWork | None = None,
        policies: PolicyRepository | None = None,
        artifact_store: ArtifactStore | None = None,
        settings: Settings | None = None,
        responsibility_provisioner: ResponsibilityProvisioner | None = None,
    ) -> None:
        self.store = store
        self.repository = repository or CommitmentRepository(store)
        self.authority = authority or AuthorityRepository(store)
        self.uow = uow or AdministrativeUnitOfWork(store)
        self.policies = policies or PolicyRepository(store)
        settings = settings or get_settings()
        self.artifact_store = artifact_store or FilesystemArtifactStore(
            __import__("pathlib").Path(settings.feishu_artifact_root)
        )
        self.settings = settings
        self.execution = ExecutionRepository(store)
        self.obligations = ObligationRepository(store)
        self.responsibility_provisioner = responsibility_provisioner
        if self.responsibility_provisioner is None and settings.kernel_bridge_mode != "disabled":
            self.responsibility_provisioner = KernelCommitmentResponsibilityProvisioner(
                store, settings=settings
            )

    def create_candidates_from_interpretation(
        self,
        interpretation: InterpretationRecord,
        *,
        source_artifact_ref: UUID | None = None,
        evidence_spans: Sequence[EvidenceSpan] = (),
    ) -> tuple[CandidateCommitment, ...]:
        if interpretation.interpretation_profile_ref != "meeting.commitment.v1":
            return ()
        if not interpretation.structured_output:
            return ()
        payload = MeetingInterpretationPayload.model_validate(interpretation.structured_output)
        artifact_ref = source_artifact_ref or interpretation.artifact_refs[0]
        available_spans = {item.evidence_span_id for item in evidence_spans}
        output: list[CandidateCommitment] = []
        for index, draft in enumerate(payload.candidate_commitments):
            refs = tuple(dict.fromkeys((*draft.evidence_span_refs, *interpretation.evidence_span_refs)))
            if not refs and len(evidence_spans) == 1:
                refs = (evidence_spans[0].evidence_span_id,)
            if not refs:
                raise CommitmentIntakeError(
                    "meeting commitment candidate requires at least one EvidenceSpan"
                )
            if available_spans and any(ref not in available_spans for ref in refs):
                raise CommitmentIntakeError("candidate references an unavailable EvidenceSpan")
            candidate = CandidateCommitment(
                candidate_commitment_id=uuid5(
                    _M9_NAMESPACE, f"candidate:{interpretation.interpretation_id}:{index}"
                ),
                source_artifact_ref=artifact_ref,
                interpretation_ref=interpretation.interpretation_id,
                evidence_span_refs=refs,
                candidate_committer_identity=draft.speaker_label,
                candidate_action=draft.candidate_action,
                candidate_due_text=draft.candidate_due_text,
                candidate_due_at=draft.candidate_due_at,
                candidate_scope_ref=draft.candidate_scope_ref,
                candidate_beneficiary=draft.candidate_beneficiary,
                classification=CandidateCommitmentClassification(draft.classification.value),
            )
            output.append(self.repository.put_candidate(candidate))
        return tuple(output)

    def resolve_speaker(
        self,
        candidate_id: UUID,
        *,
        reviewer_principal_id: str,
        external_subject: str,
        basis: dict[str, Any],
        provider: str = "feishu",
    ) -> SpeakerPrincipalResolution:
        candidate = self._candidate(candidate_id)
        self._require_reviewer(reviewer_principal_id)
        external_subject = external_subject.strip()
        provider = provider.strip()
        if not external_subject or not provider or not basis:
            raise CommitmentIntakeError("speaker resolution requires provider, subject and basis")
        principal = self.authority.resolve_identity(
            provider=provider,
            external_subject=external_subject,
            at=utcnow(),
        )
        if principal is None:
            raise CommitmentIntakeError(
                "speaker identity is unresolved or has zero/multiple current bindings"
            )
        resolution = SpeakerPrincipalResolution(
            resolution_id=uuid5(_M9_NAMESPACE, f"resolution:{candidate_id}"),
            candidate_ref=candidate_id,
            source_speaker_identity=candidate.candidate_committer_identity,
            resolved_principal_id=principal.principal_id,
            provider=provider,
            external_subject=external_subject,
            basis={**basis, "reviewer_principal_id": reviewer_principal_id},
            resolver_type="authorized_human",
        )
        return self.repository.put_resolution(resolution)

    def confirm_candidate(
        self,
        candidate_id: UUID,
        *,
        reviewer_principal_id: str,
        qualified_due_at: datetime,
        due_time_basis: str,
        fulfillment_kind: CommitmentFulfillmentKind = CommitmentFulfillmentKind.AUTHORIZED_ATTESTATION,
    ) -> tuple[AdministrativeCase, CommitmentRecord]:
        self._require_reviewer(reviewer_principal_id)
        if qualified_due_at.tzinfo is None:
            raise CommitmentIntakeError("qualified due_at must be offset-aware")
        due_time_basis = due_time_basis.strip()
        if not due_time_basis:
            raise CommitmentIntakeError("qualified due time requires a basis")
        candidate = self._candidate(candidate_id)
        if candidate.classification is not CandidateCommitmentClassification.EXPLICIT_SELF_COMMITMENT:
            raise CommitmentIntakeError("only explicit self commitments may be admitted")
        resolution = self.repository.get_resolution(candidate_id)
        if resolution is None:
            raise CommitmentIntakeError("speaker principal resolution is required")
        existing = self.repository.get_commitment_for_candidate(candidate_id)
        if existing is not None:
            case = self.store.get_case(existing.case_id)
            if case is None:
                raise CommitmentConflict("commitment points to a missing case")
            if existing.due_at != qualified_due_at.astimezone(UTC):
                raise CommitmentConflict("candidate already has a different qualified due time")
            return case, existing

        policy = self._current_policy()
        evaluation = PolicyEvaluation(
            policy_ref=policy.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="M9 commitment admission requires an authorized human decision",
            required_decision_roles=("administrative_operator",),
            allowed_effects=(
                AuthorizedEffectTemplate(
                    target_system="communication",
                    operation="message.send",
                    authority_class=AuthorityClass.NORMAL,
                ),
            ),
        )
        due_at = qualified_due_at.astimezone(UTC)
        case_id = uuid5(_M9_NAMESPACE, f"case:{candidate_id}")
        request = AdministrativeRequest(
            request_id=uuid5(_M9_NAMESPACE, f"request:{candidate_id}"),
            requester_principal_id=resolution.resolved_principal_id,
            channel="meeting-intake",
            intent="meeting-commitment",
            source_ref=f"candidate-commitment:{candidate_id}",
        )
        snapshot = FactSnapshot(
            source="meeting.commitment.v1",
            owner="administrative-orchestrator",
            authority=FactAuthority.CLAIM,
            source_ref=f"interpretation:{candidate.interpretation_ref}",
            facts={
                "candidate_ref": str(candidate_id),
                "committer_principal_id": resolution.resolved_principal_id,
                "committer_external_subject": resolution.external_subject,
                "commitment_action": candidate.candidate_action,
                "due_at": due_at.isoformat(),
                "due_time_basis": due_time_basis,
                "source_artifact_ref": str(candidate.source_artifact_ref),
                "evidence_span_refs": [str(item) for item in candidate.evidence_span_refs],
            },
        )
        original = create_case(
            request,
            case_kind="meeting-commitment",
            subject_ref=f"commitment:{candidate_id}",
            fact_snapshot=snapshot,
        ).model_copy(update={"case_id": case_id})
        try:
            self.uow.create_case(request, original)
        except IntegrityError as exc:
            replayed = self.store.get_case(case_id)
            if replayed is None:
                raise CommitmentConflict("commitment admission conflicted") from exc
            original = replayed

        if original.status is CaseStatus.RECEIVED:
            ready = start_policy_evaluation(original)
            awaiting = apply_policy_evaluation(ready, evaluation)
            self.uow.apply_policy_transition(original, awaiting, evaluation)
            current = awaiting
        else:
            current = self.store.get_case(case_id) or original

        if current.status is CaseStatus.AWAITING_DECISION:
            decision = Decision(
                decision_id=uuid5(_M9_NAMESPACE, f"decision:{candidate_id}"),
                case_id=current.case_id,
                case_version=current.version,
                authority_epoch=current.authority_epoch,
                principal_id=reviewer_principal_id,
                decision_role="administrative_operator",
                disposition=DecisionDisposition.APPROVE,
                rationale="Human-qualified explicit self commitment",
                policy_ref=current.policy_ref,  # type: ignore[arg-type]
            )
            assessment = self._assess_approval(current, evaluation, decision)
            if not assessment.satisfied or assessment.satisfaction is None:
                raise CommitmentIntakeError("reviewer does not satisfy the commitment policy")
            authorized = record_decision(current, decision, approval_complete=True)
            self.uow.apply_decision_transition(
                current,
                authorized,
                decision,
                organization_scope="*",
                approval_satisfaction=assessment.satisfaction,
            )
            current = authorized
        elif current.status is not CaseStatus.AUTHORIZED:
            raise CommitmentIntakeError(
                f"commitment admission cannot continue from case status {current.status.value}"
            )

        current = self.store.get_case(case_id) or current
        governance = self.uow.governance.get_current_for_case(
            current.case_id, current.authority_epoch
        )
        if governance is None:
            raise CommitmentIntakeError("approved commitment has no governance basis")
        commitment = CommitmentRecord(
            commitment_id=uuid5(_M9_NAMESPACE, f"commitment:{candidate_id}"),
            candidate_ref=candidate_id,
            case_id=current.case_id,
            authority_epoch=current.authority_epoch,
            committer_principal_id=resolution.resolved_principal_id,
            committer_external_subject=resolution.external_subject,
            commitment_action=candidate.candidate_action,
            due_at=due_at,
            due_time_basis=due_time_basis,
            scope_ref=candidate.candidate_scope_ref,
            fulfillment_kind=fulfillment_kind,
            created_at=current.updated_at,
            updated_at=current.updated_at,
        )
        if self.responsibility_provisioner is not None:
            refs = self.responsibility_provisioner.provision(
                case=current,
                commitment=commitment,
                governance_basis=governance,
            )
            commitment = commitment.model_copy(
                update={
                    "responsibility_ref": refs.responsibility_ref,
                    "responsibility_version": refs.responsibility_version,
                    "responsibility_admission_ref": refs.admission_ref,
                    "responsibility_assessment_ref": refs.assessment_ref,
                    "responsibility_proposal_ref": refs.proposal_ref,
                }
            )
        commitment = self.repository.put_commitment(commitment)
        self.repository.update_candidate_status(
            candidate_id, status=CandidateCommitmentStatus.ADMITTED
        )
        self.ensure_communication(commitment, draft_kind="confirmation")
        return current, commitment

    def ensure_communication(
        self,
        commitment: CommitmentRecord,
        *,
        draft_kind: str,
    ) -> CommunicationEffectRecord:
        case = self.store.get_case(commitment.case_id)
        if case is None or case.policy_ref is None:
            raise CommitmentIntakeError("communication requires a current governed case")
        if case.authority_epoch != commitment.authority_epoch:
            raise CommitmentIntakeError(
                "communication requires commitment revalidation after an authority epoch change"
            )
        if draft_kind not in {"confirmation", "reminder"}:
            raise CommitmentIntakeError("unsupported communication draft kind")
        text = self._communication_text(commitment, draft_kind)
        stored = self.artifact_store.put(text.encode("utf-8"))
        draft_id = uuid5(
            _M9_NAMESPACE, f"draft:{commitment.commitment_id}:{commitment.version}:{draft_kind}"
        )
        draft = CommunicationDraftRecord(
            draft_id=draft_id,
            case_id=commitment.case_id,
            authority_epoch=commitment.authority_epoch,
            channel="feishu-one-to-one",
            recipient_principal_id=commitment.committer_principal_id,
            recipient_external_subject=commitment.committer_external_subject,
            content_storage_ref=stored.storage_ref,
            content_digest=stored.digest,
            content_size=stored.size,
            draft_kind=draft_kind,
            generator_ref=f"administrative-orchestrator:m9-template:{draft_kind}:v1",
            created_at=commitment.updated_at,
        )
        self.repository.put_draft(draft)
        approval = self.uow.authority.get_approval_satisfaction(
            commitment.case_id, commitment.authority_epoch
        )
        if approval is None:
            raise CommitmentIntakeError("communication requires current approval satisfaction")
        governance = self.uow.governance.get_current_for_case(
            commitment.case_id, commitment.authority_epoch
        )
        if governance is None:
            raise CommitmentIntakeError("communication requires current governance basis")
        authorization = mint_execution_authorization_from_approval(
            case,
            approval,
            issuer_principal_id="service:administrative-orchestrator",
            target_system="communication",
            allowed_operations=("message.send",),
            authority_class=AuthorityClass.NORMAL,
        ).model_copy(
            update={
                "authorization_id": uuid5(
                    _M9_NAMESPACE, f"authorization:{commitment.case_id}:{commitment.authority_epoch}"
                ),
                "issued_at": commitment.updated_at,
            }
        )
        existing_authorization = self.execution.get_authorization(authorization.authorization_id)
        if existing_authorization is None:
            authorization = self.execution.put_authorization(authorization)
        else:
            if (
                existing_authorization.model_copy(update={"issued_at": authorization.issued_at})
                != authorization
            ):
                raise ExecutionConflict("communication authorization semantics drifted")
            authorization = existing_authorization
        effect_ids = {
            kind: uuid5(
                _M9_NAMESPACE,
                f"effect:{commitment.commitment_id}:{commitment.version}:{kind}",
            )
            for kind in ("confirmation", "reminder")
        }
        obligation_ids = {
            kind: uuid5(_M9_NAMESPACE, f"obligation:{effect_ids[kind]}")
            for kind in effect_ids
        }

        def build_obligation(kind: str) -> AdministrativeObligation:
            return AdministrativeObligation(
                obligation_id=obligation_ids[kind],
                case_id=commitment.case_id,
                authority_epoch=commitment.authority_epoch,
                governance_basis_id=governance.basis_id,
                kind=f"meeting-commitment-communication:{kind}",
                subject_ref=case.subject_ref,
                target_system="communication",
                required_operation="message.send",
                expected_postcondition={
                    "communication_event_id": str(uuid5(_M9_NAMESPACE, f"event:{effect_ids[kind]}")),
                    "recipient_external_subject": commitment.committer_external_subject,
                    "content_digest": (
                        stored.digest
                        if kind == draft_kind
                        else hashlib.sha256(
                            self._communication_text(commitment, kind).encode("utf-8")
                        ).hexdigest()
                    ),
                    "transport_accepted": True,
                    "delivery_confirmed": True,
                    "read_state": "unknown",
                },
                authority_class=AuthorityClass.NORMAL,
                fulfillment_kind=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED,
            )

        obligation_set = AdministrativeObligationSet(
            requirement_id=uuid5(_M9_NAMESPACE, f"obligation-set:{commitment.case_id}:{commitment.authority_epoch}"),
            case_id=commitment.case_id,
            authority_epoch=commitment.authority_epoch,
            governance_basis_id=governance.basis_id,
            obligations=(build_obligation("confirmation"), build_obligation("reminder")),
        )
        from .service import plan_effect

        existing_obligation_set = self.obligations.get_current(
            commitment.case_id,
            commitment.authority_epoch,
        )
        if existing_obligation_set is None:
            self.obligations.put(obligation_set)
            obligation = next(
                item
                for item in obligation_set.obligations
                if item.obligation_id == obligation_ids[draft_kind]
            )
            effect_id = effect_ids[draft_kind]
        else:
            if existing_obligation_set.governance_basis_id != governance.basis_id:
                raise CommitmentIntakeError("communication obligation governance basis drifted")
            obligation = next(
                (
                    item
                    for item in existing_obligation_set.obligations
                    if item.kind == f"meeting-commitment-communication:{draft_kind}"
                ),
                None,
            )
            if obligation is None:
                raise CommitmentIntakeError("communication obligation kind is unavailable")
            links = self.obligations.list_links(
                commitment.case_id,
                commitment.authority_epoch,
            )
            linked_effect = next(
                (item.effect_id for item in links if item.obligation_id == obligation.obligation_id),
                None,
            )
            effect_id = linked_effect or uuid5(
                _M9_NAMESPACE,
                f"effect:{obligation.obligation_id}",
            )

        communication_event_id = uuid5(_M9_NAMESPACE, f"event:{effect_id}")
        if existing_obligation_set is not None:
            expected_postcondition = obligation.expected_postcondition
            expected_event_id = expected_postcondition.get("communication_event_id")
            expected_recipient = expected_postcondition.get("recipient_external_subject")
            expected_content_digest = expected_postcondition.get("content_digest")
            if not isinstance(expected_event_id, str):
                raise CommitmentIntakeError(
                    "communication obligation event identity is unavailable"
                )
            try:
                communication_event_id = UUID(expected_event_id)
            except ValueError as exc:
                raise CommitmentIntakeError(
                    "communication obligation event identity is invalid"
                ) from exc
            if (
                expected_recipient != draft.recipient_external_subject
                or expected_content_digest != draft.content_digest
            ):
                raise CommitmentIntakeError(
                    "communication obligation postcondition drifted"
                )

        effect = plan_effect(
            case,
            authorization,
            operation="message.send",
            reversibility=EffectReversibility.IRREVERSIBLE,
        ).model_copy(
            update={
                "effect_id": effect_id,
                "obligation_id": obligation.obligation_id,
                "governance_basis_id": obligation_set.governance_basis_id,
                "created_at": commitment.updated_at,
                "updated_at": commitment.updated_at,
            }
        )
        self.execution.put_effect(effect)
        self.obligations.link_effect(effect, obligation)
        event = CommunicationEffectRecord(
            communication_event_id=communication_event_id,
            case_id=commitment.case_id,
            authority_epoch=commitment.authority_epoch,
            draft_id=draft_id,
            effect_id=effect_id,
            delivery_state=CommunicationDeliveryState.PREPARED,
            created_at=commitment.updated_at,
            updated_at=commitment.updated_at,
        )
        return self.repository.put_communication(event)

    def attest_fulfillment(
        self,
        case_id: UUID,
        *,
        principal_id: str,
        basis: dict[str, Any],
        at: datetime | None = None,
    ) -> CommitmentRecord:
        at = at or utcnow()
        commitment = self.repository.get_commitment(case_id)
        case = self.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "fulfillment requires commitment revalidation after an authority epoch change"
            )
        if principal_id != commitment.committer_principal_id:
            raise PermissionError("only the qualified committer may attest fulfillment")
        if not self.authority.get_principal(principal_id):
            raise CommitmentIntakeError("attesting principal is inactive or unknown")
        if not basis:
            raise CommitmentIntakeError("fulfillment attestation requires a basis")
        if commitment.state is CommitmentState.FULFILLED:
            return commitment
        attestation = CommitmentFulfillmentAttestation(
            attestation_id=uuid5(_M9_NAMESPACE, f"attestation:{case_id}:{commitment.version}"),
            case_id=case_id,
            authority_epoch=commitment.authority_epoch,
            commitment_version=commitment.version,
            principal_id=principal_id,
            basis=basis,
        )
        self.repository.put_attestation(attestation)
        updated = commitment.model_copy(
            update={
                "state": CommitmentState.FULFILLED,
                "was_overdue": commitment.was_overdue or at > commitment.due_at,
                "updated_at": at,
            }
        )
        updated = self.repository.update_commitment(updated)
        if case.status not in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
            completed = case.model_copy(
                update={
                    "status": CaseStatus.COMPLETED,
                    "version": case.version + 1,
                    "updated_at": at,
                }
            )
            self.store.update_case(
                completed,
                expected_previous_version=case.version,
                event_type="commitment.fulfilled",
                payload={"attestation_id": str(attestation.attestation_id)},
            )
        return updated

    def drive(self, case_id: UUID, *, at: datetime | None = None) -> dict[str, Any]:
        """Drive due-state and bounded communication effects for one case."""

        at = at or utcnow()
        commitment = self.repository.get_commitment(case_id)
        case = self.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "commitment drive requires revalidation after an authority epoch change"
            )
        if commitment.state is CommitmentState.ACTIVE and at >= commitment.due_at:
            overdue = commitment.model_copy(
                update={"state": CommitmentState.OVERDUE, "was_overdue": True, "updated_at": at}
            )
            commitment = self.repository.update_commitment(overdue)

        if commitment.state is CommitmentState.OVERDUE and not any(
            (draft := self.repository.get_draft(item.draft_id)) is not None
            and draft.draft_kind == "reminder"
            for item in self.repository.list_communications(case_id)
        ):
            self.ensure_communication(commitment, draft_kind="reminder")

        if not self.settings.external_effects_enabled:
            return {
                "case_id": str(case_id),
                "commitment_state": commitment.state.value,
                "due_at": commitment.due_at.isoformat(),
                "dispatched_communication_event_ids": [],
                "reason": "external_effects_disabled",
            }

        dispatched: list[str] = []
        for communication in self.repository.list_communications(
            case_id, authority_epoch=commitment.authority_epoch
        ):
            if communication.delivery_state is CommunicationDeliveryState.PREPARED:
                self.dispatch_communication(communication.communication_event_id)
                dispatched.append(str(communication.communication_event_id))
        return {
            "case_id": str(case_id),
            "commitment_state": commitment.state.value,
            "due_at": commitment.due_at.isoformat(),
            "dispatched_communication_event_ids": dispatched,
        }

    def dispatch_communication(self, communication_event_id: UUID) -> CommunicationEffectRecord:
        """Transport one prepared draft; body content never enters the ledger."""

        communication = self.repository.get_communication_event(communication_event_id)
        if communication is None:
            raise CommitmentIntakeError("communication event not found")
        if communication.delivery_state is not CommunicationDeliveryState.PREPARED:
            return communication
        draft = self.repository.get_draft(communication.draft_id)
        case = self.store.get_case(communication.case_id)
        commitment = self.repository.get_commitment(communication.case_id)
        if draft is None or case is None or commitment is None:
            raise CommitmentIntakeError("communication lineage is incomplete")
        if communication.authority_epoch != commitment.authority_epoch:
            stale = communication.model_copy(
                update={
                    "delivery_state": CommunicationDeliveryState.PERMANENT_FAILED,
                    "last_error_code": "STALE_AUTHORITY_EPOCH",
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(stale)

        if self.settings.kernel_bridge_mode == "cutover":
            return self._dispatch_communication_via_kernel(
                communication=communication,
                draft=draft,
            )

        gateway = self.settings.communication_gateway_base_url.strip().rstrip("/")
        secret = self._communication_secret()
        if not gateway or not secret:
            retrying = communication.model_copy(
                update={
                    "delivery_state": CommunicationDeliveryState.RETRYING,
                    "last_error_code": "COMMUNICATION_TRANSPORT_NOT_CONFIGURED",
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(retrying)
        body = json.dumps(
            {
                "eventId": str(communication.communication_event_id),
                "recipientOpenId": draft.recipient_external_subject,
                "text": self.artifact_store.get(
                    draft.content_storage_ref, expected_digest=draft.content_digest
                ).decode("utf-8"),
                "draftKind": draft.draft_kind,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        digest = hashlib.sha256(body).hexdigest()
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}\n{communication.communication_event_id}\n{digest}".encode(),
            hashlib.sha256,
        ).hexdigest()
        try:
            response = httpx.post(
                f"{gateway}/v1/administrative/communications",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Event-ID": str(communication.communication_event_id),
                    "X-Timestamp": timestamp,
                    "X-Signature": signature,
                },
                timeout=self.settings.communication_gateway_timeout_seconds,
            )
            if response.status_code >= 400:
                next_state = (
                    CommunicationDeliveryState.OUTCOME_UNKNOWN
                    if response.status_code in {408, 425, 429, 500, 502, 503, 504}
                    else CommunicationDeliveryState.PERMANENT_FAILED
                )
                failed = communication.model_copy(
                    update={
                        "delivery_state": next_state,
                        "last_error_code": f"GATEWAY_HTTP_{response.status_code}",
                        "attempts": communication.attempts + 1,
                        "updated_at": utcnow(),
                    }
                )
                return self.repository.update_communication(failed)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("communication gateway returned a non-object response")
            confirmed = bool(payload.get("deliveryConfirmed", False))
            sent = communication.model_copy(
                update={
                    "delivery_state": (
                        CommunicationDeliveryState.DELIVERY_CONFIRMED
                        if confirmed
                        else CommunicationDeliveryState.TRANSPORT_ACCEPTED
                    ),
                    "provider_message_ref": payload.get("providerMessageRef"),
                    "attempts": communication.attempts + 1,
                    "last_error_code": None,
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(sent)
        except (httpx.HTTPError, ValueError, UnicodeError) as exc:
            unknown = communication.model_copy(
                update={
                    "delivery_state": CommunicationDeliveryState.OUTCOME_UNKNOWN,
                    "last_error_code": type(exc).__name__,
                    "attempts": communication.attempts + 1,
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(unknown)

    def _dispatch_communication_via_kernel(
        self,
        *,
        communication: CommunicationEffectRecord,
        draft: CommunicationDraftRecord,
    ) -> CommunicationEffectRecord:
        effect = self.execution.get_effect(communication.effect_id)
        if effect is None:
            raise CommitmentIntakeError("communication effect lineage is incomplete")
        bridge = KernelExecutionBridge(self.store, settings=self.settings)
        provider = KernelCutoverEffectProvider(_NoCommunicationFallback(), bridge)
        result = provider.execute(
            effect,
            {
                "communication_event_id": str(communication.communication_event_id),
                "recipient_open_id": draft.recipient_external_subject,
                "content_storage_ref": draft.content_storage_ref,
                "content_digest": draft.content_digest,
                "draft_kind": draft.draft_kind,
            },
        )
        state = CommunicationDeliveryState.OUTCOME_UNKNOWN
        error_code = "KERNEL_EXECUTION_OUTCOME_UNKNOWN"
        provider_message_ref: str | None = None
        if result.status.value == "failed":
            state = CommunicationDeliveryState.PERMANENT_FAILED
            error_code = "KERNEL_EXECUTION_FAILED"
        elif result.status.value == "succeeded":
            observation = provider.observe(effect)
            if (
                observation.availability.value == "available"
                and observation.presence.value == "present"
                and observation.freshness.value == "current"
            ):
                state = CommunicationDeliveryState.DELIVERY_CONFIRMED
                error_code = None
                candidate_ref = observation.state.get("provider_message_ref")
                if isinstance(candidate_ref, str) and candidate_ref:
                    provider_message_ref = candidate_ref
            else:
                error_code = "KERNEL_VERIFICATION_UNAVAILABLE"
        updated = communication.model_copy(
            update={
                "delivery_state": state,
                "provider_message_ref": provider_message_ref,
                "attempts": communication.attempts + 1,
                "last_error_code": error_code,
                "updated_at": utcnow(),
            }
        )
        return self.repository.update_communication(updated)

    def discharge_responsibility(self, case_id: UUID) -> CommitmentRecord:
        commitment = self.repository.get_commitment(case_id)
        case = self.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.state is not CommitmentState.FULFILLED:
            raise CommitmentIntakeError("responsibility discharge requires fulfillment")
        if not commitment.responsibility_ref or commitment.responsibility_version is None:
            raise CommitmentIntakeError("Kernel responsibility has not been provisioned")
        client = KernelExecutionBridge(
            self.store,
            settings=self.settings,
            require_responsibility_discharge=True,
        ).client()
        status = client.get_responsibility_status(
            commitment.responsibility_ref,
            expected_version=commitment.responsibility_version,
        )
        if status.current_status == "discharged":
            return commitment
        root = f"{commitment.commitment_id}:{commitment.version}"
        assessment_ref = f"m9discharge_assessment_{uuid5(_M9_NAMESPACE, root + ':assessment').hex}"
        decision_ref = f"m9discharge_decision_{uuid5(_M9_NAMESPACE, root + ':decision').hex}"
        transition_ref = f"m9transition_{uuid5(_M9_NAMESPACE, root + ':transition').hex}"
        basis_refs = [
            f"commitment:{commitment.commitment_id}",
            f"fulfillment-attestation:{case_id}",
        ]
        now = utcnow()
        client.record_assessment(
            assessment_ref=assessment_ref,
            responsibility_ref=commitment.responsibility_ref,
            responsibility_version=commitment.responsibility_version,
            subject_ref=commitment.committer_principal_id,
            assessment_kind="commitment-fulfilled",
            basis_refs=basis_refs,
            assessed_at=now,
            fresh_until=None,
            rationale="Fulfillment was assessed from the durable authorized attestation.",
            created_at=now,
        )
        policy_ref = (
            f"{case.policy_ref.policy_id}:{case.policy_ref.version}"
            if case.policy_ref is not None
            else "meeting-commitment:m9-v1"
        )
        client.record_discharge_decision(
            decision_ref=decision_ref,
            responsibility_ref=commitment.responsibility_ref,
            responsibility_version=commitment.responsibility_version,
            assessment_ref=assessment_ref,
            basis_refs=[*basis_refs, assessment_ref],
            policy_ref=policy_ref,
            decided_at=now,
            rationale="Explicit discharge decision after fulfillment assessment.",
            created_at=now,
        )
        client.apply_lifecycle_transition(
            transition_ref=transition_ref,
            responsibility_ref=commitment.responsibility_ref,
            responsibility_version=commitment.responsibility_version,
            decision_ref=decision_ref,
            basis_refs=[*basis_refs, assessment_ref, decision_ref],
            applied_at=now,
            reason="Commitment fulfilled and responsibility explicitly discharged.",
            created_at=now,
        )
        updated = commitment.model_copy(
            update={
                "responsibility_discharge_assessment_ref": assessment_ref,
                "responsibility_discharge_decision_ref": decision_ref,
                "responsibility_transition_ref": transition_ref,
                "updated_at": now,
            }
        )
        return self.repository.update_commitment(updated)

    def _communication_secret(self) -> str:
        value = self.settings.communication_transport_secret
        if value is not None:
            secret = value.get_secret_value().strip()
            if secret:
                return secret
        path = self.settings.communication_transport_secret_file.strip()
        if not path:
            return ""
        secret_path = Path(path)
        if not secret_path.is_file() or secret_path.is_symlink():
            return ""
        return secret_path.read_text(encoding="utf-8").strip()

    def revise_due_at(
        self,
        case_id: UUID,
        *,
        reviewer_principal_id: str,
        due_at: datetime,
        basis: str,
    ) -> CommitmentRecord:
        self._require_reviewer(reviewer_principal_id)
        if due_at.tzinfo is None or not basis.strip():
            raise CommitmentIntakeError("due revision requires an offset-aware time and basis")
        commitment = self.repository.get_commitment(case_id)
        case = self.store.get_case(case_id)
        if commitment is None or case is None or commitment.state in {
            CommitmentState.FULFILLED,
            CommitmentState.CANCELLED,
        }:
            raise CommitmentIntakeError("commitment cannot be revised in its current state")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "commitment revision requires revalidation after an authority epoch change"
            )
        if case.fact_snapshot is None:
            raise CommitmentIntakeError("due revision requires a current fact snapshot")
        now = utcnow()
        facts = dict(case.fact_snapshot.facts)
        facts["due_at"] = due_at.astimezone(UTC).isoformat()
        facts["due_time_basis"] = basis
        snapshot = case.fact_snapshot.model_copy(
            update={"snapshot_id": uuid5(_M9_NAMESPACE, f"facts:{case_id}:{commitment.version + 1}"), "facts": facts, "observed_at": now}
        )
        changed = replace_facts_for_reevaluation(case, snapshot)
        policy = self._current_policy()
        evaluation = self._commitment_policy_evaluation(policy)
        ready = start_policy_evaluation(changed)
        awaiting = apply_policy_evaluation(ready, evaluation)
        self.uow.replace_facts_and_apply_policy(case, awaiting, evaluation)
        decision = Decision(
            decision_id=uuid5(_M9_NAMESPACE, f"revision-decision:{case_id}:{commitment.version + 1}"),
            case_id=awaiting.case_id,
            case_version=awaiting.version,
            authority_epoch=awaiting.authority_epoch,
            principal_id=reviewer_principal_id,
            decision_role="administrative_operator",
            disposition=DecisionDisposition.APPROVE,
            rationale="Human-qualified commitment due-time revision",
            policy_ref=awaiting.policy_ref,  # type: ignore[arg-type]
        )
        assessment = self._assess_approval(awaiting, evaluation, decision)
        if not assessment.satisfied or assessment.satisfaction is None:
            raise CommitmentIntakeError("reviewer does not satisfy the revised commitment policy")
        authorized = record_decision(awaiting, decision, approval_complete=True)
        self.uow.apply_decision_transition(
            awaiting,
            authorized,
            decision,
            organization_scope="*",
            approval_satisfaction=assessment.satisfaction,
        )
        revised_case = authorized
        revised = commitment.model_copy(
            update={
                "authority_epoch": revised_case.authority_epoch,
                "due_at": due_at.astimezone(UTC),
                "due_time_basis": basis,
                "version": commitment.version,
                "updated_at": now,
                "state": CommitmentState.ACTIVE,
            }
        )
        revised = self.repository.update_commitment(revised)
        self.ensure_communication(revised, draft_kind="confirmation")
        return revised

    def cancel_commitment(
        self,
        case_id: UUID,
        *,
        reviewer_principal_id: str,
        basis: str,
    ) -> CommitmentRecord:
        """Cancel a commitment without deleting its candidate or history.

        Cancellation advances the case authority epoch so any old timer or
        prepared reminder is stale.  It intentionally does not infer that a
        Kernel responsibility is discharged; that remains an explicit
        responsibility reassessment/discharge decision.
        """

        self._require_reviewer(reviewer_principal_id)
        basis = basis.strip()
        if not basis:
            raise CommitmentIntakeError("commitment cancellation requires a basis")
        commitment = self.repository.get_commitment(case_id)
        case = self.store.get_case(case_id)
        if commitment is None or case is None:
            raise CommitmentIntakeError("commitment case not found")
        if commitment.authority_epoch != case.authority_epoch:
            raise CommitmentIntakeError(
                "commitment cancellation requires revalidation after an authority epoch change"
            )
        if commitment.state is CommitmentState.CANCELLED:
            return commitment
        if commitment.state is CommitmentState.FULFILLED or case.status in {
            CaseStatus.COMPLETED,
            CaseStatus.CANCELLED,
        }:
            raise CommitmentIntakeError("fulfilled or terminal commitment cannot be cancelled")

        now = utcnow()
        cancelled_case = case.model_copy(
            update={
                "status": CaseStatus.CANCELLED,
                "version": case.version + 1,
                "authority_epoch": case.authority_epoch + 1,
                "updated_at": now,
            }
        )
        self.store.update_case(
            cancelled_case,
            expected_previous_version=case.version,
            event_type="commitment.cancelled",
            payload={
                "reviewer_principal_id": reviewer_principal_id,
                "basis_digest": hashlib.sha256(basis.encode("utf-8")).hexdigest(),
                "responsibility_reassessment_required": commitment.responsibility_ref is not None,
            },
        )
        cancelled = self.repository.update_commitment(
            commitment.model_copy(
                update={
                    "state": CommitmentState.CANCELLED,
                    "authority_epoch": cancelled_case.authority_epoch,
                    "version": commitment.version,
                    "updated_at": now,
                }
            )
        )
        for communication in self.repository.list_communications(case_id):
            if communication.delivery_state in {
                CommunicationDeliveryState.PREPARED,
                CommunicationDeliveryState.RETRYING,
            }:
                self.repository.update_communication(
                    communication.model_copy(
                        update={
                            "delivery_state": CommunicationDeliveryState.PERMANENT_FAILED,
                            "last_error_code": "COMMITMENT_CANCELLED",
                            "updated_at": now,
                        }
                    )
                )
        return cancelled

    @staticmethod
    def _commitment_policy_evaluation(policy) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy_ref=policy.policy_ref,
            disposition=PolicyDisposition.HUMAN_DECISION_REQUIRED,
            reason="M9 commitment admission requires an authorized human decision",
            required_decision_roles=("administrative_operator",),
            allowed_effects=(
                AuthorizedEffectTemplate(
                    target_system="communication",
                    operation="message.send",
                    authority_class=AuthorityClass.NORMAL,
                ),
            ),
        )

    def _current_policy(self):
        try:
            return self.policies.resolve_current("meeting-commitment")
        except Exception:
            # Local/test stores are often initialized without the foundation
            # command.  The same immutable default is used; production still
            # records and revalidates it through the policy plane.
            record = default_commitment_policy_version()
            self.policies.put_version(record)
            return record

    def _assess_approval(
        self,
        case: AdministrativeCase,
        evaluation: PolicyEvaluation,
        decision: Decision,
    ):
        from .authority import assess_approval_satisfaction

        return assess_approval_satisfaction(
            self.authority,
            case_id=case.case_id,
            authority_epoch=case.authority_epoch,
            policy_ref=case.policy_ref,  # type: ignore[arg-type]
            evaluation=evaluation,
            decisions=(decision,),
            organization_scope="*",
        )

    def _require_reviewer(self, principal_id: str) -> None:
        principal = self.authority.get_principal(principal_id)
        roles = self.authority.roles_for(principal_id, organization_scope="*")
        if principal is None or not roles.intersection(_REVIEW_ROLES):
            raise PermissionError(
                f"principal {principal_id} lacks an M9 commitment review role"
            )

    def _candidate(self, candidate_id: UUID) -> CandidateCommitment:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise CommitmentIntakeError("meeting commitment candidate not found")
        if candidate.status in {
            CandidateCommitmentStatus.REJECTED,
            CandidateCommitmentStatus.SUPERSEDED,
        }:
            raise CommitmentIntakeError("candidate is no longer admissible")
        return candidate

    @staticmethod
    def _communication_text(commitment: CommitmentRecord, draft_kind: str) -> str:
        label = "确认" if draft_kind == "confirmation" else "提醒"
        return (
            f"行政承诺{label}：请确认你承诺在 {commitment.due_at.isoformat()} 前完成："
            f"{commitment.commitment_action}。回复仅用于记录，不代表承诺已完成。"
        )


__all__ = [
    "CommitmentIntakeError",
    "KernelCommitmentResponsibilityProvisioner",
    "MeetingCommitmentService",
    "ResponsibilityProvisioner",
    "ResponsibilityRefs",
]
