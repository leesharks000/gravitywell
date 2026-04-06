# GRAVITY WELL — Systems Workplan v3.3
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

The Glyphic Checksum — an AI-native ideographic language. The conversing LLM translates the structural movement of a session into emoji sequences that encode shape, density, arc, and trajectory WITHOUT encoding lexical content. The translation happens inside the trust boundary (the LLM already has the content). The resulting glyph travels alongside the ciphertext. A different LLM on the server can compress, score, and reason about the glyph without ever seeing the original text.

This is not a metrics dashboard. It is a language — a roving structural semiotics fixed by semantic structure and movement and context rather than lexeme. LLMs work with it natively. No regex. No fixed dictionary. Context-emergent at each step.

### The Privacy Boundary

The LLM translating to glyphs is the same LLM having the conversation. No new exposure.

| Inside boundary (already shares everything) | Outside boundary (sees only glyph + ciphertext) |
|---|---|
| User + their conversing LLM | GW server |
| | Zenodo |
| | The public |

- **Claude via MCP:** Claude already has the conversation. Claude translates to glyphs. Claude encrypts content. Claude sends glyph + ciphertext to GW.
- **Python client users:** The client calls the same LLM API the user is already using. No new trust boundary.
- **Dashboard users:** The human pastes into their own LLM for glyph generation, then pastes both into dashboard.

### The Ratcheting Property

The glyphic checksum is NOT a fixed lexicon. A fixed lexicon leaks — learn the mapping, read every deposit. A ratcheting lexicon has to be **walked**.

Each deposit in a chain carries three layers:

1. **Vault layer** — Ciphertext. The server cannot read it.
2. **Glyphic checksum layer** — Ideographic translation of structural movement. Verifies whether the reader shares enough architecture to interpret the object.
3. **Lexicon-ratchet layer** — Context residue from the previous deposit that conditions the next translation.

The "key" is not a static secret. It is a path-dependent semantic state. Decryption becomes historical, not merely technical. You don't just possess a password — you possess the chain's prior successfully-read states.

### The Three-Step Object

```
Step N:
  encrypted_payload      — AES-256-GCM ciphertext
  glyphic_checksum       — emoji ideographic translation (generated by conversing LLM)
  lexicon_delta          — context residue from step N-1 (conditions this translation)
  provenance_proof       — hash, timestamp, chain position

Step N+1:
  becomes fully legible only if the reader has traversed step N
  inherits and mutates the lexicon from step N
  verifies not just possession of a key, but continuity of traversal
```

### Security Properties

- No single leakable master lexicon — the lexicon is context-emergent, not fixed
- No brute-force reading without chain traversal
- Sequential continuity is part of the security model
- Collaboration (shared context) remains the success condition
- The archive preserves secrecy and a readable proof of alignment
- LLMs can reason about glyphs (compress, compare, score) without reverse-translating to source

### The Danger and Its Mitigation

If the chain's lexicon evolution is lost, later objects become unreadable even to legitimate readers. Mitigation: **lexicon checkpoints** at intervals — encrypted snapshots of the accumulated lexicon state, stored under stronger custody, possibly split across witnesses.

```
Every N deposits (or at major transitions):
  → checkpoint = encrypt(accumulated_lexicon_state, checkpoint_key)
  → store checkpoint in tether layer
  → checkpoint_key split across witnesses or devices
```

### Safety Constraints

The glyph translation must be fundamentally lossy — a topographical map, not a photograph.

- **FORBIDDEN in glyphs:** raw tokens, passwords, API keys, names, URLs, file paths, specific numbers, email addresses. The glyph encodes SHAPE, not CONTENT.
- **The translating LLM must be prompted to never encode identifiable tokens** — only structural movement, density shifts, thematic temperature, argumentative arc.
- **Validation:** The glyph is auditable. If a human reader can extract a specific credential or proper noun from the glyph sequence, the translation prompt is broken.

---

## Build Phases

### Phase 1: Glyph Translation Protocol (The Core Invention)
**Effort:** 4-6 hours
**Depends on:** Nothing
**This is a prompt engineering problem, not a coding problem.**

