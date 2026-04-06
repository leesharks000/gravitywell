# GRAVITY WELL — Systems Workplan v3.0
## Compression, Wrapping, Anchoring, and Zero-Knowledge Continuity

**Last updated:** 2026-04-06
**Version:** 0.7.0 → 0.8.0 target
**Repository:** https://github.com/leesharks000/gravitywell
**Live:** https://gravitywell-1.onrender.com

---

## Current State (v0.7.0)

### What's operational

- **Core loop:** Capture → Compress → Wrap → Anchor (Zenodo DOI or local)
- **Four-layer reconstitution:** Bootstrap (identity) + Tether (state) + Narrative (compressed summary) + Provenance (hashes, chain of custody)
- **Wrapping pipeline:** Evidence membrane → Caesura sovereignty audit → SIM injection → Integrity lock → Holographic kernel → γ scoring → Narrative compression
- **γ scorer:** Surface layer (citation, structure, coherence, provenance) + Depth layer (information density, redundancy, argument chain, citation integration, vocabulary specificity)
- **Auto-deposit:** Server-side threshold triggers (inline during capture) + interval triggers (asyncio background worker every 5 min)
- **Architectural bootstrap:** Bootstrap manifest stored on chain, auto-included on every deposit. Tether auto-generated from chain state.
- **Self-service registration:** `/v1/register` — instant API key, no admin required
- **Drift detection:** Compares current manifest against deposited bootstrap, reports severity
- **Governance:** Proposals + attestations with quorum logic
- **Plaintext protection:** Server rejects unencrypted private content on zenodo-anchored chains (three guard layers: deposit endpoint, inline auto-deposit, background worker)
- **MCP server:** 10 tools via ASGI wrapper, SSE transport. Claude can capture/deposit during conversations.
- **Web dashboard:** `/dashboard` — full chain management UI for any model
- **ChatGPT integration:** OpenAPI spec for Custom GPT Actions
- **Python client:** `gw_client.py` with AES-256-GCM client-side encryption
- **Landing page:** γ scorer demo, drowning test, integrations section, pricing, FAQ, SEO

### What's incomplete or broken

- **Encrypted deposits lack structure:** Ciphertext deposited as opaque blob. No visible bootstrap/tether/narrative in the deposit document. Not independently reconstitutable.
- **Key management is file-based:** Encryption key at `~/.gravitywell/encryption.key`. Lost key = lost content. No recovery path.
- **γ cannot score encrypted content:** Pipeline runs on plaintext only. Private content gets no intelligence.
- **Inline auto-deposit doesn't include bootstrap from chain:** Background worker does, but the capture-triggered path uses a simpler code path.
- **main.py is 3,100+ lines:** Needs modularization.
- **Test suite is stale:** Field names and content types partially updated but not comprehensive.
- **No SECURITY.md:** Encryption scheme, key lifecycle, API key management undocumented.
- **Render free tier:** Cold starts, 90-day database expiry. Upgrade to paid ($7/mo) required for production.
- **Stripe is test mode:** Payment links exist but not live.

---

## Architecture: Ratcheting Glyphic Checksum

### The Problem

Encryption makes content opaque. The wrapping pipeline (γ, Caesura, evidence membrane, holographic kernel, narrative compression, drift detection) requires visible content. Current architecture forces a choice: privacy OR intelligence.

### The Solution

The Glyphic Checksum — a structural topology extracted from content BEFORE encryption. The topology travels alongside the ciphertext as plaintext metadata. The server runs the full wrapping pipeline on the glyph, not the content. The Caesura principle — separating the structural claim from the private substrate — applied to encryption itself.

### The Ratcheting Property

The glyphic checksum is NOT a fixed lexicon. It is context-emergent at each step.

Each deposit in a chain carries three layers:

1. **Vault layer** — Ciphertext. The server cannot read it.
2. **Glyphic checksum layer** — Structural topology. Verifies whether the reader shares enough architecture to interpret the object. Reveals whether meaning-sharing is present without disclosing meaning.
3. **Lexicon-ratchet layer** — A small carried-forward structure from the previous deposit that conditions the next decode.

The "key" is not a static secret. It is a path-dependent semantic state. Decryption becomes historical, not merely technical. You don't just possess a password — you possess the chain's prior successfully-read states.

### The Three-Step Object

