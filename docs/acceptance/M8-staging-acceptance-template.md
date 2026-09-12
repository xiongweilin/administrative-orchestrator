# M8 isolated staging acceptance template

> Fill this file only from a fresh isolated M8 run. Do not record secret
> values, access tokens, document bodies, invoice numbers, bank data, or raw
> provider payloads. Use identifiers, hashes, statuses, and redacted evidence
> references only.

## Run identity

- Date/time (UTC): `<YYYY-MM-DDTHH:MM:SSZ>`
- Compose project: `administrative-m8-staging`
- Administrative repository SHA: `<sha>`
- Agent Kernel revision: `<exact AGENT_KERNEL_REF candidate revision>`
- Database migration head: `0027_m8_current_qualification`
- Operator: `<principal-ref>`
- Artifact/evidence backup reference: `<redacted-locator>`

## Gate record

| Gate | Result | Evidence reference | Notes |
| --- | --- | --- | --- |
| A–C isolated topology / migration / pin | `PASS/BLOCKED` | `<ref>` | `<redacted>` |
| D–F intake / representation / parser bounds | `PASS/BLOCKED` | `<ref>` | `<redacted>` |
| G–I admission / policy / governance | `PASS/BLOCKED` | `<ref>` | `<redacted>` |
| J–L qualification / duplicate / three-way | `PASS/BLOCKED` | `<ref>` | `<redacted>` |
| M–O obligations / Kernel / draft-only ERP | `PASS/BLOCKED` | `<ref>` | `<redacted>` |
| P–R readback / recovery / completion | `PASS/BLOCKED` | `<ref>` | `<redacted>` |
| S no-payment / audit / rollback | `PASS/BLOCKED` | `<ref>` | `<redacted>` |

## Case records

For each case, record only the case id, authority epoch, policy ref, frozen
obligation requirement id, effect ids, Kernel projection/execution refs, readback
evidence refs, outcome kinds, and final status.

### Procurement

- Case id: `<uuid>`
- Status: `<status>`
- Required effects: `purchase_order.create_draft`, `purchase_order.confirm`
- Draft-only / settlement forbidden proof: `<ref>`

### Invoice/AP preparation

- Case id: `<uuid>`
- Status: `<status>`
- Qualification assessments: `<assessment-refs>`
- Three-way match result: `<qualified/mismatch/blocked>`
- Draft-only / settlement forbidden proof: `<ref>`

### Expense reimbursement preparation

- Case id: `<uuid>`
- Status: `<status>`
- Payment capability absence proof: `<ref>`

## Counterexamples

- malformed or unsupported PDF: `<result and redacted ref>`
- parser timeout/resource bound: `<result and redacted ref>`
- duplicate vendor/invoice: `<blocked result>`
- mismatched three-way match: `<blocked result>`
- provider unknown after write: `<reconcile/reopen result>`
- independent readback mismatch: `<reopen result>`
- cross-effect outcome substitution: `<blocked completion result>`
- payment/settlement request: `<rejected capability/result>`

## Closure

- Full repository tests: `<command/result>`
- Static/security checks: `<command/result>`
- PostgreSQL migration/DR result: `<command/result>`
- Console build/typecheck: `<command/result>`
- Historical M5/M6/M7 records and volumes preserved: `<yes/no + ref>`
- Acceptance owner sign-off: `<principal-ref>`
