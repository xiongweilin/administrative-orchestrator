# M5 staging acceptance record

Status: **Gates A–F PASS — PR #19 merged and post-merge main CI PASS**

This record separates evidence from the isolated task-scoped staging deployment, repository CI, and the cross-repository Agent Kernel canary. It is not a production-readiness claim. Existing local infrastructure stacks were left running and unchanged; the staging topology was isolated under `D:\infrastructure\compose\administrative-m5-staging`.

## Environment and repository evidence

| Item | Observed value / result |
| --- | --- |
| Acceptance observation time | 2026-09-10T00:52:42+08:00 for the final supported-baseline RPO/RTO run |
| Administrative branch | `codex/m5-production-trust-reality-integration` |
| Administrative implementation head last tested in real staging | `f9e67be21feb6c97648aa1d22eae6790aec21853` |
| Administrative base | `main` at `cddb5bc5f34ece1a6dffa683f089310e670fcd0d` |
| Current supported Agent Kernel revision | `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197` |
| Last Agent Kernel revision tested in real staging | `0233ba4e576b60a0702637bd93c764df9b0848d5` — historical failing baseline |
| Kernel repair | PR #95 merged; qualification remains pre-action and fresh-process post-action recovery replays the historical qualification only after a Kernel-proven committed action boundary |
| PR #19 | MERGED — squash merge commit `e75d40b3ee867af6d9d3b8849b6259c271695a9c`; post-merge main CI and M5 Production Trust both passed |
| Repository CI before PR #95 promotion | PASS; a new full Administrative CI/M5 run is required on the `fe4b3f4b…` pin |
| Isolated real staging deployment | PASS — Administrative/API/worker/Operations/Kernel plus Odoo, Keycloak, gateway, and PostgreSQL services running during the recorded staging exercise |
| Gate A exact production image/provenance | PASS — `administrative-agent-kernel:production` image `sha256:644bbf4f043021a1faab724d3a8b940afa1bcb4bdb1d4e09e9cbcbcdeb4f8910`; installed `portable-runtime` provenance resolves exactly to `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197`; `/v1/contracts` returned `200` |
| Final Administrative app image | PASS — `administrative-orchestrator:production` image `sha256:03d8faa42fabb49fd15b0210597c33fdeea8156cbe18eb256b68d96b13f3e425`; API/Operations/worker were recreated from it and report the supported revision `fe4b3f4b…` |
| Staging configuration | PRESENT in a task-scoped ignored file; secret values intentionally omitted from this record |
| Historical promoted Kernel runtime | PASS for deployment identity — the tested healthy container resolved `portable-runtime` to `0233ba4e576b60a0702637bd93c764df9b0848d5` |
| Current promoted Kernel runtime | PASS — final healthy container uses the exact fe4 image and the exact installed provenance above; production preflight passed with `kernel_revision=fe4b3f4b…` |
| Existing local infrastructure | PRESERVED — no existing commerce, Dify, gateway, observability, or Odoo stack was stopped, replaced, or deleted |
| Production preflight | PASS on the final Administrative app image and final staging configuration |

Repository CI proves repository contracts and test fixtures. The staging evidence below additionally exercises real OIDC, Odoo, Keycloak, TLS, network, credential separation, live correlation, and recovery paths. Historical failures remain evidence even after a Kernel repair; they become closed only after the repaired supported revision passes the same real-staging counterexample.

