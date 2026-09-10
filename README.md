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
                   AdministrativeExecutionGrant
                             |
                    bounded effect intent
                             |
                             v
                       Agent Kernel
                 Work / runtime authority
                 physical RealityBoundary
                             |
                  external system reality
                             |
                Kernel verification/recovery
                             |
                    domain semantic readback
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
External identity != Administrative authority
Historical role assignment != current authority
Recommendation != Decision
One Decision != multi-party approval satisfaction
ApprovalSatisfaction != AdministrativeExecutionGrant
AdministrativeExecutionGrant != Kernel runtime authorization
Administrative obligation != Kernel Work
Kernel evidence != Administrative ConfirmedOutcome
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
execution-unknown != retry permission
Object existence != semantic postcondition satisfaction
Workflow completed != responsibility discharged
Exception != permission to improvise
```

`agent-kernel` remains the generic semantic/runtime authority for persistent responsibility, Work/Run/Attempt, runtime authorization, the unique physical `RealityBoundary`, execution verification/recovery, and generic Outcome/revision semantics. This repository owns administrative-domain facts, organization/identity/policy interpretation, deterministic administrative workflows, business integration contracts, administrative obligations/effect intents, semantic completion, and exception operations.

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

## Current milestone: M6 Trusted Perception & Admission

M0–M4 established the semantic foundation, durable governed execution, organizational authority/policy, administrative correctness, and Agent Kernel convergence/cut-over invariants. M5 makes that reference architecture production-shaped without collapsing those ownership boundaries.

The M5 implementation now includes:

- production OIDC discovery/JWKS asymmetric verification with HTTPS issuer and `RS256`/`ES256` fail-closed constraints;
- durable external identity binding history, explicit revocation/rebind/deactivation lifecycle, and separation of IdP identity from Administrative authority;
- field-level `FactAssertion` authority/provenance so authoritative HRIS observations cannot promote request-only claims;
- typed Odoo HRIS and Keycloak identity authoritative readers;
- live authoritative HRIS revalidation before governed reality transitions, with `GOVERNANCE_STALE` reopen on changed/stale truth;
- Odoo/Keycloak production writer and durable request-identity reconciliation contracts;
- independent verifier identities and semantic readback rather than provider-success completion;
- authority-safe Operations API and OIDC Operations Console with no force-complete, mark-success, evidence override, Kernel authorization, or provider-retry shortcuts;
- low-cardinality Prometheus metrics, structured correlation IDs, and observed API wrappers;
- production configuration preflight that rejects non-cutover, SQLite Administrative/DBOS stores, schema auto-create, unpinned Kernel revisions, insecure provider endpoints, and shared writer/verifier identities;
- a production Agent Kernel factory using the supported bounded-domain-effect recovery store and separate writer/verifier credentials;
- online Agent Kernel SQLite backup/verify/restore using SQLite backup semantics, integrity checks, atomic publication, and SHA-256 manifests;
- PostgreSQL `pg_dump -> destroy -> pg_restore -> semantic verification` DR CI;
- Operations Console TypeScript typecheck and production build gate;
- a pinned Agent Kernel production-baseline cutover lane plus the existing `agent-kernel/main` recovery canary;
- SonarQube Cloud scan and new-code Quality Gate acceptance.

The supported Agent Kernel revision is currently:

```text
fe4b3f4bf2e376bd7105caf7d15d77e2483c7197
```

M5 has an explicit acceptance boundary: repository CI can prove code, migration, restart, cut-over, DR, ambiguity semantics, and static/security quality gates, while the external checklist proves enterprise OIDC/Odoo/Keycloak credentials and network behavior. The isolated real-staging checklist, final exact-head CI, squash merge, and post-merge main CI now pass on the supported Kernel revision `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197`; M5 is **complete for the recorded scope**.

M6 is the upstream **Trusted Perception & Admission** milestone. The current
implementation includes the Administrative Intake Plane contract and durable
core, the Feishu metadata-only durable ingress and asynchronous pipeline, the
Operations review surface with the explicit human-confirmed
`bridge_to_m5` onboarding path, and the content-addressed `ArtifactStore`
foundation wired to Feishu canonical file/image attachments. The production
Compose worker now mounts the named artifact volume and receives the optional
Feishu/model runtime references. The bridge preserves admitted intake facts as
`CLAIM`; it does not turn a candidate or a human confirmation into
`AUTHORITATIVE` truth. The authoritative refresh/revalidation path remains
owned by the existing M5 HRIS reader and governance checks. This implementation
wiring is not real-provider staging evidence and does not claim OCR,
document-to-Work behavior, or a completed provider-to-M5 run.

M6 is **in progress and is not complete until real staging evidence exists**.
Repository tests and local fixtures do not constitute real Feishu, Odoo,
Keycloak, Agent Kernel, or production model-provider results. No such external
run is claimed by this README. See `docs/milestones/M6.md`, ADR 0003,
`docs/production-operations.md`, and the evidence template at
`docs/acceptance/M6-staging-acceptance-template.md` for the remaining boundary.

See:

- `docs/architecture.md` for the current M4/M5 ownership topology;
- `docs/adr/0001-domain-kernel-dbos-ownership.md` for canonical semantic ownership;
- `docs/adr/0002-repository-and-deployment-boundaries.md` for why service/process separation does not currently imply more repositories;
- `docs/milestones/M5.md` for milestone acceptance evidence, staging checklist, and SLO targets;
- `docs/milestones/M6.md` for the Trusted Perception & Admission delivery plan and gates;
- `docs/adr/0003-trusted-perception-and-admission.md` for the intake, candidate, and admission boundary;
- `docs/production-operations.md` for deployment, observability, backup/restore, incident, and staging procedures.
- `docs/acceptance/M6-staging-acceptance-template.md` for the no-secrets/no-body staging evidence record.

## Development principles

- AI may interpret, extract, compare, investigate, draft, and propose. It does not mint organizational authority by itself.
- Deterministic policy handles already-closed rules; AI is not used to reopen routine cases without evidence.
- Authentication answers who is calling; authority answers what that principal may decide now.
- IdP roles/groups are authentication/directory inputs, not automatic Administrative authority.
- Every authority-sensitive decision is bound to the current case version, authority epoch, policy version, role, and organization scope.
- Multi-party policy requirements are satisfied by an explicit durable approval object, not by selecting one convenient Decision.
- Every material persisted fact has an owner and provenance; current facts never erase historical fact snapshots.
- Authoritative external facts are revalidated before governed reality transitions.
- External effects cross typed capability boundaries through Agent Kernel when physically cut over.
- `outcome_unknown` / execution-unknown is reconciled, not blindly retried.
- Verification proves declared postconditions against fresh external reality; HTTP success is not business completion.
- A case closes only against an explicit completion contract and confirmed outcomes.
- Repeated exceptions may become policy candidates, but one successful episode never becomes universal policy automatically.
- Domain-specific semantics stay here; generic cognition/runtime semantics stay in `agent-kernel`.

## Repository layout

```text
src/administrative_orchestrator/
    api.py                   authenticated HTTP ingress / inspection surfaces
    api_observed.py          production-observed API wrapper
    auth.py                  authentication boundary
    oidc.py                  OIDC discovery/JWKS verification
    authority.py             principals, roles, delegation, approval satisfaction
    authority_lifecycle.py   bind/revoke/rebind/deactivate audit history
    policy.py                deterministic administrative policy evaluator
    policy_plane.py          persisted policy versions / current-policy resolution
    domain.py                canonical administrative records
    fact_acquisition.py      authoritative readers / live revalidation
    fact_history.py          immutable fact lineage
    production_readiness.py  production fail-closed deployment constraints
    observability.py         correlation + low-cardinality Prometheus metrics
    kernel_state_dr.py       Kernel SQLite online backup/verify/restore primitives
    operations_api.py        human exception operations surface
    operations_app.py        observed Operations API wrapper
    service.py               pure case / authorization transitions
    unit_of_work.py          atomic persistence + outbox boundary
    onboarding_execution.py  recoverable onboarding execution state machine
    verification.py          domain semantic postcondition verification
    completion.py            domain completion contract
    messaging.py             transactional outbox / retry / dead-letter
    workflows/               DBOS durability boundary
    providers/               provider authenticity and canonical-read adapters
    intake/                  M6 durable source, evidence, interpretation, candidate, and assessment core
