# Adaptive Investigation & Governed Reframing — isolated staging acceptance

Status: accepted for the recorded isolated staging scope only. This record is
not a production-provider or independent meta-controller deployment claim.

Acceptance date: 2026-09-13, Asia/Shanghai

## Deployment identity

- Administrative base revision: `0864a99a841eadbb8849900b28e6421178c16b05`
  (PR #87 merge; the staging image also contains the current uncommitted
  Adaptive Investigation changes recorded in the working tree).
- Agent Kernel pin: `706cb3514c7edd030518f016a8f9b232b98f8166`.
- Migration head: `0031_adaptive_investigation`.
- Compose project: `administrative-staging-v1`.
- Admin image: `administrative-orchestrator:administrative-staging-v1`.
- External ports: `18301` Admin API, `18302` Operations API, `18303`
  Operations Console/OIDC issuer, `18304` Odoo, `18305` Keycloak.
- M9 project `administrative-m9-staging`, its volumes, and its containers were
  not recreated or reused for the business database.

The final-stage project has its own PostgreSQL, Keycloak, Odoo, Kernel state,
artifact, and default-network resources. The shared `feishu_secrets` mount is
read-only and no Feishu long-connection owner was started.

## Advisory route

- Route: existing host LiteLLM at `host.docker.internal:4100/v1`.
- Protocol: OpenAI-compatible Responses.
- Model: `opencode-go/deepseek-flash`.
- Provider provenance: `host-litellm`; version `configured-staging`.
- Prompt reference: `adaptive-investigation-v1`.
- Investigation output limit: 6000 tokens; client timeout: 60 seconds;
  application budget remained `max_model_calls=1` for the accepted request.
- No independently deployed `meta-controller` service was exercised.

The model route was used only through the narrow `InvestigationClient` boundary.
It received bounded references and constraints; it did not receive provider
write credentials, Kernel credentials, or unrestricted tenant data.

## Recorded vertical

The synthetic staging subject was admitted through the real OIDC-authenticated
Admin API as `person:m9-reviewer` and received a persisted decision and
approval satisfaction. The prior approval record remains historical:

- Case: `cae1108e-8a81-4634-834a-c3891ce575b1`.
- Approval satisfaction: `6765b95c-1e5b-5f7c-b8ce-cfe2b782ec21`.
- Decision: `bf85df6f-bf4e-49ad-aa64-ea687ee8b9aa`.
- Governance basis: `9e3e9050-e926-54ee-929d-b285425e0de4`, authority epoch 2.
- The running worker had already moved the case into a later revalidation
  epoch before the Adaptive request; no historical record was deleted.

Four earlier real-route attempts were persisted as failed closed, without
changing case authority:

- `f50c7194-f31c-44f8-8e81-51dd2c207574` — failed.
- `426e34d9-c622-4802-926a-a3edec01498c` — failed.
- `0e0d27bc-0f0f-4324-964c-d626568c5307` — failed.
- `24106718-ed8c-4985-9a9b-76784d093f47` — failed.

After the Responses contract, numeric uncertainty contract, image rebuild, and
staging timeout correction were deployed, the accepted advisory request was:

- Investigation: `cb5e0b59-4390-48ed-b187-dfca79a1f83b`.
- Proposal: `d812ffa8-1d06-5b25-9201-1cb67fbe0d06`.
- Proposal provenance: `host-litellm` / `opencode-go/deepseek-flash`.
- Proposal shape: 2 hypotheses, 3 missing-evidence items, 2 proposed
  reframings, and 3 possible reopen targets.
- No proposal field created a Decision, ApprovalSatisfaction,
  ExecutionAuthorization, Kernel Work, Effect, or provider command.

The evidence and qualification path then completed through the real Operations
API:

- Evidence request: `dbd6f944-c741-477c-98aa-e0fa75bb883b`.
- Evidence: `4800aa00-8a2d-4402-a337-24a67e8e743b`.
- Human assessment: `270164a4-3bfb-43d9-a0ab-531770a5638b`, disposition
  `reopen_required`.
- Reopen record: `8035eb3b-4342-5ef5-a206-383dee8d5b80`.
- Authority epoch: `3 → 4`.
- Case status after reopen: `gathering_facts`.
- Replaying the same authorization idempotency key returned `created=false`,
  kept epoch 4, and left exactly one reopen history record.

The resulting investigation is `reopened`, with one persisted proposal, one
evidence record, and one assessment. The staging case has zero execution
authorizations, zero effects, and zero outcomes; therefore no real provider
read-back is claimed for this vertical.

## Fresh verification

- Full `uv run pytest -q`: passed; the repository's two existing skips and
  dependency deprecation warnings remain unchanged.
- Full `uv run ruff check .`: passed.
- `uv run python -m compileall -q src tests alembic`: passed.
- Adaptive targeted suite: passed.
- SQLite migration round-trip through `0031_adaptive_investigation`: passed.
- `administrative-staging-v1` Compose config: passed.
- New Admin API, Operations API, Kernel, Odoo, Keycloak, and console readiness
  checks: passed.
- Operations API audit contained `governance.invalidated`,
  `authority.epoch_advanced`, and `case.reopened`.
- Local counterexample suite proves stale authorization is rejected after an
  epoch change while the historical Effect remains persisted. This staging
  vertical intentionally created no effect, so the real staging evidence is
  limited to the no-effect branch.

## Intentional residuals

- The evidence in this vertical is bounded synthetic staging evidence, not an
  independent HRIS/provider change. A future acceptance may add an external
  authoritative read-back vertical without changing this record's scope.
- No real Kernel Effect was admitted; provider read-back and effect recovery
  are therefore not claimed here.
- No independent meta-controller deployment boundary was exercised; the real
  model route plus production-shaped adapter was exercised.
- The four failed attempts are retained as failure evidence and were not
  rewritten or replayed under the successful investigation identity.
- The M9 staging project remains a separate operational surface. Do not use
  `docker compose down -v` against either project as part of ordinary cleanup.
