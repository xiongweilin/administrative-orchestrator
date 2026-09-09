# M5 staging acceptance record

Status: **BLOCKED — real staging failed on historical Kernel `0233ba4e…`; repaired Kernel `fe4b3f4b…` is now the supported baseline but still requires real-staging revalidation**

This record separates evidence from the isolated task-scoped staging deployment, repository CI, and the cross-repository Agent Kernel canary. It is not a production-readiness claim. Existing local infrastructure stacks were left running and unchanged; the staging topology was isolated under `D:\infrastructure\compose\administrative-m5-staging`.

## Environment and repository evidence

| Item | Observed value / result |
| --- | --- |
| Acceptance observation time | 2026-09-09T23:22:33+08:00 for the last real-staging run; repository repair/promotion followed afterward |
| Administrative branch | `codex/m5-production-trust-reality-integration` |
| Administrative implementation head last tested in real staging | `5c7c0aafebb4759bc43e25376617b8dd87f92c41` |
| Administrative base | `main` at `cddb5bc5f34ece1a6dffa683f089310e670fcd0d` |
| Current supported Agent Kernel revision | `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197` |
| Last Agent Kernel revision tested in real staging | `0233ba4e576b60a0702637bd93c764df9b0848d5` — historical failing baseline |
| Kernel repair | PR #95 merged; qualification remains pre-action and fresh-process post-action recovery replays the historical qualification only after a Kernel-proven committed action boundary |
| PR #19 | open, Draft; it must remain Draft pending real-staging revalidation and the remaining M5 gates |
| Repository CI before PR #95 promotion | PASS; a new full Administrative CI/M5 run is required on the `fe4b3f4b…` pin |
| Isolated real staging deployment | PASS — Administrative/API/worker/Operations/Kernel plus Odoo, Keycloak, gateway, and PostgreSQL services running during the recorded staging exercise |
| Staging configuration | PRESENT in a task-scoped ignored file; secret values intentionally omitted from this record |
| Historical promoted Kernel runtime | PASS for deployment identity — the tested healthy container resolved `portable-runtime` to `0233ba4e576b60a0702637bd93c764df9b0848d5` |
| Current promoted Kernel runtime | NOT YET REVALIDATED IN REAL STAGING — rebuild/restart must prove exact `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197` before rerunning recovery gates |
| Existing local infrastructure | PRESERVED — no existing commerce, Dify, gateway, observability, or Odoo stack was stopped, replaced, or deleted |
| Production preflight | PASS on the historical tested staging configuration; rerun is required after the current Kernel image promotion |

Repository CI proves repository contracts and test fixtures. The staging evidence below additionally exercises real OIDC, Odoo, Keycloak, TLS, network, credential separation, live correlation, and recovery paths. Historical failures remain evidence even after a Kernel repair; they become closed only after the repaired supported revision passes the same real-staging counterexample.

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
| Pre-promotion dual cutover evidence | PASS — historical | The earlier staging container executed both HRIS and IAM physical cutovers; legacy execute/observe paths remained unused; this row is not a current supported-baseline claim |
| Pre-promotion lost-ACK recovery evidence | PASS — historical | The earlier staging container recovered the committed effect with one sandbox apply attempt and no redispatch; this row is not a current supported-baseline claim |
| Kernel `0233ba4e…` pre-receipt crash recovery | **FAIL — HISTORICAL** | Real staging phase 1 for subject `m5-pre-receipt-20260909-225933` crossed Odoo exactly once (`odoo_subject_identity_count=1`) with no Kernel receipt, execution ref `execution_bounded_domain_effect_1ecc04e3d2b5949708285b29a9a67243`; after a standard fresh-process restart, phase 2 returned HTTP `409`, and a read-only state-copy diagnostic identified `domain effect authorization was consumed before qualification closure` before existing-attempt recovery could run |
| Kernel PR #95 repair | PASS at Kernel repository/conformance level | Fix preserves qualification as a pre-action closure; only a current activation proven as `resume_after_committed_action_boundary=true` can replay the historical qualification bound to the committed dispatch/fencing lineage; no second qualification event or provider invocation is created |
| Current `fe4b3f4b…` pre-receipt crash recovery | **BLOCKED / REVALIDATION REQUIRED** | The exact historical counterexample above must be rerun against a fresh production Kernel container whose installed revision is `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197` |
| Current `fe4b3f4b…` ambiguous result-commit recovery | **BLOCKED / NOT YET RUN IN REAL STAGING** | The mandatory real-staging run must prove fresh-process recovery, exact independent verifier routing, no blind redispatch, one physical outcome, immutable historical `execution-unknown`, and a new `recovered-completed` resolution |
| Fresh-process Kernel recovery overall | **BLOCKED** | Lost-ACK path passes historically, but the two mandatory recovery counterexamples must both pass on the current supported baseline |
| Repository pinned/main canary on `fe4b3f4b…` | **PENDING** | Administrative branch promotion must complete a new full CI and M5 Production Trust run; repository success will not substitute for real-staging revalidation |
| M5 merge decision | **BLOCKED** | Do not mark PR #19 Ready or merge while any mandatory recovery, OIDC key-rotation, or formal RPO/RTO gate is blocked |

