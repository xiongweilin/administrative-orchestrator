# administrative-orchestrator

Durable, governed administrative automation over human requests, organizational policy, approvals, external effects, verification, and reopen.

This repository is an **administrative domain deployment**, not a second Agent runtime and not a chat bot product. It is intended to become the organization-facing layer that turns unstructured administrative requests into durable `AdministrativeCase` state and then carries bounded work through policy, authority, execution, reality verification, and exception handling.

## Product boundary

```text
employee / manager / admin / system event
                |
                v
             Request
                |
                v
      AdministrativeCase
                |
       facts + evidence
                |
                v
       policy evaluation
          /           \
     closable       insufficient
        |               |
        v               v
     Work/Decision   REOPEN_REQUIRED
        |
        v
ExecutionAuthorization
        |
        v
     typed effect
        |
        v
 external system reality
        |
        v
 read-back / reconciliation
        |
        v
  ConfirmedOutcome
        |
        v
 close / wait / reopen
```

Core separations:

```text
Request != AdministrativeCase
AI interpretation != authoritative fact
Recommendation != Decision
Decision != ExecutionAuthorization
RoleAssignment != current authority
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
Workflow completed != responsibility discharged
Exception != permission to improvise
```

`agent-kernel` remains the generic semantic/runtime authority for durable cognition, Work/Run, authorization, verification, revision, reopen, and persistent responsibility. This repository owns administrative-domain facts, organization/identity/policy interpretation, administrative workflows, business connectors, administrative effect profiles, and domain-specific completion/reconciliation rules.

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

The first executable slice is **employee onboarding** because it forces multi-actor coordination, long-lived state, identity, policy, approvals, multiple external systems, verification, and bounded completion.

## Current milestone: M0 foundation

M0 establishes:

- canonical administrative domain vocabulary;
- `AdministrativeCase` lifecycle;
- organization / principal / role / delegation primitives;
- versioned policy records;
- explicit decision and execution-authorization boundaries;
- typed effect and evidence records;
- deterministic reopen reasons;
- FastAPI service skeleton;
- tests that lock the semantic separations before external connectors are added.

External writes are not enabled in M0.

## Development principles

- AI may interpret, extract, compare, draft, and propose. It does not mint authority by itself.
- Deterministic policy handles already-closed rules; AI is not used to re-open routine cases without evidence.
- Every material persisted field has an owner and provenance.
- External effects cross typed capability boundaries.
- `outcome_unknown` is reconciled, not blindly retried.
- A case closes only against declared completion requirements and fresh evidence.
- Repeated exceptions may become policy candidates, but one successful episode never becomes universal policy automatically.

## Repository layout

```text
src/administrative_orchestrator/
    api.py              HTTP ingress and read surfaces
    domain.py           canonical administrative records
    policy.py           deterministic policy primitives
    service.py          application service / case transitions

docs/
    architecture.md
    contracts/domain-model.md
    contracts/workflow-authority.md
    milestones/M0.md
tests/
```

## Local development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
uv run uvicorn administrative_orchestrator.api:app --reload
```

Python 3.12+ is required.

## Status

The repository has just entered implementation. M0 intentionally starts with a small executable semantic core before DBOS/PostgreSQL/Feishu/Odoo/Keycloak adapters are introduced. Those integrations must consume the core distinctions rather than redefine them.
