from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from .authority import AuthorityRepository
from .completion import assess_onboarding_completion
from .config import get_settings
from .domain import (
    AdministrativeCase,
    CaseStatus,
    ConfirmedOutcome,
    DecisionDisposition,
    EffectRealizationAssessment,
    EffectStatus,
    EvidenceRef,
    RealizationDisposition,
    ReopenReason,
)
from .effect_provider import EffectProvider, ProviderExecutionStatus
from .execution_repository import ExecutionRepository
from .execution_transitions import (
    begin_reconciliation,
    complete_verified_case,
    fail_execution,
    resume_verification,
)
from .persistence import SqlStore
from .service import (
    TransitionError,
    begin_execution,
    begin_verification,
    mint_execution_authorization,
    mint_execution_authorization_from_approval,
    plan_effect,
    require_reopen,
)
from .verification import VerificationDisposition, verify_onboarding_observation


class OnboardingExecutionEngine:
    """Recoverable onboarding driver over durable domain facts and a typed reality boundary."""

    def __init__(self, store: SqlStore, provider: EffectProvider) -> None:
        self.store = store
        self.repository = ExecutionRepository(store)
        self.provider = provider

    def run(self, case_id: UUID) -> AdministrativeCase:
        case = self._require_case(case_id)
        if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED, CaseStatus.FAILED}:
            return case
        if case.status in {
            CaseStatus.RECEIVED,
            CaseStatus.GATHERING_FACTS,
            CaseStatus.READY_FOR_POLICY,
            CaseStatus.AWAITING_DECISION,
            CaseStatus.REOPEN_REQUIRED,
            CaseStatus.WAITING,
        }:
            return case

        if case.status == CaseStatus.AUTHORIZED:
            self._plan_current_effects(case)
            executing = begin_execution(case)
            self._persist_case_transition(case, executing, "case.execution_started")
            case = executing

        effects = self.repository.list_effects(case.case_id, case.authority_epoch)
        if not effects:
            raise TransitionError("authorized onboarding case has no planned effects")

        if case.status == CaseStatus.EXECUTING:
            dispatch_state = self._drive_dispatch(case, effects)
            case = self._require_case(case_id)
            if dispatch_state == "failed":
                failed = fail_execution(case)
                self._persist_case_transition(
                    case,
                    failed,
                    "case.execution_failed",
                    {"reason": "one or more effects failed definitively"},
                )
                return failed
            if dispatch_state == "outcome_unknown":
                reconciling = begin_reconciliation(case)
                self._persist_case_transition(
                    case,
                    reconciling,
                    "case.reconciliation_started",
                    {"reason": "one or more effect outcomes are unknown or mismatched"},
                )
                case = reconciling
            else:
                verifying = begin_verification(case)
                self._persist_case_transition(case, verifying, "case.verification_started")
                case = verifying

        if case.status == CaseStatus.RECONCILING:
            result = self._verify_all(case, effects)
            if result == "mismatch":
                return self._reopen_for_mismatch(case)
            if result == "incomplete":
                return self._require_case(case_id)
            resumed = resume_verification(case)
            self._persist_case_transition(case, resumed, "case.reconciliation_resolved")
            case = resumed

        if case.status == CaseStatus.VERIFYING:
            result = self._verify_all(case, effects)
            if result == "mismatch":
                return self._reopen_for_mismatch(case)
            if result == "incomplete":
                reconciling = begin_reconciliation(case)
                self._persist_case_transition(
                    case,
                    reconciling,
                    "case.reconciliation_started",
                    {"reason": "reality read-back did not verify every effect"},
                )
                return reconciling

            outcomes = self.repository.list_outcomes(case.case_id, case.authority_epoch)
            completion = assess_onboarding_completion(effects, outcomes)
            if not completion.satisfied:
                reconciling = begin_reconciliation(case)
                self._persist_case_transition(
                    case,
                    reconciling,
                    "case.completion_blocked",
                    {
                        "requirement_id": completion.requirement_id,
                        "blocking_reasons": list(completion.blocking_reasons),
                        "missing_effect_ids": [str(item) for item in completion.missing_effect_ids],
                        "missing_outcome_kinds": list(completion.missing_outcome_kinds),
                    },
                )
                return reconciling

            completed = complete_verified_case(
                case,
                expected_effect_count=len(effects),
                verified_outcome_count=len(outcomes),
            )
            self._persist_case_transition(
                case,
                completed,
                "case.completed",
                {"completion_requirement_id": completion.requirement_id},
            )
            return completed

        return self._require_case(case_id)

    def _plan_current_effects(self, case: AdministrativeCase) -> None:
        if case.fact_snapshot is None:
            raise TransitionError("onboarding execution requires a current fact snapshot")
        evaluation = self.store.get_latest_policy_evaluation(case.case_id)
        if evaluation is None or evaluation.policy_ref != case.policy_ref:
            raise TransitionError("onboarding execution requires the current policy evaluation")

        satisfaction = AuthorityRepository(self.store).get_approval_satisfaction(
            case.case_id,
            case.authority_epoch,
        )
        decision = None
        if satisfaction is not None:
            if satisfaction.policy_ref != case.policy_ref:
                raise TransitionError("approval satisfaction policy is stale")
            required_roles = set(evaluation.required_decision_roles)
            if not required_roles.issubset(set(satisfaction.satisfied_roles)):
                raise TransitionError(
                    "approval satisfaction does not cover current required decision roles"
                )
        else:
            if get_settings().authority_enforcement_enabled:
                raise TransitionError("governed execution requires current approval satisfaction")
            decision = self.repository.get_latest_decision(case.case_id)
            if decision is None:
                raise TransitionError("onboarding execution requires an approving decision")
            if decision.disposition != DecisionDisposition.APPROVE:
                raise TransitionError("latest onboarding decision is not approving")
            if decision.authority_epoch != case.authority_epoch:
                raise TransitionError("latest onboarding decision is stale")

        unique_templates = {
            (template.target_system, template.operation, template.authority_class): template
            for template in evaluation.allowed_effects
        }
        if not unique_templates:
            raise TransitionError("current onboarding policy permits no effects")

        for key in sorted(unique_templates, key=lambda value: (value[0], value[1], value[2].value)):
            template = unique_templates[key]
            authorization_id = self._stable_id(
                "authorization",
                case,
                template.target_system,
                template.operation,
            )
            if satisfaction is not None:
                authorization = mint_execution_authorization_from_approval(
                    case,
                    satisfaction,
                    issuer_principal_id="service:administrative-orchestrator",
                    target_system=template.target_system,
                    allowed_operations=(template.operation,),
                    authority_class=template.authority_class,
                )
            else:
                assert decision is not None
                authorization = mint_execution_authorization(
                    case,
                    decision,
                    issuer_principal_id="service:administrative-orchestrator",
                    target_system=template.target_system,
                    allowed_operations=(template.operation,),
                    authority_class=template.authority_class,
                )
            authorization = authorization.model_copy(
                update={
                    "authorization_id": authorization_id,
                    "issued_at": case.updated_at,
                }
            )
            authorization = self.repository.put_authorization(authorization)
            effect_id = self._stable_id(
                "effect",
                case,
                template.target_system,
                template.operation,
            )
            effect = plan_effect(
                case,
                authorization,
                operation=template.operation,
                reversibility=self._reversibility_for(template.operation),
            ).model_copy(
                update={
                    "effect_id": effect_id,
                    "created_at": case.updated_at,
                    "updated_at": case.updated_at,
                }
            )
            self.repository.put_effect(effect)

    def _drive_dispatch(self, case: AdministrativeCase, effects) -> str:
        payload = case.fact_snapshot.facts if case.fact_snapshot else {}
        saw_unknown = False
        for planned in effects:
            effect = self.repository.get_effect(planned.effect_id) or planned
            if effect.status == EffectStatus.FAILED:
                return "failed"
            if effect.status == EffectStatus.SUCCEEDED:
                continue
            if effect.status in {EffectStatus.DISPATCHED, EffectStatus.OUTCOME_UNKNOWN}:
                observation = self.provider.observe(effect)
                verification = verify_onboarding_observation(effect, observation, payload)
                if verification.disposition == VerificationDisposition.VERIFIED:
                    self.repository.set_effect_status(
                        effect.effect_id,
                        status=EffectStatus.SUCCEEDED,
                        provider_ref=observation.provider_ref,
                    )
                    continue
                if verification.disposition == VerificationDisposition.MISMATCH:
                    self.repository.set_effect_status(
                        effect.effect_id,
                        status=EffectStatus.OUTCOME_UNKNOWN,
                        provider_ref=observation.provider_ref,
                    )
                    saw_unknown = True
                    continue
                if effect.status == EffectStatus.OUTCOME_UNKNOWN:
                    saw_unknown = True
                    continue

            self.repository.set_effect_status(effect.effect_id, status=EffectStatus.DISPATCHED)
            result = self.provider.execute(effect, payload)
            if result.status == ProviderExecutionStatus.SUCCEEDED:
                self.repository.set_effect_status(
                    effect.effect_id,
                    status=EffectStatus.SUCCEEDED,
                    provider_ref=result.provider_ref,
                )
            elif result.status == ProviderExecutionStatus.OUTCOME_UNKNOWN:
                self.repository.set_effect_status(
                    effect.effect_id,
                    status=EffectStatus.OUTCOME_UNKNOWN,
                    provider_ref=result.provider_ref,
                )
                saw_unknown = True
            else:
                self.repository.set_effect_status(
                    effect.effect_id,
                    status=EffectStatus.FAILED,
                    provider_ref=result.provider_ref,
                )
                return "failed"
        return "outcome_unknown" if saw_unknown else "succeeded"

    def _verify_all(self, case: AdministrativeCase, effects) -> str:
        incomplete = False
        facts = case.fact_snapshot.facts if case.fact_snapshot else {}
        for planned in effects:
            effect = self.repository.get_effect(planned.effect_id) or planned
            outcome_id = self._stable_id("outcome", case, str(effect.effect_id))
            existing_outcome = self.repository.get_outcome(outcome_id)
            if existing_outcome is not None:
                if (
                    existing_outcome.case_id != case.case_id
                    or existing_outcome.authority_epoch != case.authority_epoch
                    or existing_outcome.effect_id != effect.effect_id
                ):
                    raise TransitionError("persisted outcome does not match current effect authority")
                continue

            realization_id = self._stable_id("realization", case, str(effect.effect_id))
            existing_realization = self.repository.get_realization(realization_id)
            if existing_realization is not None:
                if (
                    existing_realization.effect_id != effect.effect_id
                    or existing_realization.disposition != RealizationDisposition.VERIFIED
                ):
                    raise TransitionError("persisted realization does not verify the current effect")
                self.repository.put_outcome(
                    ConfirmedOutcome(
                        outcome_id=outcome_id,
                        case_id=case.case_id,
                        case_version=effect.case_version,
                        authority_epoch=case.authority_epoch,
                        effect_id=effect.effect_id,
                        realization_assessment_id=existing_realization.assessment_id,
                        outcome_kind=f"{effect.target_system}.{effect.operation}.verified",
                        evidence=existing_realization.evidence,
                        confirmed_at=existing_realization.assessed_at,
                    )
                )
                continue

            observation = self.provider.observe(effect)
            verification = verify_onboarding_observation(effect, observation, facts)
            if verification.disposition == VerificationDisposition.MISMATCH:
                return "mismatch"
            if verification.disposition == VerificationDisposition.NOT_FOUND:
                incomplete = True
                continue

            evidence = EvidenceRef(
                evidence_id=self._stable_id("evidence", case, str(effect.effect_id)),
                source=f"reality:{effect.target_system}",
                owner=effect.target_system,
                observed_at=observation.observed_at,
                version=observation.provider_ref,
                digest=observation.digest,
                metadata={
                    "state": observation.state,
                    "semantic_verification": verification.model_dump(mode="json"),
                },
            )
            assessment = EffectRealizationAssessment(
                assessment_id=realization_id,
                effect_id=effect.effect_id,
                disposition=RealizationDisposition.VERIFIED,
                evidence=[evidence],
                assessed_at=observation.observed_at,
            )
            assessment = self.repository.put_realization(assessment, case_id=case.case_id)
            outcome = ConfirmedOutcome(
                outcome_id=outcome_id,
                case_id=case.case_id,
                case_version=effect.case_version,
                authority_epoch=case.authority_epoch,
                effect_id=effect.effect_id,
                realization_assessment_id=assessment.assessment_id,
                outcome_kind=f"{effect.target_system}.{effect.operation}.verified",
                evidence=assessment.evidence,
                confirmed_at=assessment.assessed_at,
            )
            self.repository.put_outcome(outcome)
        return "incomplete" if incomplete else "verified"

    def _reopen_for_mismatch(self, case: AdministrativeCase) -> AdministrativeCase:
        reopened_required = require_reopen(case, ReopenReason.REALITY_MISMATCH)
        self._persist_case_transition(
            case,
            reopened_required,
            "case.reopen_required",
            {"reason": ReopenReason.REALITY_MISMATCH.value},
        )
        return reopened_required

    def _persist_case_transition(
        self,
        before: AdministrativeCase,
        after: AdministrativeCase,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        self.store.update_case(
            after,
            expected_previous_version=before.version,
            event_type=event_type,
            payload=payload,
        )

    def _require_case(self, case_id: UUID) -> AdministrativeCase:
        case = self.store.get_case(case_id)
        if case is None:
            raise KeyError(f"case {case_id} not found")
        return case

    @staticmethod
    def _stable_id(kind: str, case: AdministrativeCase, *parts: str) -> UUID:
        suffix = ":".join(parts)
        return uuid5(
            NAMESPACE_URL,
            f"administrative:{kind}:{case.case_id}:{case.authority_epoch}:{suffix}",
        )

    @staticmethod
    def _reversibility_for(operation: str):
        from .domain import EffectReversibility

        if operation in {"employee.create", "identity.create", "account.provision"}:
            return EffectReversibility.CORRECTABLE
        return EffectReversibility.UNKNOWN
