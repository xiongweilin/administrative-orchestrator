from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .completion import CompletionAssessment, assess_administrative_completion
from .domain import AdministrativeCase, CaseStatus
from .execution_repository import ExecutionRepository
from .integrations.kernel.bridge import KernelExecutionBridge
from .integrations.kernel.client import (
    KernelResponsibilityDischargeError,
)
from .integrations.kernel.compatibility import KernelCompatibilityError
from .integrations.kernel.models import KernelProjectionStatus
from .obligations import (
    ObligationFulfillmentKind,
    ObligationRepository,
)
from .persistence import SqlStore


class ResponsibilityDischargeStatus(StrEnum):
    PENDING = "pending"
    DISCHARGED = "discharged"


class ResponsibilityDischargeBlocked(RuntimeError):
    """Structural discharge invariant failure; no Kernel mutation is attempted."""


@dataclass(frozen=True, slots=True)
class ResponsibilityHandle:
    responsibility_ref: str
    responsibility_version: int
    obligation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ResponsibilityDischargeResult:
    status: ResponsibilityDischargeStatus
    responsibility_refs: tuple[str, ...]
    discharged_refs: tuple[str, ...]
    assessment_refs: tuple[tuple[str, str], ...]
    decision_refs: tuple[tuple[str, str], ...]
    transition_refs: tuple[tuple[str, str], ...]
    completion: CompletionAssessment
    blocker: str | None = None