## Staging gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| OIDC discovery and JWKS | PASS | Real Keycloak issuer through the staging TLS gateway; discovery `200`, JWKS `200`, two signing keys observed |
| OIDC invalid-token rejection | PASS | Tampered token rejected with `401` |
| OIDC role/group isolation | PASS | Valid no-admin identity reached the API and received `403`; valid administrative identity received `200` |
| OIDC subject to IdentityBinding to Principal | PASS | Real Authorization Code + PKCE console login; issuer/audience/azp and subject claims were validated |
| OIDC signing-key rotation | PASS | Old `kid=xI3mC8j2G2wK-AlLNVUtSJF5mjfePRGfBBYMZLQFlkc` and new `kid=wSGaY6oTnu08ljSzoNaKKRNFyzu8KyRGXKy4QEf5D1Y`; new token was accepted without Administrative API restart, tampered token returned `401`, and a valid token without the `administrative-api` audience returned `401` |
| Odoo authoritative read | PASS | Independent reader read the provisioned employee/department/manager facts from Odoo |
| Field-level fact provenance and freshness | PASS | Approval and effect payloads carried Odoo subject/department/manager/start-date references and were refreshed before execution |
| Governance invalidation after external fact change | PASS | Case `8703634f-15de-47ea-a236-4f7032fd712a` reopened with `governance_stale` after the Odoo department changed before effect dispatch; no effects were emitted |
| Odoo Kernel physical cutover | PASS | Case `92c82e8a-d022-47a1-acf1-fa6256689330` created and independently verified the Odoo employee effect |
| Keycloak Kernel physical cutover | PASS | The same case created and independently verified the Keycloak identity and administrative attributes |
| Real post-commit response-loss and reconciliation | PASS | Case `75acc308-e66c-4a27-a89c-b545f1797657` completed after Odoo committed the employee while the provider response was intentionally lost; Kernel recorded `execution-unknown`, then `recovered-completed`; exactly one target was observed and the fault marker remained |
| Writer/verifier identity isolation | PASS for exercised paths | Separate staging writer and verifier identities were used; readback was performed independently and no-admin access was rejected |
| Operations Console OIDC/PKCE | PASS | Browser login used Authorization Code + PKCE and the console reached the Operations API without `401` |
| Live correlation and low-cardinality metrics | PASS | Correlation ID propagated through direct and gateway readiness calls and appeared in service logs; metrics exposed bounded labels and did not expose correlation IDs |
| Administrative PostgreSQL backup/restore | PASS for restore exercise | Both `administrative` and `administrative_dbos` dumps restored into an isolated PostgreSQL instance; restored case count `12`, audit-event count `242`, DBOS table count `11` |
| Administrative PostgreSQL measured RPO/RTO | PASS | Marker `person:dr-proof` was accepted, backup began `22.030s` later, both `administrative` and `administrative_dbos` were restored in isolation, Administrative semantic verification passed, `dbos` schema restored `11` non-system tables, and final-image PostgreSQL outage-to-ready plus semantic verification completed in `9.042s` (`/readyz=200`, worker running) |
| Kernel state backup/restore | PASS for restore exercise | SQLite online backup and restore passed `quick_check`; runtime record count `953`, lease count `21`, and the recovered receipt were present |
| Kernel measured RPO/RTO | PASS | Marker `work_24218628ba104742b2440f3fb0292cae` was accepted, online backup began `99.164s` later and completed in `27.758ms` with verified SHA-256 `fb1e8f1216e31e2775c3d9b66a2d2484262abd3b32172b3c6915eb09468ec40d`; isolated restore/readback passed, and final-image fresh-process outage-to-ready plus live marker readback completed in `20.733s` (`/v1/health/ready=200`, worker running) |
| Pre-promotion dual cutover evidence | PASS — historical | The earlier staging container executed both HRIS and IAM physical cutovers; legacy execute/observe paths remained unused; this row is not a current supported-baseline claim |
| Pre-promotion lost-ACK recovery evidence | PASS — historical | The earlier staging container recovered the committed effect with one sandbox apply attempt and no redispatch; this row is not a current supported-baseline claim |
| Kernel `0233ba4e…` pre-receipt crash recovery | **FAIL — HISTORICAL** | Real staging phase 1 for subject `m5-pre-receipt-20260909-225933` crossed Odoo exactly once (`odoo_subject_identity_count=1`) with no Kernel receipt, execution ref `execution_bounded_domain_effect_1ecc04e3d2b5949708285b29a9a67243`; after a standard fresh-process restart, phase 2 returned HTTP `409`, and a read-only state-copy diagnostic identified `domain effect authorization was consumed before qualification closure` before existing-attempt recovery could run |
| Kernel PR #95 repair | PASS at Kernel repository/conformance level | Fix preserves qualification as a pre-action closure; only a current activation proven as `resume_after_committed_action_boundary=true` can replay the historical qualification bound to the committed dispatch/fencing lineage; no second qualification event or provider invocation is created |
| Current `fe4b3f4b…` pre-receipt crash recovery | PASS | Subject `m5-pre-receipt-20260910-000959`, execution `execution_bounded_domain_effect_335547658f47b8e54b24dad1d0f155e3`; phase 1 crossed Odoo exactly once, fresh process recovered with `resolution=completed`, and `legacy_execute=0`, `legacy_observe=0` |
| Current `fe4b3f4b…` ambiguous result-commit recovery | PASS | Subject `m5-ambiguous-20260910-001201`, execution `execution_bounded_domain_effect_e54e7828b5a8e872f58992f6c847bd24`; fresh process returned `resolution=recovered-completed`, preserved historical execution-unknown semantics, observed one Odoo identity, and recorded `legacy_execute=0`, `legacy_observe=0` |
| Fresh-process Kernel recovery overall | PASS | Both mandatory current-baseline counterexamples passed with one physical Odoo identity and no blind redispatch |
| Repository pinned/main canary on `fe4b3f4b…` | PASS | PR head `35e6fe3…` checks were green; merge commit `e75d40b3…` main `CI` and `M5 Production Trust` runs both completed successfully |
| M5 merge decision | PASS | Gates A–F passed, PR #19 was marked Ready and squash merged, and post-merge main checks passed |

