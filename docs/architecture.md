# Architecture

## 1. Product position

`administrative-orchestrator` is the primary administrative digital-automation reference system. It owns durable organization-facing cases and the business meaning of facts, policy, approvals, obligations, semantic verification, and completion. It is not a second generic Agent runtime and it does not replace authoritative HR, finance, IAM, document, messaging, or calendar systems.

The current M5 reference chain is:

```text
authenticated ingress
        |
        v
AdministrativeRequest
        |
        v
AdministrativeCase
        |
request claims / attestations / authoritative assertions / provenance
        |
        v
persisted PolicyVersion -> PolicyEvaluation
        |
        v
current identity / role / delegation qualification
        |
        v
Decision set -> ApprovalSatisfaction
        |
        v
dependency-scoped GovernanceBasis
        |
        v
AdministrativeObligationSet
        |
        v
AdministrativeExecutionGrant / EffectIntent
        |
        v
Agent Kernel StandingResponsibility
        |
        v
WorkProposal -> admission -> Work / Run / Attempt
        |
        v
Kernel runtime authorization
        |
        v
unique physical RealityBoundary
        |
        v
external system reality
        |
        v
independent Kernel verification evidence / recovery
        |
        v
Administrative semantic verification
        |
        v
ConfirmedOutcome
        |
        v
obligation-backed CompletionAssessment
        |
        +-> COMPLETED
        +-> WAIT / RECONCILE / REASSESS / REOPEN
```

M4 completed the lower-half runtime convergence onto `agent-kernel`: cut-over writes no longer have an Administrative physical-provider fallback, and ambiguous execution is recovered by Kernel canonical recovery rather than by Administrative redispatch. M5 keeps that ownership model intact while adding production identity, authoritative facts, real-system connector contracts, human exception operations, observability, and recovery/DR gates.

See `docs/adr/0001-domain-kernel-dbos-ownership.md` for semantic ownership and `docs/adr/0002-repository-and-deployment-boundaries.md` for repository/deployment boundaries.

## 2. Ownership boundaries

### administrative-orchestrator owns

- `AdministrativeRequest`, `AdministrativeCase`, case-specific business state;
- request claims, human attestations, authoritative fact projections/assertions, provenance, and immutable fact history;
- administrative policy versions, lifecycle, deterministic policy evaluation, and business applicability;
- organization-domain identity projection, roles, delegation, decision eligibility, decisions, and `ApprovalSatisfaction`;
- dependency-scoped `GovernanceBasis` and current-governance revalidation;
- business obligations and frozen expected postconditions;
- administrative business execution grants/effect intents;
- authoritative domain-read ports and product-specific connector contracts;
- administrative semantic verification, completion, audit, review, exception, and reassessment surfaces.

### agent-kernel owns

- persistent responsibility (`StandingResponsibility`) and responsibility assessment;
- `WorkProposal`, priority/admission/reservation/commitment, Work materialization;
- Work / Run / Step / Attempt;
- generic runtime authorization and authorization use;
- capability routing, invocation permit, provider execution, and the unique physical `RealityBoundary`;
- execution-level retry permission, recovery, and reconciliation;
- generic execution evidence, Outcome/revision contracts, and canonical resolution of ambiguous provider results.

Downstream administrative code may consume Kernel contracts and retain references/projections, but it must not mint or reconstruct Kernel authority, directly retry cut-over providers, or create a second generic runtime semantic owner.

### DBOS owns

- durable workflow scheduling;
- wait, wake-up, replay, resume, and crash recovery of administrative orchestration.

DBOS does not own administrative policy, business authority, obligations, completion, or the physical effect boundary.

### external systems own

Business reality remains with its authoritative source. A local projection, adapter result, HTTP 2xx, or provider execution receipt never becomes authoritative merely because the orchestrator recorded it.

## 3. Current governance invariants

```text
Authentication != resource authorization
External identity != Administrative authority
RequestClaim != HumanAttestation != AuthoritativeFact
Historical role assignment != current qualification
PolicyVersion definition != PolicyEvaluation
Decision != ApprovalSatisfaction
ApprovalSatisfaction != AdministrativeExecutionGrant
AdministrativeExecutionGrant != Kernel runtime authorization
case-local authority_epoch != organization/policy GovernanceBasis
AdministrativeObligation != Kernel Work
Kernel execution evidence != Administrative ConfirmedOutcome
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
execution-unknown != retry permission
ABSENT != UNAVAILABLE != UNKNOWN != STALE
Object existence != semantic postcondition satisfaction
planned effects complete != business obligations complete
CaseStatus.COMPLETED != universal responsibility discharge
```

`authority_epoch` invalidates case-local authority when case facts/evidence/policy/reassessment change. `GovernanceBasis` separately records the exact external governance dependencies relied on by an approval world: fact snapshot, policy definition, scope, selected principal qualifications, and any delegation basis. Execution, verification, and completion revalidate those dependencies even when the case itself has not changed.

## 4. Business obligations before effects

Completion is not inferred from whatever the planner emitted.

```text
facts + policy + current governance
              |
              v
   AdministrativeObligationSet
          /          \
         v            v
   effect intent     completion
         |
         v
   Kernel Work
```

Required obligations must be covered by linked intents/Work and must each have semantically verified confirmed outcomes. A planner omission therefore blocks completion instead of creating a self-consistent false success.

## 5. Reality observation semantics

Observation uses independent epistemic dimensions:

```text
availability: AVAILABLE | UNAVAILABLE | UNKNOWN
presence:     PRESENT   | ABSENT      | UNKNOWN
freshness:    CURRENT   | STALE       | UNKNOWN
```

