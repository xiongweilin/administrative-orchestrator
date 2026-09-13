# M9 isolated staging

This directory is the isolated M9 staging control surface. It uses the
`administrative-m9-staging` Compose project, separate PostgreSQL/Keycloak/Odoo
databases, separate Kernel and artifact volumes, and host ports `18201`–`18205`.
It does not reuse the stopped M6/M7 services or their volumes.

The intended topology is:

```text
Feishu transcript metadata handoff
  -> M9 Administrative receipt/outbox
  -> immutable transcript artifact + EvidenceSpan
  -> candidate commitment queue
  -> human speaker/due-time qualification
  -> meeting-commitment case + approval/governance
  -> persistent Kernel responsibility proposal
  -> fixed-template internal Feishu confirmation/reminder
  -> transport ledger + independent delivery readback
  -> committer fulfillment attestation
  -> explicit responsibility discharge
```

The default model route is the already-running host LiteLLM endpoint at
`127.0.0.1:4100`; do not restart the shared LiteLLM process. The external
`feishu_secrets` volume remains the single credential mount. Secret values must
not be copied into this directory or acceptance evidence.

## Preflight and start order

From PowerShell:

```powershell
Set-Location D:\infrastructure\compose\administrative-orchestrator\deploy\m9-staging
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example build admin-postgres migrate odoo-bootstrap odoo keycloak agent-kernel api operations-api worker operations-console
docker compose --env-file .env.example up -d admin-postgres odoo-postgres keycloak
docker compose --env-file .env.example run --rm odoo-bootstrap
docker compose --env-file .env.example up -d odoo
docker compose --env-file .env.example run --rm migrate
docker compose --env-file .env.example --profile bootstrap run --rm foundation-bootstrap
docker compose --env-file .env.example up -d agent-kernel api operations-api worker operations-console
```

The M9 Gateway is a separately owned process and must be started or pointed at
through `ADMIN_COMMUNICATION_GATEWAY_BASE_URL`; do not start a second Feishu
long-connection owner in this project. The worker and Kernel receive only the
redacted transport configuration and external secret mounts.

Verify only the M9 project:

```powershell
docker compose --env-file .env.example ps
Invoke-WebRequest http://127.0.0.1:18201/readyz
Invoke-WebRequest http://127.0.0.1:18202/readyz
Invoke-WebRequest http://127.0.0.1:18203/
Invoke-WebRequest http://127.0.0.1:18204/web/database/selector
Invoke-WebRequest http://127.0.0.1:18205/realms/m9/.well-known/openid-configuration
```

Do not use `docker compose down -v` or `docker system prune`. Preserve the
M9 volumes as the rollback/evidence boundary and stop the project by its
explicit Compose file after the acceptance record is safely copied.

The current redacted record is
`docs/acceptance/M9-staging-acceptance.md`. The template
`docs/acceptance/M9-staging-acceptance-template.md` is retained for future
isolated reruns. The Compose file must receive an explicit `AGENT_KERNEL_REF`;
it has no revision fallback, so a missing candidate revision fails closed.