class AdministrativeResponsibilityDischargeService:
    """Discharge every Kernel responsibility owned by one completed case.

    This service is intentionally separate from effect execution. It consumes
    persisted Administrative completion evidence and only calls Kernel's
    assessment, decision, transition, and status contracts. It never invokes
    an effect provider or creates a new effect/grant.
    """

    def __init__(self, store: SqlStore, bridge: KernelExecutionBridge) -> None:
        self.store = store
        self.bridge = bridge
        self.obligations = ObligationRepository(store)
        self.execution = ExecutionRepository(store)

    def project_responsibility_set(
        self,
        case: AdministrativeCase,
        obligation_set,
    ) -> tuple[ResponsibilityHandle, ...]:
        """Build the deterministic set without calling or mutating Kernel."""
        return self._project_responsibility_set(case, obligation_set)

    @staticmethod
    def discharge_chain_refs(
        case: AdministrativeCase,
        handle: ResponsibilityHandle,
    ) -> tuple[str, str, str]:
        """Return deterministic assessment, decision, and transition identities."""
        return AdministrativeResponsibilityDischargeService._discharge_refs(case, handle)

    def discharge(self, case: AdministrativeCase) -> ResponsibilityDischargeResult:
        obligation_set = self.obligations.get_current(case.case_id, case.authority_epoch)
        if obligation_set is None:
            return self._blocked(
                "missing_current_obligation_set",
                responsibility_refs=(),
                completion=self._unsatisfied_completion("missing_current_obligation_set"),
            )

        effects = self.execution.list_effects(case.case_id, case.authority_epoch)
        outcomes = self.execution.list_outcomes(case.case_id, case.authority_epoch)
        links = self.obligations.list_links(case.case_id, case.authority_epoch)
        fulfillments = self.obligations.list_domain_state_fulfillments(
            case.case_id, case.authority_epoch
        )
        completion = assess_administrative_completion(
            obligation_set,
            effects,
            outcomes,
            links=links,
            fulfillments=fulfillments,
        )
        if case.status is not CaseStatus.COMPLETED:
            return self._blocked(
                "case_not_completed",
                responsibility_refs=(),
                completion=completion,
            )
        if not completion.satisfied:
            return self._blocked(
                "completion_assessment_not_satisfied",
                responsibility_refs=(),
                completion=completion,
            )

        if not self.bridge.cutover:
            return self._blocked(
                "kernel_cutover_required",
                responsibility_refs=(),
                completion=completion,
            )

        try:
            handles = self._project_responsibility_set(case, obligation_set)
        except ResponsibilityDischargeBlocked as exc:
            return self._blocked(
                str(exc),
                responsibility_refs=(),
                completion=completion,
            )

        responsibility_refs = tuple(item.responsibility_ref for item in handles)
        if not handles:
            return ResponsibilityDischargeResult(
                status=ResponsibilityDischargeStatus.DISCHARGED,
                responsibility_refs=(),
                discharged_refs=(),
                assessment_refs=(),
                decision_refs=(),
                transition_refs=(),
                completion=completion,
            )

        try:
            self.bridge.compatibility()
        except KernelCompatibilityError as exc:
            return self._blocked(
                f"kernel_compatibility_unavailable:{type(exc).__name__}",
                responsibility_refs=responsibility_refs,
                completion=completion,
            )

        return self._drive_kernel_discharge(
            case,
            handles,
            completion,
            effects=effects,
            outcomes=outcomes,
            links=links,
            fulfillments=fulfillments,
        )

    def _drive_kernel_discharge(
        self,
        case: AdministrativeCase,
        handles: tuple[ResponsibilityHandle, ...],
        completion: CompletionAssessment,
        *,
        effects: list[Any],
        outcomes: list[Any],
        links: list[Any],
        fulfillments: list[Any],
    ) -> ResponsibilityDischargeResult:
        client = self.bridge.client()
        responsibility_refs = tuple(item.responsibility_ref for item in handles)
        discharged: list[str] = []
        assessment_refs: list[tuple[str, str]] = []
        decision_refs: list[tuple[str, str]] = []
        transition_refs: list[tuple[str, str]] = []

        for handle in handles:
            try:
                status = client.get_responsibility_status(
                    handle.responsibility_ref,
                    expected_version=handle.responsibility_version,
                )
                if status.current_status == "discharged":
                    discharged.append(handle.responsibility_ref)
                    continue
                if status.current_status != "active":
                    return self._pending_result(
                        "responsibility_not_active",
                        responsibility_refs,
                        discharged,
                        assessment_refs,
                        decision_refs,
                        transition_refs,
                        completion,
                    )

                assessment_ref, decision_ref, transition_ref = self._discharge_refs(
                    case, handle
                )
                basis_refs = self._basis_refs(
                    case,
                    handle,
                    completion,
                    effects=effects,
                    outcomes=outcomes,
                    links=links,
                    fulfillments=fulfillments,
                )
                assessment_at = case.updated_at
                assessment = client.record_assessment(
                    assessment_ref=assessment_ref,
                    responsibility_ref=handle.responsibility_ref,
                    responsibility_version=handle.responsibility_version,
                    subject_ref=case.subject_ref,
                    assessment_kind="administrative-responsibility-discharge-reassessment",
                    basis_refs=basis_refs,
                    assessed_at=assessment_at,
                    fresh_until=None,
                    rationale=(
                        "Administrative CompletionAssessment is satisfied and all required "
                        "outcomes and domain fulfillments are verified."
                    ),
                    created_at=assessment_at,
                )
                assessment_refs.append((handle.responsibility_ref, assessment.assessment_ref))

                after_assessment = client.get_responsibility_status(
                    handle.responsibility_ref,
                    expected_version=handle.responsibility_version,
                )
                if after_assessment.current_status != "active":
                    return self._pending_result(
                        "assessment_did_not_leave_responsibility_active",
                        responsibility_refs,
                        discharged,
                        assessment_refs,
                        decision_refs,
                        transition_refs,
                        completion,
                    )

                decision = client.record_discharge_decision(
                    decision_ref=decision_ref,
                    responsibility_ref=handle.responsibility_ref,
                    responsibility_version=handle.responsibility_version,
                    assessment_ref=assessment.assessment_ref,
                    basis_refs=(assessment.assessment_ref, *basis_refs),
                    policy_ref=self._policy_ref(case),
                    decided_at=assessment_at + timedelta(seconds=1),
                    rationale="Fresh completion assessment supports explicit discharge judgment.",
                    created_at=assessment_at + timedelta(seconds=1),
                )
                decision_refs.append((handle.responsibility_ref, decision.decision_ref))

                after_decision = client.get_responsibility_status(
                    handle.responsibility_ref,
                    expected_version=handle.responsibility_version,
                )
                if after_decision.current_status != "active":
                    return self._pending_result(
                        "decision_did_not_leave_responsibility_active",
                        responsibility_refs,
                        discharged,
                        assessment_refs,
                        decision_refs,
                        transition_refs,
                        completion,
                    )

                transition = client.apply_lifecycle_transition(
                    transition_ref=transition_ref,
                    responsibility_ref=handle.responsibility_ref,
                    responsibility_version=handle.responsibility_version,
                    decision_ref=decision.decision_ref,
                    basis_refs=(decision.decision_ref, assessment.assessment_ref),
                    applied_at=assessment_at + timedelta(seconds=2),
                    reason="Administrative responsibility is explicitly discharged after verified completion.",
                    created_at=assessment_at + timedelta(seconds=2),
                )
                transition_refs.append((handle.responsibility_ref, transition.transition_ref))

                final_status = client.get_responsibility_status(
                    handle.responsibility_ref,
                    expected_version=handle.responsibility_version,
                )
                if final_status.current_status != "discharged":
                    return self._pending_result(
                        "transition_did_not_confirm_discharge",
                        responsibility_refs,
                        discharged,
                        assessment_refs,
                        decision_refs,
                        transition_refs,
                        completion,
                    )
                discharged.append(handle.responsibility_ref)
            except (KernelResponsibilityDischargeError, ResponsibilityDischargeBlocked) as exc:
                return self._pending_result(
                    (
                        str(exc)
                        if isinstance(exc, ResponsibilityDischargeBlocked)
                        else f"kernel_discharge_unavailable:{type(exc).__name__}"
                    ),
                    responsibility_refs,
                    discharged,
                    assessment_refs,
                    decision_refs,
                    transition_refs,
                    completion,
                )

        return ResponsibilityDischargeResult(
            status=ResponsibilityDischargeStatus.DISCHARGED,
            responsibility_refs=responsibility_refs,
            discharged_refs=tuple(discharged),
            assessment_refs=tuple(assessment_refs),
            decision_refs=tuple(decision_refs),
            transition_refs=tuple(transition_refs),
            completion=completion,
        )

    def _project_responsibility_set(
        self,
        case: AdministrativeCase,
        obligation_set,
    ) -> tuple[ResponsibilityHandle, ...]:
        projections = self.bridge.repository.list_projections_for_case(case.case_id)
        current_external = tuple(
            item
            for item in obligation_set.obligations
            if item.required
            and item.fulfillment_kind is ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED
        )
        current_matches: dict[UUID, list[Any]] = {item.obligation_id: [] for item in current_external}
        by_ref: dict[str, tuple[int, set[UUID]]] = {}

        for projection in projections:
            if projection.status is KernelProjectionStatus.SHADOW:
                raise ResponsibilityDischargeBlocked("kernel_projection_missing_responsibility_ref")
            responsibility_ref = projection.kernel_responsibility_ref
            if not isinstance(responsibility_ref, str) or not responsibility_ref:
                raise ResponsibilityDischargeBlocked("kernel_projection_missing_responsibility_ref")
            version = projection.admission_payload.get("responsibility_version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise ResponsibilityDischargeBlocked("kernel_projection_missing_responsibility_version")
            if (
                projection.kernel_execution_responsibility_ref is not None
                and projection.kernel_execution_responsibility_ref != responsibility_ref
            ):
                raise ResponsibilityDischargeBlocked("kernel_execution_responsibility_identity_rebound")
            if projection.authority_epoch == case.authority_epoch:
                current_matches.setdefault(projection.obligation_id, []).append(projection)
            existing = by_ref.get(responsibility_ref)
            if existing is None:
                by_ref[responsibility_ref] = (version, {projection.obligation_id})
            elif existing[0] != version:
                raise ResponsibilityDischargeBlocked("responsibility_version_rebound")
            else:
                existing[1].add(projection.obligation_id)

        for obligation in current_external:
            matches = current_matches.get(obligation.obligation_id, [])
            if len(matches) != 1:
                raise ResponsibilityDischargeBlocked("missing_or_duplicate_current_kernel_projection")
            projection = matches[0]
            if (
                projection.status is not KernelProjectionStatus.CUTOVER
                or projection.kernel_execution_status is None
                or projection.kernel_execution_status.value != "completed"
            ):
                raise ResponsibilityDischargeBlocked("current_external_responsibility_not_completed")

        handles = tuple(
            ResponsibilityHandle(
                responsibility_ref=responsibility_ref,
                responsibility_version=version,
                obligation_ids=tuple(sorted(obligation_ids, key=str)),
            )
            for responsibility_ref, (version, obligation_ids) in sorted(by_ref.items())
        )
        return handles

    @staticmethod
    def _discharge_refs(
        case: AdministrativeCase,
        handle: ResponsibilityHandle,
    ) -> tuple[str, str, str]:
        prefix = (
            f"{case.case_id}:{case.version}:{case.authority_epoch}:"
            f"{handle.responsibility_ref}:{handle.responsibility_version}"
        )
        return (
            f"assessment_admin_discharge_{uuid5(NAMESPACE_URL, f'assessment:{prefix}').hex}",
            f"decision_admin_discharge_{uuid5(NAMESPACE_URL, f'decision:{prefix}').hex}",
            f"transition_admin_discharge_{uuid5(NAMESPACE_URL, f'transition:{prefix}').hex}",
        )

    def _basis_refs(
        self,
        case: AdministrativeCase,
        handle: ResponsibilityHandle,
        completion: CompletionAssessment,
        *,
        effects: list[Any],
        outcomes: list[Any],
        links: list[Any],
        fulfillments: list[Any],
    ) -> tuple[str, ...]:
        refs = {
            f"administrative-case:{case.case_id}:version:{case.version}:epoch:{case.authority_epoch}",
            f"completion-assessment:{completion.requirement_id}",
            f"responsibility:{handle.responsibility_ref}:version:{handle.responsibility_version}",
            self._policy_ref(case),
        }
        for obligation_id in handle.obligation_ids:
            refs.add(f"administrative-obligation:{obligation_id}")
        effect_by_id = {item.effect_id: item for item in effects}
        for link in links:
            if link.obligation_id in handle.obligation_ids and link.effect_id in effect_by_id:
                refs.add(f"administrative-effect:{link.effect_id}")
        for outcome in outcomes:
            if outcome.effect_id in effect_by_id:
                refs.add(f"confirmed-outcome:{outcome.outcome_id}")
        for fulfillment in fulfillments:
            if fulfillment.obligation_id in handle.obligation_ids:
                refs.add(f"domain-fulfillment:{fulfillment.fulfillment_id}")
        return tuple(sorted(refs))

    @staticmethod
    def _policy_ref(case: AdministrativeCase) -> str:
        if case.policy_ref is None:
            raise ResponsibilityDischargeBlocked("missing_current_policy")
        return f"policy:{case.policy_ref.policy_id}:{case.policy_ref.version}"

    @staticmethod
    def _unsatisfied_completion(reason: str) -> CompletionAssessment:
        return CompletionAssessment(
            requirement_id=f"blocked:{reason}",
            satisfied=False,
            blocking_reasons=(reason,),
        )

    @staticmethod
    def _blocked(
        blocker: str,
        *,
        responsibility_refs: tuple[str, ...],
        completion: CompletionAssessment,
    ) -> ResponsibilityDischargeResult:
        return ResponsibilityDischargeResult(
            status=ResponsibilityDischargeStatus.PENDING,
            responsibility_refs=responsibility_refs,
            discharged_refs=(),
            assessment_refs=(),
            decision_refs=(),
            transition_refs=(),
            completion=completion,
            blocker=blocker,
        )

    @staticmethod
    def _pending_result(
        blocker: str,
        responsibility_refs: tuple[str, ...],
        discharged: list[str],
        assessment_refs: list[tuple[str, str]],
        decision_refs: list[tuple[str, str]],
        transition_refs: list[tuple[str, str]],
        completion: CompletionAssessment,
    ) -> ResponsibilityDischargeResult:
        return ResponsibilityDischargeResult(
            status=ResponsibilityDischargeStatus.PENDING,
            responsibility_refs=responsibility_refs,
            discharged_refs=tuple(discharged),
            assessment_refs=tuple(assessment_refs),
            decision_refs=tuple(decision_refs),
            transition_refs=tuple(transition_refs),
            completion=completion,
            blocker=blocker,
        )


__all__ = [
    "AdministrativeResponsibilityDischargeService",
    "ResponsibilityDischargeBlocked",
    "ResponsibilityDischargeResult",
    "ResponsibilityDischargeStatus",
    "ResponsibilityHandle",
]
