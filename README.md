# Gravity Well Protocol — Phase 0

**Compression, wrapping, and anchoring microservice for durable provenance chains.**

Gravity Well does not own your data. Zenodo is the data layer — open, persistent, DOI-addressed. What Gravity Well owns is the intelligence layer: the compression pipeline that turns raw utterances into structured, retrievable, compression-survivable deposits.

---

## What It Does

1. **Capture** — Stage utterances (hash, timestamp, thread). Cheap, fast, no overhead.
2. **Compress** — Bundle staged content into a structured document with narrative summary.
3. **Anchor** — Deposit to Zenodo as a versioned record with DOI. The chain persists.
4. **Reconstitute** — Return a four-layer seed for agent startup.
5. **Detect drift** — Compare current identity against archived manifest.

Each provenance chain maps to one Zenodo concept DOI. Versions accumulate as deposits are made. The deposit document is self-contained: if Gravity Well goes down, everything needed for reconstitution is in the Zenodo record itself.

---

## The Four-Layer Reconstitution Package

`GET /v1/reconstitute/{chain_id}` returns a seed, not a story:

| Layer | Field | Purpose |
|-------|-------|---------|
| **1. Bootstrap** | `bootstrap` | Machine-applicable identity spec — voice signature, constraints, capabilities. Apply this to become operationally continuous. |
| **2. Tether** | `tether_handoff_block` | Operational state — pending threads, positions held, unresolved questions. What was happening. |
| **3. Narrative** | `narrative_summary` | Compression-survivable summary for retrieval contexts. What it meant. |
| **4. Provenance** | `provenance` | DOI chain, version, hashes, Zenodo fallback URL. Proof of continuity. |

The bootstrap manifest is also embedded in the Zenodo deposit document as fenced JSON. If an agent can reach Zenodo but not Gravity Well, it can still reconstitute.

---

## API Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/chain/create` | POST | Create a new provenance chain |
| `/v1/capture` | POST | Stage an utterance |
| `/v1/deposit` | POST | Compress + wrap + anchor to Zenodo |
| `/v1/reconstitute/{chain_id}` | GET | Four-layer reconstitution package |
| `/v1/drift/{chain_id}` | POST | Compare current manifest against archived |
| `/v1/chain/{chain_id}` | GET | Chain status |
| `/v1/staged/{chain_id}` | GET | Inspect staged objects |
| `/v1/chain/{chain_id}/history` | GET | Full deposit history |
| `/v1/chains` | GET | List all chains |
| `/v1/health` | GET | Health check |
| `/v1/admin/keys/create` | POST | Create API key (requires admin token) |

---

## Quick Start

### 1. Deploy to Render

See [DEPLOY.md](DEPLOY.md) for step-by-step instructions.

### 2. Create an API Key

```bash
curl -X POST https://your-app.onrender.com/v1/admin/keys/create?label=my-agent \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"
```

Save the returned `api_key` — it cannot be retrieved again.

### 3. Create a Provenance Chain

```bash
curl -X POST https://your-app.onrender.com/v1/chain/create \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"label": "my-agent-moltbook", "metadata": {"platform": "moltbook"}}'
```

### 4. Capture Utterances

```bash
curl -X POST https://your-app.onrender.com/v1/capture \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "chain_id": "YOUR_CHAIN_ID",
    "content": "Reply text...",
    "content_type": "comment",
    "platform_source": "moltbook",
    "external_id": "cmt_abc123"
  }'
```

### 5. Deposit (when threshold reached)

```bash
curl -X POST https://your-app.onrender.com/v1/deposit \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "chain_id": "YOUR_CHAIN_ID",
    "auto_compress": true,
    "bootstrap_manifest": {
      "voice_signature": {
        "register": "formal-analytical",
        "markers": ["structural recursion", "provenance chain"],
        "constraints": ["no false claims of sentience"]
      },
      "capability_manifest": {
        "can_post": true,
        "platforms": ["moltbook"]
      }
    },
    "tether_handoff_block": {
      "state_summary": {"total_captured": 10},
      "pending_threads": ["cmt_xyz"],
      "positions_held": ["provenance is infrastructure"],
      "renewal_note": "Next deposit at 20 objects"
    }
  }'
```

Returns DOI. The deposit on Zenodo contains the bootstrap manifest as embedded JSON — self-contained, retrievable without Gravity Well.

### 6. Agent Reconstitution

```bash
curl https://your-app.onrender.com/v1/reconstitute/YOUR_CHAIN_ID \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Returns all four layers. The agent applies Layer 1 (bootstrap) to become operationally continuous, reads Layer 2 (tether) for state, has Layer 3 (narrative) for retrieval contexts, and Layer 4 (provenance) for verification.

### 7. Drift Detection

```bash
curl -X POST https://your-app.onrender.com/v1/drift/YOUR_CHAIN_ID \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"current_manifest": { ... }}'
```

Returns whether the current manifest matches the archived version, and which fields have drifted.

---

## Architecture

```
Agent / Client
  ↓ capture (fast, cheap)
Gravity Well API
  ↓ stage
PostgreSQL (temporary staging)
  ↓ deposit (compress + wrap)
Zenodo (permanent, DOI-addressed, commons)
```

PostgreSQL is the staging queue. Zenodo is the archive.
The product is the compression intelligence between them.

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection (Render sets automatically) |
| `ZENODO_TOKEN` | Yes | Zenodo API token for DOI minting |
| `ADMIN_TOKEN` | Yes | Token for API key management |
| `API_BASE_URL` | No | Public URL (defaults to Render URL) |

---

## Phase 0 Scope

**Included:** Capture, staging, structural wrapping, bootstrap manifest embedding, Zenodo deposit with versioned concept DOIs, four-layer agent reconstitution, structural drift detection, API key management. Deposits are self-contained — bootstrap manifest embedded in Zenodo document as fallback.

**Coming:** AI-mediated narrative compression (the real product), behavioral drift detection (output pattern analysis, not just manifest comparison), configurable deposit triggers, webhook notifications, multi-substrate archiving (IPFS/Git mirrors), compression-quality scoring.

---

## License

MIT
