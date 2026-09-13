# M9 isolated staging acceptance template

This template records only redacted evidence. Do not paste transcript bodies,
message bodies, access tokens, HMAC keys, provider secrets, private URLs, or
raw identity credentials.

## Deployment identity

- Compose project: `administrative-m9-staging`
- Admin revision:
- Gateway revision / worktree:
- Agent Kernel revision (`AGENT_KERNEL_REF`):
- migration head:
- timestamp / timezone:

## Topology and isolation

- [ ] M9 PostgreSQL, Kernel, artifact, and OIDC volumes are separate from M6–M8.
- [ ] one Gateway owner is recorded; no second long-connection owner was started.
- [ ] direct Compose startup without the pinned Kernel reference fails closed.
- [ ] `/readyz` proves the expected Admin and Kernel revision.

## Intake and qualification

- [ ] real Feishu transcript event was received through the verified metadata path.
- [ ] canonical transcript artifact and EvidenceSpan references are recorded by digest/ref only.
- [ ] candidate count and classifications:
- [ ] prompt-injection candidate-only counterexample:
- [ ] zero-binding and multiple-binding counterexamples:
- [ ] assignment-to-other / aspiration / suggestion counterexamples:
- [ ] qualified principal and due-time basis are redacted references only.

## Authority and responsibility

- [ ] human reviewer role and approval satisfaction:
- [ ] policy ref/version and governance basis digest:
- [ ] Kernel responsibility proposal receipt refs:
- [ ] no Work admission was used for the commitment responsibility.
- [ ] completion evidence is distinct from discharge evidence.

## Governed communication

- [ ] confirmation draft storage ref/digest only:
- [ ] communication event id:
- [ ] separate Gateway HMAC configuration ref:
- [ ] replay returned the existing event without a second provider send.
- [ ] lost-ACK outcome-unknown case was reconciled without a new event identity.
- [ ] transport accepted evidence:
- [ ] independent delivery verification evidence:
- [ ] human-read state remains `unknown`.
- [ ] reminder count is zero or one; no confirmation message was treated as fulfillment.

## Fulfillment and discharge

- [ ] authorized committer fulfillment attestation or objective evidence ref:
- [ ] wrong-principal attestation was rejected:
- [ ] due revision/cancellation stale-timer evidence:
- [ ] responsibility assessment ref:
- [ ] explicit discharge decision ref:
- [ ] lifecycle transition ref and final Kernel status:

## Required verification

- [ ] Admin ruff
- [ ] Admin targeted and full pytest
- [ ] migration upgrade/downgrade/upgrade on SQLite
- [ ] migration and targeted tests on PostgreSQL
- [ ] default/dev/prod fail-closed configuration checks
- [ ] Gateway ruff and full pytest
- [ ] Operations Console typecheck/build
- [ ] SonarQube/new-code quality gate
- [ ] mandatory CI and M5–M8 regression lanes
- [ ] Kernel checks if Kernel code changed

## Counterexample ledger

Record pass/fail and redacted evidence for every mandatory counterexample in
the M9 plan. A local unit test is not a substitute for the real-provider
frontier where the plan requires real staging evidence.

## Closure

- [ ] required PRs merged
- [ ] post-merge main revisions verified
- [ ] closure acceptance record committed
- [ ] annotated tag `m9-accepted-YYYY-MM-DD` created only after all R-gate evidence