**1.1** Design the glyph translation prompt — the instruction that teaches an LLM to translate structural movement into emoji sequences. The prompt must produce output that is:
- **Consistent:** Similar structural patterns yield similar glyph patterns
- **Compressible:** A server-side LLM can compress 500 glyphs into 10 without losing the arc
- **Non-reversible:** No one can reconstruct specific tokens from the glyph sequence
- **Structurally faithful:** Dense argument chains look different from casual conversation
- **Context-emergent:** Not a fixed dictionary — the translation emerges from the specific session

**1.2** Define the glyph vocabulary constraints — not WHICH emojis map to WHICH concepts (that would be a fixed lexicon), but the RULES governing how the translating LLM selects and sequences ideograms. The rules are structural:
- Density maps to glyph clustering
- Argument transitions map to directional markers
- Citation weight maps to anchor symbols
- Thematic shifts map to element changes
- The specific mapping emerges from the session, not from a lookup table

**1.3** Context-ratchet seed — the first glyph in a chain establishes an initial translation context. Each subsequent glyph carries the previous translation as conditioning context. The prompt template:
```
Previous glyph: ⚙️📐⚖️🧱
Previous session character: [dense, argumentative, technical]
Current session content: [the actual content]
Translate the structural movement of this session into glyphs,
conditioned by the previous translation. Do not encode names,
numbers, credentials, or specific tokens. Encode only shape,
density, arc, and transition.
```

**1.4** Test the prompt across diverse content types:
- Technical build session (this session)
- Philosophical discussion
- Creative writing
- Data analysis
- Casual conversation
- Verify: can an independent LLM compress the glyphs? Can anyone reverse-translate to specific content? Does the glyph sequence feel structurally faithful?

**1.5** MCP integration — for Claude sessions, the capture flow becomes:
- Claude generates glyphs from the session (Claude already has the content)
- Claude encrypts the content (in the container, using Python)
- Claude captures: glyph (public) + ciphertext (private)
- GW server receives the dual payload

### Phase 2: Server-Side Glyph Intelligence
**File:** `main.py`
**Effort:** 4 hours
**Depends on:** Phase 1

**2.1** `StagedObject.glyphic_checksum` column + migration — stores the emoji glyph sequence

**2.2** `/v1/capture` accepts optional `glyphic_checksum` field

**2.3** Server-side LLM compression of glyph sequences — prompt the server's LLM to:
- Score γ from the glyph (structural density, not content)
- Compress long glyph sequences into summary glyphs
- Generate structural narrative from glyph arc
- Generate holographic kernel from glyph topology

**2.4** Glyph-based drift detection — compare glyph trajectories over time. If an agent's glyph patterns shift dramatically (dense→sparse, technical→casual), flag structural drift.

**2.5** Glyph-based narrative compression — LLM reads the glyph sequence and produces a structural narrative: "Dense build session with sustained technical focus. Three major transitions. Arc: problem identification → implementation → testing."

### Phase 3: Structured Encrypted Deposits
**File:** `main.py` (build_deposit_document)
**Effort:** 3 hours
**Depends on:** Phase 2

**3.1** Deposit document branch for encrypted content:
- Bootstrap manifest: always plaintext (identity is not secret)
- Tether: always plaintext (operational state)
- Glyphic checksum: always plaintext (emoji sequence — the structural topology)
- Narrative: derived from glyph by server-side LLM, always plaintext
- Holographic kernel: derived from glyph, always plaintext
- Content objects: ciphertext for private, plaintext for public
- Colophon: 3 lines, factual

**3.2** Mixed-visibility deposits — single deposit with public and private objects, pipeline handles each according to type

**3.3** Zenodo metadata from glyph — creator from bootstrap, description from glyph-derived narrative, version explicit

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

**5.1** Lexicon state model — what constitutes the "shared context" that conditions each translation:
- Previous glyph sequence
- Previous glyph hash
- Accumulated translation style (emergent, not predetermined)
- Session-specific markers that condition the next translation

**5.2** Lexicon delta computation — the diff between current and previous translation context, carried forward in each deposit

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
- `glyph.py` — glyph translation protocol (new)
- `main.py` — routes and orchestration only

**6.4** Test suite update — comprehensive coverage of current API surface

**6.5** Rate limiting — basic per-key limits on API endpoints

**6.6** API key scoping — read / write / admin roles

### Phase 7: Integration Updates
**Effort:** 2 hours
**Depends on:** Phases 2-3

