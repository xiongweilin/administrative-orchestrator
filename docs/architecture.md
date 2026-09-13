# Architecture

`administrative-orchestrator` is the domain system for governed administrative automation. Its architecture is organized by semantic ownership, not by delivery milestone.

The canonical noun definitions are in `docs/contracts/domain-model.md`; the authority composition rules are in `docs/contracts/workflow-authority.md`. ADRs explain why the ownership boundaries exist. Acceptance documents prove particular real executions but do not define current architecture.

## 1. System boundary

Administrative owns the durable organizational meaning of a matter: what was observed, what entered the formal model, which facts are current, which policy applies, who may decide, what obligations exist, which business effect is intended, what reality was verified, and whether the matter is complete or must reopen.

Administrative does **not** own the generic agent runtime or the physical provider effect boundary.

```text
organizational reality
        |
        v
+---------------- Administrative ----------------+
|                                                |
|  perception -> admission -> case              |
|       -> facts / policy / authority            |
|       -> governance / obligations              |
|       -> business effect intent                |
|                                                |
+----------------------|-------------------------+
                       |
                       v
                  Agent Kernel
        responsibility / Work / Run / Attempt
        runtime authorization / capability
        physical RealityBoundary / recovery
                       |
                       v
                external systems
                       |
                       v
+---------------- Administrative ----------------+
| authoritative read-back -> realization        |
| -> ConfirmedOutcome -> completion/reopen       |
+------------------------------------------------+
```

DBOS schedules Administrative workflows durably. Transport gateways carry authenticated provider interaction. Neither DBOS nor a gateway becomes an alternate owner of business authority, completion, responsibility, or effect semantics.

## 2. Semantic planes

### 2.1 Perception plane

The perception plane preserves the difference between what arrived and what the system thinks it means.

```text
provider/source event
   -> IntakeReceipt
   -> SourceArtifact
   -> DocumentRepresentation
   -> EvidenceSpan
   -> InterpretationRecord
```

`IntakeReceipt` establishes durable receipt and bounded source-verification facts. `SourceArtifact` is immutable source material. `DocumentRepresentation` is derived. `EvidenceSpan` locates support. `InterpretationRecord` is model/parser interpretation.

No object in this plane is an authoritative Administrative fact merely by existing.

For provider-backed messaging, the first durable handoff contains metadata required to identify and fetch the canonical provider object. Message bodies and extracted content do not become transport-ledger authority. Provider-native sender identity remains source evidence until current `IdentityBinding` resolves it.

### 2.2 Candidate and admission plane

Interpretation may produce candidates:

```text
InterpretationRecord
   -> CandidateAdministrativeRequest
   -> CandidateFactAssertion
   -> CandidateCaseUpdate
   -> CandidateCommitment
```

Candidates remain proposals. `IntakeAssessment` decides how a candidate is handled. Only a final deterministic or authorized-human path may admit a supported candidate. `PromotionRecord` preserves the exact lineage into formal Administrative state.

```text
candidate
  -> IntakeAssessment
  -> PromotionRecord
  -> AdministrativeRequest / AdministrativeCase
```

Human admission authorizes entry into the formal model; it does not convert candidate claims into `AUTHORITATIVE` facts. Authoritative facts come through approved fact owners/readers.

Pre-admission supersession and post-admission case updates remain different operations. A later source event must not accidentally create a second case where the product semantics require an update to the existing one.

### 2.3 Case and fact plane

`AdministrativeRequest` is the formal trigger. `AdministrativeCase` is the durable business matter.

The case references immutable fact history and a current fact projection. Field-level `FactAssertion` preserves claim, attestation, authoritative ownership, and provenance. A new current snapshot never erases historical snapshots.

`case.version` tracks state/history concurrency. `authority_epoch` tracks authority-sensitive invalidation. They are related but non-equivalent clocks.

Authoritative external facts are re-read before governed reality transitions when the product contract requires fresh truth. Changed decision-relevant facts can invalidate the current governance world and require re-evaluation or reopen.

### 2.4 Policy and authority plane

The authority plane converts current facts and organizational structure into bounded closure.

```text
FactSnapshot
  -> PolicyRef / PolicyEvaluation
  -> current Principal / RoleAssignment / Delegation eligibility
  -> Decision set
  -> ApprovalSatisfaction
  -> GovernanceBasis
```

Authentication is upstream evidence about caller identity. `IdentityBinding` resolves external identity into an Administrative Principal. Roles/delegations establish eligibility. A `Decision` records judgment. `ApprovalSatisfaction` proves that the policy's required decision structure is closed. `GovernanceBasis` freezes the exact fact/policy/scope/qualification world relied upon.

Before authority-sensitive action, verification, or completion, the relevant governance dependencies are revalidated. Stale governance fails closed.

### 2.5 Obligation and effect-intent plane

Administrative derives required business conditions before planning external action.

```text
current case + GovernanceBasis
        |
        v
AdministrativeObligationSet
        |
        +-> DOMAIN_STATE_VERIFIED
        |
        +-> EXTERNAL_EFFECT_VERIFIED
                     |
                     v
             ExecutionAuthorization
                     |
                     v
                EffectRecord
```

