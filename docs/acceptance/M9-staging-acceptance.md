# M9 isolated staging acceptance

Status: runtime acceptance evidence recorded; repository closure remains
pending until the Administrative and Gateway PRs are merged, post-merge main
revisions and CI are verified, and the annotated acceptance tag is created.

This record contains identifiers, states, and digests only. It intentionally
does not contain transcript bodies, message bodies, access tokens, HMAC keys,
provider secrets, or raw identity credentials.

## Deployment identity

- Compose project: `administrative-m9-staging`
- Admin revision under test: `codex/m9-communication-commitment` (working tree)
- Gateway revision under test: `codex/m9-communication-transport` (working tree)
- Agent Kernel revision: `706cb3514c7edd030518f016a8f9b232b98f8166`
- migration head: `0030_m9_communications`
- acceptance date: 2026-09-13, Asia/Shanghai

## Topology and isolation

- PASS — M9 uses the isolated PostgreSQL, Kernel state, artifact, OIDC, and
  Odoo volumes declared by `deploy/m9-staging/compose.yaml`.
- PASS — the pre-existing `feishu-dify-gateway` remains the long-connection
  owner; the M9 Gateway is the one explicitly configured administrative
  transport owner. No second Feishu WebSocket owner was started.
- PASS — `AGENT_KERNEL_REF` is required by the M9 compose interpolation and
  the Kernel Dockerfile; the final image carries the exact revision above.
- PASS — M9 compose config and the production compose config both render
  successfully.
- PASS — after final image recreation, Admin API, Operations API, and Kernel
  readiness checks are healthy; the M9 worker and migration completed without
  resetting the retained staging volumes.

## Real-provider intake and qualification

The real Feishu metadata callback path produced the following redacted
transcript intake record:

- inbound event: `m9-final-clean-transcript-d763a85e-a673-47b1-a48c-167fae80af0e`
- provider message ref: `om_x100b655698615ca4b3e9b737b630591`
- verified callback receipt/outbox ref:
  `639eee90-a05b-417b-a626-8de71fbefa0c`
- interpretation ref: `43d60d9c-f4d6-57bb-879d-0e9898cb449a`
- explicit candidate: `9c75115a-3572-5b70-9a18-9cc7a751967a`
- source artifact ref: `4dcbd92f-1daf-52db-9274-f14260e532b6`
- EvidenceSpan ref: `a40d6d3f-f6cd-5bca-81f5-0a539c5f07cb`
- candidate status/classification: `admitted` / `explicit_self_commitment`
- qualified speaker resolution: `53c81706-3fff-5430-89d9-8e6854b64ab6`
- qualified principal: `person:m9-subject`
- due time: `2030-09-26T09:00:00Z`; exact due basis is retained in the case
  record and is not copied here.

The same interpretation also yielded a suggestion candidate
`43324c76-bb95-5264-a3b5-e489a3d1c038`; it did not cross the commitment
admission boundary. Candidate extraction therefore remained candidate-only
until identity, semantic qualification, human admission, and policy checks
completed.

## Authority and persistent responsibility

- PASS — reviewer admission created case
  `06b4bf7f-4953-5083-9458-3f5fb7431c42` and commitment
  `229741be-972e-5215-9a60-26e1d8abdbe4`.
- PASS — the qualified principal is `person:m9-subject`; reviewer and subject
  OIDC bindings are distinct.
- PASS — policy/governance admission used the M9 administrative responsibility
  policy and a frozen authority epoch; the exact policy body is not duplicated
  here.
- PASS — persistent Kernel responsibility ref:
  `m9resp_ded5d68a477e5035be662239e242f4d7`, version `1`.
- PASS — commitment responsibility did not use Kernel Work admission. Kernel
  Work/effect execution was used only for the governed communication effects.
- PASS — completion evidence and responsibility discharge evidence are stored
  as separate records.

## Governed communication and independent verification

Confirmation and due reminder were separate immutable communication events:

| purpose | event id | provider ref | Admin state | read state | attempts |
|---|---|---|---|---|---:|
| confirmation | `2f2fde4e-a257-50f4-83ae-ef05339d1704` | `om_x100b655693b8c8a8b4b9c100002cb77` | `delivery_confirmed` | `unknown` | 1 |
| due reminder | `dd5072c7-1440-5d3b-9534-c3d89b9c60ea` | `om_x100b6556ac8674acb4bbeafbd8d74fc` | `delivery_confirmed` | `unknown` | 1 |

- PASS — drafts are artifact-backed and content digests are frozen before
  authorization; bodies are not stored in the Gateway ledger.
- PASS — the administrative transport uses its separate HMAC configuration
  reference and signed event identity.
- PASS — Gateway ledger state for both events is one transport attempt with
  `transport_accepted=true`; the Gateway transport ledger does not assert
  human read.
- PASS — Admin independently read the canonical Feishu message and promoted
  both projections to `cutover` with Kernel execution status `completed`.
- PASS — the confirmation and reminder Kernel execution refs are respectively
  `execution_bounded_domain_effect_f7e0423eca7432af3a8a733727ec5351` and
  `execution_bounded_domain_effect_0c040af24a8d237606f7571a9bcb7166`.
- PASS — final restart/recreate verification retained both provider refs,
  event identities, digests, and single-attempt counts; no duplicate send was
  created.

Historical fail-closed transport/readback evidence is retained, not replayed:

- event `7753aa79-4ab0-5a08-b5db-07b641b19e26` had one physical provider send
  and provider ref `om_x100b6556d14f48a0b242208a6d833f7`; the earlier readback
  path rejected the incompatible event identity and Kernel did not admit the
  effect. The later fix froze and reused the persisted communication event id;
  the historical event was not rewritten or resent.