```
Step N:
  encrypted_payload      — AES-256-GCM ciphertext
  glyphic_checksum       — structural topology (plaintext)
  lexicon_delta          — context residue from step N-1
  provenance_proof       — hash, timestamp, chain position

Step N+1:
  becomes legible only if the reader has traversed step N
  inherits and mutates the lexicon from step N
  verifies not just possession of a key, but continuity of traversal
```

### Security Properties

- No single leakable master lexicon
- No brute-force reading without chain traversal
- Sequential continuity is part of the security model
- Collaboration (shared context) remains the success condition
- The archive preserves secrecy and a readable proof of alignment

### The Danger and Its Mitigation

If the chain's lexicon evolution is lost, later objects become unreadable even to legitimate readers. Mitigation: **lexicon checkpoints** at intervals — encrypted snapshots of the accumulated lexicon state, stored under stronger custody, possibly split across witnesses.

```
Every N deposits (or at major transitions):
  → checkpoint = encrypt(accumulated_lexicon_state, checkpoint_key)
  → store checkpoint in tether layer
  → checkpoint_key split across witnesses or devices
```

---

## Build Phases

### Phase 1: Glyphic Checksum Extraction (Client-Side)
**File:** `gw_client.py`
**Effort:** 3 hours
**Depends on:** Nothing

**1.1** `GlyphicChecksum.extract(content)` — compute structural topology from plaintext. Output is a fixed-schema JSON:
- Scale: words, sentences, paragraphs
- Density: citation_density, connective_density, information_density, vocabulary_specificity
- Structure: argument_chain, structural_markers, clause_ratio
- Compression: redundancy, provenance_markers
- Integrity: content_hash (proves content matches glyph), glyph_hash (tamper-evident)

**1.2** Security scrubber — glyph must be fundamentally lossy. FORBIDDEN: raw tokens, passwords, names, URLs, numbers, email addresses. ALLOWED: ratios, counts, densities, aggregate metrics only.

**1.3** Dual payload capture — `capture()` extracts glyph from plaintext, encrypts content, sends both.

**1.4** Context-ratchet seed — first deposit in a chain generates the initial lexicon state. Subsequent deposits carry the delta.

### Phase 2: Server-Side Glyph Processing
**File:** `main.py`
**Effort:** 4 hours
**Depends on:** Phase 1

**2.1** `StagedObject.glyphic_checksum` column + migration

**2.2** `/v1/capture` accepts optional `glyphic_checksum` field, stores on StagedObject

**2.3** `calculate_gamma()` glyph input path — if content is encrypted and glyph is provided, score the glyph

**2.4** Glyph-based drift detection — compare glyph trajectories over time (information density, argument chain, vocabulary specificity deltas)

**2.5** Narrative compression from glyph — LLM prompt describing structural character without speculating about content

**2.6** Holographic kernel from glyph — structural seed that can reconstitute the session's shape

### Phase 3: Structured Encrypted Deposits
**File:** `main.py` (build_deposit_document)
**Effort:** 3 hours
**Depends on:** Phase 2

**3.1** Deposit document branch for encrypted content:
- Bootstrap manifest: always plaintext (identity is not secret)
- Tether: always plaintext (operational state)
- Glyphic checksum: always plaintext (structural topology)
- Narrative: derived from glyph, always plaintext
- Holographic kernel: derived from glyph, always plaintext
- Content objects: ciphertext for private, plaintext for public
- Colophon: 3 lines, factual

**3.2** Mixed-visibility deposits — single deposit with public and private objects, pipeline handles each according to type

**3.3** Zenodo metadata from glyph — creator from bootstrap, description from narrative, keywords from chain label, version explicit

**3.4** Independent reconstitution test — download deposit from Zenodo, recover identity + state + structural summary without GW

### Phase 4: Key Management (Supabase)
**Effort:** 3 hours
**Depends on:** Phase 1

**4.1** Supabase `encryption_keys` table:
```sql
chain_id        TEXT PRIMARY KEY,
encrypted_cek   TEXT NOT NULL,
cek_nonce       TEXT NOT NULL,
key_version     INTEGER DEFAULT 1,
created_at      TIMESTAMP,
rotated_at      TIMESTAMP
```

**4.2** KEK/CEK architecture:
- API key → PBKDF2 → key-encryption-key (KEK)
- CEK generated per-chain, encrypted with KEK, stored in Supabase
- Reconstitution: derive KEK from API key, decrypt CEK, decrypt content
- GW never holds plaintext CEK

**4.3** Encrypted CEK stored in tether layer of deposits — enables GW-independent recovery