`AdministrativeObligationSet` is frozen per case/authority epoch and governance basis. It is the completion contract. It is not reconstructed from successful effects after the fact.

`ExecutionAuthorization` is the canonical Administrative exact-scope authorization. It binds current case/epoch, subject, target system, allowed operations, policy, authority class, issuer, and supporting approval/decision lineage. It is not Kernel runtime authorization.

`EffectRecord` is Administrative business effect intent/lineage. Once physically cut over, Administrative does not directly own provider retry/recovery; it submits bounded capability work through Kernel.

### 2.6 Kernel runtime plane

Agent Kernel is a separate semantic owner for generic runtime concerns:

- persistent responsibility;
- WorkProposal/admission/materialization;
- Work / Run / Step / Attempt;
- generic runtime authorization and authorization use;
- capability routing and invocation permit;
- provider execution through the unique physical `RealityBoundary`;
- retry permission, outcome ambiguity, recovery, and reconciliation identity;
- generic execution evidence and Outcome/revision contracts.

Administrative may persist references/projections to Kernel objects. It must not reconstruct Kernel authority locally, mint a second Work/Run model, or bypass Kernel with a second cut-over provider path.

## 3. Return path from reality

Provider or Kernel success is not Administrative completion.

```text
physical execution
   -> authoritative external reality
   -> independent read-back
   -> EffectRealizationAssessment
   -> ConfirmedOutcome
   -> CompletionAssessment
```

`EffectRealizationAssessment` explicitly distinguishes verified, not verified, mismatch, and unknown. `ConfirmedOutcome` is a bounded Administrative semantic conclusion supported by realization evidence.

`CompletionAssessment` evaluates the current `AdministrativeObligationSet`. External-effect obligations require matching effect/obligation lineage and verified outcome evidence. Domain-state obligations require verified Administrative state. The two proof modes do not substitute for one another.

If current reality cannot be established, the system waits, reconciles, or reopens. It does not turn uncertainty into success.

## 4. Persistent responsibility

Persistent responsibility belongs to Kernel. Administrative determines business obligations and can create/reference responsibility under its Kernel contract, but responsibility state is not just another case column.

The lifecycle is intentionally split:

```text
Administrative obligation or admitted commitment
        |
        v
Kernel responsibility
        |
     ACTIVE
        |
        +-> OVERDUE-like temporal evidence where applicable
        |
Administrative CompletionAssessment / fulfillment evidence
        |
        v
Kernel responsibility assessment
        |
        v
discharge decision
        |
        v
lifecycle transition -> DISCHARGED
```

Administrative case completion is evidence for responsibility discharge, not a substitute for it. The discharge service calls Kernel assessment/decision/transition/status contracts and does not create a new provider effect.

## 5. Commitment architecture

Meeting/transcript input reuses the perception and admission planes.

```text
SourceArtifact
  -> DocumentRepresentation
  -> EvidenceSpan
  -> InterpretationRecord
  -> CandidateCommitment
  -> SpeakerPrincipalResolution
  -> authorized admission
  -> meeting-commitment AdministrativeCase
  -> CommitmentRecord
  -> persistent Kernel responsibility
```

The qualification contract is deliberately narrow:

- speaker label/provider display identity is not a Principal;
- ambiguous speaker resolution fails closed;
- only explicit self-commitment enters the formal commitment path;
- due time must be offset-aware and retain its interpretation basis;
- suggestion, aspiration, information, and assignment-to-other remain non-commitment classes.

Commitment creation does not directly create external Work/effects. Due revision/cancellation invalidates stale timers/reminders. `OVERDUE` records temporal status, not failure. Late authorized fulfillment may close the commitment while overdue history remains immutable.

## 6. Governed communication architecture

Outbound communication is an Administrative effect with frozen content integrity and a transport-only provider boundary.

```text
bounded/fixed-template generation
   -> CommunicationDraftRecord
   -> ArtifactStore reference + content digest
   -> current Administrative authority
   -> Kernel capability / durable execution identity
   -> transport-only gateway
   -> provider
   -> canonical provider read-back
   -> CommunicationEffectRecord
```

The transport gateway does not persist or reinterpret Administrative content as business truth. Administrative persists the draft artifact/digest and delivery metadata necessary for governance and reconciliation.

Delivery state preserves:

```text
PREPARED
TRANSPORT_ACCEPTED
DELIVERY_CONFIRMED
RETRYING
PERMANENT_FAILED
OUTCOME_UNKNOWN
```

`CommunicationReadState` is independent; delivery confirmation does not establish human read. Lost acknowledgement is reconciled under the same durable communication/execution identity rather than by generating a new identity and blindly sending again.

## 7. Transaction architecture

Document-driven financial cases reuse the same planes rather than forming a separate workflow language.

Raw document evidence becomes a `DocumentRepresentation` with exact spans. Admission preserves extracted financial values as claims. Transaction qualification is a separate eligibility layer over current vendor/master-data, duplicate detection, amount/currency/match evidence, and policy inputs.

