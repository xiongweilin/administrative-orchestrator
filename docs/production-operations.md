# Production operations and disaster recovery

This runbook describes the M5 production-shaped deployment and the M6 intake
additions. It preserves the Administrative/Agent Kernel authority split and
deliberately treats recovery as reconciliation of durable facts, not as
permission to improvise or blindly replay provider writes. M6 intake is an
upstream perception path; it does not create another execution authority.

## Reference topology

```text
OIDC / enterprise IdP
        |
        v
Administrative API -------- Operations API / Console
        |                          |
        +-----------+--------------+
                    |
        Administrative PostgreSQL
                    |
                 DBOS worker
                    |
             DBOS PostgreSQL
                    |
                    v
              Agent Kernel
          single physical writer
                    |
       +------------+-------------+
       |                          |
   Odoo HRIS                  Keycloak IAM
 writer + verifier          writer + verifier
       |                          |
       +------------+-------------+
                    |
          independent readback
```

`AdministrativeCase` is business workflow truth. DBOS owns durable wait/replay. Agent Kernel owns physical cut-over execution/recovery semantics. Odoo/Keycloak are external reality systems.

The M6 intake path is adjacent to the trusted-action path:

```text
Feishu callback
  -> verified metadata-only durable ingress
  -> Administrative PostgreSQL receipt/outbox
  -> worker canonical fetch
  -> ArtifactStore + source/evidence lineage
  -> interpretation/candidate/review
  -> optional human-confirmed bridge_to_m5
  -> existing IngressReceipt / AdministrativeRequest / M5 case path
```

The callback does not wait for canonical fetch or model processing. No Feishu
message body or extracted content belongs in the receipt, outbox payload, or
ordinary operational logs.

## Required production properties

The production control plane must satisfy all of these before startup:

- `ADMIN_RUNTIME_PROFILE=production`;
- `ADMIN_AUTH_MODE=oidc` with HTTPS issuer and asymmetric JWKS verification;
- `ADMIN_KERNEL_BRIDGE_MODE=cutover`;
- `ADMIN_EXTERNAL_EFFECTS_ENABLED=true`;
- `ADMIN_KERNEL_SUPPORTED_REVISION` equals the revision supported by the deployed Administrative build;
- `ADMIN_AUTO_CREATE_SCHEMA=false`; migrations run explicitly through Alembic;
- Administrative, worker, and DBOS durable stores use PostgreSQL;
- Odoo and Keycloak production endpoints use HTTPS;
- authoritative reader, writer, and verifier credential references are configured;
- writer and verifier identities/secrets are distinct;
- durable external request-identity fields/attributes are configured;
- `PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH` is an absolute path on durable single-writer storage.

When M6 intake is enabled, the deployment must additionally provide
configuration references for the Feishu callback verification (and optional
signed-header) material, the canonical message read credential, the model
gateway, the durable artifact root, and the current Feishu-to-Administrative
identity bindings. The worker runtime must inject the configured Feishu
processor; the relay intentionally fails closed when processing dependencies
are absent. The production Compose reference mounts
`administrative-intake-artifacts` at the configured artifact root for the
worker; the deployment backup policy must include that volume alongside the
Administrative database. These are deployment prerequisites, not evidence
that the external systems have already run successfully.

Run the static deployment gate before starting the application processes:

```bash
uv run python scripts/production_preflight.py
```

The command validates configuration and the presence of configured secret environment variables. It does not print secret values.

## Credential separation

Use separate service identities for these trust domains:

| System | Identity | Minimum responsibility |
| --- | --- | --- |
| OIDC | Administrative API | token validation only; no organization-role minting |
| Odoo | reader | authoritative HR facts required by policy/governance |
| Odoo | writer | only the bounded HRIS mutations delegated to Kernel |
| Odoo | verifier | read-only independent postcondition observation |
| Keycloak | reader | directory/identity facts required by Administrative logic |
| Keycloak | writer | bounded IAM mutations delegated to Kernel |
| Keycloak | verifier | read-only independent postcondition observation |

Writer and verifier accounts must not be aliases for the same account/client. Production preflight rejects that configuration.

Secret values belong in the deployment secret manager/environment. Domain records, Administrative evidence, and Kernel evidence store credential configuration references, not raw credentials.

## Startup sequence

1. Provision PostgreSQL, durable Kernel storage, and the durable M6 artifact
   volume when intake is enabled.
2. Restore required secrets from the platform secret manager.
3. Run `alembic upgrade head` against the Administrative PostgreSQL database.
4. Ensure the DBOS system database exists and is reachable.
5. Run `scripts/production_preflight.py`.
6. Start Agent Kernel at the supported pinned revision using the production bounded-effect factory:

   ```bash
   PORTABLE_RUNTIME_BOUNDED_DOMAIN_EFFECT_FACTORY=scripts.production_kernel_stack:build \
   python -m uvicorn portable_runtime.public_contracts.http:create_configured_public_app \
     --factory --host 0.0.0.0 --port 8020
   ```

7. Start the observed Administrative API:

   ```bash
   python -m uvicorn administrative_orchestrator.api_observed:app \
     --host 0.0.0.0 --port 8000
   ```

