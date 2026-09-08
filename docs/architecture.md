# Architecture

## 1. Product position

`administrative-orchestrator` is the primary administrative digital-automation reference system. It owns durable organization-facing cases and the business meaning of facts, policy, approvals, obligations, semantic verification, and completion. It is not a second generic Agent runtime and it does not replace authoritative HR, finance, IAM, document, messaging, or calendar systems.

The current reference chain is:

```text
authenticated ingress
        |
        v
AdministrativeRequest
        |
        v
AdministrativeCase
        |
request claims / attested facts / provenance
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
OnboardingObligationSet
        |
        v
ExecutionAuthorization  (historical compatibility name)
        |
        v
EffectRecord            (historical compatibility/execution surface)
        |
        v
external authoritative reality
        |
        v
availability + presence + freshness
        |
        v
frozen-postcondition semantic verification
        |
        v
ConfirmedOutcome
        |
        v
obligation-backed CompletionAssessment
        |
        +-> COMPLETED
        +-> WAIT / RECONCILE / REASSESS
```

Stage 2 migrates the lower execution half onto `agent-kernel` without changing the business distinctions above. See `docs/adr/0001-domain-kernel-dbos-ownership.md`.

## 2. Ownership boundaries

### administrative-orchestrator owns

- `AdministrativeRequest`, `AdministrativeCase`, case-specific business state;
- request claims, human attestations, authoritative fact projections, provenance, and immutable fact history;
- administrative policy versions, lifecycle, deterministic policy evaluation, and business applicability;
- organization-domain identity projection, roles, delegation, decision eligibility, decisions, and `ApprovalSatisfaction`;
- dependency-scoped `GovernanceBasis` and current-governance revalidation;
- business obligations and frozen expected postconditions;
- administrative business grants/effect intents as the migration proceeds;
- administrative semantic verification, completion, audit, review, exception, and reassessment surfaces.

### agent-kernel owns

- persistent responsibility (`StandingResponsibility`) and responsibility assessment;
- `WorkProposal`, priority/admission/reservation/commitment, Work materialization;
- Work / Run / Step / Attempt;
- generic runtime authorization and authorization use;
- capability routing, invocation permit, provider execution, and the unique physical `RealityBoundary`;
- execution-level retry permission, recovery, and reconciliation;
- generic Outcome/revision contracts.

Downstream administrative code may consume kernel contracts and retain references/projections, but it must not mint or reconstruct kernel authority or create a second generic runtime semantic owner.

### DBOS owns

- durable workflow scheduling;
- wait, wake-up, replay, resume, and crash recovery of administrative orchestration.

DBOS does not own administrative policy, business authority, obligations, completion, or the long-term physical effect boundary.

### external systems own

Business reality remains with its authoritative source. A local projection, adapter result, or HTTP 2xx never becomes authoritative merely because the orchestrator recorded it.

## 3. Current governance invariants

```text
Authentication != resource authorization
RequestClaim != HumanAttestation != AuthoritativeFact
Historical role assignment != current qualification
PolicyVersion definition != PolicyEvaluation
Decision != ApprovalSatisfaction
ApprovalSatisfaction != ExecutionAuthorization
case-local authority_epoch != organization/policy GovernanceBasis
AdministrativeObligation != planned EffectRecord
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
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
   effect planning   completion
```

Required obligations must be covered by linked effects and must each have semantically verified confirmed outcomes. A planner omission therefore blocks completion instead of creating a self-consistent false success.

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

## 6. Closed versus open work

Routine administrative work remains deterministic whenever current ontology, policy, authoritative facts, and governance are sufficient. Ordinary missing information is `GATHERING_FACTS`; waiting for a decision is `AWAITING_DECISION`.

A closed deterministic administrative workflow does not fabricate `CognitiveClosure` merely to use `agent-kernel`. During Stage 2 it will hand a bounded administrative obligation/business grant into persistent responsibility and normal Work admission:

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

It may bypass cognition; it may not bypass responsibility or Work admission.

Administrative reassessment is required when the current business frame becomes invalid, including stale governance, policy conflict, unresolved authority, incompatible subject/scope change, or reality contradiction. This is distinct from the kernel's cognitive reopen semantics.

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

## 8. Runtime profiles

```text
test         -> compatibility/unit semantics may exercise historical paths
development  -> explicit local sandbox conveniences
governed     -> authority enforcement is mandatory and cannot be disabled by env toggle
```

The Docker Compose reference stack runs the API/worker in `governed` profile while using development identity transport only for reproducible local E2E.

## 9. Milestones

- **M0 — semantic foundation:** case/policy/decision/effect distinctions.
- **M1 — durable execution:** PostgreSQL, Alembic, outbox, DBOS wait/restart, authoritative sandbox.
- **M2 — organizational authority and policy:** authenticated principals, scoped role/delegation, multi-party approval satisfaction, versioned Policy Plane.
- **M3 — administrative correctness:** resource authorization, dependency-scoped GovernanceBasis, obligation-backed completion, reality epistemics, fact-authority distinction, explicit policy lifecycle. This is the current stage.
- **M4 — kernel convergence:** compatibility gate, shadow bridge, persistent-responsibility/Work admission, administrative business-grant/effect-intent split, one-capability cutover, then unique kernel RealityBoundary.
- **M5 — production identity and connectors:** OIDC/JWKS, authoritative organization/fact sources, controlled HRIS/IAM reads and writes, operations console.
- **M6 — broader administrative slices:** offboarding, leave, expense, access, procurement, document approval, AP preparation, and scheduling after the reference execution model is proven.

## 10. System-self-operation boundary

`control-plane` may monitor and repair the deployment of `administrative-orchestrator`, but it must not become the administrative business authority.

```text
administrative case authority
!=
platform repair authority
```

The same physical service may be observed by both systems without merging their responsibilities.
