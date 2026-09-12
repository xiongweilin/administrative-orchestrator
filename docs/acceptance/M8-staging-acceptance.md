# M8 isolated staging acceptance record

> Scope: the 2026-09-12 isolated M8 staging run and the two bounded
> correctness repairs required before closure. This record contains only
> identifiers, statuses, hashes, and redacted evidence references; it does not
> contain credentials, document bodies, invoice numbers, bank data, or raw
> provider payloads.

## Run identity

- Date/time: `2026-09-12` (local staging run; evidence captured during this run)
- Compose project: `administrative-m8-staging`
- Administrative implementation source: branch `codex/m8-document-driven-closure` at `c9de3bf82176fa822d882fef07a39f9e311babbb`, delivered through PR #80 and merged as `528fc94a6876de80eb8278be34ed5f294474e857`
- Promoted Agent Kernel revision: `0bb90afa4cf8517018e3e5b3715da12d28908c79`
- Kernel source branch: `m8-administrative-public-v3`, delivered through PR #99 and merged as `729082888f5a875db2df2a2e59517ca6d80e4be8`
- Database migration head: `0026_m8_transaction_evidence`
- Runtime profile: `staging`
- Operator/reviewer binding: `person:m8-reviewer`
- Artifact/evidence backup reference: `D:\infrastructure\compose\_m8-acceptance-backups`

## Gate record

| Gate | Result | Evidence reference | Notes |
| --- | --- | --- | --- |
| A–C isolated topology / migration / pin | `PASS` | Compose config, `docker compose ps`, Alembic current/heads | Current and head are both `0026_m8_transaction_evidence`; all M8 services are healthy or running. |
| D–F intake / representation / parser bounds | `PASS` | Three redacted `M8-STAGING-REAL-20260912-*` file references; M8 intake/representation tests | Three real Feishu-sourced receipts produced the bounded artifact, representation, interpretation, and candidate lineage. |
| G–I admission / policy / governance | `PASS` | Current case decisions and governance-basis references | Human admission, typed facts, policy evaluation, and current governance were preserved per case epoch. |
| J–L qualification / duplicate / three-way | `PASS` | Qualification assessment references for invoice case | Vendor, duplicate, and three-way checks were recorded; no payment authority was introduced. |
| M–O obligations / Kernel / draft-only ERP | `PASS` | Effect, realization, outcome, Kernel projection, and Odoo readback references below | Procurement draft/confirm, invoice draft, and expense preparation completed through bounded effects only. |
| P–R readback / recovery / completion | `PASS` | Independent readback, recovery, Fix A/Fix B regression evidence, PR #80 CI | Exact completion binding, lost-ACK recovery, pre-receipt recovery, and ambiguous recovery passed. |
| S no-payment / audit / rollback | `PASS` | Backup directory, provider capability tests, preserved historical records, PR #80 CI | No payment or settlement was performed; M5–M7 volumes and historical evidence were not removed. |

## Case records

### Procurement

- Case id: `62226a7a-3f4e-4015-b27f-d62adb035d4b`
- Authority epoch: `3`
- Governance basis: `39f0c7fb-c744-533a-a652-1fb944b8d578`
- Status: `completed`
- Required effects: `purchase_order.create_draft`, `purchase_order.confirm`
- Effect ids: `7bb84362-6cca-591a-a265-37062aaffcc4`, `d43b5158-813d-52cd-8d4e-807c96c767d9`
- Realization ids: `c9fad4f3-b356-539c-90ac-9216a55880ef`, `77f88e23-c356-57e3-a3c1-7499e72c7aa4`
- Outcome ids: `0ccb31ed-ed8d-56a8-bc92-a1637408d44b`, `da47259c-15da-514d-a0d7-14bb38a74e53`
- Outcome kinds: `erp.purchase_order.create_draft.verified`, `erp.purchase_order.confirm.verified`
- Independent readback: `odoo:purchase.order:12`, state `purchase`
- Draft-only / settlement-forbidden proof: capability routing and Odoo readback; no payment effect was admitted or executed.

