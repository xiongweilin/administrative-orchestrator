# Architecture

## 1. Product position

`administrative-orchestrator` owns the administrative-domain control surface around durable organizational cases. It is not a second generic Agent runtime and it does not replace authoritative HR, finance, IAM, document, messaging, or calendar systems.

```text
Feishu / Web / Email / webhook / system event
                    |
                    v
                 ingress
                    |
                    v
          AdministrativeCase
        facts / evidence / subject
                    |
                    v
              policy plane
          /                     \
   routine closure          insufficient frame
        |                         |
        v                         v
 decision / auto path       REOPEN_REQUIRED
        |
        v
 ExecutionAuthorization
        |
        v
 durable typed effect workflow
        |
        v
 HRIS / ERP / IAM / Docs / Calendar / Messaging
        |
        v
 external read-back / realization assessment
        |
        v
 reconciliation / bounded completion
        |
        v
 close / wait / reopen
```

## 2. Ownership boundaries

### administrative-orchestrator owns

- organization-domain projections needed for administrative decisions;
- principal, role assignment and delegation records used by administrative policy;
- versioned administrative policy and its current-use evaluation;
- `AdministrativeCase` and case-specific business state;
- administrative approval requirements and decisions;
- server-owned mapping from approved decisions to exact execution-authorization profiles;
- administrative typed-effect vocabulary and connector adapters;
- domain-specific read-back, reconciliation and completion requirements;
- administrative audit/read projections and exception/reopen queues.

### agent-kernel owns

- generic durable cognition and temporary closure semantics;
- Work / Run / Step / Attempt;
- generic authorization records and capability routing;
- reality boundary semantics;
- verification/revision/reopen and persistent responsibility contracts.

The administrative product may consume these contracts but must not fork or silently redefine them.

### external systems own

Business reality remains with its authoritative source. For example:

```text
Employee record       -> HRIS / Odoo
Account/group state   -> IAM / Keycloak
Posted accounting     -> ERP / Odoo
Calendar event        -> calendar provider
Document version      -> document system
Message delivery      -> messaging provider
```

A local projection or successful adapter response never re-owns these facts.

## 3. Core control chain

```text
AdministrativeRequest
  -> AdministrativeCase
  -> current facts/evidence
  -> PolicyEvaluation
  -> Decision when required
  -> ExecutionAuthorization
  -> EffectRecord
  -> external provider
  -> EffectRealizationAssessment
  -> ConfirmedOutcome where required
  -> case completion assessment
```

Negative invariants:

```text
AI interpretation != authoritative fact
PolicyEvaluation != Decision
Decision != ExecutionAuthorization
RoleAssignment != ExecutionAuthorization
EffectRecord.succeeded != EffectRealizationAssessment.VERIFIED
EffectRealizationAssessment.VERIFIED != universal truth
CaseStatus.COMPLETED != universal responsibility discharge
```

## 4. Open versus closed administrative work

Routine administrative work should remain closed whenever the current ontology, policy and authoritative facts are sufficient. Ordinary missing information is `GATHERING_FACTS`, not deep reopen.

`REOPEN_REQUIRED` is reserved for conditions such as:

- no applicable current policy exists;
- current policies conflict;
- current authority cannot be resolved under known rules;
- the case subject or scope changed after a relied-upon decision;
- an external effect has ambiguous realization that cannot be reconciled in the current frame;
- current reality contradicts the represented business state;
- a requested action introduces a risk/subject dimension absent from the current administrative model.

Reopen is explicit. The system must not let a model improvise authority merely because ordinary closure failed.

## 5. Risk model

Administrative effects use two independent axes.

### reversibility

```text
READ_ONLY
REVERSIBLE
CORRECTABLE
IRREVERSIBLE
UNKNOWN
```

### authority sensitivity

```text
NORMAL
PII
FINANCIAL
PRIVILEGED_ACCESS
EMPLOYMENT
LEGAL
REGULATED
```

A reversible effect may still require strong approval. Granting administrator access is reversible but highly authority-sensitive.

## 6. Execution architecture milestones

M0 uses an in-memory API only to lock domain semantics.

M1 introduces PostgreSQL, Alembic, DBOS and append-only event/audit persistence.

M2 introduces the first real sandbox adapters:

- Odoo 19 for employee/expense/procurement/accounting facts;
- Keycloak for identity/group/access facts;
- Feishu for multi-user request/approval/notification transport.

M3 completes employee onboarding/offboarding with external read-back and declared-scope completion.

M4 expands into leave, expense, access, procurement, document approval and AP preparation while preserving the same control chain.

## 7. System-self-operation boundary

`control-plane` may monitor and repair the deployment of `administrative-orchestrator`, but it must not become the administrative business authority.

```text
administrative case authority
!=
platform repair authority
```

The same physical service may be observed by both systems without merging their responsibilities.