8. Start the observed Operations API separately:

   ```bash
   python -m uvicorn administrative_orchestrator.operations_app:app \
     --host 0.0.0.0 --port 8001
   ```

9. Start the DBOS worker only after the databases, Kernel, and external provider routes are ready.
10. Expose the Operations Console behind the same enterprise ingress/IdP policy as the Operations API.

Do not use the development Compose topology as a production manifest. It intentionally uses reproducible development authentication and sandbox providers.

## Readiness and cut-over checks

Before enabling worker traffic:

- `/readyz` reports the expected production profile and source kinds;
- Kernel `/v1/contracts` is reachable from the worker network;
- the configured Kernel contract revision matches the Administrative supported revision;
- Odoo reader can resolve a staging employee and department;
- Keycloak reader can resolve a staging identity;
- writer identities can perform only the intended bounded mutation;
- verifier identities can read but cannot perform the writer mutation;
- the durable Odoo request field and Keycloak request attribute are present and queryable;
- Prometheus can scrape `/metrics` on the observed Administrative surfaces.

For M6 intake staging, also verify:

- Feishu URL verification and authenticated callback behavior against the
  actual staging provider, including a negative token/signature case;
- one accepted callback produces one receipt and one metadata-only outbox
  event, while a duplicate is idempotent;
- the asynchronous worker can fetch the canonical message, verify provider
  tenant/message/sender/thread identity, persist the artifact/evidence digest,
  and resolve the current Administrative identity binding;
- the configured artifact root is durable and a digest mismatch, missing
  object, or unavailable store fails closed;
- the intake review permission is distinct from read-only operations access;
- a final human assessment is required before `bridge_to_m5`, and the bridge
  only enters the supported onboarding path.

For a first cut-over, begin with a bounded staging cohort. A provider or network failure after a write must be treated as execution-unknown and reconciled by durable request identity; it must not trigger an operator retry button.

## Observability contract

The observed HTTP wrappers expose `/metrics` and return `X-Correlation-ID` on every response.

Key metrics:

```text
administrative_http_requests_total
administrative_http_request_duration_seconds
administrative_authoritative_fact_refresh_total
administrative_governance_revalidation_total
administrative_connector_outcome_total
administrative_identity_lifecycle_total
```

Metric labels are deliberately low-cardinality. Do not add `case_id`, `principal_id`, external subject, request UUID, or correlation ID as Prometheus labels. Those identifiers belong in structured logs and durable domain/Kernel records.

Initial operating targets are defined in `docs/milestones/M5.md`. `GOVERNANCE_STALE` is a correctness event, not an availability defect.

## PostgreSQL backup and restore

Production infrastructure must back up both:

1. the Administrative PostgreSQL database;
2. the DBOS system PostgreSQL database.

The repository M5 DR job proves a real custom-format Administrative backup/restore cycle with PostgreSQL 17:

```text
Alembic migrate
-> seed durable authority + identity lifecycle state
-> pg_dump -Fc
-> DROP public schema
-> pg_restore --exit-on-error
-> semantic verification
```

For production, use the platform's encrypted snapshot/PITR facility where available and retain a documented `pg_dump`/`pg_restore` path for portable recovery. The DBOS database must be included in the infrastructure backup policy even though the repository's semantic `pg_dump` fixture focuses on Administrative authority state.

Do not restore only the API database while intentionally discarding DBOS durability unless the incident procedure explicitly accounts for that loss.

## Agent Kernel state backup

The current supported bounded-domain-effect recovery store is SQLite. The M5 reference topology therefore runs it as a single writer on durable storage.

Create an online consistent backup while the Kernel is running:

```bash
uv run python scripts/kernel_state_backup.py backup \
  "$PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH" \
  /secure-backups/kernel-$(date -u +%Y%m%dT%H%M%SZ).db
```

The backup implementation uses SQLite's backup API, runs `PRAGMA quick_check`, atomically publishes the backup, and writes a `.sha256` manifest.

Verify a backup independently:

```bash
uv run python scripts/kernel_state_backup.py verify /secure-backups/kernel-20260909T090000Z.db
```

A mismatched SHA-256 manifest or failed SQLite integrity check makes the backup unusable.

## Agent Kernel restore

Do not restore into a live Kernel writer.

1. Stop or fence the Kernel writer.
2. Stop/fence Administrative workers that may submit new cut-over Work.
3. Select the incident-approved backup and run `verify`.
4. Restore into the configured durable state path:

   ```bash
   uv run python scripts/kernel_state_backup.py restore \
     /secure-backups/kernel-approved.db \
     "$PORTABLE_RUNTIME_ADMIN_PRODUCTION_STATE_PATH" \
     --force
   ```

5. Start Kernel and verify `/v1/contracts`.
6. Start the Administrative worker.
7. Inspect cases/Attempts in `reconciling`, `waiting`, or reopen-required states.
8. Let canonical Kernel recovery reconcile durable request identities.

Never convert a restored `execution-unknown` Attempt to success by operator assertion, and never invoke the provider a second time merely because a response was lost.