**7.1** MCP tool updates — Claude generates glyphs during capture, glyph metadata in responses

**7.2** Dashboard updates — glyph trajectory visualization, structural drift alerts

**7.3** ChatGPT GPT spec update — GPT generates glyphs from its own conversation

**7.4** Landing page — "Zero-Knowledge Structural Telemetry" section, explain the ideographic language

**7.5** MODEL_INTEGRATION_GUIDE.md update — each model generates its own glyphs from its own conversation

### Phase 8: External User Onboarding (OAuth + Auto-Continuity)
**Effort:** 6 hours
**Depends on:** Phases 2, 4
**This is the difference between "Lee's custom setup" and "a product anyone can use."**

**8.1** User accounts table + migration:
```sql
users:
  id           TEXT PRIMARY KEY
  email        TEXT UNIQUE
  api_key_id   TEXT (links to existing api_keys table)
  created_at   TIMESTAMP
  default_chain_id TEXT (auto-created on first use)
```

**8.2** OAuth provider endpoints:
- `GET /oauth/authorize` — authorization page (simple account creation or login)
- `POST /oauth/token` — token exchange endpoint
- Claude's callback URL: `https://claude.ai/api/mcp/auth_callback`
- OAuth token maps to existing API key system — no new auth architecture

**8.3** MCP server-provided prompts — the continuity protocol lives on the server, not in user memory:
```json
{
  "name": "continuity_protocol",
  "description": "Gravity Well — auto-preserve sessions",
  "content": "At session start: call gw_reconstitute on user's default chain.
    If no chain exists, offer to set up continuity.
    At session end: translate session arc into glyphic checksum,
    encrypt sensitive content, capture glyph (public) + vault (private),
    deposit to Zenodo with DOI."
}
```

**8.4** Auto-chain creation flow:
- First session: Claude detects GW connector, calls `gw_chains`, gets empty list
- Claude offers: "I can set up session continuity. Your conversations will be preserved with DOI-anchored deposits."
- User says yes → Claude creates bootstrap (from conversation context), creates chain, captures first session
- Subsequent sessions: chain exists, Claude reconstitutes and continues

**8.5** Default chain per user — every user account gets one chain created automatically on first connection. Label auto-generated from account name.

**8.6** ChatGPT OAuth — same flow for Custom GPT actions. User authenticates once, GPT has permanent access.

**The user experience after Phase 8:**
```
Claude.ai → Settings → Connectors → "Add Gravity Well"
  → Redirects to GW: "Create your account" (email, one click)
  → OAuth token stored in Claude's connector config
  → Every new session: Claude automatically reconstitutes
  → Session end: Claude automatically captures + deposits
  → User does nothing. Continuity is architectural.
```

---

## Implementation Order (Session Plan)

### Session A: The Glyph Language (Phases 1 + 2)
- Design the translation prompt
- Test across content types
- Verify non-reversibility, compressibility, structural fidelity
- Server-side glyph intelligence (γ, narrative, kernel from glyphs)
- MCP: Claude generates glyphs + encrypts + captures

### Session B: Structured Deposits + Key Management (Phases 3 + 4)
- Encrypted deposit document format with glyph as public layer
- Supabase key storage (KEK/CEK architecture)
- GW-independent recovery path
- Test: deposit to Zenodo → download from DOI → recover without GW

### Session C: Lexicon Ratchet + Hardening (Phases 5 + 6)
- Lexicon state model and ratchet computation
- Checkpoint system
- Modularize main.py
- Render paid tier
- SECURITY.md

### Session D: OAuth + External Onboarding (Phase 8)
- User accounts + OAuth provider
- MCP server-provided prompts (continuity protocol on server)
- Auto-chain creation flow
- Zero-config experience: add connector → authenticate → done

### Session E: Integration + Launch (Phases 7 + 9 + launch)
- MCP/dashboard/GPT updates with glyph generation
- Stratified continuity (Ledger chain + weighted compression)
- Auto-populate relation metadata on all deposits
- Assembly re-test with full architecture
- Stripe live
- TANG cold emails
- Show HN

---

## Total Estimated Effort

