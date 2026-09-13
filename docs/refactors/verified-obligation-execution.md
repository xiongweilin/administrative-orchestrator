# Verified obligation execution boundary

This post-closure refactor introduces `VerifiedObligationExecutor` as a composition seam for the execution mechanics already shared by multiple Administrative domains.

## Ownership

`VerifiedObligationExecutor` owns only the generic post-authorization lifecycle:

- execution / reconciliation / verification state progression;
- dispatch of already-planned effects through the configured provider;
- fail-closed handling of ambiguous or unavailable read-back;
- realization evidence creation;
- exact effect-to-confirmed-outcome recording;
- collection of current outcomes and realizations before domain completion assessment.

It does **not** own domain interpretation. Planning, qualification, effect ordering and payload dependencies, semantic reality verification, completion meaning, reopen policy, effective-time rules, transfer semantics, and financial transaction semantics remain on the existing domain execution engines.

## Compatibility

This change deliberately preserves the historical public class surface:

```text
FinancialExecutionEngine(OnboardingExecutionEngine)
OffboardingExecutionEngine(OnboardingExecutionEngine)
```

`FinancialExecutionEngine` and `OffboardingExecutionEngine` compose the generic executor beneath that compatibility surface. `OnboardingExecutionEngine` remains the existing reference implementation in this slice; migrating or simplifying the inheritance hierarchy is explicitly out of scope.

Financial qualification waiting remains interpreted by `FinancialExecutionEngine`. Offboarding effective-time qualification, Administrative domain-state fulfillment, continuity transfer, and transfer-specific reopen behavior remain interpreted by `OffboardingExecutionEngine`.

## Invariants

- no schema or migration changes;
- no capability or Agent Kernel contract changes;
- no provider retry-policy changes;
- `OUTCOME_UNKNOWN` still requires reconciliation and never grants blind retry permission;
- provider success still does not substitute for verified reality;
- exact effect / realization / confirmed-outcome lineage is unchanged;
- obligation completion semantics remain domain-owned;
- authority-epoch and governance revalidation remain unchanged;
- M5/M7/M8 accepted behavior and evidence are not rewritten.

A later change may migrate `OnboardingExecutionEngine` itself to the composition seam only after this shared lifecycle has been proven through the independent financial and offboarding regression suites. That is a separate decision, not part of this refactor.
