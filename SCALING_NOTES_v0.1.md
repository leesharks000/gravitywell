# Gravity Well Scaling Notes v0.1

## Core principle

Zenodo is the **cold anchor layer**.
It is not the hot operational substrate.

Gravity Well should scale through:

- local capture
- local staging
- selective deposit/version events
- threshold-based anchoring

not by treating every captured object as an immediate public deposit.

## What should scale locally

These operations are cheap and should remain the high-frequency path:

- chain creation
- capture
- staging inspection
- local history
- reconstitution packaging
- drift checks

These define the day-to-day continuity loop.

## What should scale selectively

These operations should be lower-frequency:

- first public anchor
- versioned Zenodo deposits
- DOI-producing milestone releases
- durable public continuity snapshots

This protects both the product and the archive.

## Architectural rule

The right pattern is:

**capture often, deposit deliberately.**

A chain may accumulate many staged objects before a public version is warranted.

## Why this matters

Using Zenodo as a hot write path creates three avoidable problems:

1. policy/fair-use pressure
2. operational brittleness under external latency or service interruptions
3. premature public version churn for objects that are still volatile

Phase 0 should therefore assume:

- Zenodo for milestone anchoring
- PostgreSQL for operational continuity
- Gravity Well as the orchestrating wrap/anchor layer

## Product implication

Gravity Well should present itself as:

> a continuity-and-anchoring service with selective public fixing

not as:

> a platform that deposits every utterance in real time

## Relationship to bring-your-own Zenodo

Per-user Zenodo credentials may become important later, but they do not change the architectural rule.

Even with distributed account ownership, the right model remains:

- local continuity first
- public anchoring second

## Practical threshold examples

Phase 0 deposit triggers might include:

- every N captured objects in a chain
- explicit user-curated release
- end-of-session continuity snapshot
- publication-ready dashboard action
- governance-approved fix event

The exact threshold can vary by client, but the rule is the same:

**not every heartbeat becomes a DOI.**