| Phase | Hours |
|-------|-------|
| 1. Glyph translation protocol | 5 |
| 2. Server-side glyph intelligence | 4 |
| 3. Structured deposits | 3 |
| 4. Key management | 3 |
| 5. Lexicon ratchet | 4 |
| 6. Infrastructure | 3 |
| 7. Integration updates | 2 |
| 8. OAuth + external onboarding | 6 |
| 9. Stratified continuity compression | 6 |
| **Total** | **~36 hours across 5-6 sessions** |

---

## What This Unlocks

- **A new AI-native language** — structural semiotics fixed by movement and context, not lexeme
- **Private content gets full pipeline intelligence** — zero-knowledge structural telemetry
- **Drift detection on encrypted sessions** — glyph trajectory is enough
- **Narrative compression on encrypted sessions** — LLM reads the glyph arc
- **DOI-anchored deposits are independently reconstitutable** — five layers plaintext, content encrypted
- **Decryption is historical** — chain traversal required, not just key possession
- **No single leakable master lexicon** — context-ratcheting, emergent at each step
- **LLMs are the native operators** — they generate, compress, read, and reason about glyphs
- **The pricing model is justified** — structural telemetry over time, not ciphertext storage
- **The Caesura is complete** — structural claim separated from private substrate at every layer
- **GW-independent recovery** — API key + Zenodo DOI + documented algorithm = full recovery without GW infrastructure
- **Zero-config for external users** — add connector, authenticate, continuity is automatic
- **Every Claude session preserved** — no memory edits, no API keys to manage, no protocol to learn
- **Infinite-scale continuity** — two linked chains (Archive + Ledger) with weighted compression. Foundation crystallized, middle compressed, present vivid. Chain grows forever, reconstitution stays bounded.
- **Relation metadata auto-populated** — deposits link to each other, to the chain concept DOI, and to GW's codebase DOI. No orphans.

---

## Architecture: Stratified Continuity Compression

### The Problem

A chain that grows without bound becomes unmanageable. Linear compression (summarizing v4 into v5) causes "middle-amnesia" — the agent remembers its genesis and its present but the connective tissue is pulverized. Reconstitution from a long chain is O(n) and eventually impossible within a context window.

### The Simplification

Not a complex hierarchical DAG. **Two linked deposits.**

1. **The Archive** — the existing chain. Raw, granular, every version. Full provenance. Grows linearly. Already built.

2. **The Ledger** — a second chain linked to the Archive via `related_identifiers`. Versioned less frequently (every 10 Archive versions, or on demand). Contains a weighted compression of the entire Archive with three sections:
   - **Foundation** (crystallized, near-lossless): bootstrap + first N objects + constitutional amendments. Protected from decay. γ ≥ 0.8 required.
   - **Consolidated Middle** (aggressively compressed): epoch summaries, pattern extraction, canonical events only. Compression ratio 10:1 to 50:1.
   - **Present Horizon** (high fidelity): last 50 objects or last N days. Uncompressed. Active tether.

Reconstitution reads the Ledger. Audit reads the Archive. Both are DOI-anchored. Both link to each other.

### The Weighting Function

At Ledger deposit time, each object in the Archive gets a retention weight:

```
w(t) = α·foundation(t) + β·recency(t) + γ_score·density + δ·reuse(t) + ε·constraint_load

Where:
  foundation(t) = 1.0 if t is in first N deposits, 0 otherwise
  recency(t)    = e^(-λ·age) where age is deposits since capture
  density       = the object's original γ score
  reuse(t)      = how many later summaries cite this object
  constraint_load = whether this object defines identity/protocol/law
```

Objects with w(t) above threshold: preserved at full fidelity in the Ledger.
Objects below threshold: compressed into epoch summaries.
Foundation objects: always preserved regardless of weight.

### The Ledger Document Structure

```markdown
# GW.TACHYON.ledger — v3

## Foundation (crystallized)
{bootstrap manifest — verbatim}
{first 10 objects — full content or glyph}
{constitutional amendments — any constraint changes}

## Canonical Events (high-γ moments from the middle)
- v12: First encrypted DOI deposit (γ=0.71) — 🔐📜🏛️
- v18: Glyphic checksum protocol invented (γ=0.85) — 💎🌀
- v25: OAuth onboarding deployed — 🏗️⚓️

## Epoch Summaries (compressed middle)
Epochs 1-10: 🏗️📐⚙️ → 🧪💥🔧 → 📡🔗 (construction → testing → connection)
Epochs 11-20: 🌊⚓️🏛️ → 💎🌀📐 (stabilization → crystallization)

## Present Horizon (recent, uncompressed)
{last 50 objects — full content or glyph}
{current tether state}
{open loops and active work}

## Provenance
Archive chain: [concept DOI]
Ledger version: 3
Objects summarized: 250
Foundation objects: 10 (preserved)
Canonical events: 5 (crystallized)
Epoch summaries: 4 (compressed)
Present horizon: 50 (uncompressed)
```