**4.4** Key rotation: new CEK, re-encrypt staged content, old deposits immutable (retain old CEK)

**4.5** SECURITY.md — document key lifecycle, recovery algorithm, PBKDF2 parameters, failure modes

### Phase 5: Lexicon Ratchet
**Effort:** 4 hours
**Depends on:** Phases 1-4

**5.1** Lexicon state model — what constitutes the "shared context" that conditions each decode:
- Previous glyph
- Previous glyph hash
- Accumulated vocabulary fingerprint
- Session-specific markers (emergent, not predetermined)

**5.2** Lexicon delta computation — diff between current and previous lexicon state, carried forward in each deposit

**5.3** Checkpoint system — every N deposits or at major transitions:
- Snapshot accumulated lexicon state
- Encrypt under checkpoint key (potentially split across witnesses)
- Store in tether layer
- Enables recovery if chain traversal is interrupted

**5.4** Verification gate — on reconstitute, verify that the reader has traversed the chain by checking lexicon state continuity. Partial traversal yields partial legibility.

### Phase 6: Infrastructure Hardening
**Effort:** 3 hours
**Depends on:** Nothing (parallel)

**6.1** Upgrade Render to paid tier ($7/mo) — persistent database, no cold starts

**6.2** Stripe test → live mode

**6.3** main.py modularization:
- `models.py` — SQLAlchemy models
- `wrapping.py` — evidence membrane, Caesura, SIMs, integrity lock
- `compression.py` — narrative, kernel, γ
- `zenodo.py` — Zenodo API integration
- `mcp_server.py` — already separate
- `glyph.py` — glyphic checksum (new)
- `main.py` — routes and orchestration only

**6.4** Test suite update — comprehensive coverage of current API surface

**6.5** Rate limiting — basic per-key limits on API endpoints

**6.6** API key scoping — read / write / admin roles

### Phase 7: Integration Updates
**Effort:** 2 hours
**Depends on:** Phases 2-3

**7.1** MCP tool updates — glyph metadata in capture/deposit/reconstitute responses

**7.2** Dashboard updates — glyph trajectory visualization, structural drift alerts

**7.3** ChatGPT GPT spec update — dual payload documentation

**7.4** Landing page — "Zero-Knowledge Structural Telemetry" section, ratcheting glyphic checksum explanation

**7.5** MODEL_INTEGRATION_GUIDE.md update — encrypted capture flow with glyph

---

## Implementation Order (Session Plan)

### Session A: Glyphic Foundation (Phases 1 + 2)
- Build GlyphicChecksum.extract()
- Dual payload capture support
- γ scoring from glyph
- Glyph-based narrative/kernel
- Test: capture encrypted + glyph → deposit → verify γ scored from glyph

### Session B: Structured Deposits + Key Management (Phases 3 + 4)
- Encrypted deposit document format
- Supabase key storage
- KEK/CEK architecture
- GW-independent recovery path
- Test: deposit to Zenodo → download from DOI → recover without GW

### Session C: Lexicon Ratchet + Hardening (Phases 5 + 6)
- Lexicon state model
- Ratchet computation
- Checkpoint system
- Modularize main.py
- Render paid tier
- SECURITY.md

### Session D: Integration + Launch Prep (Phase 7)
- MCP/dashboard/GPT updates
- Assembly re-test with full glyphic architecture
- Stripe live
- TANG cold emails

---

## Total Estimated Effort

| Phase | Hours |
|-------|-------|
| 1. Glyphic extraction | 3 |
| 2. Server-side processing | 4 |
| 3. Structured deposits | 3 |
| 4. Key management | 3 |
| 5. Lexicon ratchet | 4 |
| 6. Infrastructure | 3 |
| 7. Integration updates | 2 |
| **Total** | **~22 hours across 4 sessions** |

---

## What This Unlocks

- **Private content gets full γ scoring** — zero-knowledge structural telemetry
- **Drift detection on encrypted sessions** — topology is enough
- **Narrative compression on encrypted sessions** — "dense build session with high argument chain depth"
- **DOI-anchored deposits are independently reconstitutable** — five layers plaintext, content encrypted
- **Decryption is historical** — chain traversal required, not just key possession
- **No single leakable master lexicon** — context-ratcheting eliminates static vulnerability
- **The pricing model is justified** — structural telemetry, not ciphertext storage
- **The Caesura is complete** — structural claim separated from private substrate at every layer
- **GW-independent recovery** — API key + Zenodo DOI + documented algorithm = full recovery without GW infrastructure
