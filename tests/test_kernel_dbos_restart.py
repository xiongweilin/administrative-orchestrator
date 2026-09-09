from __future__ import annotations

import os
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
import pytest
from sqlalchemy import create_engine

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import (
    AdministrativeRequest,
    CaseStatus,
    Decision,
    DecisionDisposition,
    FactSnapshot,
    PolicyRef,
)
from administrative_orchestrator.effect_provider import (
    ProviderExecutionResult,
    ProviderExecutionStatus,
    RealityObservation,
)
from administrative_orchestrator.execution_repository import ExecutionRepository
from administrative_orchestrator.integrations.kernel.models import (
    KernelExecutionStatus,
    KernelProjectionStatus,
)
from administrative_orchestrator.messaging import claim_outbox, mark_dispatched
from administrative_orchestrator.obligations import ObligationRepository
from administrative_orchestrator.persistence import Base, SqlStore
from administrative_orchestrator.policy import OnboardingFacts, OnboardingPolicy
from administrative_orchestrator.service import (
    apply_policy_evaluation,
    create_case,
    record_decision,
    start_policy_evaluation,
)
from administrative_orchestrator.unit_of_work import AdministrativeUnitOfWork
from administrative_orchestrator.workflows.protocol import CASE_CHANGED_TOPIC
from administrative_orchestrator.workflows.relay import (
    execute_outbox_action,
    plan_outbox_action,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ADMIN_RUN_DBOS_INTEGRATION") != "1",
    reason="set ADMIN_RUN_DBOS_INTEGRATION=1 to run PostgreSQL/DBOS integration",
)

PG_ADMIN_URL = os.getenv(
    "ADMIN_TEST_PG_ADMIN_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/postgres",
)


@dataclass
class KernelReceiptState:
    case_id: UUID | None = None
    authority_epoch: int = 0
    receipts_completed: bool = False


class TrackingFallbackProvider:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.observe_calls = 0
        self.realized: dict[UUID, dict[str, object]] = {}

    def execute(self, effect, payload):
        self.execute_calls += 1
        self.realized[effect.effect_id] = dict(payload)
        return ProviderExecutionResult(
            status=ProviderExecutionStatus.SUCCEEDED,
            provider_ref=f"legacy:{effect.effect_id}",
        )

    def observe(self, effect):
        self.observe_calls += 1
        payload = self.realized.get(effect.effect_id)
        if payload is None:
            return RealityObservation(
                found=False,
                target_system=effect.target_system,
                operation=effect.operation,
                subject_ref=effect.subject_ref,
            )
        return RealityObservation(
            found=True,
            target_system=effect.target_system,
            operation=effect.operation,
            subject_ref=effect.subject_ref,
            provider_ref=f"legacy:{effect.effect_id}",
            state={"active": True, "payload": payload},
            digest=f"legacy-digest:{effect.effect_id}",
        )


class RestartKernelRepository:
    def __init__(self, store: SqlStore, state: KernelReceiptState) -> None:
        self.store = store
        self.state = state

    def _obligation_set(self):
        if self.state.case_id is None:
            return None
        return ObligationRepository(self.store).get_current(
            self.state.case_id,
            self.state.authority_epoch,
        )

    def _obligation(self, obligation_id: UUID):
        obligation_set = self._obligation_set()
        if obligation_set is None:
            return None
        return next(
            (item for item in obligation_set.obligations if item.obligation_id == obligation_id),
            None,
        )

    @staticmethod
    def _intent_id(obligation_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"kernel-restart:intent:{obligation_id}")

    def get_projection_for_obligation(self, obligation_id: UUID):
        obligation = self._obligation(obligation_id)
        if obligation is None or obligation.target_system not in {"hris", "iam"}:
            return None
        if not self.state.receipts_completed:
            return None
        target = obligation.target_system
        return SimpleNamespace(
            obligation_id=obligation_id,
            intent_id=self._intent_id(obligation_id),
            status=KernelProjectionStatus.CUTOVER,
            kernel_execution_status=KernelExecutionStatus.COMPLETED,
            kernel_execution_ref=f"execution:restart:{target}",
            kernel_provider_id=f"provider:restart:{target}",
            kernel_execution_processed_at=datetime.now(UTC),
            kernel_evidence_ref=f"evidence:restart:{target}",
        )

    def get_intent(self, intent_id: UUID):
        obligation_set = self._obligation_set()
        if obligation_set is None:
            return None
        for obligation in obligation_set.obligations:
            if self._intent_id(obligation.obligation_id) == intent_id:
                return SimpleNamespace(
                    intent_id=intent_id,
                    expected_postcondition=dict(obligation.expected_postcondition),
                )
        return None


