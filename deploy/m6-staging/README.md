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
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example build admin-postgres migrate odoo-bootstrap odoo keycloak agent-kernel api operations-api worker operations-console
docker compose --env-file .env.example up -d admin-postgres odoo-postgres keycloak
docker compose --env-file .env.example run --rm odoo-bootstrap
docker compose --env-file .env.example up -d odoo
docker compose --env-file .env.example run --rm migrate
docker compose --env-file .env.example --profile bootstrap run --rm foundation-bootstrap
docker compose --env-file .env.example up -d agent-kernel api operations-api worker operations-console
```

The verification token is intentionally not in `.env.example`. Materialize it
with the repository-owned Windows helper after the user has entered the token
from the Feishu app configuration into Windows Credential Manager:

```powershell
pwsh -File ..\windows\Set-AdministrativeM6FeishuVerificationToken.ps1 `
  -Command store-and-materialize
```

The helper stores the token in Windows Credential Manager and writes only the
task-scoped `.env.m6-secrets` file under this directory; it never prints the
value. The gateway app ID and app secret are read in-process from the existing
external `feishu_secrets` volume.

The long-connection handoff also uses a separate internal transport secret.
Materialize it with the companion helper; it stores a task-scoped Credential
Manager entry, adds `ADMIN_FEISHU_INGRESS_SHARED_SECRET` to the task-scoped
API environment file, and writes the corresponding `600`-mode file into the
external `feishu_secrets` volume without displaying the value:

```powershell
pwsh -File ..\windows\Set-AdministrativeM6FeishuIngressSharedSecret.ps1 `
  -Command generate-and-materialize -Force
```

The gateway reads that file as
`/run/secrets/administrative_ingress_shared_secret` through
`ADMINISTRATIVE_INGRESS_SHARED_SECRET_FILE`. It is deliberately separate from
the Feishu callback verification token: the callback token remains required
for direct HTTP callbacks, while the official long connection uses the
gateway-to-Admin transport credential for the metadata-only handoff.

## Runtime checks

```powershell
docker compose --env-file .env.example ps
Invoke-WebRequest http://127.0.0.1:18086/readyz
Invoke-WebRequest http://127.0.0.1:18087/readyz
Invoke-WebRequest http://127.0.0.1:18088/
Invoke-WebRequest http://127.0.0.1:18090/realms/m6/.well-known/openid-configuration
Invoke-WebRequest http://127.0.0.1:18089/web/database/selector
```

The model route is the already-running host LiteLLM process at
`127.0.0.1:4100`, using the OpenAI-compatible Responses protocol and the
`opencode-go/deepseek-flash` route. Do not stop or restart LiteLLM during this
staging run. The container reaches it through `host.docker.internal:4100`.

The recorded acceptance run for this stack is
`docs/acceptance/M6-staging-acceptance.md`.
The Operations Console OIDC client (`administrative-operations-console`) must
carry the standard Keycloak `basic` client scope so access tokens include the
OIDC `sub` claim. `infra/keycloak/m6-realm.json` declares that scope and adds
it to the client's default scopes; a long-lived staging realm that predates the
definition must be updated through the Keycloak Admin API, because
`--import-realm` skips an existing realm.

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
