# Administrative domain model

## Canonical objects

### AdministrativeRequest

An ingress event or explicit human request. It records who asked, through which channel, the expressed intent and a source reference when available.

It is not durable administrative responsibility by itself.

### AdministrativeCase

The durable administrative matter. A case survives chat/session/model/process boundaries and is the primary domain object for multi-step administrative work.

Required identity:

- `case_id`;
- `case_kind`;
- requester principal;
- current subject reference;
- monotonic case version;
- current status.

A case version changes whenever material evidence or state changes. Historical decisions and authorizations remain historical records and do not silently bind a newer case version.

### Principal / RoleAssignment / Delegation

`Principal` is an actor identity known to the administrative product.

`RoleAssignment` says that a principal has one role inside one organizational scope during a validity window.

`Delegation` records an explicitly bounded temporary transfer of role-use eligibility between principals. Delegation does not itself mint an execution authorization.

```text
Principal != RoleAssignment
RoleAssignment != Delegation
RoleAssignment/Delegation != Decision
Decision != ExecutionAuthorization
```

### PolicyRef / PolicyEvaluation

A `PolicyRef` binds a policy identifier, immutable version, owner and effective window.

A `PolicyEvaluation` is the result of applying current facts to one current policy version. It may say:

- `AUTO_CLOSABLE`;
- `HUMAN_DECISION_REQUIRED`;
- `NEED_MORE_FACTS`;
- `REOPEN_REQUIRED`;
- `DENIED`.

Ordinary missing facts are not epistemic reopen.

### Decision

A current principal's bounded disposition over one exact case version under one exact policy version.

Current dispositions:

- approve;
- reject;
- request changes;
- escalate.

A Decision records judgment. It does not by itself authorize an external effect.

### ExecutionAuthorization

A server-minted exact-scope authority record bound to:

- case id and current version;
- supporting decision;
- subject;
- target system;
- allowed operation set;
- authority sensitivity class;
- policy version;
- issuer;
- optional expiry/revocation.

Dispatch must reject stale, revoked, expired, subject-mismatched, target-mismatched or operation-mismatched authority.

### EffectRecord

A typed planned/dispatched external effect. It records execution facts, not external reality.

Status vocabulary:

```text
planned
-> dispatched
-> succeeded | failed | outcome_unknown
```

`outcome_unknown` is not retry permission.

### EvidenceRef

A bounded reference to observed information with source, fact owner, observation time and optional source version/digest. Evidence is data, not instruction.

### EffectRealizationAssessment

An explicit assessment of whether the intended external effect is observed in authoritative reality.

```text
VERIFIED
NOT_VERIFIED
MISMATCH
UNKNOWN
```

`VERIFIED` requires evidence.

### ConfirmedOutcome

A bounded confirmed business result derived from realization evidence. It must not imply more than its declared outcome kind and case scope.

## Case lifecycle

```text
RECEIVED
  -> GATHERING_FACTS
  -> READY_FOR_POLICY
  -> AWAITING_DECISION
  -> AUTHORIZED
  -> EXECUTING
  -> VERIFYING
  -> RECONCILING
  -> COMPLETED
```

Cross-cutting non-success states:

```text
WAITING
REOPEN_REQUIRED
FAILED
CANCELLED
```

Not every workflow must traverse every state. State skipping is permitted only when the corresponding semantic requirement is genuinely absent; for example, a policy-defined low-risk auto path may not need a human-decision state, but it still needs an explicit authority path before external effects.

## Reopen reasons

Initial canonical reopen reasons:

- `NO_APPLICABLE_POLICY`;
- `POLICY_CONFLICT`;
- `MISSING_REQUIRED_FACT` only when the fact cannot be acquired within the represented case procedure;
- `AUTHORITY_UNRESOLVED`;
- `SUBJECT_CHANGED`;
- `OUTCOME_UNKNOWN` when ordinary reconciliation cannot settle realization;
- `REALITY_MISMATCH`;
- `SCOPE_EXPANSION`;
- `UNKNOWN_RISK_DIMENSION`.

The vocabulary may evolve only when concrete administrative failures show that the existing set cannot preserve a necessary distinction.

## Field ownership rule

For every persisted decision-relevant field, the implementation must make it possible to answer:

```text
Where did this value come from?
Who owns the authoritative fact?
Which version was relied upon?
How was it validated?
Where may it be used?
```

AI-derived values remain candidate/interpreted facts until validated against an authoritative source or explicitly accepted under a policy that permits such evidence.