## Detailed evidence boundary

The strongest real-staging path is the completed dual-provider case `92c82e8a-d022-47a1-acf1-fa6256689330`: two effects succeeded, two independently verified outcomes were recorded, and the Odoo and Keycloak readbacks matched the approved subject facts. The controlled Odoo response-loss case `75acc308-e66c-4a27-a89c-b545f1797657` separately demonstrated that one committed physical effect was reconciled after a fresh Kernel recovery without blind redispatch.

The historical pre-receipt blocker was in the cross-repository Kernel contract, not the isolated staging network. On `0233ba4e…`, the real pre-receipt fixture established the physical boundary and one Odoo subject identity, but fresh-process execution failed in `DomainEffectQualificationAssessment` because a new fencing generation attempted a new qualification closure after the canonical AuthorizationUse had already been consumed at the committed action boundary. The phase-2 state copy contained the succeeded Attempt but no Outcome, Evidence, or bounded receipt.

Agent Kernel PR #95 repaired that sequencing without weakening qualification ordering: the current activation must first prove a committed action boundary, and qualification then replays the historical pre-action closure identified by the committed dispatch's historical fencing generation. The repair was merged as `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197` and promoted as the Administrative supported baseline. This record remains blocked until the same real-staging counterexample passes on that exact revision. No Administrative fallback/workaround is authorized.

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

The current supported Kernel revision is `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197`. Promotion does not authorize production cutover or M5 completion before the real-staging recovery, key-rotation, and RPO/RTO gates pass.

## Required unblock evidence

1. Rebuild/restart the isolated staging Kernel from the standard production image and prove the installed `portable-runtime` resolves exactly to `fe4b3f4bf2e376bd7105caf7d15d77e2483c7197`.
2. Re-run the real pre-receipt counterexample and prove fresh-process completion from the existing succeeded Attempt without a second physical dispatch, second qualification closure, or new runtime authority.
3. Re-run the real ambiguous-result counterexample and prove exact independent verifier routing, canonical recovery, immutable historical `execution-unknown`, a new `recovered-completed` resolution, and exactly one physical external outcome.
4. Execute OIDC signing-key rotation against the staging realm and prove running-process JWKS refresh for a new `kid` plus fail-closed rejection of an unknown key after refresh.
5. Measure service-level RPO/RTO from a defined outage/last-accepted-write boundary through service-ready and semantic verification for both Administrative/DBOS PostgreSQL and Kernel state.
6. Re-run production preflight and the full Administrative repository CI/M5 workflows on the current supported Kernel pin.
7. Only after every mandatory row is PASS may PR #19 be marked Ready, merged, or described as M5 complete.

## Residual risk

Until the above evidence exists, the remaining risks are unverified real-staging recovery on the repaired Kernel baseline, terminal recovery after an ambiguous result-commit boundary, untested OIDC signing-key rotation, and unmeasured service-level RPO/RTO. Real staging happy-path, governance invalidation, least-privilege rejection, observability, and one response-loss reconciliation path are recorded as evidence, but they do not compensate for an unverified current recovery baseline.
