# M6 staging acceptance evidence template

Status: **template only — not an acceptance result**.

Use this record only for a real staging run of the M6 provider-to-review and
human-confirmed M5 boundary. Do not enter secrets, tokens, private keys,
credential values, callback bodies, message text, document text, attachments,
model prompts/responses, or other sensitive source content. Use stable
redacted identifiers, digests, timestamps, configuration references, and
links to access-controlled evidence instead. `PENDING` means the check was not
run; it must not be changed to `PASS` from a unit test or synthetic fixture.

M6 is **not complete until this record contains fresh real-staging evidence**
for all applicable required checks, the required CI gates are green, and the
final changes are merged to `main` with post-merge main CI green.

## Run metadata

| Field | Value |
| --- | --- |
| Administrative repository commit | `[SHA]` |
| Staging run identifier | `[redacted run/reference]` |
| Run start/end (UTC) | `[timestamp]` |
| Staging environment reference | `[non-secret environment identifier]` |
| Feishu tenant/app reference | `[configuration reference only]` |
| IdP/Odoo/Keycloak/Kernel environment references | `[configuration references only]` |
| Artifact-store adapter/root reference | `[configuration reference only]` |
| Model gateway/profile reference | `[configuration reference only]` |
| Intake reviewer / approver references | `[principal or ticket references]` |
| Evidence index / ticket | `[access-controlled link or ID]` |

## Evidence rules

- [ ] Every evidence reference is redacted and contains no secret or source
      body.
- [ ] Provider, IdP, Odoo, Keycloak, Kernel, and model results below are based
      on this staging run, not on repository tests or local fixtures.
- [ ] Any skipped, blocked, or not-applicable check has a reason and owner.
- [ ] Correlation IDs, request/event IDs, case IDs, artifact digests, and
      timestamps are sufficient to locate protected evidence without copying
      its payload.

## Acceptance matrix

Record `PASS`, `FAIL`, `PENDING`, or `N/A` and link only to protected evidence
references.

| Gate | Required staging observation | Status | Evidence reference / notes |
| --- | --- | --- | --- |
| A — Feishu authenticity | URL verification and a valid staging callback are accepted; invalid token/signature or stale signed callback is rejected; no unverified event is enqueued. | `[ ]` | `[reference]` |
| B — Durable ingress | One accepted callback creates one verified `IntakeReceipt` and one `intake.feishu.received` outbox event in the same durable path; duplicate delivery is idempotent; conflicting delivery identity fails closed. | `[ ]` | `[reference]` |
| C — No-body boundary | Receipt, outbox payload, ordinary logs, and this record contain metadata/digests/references only; no callback body, message text, document text, token, or model content is copied. | `[ ]` | `[reference]` |
| D — Canonical source lineage | The worker fetches the canonical message after acceptance and verifies provider tenant, message, sender, and thread identity; `SourceArtifact`/`EvidenceSpan` lineage is durable and digest-addressed. | `[ ]` | `[reference]` |
| E — Artifact integrity foundation | A non-sensitive fixture/reference is stored, read, and digest-verified; missing/corrupt/unavailable artifact behavior fails closed. Record digest/reference only, never the fixture body. | `[ ]` | `[reference]` |
| F — Identity/conversation | The current Feishu identity binding resolves to the expected Administrative principal; displayed sender text is not used as a principal; tenant/thread continuity and ordering are enforced. | `[ ]` | `[reference]` |
| G — Candidate boundary | Interpretation and candidate records retain source/evidence lineage; candidate facts are only `CLAIM` or `ATTESTED_CANDIDATE`; model/provider failure retains source lineage without fabricating admission. | `[ ]` | `[reference]` |
| H — Human confirmation | A reviewer with intake-review permission records a final human `IntakeAssessment(ADMIT)` with basis; model confidence alone cannot promote; read-only operations access cannot approve. | `[ ]` | `[reference]` |
| I — `bridge_to_m5` boundary | `bridge_to_m5=true` succeeds only for `employee-onboarding` with a human-selected `subject_ref`; unsupported case kinds/missing subject/conflicting lineage are rejected; no direct Kernel/provider call occurs. | `[ ]` | `[reference]` |
| J — Promotion idempotency | Promotion creates at most one `PromotionRecord`, `IngressReceipt`, `AdministrativeRequest`, and case; replay returns the existing lineage and a conflicting requester is rejected. | `[ ]` | `[reference]` |
| K — Claim preservation | The bridged M5 fact snapshot and per-field assertions remain `FactAuthority.CLAIM`; human confirmation is not recorded as `AUTHORITATIVE`. | `[ ]` | `[reference]` |
| L — Authoritative refresh | The approved HRIS refresh/revalidation path is exercised as applicable; only approved current HRIS fields become `AUTHORITATIVE`; request-only fields remain claims. | `[ ]` | `[reference]` |
| M — Stale/changed truth | A changed or stale authoritative dependency blocks continuation and is handled through the existing `GOVERNANCE_STALE` reopen/reassessment boundary; no operator assertion bypasses it. | `[ ]` | `[reference]` |
| N — M5 vertical slice | If the real provider-to-M5 path is in scope for this run, the actual Odoo/Keycloak/Kernel/independent verification observations are recorded by protected references only. If not run, leave `PENDING` and state why. | `[ ]` | `[reference]` |
| O — Restart/recovery | A worker/API restart or bounded lease recovery does not duplicate the receipt, candidate, promotion, request, or case; unresolved processing remains recoverable from durable state. | `[ ]` | `[reference]` |
| P — Observability | Correlation, metrics, review audit, and failure/reconciliation evidence are discoverable without high-cardinality sensitive payloads. | `[ ]` | `[reference]` |

## External results and intentional leftovers

Do not infer results for a provider or system that was not actually exercised.

| System / boundary | Fresh result | Protected evidence reference | Owner / next action |
| --- | --- | --- | --- |
| Feishu callback + canonical API | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |
| Identity provider / identity binding | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |
| Odoo authoritative reader | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |
| Keycloak identity/connector path | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |
| Agent Kernel cut-over/verification path | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |
| Model gateway/profile | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |
| Artifact storage | `[PASS/FAIL/PENDING]` | `[reference]` | `[owner/action]` |

## Closure decision

- [ ] All applicable required gates above have fresh real-staging evidence.
- [ ] No secrets or source/document bodies are present in this record.
- [ ] Required repository CI is green for the final commit.
- [ ] Final changes are merged to `main`.
- [ ] Post-merge main CI is green.
- [ ] No external result has been inferred from code, tests, or configuration
      presence.

Final status: `[M6 incomplete / M6 accepted for recorded scope]`

Until all applicable evidence and closure conditions are checked, retain the
status **M6 incomplete pending real staging evidence**.