class RestartKernelBridge:
    enabled = True
    cutover = True

    def __init__(self, store: SqlStore, state: KernelReceiptState) -> None:
        self.repository = RestartKernelRepository(store, state)

    def prepare(self, *args, **kwargs):
        del args, kwargs
        return None


def _create_database(name: str) -> None:
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')


def _drop_database(name: str) -> None:
    with psycopg.connect(PG_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _wait_until(predicate, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition did not become true before timeout")


def _relay_all(store: SqlStore) -> int:
    events = claim_outbox(store, batch=50, lease_seconds=30)
    for event in events:
        execute_outbox_action(plan_outbox_action(event))
        mark_dispatched(store, event.event_id)
    return len(events)


def test_kernel_owned_effects_survive_dbos_restart_without_legacy_fallback(monkeypatch) -> None:
    from dbos import DBOS, DBOSConfig

    token = secrets.token_hex(4)
    app_db = f"admin_kernel_restart_app_{token}"
    sys_db = f"admin_kernel_restart_sys_{token}"
    _create_database(app_db)
    _create_database(sys_db)
    app_url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{app_db}"
    sys_url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{sys_db}"
    app_engine = create_engine(app_url, pool_pre_ping=True)
    Base.metadata.create_all(app_engine)
    fallback = TrackingFallbackProvider()
    kernel_state = KernelReceiptState()

    monkeypatch.setenv("ADMIN_DATABASE_URL", app_url)
    monkeypatch.setenv("ADMIN_WORKER_DATABASE_URL", app_url)
    monkeypatch.setenv("ADMIN_DBOS_SYSTEM_DATABASE_URL", sys_url)
    monkeypatch.setenv("ADMIN_EXTERNAL_EFFECTS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_KERNEL_BRIDGE_MODE", "cutover")
    get_settings.cache_clear()

    config = DBOSConfig(
        name="admin-kernel-restart-test",
        system_database_url=sys_url,
        application_database_url=app_url,
        log_level="WARNING",
        dbos_system_schema="dbos",
    )

    try:
        DBOS(config=config)
        from administrative_orchestrator.workflows import definitions

        monkeypatch.setattr(definitions, "HttpEffectProvider", lambda *args, **kwargs: fallback)
        monkeypatch.setattr(
            definitions,
            "KernelExecutionBridge",
            lambda store, settings=None: RestartKernelBridge(store, kernel_state),
        )
        # Physical cutover durability is under test here. Proposal/admission
        # semantics are covered by the cross-repo Kernel lane and are kept out
        # of this focused restart fixture.
        monkeypatch.setattr(
            definitions,
            "prepare_onboarding_kernel_shadow",
            lambda *args, **kwargs: [],
        )
        DBOS.launch()

        store = SqlStore(app_url)
        uow = AdministrativeUnitOfWork(store)
        facts = OnboardingFacts(
            employee_ref="employee:kernel-restart",
            department_ref="department:engineering",
            manager_principal_id="person:manager",
            start_date="2026-09-15",
            employment_type="full-time",
        )
        request = AdministrativeRequest(
            requester_principal_id="person:requester",
            channel="integration-test",
            intent="onboard employee:kernel-restart",
        )
        original = create_case(
            request,
            case_kind="employee-onboarding",
            subject_ref=facts.employee_ref,
            fact_snapshot=FactSnapshot(
                source="integration-test",
                owner="integration-test",
                facts=facts.model_dump(mode="json"),
            ),
        )
        uow.create_case(request, original)
        ready = start_policy_evaluation(original)
        policy_ref = PolicyRef(
            policy_id="employee-onboarding",
            version="v0.1",
            owner="integration-test",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        )
        evaluation = OnboardingPolicy(policy_ref).evaluate(facts)
        awaiting = apply_policy_evaluation(ready, evaluation)
        uow.apply_policy_transition(original, awaiting, evaluation)

        assert _relay_all(store) == 1
        _wait_until(lambda: DBOS.get_workflow_status(str(awaiting.case_id)) is not None)

        current = store.get_case(awaiting.case_id)
        assert current is not None
        decision = Decision(
            case_id=current.case_id,
            case_version=current.version,
            authority_epoch=current.authority_epoch,
            principal_id="person:hr-approver",
            disposition=DecisionDisposition.APPROVE,
            rationale="integration approval",
            policy_ref=policy_ref,
        )
        authorized = record_decision(current, decision)
        uow.apply_decision_transition(current, authorized, decision)
        kernel_state.case_id = authorized.case_id
        kernel_state.authority_epoch = authorized.authority_epoch

        assert _relay_all(store) == 1
        _wait_until(
            lambda: (store.get_case(authorized.case_id) or authorized).status
            == CaseStatus.RECONCILING,
            timeout=60,
        )

        partial = store.get_case(authorized.case_id)
        assert partial is not None
        effects = ExecutionRepository(store).list_effects(
            partial.case_id,
            partial.authority_epoch,
        )
        assert len(effects) == 2
        links = {
            link.effect_id: link
            for link in ObligationRepository(store).list_links(
                partial.case_id,
                partial.authority_epoch,
            )
        }
        assert set(links) == {effect.effect_id for effect in effects}
        for effect in effects:
            link = links[effect.effect_id]
            assert effect.obligation_id == link.obligation_id
            assert effect.governance_basis_id == link.governance_basis_id
        assert fallback.execute_calls == 0
        assert fallback.observe_calls == 0

        DBOS.destroy()
        kernel_state.receipts_completed = True
        DBOS(config=config)
        DBOS.launch()
        DBOS.resume_workflows([str(authorized.case_id)])
        DBOS.send(
            destination_id=str(authorized.case_id),
            topic=CASE_CHANGED_TOPIC,
            message={"reason": "kernel_receipts_completed_after_restart"},
            idempotency_key=f"kernel-restart-{token}",
        )

        _wait_until(
            lambda: (store.get_case(authorized.case_id) or authorized).status
            == CaseStatus.COMPLETED,
            timeout=60,
        )

        completed = store.get_case(authorized.case_id)
        assert completed is not None
        completed_effects = ExecutionRepository(store).list_effects(
            completed.case_id,
            completed.authority_epoch,
        )
        completed_links = {
            link.effect_id: link
            for link in ObligationRepository(store).list_links(
                completed.case_id,
                completed.authority_epoch,
            )
        }
        for effect in completed_effects:
            link = completed_links[effect.effect_id]
            assert effect.obligation_id == link.obligation_id
            assert effect.governance_basis_id == link.governance_basis_id

        outcomes = ExecutionRepository(store).list_outcomes(
            completed.case_id,
            completed.authority_epoch,
        )
        assert {item.outcome_kind for item in outcomes} == {
            "hris.employee.create.verified",
            "iam.identity.create.verified",
        }
        assert fallback.execute_calls == 0
        assert fallback.observe_calls == 0
    finally:
        with suppress(Exception):
            DBOS.destroy()
        get_settings.cache_clear()
        app_engine.dispose()
        _drop_database(app_db)
        _drop_database(sys_db)