Supported typed case families include procurement request, invoice/AP preparation, and expense reimbursement. Their ERP writes are bounded draft/preparation capabilities. Payment, bank transfer, and settlement are separate authority domains and are not implied by draft creation.

A transaction qualification may enter `GovernanceBasis` as a dependency. If the qualification changes, old governance must not continue to authorize an effect.

## 8. Employee lifecycle architecture

Employee onboarding/offboarding are case kinds over the same case, fact, authority, obligation, execution, verification, and completion language.

Lifecycle-specific facts such as active state/effective termination time are authoritative HR dependencies. Effective-time waiting is not failure. Ownership-transfer/domain-state requirements may be Administrative obligations even when they require no external provider effect.

Offboarding effects such as IAM disablement or HRIS deactivation remain separately authorized and independently verified. Partial physical progress under verifier unavailability does not imply case completion.

## 9. Reopen and reconciliation

Reconciliation addresses uncertainty inside the represented procedure. Reopen addresses a framing/closure world that is no longer sufficient.

Examples requiring explicit preservation include:

- provider result ambiguous but recoverable under the same execution identity -> reconcile;
- authoritative read-back temporarily unavailable -> wait/reconcile;
- current fact/policy/authority dependency differs from the governance basis -> reopen/reassess;
- observed external state contradicts the intended postcondition -> reopen or governed correction;
- new scope/risk dimension not covered by current policy -> reopen.

```text
OUTCOME_UNKNOWN != retry permission
REOPEN_REQUIRED != execution authorization
compensation != hidden rollback
```

Correction/compensation is new governed action with fresh authority and evidence.

An `OUTCOME_UNKNOWN` investigation trigger is accepted only after the
Administrative boundary verifies a matching persisted Kernel execution
projection and a terminal Kernel reconciliation resolution. An arbitrary
caller-supplied reference or model opinion cannot substitute for that Kernel
evidence.

## 9.1 Adaptive investigation and governed reframing

Administrative has a bounded investigation/reopen vocabulary above the
existing authority chain. It is not a new ontology or execution engine:

```text
case anomaly / closure insufficiency
    -> InvestigationTrigger / InvestigationRequest
    -> bounded advisory client
    -> InvestigationProposal / evidence request / ReframingProposal
    -> Administrative ReopenAssessment
    -> authorized ReopenRecord, or preserve closure
    -> one existing authority_epoch advances on reopen
    -> fresh governance and closure
```

Administrative owns the durable investigation records, proposal qualification,
reopen authority, historical invalidation references, and closure semantics.
The advisory client and `meta-controller` own only bounded epistemic advice.
Agent Kernel remains the first owner of execution-unknown reconciliation and
the only owner of Work, runtime authorization, provider execution, and the
physical RealityBoundary.

Investigation output cannot mint facts, decisions, approvals,
ExecutionAuthorization, Work, or effects. Reframing never mutates current
case truth by itself. Reopen advances the existing `authority_epoch`, fences
stale authorization, and preserves historical Effects, Outcomes, Obligations,
Commitments, and responsibility lineage.

## 10. Process and repository boundaries

The repository is a product monorepo. API, Operations API, worker, DBOS workflows, product-specific integrations, migrations, Operations Console, deployment assets, DR, and product documentation share one Administrative semantic/versioning lifecycle.

A process/container/language boundary is not by itself a repository boundary. A component should split only when it acquires an independent consumer/release/ownership/SLA/security/version contract.

`agent-kernel` remains separate because it owns a genuinely independent generic runtime contract. Provider gateways remain separate where their transport/security lifecycle is independently useful, but they do not absorb Administrative semantics.

## 11. Current invariants

```text
Authentication != Administrative authority
Source authenticity != content truth
Interpretation != authoritative fact
Candidate != formal Administrative state
External identity != Principal
Principal eligibility != Decision
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Kernel runtime authorization
AdministrativeObligation != Kernel Work
EffectRecord != external reality
Provider success != ConfirmedOutcome
Kernel execution evidence != Administrative semantic outcome
OUTCOME_UNKNOWN != retry permission
Object existence != semantic postcondition satisfaction
Case completion != responsibility discharge
Speaker label != Principal
Suggestion != commitment
TransportAccepted != DeliveryConfirmed != HumanRead
Investigation != Authority
Hypothesis != Fact
ReframingProposal != Reframe
ReopenAssessment != ReopenRecord
Reopen != DeleteHistory
```

These invariants are the architecture's stable spine. Provider brands, staging directories, migration labels, acceptance tags, and milestone-named compatibility identifiers may change or remain historical without changing this ownership model.

## 12. Where truth lives

Use the following order when documents disagree:

1. current code, migrations, and live runtime evidence for implemented behavior;
2. `docs/contracts/domain-model.md` for current vocabulary and semantic distinctions;
3. this document and ADRs for current ownership/topology;
4. acceptance records for what a specific recorded real run proved;
5. milestone documents for historical delivery intent and evidence location.

Historical acceptance is preserved, not rewritten into current semantics.