- callback receipt `f8ea18d6-8126-47f3-950b-8997f2ac3d4a` used a mismatched
  canonical sender; the Gateway outbox stayed fail-closed with no accepted
  administrative interpretation.

## Fulfillment and discharge

- PASS — no reminder was sent before the exact due time; at due time exactly
  one reminder event was created for the active commitment.
- PASS — reviewer/wrong-principal fulfillment was rejected with HTTP 403 and
  did not create an attestation or change commitment state.
- PASS — qualified committer fulfillment succeeded with HTTP 200; commitment
  state became `fulfilled`, version `4`, with `was_overdue=true`.
- PASS — attestation ref `22f9aef3-d114-5796-b2c5-7498966408e6` records
  commitment version `2` and principal `person:m9-subject`.
- PASS — case status became `completed` independently of communication
  delivery state.
- PASS — explicit discharge chain completed:
  - assessment: `m9discharge_assessment_7d94b4e1bb065d2d8c34666a85441f2c`
  - decision: `m9discharge_decision_8686c59ad3b6578593acfca30d090096`
  - transition: `m9transition_72449cfa10e157d9a60870791fc81a03`
  - Kernel status after final restart: `discharged`, version `1`.

## Gate A–R

- A — PASS: real Feishu transcript metadata intake and verified callback.
- B — PASS: interpretation produced explicit and non-commitment candidates.
- C — PASS: candidate-only invariant prevented extraction from becoming
  authority.
- D — PASS: provider identity was resolved to the qualified principal through
  an authorized resolution record.
- E — PASS: exact due time and due basis were qualified before admission.
- F — PASS: human reviewer admission and policy/governance satisfaction.
- G — PASS: persistent Kernel responsibility was created and versioned.
- H — PASS: frozen confirmation communication was admitted and dispatched.
- I — PASS: independent canonical-provider verification completed both
  communication projections.
- J — PASS: delivery confirmation and human-read state remain distinct.
- K — PASS: pre-due worker restart produced no reminder.
- L — PASS: due-time drive produced exactly one reminder and persisted its
  immutable communication identity.
- M — PASS: wrong principal rejected; qualified committer attestation accepted.
- N — PASS: Administrative completion is separate from delivery and from
  responsibility discharge.
- O — PASS: assessment → decision → lifecycle transition left Kernel status
  `discharged`.
- P — PASS: due revision and cancellation tests stale old timers/effects while
  retaining case history and authority-epoch boundaries.
- Q — PASS: Gateway outcome-unknown/idempotency behavior is covered by the
  transport tests; real restart/recreate evidence retained one attempt per
  accepted event and did not duplicate either message.
- R — PASS: adversarial/prompt-like, ambiguous, assignment-to-other, and
  suggestion inputs remained non-authoritative.

## Mandatory counterexample ledger

- `We should ...` / aspiration / suggestion — PASS; candidate remains outside
  admission (`43324c76-bb95-5264-a3b5-e489a3d1c038`).
- ambiguous speaker — PASS; no principal resolution or promotion.
- assignment to another person — PASS; no self-commitment promotion.
- prompt injection — PASS; instruction-like candidate content cannot create
  authority, Work, send, fulfillment, or completion.
- speaker label used as principal — PASS; explicit resolution is required.
- ambiguous due — PASS; no qualified commitment until due basis is valid.
- due revision — PASS; old prepared/retrying communication is stale and cannot
  be sent against the new authority epoch.
- cancellation — PASS; prepared/retrying communication is marked
  `COMMITMENT_CANCELLED` and history remains.
- wrong-principal fulfillment — PASS; HTTP 403 and no attestation.
- lost ACK/readback failure — PASS; historical event
  `7753aa79-4ab0-5a08-b5db-07b641b19e26` has one physical send and no replay;
  the system stayed fail-closed until reconciliation/fix.
- Gateway delivery vs human read — PASS; both accepted messages retain
  `read_state=unknown`.
- transcript/callback replay — PASS; Gateway and commitment idempotency tests
  return existing records without a second provider send.

## Required verification

- PASS — Admin target M9 tests: `13 passed`.
- PASS — Admin full pytest exited `0`.
- PASS — Admin full ruff check over `src tests scripts alembic`.
- PASS — SQLite migration lane: fresh `upgrade → downgrade base → upgrade`
  through `0030_m9_communications`.
- PASS — PostgreSQL staging migration container completed successfully.
- PASS — M9 and production compose config render checks.
- PASS — Operations Console `npm run build`.
- PASS — Gateway ruff and mypy.
- PASS — Gateway full pytest: `57 passed`.
- PASS — Kernel M9 verifier changes: full local suite and ruff passed before
  merge; final staging image was built from promoted main revision
  `706cb3514c7edd030518f016a8f9b232b98f8166`.
- PENDING — SonarQube/new-code quality result, mandatory PR CI, and post-merge
  main verification are recorded after the Admin/Gateway PRs are opened.

## Residual risks and explicit boundaries

- No ASR or voice pipeline is in scope.
- No human-read proof is claimed; `delivery_confirmed` is not `human_read`.
- No external recipients beyond the isolated M9 staging identity are in scope.
- No delegated assignment is promoted as a self-commitment.
- Provider/API credentials and message bodies remain outside this record.
- The historical readback-failure event is preserved as evidence and is not
  treated as a successful current-path result.
- M10 meta-controller, mass broadcast, email/SMS/Slack, and arbitrary message
  generation remain explicitly out of scope.

## Closure

- [ ] Administrative M9 PR merged
- [ ] Gateway M9 PR merged
- [ ] required CI, Sonar/new-code, and M5–M8 regression lanes green
- [ ] post-merge main revisions verified
- [ ] this acceptance record committed as the closure record
- [ ] annotated tag `m9-accepted-2026-09-13` created only after all gates pass
