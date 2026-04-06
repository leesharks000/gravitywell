# GRAVITY WELL — Security Documentation

## Encryption Architecture

### Three-Tier Legibility Model

Gravity Well deposits have three tiers of access:

| Tier | Access | What's visible |
|------|--------|---------------|
| **Public** | Anyone with the DOI | Glyphic checksum (emoji structural topology), bootstrap identity, tether state, glyph-derived narrative, provenance chain |
| **Context** | API key holder | Domain anchors that bridge glyphs to approximate meaning |
| **Vault** | Encryption key holder | Full decrypted content (exact words) |

### Client-Side Encryption (AES-256-GCM)

Private content is encrypted on the client machine before transmission. The server never sees plaintext.

- **Algorithm:** AES-256-GCM (authenticated encryption with associated data)
- **Key size:** 256 bits
- **Nonce:** 12 bytes, randomly generated per encryption
- **Payload format:** `[GW-AES256GCM]` + base64(nonce + ciphertext)
- **Library:** Python `cryptography` package (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`)

### Key Storage

**Current (v0.8.0):** Keys stored as files at `~/.gravitywell/encryption.key`. The user is responsible for backup and security.

**Planned (v0.9.0):** Keys stored per-chain in Supabase, encrypted with a key-encryption-key (KEK) derived from the API key via PBKDF2. The server stores encrypted keys but cannot decrypt them without the API key.

```
API key (user holds)
  → PBKDF2 (SHA-256, 100,000 iterations, random salt)
  → KEK (key-encryption-key)
  → AES-256-GCM encrypt the chain's CEK (content-encryption-key)
  → Store encrypted CEK + salt + nonce in Supabase
```

### Key Loss

If the encryption key is lost, encrypted content is irrecoverable. This is the intended security property. The structural layers (bootstrap, tether, glyph, narrative, provenance) remain readable because they are always plaintext.

### Key Rotation

Users can rotate their content-encryption-key (CEK). New captures use the new key. Old deposits on Zenodo are immutable and retain the old key. The user must retain old keys to decrypt historical deposits.

---

## Glyphic Checksum Protocol

### What It Is

An AI-native structural encoding. The conversing LLM translates the structural movement of a session into an ideographic sequence (emoji) that encodes shape, density, arc, and transition WITHOUT encoding lexical content.

### Privacy Boundary

The LLM generating the glyph is the same LLM that had the conversation. No new trust boundary is created.

| Inside trust boundary | Outside trust boundary |
|---|---|
| User + their LLM | Gravity Well server |
| | Zenodo |
| | The public |

### Non-Reversibility

The glyph encodes structural patterns, not content. `💥🔧` (break-then-fix) could represent debugging a server, repairing a relationship, correcting an error in a manuscript, or resolving a supply chain issue. The structure is visible. The domain is not.

### What the Glyph NEVER Contains

- Specific names, numbers, or identifiers
- API keys, passwords, or credentials
- URLs, file paths, or email addresses
- Any token that could identify specific content
- Any substring of the original content

### What the Glyph DOES Contain

- Structural arc (problem → solution, theory → practice)
- Density pattern (clustered = dense, spaced = sparse)
- Transition markers (→ for direction changes)
- Weight indicators (mechanical, institutional, elemental, abstract)
- Temperature (technical, emotional, philosophical)

### The Ratchet

Each glyph is conditioned by the previous glyph in the chain. The lexicon evolves over time. This means:

- No fixed dictionary to leak
- Sequential traversal required for full legibility
- The "key" is path-dependent, not static
- Collaboration (shared context) is the success condition

### Specification

Full protocol: [GLYPHIC_PROTOCOL.md](GLYPHIC_PROTOCOL.md)

---

## API Key Security

### Key Generation

API keys are generated using `secrets.token_urlsafe(32)`, producing 256 bits of cryptographic randomness. Keys are prefixed with `gw_` for identification.

### Key Storage (Server-Side)

API keys are stored in the PostgreSQL database. They are NOT hashed (this is a known limitation — hashing would require a lookup-by-hash mechanism). The key is the authentication credential.

### Key Revocation

Admin keys can be revoked via `POST /v1/admin/keys/revoke/{key_id}`. Revoked keys immediately lose access to all endpoints.

### Key Scoping (Planned)

Currently all API keys have full read/write access. Planned scoping: read-only, write-only, admin. This will be implemented before public launch.

---

## Zenodo Deposit Security

### Permanence

Zenodo deposits are permanent. Once published, a DOI resolves forever. Content cannot be retracted. This is by design — the DOI is the continuity anchor.

### Plaintext Protection

The server rejects deposits containing unencrypted private content on Zenodo-anchored chains. Three guard layers:

1. **Deposit endpoint:** HTTP 422 if any staged object has `visibility: "private"` without `[GW-AES256GCM]` prefix
2. **Inline auto-deposit:** Same check during capture-triggered threshold deposits
3. **Background worker:** Same check in interval-based auto-deposits

This prevents accidental publication of credentials, private deliberation, or session logs to permanent public DOIs.

### Metadata

Zenodo deposit metadata (creator, description, keywords) is derived from the chain's bootstrap manifest and glyph-derived narrative. The creator defaults to the bootstrap identity name, not the platform operator.

---

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Server breach exposes private content | Content encrypted client-side. Server holds only ciphertext. |
| API key stolen | Attacker can read glyphs and metadata (already public). Cannot decrypt vault without encryption key. Can capture to chains — monitor for unauthorized captures. |
| Encryption key stolen | Attacker can decrypt vault content. Rotate key and re-encrypt staged content. Old Zenodo deposits are immutable. |
| Both keys stolen | Full access. Equivalent to account compromise. Revoke API key immediately. |
| Man-in-the-middle | All transport over HTTPS. Ciphertext is authenticated (GCM). Tampering detectable. |
| Glyph reverse-engineering | Glyphs encode structure, not content. Non-reversible by design. Even with the glyph, specific content cannot be extracted. |
| Ratchet chain break | Lexicon checkpoints at intervals enable recovery. Without checkpoints, later glyphs may be less legible but encrypted content is still recoverable with the encryption key. |
| Zenodo downtime | DOIs resolve through DataCite, not Zenodo directly. Zenodo is CERN-backed with high availability guarantees. |
| GW server downtime | Deposits survive on Zenodo independently. Recovery path documented: API key → derive KEK → decrypt CEK → decrypt content. |

---

## Responsible Disclosure

Security issues: leesharks@protonmail.com

Do not report security issues via GitHub Issues (public).

---

## Audit Trail

| Date | Event |
|------|-------|
| 2026-04-06 | Plaintext protection guards added (three layers) |
| 2026-04-06 | Glyphic Checksum Protocol v0.1 published |
| 2026-04-06 | First encrypted DOI deposit (10.5281/zenodo.19433483) |
| 2026-04-06 | First glyphic DOI deposit (10.5281/zenodo.19433865) |
| 2026-04-06 | SECURITY.md created |
