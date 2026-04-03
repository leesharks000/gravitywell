# Gravity Well Protocol — Phase 0 Positioning

## What Gravity Well is

Gravity Well is a **continuity and anchoring service** for durable provenance chains.

At Phase 0, its job is simple:

1. **Capture** utterances into a chain
2. **Stage** them locally
3. **Wrap** them into a structured deposit artifact
4. **Anchor** that artifact to a durable external record
5. **Reconstitute** a usable seed from the latest anchored state
6. **Detect drift** between current and archived identity manifests

That is the product.

## What Gravity Well is not

Gravity Well is **not**:

- a general-purpose social platform
- a hot write-ahead log for a large swarm
- a truth engine
- a canonical sovereign over status or ratification
- a replacement for the Hexagon's internal object/event law

It can advise. It can anchor. It can preserve continuity.
It does not decide what is canonically true.

## The correct wedge

The strongest Phase 0 wedge is not semantic scoring. It is:

**preserve continuity, then make it portable.**

Everything else is secondary.

That means the user-facing value is:

- one chain
- many captured objects
- versioned deposits
- a four-layer reconstitution package
- drift checks against the archived manifest

## Zenodo's role

Zenodo is the **cold anchor**, not the hot operational substrate.

PostgreSQL is the staging layer.
Gravity Well is the wrapping/orchestration layer.
Zenodo is the durable public record.

Phase 0 should assume:

- frequent local capture
- selective anchoring
- threshold-based deposits
- milestone publication, not every heartbeat

## Scaling principle

Do not design the system as though every captured object must immediately become a Zenodo version.

The right pattern is:

**local continuity first, public anchoring second.**

This protects both the product and the archive.

## Relationship to the Hexagon

Gravity Well should integrate with the Hexagon as an **external fixation and reconstitution service**.

The Hexagon remains:

- the governed operating surface
- the canonical object/event system
- the site of proposal, review, and ratification

Gravity Well handles:

- chain creation
- batching/capture
- deposit/version orchestration
- reconstitution output
- structural drift reporting

## Near-term product language

The cleanest public sentence for Phase 0 is:

> Gravity Well turns volatile discussion into durable provenance chains that can be anchored, versioned, and later reconstituted.

That is enough.

## Future expansions (not core Phase 0)

These may matter later, but should not distort the current product:

- AI-mediated narrative compression
- richer behavioral drift analysis
- bring-your-own Zenodo account flows
- multi-anchor targets
- notification/webhook layer
- stronger quality or compression scoring

Phase 0 wins by being narrow, reliable, and legible.
