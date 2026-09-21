# EvidenceConsensus × GenLayer

EvidenceConsensus is a standalone GenLayer Intelligent Contract for **multi-source evidence verification with substantive validator consensus**.

The contract allows users to submit a claim, define explicit verification criteria, and provide multiple evidence URLs. GenLayer then independently evaluates the claim through leader and validator execution.

The key design principle is simple:

> Validators must independently determine whether the claim is `APPROVED` or `REJECTED`. They do not merely validate the format or label returned by the leader.

This makes the contract useful as a reusable verification primitive for applications that need trustworthy, evidence-based decisions.

---

## Problem

A common failure mode in AI-powered verification contracts is a weak validator.

For example, a contract may ask the leader to return:

```text
APPROVED
```

and then have the validator only check that the response starts with an allowed label.

That creates a serious problem.

A validator could effectively accept:

```text
APPROVED
```

without determining whether the underlying claim is actually supported.

As a result, opposite decisions could potentially pass a weak validation rule.

EvidenceConsensus is designed to avoid this pattern.

---

## Solution

EvidenceConsensus makes the validator independently perform the substantive verification task.

For every verification request, both sides receive the same:

* Claim
* Verification criteria
* Evidence URLs

The leader:

1. Fetches the evidence.
2. Evaluates the claim against the criteria.
3. Produces an `APPROVED` or `REJECTED` decision.

The validator independently:

1. Fetches the same evidence sources.
2. Evaluates the same claim.
3. Applies the same verification criteria.
4. Produces its own independent decision.

Consensus is accepted only when:

```text
Leader verdict == Validator verdict
```

Therefore:

```text
APPROVED == APPROVED
```

is accepted, and:

```text
REJECTED == REJECTED
```

is also accepted.

But:

```text
APPROVED != REJECTED
```

fails consensus.

---

## Architecture

```text
                   USER
                     │
                     │
                     ▼
              create_claim()
                     │
                     ▼
              ┌──────────────┐
              │ Claim Record │
              └──────┬───────┘
                     │
                     │ verify_claim()
                     ▼
              ┌──────────────┐
              │ GenLayer VM  │
              └──────┬───────┘
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
      LEADER                VALIDATOR
          │                     │
   fetch evidence         fetch evidence
          │                     │
   evaluate claim         evaluate claim
          │                     │
          ▼                     ▼
      APPROVED              APPROVED
          │                     │
          └──────────┬──────────┘
                     │
                     ▼
                  CONSENSUS
                     │
                     ▼
              Store final result
```

The validator does not simply inspect the leader's answer.

It independently reaches the substantive decision.

---

## Core Consensus Rule

The core security property is implemented as:

```python
return leader_verdict == validator_verdict
```

This means that the validator must independently derive the same substantive outcome.

The contract does **not** use a validation rule such as:

```python
return leader_response.startswith("APPROVED")
```

or:

```python
return leader_response in ["APPROVED", "REJECTED"]
```

Those approaches only validate the response format.

EvidenceConsensus validates the underlying decision.

---

## Multi-Source Evidence

A claim can contain multiple evidence URLs.

For example:

```text
Claim:
The Eiffel Tower is located in Paris.

Criteria:
The evidence must explicitly establish that the Eiffel Tower
is located in Paris.

Evidence:
- Source 1
- Source 2
```

Both leader and validator independently retrieve the supplied sources.

The evidence is then provided to the verification model together with the claim and criteria.

The contract supports up to 10 evidence sources per claim.

---

## Decision Semantics

The verifier has exactly two substantive outcomes.

### APPROVED

The available evidence sufficiently supports the claim according to the supplied criteria.

### REJECTED

The evidence:

* does not sufficiently support the claim,
* contradicts the claim,
* is insufficient,
* is ambiguous,
* or cannot establish the required criteria.

The verifier is instructed not to infer unsupported facts.

When important evidence is missing or ambiguous, the contract uses:

```text
REJECTED
```

rather than making an unsupported approval.

---

## Contract State

Each claim is stored with information including:

```json
{
  "id": "1",
  "claim": "...",
  "criteria": "...",
  "evidence_urls": [],
  "status": "PENDING",
  "verdict": "",
  "reasoning": "",
  "supporting_sources": [],
  "created_at": 0
}
```

After successful consensus, the record contains the final verification information:

```json
{
  "status": "APPROVED",
  "verdict": "APPROVED",
  "reasoning": "...",
  "supporting_sources": [],
  "verified_evidence": [],
  "verified_at": 0
}
```

The final state is written only after the consensus execution succeeds.

---

## Public Methods

### `create_claim`

Creates a new claim.

Parameters:

```text
claim
criteria
evidence_urls
```

Example:

```text
claim:
The Eiffel Tower is located in Paris.

criteria:
The evidence must explicitly establish that the Eiffel Tower
is located in Paris.

evidence_urls:
[
  "https://example.com/source1",
  "https://example.com/source2"
]
```

Returns the new claim ID.

---

### `verify_claim`

Runs GenLayer consensus for a previously submitted claim.

Example:

```text
verify_claim("1")
```

The leader and validator independently evaluate the claim.

If their substantive verdicts match, the final result is stored.

---

### `get_claim`

Returns the complete claim record.

Example:

```text
get_claim("1")
```

---

### `get_verdict`

Returns:

```text
APPROVED
```

or:

```text
REJECTED
```

---

### `get_status`

Returns the current claim status:

```text
PENDING
APPROVED
REJECTED
```

---

### `get_counter`

Returns the total number of submitted claims.

