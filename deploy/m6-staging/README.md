# M6 isolated staging

This directory is the only M6 staging control surface. It builds the merged
Administrative `main` tree together with the pinned Agent Kernel and runs an
isolated Compose project named `administrative-m6-staging`.

The topology is:

```text
live feishu-dify-gateway (official SDK long connection)
        -> metadata-only /admin handoff
        -> Admin API -> PostgreSQL IntakeReceipt/outbox
        -> Admin worker -> Feishu canonical API + ArtifactStore + LiteLLM
        -> Operations Console human ADMIT
        -> bridge_to_m5 -> Odoo/Keycloak authoritative refresh
        -> pinned Agent Kernel -> Odoo/Keycloak -> independent readback
```

The live gateway is not duplicated here. A second Feishu long connection using
the same app credentials would create competing delivery owners. Rebuild the
live gateway from its merged `main` only after this stack is healthy and use an
independent process for the gateway recreate.

## Start order

From PowerShell:

```powershell
Set-Location D:\infrastructure\compose\administrative-orchestrator\deploy\m6-staging
Copy-Item .env.example .env.m6-staging
docker compose --env-file .env.m6-staging config --quiet
docker compose --env-file .env.m6-staging build admin-postgres migrate odoo-bootstrap odoo keycloak agent-kernel api operations-api worker operations-console
docker compose --env-file .env.m6-staging up -d admin-postgres odoo-postgres keycloak
docker compose --env-file .env.m6-staging run --rm odoo-bootstrap
docker compose --env-file .env.m6-staging up -d odoo
docker compose --env-file .env.m6-staging run --rm migrate
docker compose --env-file .env.m6-staging --profile bootstrap run --rm foundation-bootstrap
docker compose --env-file .env.m6-staging up -d agent-kernel api operations-api worker operations-console
```

The verification token is intentionally not in `.env.example`. Materialize it
with the repository-owned Windows helper after the user has entered it into
Windows Credential Manager:

```powershell
pwsh -File ..\windows\Set-AdministrativeM6FeishuVerificationToken.ps1 `
  -Command store-and-materialize
```

The helper writes only the task-scoped `.env.m6-secrets` file under this
directory and never prints the value. The gateway app ID and app secret are
read in-process from the existing external `feishu_secrets` volume.

## Runtime checks

```powershell
docker compose --env-file .env.m6-staging ps
Invoke-WebRequest http://127.0.0.1:18086/readyz
Invoke-WebRequest http://127.0.0.1:18087/readyz
Invoke-WebRequest http://127.0.0.1:18088/
Invoke-WebRequest http://127.0.0.1:18090/realms/m6/.well-known/openid-configuration
Invoke-WebRequest http://127.0.0.1:18089/web/database/selector
```

The model route is the already-running host LiteLLM process at
`127.0.0.1:4102`. Do not stop or restart LiteLLM during this staging run. The
container reaches it through `host.docker.internal:4102`.

After the staging API is healthy, set the live gateway's local
`ADMINISTRATIVE_INGRESS_BASE_URL` to `http://host.docker.internal:18086`, keep
`ADMINISTRATIVE_ROUTE_PREFIX=/admin`, build the merged gateway `main`, and
recreate only `feishu-dify-gateway` from an independent process. Ordinary text
keeps the control-plane route; only messages beginning with `/admin` enter this
metadata-only lane.

## Artifact recovery

The worker artifact volume is content-addressed and separate from PostgreSQL.
Use the paired scripts in this directory to create a tar backup and restore it
into a new isolated Docker volume. The restore script refuses to target the
live staging volume unless an explicit override is supplied.

Do not use `docker compose down -v` or `docker system prune` here. The staging
volumes are part of the acceptance evidence and recovery path.