Examples:

```text
HTTP 404 from authoritative source
-> AVAILABLE + ABSENT + CURRENT

network timeout
-> UNAVAILABLE + UNKNOWN + UNKNOWN
```

A network failure is never proof that an object is absent. An ambiguous prior effect result is never permission for a blind side-effect retry.

Production integration preserves three different roles even when they target the same vendor system:

```text
Administrative authoritative reader
!= Kernel writer provider
!= Kernel independent verifier
```

The writer changes reality. The verifier independently observes declared postconditions. The Administrative reader supplies current business facts and governance dependencies. Sharing a vendor API does not merge these authorities.

## 6. Closed versus open work

Routine administrative work remains deterministic whenever current ontology, policy, authoritative facts, and governance are sufficient. Ordinary missing information is `GATHERING_FACTS`; waiting for a decision is `AWAITING_DECISION`.

A closed deterministic administrative workflow does not fabricate `CognitiveClosure` merely to use `agent-kernel`. It hands a bounded administrative obligation/business grant into persistent responsibility and normal Work admission:

```text
AdministrativeObligation
-> AdministrativeExecutionGrant
-> StandingResponsibility / ResponsibilityAssessment
-> WorkProposal
-> priority/admission/reservation/commitment
-> Work / Run
-> runtime authorization
-> RealityBoundary
```

It may bypass cognition; it may not bypass responsibility, Work admission, runtime authorization, the unique RealityBoundary, or canonical recovery.

Administrative reassessment is required when the current business frame becomes invalid, including stale governance, policy conflict, unresolved authority, incompatible subject/scope change, or reality contradiction. This is distinct from the Kernel's cognitive reopen semantics.

## 7. Risk model

Administrative effects retain independent reversibility and authority-sensitivity axes.

Reversibility:

```text
READ_ONLY
REVERSIBLE
CORRECTABLE
IRREVERSIBLE
UNKNOWN
```

Authority sensitivity:

```text
NORMAL
PII
FINANCIAL
PRIVILEGED_ACCESS
EMPLOYMENT
LEGAL
REGULATED
```

Reversibility never implies weak authority. Granting administrator access is reversible but highly authority-sensitive.

## 8. Runtime and deployment profiles

```text
test         -> compatibility/unit semantics may exercise historical paths
development  -> explicit local sandbox conveniences
governed     -> authority enforcement is mandatory and cannot be disabled by env toggle
production   -> OIDC, PostgreSQL durability, explicit migrations, Kernel cutover,
                pinned Kernel revision, HTTPS providers, credential separation,
                production preflight and durable recovery storage
```

The development Docker Compose stack runs governed application semantics with reproducible local identity/provider conveniences. `compose.production.yaml` is the production-shaped reference topology and still requires real environment-specific staging/production credentials, network policy, backup policy, and acceptance evidence.

Service/process boundaries do not imply repository boundaries. The Administrative API, Operations API, DBOS worker, product-specific integrations, migrations, deployment assets, and TypeScript Operations Console remain one repository because they share one Administrative semantic/versioning and acceptance lifecycle. See ADR 0002.

## 9. Milestones

- **M0 — semantic foundation:** case/policy/decision/effect distinctions.
- **M1 — durable execution:** PostgreSQL, Alembic, outbox, DBOS wait/restart, authoritative sandbox.
- **M2 — organizational authority and policy:** authenticated principals, scoped role/delegation, multi-party approval satisfaction, versioned Policy Plane.
- **M3 — administrative correctness:** resource authorization, dependency-scoped GovernanceBasis, obligation-backed completion, reality epistemics, fact-authority distinction, explicit policy lifecycle.
- **M4 — kernel convergence:** compatibility gate, persistent responsibility/Work admission, administrative business-grant/effect-intent split, HRIS/IAM physical cut-over, unique Kernel RealityBoundary, and canonical ambiguous-result recovery.
- **M5 — production trust and reality integration:** OIDC/JWKS, field-level authoritative provenance, Odoo/Keycloak read/write/verification contracts, Operations Console, observability, production preflight, DR gates, pinned Kernel baseline plus `agent-kernel/main` recovery canary. **Repository implementation/CI, isolated real-staging Gates A–F, squash merge, and post-merge main CI are complete for the recorded scope.**
- **M6 — broader administrative slices:** offboarding, leave, expense, access, procurement, document approval, AP preparation, and scheduling only after M5 real-staging acceptance.

M5 staging acceptance is intentionally external to repository CI. The checklist and evidence requirements are in `docs/milestones/M5.md` and `docs/production-operations.md`.

## 10. Repository and deployment topology

Current repository ownership is intentionally coarse-grained around semantic/versioning ownership rather than process count:

```text
agent-kernel                         separate repository
    generic responsibility / Work / runtime authority / RealityBoundary / recovery

administrative-orchestrator          one product repository
    Administrative domain + policy + authority + obligations + completion
    Administrative API
    Operations API
    DBOS worker/orchestration
    Odoo/Keycloak Administrative integration contracts/implementations
    Operations Console (TypeScript)
    migrations / deployment / observability / DR / docs
```

A component becomes a repository-split candidate only when it acquires an independently owned contract and lifecycle: multiple product consumers, independent release cadence/SLA/security boundary/team, or stable external versioning needs. Code size or having a separate process/container is not by itself a split trigger.

## 11. System-self-operation boundary

`control-plane` may monitor and repair the deployment of `administrative-orchestrator`, but it must not become the administrative business authority.

```text
administrative case authority
!=
platform repair authority
```

The same physical service may be observed by both systems without merging their responsibilities.