### Invoice/AP preparation

- Case id: `87828a43-c55b-4b39-8ffb-f200a3d3110d`
- Authority epoch: `3`
- Governance basis: `947acbdd-c151-5e0f-8bcc-dce1e29a8dc1`
- Status: `completed`
- Required effect: `vendor_bill.create_draft`
- Effect id: `a3be487f-3274-5eee-9a62-f999206da675`
- Realization id: `7813e0ea-fb40-5bfd-bcc4-3c4286dba15b`
- Outcome id: `676d84da-a107-53d3-a5fd-2e61d824368f`
- Outcome kind: `erp.vendor_bill.create_draft.verified`
- Qualification assessments: `bfe7b44f-ae3c-5fe4-ad27-7f1aa0df7056`, `eb4bc9fd-b11f-5179-ac2b-3a38afe70041`, `3f69fb5e-ad96-5d5e-86c3-824cba405620`
- Independent readback: `odoo:account.move:4`, state `draft`
- Draft-only / settlement-forbidden proof: no posting, payment, or settlement capability was admitted.

### Expense reimbursement preparation

- Case id: `c71b8eae-751c-4940-a741-82f90fdf07f1`
- Historical authority epoch: `4`; current authority epoch: `6`
- Current governance basis: `5c57c52a-ff49-59d4-b328-ce69eb24a12b`
- Status: `completed` at current epoch `6`
- Current effect id: `e74ef06f-52a4-5347-abc0-be970d30c958`
- Realization id: `119beec3-cc0d-5588-87da-481c6b5b88fd`
- Outcome id: `aa862894-b775-5e8f-ac6e-0be2bb697c0b`
- Outcome kind: `erp.expense_report.create.verified`
- Kernel projection refs: `request_domain_effect_6129746944f43c9825267e411e986fb8`, `execution_bounded_domain_effect_7a9dbe41fb90d1b81c765c9c4c494e`, `outcome_verified_e2c459c1902156ec3271234f40c4645c`, `evidence_domain_effect_verification_8d420432c94656d67465b6f425135f48`
- Independent readback: `odoo:hr.expense:4`, draft preparation state
- Recovery proof: the prior epoch's `verified-fail` history was preserved; the current epoch used a new request chain and exact payload readback.
- Payment capability absence proof: no reimbursement payment or bank-transfer effect exists in the case/effect set.

## Fix A — runtime revision invariant

- Canonical deployment source: `AGENT_KERNEL_REF`.
- Production wiring: `compose.production.yaml` requires `AGENT_KERNEL_REF` for Administrative expected revision, Kernel build arg, and runtime `PORTABLE_RUNTIME_BUILD_REVISION`; `Dockerfile.kernel` has no independent revision default; application Python has no hardcoded supported revision.
- Runtime proof: Kernel `/v1/contracts` returned `build_revision=0bb90afa4cf8517018e3e5b3715da12d28908c79`, `owner=portable-runtime/contracts`, `catalog_version=portable-runtime-contracts-v1`, and `runtime_protocol=2.0`.
- Readiness proof: Administrative API and Operations API `/readyz` both returned `status=ready` with `kernel_revision=0bb90afa4cf8517018e3e5b3715da12d28908c79`.
- Discriminating tests: expected A/runtime A passes; expected A/runtime B fails; missing runtime revision fails in production; missing deployment revision fails closed.
- Historical M6/M7 pins were left unchanged because they are recorded historical staging/workflow baselines, not the promoted M8 runtime source.

## Fix B — exact effect/realization/outcome binding

- Completion invariant: an obligation is complete only when its linked effect has the exact expected outcome kind and that outcome points to a `VERIFIED` realization whose `effect_id` is the same effect.
- Repository invariant: outcome persistence requires a persisted effect, persisted realization, equal `realization.effect_id`, and matching case/version/authority epoch; realization persistence requires a persisted effect in the requested case.
- Discriminating tests: crossed outcome kinds remain incomplete; cross-effect realization remains incomplete; repository crossed-chain append raises `ExecutionConflict`; missing effect/realization and case/version/epoch mismatches are rejected; the correct chain passes.