operations-console/          OIDC human exception UI (TypeScript)
docs/
    architecture.md
    production-operations.md
    adr/
        0001-domain-kernel-dbos-ownership.md
        0002-repository-and-deployment-boundaries.md
    contracts/
    milestones/
scripts/
    production_preflight.py
    production_kernel_stack.py
    kernel_state_backup.py
    postgres_dr_fixture.py
tests/
```

## Repository and deployment boundary

The repository is intentionally a product monorepo even though the production topology has multiple processes and two implementation languages. Administrative API, Operations API, worker, product-specific integration code, migrations, Operations Console, deployment assets, DR, and docs currently share one Administrative semantic/versioning and acceptance lifecycle.

`agent-kernel` remains a separate repository because it owns a genuinely independent generic runtime contract and lifecycle. New repositories should be created only when a component acquires independent consumers, release cadence, ownership/SLA/security controls, or stable external versioning needs—not merely because it is a separate service, container, language, or large directory. See ADR 0002.

## Local development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
```

For the complete development/reference topology:

```bash
docker compose up -d --build
python scripts/e2e_compose.py
docker compose down -v --remove-orphans
```

Python 3.12+ is required.

The development Compose topology is intentionally not a production manifest. It uses reproducible local authentication and sandbox providers. Production deployment requirements are in `docs/production-operations.md`.

## Production preflight

A production deployment must run migrations explicitly, provide PostgreSQL durability, configure OIDC/Odoo/Keycloak credentials, use Kernel cutover mode, and provide a durable absolute Kernel state path.

After supplying the production environment:

```bash
uv run python scripts/production_preflight.py
```

Do not start physical cut-over workers when this gate fails.

## CI model

The normal CI lane proves full repository behavior, including PostgreSQL/DBOS restart recovery, Compose E2E, SonarQube Cloud Quality Gate, and the current `agent-kernel/main` recovery canary.

The M5 workflow separately proves:

- production trust/OIDC/connector/readiness/observability/DR invariants;
- Operations Console typecheck + build;
- PostgreSQL destructive backup/restore semantics;
- physical cut-over against the supported pinned Agent Kernel revision.

Keeping pinned-baseline and main-canary lanes separate prevents an upstream Kernel change from silently redefining the production contract.

## Near-term direction

After real-staging M5 acceptance, the next work should be driven by measured operating needs rather than by adding authority shortcuts. Likely directions are additional administrative slices, richer Policy Plane operations, production dashboard/alert calibration, and—only if availability/concurrency measurements justify it—an Agent Kernel store-port implementation for a multi-writer-capable durable backend.

Natural-language and Agent-based intake should remain above this governed execution core. They may improve interpretation and investigation, but they must consume rather than bypass the same fact, policy, authority, effect, verification, reconciliation, and completion contracts.
