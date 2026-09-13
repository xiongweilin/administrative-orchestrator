# Adaptive Investigation & Governed Reframing — isolated staging acceptance

Status: accepted for the recorded isolated staging scope only. This record
includes a follow-up real bounded draft effect, independent ERP read-back, and
adaptive revalidation; it is not a production-provider or independent
meta-controller deployment claim.

Acceptance date: 2026-09-13, Asia/Shanghai

This record describes the isolated staging run performed before PR #89 was
merged. The run's source identity is preserved below; the implementation was
subsequently merged into `main`.

## Deployment identity

- Staging source revision: `0864a99a841eadbb8849900b28e6421178c16b05`
  (PR #87 merge plus the Adaptive Investigation changes present in the
  staging working tree at acceptance time).
- Post-acceptance merged main revision: `7fb328a4023133848f0b49bb77d27ad12b8bd03f`
  (PR #89 squash merge).
- Follow-up payload-field wiring revision:
  `360a8df8ae04e1ca515ff001f7367d301748099d`.
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

## Follow-up real bounded effect and adaptive revalidation

The historical vertical above remains unchanged and intentionally records the
no-effect investigation path. A second synthetic case was then used to close
the real-provider portion of the acceptance without replaying the historical
case:

- Candidate: `557a178c-8dce-5dfa-b0a4-385e2ca24184`.
- Case: `6c268e92-c391-4a99-96b3-392d80e1920d`, authorized at epoch `3`.
- Qualification assessments:
  `d41b976c-3fbc-56b1-b0ba-9eead999e1dc`,
  `b5a15dbc-e073-5262-9910-b8c372c7a20c`, and
  `ce66ae0a-137f-53fb-bf7b-35e3ae431fb6`, all `qualified`.
- Evidence link: `ce118f50-ae12-4078-8961-a246fbe6a870`.
- Human decision: `c20f5a62-1f5c-45c2-8a2c-bb49ea3764a7`,
  `finance_approver`, approval satisfied.
- Bounded effect: `a6d34535-688c-52d1-bacc-587cbf2226e2`,
  operation `vendor_bill.create_draft`, status `succeeded`,
  provider reference `odoo:account.move:1`.
- Confirmed outcome: `37238150-62e1-592f-b4b1-4cf8650e737a`; realization
  `37337714-4eb5-5df9-bc7e-a2138ae742e8`, disposition `verified`.
- Independent Odoo read-back found exactly one matching `account.move`, with
  reference `ADAPTIVE-20260913-002`, `state=draft`, the governed subject
  identity, and the exact persisted payload. The final-stage Odoo addon uses
  `x_administrative_m9_payload_json`; the provider was wired to that field via
  `ADMIN_ODOO_TRANSACTION_PAYLOAD_FIELD`. No post/pay/settlement operation was
  attempted.

The first attempt against a separate synthetic invoice case failed closed
before any Odoo record was created because the provider's former hard-coded
M8 payload field was absent from the M9 staging addon. It produced no external
operation reference or outcome. The focused wiring change above made the
payload field deployment-scoped; the failed attempt was not replayed.

The completed case was then revalidated through the real configured
investigation model route:

- Investigation: `afd1be4d-2ce1-47a8-b170-6dd1c1299999`, status `reopened`.
- Proposal: `c7f20b59-9352-53cb-a507-f59529fd8bd7`, provenance
  `host-litellm`; three hypotheses, five missing-evidence items, and two
  reframings.
- Evidence: `ea3e3704-569a-4c7b-8c26-0c93c7c3acfe`, source
  `administrative-staging-v1:odoo-independent-readback`.
- Human assessment: `426737e7-b8e1-42c8-b59a-bf66db8e5c9c`,
  disposition `reopen_required`.
- Reopen: `23b51247-2282-52fb-9328-8a10a745b3d9`, authority epoch `3 → 4`;
  the case is now `gathering_facts`.
- Fresh closure reads show one historical epoch-3 Effect, one Outcome, and
  one verified realization; epoch 4 has zero new effects. The reopen record
  references one affected execution authorization, so the old effect remains
  historical reality while the new epoch is fenced from replay.

One earlier attempt inserted evidence before running the advisory and was
correctly placed in `requires_human_review` without a proposal or external
effect (`a7269852-57bb-4f62-a430-3088e3002f38`). The successful run follows
the accepted ordering: advisory proposal first, then evidence, human
assessment, and authorized reopen.

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
  evidence is complemented by the follow-up real draft effect/read-back
  vertical above.
- Follow-up real staging checks prove a single bounded Odoo draft was written
  and independently read back before the case was reopened; no settlement
  path was exercised.

## Intentional residuals

- The original recorded vertical is bounded synthetic staging evidence and
  remains immutable in meaning; the follow-up adds one isolated synthetic ERP
  draft and read-back, not a production-provider change.
- No separate real provider outcome-unknown/lost-ack recovery was exercised;
  cross-service restart/replay and local recovery suites remain the evidence
  for that boundary.
- No independent meta-controller deployment boundary was exercised; the real
  model route plus production-shaped adapter was exercised.
- The meta-controller service deployment boundary remains deferred because the
  owner repository currently exposes a policy/library layer rather than a
  stable independently deployable service. Repository tests separately cover
  durable investigation state across service restart and commitment lineage
  on authorized reopen.
- The four failed attempts are retained as failure evidence and were not
  rewritten or replayed under the successful investigation identity.
- The M9 staging project remains a separate operational surface. Do not use
  `docker compose down -v` against either project as part of ordinary cleanup.