## Counterexamples

- Malformed or unsupported PDF: bounded parser failure tests pass and do not create an admitted transaction.
- Parser timeout/resource bound: bounded failure-path tests pass; no unbounded parser path was introduced.
- Duplicate vendor/invoice: duplicate qualification remains blocked in the invoice evidence.
- Mismatched three-way match: qualification remains blocked until the match is qualified.
- Provider unknown after write: the existing lost-ack recovery evidence remains preserved and was not reinterpreted as success.
- Independent readback mismatch: expense historical epoch remains `verified-fail`/reopen history; current epoch was re-assessed and independently read back.
- Cross-effect outcome substitution: completion remains unsatisfied and repository append is rejected.
- Payment/settlement request: capability and effect routing reject payment/settlement; the three current cases contain only bounded preparation effects.

## Verification record

- Admin targeted static check: `uv run ruff check ...` — `PASS`.
- Admin affected regression basis: Fix A/Fix B, M5/M7/P0/M8 tests — `13 passed` in the independent pass; prior full targeted run also passed.
- Admin full suite: `uv run pytest -q` — exit code `0`, complete run, only existing dependency deprecation warnings.
- Kernel public contract static/test basis: `uv run ruff check ...` and public contract tests — `PASS`, `5 passed` in the independent pass.
- Kernel full suite: `uv run pytest -q` — `1307 passed, 33 xfailed, 2 warnings`.
- Admin full suite with coverage: `uv run pytest -q --cov=src/administrative_orchestrator` — exit code `0`, local total coverage `84%`.
- Compose render: `docker compose -f deploy/m8-staging/compose.yaml -p administrative-m8-staging config --quiet` — `PASS`.
- Staging migration: `alembic current` and `alembic heads` — both `0026_m8_transaction_evidence`.
- Staging runtime: API/Operations `/readyz` — `ready`; Kernel `/v1/contracts` revision — exact match.
- PostgreSQL migration/DR: the M8 migration roundtrip `base → 0026 → base → 0026` passed in the earlier isolated migration gate; current staging remains at `0026`.
- Historical M5/M6/M7 records and volumes preserved: `yes`; no old volumes were removed and the acceptance backup directory remains available.
- Admin PR #80 required checks: CI runs `34701651683` and `34701651698` — all checks `PASS`, including SonarQube Cloud Quality Gate, compose/DBOS/PostgreSQL lanes, operations-console, production-trust, and Kernel cutover/restart/recovery lanes.
- Kernel PR #99 required checks: public-contract consumers, strict conformance, and lint/test — `PASS`.

## Closure status and intentional leftovers

M8 is `PASS` and accepted for the recorded isolated-staging/document-driven transaction scope. Admin PR #80 and Kernel PR #99 were merged into their respective `main` branches after all required checks passed.

- The old M7 linked-worktree directories are absent; stale Kernel worktree metadata was pruned. The merged M8 Kernel linked worktree was removed after it was verified clean. The Kernel main repository at `D:\agent\agent-kernel` is retained because it is the repository's main worktree, not an obsolete linked worktree.
- Old M5/M6/M7 containers are absent. Successful one-off M8 migration/bootstrap containers were removed; the M8 service containers remain running for the accepted staging evidence.
- Historical M5–M7 volumes and acceptance records remain intentionally preserved. No `down -v`, volume deletion, or broad Docker prune was used.
- The cleanup manifest is `D:\infrastructure\compose\_m8-acceptance-backups\m8-remote-branch-cleanup-20260912.txt`; old M7 remote refs were already absent and only stale local tracking/worktree metadata was pruned. The merged M8 source branches remain as historical rollback refs.

This is an M8 closure for the current scope only. It does not authorize starting M9, changing scope, deleting historical worktrees/volumes, or rewriting historical M5–M7 acceptance records.
