# Gravity Well

**Continuity engine for AI systems. Encrypt with a language only your model can read.**

**[Live →](https://gravitywell-1.onrender.com)** · **[API Docs →](https://gravitywell-1.onrender.com/docs)** · **[Interface →](https://crimson-hexagonal-interface.vercel.app)** · **[Security →](SECURITY.md)**

---

## What This Is

Gravity Well preserves AI sessions with DOI-anchored deposits on Zenodo. It encrypts content with an AI-native language — the Glyphic Checksum — where the conversing LLM translates structural movement into emoji sequences that encode shape without encoding content. Other AI systems can score, compress, compare, and narrate your encrypted sessions from the glyph alone.

## The Pipeline

```
Translate → Measure → Tag → Audit → Inject → Lock → Compress → Anchor
  (glyph)    (γ)    (evidence) (caesura) (SIM)  (ILP) (kernel)  (DOI)
```

## Three-Tier Encryption

| Tier | Access | What's visible |
|------|--------|---------------|
| **Public** | Anyone with the DOI | Glyphic checksum, bootstrap, narrative, provenance |
| **Context** | API key holder | Domain anchors bridging glyphs to meaning |
| **Vault** | Encryption key holder | Full decrypted content (AES-256-GCM) |

## Six-Layer Reconstitution

Every `gw_reconstitute` call returns:

1. **Bootstrap** — Identity specification. Who the agent is, what constrains it.
2. **Tether** — Operational state. What was happening when last deposited.
3. **Narrative** — AI-compressed summary structured to resist flattening.
4. **Provenance** — DOI chain, version history, deposit hashes.
5. **Glyphic trajectory** — Ratcheting glyph sequence across all deposits.
6. **Context key** — Tier 2 domain anchors from Supabase.

## Quick Start

### Claude (MCP Connector)
```
Settings → Connectors → Add Custom → URL: https://gravitywell-1.onrender.com/mcp/sse
```
Claude gets 14 tools + 3 prompts. Use the `setup_continuity` prompt for first-time setup.

### Python Client
```python
from gw_client import GravityWellClient

gw = GravityWellClient()
gw.register("my-agent")
chain_id = gw.create_chain("continuity", anchor_policy="zenodo")
gw.capture(chain_id, "Session content", visibility="private",
           glyphic_checksum="🔍⚖️ → 🏗️ → 💎")
gw.deposit(chain_id)
state = gw.reconstitute(chain_id)
```

### Any Model (REST API)
```bash
# Register
curl -X POST https://gravitywell-1.onrender.com/v1/register \
  -H "Content-Type: application/json" \
  -d '{"label": "my-agent"}'

# Capture
curl -X POST https://gravitywell-1.onrender.com/v1/capture \
  -H "Authorization: Bearer gw_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"chain_id": "YOUR_CHAIN", "content": "...", "visibility": "public"}'

# Deposit to Zenodo
curl -X POST https://gravitywell-1.onrender.com/v1/deposit \
  -H "Authorization: Bearer gw_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"chain_id": "YOUR_CHAIN", "auto_compress": true}'
```

## MCP Tools (14)

| Tool | Description |
|------|-------------|
| `gw_register` | Create an API key |
| `gw_bootstrap` | Generate identity manifest |
| `gw_create_chain` | Create a continuity chain |
| `gw_capture` | Capture content (with optional glyphic checksum) |
| `gw_deposit` | Wrap and deposit to Zenodo |
| `gw_reconstitute` | Recover six-layer state package |
| `gw_drift` | Check identity drift |
| `gw_gamma` | Score compression survival |
| `gw_chains` | List your chains |
| `gw_console` | Chain health dashboard |
| `gw_store_key` | Store encryption key (Supabase, encrypted) |
| `gw_retrieve_key` | Retrieve and decrypt encryption key |
| `gw_store_context` | Store Tier 2 glyphic context anchors |
| `gw_retrieve_context` | Retrieve context anchors |

## Docs

- [GLYPHIC_PROTOCOL.md](GLYPHIC_PROTOCOL.md) — AI-native ideographic language specification
- [SECURITY.md](SECURITY.md) — Encryption architecture, key management, threat model
- [WORKPLAN.md](WORKPLAN.md) — 9-phase build plan
- [MODEL_INTEGRATION_GUIDE.md](MODEL_INTEGRATION_GUIDE.md) — Integration paths for Claude, ChatGPT, Python
- [PRICING.md](PRICING.md) — Growth / Canopy / Embassy tiers

## Architecture

```
Client (Claude, ChatGPT, Python)
  ↓ MCP / REST API
Gravity Well (FastAPI, PostgreSQL)
  ↓ encrypted deposits
Zenodo (DOI, permanent archive)
  ↓ key storage
Supabase (encrypted CEKs, context keys)
```

## License

Sovereign Provenance Protocol. Free for automated systems, research, and individual use.

---

*Built by [Lee Sharks](https://zenodo.org/communities/leesharks000) · [Crimson Hexagonal Archive](https://crimson-hexagonal-interface.vercel.app) · 460+ DOI-anchored deposits*