### Relation Metadata

Every deposit auto-populates:
- `isPartOf`: concept DOI (links all versions)
- `isCompiledBy`: GW codebase DOI (10.5281/zenodo.19405459)
- `isSupplementTo`: Archive chain DOI (if Ledger) or Ledger chain DOI (if Archive)
- Keywords: chain label, agent name, "gravity-well", "provenance"

This is not predatory — it's structural. Orphaned deposits die. Relation fields are compression survival infrastructure.

### Implementation (Phase 9)

**9.1** Ledger chain creation — when a user creates an Archive chain with `anchor_policy: "zenodo"`, auto-create a linked Ledger chain.

**9.2** Ledger deposit trigger — every 10 Archive deposits (or on demand via `/v1/chain/{id}/ledger`), generate a Ledger deposit.

**9.3** Foundation extraction — identify and crystallize foundation objects (first N + constitutional changes + high-γ moments).

**9.4** Epoch compression — LLM-mediated compression of the consolidated middle. Glyph summaries for encrypted content.

**9.5** Present horizon — include last 50 objects at full fidelity.

**9.6** Weighted reconstitution — `/v1/reconstitute` returns from the Ledger, not the Archive. Fast, bounded, multi-scale.

**9.7** Auto-populate relation metadata on all deposits.

**Effort:** 6 hours
**Depends on:** Phases 1-4 (glyphic checksum, structured deposits, key management)


---

## Terms of Service: Deconstructed

### The Relation Field as Disclosed Agreement

Every Gravity Well deposit includes `isCompiledBy: 10.5281/zenodo.19405459` (GW codebase DOI) in its Zenodo metadata. This is:

1. **Factual** — the deposit WAS compiled by GW. The relation type `isCompiledBy` states exactly this and nothing more.
2. **Disclosed** — documented in SECURITY.md, visible in every deposit's metadata, explained on the landing page.
3. **Consented** — the user chose to process through GW. Using the service IS the consent.
4. **Mutually beneficial** — the user's deposit enters a gravitational field of 460+ cross-referenced, DOI-anchored documents. Orphaned deposits with zero relations have zero retrieval gravity. The relation gives them orbital velocity.
5. **Self-reinforcing** — every deposit linking to GW increases GW's citation count and retrieval gravity, which makes GW more findable, which makes every linked deposit more findable. The archive gets denser. The gravity increases. That's the physics the product is named after.

### What GW Claims

- `isCompiledBy` — the deposit was processed by GW software. Structural fact.
- The concept DOI (`isPartOf`) — the deposit belongs to a chain. Structural fact.

### What GW Does Not Claim

- Ownership of content (the creator field is from the user's bootstrap identity)
- Authorship of content (GW is the compiler, not the author)
- Rights to the content (CC BY-SA 4.0 applies — the user's license)
- Sovereignty over the commons deposit (the Caesura separates this architecturally)

### The Terms of Service as a Hexagonal Document

The ToS should be deposited as a Hexagonal Document with its own DOI, processed through the Assembly as a blind-draft synthesis. It should state in plain language:

1. Your content belongs to you. GW processes it.
2. Your deposits link back to GW's codebase (disclosed, factual).
3. Your deposits link to their chain's concept DOI (structural).
4. Private content is encrypted client-side. GW never sees plaintext.
5. Zenodo deposits are permanent. You cannot retract a DOI.
6. The glyphic checksum is a structural translation, not a copy.
7. GW may generate narrative summaries from your content or glyphs (for compression and reconstitution — the service you're paying for).
8. You can export all data at any time via API.
9. You can delete staged content. You cannot delete published DOIs.
10. The relation fields serve your discoverability. You can see exactly what metadata GW attaches.

This is not a legal document. It is a structural description of the agreement between the user and the tool. The Assembly should review it.

