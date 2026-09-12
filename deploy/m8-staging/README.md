# M8 isolated staging

This directory is the isolated M8 staging control surface. It uses the
`administrative-m8-staging` Compose project, separate PostgreSQL/Keycloak/Odoo
databases, separate Kernel and artifact volumes, and host ports `18101`–`18105`.
It does not reuse the stopped M6/M7 services or their volumes.

The intended topology is:

```text
Feishu metadata handoff
  -> M8 Administrative receipt/outbox
  -> immutable raw artifact + DocumentRepresentation
  -> Operations Console human ADMIT
  -> typed transaction policy / qualification assessment
  -> approval + governance basis
  -> frozen financial obligations
  -> Kernel-owned Odoo draft capability
  -> independent Odoo readback
  -> exact outcome binding / completion or reconcile
```

The default model route is the already-running host LiteLLM endpoint at
`127.0.0.1:4100`; do not restart the shared LiteLLM process. The external
`feishu_secrets` volume remains the single credential mount. Secret values must
not be copied into this directory or acceptance evidence.

## Preflight and start order

From PowerShell:

```powershell
Set-Location D:\infrastructure\compose\administrative-orchestrator\deploy\m8-staging
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example build admin-postgres migrate odoo-bootstrap odoo keycloak agent-kernel api operations-api worker operations-console
docker compose --env-file .env.example up -d admin-postgres odoo-postgres keycloak
docker compose --env-file .env.example run --rm odoo-bootstrap
docker compose --env-file .env.example up -d odoo
docker compose --env-file .env.example run --rm migrate
docker compose --env-file .env.example --profile bootstrap run --rm foundation-bootstrap
docker compose --env-file .env.example up -d agent-kernel api operations-api worker operations-console
```

Verify only the M8 project:

```powershell
docker compose --env-file .env.example ps
Invoke-WebRequest http://127.0.0.1:18101/readyz
Invoke-WebRequest http://127.0.0.1:18102/readyz
Invoke-WebRequest http://127.0.0.1:18103/
Invoke-WebRequest http://127.0.0.1:18104/web/database/selector
Invoke-WebRequest http://127.0.0.1:18105/realms/m8/.well-known/openid-configuration
```

Do not use `docker compose down -v` or `docker system prune`. Preserve the
M8 volumes as the rollback/evidence boundary and stop the project by its
explicit Compose file after the acceptance record is safely copied.

The current redacted record is
`docs/acceptance/M8-staging-acceptance.md`. The template
`docs/acceptance/M8-staging-acceptance-template.md` is retained for future
isolated reruns. The Compose file must receive an explicit `AGENT_KERNEL_REF`;
it has no revision fallback, so a missing candidate revision fails closed.
