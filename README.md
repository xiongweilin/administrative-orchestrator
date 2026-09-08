# administrative-orchestrator

Durable, governed administrative automation over authenticated requests, organizational policy, approvals, external effects, semantic reality verification, completion, reconciliation, and reopen.

This repository is the primary **administrative digital-automation reference system**. It is not a second Agent runtime and not a chatbot product. Its job is to turn organization-facing administrative requests into durable `AdministrativeCase` state and carry bounded work through facts, policy, authority, execution, reality verification, completion, and exception handling.

## Product boundary

```text
authenticated person / service / system event
                    |
                    v
                 Request
                    |
                    v
          AdministrativeCase
                    |
          facts + provenance
                    |
                    v
        persisted policy version
                    |
                    v
       deterministic evaluation
          /                 \
   routine closure       decision required
                             |
                   role / delegation check
                             |
                   Decision set / quorum
                             |
                   ApprovalSatisfaction
                             |
                   ExecutionAuthorization
                             |
                        typed effect
                             |
                             v
                  external system reality
                             |
                 semantic read-back / reconcile
                             |
                             v
                    ConfirmedOutcome
                             |
                    completion contract
                             |
                             v
                    close / wait / reopen
```

Core separations:

```text
Request != AdministrativeCase
AI interpretation != authoritative fact
Historical role assignment != current authority
Recommendation != Decision
One Decision != multi-party approval satisfaction
ApprovalSatisfaction != ExecutionAuthorization
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
Object existence != semantic postcondition satisfaction
Workflow completed != responsibility discharged
Exception != permission to improvise
```

`agent-kernel` remains the generic semantic/runtime authority for open cognition, Work/Run, verification/revision, reopen, and persistent responsibility. This repository owns administrative-domain facts, organization/identity/policy interpretation, deterministic administrative workflows, business connectors, administrative effect profiles, completion contracts, and domain-specific reconciliation.

DBOS is deliberately confined to the durable orchestration boundary. `AdministrativeCase` remains the business state machine and source of current administrative workflow truth.

## Initial system scope

The initial system is deliberately broad enough to validate a complete administrative operating model rather than one isolated Agent demo.

Planned vertical slices:

1. employee onboarding / offboarding;
2. leave request;
3. expense reimbursement;
4. access request;
5. procurement request;
6. document / contract approval;
7. invoice / AP preparation;
8. general administrative scheduling and resource requests.

The first executable slice is **employee onboarding** because it forces multi-actor coordination, long-lived state, identity, policy, approvals, multiple external systems, semantic verification, and bounded completion.

## Current milestone: M2 organizational authority and policy

M0 semantic foundation is complete. M1 durable governed execution is implemented for the onboarding reference slice. The repository is now in M2, where organizational identity, authority, approval satisfaction, and persisted policy become first-class runtime facts.

The current onboarding reference slice includes:

- PostgreSQL persistence with Alembic migrations;
- transactional case/policy/decision transitions and durable outbox wake-up;
- DBOS durable wait/replay and worker restart recovery;
- deterministic effect and authorization identifiers for replay safety;
- authoritative HTTP sandbox with provider-side effect idempotency;
- `outcome_unknown` reconciliation without blind retry;
- semantic postcondition verification rather than identity-only read-back;
- explicit completion assessment before case closure;
- immutable `FactSnapshot` history while the case points to current facts;
- durable ingress receipts keyed by `source_event_id`;
- authenticated principals, external identity bindings, roles, scoped delegation, and time validity;
- policy-declared required decision roles and separation-of-duties constraints;
- persisted multi-party `ApprovalSatisfaction` as the authority basis for governed execution;
- persisted, versioned Policy Plane records compiled into deterministic onboarding evaluation;
- audit, decision, authorization, effect, realization, outcome, completion, fact-history, and dead-letter inspection surfaces;
- full Docker Compose HTTP E2E for standard and privileged onboarding;
- CI coverage for lint/tests, migration round trips, PostgreSQL/DBOS restart recovery, and full Compose E2E.

The reference deployment uses development authentication only to make the full-stack E2E reproducible. The default runtime authentication mode is fail-closed JWT; production identity integration must bind external subjects to current organizational principals rather than accept caller-supplied principal identity.

## Development principles

- AI may interpret, extract, compare, investigate, draft, and propose. It does not mint organizational authority by itself.
- Deterministic policy handles already-closed rules; AI is not used to reopen routine cases without evidence.
- Authentication answers who is calling; authority answers what that principal may decide now.
- Every authority-sensitive decision is bound to the current case version, authority epoch, policy version, role, and organization scope.
- Multi-party policy requirements are satisfied by an explicit durable approval object, not by selecting one convenient Decision.
- Every material persisted fact has an owner and provenance; current facts never erase historical fact snapshots.
- External effects cross typed capability boundaries.
- `outcome_unknown` is reconciled, not blindly retried.
- Verification proves declared postconditions against fresh external reality; HTTP success is not business completion.
- A case closes only against an explicit completion contract and confirmed outcomes.
- Repeated exceptions may become policy candidates, but one successful episode never becomes universal policy automatically.
- Domain-specific semantics stay here; generic cognition/runtime semantics stay in `agent-kernel`.

## Repository layout

```text
src/administrative_orchestrator/
    api.py                  authenticated HTTP ingress / inspection surfaces
    auth.py                 authentication boundary
    authority.py            principals, roles, delegation, approval satisfaction
    policy.py               deterministic administrative policy evaluator
    policy_plane.py         persisted policy versions / current-policy resolution
    domain.py               canonical administrative records
    service.py              pure case / authorization transitions
    unit_of_work.py         atomic persistence + outbox boundary
    onboarding_execution.py recoverable onboarding execution state machine
    verification.py         domain semantic postcondition verification
    completion.py           domain completion contract
    fact_history.py         immutable fact lineage
    ingress.py              durable source-event idempotency
    messaging.py            transactional outbox / retry / dead-letter
    workflows/              DBOS durability boundary

docs/
    architecture.md
    contracts/
    milestones/M0.md
    milestones/M2.md
tests/
```

## Local development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
```

For the complete reference topology:

```bash
docker compose up -d --build
python scripts/e2e_compose.py
docker compose down -v --remove-orphans
```

Python 3.12+ is required.

## Near-term direction

The immediate objective is not to multiply domain orchestrators. It is to make this administrative reference system trustworthy enough to carry real organizational responsibility. The next work should deepen real identity/organization integration, production Policy Plane operations, real HRIS/IAM/communication connectors, exception operations, and additional administrative slices while preserving the existing authority/reality distinctions.

Natural-language and Agent-based intake should sit above this governed execution core. They may improve interpretation and investigation, but they must consume rather than bypass the same fact, policy, authority, effect, verification, and completion contracts.
