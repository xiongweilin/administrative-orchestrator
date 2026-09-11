# M7 isolated staging

This directory is the M7 staging control surface. It runs an isolated Compose
project named `administrative-m7-staging` with the merged Administrative build,
the pinned Agent Kernel revision, a separate PostgreSQL database, a separate
`m7` Keycloak realm, a separate Odoo database, and separate Kernel/artifact
volumes. The accepted M6 stack and its volumes remain outside this project.

The topology is:

```text
existing Feishu gateway long connection (one owner)
        -> temporary /admin handoff to M7 API
        -> M7 API -> PostgreSQL intake receipt/outbox
        -> M7 worker -> canonical Feishu artifact + LiteLLM interpretation
        -> Operations Console human ADMIT
        -> authoritative Odoo HR refresh (independent HR action)
        -> approval / effective-time wait / wake revalidation
        -> Administrative authority lifecycle + pinned Agent Kernel
        -> Keycloak disable + session revoke + Odoo deactivate
        -> independent readback -> completion -> responsibility discharge
```

The existing gateway is deliberately not duplicated: a second Feishu long
connection with the same app credentials would create competing delivery
owners. During the M7 exercise, temporarily point its `/admin` handoff at
`http://host.docker.internal:18091`; restore the M6 endpoint after the run.
Use the gateway's existing external `feishu_secrets` volume. Secret values
must not be copied into this directory or recorded in acceptance evidence.

## Start order

From PowerShell:

```powershell
Set-Location D:\infrastructure\compose\administrative-orchestrator\deploy\m7-staging
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example build admin-postgres migrate odoo-bootstrap odoo keycloak agent-kernel api operations-api worker operations-console
docker compose --env-file .env.example up -d admin-postgres odoo-postgres keycloak
docker compose --env-file .env.example run --rm odoo-bootstrap
docker compose --env-file .env.example up -d odoo
docker compose --env-file .env.example run --rm migrate
docker compose --env-file .env.example --profile bootstrap run --rm foundation-bootstrap
docker compose --env-file .env.example up -d agent-kernel api operations-api worker operations-console
```

The API reads the existing task-scoped Feishu ingress secret file through the
M6 staging secret locator declared in `compose.yaml`; Compose does not print
the value. The worker reads Feishu app credentials from the external
`feishu_secrets` volume, and the model route is the already-running host
LiteLLM process at `127.0.0.1:4100`. Do not stop or restart that process.

## Runtime checks

```powershell
docker compose --env-file .env.example ps
Invoke-WebRequest http://127.0.0.1:18091/readyz
Invoke-WebRequest http://127.0.0.1:18092/readyz
Invoke-WebRequest http://127.0.0.1:18093/
Invoke-WebRequest http://127.0.0.1:18095/realms/m7/.well-known/openid-configuration
Invoke-WebRequest http://127.0.0.1:18094/web/database/selector
```

The Odoo M7 addon declares the durable identity and termination fields used by
the authoritative reader and Kernel-owned deactivation capability. The seeded
M7 employee is initially active and has no termination schedule. The
termination schedule used for acceptance must be written later by the
independent HR administrator account, outside the offboarding case execution
path.

## Gateway handoff and rollback

Record the current gateway endpoint before changing it. Recreate only the
existing `feishu-dify-gateway` container with the temporary M7 endpoint, then
send the real `/admin` request and collect the redacted candidate reference.
After the M7 run, recreate the gateway with its prior M6 endpoint and verify
its health/readiness. The M7 Compose project itself does not own the gateway.

Do not use `docker compose down -v` or `docker system prune` here. The M7
volumes are the staging evidence and recovery boundary. Stop/remove only the
M7 project by explicit service/project name after preserving the acceptance
record and any required volume backup.

The acceptance record is
`docs/acceptance/M7-staging-acceptance.md`, created only after a fresh run from
the retained template.
