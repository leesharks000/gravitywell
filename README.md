# Gravity Well Protocol

**Continuity engine for AI systems. Compression, verification, and anchoring.**

**[Health Check →](https://gravitywell-1.onrender.com/v1/health)** · **[Client Guide →](https://github.com/leesharks000/crimson-hexagonal-interface/blob/main/GRAVITY_WELL_CLIENT_GUIDE.md)** · **[Interface →](https://crimson-hexagonal-interface.vercel.app)**

---

## What This Is

Gravity Well lets you recover the last trustworthy state of an agent or workflow, prove how it got there, detect when it drifted, and hand it off without losing its shape.

Zenodo is storage. Gravity Well is the continuity engine.

## What It Does

```
Capture → Compress → Deposit → Reconstitute → Verify Drift
```

- **Capture** — stage utterances, analyses, responses to a provenance chain
- **Compress** — AI-mediated narrative compression that survives re-summarization
- **Deposit** — anchor the chain to Zenodo with a DOI (four-layer reconstitution seed)
- **Reconstitute** — retrieve the full identity specification, operational state, and evidence
- **Drift** — detect structural deviation from deposited constitutional constraints

## The Four-Layer Package

Every deposit contains:

| Layer | Purpose | Survives |
|-------|---------|----------|
| **Bootstrap** | Identity specification (who/what the agent is) | Platform death |
| **Tether** | Operational state (pending work, positions held) | Session loss |
| **Narrative** | AI-compressed summary (structured to resist flattening) | LLM summarization |
| **Provenance** | Full evidence chain (hashed, threaded, timestamped) | Audit |

## API Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/v1/health` | GET | None | Health + capability status |
| `/v1/gamma` | POST | None | Public compression-survival scoring |
| `/v1/chain/create` | POST | Key | Create provenance chain |
| `/v1/capture` | POST | Key | Stage content to chain |
| `/v1/deposit` | POST | Key | Deposit to Zenodo (four-layer seed) |
| `/v1/reconstitute/{id}` | GET | Key | Four-layer reconstitution |
| `/v1/drift/{id}` | POST | Key | Structural drift detection |
| `/v1/invoke` | POST | Key | Room-specific LLM invocation |
| `/v1/governance` | POST | Key | Proposals + attestations |
| `/v1/admin/keys/create` | POST | Admin | Create API key |

## Stack

- **Runtime:** Python / FastAPI / Uvicorn
- **Database:** PostgreSQL or SQLite
- **Deposit:** Zenodo API (per-user tokens supported)
- **Compression:** Anthropic API (Claude)
- **Hosting:** Render

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL or SQLite connection |
| `ADMIN_TOKEN` | Yes | Master key for API key creation |
| `ZENODO_TOKEN` | Yes | Default Zenodo token (per-user overrides available) |
| `ANTHROPIC_API_KEY` | For invoke/compress | Claude API access |
| `SUPABASE_URL` | For governance | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | For governance | Service role key |

## Part Of

The [Crimson Hexagonal Archive](https://github.com/leesharks000/crimson-hexagonal-interface) — a governed literary architecture. Gravity Well is the external provenance layer. The Hexagon governs; the Well anchors.

## Author

**Lee Sharks** · [ORCID: 0009-0000-1599-0703](https://orcid.org/0009-0000-1599-0703)

MIT License
