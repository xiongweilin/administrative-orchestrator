# M5 staging acceptance record

Status: **BLOCKED — real staging evidence is present, but promoted Agent Kernel `0233ba4e…` pre-receipt recovery does not pass**

This record separates evidence from the isolated task-scoped staging deployment, repository CI, and the cross-repository Agent Kernel canary. It is not a production-readiness claim. Existing local infrastructure stacks were left running and unchanged; the staging topology was isolated under `D:\infrastructure\compose\administrative-m5-staging`.

## Environment and repository evidence

| Item | Observed value / result |
| --- | --- |
| Acceptance observation time | 2026-09-09T23:22:33+08:00 |
| Administrative branch | `codex/m5-production-trust-reality-integration` |
| Administrative implementation head tested | `5c7c0aafebb4759bc43e25376617b8dd87f92c41` |
| Administrative base | `main` at `cddb5bc5f34ece1a6dffa683f089310e670fcd0d` |
| Supported Agent Kernel revision | `0233ba4e576b60a0702637bd93c764df9b0848d5` |
| Pinned Agent Kernel checkout | `main` at `0233ba4e576b60a0702637bd93c764df9b0848d5`; clean |
| Pinned revision versus Kernel remote `main` | identical (`0233ba4e576b60a0702637bd93c764df9b0848d5`) |
| PR #19 | open, Draft, mergeable state `clean` |
| Repository CI and M5 Production Trust | PASS — all 8 reported checks successful |
| Isolated real staging deployment | PASS — Administrative/API/worker/Operations/Kernel plus Odoo, Keycloak, gateway, and PostgreSQL services running |
| Staging configuration | PRESENT in a task-scoped ignored file; secret values intentionally omitted from this record |
| Promoted Kernel runtime | PASS for deployment identity — healthy container; `portable-runtime` direct URL resolved to `0233ba4e576b60a0702637bd93c764df9b0848d5` |
| Existing local infrastructure | PRESERVED — no existing commerce, Dify, gateway, observability, or Odoo stack was stopped, replaced, or deleted |
| Production preflight | PASS — production image executed with the merged task-scoped staging configuration and pinned Kernel revision |

Repository CI proves repository contracts and test fixtures. The staging evidence below additionally exercises real OIDC, Odoo, Keycloak, TLS, network, credential separation, live correlation, and recovery paths. It does not waive the failed pinned/main recovery gates.

## Staging gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| OIDC discovery and JWKS | PASS | Real Keycloak issuer through the staging TLS gateway; discovery `200`, JWKS `200`, two signing keys observed |
| OIDC invalid-token rejection | PASS | Tampered token rejected with `401` |
| OIDC role/group isolation | PASS | Valid no-admin identity reached the API and received `403`; valid administrative identity received `200` |
| OIDC subject to IdentityBinding to Principal | PASS | Real Authorization Code + PKCE console login; issuer/audience/azp and subject claims were validated |
| OIDC signing-key rotation | BLOCKED | No rotation was performed in the task-scoped Keycloak realm |
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
| Administrative PostgreSQL measured RPO/RTO | BLOCKED | Backup elapsed `0.658s` and restore elapsed `6.231s` were measured, but a service-level outage-to-ready RTO and last-accepted-write-to-backup RPO were not measured |
| Kernel state backup/restore | PASS for restore exercise | SQLite online backup and restore passed `quick_check`; runtime record count `953`, lease count `21`, and the recovered receipt were present |
| Kernel measured RPO/RTO | BLOCKED | Backup elapsed `0.324s` and file restore elapsed `0.156s` were measured, but fresh-process service-ready RTO and last-accepted-write RPO were not measured |
| Pre-promotion dual cutover evidence | PASS — historical | The earlier staging container executed both HRIS and IAM physical cutovers; legacy execute/observe paths remained unused; this row is not a current promoted-baseline claim |
| Pre-promotion lost-ACK recovery evidence | PASS — historical | The earlier staging container recovered the committed effect with one sandbox apply attempt and no redispatch; this row is not a current promoted-baseline claim |
| Promoted Kernel pre-receipt crash recovery | **BLOCKED** | Real staging phase 1 for subject `m5-pre-receipt-20260909-225933` crossed Odoo exactly once (`odoo_subject_identity_count=1`) with no Kernel receipt, execution ref `execution_bounded_domain_effect_1ecc04e3d2b5949708285b29a9a67243`; after a standard promoted-process restart, phase 2 returned HTTP `409`, and a read-only state-copy diagnostic identified `domain effect authorization was consumed before qualification closure` before existing-attempt recovery could run |
| Promoted Kernel ambiguous result-commit recovery | **BLOCKED / NOT RUN IN THIS PASS** | The mandatory run stopped at the real pre-receipt blocker; the older sandbox/6b result is historical and is not evidence for promoted `0233ba4e…` staging acceptance |
| Fresh-process Kernel recovery overall | **BLOCKED** | Lost-ACK path passes, but pre-receipt and ambiguous-result mandatory paths are not both recoverable |
| Main canary | **BLOCKED** | Pinned revision equals current Kernel `main`; the failing recovery gates therefore also block a main canary pass |
| M5 merge decision | **BLOCKED** | Do not mark PR #19 Ready or merge while any mandatory recovery or RPO/RTO gate is blocked |

## Detailed evidence boundary

The strongest real-staging path is the completed dual-provider case `92c82e8a-d022-47a1-acf1-fa6256689330`: two effects succeeded, two independently verified outcomes were recorded, and the Odoo and Keycloak readbacks matched the approved subject facts. The controlled Odoo response-loss case `75acc308-e66c-4a27-a89c-b545f1797657` separately demonstrated that one committed physical effect was reconciled after a fresh Kernel recovery without blind redispatch.

The remaining blocker is in the cross-repository Kernel contract, not the isolated staging network. The promoted container runs the exact supported/current-main revision `0233ba4e…`. The real pre-receipt fixture establishes the physical boundary and one Odoo subject identity, but fresh-process execution fails in `DomainEffectQualificationAssessment` because the authorization use is already consumed before the existing succeeded Attempt can be resumed. The phase-2 state copy contains the succeeded Attempt but no Outcome, Evidence, or bounded receipt. No change was made to `D:\agent\agent-kernel`; any repair must be a separate Kernel branch and PR before this record can be reopened, and no Administrative fallback/workaround is authorized.

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

The supported Kernel revision remains `0233ba4e576b60a0702637bd93c764df9b0848d5`; this blocked record authorizes no revision promotion and no production cutover.

## Required unblock evidence

1. Repair the pre-receipt recovery protocol in a separate Agent Kernel branch and PR; do not modify Agent Kernel in Administrative PR #19.
2. Re-run the isolated pre-receipt and ambiguous-result tests against a fresh Kernel process and verify no blind redispatch, one physical apply, durable receipt, independent verification, and terminal recovery state.
3. Re-run the pinned/current-main canary at the repaired Kernel revision and record the exact revision; keep the current production pin unchanged until that canary passes.
4. Measure service-level RPO/RTO from a defined outage/last-accepted-write boundary through service-ready and semantic verification for both PostgreSQL and Kernel state.
5. Only after every mandatory row is PASS may PR #19 be marked Ready, merged, or described as M5 complete.

## Residual risk

Until the above evidence exists, the remaining risks are durable recovery after a pre-receipt crash, terminal recovery after an ambiguous result-commit boundary, untested OIDC signing-key rotation, and unmeasured service-level RPO/RTO. Real staging happy-path, governance invalidation, least-privilege rejection, observability, and one response-loss reconciliation path are recorded as evidence, but they do not compensate for a failed recovery contract.
