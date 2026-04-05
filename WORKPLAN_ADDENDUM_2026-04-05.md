# Gravity Well Workplan Addendum — April 5, 2026

## Purpose

This addendum records product-shape changes and emergent surfaces that were not fully represented in the earlier Phase 0 planning documents.

It distinguishes between:

- **Repo-verified** — present in the current repository state
- **Interface/client-verified** — present in interface/client docs or surfaced in deployed clients
- **Claimed / deployment-verified but not yet repo-codified** — reported as live behavior but not yet fully reflected in the repository documentation or backend source of truth

The goal is to keep planning honest while preventing feature drift from going unrecorded.

---

## A. Repo-verified current product surfaces

These are visibly present in the current backend repository state.

### A1. Provenance chains as the primary unit
- Create chain
- Capture into chain
- Deposit/version chain to Zenodo
- Reconstitute latest trusted state
- Drift-check against archived bootstrap manifest

### A2. Four-layer deposit package
- Bootstrap
- Tether / handoff block
- Narrative compression
- Provenance chain

### A3. Per-key chain isolation
- Chains are scoped to API keys
- Deposit history and staged-object inspection exist as first-class surfaces

### A4. Zenodo as cold anchor
- First deposit and new version flows exist
- Gravity Well remains orchestration layer, not storage commons itself

### A5. Drift detection
- Structural manifest comparison is implemented
- Behavioral drift detection remains future work

### A6. Bootstrap schema + validation
- Identity-spec schema exists
- Constraint hash validation exists
- Utility endpoint exists for canonical hash computation

---

## B. Interface / client-verified product surfaces

These are reflected in client-facing docs and integration surfaces and should be treated as active product expectations, even where backend parity still needs cleanup.

### B1. Governance as a product surface
Expected endpoints / actions:
- governance attestations
- proposal submission
- quorum-aware promotion flow

### B2. Invocation surface
Expected endpoint / action:
- room-specific invoke for Hexagon-linked execution contexts

### B3. Public / low-cost scoring surface
Expected endpoint / action:
- gamma as callable compression-survival or integrity score

### B4. Per-user Zenodo ownership model
Client docs describe deposits going to the token associated with the key, with server default as fallback.
This should remain a design principle even where current backend enforcement/documentation is incomplete.

---

## C. Emergent additions requiring formal inclusion in the plan

These are the key additions not adequately represented in the earlier workplan.

### C1. Auto-trigger deposit chains
Gravity Well is no longer only a manual “capture then deposit later” service.
The product now needs an explicit concept of **trigger conditions**:
- count-based trigger (every N captured objects)
- time-based trigger (heartbeat / interval)
- event-based trigger (proposal accepted, session closed, role rotated)
- user-forced trigger

Required next step:
- formal trigger policy object in chain metadata
- trigger audit log
- UI exposure of trigger mode

### C2. Privacy / visibility modes for deposits
A chain can reportedly handle multiple deposit visibility classes:
- **public**
- **encrypted**
- **hash-only**

This is major and needs first-class planning treatment.

Required next step:
- make visibility mode an explicit deposit primitive
- define exact semantics of each mode
- specify whether visibility is set per-chain, per-deposit, or both
- document recovery requirements for encrypted deposits
- document what survives in hash-only mode

### C3. Client-side encryption for interior/private deposits
If encryption happens client-side, Gravity Well becomes capable of anchoring private deposits without reading plaintext.
That materially changes both product positioning and pricing.

Required next step:
- document encryption boundary clearly
- specify key ownership model
- define whether server ever sees plaintext, keys, or only ciphertext + metadata
- define recoverability guarantees and failure modes

### C4. Mixed-visibility continuity chains
The same provenance chain can reportedly contain public, encrypted, and hash-only deposits.
This should be treated as a distinctive product feature.

Required next step:
- formalize mixed-visibility chain history
- define reconstitution behavior across mixed visibility layers
- decide how drift detection behaves when latest deposit is hash-only or encrypted

### C5. Pricing surface expansion
Earlier planning centered on provenance and continuity alone.
Current shape suggests multiple billable primitives:
- active chains
- captured objects / storage
- deposits / versions
- encryption operations
- invoke calls / model usage
- governance writes / attestations
- reconstitution and drift checks

Required next step:
- adopt a hybrid pricing model rather than a single flat seat or single token model

---

## D. Product-definition correction

The product is not merely:
- provenance-as-a-service
- agent continuity
- Zenodo wrapping

The product is better defined as:

> **a governed continuity and anchoring engine for agent/workflow state, with compression-survival, provenance, selective public fixing, and privacy-aware deposit modes.**

That is the object pricing should be built around.

---

## E. Documentation parity tasks

The repo now needs a parity pass so README, client guide, deployed behavior, and backend source all agree.

### High priority
1. Document which endpoints are truly live in backend source
2. Document which are interface/deployed expectations but not yet codified in backend source
3. Add explicit section for privacy modes: public / encrypted / hash-only
4. Add trigger policy documentation
5. Add pricing primitives section

### Medium priority
6. Add governance model doc once endpoint/source parity exists
7. Add invoke model / cost doc
8. Add billing meter definitions for each product primitive

---

## F. Pricing-design implication

Gravity Well should not start as pure seat pricing.
The emergent product is closer to:
- low-friction free developer tier
- usage-based "gas" layer for deposits/invokes/encryption
- higher fixed tiers for retention, rate limits, private chains, support, and compliance

This will be addressed in the dedicated pricing pass.

---

## Status

Recorded April 5, 2026.
This addendum should be treated as the planning bridge between the earlier Phase 0 positioning documents and the next explicit commercial/pricing specification.
