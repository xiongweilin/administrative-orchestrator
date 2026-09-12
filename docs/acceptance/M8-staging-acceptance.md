# M8 isolated staging acceptance record

> Scope: the 2026-09-12 isolated M8 staging run and the two bounded
> correctness repairs required before closure. This record contains only
> identifiers, statuses, hashes, and redacted evidence references; it does not
> contain credentials, document bodies, invoice numbers, bank data, or raw
> provider payloads.

## Run identity

- Date/time: `2026-09-12` (local staging run; evidence captured during this run)
- Compose project: `administrative-m8-staging`
- Administrative repository: `main` at `20d3c1a0d4ba28e37e08341a5f6cd5d96583252a` plus the preserved M8 working tree
- Candidate Agent Kernel revision: `0bb90afa4cf8517018e3e5b3715da12d28908c79`
- Kernel worktree: `m8-administrative-public-v3`, clean, ahead of its remote by one local commit
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
| P–R readback / recovery / completion | `PASS` locally; `REOPEN` for remote closure | Independent readback, recovery, Fix A/Fix B regression evidence | Exact completion binding and expense stale-identity recovery passed. Mandatory remote checks are unavailable for the unpushed candidate. |
| S no-payment / audit / rollback | `PASS` locally; `REOPEN` for remote closure | Backup directory, provider capability tests, preserved historical records | No payment or settlement was performed; M5–M7 volumes and historical evidence were not removed. |

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
- Historical M6/M7 pins were left unchanged because they are recorded historical staging/workflow baselines, not the production runtime source for this M8 candidate.

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
- Compose render: `docker compose -f deploy/m8-staging/compose.yaml -p administrative-m8-staging config --quiet` — `PASS`.
- Staging migration: `alembic current` and `alembic heads` — both `0026_m8_transaction_evidence`.
- Staging runtime: API/Operations `/readyz` — `ready`; Kernel `/v1/contracts` revision — exact match.
- PostgreSQL migration/DR: the M8 migration roundtrip `base → 0026 → base → 0026` passed in the earlier isolated migration gate; current staging remains at `0026`.
- Historical M5/M6/M7 records and volumes preserved: `yes`; no old volumes were removed and the acceptance backup directory remains available.

## Closure status and intentional leftovers

Local correctness and local isolated-staging evidence are `PASS`. M8 is not marked fully closed because the required remote evidence is unavailable within the current authorization boundary:

- Administrative M8 changes remain uncommitted in the preserved dirty worktree, so the remote checks visible for baseline `20d3c1a...` do not qualify this candidate.
- Kernel candidate `0bb90afa...` is local-only and not pushed; it has no matching PR/check run.
- Branch-protection/required-check configuration could not be qualified read-only; no push, PR creation, or workflow trigger was performed.
- Acceptance owner sign-off remains pending.

This is a closure `REOPEN` for remote CI/owner evidence only. It is not a product correctness failure, and it does not authorize starting M9, changing scope, deleting worktrees/volumes, or rewriting historical M5–M7 acceptance records.
