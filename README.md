# administrative-orchestrator

[![CI](https://github.com/xiongweilin/administrative-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/xiongweilin/administrative-orchestrator/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](pyproject.toml)

A reference system for governed administrative automation: trusted intake, organizational authority, durable execution, reality verification, completion, reconciliation, commitments, and governed communication.

## Concrete workflow: employee onboarding

Suppose a manager requests employee onboarding through an authenticated organizational channel.

A useful automation system cannot safely jump from the request directly to "create accounts." It must determine what was actually requested, which facts are authoritative, whether the requester currently has the required organizational authority, which obligations must be satisfied, which external effects are permitted, and whether those effects really happened.

This repository carries that workflow as an explicit chain:

```text
authenticated request
  -> preserve source/evidence lineage
  -> qualify the request into an AdministrativeCase
  -> resolve current organizational identity and authority
  -> evaluate current policy and approval requirements
  -> derive onboarding obligations
  -> mint bounded Administrative execution authorization
  -> hand durable Work to Agent Kernel
  -> execute approved HRIS/IAM effects
  -> read authoritative external state back
  -> verify required postconditions
  -> complete only when the obligations are actually satisfied
```

A provider returning success is not enough. An approval is not execution authority. AI confidence is not an organizational fact. A completed workflow run is not proof that responsibility has been discharged.

The same model is reused for offboarding, HRIS/IAM fact refresh, procurement and invoice preparation, expenses, commitments, governed communication, and Operations review.

## What this repository owns

The repository owns the **Administrative domain**. It turns organizational input into durable administrative matters and carries them through evidence, facts, policy, authority, obligations, bounded action, verification, completion, and reopen. It is not a chatbot, not a generic agent runtime, and not a replacement for authoritative HR, finance, IAM, messaging, document, or calendar systems.

The canonical vocabulary is `docs/contracts/domain-model.md`. Current architecture is `docs/architecture.md`. Historical milestone and acceptance documents prove how capabilities were introduced and exercised; they do not define the current language.

## Semantic pipeline

```text
organizational reality
        |
        v
authenticated source event / explicit request
        |
        +------------------------------+
        |                              |
        v                              v
IntakeReceipt -> SourceArtifact     AdministrativeRequest
        |                              |
        v                              |
DocumentRepresentation                 |
        |                              |
        v                              |
EvidenceSpan                           |
        |                              |
        v                              |
InterpretationRecord                   |
        |                              |
        v                              |
candidate -> IntakeAssessment          |
        |                              |
        v                              |
PromotionRecord -----------------------+
                                       |
                                       v
                              AdministrativeCase
                                       |
                             facts + provenance
                                       |
                                       v
                             PolicyRef / evaluation
                                       |
                                       v
                         identity / role / delegation
                                       |
                                       v
                         Decision -> ApprovalSatisfaction
                                       |
                                       v
                                GovernanceBasis
                                       |
                                       v
                          AdministrativeObligationSet
                                       |
                          +------------+-------------+
                          |                          |
                          v                          v
              domain-state fulfillment      ExecutionAuthorization
                                                     |
                                                     v
                                                EffectRecord
                                                     |
                                                     v
                                                Agent Kernel
                                  responsibility / Work / runtime authority
                                      physical RealityBoundary / recovery
                                                     |
                                                     v
                                            external system reality
                                                     |
                                                     v
                                      independent authoritative read-back
                                                     |
                                                     v
                                    EffectRealizationAssessment
                                                     |
                                                     v
                                             ConfirmedOutcome
                                                     |
                                                     v
                                           CompletionAssessment
                                                     |
                                  complete / wait / reconcile / reopen
```

Meeting commitments enter the same responsibility model through `CandidateCommitment -> SpeakerPrincipalResolution -> authorized admission -> CommitmentRecord -> persistent Kernel responsibility`. Commitment creation does not itself create external Work or an effect.

Governed outbound communication uses `CommunicationDraftRecord` and `CommunicationEffectRecord`; content is frozen by digest before execution, the gateway is transport-only, and delivery confirmation remains distinct from human read state.

## Core distinctions

```text
Source authenticity != content truth
SourceArtifact != InterpretationRecord
InterpretationRecord != Candidate
Candidate != AdministrativeRequest
AI confidence != admission authority
Admission != authoritative fact
Request != AdministrativeCase
External identity != Principal
Principal != organizational authority
Recommendation != Decision
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Kernel runtime authorization
AdministrativeObligation != Kernel Work
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
OUTCOME_UNKNOWN != retry permission
Object existence != semantic postcondition satisfaction
Case completion != responsibility discharge
CandidateCommitment != CommitmentRecord
transport_accepted != delivery_confirmed
delivery_confirmed != human_read
Exception != permission to improvise
Investigation != authority
Hypothesis != fact
ReframingProposal != reframe
ReopenAssessment != ReopenRecord
Reopen != history deletion
```

These are product invariants, not documentation conventions.

## Ownership boundary

`administrative-orchestrator` owns:

- intake receipts, source/evidence lineage, interpretations, candidates, assessments, and promotion lineage;
- durable `AdministrativeRequest` and `AdministrativeCase` state;
- fact authority/provenance and immutable fact history;
- Administrative identity projection, roles, delegation, Decisions, and `ApprovalSatisfaction`;
- policy versions/evaluation, current-governance qualification, and `GovernanceBasis`;
- business obligations and expected postconditions;
- Administrative `ExecutionAuthorization`, effect intent/lineage, semantic verification, `ConfirmedOutcome`, and completion;
- typed employee-lifecycle and financial-transaction semantics;
- commitment qualification/admission/fulfillment semantics;
- governed communication draft/delivery semantics;
- bounded investigation triggers/requests/proposals, evidence requests, reframing proposals, and governed reopen records;
- Operations review, exception, reassessment, audit, and product-specific integration contracts.

`agent-kernel` owns:

- persistent responsibility and responsibility lifecycle;
- Work proposal/admission/materialization, Work/Run/Step/Attempt;
- generic runtime authorization and capability routing;
- provider execution and the unique physical `RealityBoundary`;
- retry permission, ambiguous-execution recovery, reconciliation identity, generic execution evidence, and generic Outcome/revision contracts.

DBOS owns durable orchestration scheduling, wait/wake/replay/resume. It does not own business truth, authority, obligations, completion, or physical effects.

Transport gateways own transport authenticity and provider interaction. They do not own Administrative intent, authority, completion, responsibility, or provider-content interpretation.

External systems remain authoritative for the business reality they own.

## Current capability surface

The current repository contains one coherent Administrative language across these supported slices:

- employee onboarding and offboarding;
- authoritative HRIS/IAM fact refresh and governed lifecycle effects;
- document-backed procurement, invoice/AP preparation, and expense reimbursement;
- typed transaction qualification and draft-only ERP effects;
- Feishu-backed communication intake with durable source/evidence lineage;
- meeting transcript self-commitment qualification and admission;
- persistent commitment responsibility, overdue/fulfillment semantics, and explicit responsibility discharge;
- bounded internal Feishu confirmation/reminder communication with canonical provider read-back;
- bounded advisory investigation and authority-epoch reopen paths with stale-authorization fencing;
- Operations API/Console, observability, PostgreSQL DR, Kernel-state recovery, and production preflight.

Not currently claimed by the accepted system include ASR/meeting bots, proof of human read, external-recipient or broadcast communication, delegated commitment assignment, payment/settlement, or an independently deployed meta-controller service.

Adaptive investigation has a recorded isolated staging acceptance in `docs/acceptance/adaptive-investigation-staging-acceptance.md`; that record does not claim production-provider deployment or an independently deployed meta-controller.

## Authority and completion model

Authentication answers who crossed a boundary. Administrative identity resolution answers which Principal that subject maps to. Authority answers what that Principal may decide **now** under current role, delegation, policy, scope, facts, and authority epoch.

`authority_epoch` invalidates stale authority-sensitive closure when the relevant world changes. `GovernanceBasis` freezes the exact fact/policy/organizational dependencies relied upon and is revalidated before acting or closing.

Administrative derives obligations before effects. An external obligation is complete only when a matching effect has independent authoritative realization evidence and the required `ConfirmedOutcome`; a domain-state obligation is complete only from verified Administrative domain state. Neither proof mode impersonates the other.

`OUTCOME_UNKNOWN` is a reconciliation state. It does not grant resend or retry authority.

Adaptive investigation is a bounded advisory path. Administrative may record a
trigger, request evidence, preserve competing hypotheses, and qualify a
reopen. The advisory client receives bounded references and returns
schema-validated proposals only. It cannot create authority, facts, Work,
effects, or completion. A reopen advances the existing `authority_epoch` and
requires fresh governance before any new effect.

## Commitment and communication model

Only an explicitly qualified self-commitment can become a formal `CommitmentRecord`. Speaker labels are source evidence, not Administrative Principals. Due times are offset-aware. Revision/cancellation makes stale timers and reminders unusable. `OVERDUE` records lateness, not failure; late authorized fulfillment can complete while preserving overdue history.

Outbound communication has its own durable event identity and frozen content digest. The same identity is reconciled after a lost acknowledgement. A new event identity is not minted merely to make uncertainty disappear.

```text
CommunicationDraftRecord
  -> current authority
  -> Kernel capability / execution identity
  -> transport-only gateway
  -> provider
  -> canonical read-back
  -> delivery state
```

`delivery_confirmed` does not imply `human_read`; current read state remains independently represented.

## Repository layout

```text
src/administrative_orchestrator/
    domain.py                 core request/case/fact/effect/outcome records
    authority.py              identity binding, roles, delegation, approval satisfaction
    governance.py             frozen governance basis and revalidation
    obligations.py            business obligations and fulfillment proof modes
    completion.py             obligation-backed completion assessment
    service.py                pure case and ExecutionAuthorization transitions
    unit_of_work.py           atomic case/authority persistence + outbox
    intake/                   source, evidence, representation, interpretation, candidate plane
    admission.py              candidate assessment/promotion into formal Administrative state
    financial.py              typed transaction facts/policy/qualification language
    commitment_models.py      commitment and communication records
    commitment_service.py     qualification, admission, fulfillment, communication lifecycle
    investigation_models.py  bounded investigation/reframing/reopen language
    investigation_reconciliation.py Kernel-first OUTCOME_UNKNOWN qualification
    investigation_repository.py durable investigation and reopen records
    investigation_service.py qualification, advisory boundary, and epoch transition
    investigation_client.py  narrow fail-closed advisory adapter
    model_investigation_client.py bounded OpenAI-compatible model adapter
    responsibility_discharge.py Administrative evidence -> Kernel discharge protocol
    integrations/kernel/      Kernel contract bridge; no second runtime owner
    providers/                provider authenticity/canonical-read adapters
    workflows/                DBOS durability boundary
    operations_api.py         authorized exception/review operations
docs/
    architecture.md           current semantic/topological architecture
    contracts/                canonical language and authority composition
    adr/                      decisions and ownership rationale
    acceptance/               immutable recorded acceptance evidence
    milestones/               historical delivery plans/evidence locators
deploy/                       historical/current isolated staging surfaces
operations-console/           OIDC human operations UI
```

Names containing historical milestone labels in migrations, staging directories, tests, workflow names, policy identifiers, or API/wire compatibility values remain stable where changing them could break replay, persisted identity, evidence, or callers. They are compatibility identifiers, not current domain vocabulary.

## Current promoted Kernel baseline

Production does not derive the Kernel revision from prose. The deployment-level source is `AGENT_KERNEL_REF`; production Compose, Kernel image build, Administrative expected revision, and runtime `build_revision` evidence must converge on the same value.

Current promoted baseline:

```text
17acfba8338683bdb0f3d1c93aa671778603482a
```

Repository tests guard the mutable production/CI pin surfaces against drifting apart.

## Development

Python 3.12+:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
```

Reference Compose topology:

```bash
docker compose up -d --build
python scripts/e2e_compose.py
docker compose down -v --remove-orphans
```

Production preflight, deployment, observability, backup/restore, incidents, and staging procedures are in `docs/production-operations.md`.

## CI and trust boundary

Normal CI exercises lint/tests, migration roundtrip, Compose configuration/E2E, PostgreSQL/DBOS restart paths, cross-repository Kernel cutover/recovery, and SonarQube Cloud Quality Gate. The production-trust workflow additionally proves production identity/connector/readiness/DR invariants, Operations Console build, PostgreSQL destructive restore semantics, and the pinned Kernel cutover lane.

Repository CI proves repository semantics. Real provider credentials, network paths, and external-system behavior are proven only by the corresponding recorded acceptance run; a unit test or local fixture is never relabeled as real-provider evidence.

## Historical acceptance

Acceptance history is preserved because it proves when concrete slices crossed real boundaries. It is not the vocabulary for understanding the current system.

Recorded staging evidence:

- `docs/acceptance/M5-staging-acceptance.md`;
- `docs/acceptance/M6-staging-acceptance.md`;
- `docs/acceptance/M7-staging-acceptance.md`;
- `docs/acceptance/M8-staging-acceptance.md`;
- `docs/acceptance/M9-staging-acceptance.md`.

The accepted M9 tag remains `m9-accepted-2026-09-13`. Later documentation or language cleanup does not move that acceptance boundary.

For design rationale, see ADRs 0001–0006. For historical delivery plans, see `docs/milestones/`. For current product meaning, return to `docs/contracts/domain-model.md` and `docs/architecture.md`.

## Contributing and security

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution boundaries and [`SECURITY.md`](SECURITY.md) for private security reporting guidance.
