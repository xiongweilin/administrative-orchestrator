# Workflow authority map

This document locks the first complete administrative vertical slice: employee onboarding.

## Trigger

A current principal submits an onboarding request for one employee subject through an authenticated ingress.

## Main states

```text
received
-> gathering_facts
-> ready_for_policy
-> awaiting_decision
-> authorized
-> executing
-> verifying
-> reconciling
-> completed
```

Exception states:

```text
waiting
reopen_required
failed
cancelled
```

## Actors and owners

| Transition / fact | Owner | Automated? | Notes |
| --- | --- | --- | --- |
| request authentication | ingress / identity adapter | yes | transport identity is evidence, not business authority |
| employee/manager/department facts | HRIS authoritative adapter | yes/read | AI extraction may propose refs but not own them |
| policy selection/evaluation | administrative policy plane | yes | versioned deterministic policy where possible |
| HR approval decision | eligible HR principal | human initially | exact case and policy version |
| privileged access approval | manager + access approver | human initially | separate from employment approval |
| execution authorization | administrative server | yes | server-owned exact profile; never client-supplied scope |
| HRIS employee create | HRIS effect adapter | yes | typed effect |
| IAM identity create | IAM effect adapter | yes | typed effect |
| SaaS account provision | system-specific adapter | yes | only configured/allowed systems |
| effect realization | authoritative system read-back | yes | provider success alone is insufficient |
| reconciliation | administrative worker | yes | ambiguous/mismatched state is not auto-smoothed |
| case completion | administrative completion evaluator | yes | declared-scope only |
| reopen decision | administrative controller / qualified human path | explicit | failure alone does not imply reopen |
| policy change | policy owner | human promotion | repeated cases may propose candidates but not self-promote |

## Invalid transitions

The implementation must reject at least:

```text
request -> effect
AI recommendation -> execution authorization
role membership -> direct effect
historical approval -> current effect after case mutation
provider success -> completed without read-back
outcome_unknown -> blind resend
missing routine field -> deep ontology reopen
reopen_required -> new effect without explicit reopen and fresh closure
```

## Evidence required for completion

An onboarding case may be declared complete only when its declared workflow requires and freshly verifies all applicable items:

- authoritative employee record exists with expected subject/version;
- expected IAM identity exists;
- required group/access assignments match current policy and approvals;
- requested configured SaaS accounts are observed as provisioned;
- no blocking reconciliation difference remains;
- every authority-sensitive effect has a current supporting authorization lineage;
- outstanding administrative obligations required by the profile are discharged or explicitly deferred by policy.

A UI success message, workflow return value or adapter `200 OK` does not satisfy these requirements by itself.

## Compensation and correction

Onboarding is not assumed globally reversible.

- incorrectly created account: disable/delete through the target system's supported correction path;
- wrong group membership: remove using a separately authorized effect;
- wrong employee master data: correct through HRIS-supported update/correction mechanisms;
- unknown external outcome: read and reconcile before considering any resend;
- privileged access mistakenly granted: treat as a security event in addition to corrective removal.

Compensation is new Work with its own authority and evidence. It is not hidden rollback magic.

## Audit minimum

For each material transition retain stable references to:

- request identity/source;
- case/version;
- facts/evidence versions relied on;
- policy/version;
- human decisions;
- execution authorization;
- effect id/provider reference;
- read-back evidence;
- reconciliation result;
- completion or reopen assessment.
