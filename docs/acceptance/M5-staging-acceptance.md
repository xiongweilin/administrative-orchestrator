# M5 staging acceptance record

Status: **BLOCKED — real staging inputs are not available in this environment**

This record is an evidence boundary, not a production-readiness claim. Repository CI and local configuration checks are recorded separately from acceptance against real OIDC, Odoo, Keycloak, network, credential-scope, and disaster-recovery systems.

## Environment and repository evidence

| Item | Observed value / result |
| --- | --- |
| Acceptance observation time | 2026-09-09T18:56:47+08:00 |
| Administrative branch | `codex/m5-production-trust-reality-integration` |
| Administrative commit | `26531bd152d39004e64e59e49ebea959ee269714` |
| Administrative base | `main` at `cddb5bc5f34ece1a6dffa683f089310e670fcd0d` |
| Supported Agent Kernel revision | `6b154f54a140da9fa97d6556720ae5744e95ffce` |
| Local Agent Kernel checkout | `main` at the supported revision; clean |
| PR #19 | open, Draft, mergeable state `clean`, no reviews or inline review comments observed |
| Repository CI | PASS — run `#283` |
| M5 Production Trust workflow | PASS — run `#49` |
| Production Compose rendering with non-secret example configuration | PASS |
| Actual staging deployment | BLOCKED — no Administrative/OIDC/Kernel/Odoo/Keycloak staging topology is configured or running here |
| Actual staging environment file | ABSENT; only `.env.production.example` is present |

The CI runs prove repository contracts, migration/restart behavior, cutover/recovery fixtures, Operations Console build, and DR test fixtures. They do not prove enterprise credentials, network policy, least-privilege scopes, or measured staging RPO/RTO.

## Staging gate results

| Gate | Result | Evidence boundary |
| --- | --- | --- |
| OIDC discovery and JWKS | BLOCKED | No configured staging issuer or reachable staging IdP was available |
| OIDC token rejection and key rotation | BLOCKED | Requires real staging tokens and signing-key rotation |
| OIDC subject to IdentityBinding to Principal | BLOCKED | Requires a real staging login and durable binding operation |
| IdP groups isolated from Administrative roles | BLOCKED | Requires a real IdP identity with groups but no Administrative role assignment |
| Odoo authoritative read | BLOCKED | No configured staging Odoo reader reference or staging fixture |
| Field-level fact provenance and freshness | BLOCKED | Depends on the real Odoo authoritative read |
| Governance invalidation after external fact change | BLOCKED | Requires changing a non-production Odoo fixture between approval and execution |
| Odoo Kernel physical cutover | BLOCKED | No staging writer/verifier identities or staging Odoo endpoint |
| Keycloak Kernel physical cutover | BLOCKED | No staging realm, writer/verifier clients, or staging endpoint |
| Ambiguous provider result and reconciliation | BLOCKED | Requires a real post-commit response-loss window against staging providers |
| Fresh-process Kernel recovery | BLOCKED for staging | Repository recovery CI is PASS; no staging Kernel deployment/state path is available |
| Writer/verifier identity isolation | BLOCKED | Credential configuration and provider-side permission checks are unavailable |
| Operations Console OIDC/PKCE | BLOCKED for staging | Console build CI is PASS; no staging IdP and Operations API are available |
| Live correlation and low-cardinality metrics | BLOCKED for staging | No running M5 deployment is available to exercise the correlation chain |
| Administrative PostgreSQL backup/restore and measured RPO/RTO | BLOCKED for staging | CI DR fixture is PASS; no staging database/backup target is available |
| Kernel state backup/restore and measured RPO/RTO | BLOCKED for staging | Repository Kernel DR tests are PASS; no staging Kernel state store is available |
| Production preflight against real deployment configuration | BLOCKED | Required production configuration and credential references are absent from this environment |

No staging gate is marked PASS based on a mock, local unrelated service, or repository-only test.

## Missing configuration references

The following configuration references are not present in the current process/deployment environment. Names are listed without values by design.

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

The supported Kernel revision remains the repository value `6b154f54a140da9fa97d6556720ae5744e95ffce`; no revision promotion is authorized by this blocked record.

## Required unblock evidence

To continue without changing the architecture or weakening a gate, provide the staging configuration through the approved secret/configuration channel and execute the checklist against non-production fixtures:

1. reachable OIDC issuer, Odoo, and Keycloak endpoints;
2. reader, writer, and verifier credential references with distinct writer/verifier identities;
3. a staging Administrative/PostgreSQL/DBOS/Kernel/Operations API/Console deployment;
4. non-production employee, identity, and approval fixtures;
5. controlled transport-failure injection for ambiguity/reconciliation;
6. PostgreSQL and Kernel backup/restore targets with measured RPO/RTO;
7. the resulting PASS/FAIL evidence and residual-risk record.

Until those checks are executed, PR #19 must remain Draft and M5 must not be declared complete, production-ready, or merged.

## Residual risk

The following remain unverified in this environment: real identity binding, external authority scope, authoritative fact freshness, provider least privilege, physical Odoo/Keycloak effects, ambiguous-result exactly-once proof, live observability, and measured disaster-recovery objectives.