---

### `get_latest_id`

Returns the most recently created claim ID.

---

## Example: Approved Claim

Input:

```text
Claim:
The Eiffel Tower is located in Paris.

Criteria:
The evidence must explicitly establish that the Eiffel Tower
is located in Paris.
```

Assume both independent executions determine:

```text
Leader    → APPROVED
Validator → APPROVED
```

The consensus condition becomes:

```text
APPROVED == APPROVED
```

Result:

```text
CONSENSUS ACCEPTED
```

The claim is stored as:

```text
status  = APPROVED
verdict = APPROVED
```

---

## Example: Rejected Claim

Input:

```text
Claim:
The Eiffel Tower is located in London.

Criteria:
The evidence must explicitly establish that the Eiffel Tower
is located in London.
```

The evidence does not establish the claim.

Both independent evaluations may therefore determine:

```text
Leader    → REJECTED
Validator → REJECTED
```

The consensus condition becomes:

```text
REJECTED == REJECTED
```

Result:

```text
CONSENSUS ACCEPTED
```

The claim is stored as:

```text
status  = REJECTED
verdict = REJECTED
```

Notice that consensus does not mean "approved".

Consensus means that the independent verification processes agree on the substantive result.

---

## Example: Conflicting Verification

Consider a case where the independent executions produce:

```text
Leader    → APPROVED
Validator → REJECTED
```

The consensus condition becomes:

```text
APPROVED != REJECTED
```

Therefore:

```text
CONSENSUS FAILED
```

The contract does not treat the leader's decision as authoritative.

This is the central property of the design.

---

## Why Reasoning Is Not Compared

The contract compares the substantive decision:

```text
APPROVED
```

or:

```text
REJECTED
```

It does not require both nodes to produce identical natural-language reasoning.

For example:

Leader:

```json
{
  "verdict": "APPROVED",
  "reasoning": "Two independent sources establish the location."
}
```

Validator:

```json
{
  "verdict": "APPROVED",
  "reasoning": "The supplied evidence directly confirms the claim."
}
```

These responses have different wording but the same substantive decision.

Therefore:

```text
APPROVED == APPROVED
```

and consensus can succeed.

This avoids requiring nondeterministic natural-language explanations to be byte-for-byte identical.

---

## Why This Is a GenLayer Use Case

Traditional smart contracts cannot natively determine whether arbitrary external web evidence substantively supports a natural-language claim.

EvidenceConsensus uses GenLayer's intelligent-contract execution model to combine:

* Smart-contract state
* External web evidence
* LLM-based reasoning
* Independent validator execution
* Consensus-based verification

The blockchain stores the resulting verified state only after the independent verification processes agree.

---

## Design Principles

### 1. Evidence first

The decision is based on fetched evidence rather than an unsupported model assumption.

### 2. Independent validation

The validator performs the verification task itself.

### 3. Substantive consensus

Consensus compares the actual decision:

```text
APPROVED / REJECTED
```

rather than merely checking output formatting.

### 4. Deterministic state mutation

External and nondeterministic work happens during consensus execution.

Contract storage is updated only after the consensus result is available.

### 5. Reusable primitive

The contract is not tied to one specific domain.

The same primitive can be used for:

* Fact verification
* Document verification
* Research claims
* Product claims
* Compliance checks
* DAO governance evidence
* AI-generated claims
* Provenance verification
* Real-world information verification

---

## Security Considerations

EvidenceConsensus does not assume that an individual LLM response is correct.

Instead, it relies on independent evaluation and agreement.

The validator is intentionally given the same substantive inputs:

```text
claim
criteria
evidence
```

and must independently reach the same verdict.

This prevents the validator from accepting a leader decision solely because it uses an allowed label.

The contract therefore turns the validator from a **format checker** into a **substantive verifier**.

---

## Limitations

Consensus agreement does not mathematically prove that a real-world claim is true.

It establishes that the independent GenLayer verification executions reached the same substantive conclusion from the supplied evidence and criteria.

External websites can also change, disappear, block automated requests, or provide conflicting information.

For this reason, the contract stores the verified evidence and supporting-source information alongside the final decision.

---

## Deployment

The contract is designed to be deployed directly through **GenLayer Studio**.

No frontend is required.

The intended workflow is:

```text
Deploy contract
      ↓
create_claim()
      ↓
verify_claim()
      ↓
GenLayer consensus
      ↓
get_claim()
```

All interaction can be performed directly through the GenLayer Studio interface.

---

## Example Workflow

### 1. Create a claim

```text
create_claim(
    "The Eiffel Tower is located in Paris.",
    "The evidence must explicitly establish that the Eiffel Tower is located in Paris.",
    [
        "SOURCE_URL_1",
        "SOURCE_URL_2"
    ]
)
```

### 2. Receive claim ID

```text
"1"
```

### 3. Verify

```text
verify_claim("1")
```

### 4. Read result

```text
get_claim("1")
```

### 5. Read final verdict

```text
get_verdict("1")
```

Possible result:

```text
APPROVED
```

or:

```text
REJECTED
```

---

## Project Goal

EvidenceConsensus is designed as a reusable GenLayer contract primitive demonstrating a stronger approach to AI-assisted verification:

```text
External Evidence
       +
Explicit Criteria
       +
Independent Evaluation
       +
Validator Re-evaluation
       +
Substantive Verdict Matching
       =
Evidence-Based Consensus
```

The central idea is that **validators should independently verify the claim itself, not merely validate the shape of another model's response.**

---

## License

MIT