## Cross-store recovery ordering

Administrative PostgreSQL, DBOS PostgreSQL, Kernel state, and external systems are independent durability domains. A backup set is therefore not automatically a distributed transaction snapshot.

For disaster recovery:

1. fence new mutating traffic;
2. restore Administrative and DBOS databases to the incident-approved recovery point;
3. restore/fence the Kernel state to the corresponding or safest available point;
4. start Kernel before the worker resumes submissions;
5. allow request-identity reconciliation to resolve ambiguous external effects;
6. refresh authoritative HRIS facts before continuing governed reality transitions;
7. reopen cases when governance/evidence freshness cannot be proven.

When recovery points differ, prefer conservative reopen/reconcile over inventing completion or retry authority.

## Failure procedures

### OIDC unavailable

- Keep production authentication fail closed.
- Do not switch to development/JWT shared-secret mode as an incident workaround.
- Existing background Work may continue only if its Administrative authority and external-fact validity remain provable.

### Odoo/Keycloak unavailable before a write

- Kernel may report unavailable/failed according to the provider contract.
- Administrative cases remain waiting/reconciling as appropriate.
- Do not bypass through direct admin-console mutations without recording a separate controlled external change and subsequent reconciliation.

### Transport failure after a possible write

- Treat as execution-unknown.
- Preserve Kernel state and durable external request identity.
- Reconcile; do not blindly invoke again.

### Verifier unavailable

- Provider success is insufficient for Administrative completion.
- Keep the obligation unresolved until independent verification can run.

### Authoritative fact changed after approval

- Revalidation returns stale/changed.
- Administrative case reopens under `GOVERNANCE_STALE` before further reality mutation.

### Kernel unavailable

- Stop new cut-over submissions or disable external effects.
- Do not reroute physical writes through the Administrative sandbox/provider path.
- Restore/restart Kernel and resume from durable Attempt state.

### Feishu callback rejected or canonical fetch unavailable

- Return the authenticated-boundary error for an invalid callback; do not
  enqueue unverified metadata.
- Treat a canonical fetch failure as an intake processing failure. Preserve the
  verified receipt and source lineage, and do not fabricate a candidate or
  admission.
- Do not place callback bodies, provider tokens, access tokens, or document
  content in incident tickets, logs, or the acceptance record.

### Artifact storage unavailable or corrupt

- Keep the source/receipt state pending or failed according to the intake
  worker contract.
- Do not reinterpret a missing or digest-mismatched object and do not promote
  a candidate from incomplete evidence.
- Restore the artifact store through the platform's approved storage recovery
  procedure, then re-run the bounded integrity check before resuming intake.

### Candidate bridge or authoritative refresh conflict

- A model suggestion, candidate `CLAIM`, or human confirmation does not become
  `AUTHORITATIVE`.
- Use the existing HRIS refresh/revalidation path for authoritative fields.
- If the current authoritative record is stale or changed, stop the governed
  transition and handle the case under `GOVERNANCE_STALE`; do not resolve it
  by editing the candidate or asserting provider success.

## Safe rollback from a deployment

If a release must be rolled back before any ambiguous provider execution:

1. disable new external effects;
2. drain/fence workers;
3. restore the previously supported Administrative/Kernel build pair;
4. verify the pinned contract revision;
5. resume only after readiness checks.

If any effect is execution-unknown, preserve the newer Kernel state until reconciliation is complete. Rollback is not permission to erase Attempt evidence or replay the external mutation.

## Real staging acceptance

Public CI cannot exercise enterprise credentials or provider delivery. Before
production acceptance, execute the M5 checklist in `docs/milestones/M5.md` and
the M6 record in
`docs/acceptance/M6-staging-acceptance-template.md` against the actual
Feishu/IdP/Odoo/Keycloak/Kernel staging topology and least-privilege accounts.

Record at minimum:

- Administrative build SHA;
- Agent Kernel revision;
- staging IdP/Odoo/Keycloak environment identifiers;
- writer/verifier credential configuration references (never secret values);
- injected ambiguity scenario and reconciliation evidence;
- independent readback mismatch scenario;
- authoritative-fact-change reopen evidence;
- backup/restore exercise timestamps and achieved RPO/RTO;
- dashboards/log correlation evidence.

For M6, also record only non-sensitive evidence references for:

- Feishu callback verification, duplicate delivery, canonical fetch, and
  metadata-only durable ingress;
- source/artifact/evidence digest lineage and artifact corruption/missing
  object fail-closed behavior;
- current identity binding and conversation continuity;
- human review, `bridge_to_m5` constraints, promotion idempotency, and the
  resulting candidate `CLAIM` boundary;
- authoritative HRIS refresh/revalidation, including a changed/stale case
  handled under `GOVERNANCE_STALE`;
- the actual provider-to-M5 run, if performed, with external evidence
  references rather than provider payloads or credentials.

Do not fill the record with invented provider, Odoo, Keycloak, Kernel, or
model-provider results. Until the real-staging record exists with fresh
evidence, M6 remains incomplete even if repository implementation and CI are
green.