## Detailed evidence boundary

The strongest real-staging path is the completed dual-provider case `92c82e8a-d022-47a1-acf1-fa6256689330`: two effects succeeded, two independently verified outcomes were recorded, and the Odoo and Keycloak readbacks matched the approved subject facts. The controlled Odoo response-loss case `75acc308-e66c-4a27-a89c-b545f1797657` separately demonstrated that one committed physical effect was reconciled after a fresh Kernel recovery without blind redispatch.

The repaired supported baseline was revalidated with two fresh-process counterexamples. The pre-receipt case crossed Odoo once and completed from the existing succeeded Attempt after Kernel restart. The ambiguous result-commit case retained immutable historical `execution-unknown` and produced a new `recovered-completed` resolution after independent verification, again with one physical Odoo identity and no legacy provider calls.

The signing-key rotation used the task-scoped Keycloak realm's existing RSA provider at priority `100` (`ab8cfde2-16b0-4112-bfc2-6469ee8f987c`) and a new provider `9b891f25-6183-48df-bd8b-fda7f3d5e180` at priority `110`. During rotation, the Administrative API container remained `7a80ca0cb2aebcf3e2d5999dca45dab5fe8e3f358cf0ce5306340a5ae38f81bc` with start time `2026-09-09T11:57:00.930287121Z`; Keycloak remained container `2448e02d0d4e00c44dbc728c81f47cda3a434a9e4c9cdf10bf3e5de3263a5ac2`. The later app-image rebuild occurred only after Gate D completed.

Formal RPO/RTO evidence was measured from explicit durable markers. PostgreSQL marker acceptance at `2026-09-10T00:38:04.379+08:00` to backup start at `00:38:26.409+08:00` was `22.030s`; final-image outage start at `00:52:04.152+08:00` reached `/readyz=200`, a running worker, and semantic marker verification at `00:52:13.194+08:00` (`9.042s`). Kernel marker acceptance at `00:41:41.039+08:00` to online backup start at `00:43:20.203+08:00` was `99.164s`; final-image fresh-process outage start at `00:52:22.102+08:00` reached `/v1/health/ready=200`, a running worker, and live marker verification at `00:52:42.835+08:00` (`20.733s`). Both RPO windows are below five minutes and both RTO measurements are below thirty minutes.

The historical pre-receipt blocker was in the cross-repository Kernel contract, not the isolated staging network. On `0233ba4e…`, the real pre-receipt fixture established the physical boundary and one Odoo subject identity, but fresh-process execution failed in `DomainEffectQualificationAssessment` because a new fencing generation attempted a new qualification closure after the canonical AuthorizationUse had already been consumed at the committed action boundary. The phase-2 state copy contained the succeeded Attempt but no Outcome, Evidence, or bounded receipt.

Agent Kernel PR #95 repaired that sequencing without weakening qualification ordering: the current activation must first prove a committed action boundary, and qualification then replays the historical pre-action closure identified by the committed dispatch's historical fencing generation. The repair was merged as `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197` and promoted as the Administrative supported baseline. The same real-staging counterexamples now pass on that exact revision. No Administrative fallback/workaround was used.

## Protected configuration references

The following references are present only as names in the task-scoped local configuration and are intentionally recorded without values. Existing credentials and secret values were not read into this record or emitted to logs.

### Control plane and durable stores

- `ADMIN_RUNTIME_PROFILE=production`
- `ADMIN_AUTH_MODE=oidc`
- `ADMIN_OIDC_ISSUER`
- `ADMIN_OIDC_AUDIENCE`
- `ADMIN_DATABASE_URL`
- `ADMIN_WORKER_DATABASE_URL`
- `ADMIN_DBOS_SYSTEM_DATABASE_URL`
- `PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH`

### Odoo reader/writer/verifier

- `ADMIN_ODOO_BASE_URL`
- `ADMIN_ODOO_DATABASE`
- `ADMIN_ODOO_READER_USERNAME`
- `ADMIN_ODOO_READER_SECRET`
- `ADMIN_ODOO_WRITER_USERNAME`
- `ADMIN_ODOO_WRITER_SECRET`
- `ADMIN_ODOO_VERIFIER_USERNAME`
- `ADMIN_ODOO_VERIFIER_SECRET`
- `ADMIN_ODOO_REQUEST_REF_FIELD`

### Keycloak reader/writer/verifier

- `ADMIN_KEYCLOAK_BASE_URL`
- `ADMIN_KEYCLOAK_REALM`
- `ADMIN_KEYCLOAK_READER_CLIENT_ID`
- `ADMIN_KEYCLOAK_READER_SECRET`
- `ADMIN_KEYCLOAK_WRITER_CLIENT_ID`
- `ADMIN_KEYCLOAK_WRITER_SECRET`
- `ADMIN_KEYCLOAK_VERIFIER_CLIENT_ID`
- `ADMIN_KEYCLOAK_VERIFIER_SECRET`
- `ADMIN_KEYCLOAK_REQUEST_REF_ATTRIBUTE`

### Operations Console

- `ADMIN_OPERATIONS_OIDC_CLIENT_ID`
- `ADMIN_OPERATIONS_OIDC_SCOPE`

The current supported Kernel revision is `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197`. Gates A–F pass in isolated real staging, and the final exact-head CI, squash merge, and post-merge main CI closure are complete for this recorded scope.

## Final closure evidence

1. Gates A–F are PASS on the exact supported Kernel revision and final Administrative app image, with evidence above.
2. The final exact-head Administrative CI/M5 workflows passed on PR head `35e6fe3…`.
3. PR #19 was marked Ready, squash merged as `e75d40b3…`, and post-merge `main` `CI` plus `M5 Production Trust` passed.

## Residual risk

The mandatory M5 risks and procedural closure gates are closed for the recorded scope: repaired-Kernel fresh-process recovery, ambiguous result-commit recovery, OIDC key rotation, measured PostgreSQL/DBOS and Kernel RPO/RTO, exact-head CI, squash merge, and post-merge main CI all passed.
