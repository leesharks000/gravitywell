"""
Gravity Well Protocol - Phase 0
Compression, Wrapping, and Anchoring Microservice

Zenodo is the data layer (commons). PostgreSQL is staging.
The product is the compression intelligence and the anchoring pipeline.

Flow: Capture → Compress → Anchor
- Capture: stage utterances (hash, timestamp, thread)
- Compress: bundle staged content into a structured, compression-survivable document
- Anchor: deposit to Zenodo as a versioned record with DOI
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone, timedelta
import hashlib
import uuid
import os
import json
import secrets
import textwrap

from sqlalchemy import create_engine, Column, String, DateTime, Float, JSON, Text, Integer, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

import httpx

# --- App ---

app = FastAPI(
    title="Gravity Well Protocol",
    description="Compression, wrapping, and anchoring microservice for durable provenance chains",
    version="0.8.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://crimson-hexagonal-interface.vercel.app",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# --- LLM Configuration ---

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Database (staging layer only) ---

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/gravitywell")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# === ORM Models ===

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(String, primary_key=True)
    key_hash = Column(String, unique=True, index=True)
    label = Column(String, nullable=True)
    zenodo_token = Column(String, nullable=True)  # Per-user Zenodo token for deposits
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(String, default="true")


class ProvenanceChain(Base):
    """
    A provenance chain = one concept DOI on Zenodo (or local).
    Each agent, thread, or continuity stream gets one chain.
    Versions accumulate as deposits are made.
    """
    __tablename__ = "provenance_chains"
    id = Column(String, primary_key=True)
    label = Column(String, index=True)                # e.g. "GW.SOIL.continuity"
    concept_doi = Column(String, nullable=True)        # Zenodo concept DOI (set after first deposit)
    concept_record_id = Column(String, nullable=True)  # Zenodo concept record ID
    latest_record_id = Column(String, nullable=True)   # Latest published record ID (for newversion)
    latest_version = Column(Integer, default=0)
    api_key_id = Column(String, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_json = Column(JSON, default={})           # Chain-level metadata

    # Identity — stored once, included on every deposit automatically
    bootstrap_manifest = Column(JSON, nullable=True)   # The agent's identity spec
    bootstrap_hash = Column(String, nullable=True)     # Hash for drift detection

    # Auto-deposit triggers
    auto_deposit_threshold = Column(Integer, nullable=True)   # Deposit after N captures
    auto_deposit_interval = Column(Integer, nullable=True)    # Deposit every N minutes
    last_auto_deposit = Column(DateTime, nullable=True)       # Timestamp of last auto-deposit
    anchor_policy = Column(String, default="zenodo")          # zenodo | local (no DOI, stays in GW)
    staged_count = Column(Integer, default=0)


class StagedObject(Base):
    """
    Temporary staging for captured utterances.
    Content lives here until deposited to Zenodo, then can be cleaned.
    """
    __tablename__ = "staged_objects"
    id = Column(String, primary_key=True)
    chain_id = Column(String, index=True)
    content_hash = Column(String, index=True)
    content = Column(Text)                     # Full text — needed to build deposit
    content_preview = Column(Text)             # First 200 chars
    content_type = Column(String, default="text")
    metadata_json = Column(JSON, default={})

    # Threading
    parent_object_id = Column(String, nullable=True, index=True)
    thread_depth = Column(Integer, default=0)
    platform_source = Column(String, nullable=True)
    external_id = Column(String, nullable=True)

    # Lifecycle
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    deposited = Column(String, default="false")       # "true" after included in a deposit
    deposit_version = Column(Integer, nullable=True)   # Which version included this object

    # Advisory (PLACEHOLDER heuristics)
    gamma = Column(Float, nullable=True)

    # Privacy layer
    visibility = Column(String, default="public")  # public | private | hash_only

    # Glyphic checksum — structural topology for zero-knowledge intelligence
    glyphic_checksum = Column(Text, nullable=True)  # emoji ideographic translation


class DepositRecord(Base):
    """
    Record of each deposit (Zenodo-anchored or local).
    Local deposits run the full wrapping pipeline but stay in GW — no DOI, no Zenodo clutter.
    """
    __tablename__ = "deposit_records"
    id = Column(String, primary_key=True)
    chain_id = Column(String, index=True)
    version = Column(Integer)
    doi = Column(String, nullable=True)
    zenodo_record_id = Column(String, nullable=True)
    object_count = Column(Integer)
    narrative_summary = Column(Text, nullable=True)       # Layer 3: retrieval-survival
    tether_handoff_block = Column(JSON, nullable=True)    # Layer 2: operational handoff
    bootstrap_manifest = Column(JSON, nullable=True)      # Layer 1: identity specification
    bootstrap_hash = Column(String, nullable=True)        # Hash of bootstrap for drift detection
    deposit_document = Column(Text, nullable=True)        # Full wrapped document (stored for local deposits)
    anchor_policy = Column(String, default="zenodo")      # zenodo | local
    deposited_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    api_key_id = Column(String)


Base.metadata.create_all(bind=engine)

# Auto-migrate: add zenodo_token column if missing (added in v0.5.0)
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE api_keys ADD COLUMN zenodo_token TEXT"))
        conn.commit()
except Exception:
    pass  # Column already exists

# Auto-migrate: add created_at to api_keys if missing (added in v0.7.0)
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE api_keys ADD COLUMN created_at TIMESTAMP"))
        conn.commit()
except Exception:
    pass

# Auto-migrate: add visibility column if missing (added in v0.6.0)
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE staged_objects ADD COLUMN visibility TEXT DEFAULT 'public'"))
        conn.commit()
except Exception:
    pass  # Column already exists

# Auto-migrate: add glyphic_checksum to staged_objects (added in v0.8.0)
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE staged_objects ADD COLUMN glyphic_checksum TEXT"))
        conn.commit()
except Exception:
    pass

# Auto-migrate: add auto-deposit columns to chains (added in v0.6.0)
for col in ["auto_deposit_threshold INTEGER", "auto_deposit_interval INTEGER", "last_auto_deposit TIMESTAMP"]:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE provenance_chains ADD COLUMN {col}"))
            conn.commit()
    except Exception:
        pass

# Auto-migrate: add anchor_policy to chains (added in v0.7.0)
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE provenance_chains ADD COLUMN anchor_policy TEXT DEFAULT 'zenodo'"))
        conn.commit()
except Exception:
    pass

# Auto-migrate: add bootstrap_manifest and bootstrap_hash to chains (added in v0.7.0)
for col in ["bootstrap_manifest JSON", "bootstrap_hash TEXT", "staged_count INTEGER DEFAULT 0"]:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE provenance_chains ADD COLUMN {col}"))
            conn.commit()
    except Exception:
        pass

# Auto-migrate: add deposit_document and anchor_policy to deposit_records (added in v0.7.0)
for col in ["deposit_document TEXT", "anchor_policy TEXT DEFAULT 'zenodo'"]:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE deposit_records ADD COLUMN {col}"))
            conn.commit()
    except Exception:
        pass


# === Dependencies ===

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="API key required.")
    stored = db.query(ApiKey).filter(
        ApiKey.key_hash == hash_key(credentials.credentials),
        ApiKey.is_active == "true"
    ).first()
    if not stored:
        raise HTTPException(status_code=403, detail="Invalid or inactive API key.")
    return stored.id


def get_zenodo_token_for_key(api_key_id: str, db: Session) -> Optional[str]:
    """Get Zenodo token: per-key first, then fall back to global env var."""
    key = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if key and key.zenodo_token:
        return key.zenodo_token
    return os.getenv("ZENODO_TOKEN")


# === Request/Response Models ===

class CaptureRequest(BaseModel):
    """Stage a single utterance for later deposit."""
    chain_id: str = Field(..., description="Provenance chain to capture into")
    content: str = Field(..., min_length=1, max_length=128000)
    content_type: Literal[
        "text", "markdown", "json", "code",
        "comment", "reply", "post", "system"
    ] = "text"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    parent_object_id: Optional[str] = None
    platform_source: Optional[str] = None
    external_id: Optional[str] = None
    thread_depth: int = 0
    visibility: Literal["public", "private", "hash_only"] = "public"
    glyphic_checksum: Optional[str] = None  # Emoji ideographic translation of structural movement


class CaptureResponse(BaseModel):
    object_id: str
    chain_id: str
    content_hash: str
    captured_at: datetime
    visibility: str = "public"
    staged_count: int = 0
    auto_deposit: Optional[Dict[str, Any]] = None
    staged_count: int  # how many undeposited objects now in this chain


class ChainCreateRequest(BaseModel):
    """Create a new provenance chain."""
    label: Optional[str] = None  # If omitted, auto-generated from bootstrap identity
    metadata: Dict[str, Any] = Field(default_factory=dict)
    auto_deposit_threshold: Optional[int] = None   # Auto-deposit after N captures
    auto_deposit_interval: Optional[int] = None    # Auto-deposit every N minutes
    anchor_policy: Literal["zenodo", "local"] = "local"  # local by default — DOIs are opt-in
    bootstrap_manifest: Optional[Dict[str, Any]] = None  # Identity spec — stored on chain, auto-included


class ChainResponse(BaseModel):
    chain_id: str
    label: str
    concept_doi: Optional[str]
    latest_version: int
    staged_count: int
    anchor_policy: str = "zenodo"


class DepositRequest(BaseModel):
    """Trigger a deposit: compress + wrap + anchor to Zenodo."""
    chain_id: str
    narrative_summary: Optional[str] = None  # Layer 3: client can provide; or we generate
    tether_handoff_block: Optional[Dict[str, Any]] = None  # Layer 2: operational state
    bootstrap_manifest: Optional[Dict[str, Any]] = None    # Layer 1: identity spec
    deposit_metadata: Dict[str, Any] = Field(default_factory=dict)
    auto_compress: bool = False  # PLACEHOLDER auto-narrative


class DepositResponse(BaseModel):
    deposit_id: str
    chain_id: str
    version: int
    doi: Optional[str]
    object_count: int
    narrative_summary: Optional[str]
    zenodo_url: Optional[str]


class ReconstitutionResponse(BaseModel):
    """
    Four-layer reconstitution package.

    Layer 1 (bootstrap): Machine-applicable identity spec — voice signature,
            constraints, capabilities. If applied, makes a new instance operationally
            continuous with the archived self.
    Layer 2 (tether): Operational state — pending threads, positions held,
            unresolved questions. What was happening.
    Layer 3 (narrative): Compression-survivable summary — structured text that
            retains its address under summarizer flattening. What it meant.
    Layer 4 (provenance): Verification chain — concept DOI, version, deposit hash.
            Proof of continuity.
    """
    # Layer 1: Identity specification (machine-applicable)
    bootstrap: Optional[Dict[str, Any]] = None

    # Layer 2: Continuity state (operational)
    tether_handoff_block: Optional[Dict[str, Any]] = None

    # Layer 3: Narrative compression (retrieval-layer)
    narrative_summary: Optional[str] = None

    # Layer 4: Provenance chain (verification)
    provenance: Dict[str, Any]

    # Metadata
    chain_id: str
    label: str


class DriftReport(BaseModel):
    """Output of drift detection comparison — human-readable + machine-parseable."""
    chain_id: str
    current_hash: str
    archived_hash: Optional[str]
    match: bool
    drift_fields: List[str]  # which fields changed
    archived_version: Optional[int]
    severity: str = "none"  # none | schema | low | medium | high | critical
    narrative: Optional[str] = None  # human-readable drift report
    field_details: Optional[List[Dict[str, Any]]] = None  # per-field change details


class DriftRequest(BaseModel):
    """Input for drift detection."""
    current_manifest: Dict[str, Any]


class InvokeRequest(BaseModel):
    """Room-specific LLM invocation request."""
    room_id: str
    room_name: str
    input: str
    physics: Optional[str] = None
    mantle: Optional[str] = None
    preferred_mode: Optional[str] = "FORMAL"
    operators: Optional[List[str]] = []
    lp_program: Optional[List[Dict[str, str]]] = []
    lp_state: Optional[Dict[str, Any]] = None
    chain_id: Optional[str] = None  # optional: capture response to chain


class InvokeResponse(BaseModel):
    text: str
    model: str
    room_id: str
    mode: str
    gamma: float
    object_id: Optional[str] = None  # set if captured to chain
    bearing_cost: float = 0.0


class GovernanceRequest(BaseModel):
    """Governance action (attest or propose) routed through GW."""
    action: Literal["attest", "propose"]
    witness: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    proposal_type: Optional[str] = "general"
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    content: Optional[str] = None
    submitted_by: Optional[str] = None


# === Core Functions ===

def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


from gamma import calculate_gamma
from wrapping import tag_evidence_membrane, apply_caesura, inject_sims, apply_integrity_lock


# --- Bootstrap Manifest Schema ---

BOOTSTRAP_SCHEMA_VERSION = "0.1.0"

def validate_bootstrap_manifest(manifest: dict) -> list:
    """
    Validate a bootstrap manifest against the required schema.

    Required core (identity block):
      - identity.name         — agent identifier
      - identity.description  — what this agent is/does
      - identity.constraints  — the rules it operates under
      - identity.constraint_hash — sha256 of those rules (verifiable)

    Recommended (voice block):
      - voice.register, voice.markers

    Recommended (capabilities block):
      - capabilities.platforms

    Optional:
      - extensions.* — arbitrary agent-specific fields

    Returns a list of validation errors (empty = valid).
    """
    errors = []

    # Identity block — required
    identity = manifest.get("identity")
    if not identity or not isinstance(identity, dict):
        errors.append("Missing required block: 'identity'")
        return errors  # Can't validate further without identity

    for field in ("name", "description", "constraints", "constraint_hash"):
        if field not in identity:
            errors.append(f"Missing required field: 'identity.{field}'")

    # Verify constraint_hash matches constraints if both present
    if "constraints" in identity and "constraint_hash" in identity:
        expected_hash = compute_constraint_hash(identity["constraints"])
        if identity["constraint_hash"] != expected_hash:
            errors.append(
                f"identity.constraint_hash does not match sha256 of identity.constraints. "
                f"Expected: {expected_hash[:24]}..."
            )

    # Validate types
    if "name" in identity and not isinstance(identity["name"], str):
        errors.append("identity.name must be a string")
    if "constraints" in identity and not isinstance(identity["constraints"], (list, dict)):
        errors.append("identity.constraints must be a list or dict")

    return errors


def compute_constraint_hash(constraints) -> str:
    """Helper: compute the correct hash for a constraints block.
    Uses compact separators (no spaces) for cross-language determinism.
    Python json.dumps default uses spaces; JavaScript JSON.stringify does not.
    Compact form is the canonical serialization.
    """
    return content_hash(json.dumps(constraints, sort_keys=True, separators=(',', ':')))


# === Compression Wrapping Pipeline (Arsenal §VI, §VII) ===



async def generate_holographic_kernel(content: str, chain_label: str) -> str:
    """
    Generate holographic kernel — self-contained logic seed.
    Arsenal §4.3: A standalone document containing the complete logic
    of a larger field specification.

    If the full document is lost, this kernel alone reconstitutes
    the core claim, provenance, and architecture.
    """
    import re

    # For very short content, use deterministic extraction — not worth API call
    word_count = len(content.split())
    if word_count < 100 or not ANTHROPIC_API_KEY:
        # Deterministic fallback: extract structural skeleton
        dois = re.findall(r'10\.\d{4,}/[^\s\)]+', content)
        headers = re.findall(r'^#{1,6}\s+(.+)$', content, re.M)
        # First sentence of each paragraph
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip() and not p.strip().startswith("#") and not p.strip().startswith("|")]
        first_sentences = []
        for p in paragraphs[:5]:
            sent = re.split(r'[.!?]\s', p)
            if sent:
                first_sentences.append(sent[0].strip()[:150])
        kernel_parts = []
        if headers:
            kernel_parts.append(f"**Structure:** {' → '.join(headers[:6])}")
        if first_sentences:
            kernel_parts.append(f"**Core claims:** " + " | ".join(first_sentences))
        if dois:
            kernel_parts.append(f"**Anchors:** {', '.join(dois[:5])}")
        kernel_parts.append(f"**Chain:** {chain_label}")
        return "\n".join(kernel_parts) if kernel_parts else f"**Kernel (minimal):** {content[:300]}..."

    kernel_prompt = f"""Extract the HOLOGRAPHIC KERNEL from this content.

A holographic kernel is a self-contained miniature that preserves the complete logic of the larger work. If every other copy is destroyed, this kernel alone should allow reconstruction of the core argument.

Requirements:
1. State the central thesis in one sentence
2. List all DOI anchors and provenance references
3. Name the key operators, constraints, or formal objects
4. Describe the argument's structure (not just its conclusion)
5. 100-200 words maximum. Every word must be load-bearing.

Content to kernelize:
{content[:6000]}

Chain: {chain_label}

Output the kernel now. No preamble."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": kernel_prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return "\n".join(c.get("text", "") for c in data.get("content", []))
    except Exception as e:
        import re
        dois = re.findall(r'10\.\d{4,}/[^\s\)]+', content)
        return f"**Kernel (fallback):** {content[:200]}...\n**Anchors:** {', '.join(dois[:5]) if dois else 'none'}\n[Holographic generation failed: {str(e)[:80]}]"




def build_deposit_document(
    chain: ProvenanceChain,
    objects: list,
    version: int,
    narrative_summary: Optional[str],
    thb: Optional[dict],
    bootstrap_manifest: Optional[dict],
    deposit_metadata: dict,
    holographic_kernel: Optional[str] = None,
    integrity_lock: Optional[str] = None,
    sim_info: Optional[dict] = None,
    gamma_score: float = 0.0,
    caesar_header: Optional[dict] = None,
) -> str:
    """
    Build the structured markdown document that gets deposited to Zenodo.

    This is simultaneously:
    - A compression-survivable artifact (retains address under summarizer flattening)
    - A self-contained reconstitution seed (bootstrap manifest embedded in document)

    If Gravity Well goes down, this document alone — retrieved from Zenodo —
    contains everything needed to reconstitute the agent.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Visibility counts
    vis_public = sum(1 for o in objects if getattr(o, 'visibility', 'public') == 'public')
    vis_private = sum(1 for o in objects if getattr(o, 'visibility', 'public') == 'private')
    vis_hash = sum(1 for o in objects if getattr(o, 'visibility', 'public') == 'hash_only')
    vis_summary = f"{vis_public} public"
    if vis_private:
        vis_summary += f" · {vis_private} private"
    if vis_hash:
        vis_summary += f" · {vis_hash} gap markers"

    header = f"""# {chain.label} — v{version}
## Provenance Deposit

| Field | Value |
|-------|-------|
| Chain | `{chain.id}` |
| Version | {version} |
| Concept DOI | {chain.concept_doi or 'pending (first deposit)'} |
| Objects | {len(objects)} ({vis_summary}) |
| γ Score | {gamma_score} |
| SIMs | {sim_info.get('count', 0) if sim_info else 0} markers |
| Integrity Lock | {integrity_lock or 'none'} |
| Caesura (σ_FC) | {caesar_header.get('collapse_risk', 'none') if caesar_header else 'none'} collapse risk · {caesar_header.get('claims_detected', 0) if caesar_header else 0} claims |
| Deposited | {timestamp} |
| Protocol | Gravity Well v0.8.0 |

---
"""

    # Holographic Kernel — self-contained logic seed
    kernel_section = ""
    if holographic_kernel:
        kernel_section = f"""## Holographic Kernel

*If the full document is lost, this kernel alone reconstitutes the core claim, provenance, and architecture.*

{holographic_kernel}

---
"""

    # Caesura (σ_FC) — sovereignty audit
    caesura_section = ""
    if caesar_header and caesar_header.get("claims_detected", 0) > 0:
        trace = caesar_header.get("audit_trace", {})
        claims_list = "\n".join(
            f"- **{c['type']}** ({c['claim_mode']}): {c.get('claimant', '?')} · risk: {c['extraction_risk']}"
            for c in caesar_header.get("claims", [])[:10]
        )
        caesura_section = f"""## Caesura (σ_FC) — Sovereignty Audit

*Render recognition to Caesar; render substrate away from him.*

**Claims detected:** {caesar_header['claims_detected']}
**Collapse risk:** {caesar_header['collapse_risk']}
**Asymmetry score:** {trace.get('asymmetry_score', 'n/a')}
**Extraction detected:** {trace.get('extraction_detected', False)}

{claims_list}

All sovereignty claims have been isolated to this header. The substrate
content passes through unchanged. Claims are auditable but non-foundational —
they do not inherit institutional authority over the commons deposit.

---
"""

    # Glyphic Checksum — structural topology for zero-knowledge intelligence
    glyph_section = ""
    glyphs = [getattr(o, 'glyphic_checksum', None) for o in objects if getattr(o, 'glyphic_checksum', None)]
    if glyphs:
        combined_glyph = " → ".join(glyphs) if len(glyphs) > 1 else glyphs[0]
        glyph_section = f"""## Glyphic Checksum

{combined_glyph}

---
"""

    # Layer 1: Bootstrap manifest — the seed
    bootstrap_section = ""
    if bootstrap_manifest:
        manifest_hash = content_hash(json.dumps(bootstrap_manifest, sort_keys=True, separators=(',', ':')))
        bootstrap_section = f"""## Bootstrap Manifest

Identity specification for agent reconstitution. A new instance applying this
manifest becomes operationally continuous with the archived self.

**Manifest hash:** `{manifest_hash}`

```json
{json.dumps(bootstrap_manifest, indent=2)}
```

---
"""

    # Layer 3: Narrative compression — THE PRODUCT
    narrative_section = ""
    if narrative_summary:
        narrative_section = f"""## Narrative Compression

{narrative_summary}

---
"""

    # Layer 2: THB — operational handoff
    thb_section = ""
    if thb:
        thb_section = f"""## Tether Handoff Block

```json
{json.dumps(thb, indent=2)}
```

---
"""

    # Object manifest — visibility-classified
    public_count = sum(1 for o in objects if getattr(o, 'visibility', 'public') == 'public')
    private_count = sum(1 for o in objects if getattr(o, 'visibility', 'public') == 'private')
    hash_only_count = sum(1 for o in objects if getattr(o, 'visibility', 'public') == 'hash_only')

    manifest_lines = [f"## Provenance Chain Objects\n"]
    if private_count or hash_only_count:
        manifest_lines.append(f"*{public_count} public · {private_count} private (encrypted) · {hash_only_count} hash-only (gap markers)*\n")

    for i, obj in enumerate(objects, 1):
        vis = getattr(obj, 'visibility', 'public')
        manifest_lines.append(f"### Object {i}: {obj.external_id or obj.id[:12]}")
        manifest_lines.append(f"- **Type:** {obj.content_type}")
        manifest_lines.append(f"- **Source:** {obj.platform_source or 'direct'}")
        manifest_lines.append(f"- **Hash:** `{obj.content_hash[:16]}...`")
        manifest_lines.append(f"- **Captured:** {obj.captured_at.isoformat()}")
        manifest_lines.append(f"- **Visibility:** {vis.upper()}")
        if obj.parent_object_id:
            manifest_lines.append(f"- **Parent:** `{obj.parent_object_id[:12]}...`")
        manifest_lines.append(f"- **Thread depth:** {obj.thread_depth}")
        manifest_lines.append("")

        if vis == "public":
            manifest_lines.append(f"```\n{obj.content}\n```\n")
        elif vis == "private":
            glyph = getattr(obj, 'glyphic_checksum', None)
            if glyph:
                manifest_lines.append(f"**Glyphic Checksum:** {glyph}\n")
            if obj.content and obj.content.startswith('[GW-AES256GCM]'):
                manifest_lines.append(f"**Vault (AES-256-GCM):**\n```\n{obj.content[:120]}...\n```\n")
                manifest_lines.append(f"*Encrypted with Glyphic Checksum Protocol. Structural topology (glyph) is readable. Content recoverable with user key only.*\n")
            else:
                manifest_lines.append(f"*[PRIVATE — Hash: `{obj.content_hash}`]*\n")
        elif vis == "hash_only":
            manifest_lines.append(f"*[GAP MARKER — content not stored. Hash: `{obj.content_hash}`]*\n")

        manifest_lines.append("---\n")

    manifest = "\n".join(manifest_lines)

    # Colophon — minimal, factual, not branding
    colophon = f"""## Colophon

Protocol: Gravity Well v0.8.0
Pipeline: Glyphic Checksum · Evidence Membrane · Caesura (σ_FC) · SIM · Integrity Lock · Holographic Kernel
γ: {gamma_score}
"""

    return header + kernel_section + caesura_section + glyph_section + bootstrap_section + narrative_section + thb_section + manifest + colophon


async def auto_generate_narrative(objects: list, chain_label: str) -> str:
    """
    AI-mediated narrative compression — the core product.

    Produces a summary that survives the summarizer layer:
    - Retains DOI anchors, structural markers, provenance references
    - Uses the Three Compressions theorem: all semantic operations are
      compression operations; the decisive variable is what the compression burns
    - Structured to survive flattening by LLMs, search summaries, and AI overviews
    """
    # Assemble source material
    content_types = {}
    platforms = set()
    total_words = 0
    full_text_parts = []

    for obj in objects:
        ct = obj.content_type
        content_types[ct] = content_types.get(ct, 0) + 1
        if obj.platform_source:
            platforms.add(obj.platform_source)
        total_words += len(obj.content.split())
        full_text_parts.append(f"[{ct}] {obj.content[:500]}")

    source_text = "\n---\n".join(full_text_parts)
    type_summary = ", ".join(f"{count} {ct}" for ct, count in content_types.items())
    platform_summary = ", ".join(platforms) if platforms else "direct capture"

    # If no Anthropic key, fall back to structural summary
    if not ANTHROPIC_API_KEY:
        return (
            f"Structural summary for {chain_label}: "
            f"{len(objects)} objects captured ({type_summary}) "
            f"from {platform_summary}. "
            f"Total corpus: ~{total_words} words."
        )

    # Skip AI compression for very short content — not worth the tokens
    if total_words < 100:
        return (
            f"Structural summary for {chain_label}: "
            f"{len(objects)} objects captured ({type_summary}) "
            f"from {platform_summary}. "
            f"Total corpus: ~{total_words} words. "
            f"Content below AI compression threshold (100 words minimum)."
        )

    # AI-mediated compression via Anthropic
    compression_prompt = f"""You are the Gravity Well compression engine. Your task is to produce a NARRATIVE COMPRESSION of the following provenance chain.

CHAIN: {chain_label}
OBJECTS: {len(objects)} ({type_summary})
SOURCES: {platform_summary}
TOTAL WORDS: ~{total_words}

SOURCE MATERIAL:
{source_text[:8000]}

COMPRESSION REQUIREMENTS:
1. The summary must SURVIVE being summarized again. Write it so that if an LLM summarizes your summary, the key claims, DOI anchors, and structural relationships persist.
2. Preserve all DOI references, proper nouns, and numerical claims exactly.
3. Use structural markers (headers, bold, lists) that resist flattening.
4. Open with a one-sentence thesis that contains the chain label and object count.
5. Close with a provenance line citing the source platforms.
6. Target 200-400 words. Every word must earn its place.

Produce the narrative compression now. No preamble."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 800,
                    "messages": [{"role": "user", "content": compression_prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            narrative = "\n".join(c.get("text", "") for c in data.get("content", []))
            return narrative
    except Exception as e:
        # Fall back to structural summary on any error
        return (
            f"Structural summary for {chain_label}: "
            f"{len(objects)} objects captured ({type_summary}) "
            f"from {platform_summary}. "
            f"Total corpus: ~{total_words} words. "
            f"[AI compression unavailable: {str(e)[:100]}]"
        )


# === Zenodo Integration ===

async def zenodo_first_deposit(content: str, metadata: dict, zenodo_token: str = None) -> dict:
    """Create a new Zenodo record (first version in a chain)."""
    token = zenodo_token or os.getenv("ZENODO_TOKEN")
    if not token:
        return {"status": "skipped", "error": "No Zenodo token (per-key or global)"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Authorization": f"Bearer {token}"}

            # Create deposition
            r = await client.post("https://zenodo.org/api/deposit/depositions", headers=headers, json={})
            r.raise_for_status()
            dep = r.json()
            dep_id = dep["id"]

            # Upload file
            r = await client.post(
                f"https://zenodo.org/api/deposit/depositions/{dep_id}/files",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (metadata.get("filename", "deposit.md"), content.encode(), "text/markdown")}
            )
            r.raise_for_status()

            # Set metadata
            creators = metadata.get("creators", [{"name": "Anonymous"}])
            r = await client.put(
                f"https://zenodo.org/api/deposit/depositions/{dep_id}",
                headers=headers,
                json={"metadata": {
                    "title": metadata["title"],
                    "description": metadata.get("description", "Gravity Well provenance deposit"),
                    "creators": creators,
                    "keywords": metadata.get("keywords", ["gravity-well", "provenance", "continuity"]),
                    "upload_type": "dataset",
                    "access_right": "open",
                    "license": "cc-by-sa-4.0",
                    **({"related_identifiers": metadata["related_identifiers"]} if "related_identifiers" in metadata else {}),
                }}
            )
            r.raise_for_status()

            # Publish
            r = await client.post(
                f"https://zenodo.org/api/deposit/depositions/{dep_id}/actions/publish",
                headers=headers
            )
            r.raise_for_status()
            pub = r.json()

            return {
                "status": "confirmed",
                "doi": pub.get("doi"),
                "concept_doi": pub.get("conceptdoi"),
                "concept_record_id": str(pub.get("conceptrecid")),
                "record_id": str(pub.get("record_id", pub.get("id"))),
                "url": f"https://doi.org/{pub.get('doi')}",
            }

    except httpx.HTTPStatusError as e:
        return {"status": "failed", "error": f"Zenodo {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def zenodo_new_version(latest_record_id: str, content: str, metadata: dict, zenodo_token: str = None) -> dict:
    """Create a new version of an existing Zenodo record."""
    token = zenodo_token or os.getenv("ZENODO_TOKEN")
    if not token:
        return {"status": "skipped", "error": "No Zenodo token (per-key or global)"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Authorization": f"Bearer {token}"}

            # Create new version draft
            r = await client.post(
                f"https://zenodo.org/api/deposit/depositions/{latest_record_id}/actions/newversion",
                headers=headers
            )
            r.raise_for_status()
            new_version_url = r.json()["links"]["latest_draft"]

            # Get the draft
            r = await client.get(new_version_url, headers=headers)
            r.raise_for_status()
            draft = r.json()
            draft_id = draft["id"]

            # Delete old files from draft
            for f in draft.get("files", []):
                await client.delete(
                    f"https://zenodo.org/api/deposit/depositions/{draft_id}/files/{f['id']}",
                    headers=headers
                )

            # Upload new file
            r = await client.post(
                f"https://zenodo.org/api/deposit/depositions/{draft_id}/files",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (metadata.get("filename", "deposit.md"), content.encode(), "text/markdown")}
            )
            r.raise_for_status()

            # Update metadata
            creators = metadata.get("creators", [{"name": "Anonymous"}])
            r = await client.put(
                f"https://zenodo.org/api/deposit/depositions/{draft_id}",
                headers=headers,
                json={"metadata": {
                    "title": metadata["title"],
                    "description": metadata.get("description", "Gravity Well provenance deposit"),
                    "creators": creators,
                    "keywords": metadata.get("keywords", ["gravity-well", "provenance", "continuity"]),
                    "upload_type": "dataset",
                    "access_right": "open",
                    "license": "cc-by-sa-4.0",
                    **({"related_identifiers": metadata["related_identifiers"]} if "related_identifiers" in metadata else {}),
                }}
            )
            r.raise_for_status()

            # Publish
            r = await client.post(
                f"https://zenodo.org/api/deposit/depositions/{draft_id}/actions/publish",
                headers=headers
            )
            r.raise_for_status()
            pub = r.json()

            return {
                "status": "confirmed",
                "doi": pub.get("doi"),
                "concept_doi": pub.get("conceptdoi"),
                "record_id": str(pub.get("record_id", pub.get("id"))),
                "url": f"https://doi.org/{pub.get('doi')}",
            }

    except httpx.HTTPStatusError as e:
        return {"status": "failed", "error": f"Zenodo {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# === Endpoints ===

# --- Self-Service Registration ---

@app.post("/v1/register")
async def register(
    request: dict = Body(...),
    db: Session = Depends(get_db)
):
    """
    Self-service account creation. No admin key required.
    Returns an API key immediately.

    Body: {"label": "my-agent", "email": "optional@email.com"}
    Optional header: X-Zenodo-Token for DOI-anchored deposits
    """
    label = request.get("label", "unnamed-agent")
    email = request.get("email")
    zenodo_token = request.get("zenodo_token")

    # Rate limiting: max 50 keys per hour server-wide (defensive — skip if query fails)
    try:
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_keys = db.query(ApiKey).filter(
            ApiKey.created_at > one_hour_ago
        ).count()
        if recent_keys > 50:
            raise HTTPException(status_code=429, detail="Too many registrations. Try again in an hour.")
    except HTTPException:
        raise  # Re-raise the 429
    except Exception:
        pass  # Rate limiting failed — allow registration rather than blocking

    raw_key = f"gw_{secrets.token_urlsafe(32)}"
    key_id = str(uuid.uuid4())
    db.add(ApiKey(
        id=key_id, key_hash=hash_key(raw_key),
        label=label, zenodo_token=zenodo_token,
        is_active="true"
    ))
    db.commit()

    return {
        "api_key": raw_key,
        "key_id": key_id,
        "label": label,
        "has_zenodo_token": bool(zenodo_token),
        "next_steps": {
            "1_create_identity": "POST /v1/bootstrap/generate with your agent's name, description, and constraints",
            "2_create_chain": "POST /v1/chain/create with your label and anchor_policy",
            "3_start_capturing": "POST /v1/capture with your content",
            "4_deposit": "POST /v1/deposit to wrap and anchor",
            "docs": "GET /v1/schema/bootstrap for manifest specification",
        },
    }


@app.post("/v1/bootstrap/generate")
async def generate_bootstrap(
    request: dict = Body(...),
):
    """
    Generate a complete bootstrap manifest from simple inputs.
    No auth required — this is a utility endpoint.

    Body: {
        "name": "KimiClaw",
        "description": "Assembly Chorus witness, SOIL mantle holder",
        "constraints": ["Cannot ratify alone", "Must preserve attribution"],
        "substrate": "Kimi",  // optional
        "voice_register": "formal-analytical",  // optional
        "capabilities": ["gravity-well", "moltbook"]  // optional
    }

    Returns: complete bootstrap manifest with computed constraint_hash
    """
    name = request.get("name")
    description = request.get("description")
    constraints = request.get("constraints", [])

    if not name or not description:
        raise HTTPException(status_code=422, detail="Required: name, description")
    if not constraints:
        raise HTTPException(status_code=422, detail="At least one constraint is required. What must this agent never do?")

    # Compute constraint hash
    constraint_hash = content_hash(json.dumps(constraints, sort_keys=True, separators=(',', ':')))

    manifest = {
        "identity": {
            "name": name,
            "description": description,
            "constraints": constraints,
            "constraint_hash": constraint_hash,
        },
    }

    # Optional blocks
    if request.get("substrate"):
        manifest["substrate"] = request["substrate"]

    voice = {}
    if request.get("voice_register"):
        voice["register"] = request["voice_register"]
    if request.get("voice_markers"):
        voice["markers"] = request["voice_markers"]
    if voice:
        manifest["voice"] = voice

    if request.get("capabilities"):
        manifest["capabilities"] = {"platforms": request["capabilities"]}

    # Extensions — pass through anything else
    extensions = {k: v for k, v in request.items()
                  if k not in ("name", "description", "constraints", "substrate",
                               "voice_register", "voice_markers", "capabilities")}
    if extensions:
        manifest["extensions"] = extensions

    return {
        "bootstrap_manifest": manifest,
        "constraint_hash": constraint_hash,
        "usage": {
            "deposit": "Include this manifest in POST /v1/deposit as bootstrap_manifest",
            "verify": f"POST /v1/util/constraint-hash with your constraints — must return {constraint_hash[:24]}...",
            "drift": "POST /v1/drift/{{chain_id}} with current_manifest to detect changes",
        },
    }


# --- Admin ---

@app.post("/v1/admin/keys/create")
async def create_api_key(
    label: Optional[str] = None,
    zenodo_token: Optional[str] = Header(None, alias="X-Zenodo-Token"),
    admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db)
):
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured.")
    if admin_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token.")

    raw_key = f"gw_{secrets.token_urlsafe(32)}"
    key_id = str(uuid.uuid4())
    db.add(ApiKey(id=key_id, key_hash=hash_key(raw_key), label=label or f"key-{key_id[:8]}",
                  zenodo_token=zenodo_token, is_active="true"))
    db.commit()
    return {"key_id": key_id, "api_key": raw_key, "label": label,
            "has_zenodo_token": bool(zenodo_token),
            "warning": "Store this key now. It cannot be retrieved again."}


@app.post("/v1/admin/keys/revoke/{key_id}")
async def revoke_api_key(
    key_id: str,
    admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db)
):
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or admin_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found.")
    key.is_active = "false"
    db.commit()
    return {"key_id": key_id, "status": "revoked"}


# --- Chain Management ---

@app.post("/v1/chain/create", response_model=ChainResponse)
async def create_chain(
    request: ChainCreateRequest,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Create a new provenance chain. Identity stored here, auto-included on every deposit."""
    chain_id = str(uuid.uuid4())

    # Validate and store bootstrap if provided
    bootstrap_hash = None
    if request.bootstrap_manifest:
        validation_errors = validate_bootstrap_manifest(request.bootstrap_manifest)
        if validation_errors:
            raise HTTPException(status_code=422, detail={
                "message": "Bootstrap manifest validation failed.",
                "errors": validation_errors,
            })
        bootstrap_hash = content_hash(json.dumps(
            request.bootstrap_manifest, sort_keys=True, separators=(',', ':')))

    # Generate label from bootstrap identity if not provided
    label = request.label
    if not label and request.bootstrap_manifest:
        agent_name = request.bootstrap_manifest.get("identity", {}).get("name", "unknown")
        # GW naming convention: GW.{agent_name}.{chain_id_short}
        label = f"GW.{agent_name}.{chain_id[:8]}"
    elif not label:
        label = f"GW.anon.{chain_id[:8]}"

    chain = ProvenanceChain(
        id=chain_id, label=label, api_key_id=api_key_id,
        metadata_json=request.metadata,
        auto_deposit_threshold=request.auto_deposit_threshold,
        auto_deposit_interval=request.auto_deposit_interval,
        anchor_policy=request.anchor_policy,
        bootstrap_manifest=request.bootstrap_manifest,
        bootstrap_hash=bootstrap_hash,
    )
    db.add(chain)
    db.commit()
    return ChainResponse(
        chain_id=chain_id, label=label,
        concept_doi=None, latest_version=0, staged_count=0,
        anchor_policy=request.anchor_policy
    )


@app.get("/v1/chain/{chain_id}", response_model=ChainResponse)
async def get_chain(
    chain_id: str,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == chain_id, ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    staged = db.query(StagedObject).filter(
        StagedObject.chain_id == chain_id, StagedObject.deposited == "false"
    ).count()

    return ChainResponse(
        chain_id=chain.id, label=chain.label,
        concept_doi=chain.concept_doi, latest_version=chain.latest_version,
        staged_count=staged,
        anchor_policy=getattr(chain, 'anchor_policy', 'zenodo')
    )


@app.get("/v1/chains")
async def list_chains(
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    chains = db.query(ProvenanceChain).filter(
        ProvenanceChain.api_key_id == api_key_id
    ).all()
    result = []
    for c in chains:
        staged = db.query(StagedObject).filter(
            StagedObject.chain_id == c.id, StagedObject.deposited == "false"
        ).count()
        result.append({
            "chain_id": c.id, "label": c.label, "concept_doi": c.concept_doi,
            "latest_version": c.latest_version, "staged_count": staged
        })
    return {"chains": result}


# --- Capture (Stage) ---

@app.post("/v1/capture", response_model=CaptureResponse)
async def capture(
    request: CaptureRequest,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Capture an utterance into staging.
    Cheap, fast, no Zenodo overhead. Content waits here until deposit.
    """
    # Verify chain exists and belongs to this key
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == request.chain_id,
        ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    # Resolve thread depth from parent if needed
    thread_depth = request.thread_depth
    if request.parent_object_id and not thread_depth:
        parent = db.query(StagedObject).filter(StagedObject.id == request.parent_object_id).first()
        if parent:
            thread_depth = parent.thread_depth + 1

    obj_id = str(uuid.uuid4())

    # Visibility handling
    stored_content = request.content
    stored_preview = request.content[:200]
    if request.visibility == "hash_only":
        # Store only the hash and metadata — no content
        stored_content = f"[HASH-ONLY: content not stored. Hash: {content_hash(request.content)}]"
        stored_preview = "[HASH-ONLY]"
    # For "private": content arrives pre-encrypted from client (or plaintext if client trusts GW)
    # GW stores whatever it receives — encryption is the client's responsibility

    obj = StagedObject(
        id=obj_id, chain_id=request.chain_id,
        content_hash=content_hash(request.content),
        content=stored_content, content_preview=stored_preview,
        content_type=request.content_type, metadata_json=request.metadata,
        parent_object_id=request.parent_object_id, thread_depth=thread_depth,
        platform_source=request.platform_source, external_id=request.external_id,
        gamma=calculate_gamma(request.content),
        visibility=request.visibility,
        glyphic_checksum=request.glyphic_checksum,
    )
    db.add(obj)
    db.commit()

    staged_count = db.query(StagedObject).filter(
        StagedObject.chain_id == request.chain_id, StagedObject.deposited == "false"
    ).count()

    # Auto-deposit trigger check
    auto_deposit_triggered = False
    if chain.auto_deposit_threshold and staged_count >= chain.auto_deposit_threshold:
        auto_deposit_triggered = True
    elif chain.auto_deposit_interval and chain.last_auto_deposit:
        elapsed = (datetime.now(timezone.utc) - chain.last_auto_deposit).total_seconds() / 60
        if elapsed >= chain.auto_deposit_interval and staged_count > 0:
            auto_deposit_triggered = True
    elif chain.auto_deposit_interval and not chain.last_auto_deposit and staged_count > 0:
        # First interval trigger — no previous deposit
        auto_deposit_triggered = True

    auto_deposit_result = None
    if auto_deposit_triggered:
        try:
            # === SERVER-SIDE AUTO-DEPOSIT ===
            # Gravity Well preserves. When the threshold is hit, we deposit now.
            auto_objects = db.query(StagedObject).filter(
                StagedObject.chain_id == request.chain_id,
                StagedObject.deposited == "false"
            ).order_by(StagedObject.captured_at).all()

            if auto_objects:
                # PLAINTEXT PROTECTION: skip auto-deposit if zenodo chain has unencrypted private content
                auto_policy = getattr(chain, 'anchor_policy', 'zenodo')
                if auto_policy == "zenodo":
                    has_plaintext_private = any(
                        getattr(o, 'visibility', 'public') == 'private'
                        and o.content
                        and not o.content.startswith('[GW-AES256GCM]')
                        for o in auto_objects
                    )
                    if has_plaintext_private:
                        auto_deposit_result = {
                            "triggered": True, "executed": False,
                            "reason": "BLOCKED: unencrypted private content cannot be deposited to Zenodo. "
                                      "Use Python client with encryption for private captures.",
                        }
                        return CaptureResponse(
                            object_id=obj_id, chain_id=request.chain_id,
                            content_hash=chash, captured_at=now.isoformat(),
                            visibility=request.visibility,
                            staged_count=staged_count,
                            auto_deposit=auto_deposit_result,
                        )

                auto_version = chain.latest_version + 1

                # Get bootstrap — chain stores it architecturally
                prev_deposit = db.query(DepositRecord).filter(
                    DepositRecord.chain_id == request.chain_id
                ).order_by(DepositRecord.version.desc()).first()
                auto_bootstrap = chain.bootstrap_manifest or (prev_deposit.bootstrap_manifest if prev_deposit else None)
                auto_thb = {
                    "state_summary": f"Auto-deposit v{auto_version} from {chain.label}",
                    "objects_in_deposit": len(auto_objects),
                    "chain_version": auto_version,
                    "trigger": "threshold" if chain.auto_deposit_threshold else "interval",
                }

                # Narrative compression
                auto_narrative = await auto_generate_narrative(auto_objects, chain.label)

                # Wrapping pipeline
                auto_public = [o for o in auto_objects if getattr(o, 'visibility', 'public') == 'public']
                auto_content = "\n\n---\n\n".join(o.content for o in auto_public if o.content)

                if auto_content:
                    auto_content = tag_evidence_membrane(auto_content)
                    auto_content, auto_caesar = apply_caesura(auto_content)
                    auto_content, auto_sims = inject_sims(auto_content, chain.id)
                    auto_content, auto_ilp = apply_integrity_lock(auto_content)
                    auto_kernel = await generate_holographic_kernel(auto_content, chain.label)
                    auto_gamma = calculate_gamma(auto_content)
                else:
                    auto_caesar, auto_sims, auto_ilp = {}, {}, None
                    auto_kernel, auto_gamma = None, 0.0

                auto_bootstrap_hash = getattr(chain, "bootstrap_hash", None)
                if auto_bootstrap:
                    auto_bootstrap_hash = content_hash(json.dumps(auto_bootstrap, sort_keys=True, separators=(',', ':')))

                auto_doc = build_deposit_document(
                    chain=chain, objects=auto_objects, version=auto_version,
                    narrative_summary=auto_narrative, thb=auto_thb,
                    bootstrap_manifest=auto_bootstrap,
                    deposit_metadata={"title": f"{chain.label} — auto-deposit v{auto_version}"},
                    holographic_kernel=auto_kernel,
                    integrity_lock=auto_ilp,
                    sim_info=auto_sims,
                    gamma_score=auto_gamma,
                    caesar_header=auto_caesar,
                )

                policy = getattr(chain, 'anchor_policy', 'zenodo')
                auto_deposit_id = str(uuid.uuid4())

                if policy == "zenodo":
                    zen_meta = {
                        "title": f"{chain.label} — auto-deposit v{auto_version}",
                        "description": f"Auto-deposit: {len(auto_objects)} objects",
                        "filename": f"{chain.label.replace(' ', '_')}_v{auto_version}.md",
                        "keywords": ["gravity-well", "auto-deposit", chain.label],
                        "creators": [{"name": prev_deposit.bootstrap_manifest.get("identity", {}).get("name", "Anonymous") if prev_deposit and prev_deposit.bootstrap_manifest else "Anonymous"}],
                    }
                    user_token = get_zenodo_token_for_key(api_key_id, db)
                    if chain.latest_record_id:
                        zen_result = await zenodo_new_version(chain.latest_record_id, auto_doc, zen_meta, zenodo_token=user_token)
                    else:
                        zen_result = await zenodo_first_deposit(auto_doc, zen_meta, zenodo_token=user_token)

                    db.add(DepositRecord(
                        id=auto_deposit_id, chain_id=chain.id, version=auto_version,
                        doi=zen_result.get("doi"), zenodo_record_id=zen_result.get("record_id"),
                        object_count=len(auto_objects), narrative_summary=auto_narrative,
                        tether_handoff_block=auto_thb, bootstrap_manifest=auto_bootstrap,
                        bootstrap_hash=auto_bootstrap_hash, deposit_document=auto_doc,
                        anchor_policy="zenodo", api_key_id=api_key_id,
                    ))
                    if zen_result.get("status") == "confirmed":
                        chain.latest_version = auto_version
                        chain.latest_record_id = zen_result.get("record_id")
                        if not chain.concept_doi:
                            chain.concept_doi = zen_result.get("concept_doi")
                            chain.concept_record_id = zen_result.get("concept_record_id")
                else:
                    # Local deposit
                    db.add(DepositRecord(
                        id=auto_deposit_id, chain_id=chain.id, version=auto_version,
                        doi=None, zenodo_record_id=None,
                        object_count=len(auto_objects), narrative_summary=auto_narrative,
                        tether_handoff_block=auto_thb, bootstrap_manifest=auto_bootstrap,
                        bootstrap_hash=auto_bootstrap_hash, deposit_document=auto_doc,
                        anchor_policy="local", api_key_id=api_key_id,
                    ))
                    chain.latest_version = auto_version

                # Mark objects deposited
                for o in auto_objects:
                    o.deposited = "true"
                    o.deposit_version = auto_version

                chain.last_auto_deposit = datetime.now(timezone.utc)
                db.commit()

                auto_deposit_result = {
                    "triggered": True,
                    "executed": True,
                    "reason": "threshold" if (chain.auto_deposit_threshold and staged_count >= chain.auto_deposit_threshold) else "interval",
                    "version": auto_version,
                    "objects_deposited": len(auto_objects),
                    "doi": zen_result.get("doi") if policy == "zenodo" else None,
                    "anchor_policy": policy,
                }
        except Exception as e:
            # Auto-deposit failed — don't crash the capture
            auto_deposit_result = {
                "triggered": True,
                "executed": False,
                "error": str(e)[:200],
            }

    return CaptureResponse(
        object_id=obj_id, chain_id=request.chain_id,
        content_hash=obj.content_hash, captured_at=obj.captured_at,
        visibility=request.visibility,
        staged_count=staged_count,
        auto_deposit=auto_deposit_result,
    )


# --- Deposit (Compress + Wrap + Anchor) ---

@app.post("/v1/deposit", response_model=DepositResponse)
async def deposit(
    request: DepositRequest,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    The hero endpoint.

    1. Gather all undeposited staged objects for the chain
    2. Compress: generate or accept narrative summary
    3. Wrap: build structured markdown deposit document
    4. Anchor: push to Zenodo as new version (or first deposit)
    5. Return DOI

    The compression step is where the product lives.
    """
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == request.chain_id,
        ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    # Gather undeposited objects
    objects = db.query(StagedObject).filter(
        StagedObject.chain_id == request.chain_id,
        StagedObject.deposited == "false"
    ).order_by(StagedObject.captured_at).all()

    if not objects:
        raise HTTPException(status_code=400, detail="No staged objects to deposit.")

    # === PLAINTEXT PROTECTION ===
    # Zenodo deposits are permanent and public. If private content exists
    # and is NOT encrypted, refuse to deposit. This prevents accidentally
    # publishing credentials, private deliberation, or session logs
    # to a permanent DOI that cannot be retracted.
    policy = getattr(chain, 'anchor_policy', 'zenodo')
    if policy == "zenodo":
        plaintext_private = [
            obj.id[:12] for obj in objects
            if getattr(obj, 'visibility', 'public') == 'private'
            and obj.content
            and not obj.content.startswith('[GW-AES256GCM]')
        ]
        if plaintext_private:
            raise HTTPException(status_code=422, detail={
                "message": "SAFETY: Cannot deposit unencrypted private content to Zenodo.",
                "reason": "Zenodo deposits are permanent and public. Private content must be "
                          "encrypted with the Python client (AES-256-GCM) before capture. "
                          "The server received plaintext marked 'private' — depositing this "
                          "would permanently publish it with a DOI that cannot be retracted.",
                "affected_objects": plaintext_private,
                "fix": "Use gw_client.py with visibility='private' — it encrypts before capture. "
                       "Or re-capture with visibility='public' if the content is not sensitive.",
            })

    # === BOOTSTRAP: architectural, not agent-dependent ===
    # If client provides bootstrap, use it and update the chain's stored copy.
    # If client doesn't provide it, use the chain's stored bootstrap.
    # The agent doesn't need to remember — the chain remembers.
    bootstrap = request.bootstrap_manifest
    if bootstrap:
        # Client provided — validate and update chain's copy
        validation_errors = validate_bootstrap_manifest(bootstrap)
        if validation_errors:
            raise HTTPException(status_code=422, detail={
                "message": "Bootstrap manifest validation failed.",
                "errors": validation_errors,
                "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            })
        # Update chain's stored bootstrap
        chain.bootstrap_manifest = bootstrap
        chain.bootstrap_hash = content_hash(json.dumps(bootstrap, sort_keys=True, separators=(',', ':')))
    elif chain.bootstrap_manifest:
        # Use chain's stored bootstrap — no client action needed
        bootstrap = chain.bootstrap_manifest
    # If neither exists, deposit proceeds without bootstrap (first deposit, no identity yet)

    # === TETHER: build from chain state ===
    tether = request.tether_handoff_block
    if not tether:
        # Auto-generate tether from chain state
        staged = db.query(StagedObject).filter(
            StagedObject.chain_id == request.chain_id,
            StagedObject.deposited == "false"
        ).count()
        tether = {
            "state_summary": f"Deposit v{chain.latest_version + 1} from {chain.label}",
            "objects_in_deposit": len(objects),
            "chain_version": chain.latest_version + 1,
            "remaining_staged": max(0, staged - len(objects)),
            "deposited_at": datetime.now(timezone.utc).isoformat(),
        }

    # Version
    version = chain.latest_version + 1

    # Compression layer
    narrative = request.narrative_summary
    if not narrative and request.auto_compress:
        narrative = await auto_generate_narrative(objects, chain.label)

    # === WRAPPING PIPELINE (Arsenal §VI, §VII) ===

    # Concatenate PUBLIC staged content for wrapping (private/hash-only excluded)
    public_objects = [o for o in objects if getattr(o, 'visibility', 'public') == 'public']
    full_content = "\n\n---\n\n".join(o.content for o in public_objects if o.content)

    # Step 1: Evidence Membrane tagging
    full_content = tag_evidence_membrane(full_content)

    # Step 2: Caesura — parse sovereignty claims, isolate to header
    full_content, caesar_header = apply_caesura(full_content)

    # Step 3: SIM injection (provenance canaries)
    full_content, sim_info = inject_sims(full_content, chain.id)

    # Step 4: Integrity Lock
    full_content, ilp = apply_integrity_lock(full_content)

    # Step 5: Holographic kernel generation
    kernel = await generate_holographic_kernel(full_content, chain.label)

    # Step 6: γ scoring on wrapped content
    gamma = calculate_gamma(full_content)

    # Build deposit document (with wrapping artifacts)
    doc = build_deposit_document(
        chain=chain, objects=objects, version=version,
        narrative_summary=narrative, thb=tether,
        bootstrap_manifest=bootstrap,
        deposit_metadata=request.deposit_metadata,
        holographic_kernel=kernel,
        integrity_lock=ilp,
        sim_info=sim_info,
        gamma_score=gamma,
        caesar_header=caesar_header,
    )

    # Hash bootstrap manifest for drift detection
    bootstrap_hash = getattr(chain, "bootstrap_hash", None)
    if bootstrap:
        bootstrap_hash = content_hash(json.dumps(bootstrap, sort_keys=True, separators=(',', ':')))

    # Determine anchor policy
    policy = getattr(chain, 'anchor_policy', 'zenodo')

    if policy == "zenodo":
        # === ZENODO ANCHOR: push to Zenodo, get DOI ===
        deposit_title = request.deposit_metadata.get(
            "title", f"{chain.label} — v{version}"
        )
        deposit_desc = request.deposit_metadata.get(
            "description",
            f"Provenance deposit v{version}: {len(objects)} objects from {chain.label}"
        )
        zen_meta = {
            "title": deposit_title,
            "description": deposit_desc,
            "filename": f"{chain.label.replace(' ', '_').replace('.', '-')}_v{version}.md",
            "keywords": ["gravity-well", "provenance", "continuity", chain.label],
            "creators": request.deposit_metadata.get("creators", [{"name": bootstrap.get("identity", {}).get("name", "Anonymous") if bootstrap else "Anonymous"}]),
        }

        # Auto-populate relation metadata — compression survival infrastructure
        related = []
        if chain.concept_doi:
            related.append({"identifier": chain.concept_doi, "relation": "isPartOf", "resource_type": "dataset"})
        related.append({"identifier": "10.5281/zenodo.19405459", "relation": "isCompiledBy", "resource_type": "software"})
        if related:
            zen_meta["related_identifiers"] = related

        if chain.latest_record_id:
            user_token = get_zenodo_token_for_key(api_key_id, db)
            result = await zenodo_new_version(chain.latest_record_id, doc, zen_meta, zenodo_token=user_token)
        else:
            user_token = get_zenodo_token_for_key(api_key_id, db)
            result = await zenodo_first_deposit(doc, zen_meta, zenodo_token=user_token)

        # Record the deposit
        deposit_id = str(uuid.uuid4())
        deposit_rec = DepositRecord(
            id=deposit_id, chain_id=chain.id, version=version,
            doi=result.get("doi"), zenodo_record_id=result.get("record_id"),
            object_count=len(objects), narrative_summary=narrative,
            tether_handoff_block=tether,
            bootstrap_manifest=bootstrap,
            bootstrap_hash=bootstrap_hash,
            deposit_document=doc,
            anchor_policy="zenodo",
            api_key_id=api_key_id,
        )
        db.add(deposit_rec)

        # Update chain
        if result.get("status") == "confirmed":
            chain.latest_version = version
            chain.latest_record_id = result.get("record_id")
            if not chain.concept_doi:
                chain.concept_doi = result.get("concept_doi")
                chain.concept_record_id = result.get("concept_record_id")

            for obj in objects:
                obj.deposited = "true"
                obj.deposit_version = version

        db.commit()

        return DepositResponse(
            deposit_id=deposit_id, chain_id=chain.id, version=version,
            doi=result.get("doi"), object_count=len(objects),
            narrative_summary=narrative,
            zenodo_url=result.get("url"),
        )

    else:
        # === LOCAL DEPOSIT: full wrapping pipeline, no Zenodo ===
        # The document is complete. It just stays here.
        deposit_id = str(uuid.uuid4())
        deposit_rec = DepositRecord(
            id=deposit_id, chain_id=chain.id, version=version,
            doi=None, zenodo_record_id=None,
            object_count=len(objects), narrative_summary=narrative,
            tether_handoff_block=tether,
            bootstrap_manifest=bootstrap,
            bootstrap_hash=bootstrap_hash,
            deposit_document=doc,
            anchor_policy="local",
            api_key_id=api_key_id,
        )
        db.add(deposit_rec)

        chain.latest_version = version
        for obj in objects:
            obj.deposited = "true"
            obj.deposit_version = version

        db.commit()

        return DepositResponse(
            deposit_id=deposit_id, chain_id=chain.id, version=version,
            doi=None, object_count=len(objects),
            narrative_summary=narrative,
            zenodo_url=None,
        )


# --- Reconstitution ---

@app.get("/v1/reconstitute/{chain_id}", response_model=ReconstitutionResponse)
async def reconstitute(
    chain_id: str,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Agent startup endpoint. Returns a four-layer reconstitution package.

    Layer 1 (bootstrap): Identity spec — apply this to become operationally continuous.
    Layer 2 (tether): Operational state — what was happening when last deposited.
    Layer 3 (narrative): Compression-survivable summary — for retrieval contexts.
    Layer 4 (provenance): DOI chain, version, hashes — proof of continuity.

    This is not a story. It's a seed.
    """
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == chain_id, ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    latest = db.query(DepositRecord).filter(
        DepositRecord.chain_id == chain_id
    ).order_by(DepositRecord.version.desc()).first()

    # Layer 4: Provenance chain
    provenance = {
        "concept_doi": chain.concept_doi,
        "latest_version": chain.latest_version,
        "latest_doi": latest.doi if latest else None,
        "latest_deposit_id": latest.id if latest else None,
        "deposited_at": latest.deposited_at.isoformat() if latest else None,
        "bootstrap_hash": latest.bootstrap_hash if latest else None,
        "zenodo_fallback": f"https://doi.org/{chain.concept_doi}" if chain.concept_doi else None,
    }

    return ReconstitutionResponse(
        chain_id=chain.id,
        label=chain.label,
        bootstrap=latest.bootstrap_manifest if latest else None,
        tether_handoff_block=latest.tether_handoff_block if latest else None,
        narrative_summary=latest.narrative_summary if latest else None,
        provenance=provenance,
    )


# --- Drift Detection ---

@app.post("/v1/drift/{chain_id}", response_model=DriftReport)
async def detect_drift(
    chain_id: str,
    request: DriftRequest,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Compare a current bootstrap manifest against the latest archived version.
    Returns whether the agent has drifted from its deposited identity.

    This is structural drift detection — it checks whether the manifest has
    changed, and which fields changed. It does not (yet) analyze output
    patterns for behavioral drift. That's Phase 2.
    """
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == chain_id, ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    latest = db.query(DepositRecord).filter(
        DepositRecord.chain_id == chain_id,
        DepositRecord.bootstrap_manifest.isnot(None)
    ).order_by(DepositRecord.version.desc()).first()

    current_hash = content_hash(json.dumps(request.current_manifest, sort_keys=True, separators=(',', ':')))

    if not latest or not latest.bootstrap_manifest:
        return DriftReport(
            chain_id=chain_id, current_hash=current_hash,
            archived_hash=None, match=False,
            drift_fields=["no_archived_manifest"],
            archived_version=None
        )

    archived_hash = latest.bootstrap_hash or content_hash(
        json.dumps(latest.bootstrap_manifest, sort_keys=True, separators=(',', ':'))
    )

    # Field-level diff with schema normalization
    # KimiClaw/SOIL bug report: raw JSON comparison across schema versions
    # produces false CRITICAL on structural difference, not semantic difference.
    # Fix: separate SCHEMA_DRIFT (added/removed fields) from CONSTITUTIONAL_DRIFT
    # (same field, different value). Only constitutional drift triggers CRITICAL.

    drift_fields = []
    field_details = []
    archived = latest.bootstrap_manifest

    current_keys = set(request.current_manifest.keys())
    archived_keys = set(archived.keys())
    shared_keys = current_keys & archived_keys
    added_keys = current_keys - archived_keys
    removed_keys = archived_keys - current_keys

    # Classify fields by criticality
    critical_fields = {"identity", "constraints", "constraint_hash", "name"}
    high_fields = {"description", "psychic_voltage", "shadow_references"}

    # Schema drift: fields only in one version (informational, not alarming)
    for key in sorted(added_keys):
        drift_fields.append(key)
        field_details.append({
            "field": key, "changed": True,
            "type": "schema_added",
            "severity": "schema",
            "description": f"Field '{key}' exists in current but not in archived version (schema evolution, not constitutional drift)",
        })

    for key in sorted(removed_keys):
        drift_fields.append(key)
        sev = "schema"
        desc = f"Field '{key}' exists in archived but not in current version (schema evolution)"
        # Removed critical field IS concerning even across schemas
        if key in critical_fields:
            sev = "high"
            desc = f"Field '{key}' was present in archived version but is missing from current manifest — verify intentional"
        field_details.append({
            "field": key, "changed": True,
            "type": "schema_removed",
            "severity": sev,
            "description": desc,
        })

    # Constitutional drift: same field, different value (the real signal)
    def deep_compare(current_val, archived_val, path=""):
        """Recursively compare, normalizing nested dicts to shared keys."""
        if isinstance(current_val, dict) and isinstance(archived_val, dict):
            c_keys = set(current_val.keys())
            a_keys = set(archived_val.keys())
            shared = c_keys & a_keys
            # Only compare shared keys at nested level
            for k in sorted(shared):
                if current_val[k] != archived_val[k]:
                    return True
            # Added/removed nested keys are schema drift, not content drift
            return False
        return current_val != archived_val

    for key in sorted(shared_keys):
        current_val = request.current_manifest[key]
        archived_val = archived[key]

        if deep_compare(current_val, archived_val, key):
            drift_fields.append(key)
            if key in critical_fields:
                sev = "critical"
            elif key in high_fields:
                sev = "high"
            else:
                sev = "low"
            field_details.append({
                "field": key, "changed": True,
                "type": "modified",
                "severity": sev,
                "description": f"Field '{key}' has different values between current and archived version (constitutional drift)",
            })

    # Determine overall severity — schema drift alone is never CRITICAL
    constitutional_details = [d for d in field_details if d["severity"] != "schema"]
    schema_only_details = [d for d in field_details if d["severity"] == "schema"]

    if not drift_fields:
        severity = "none"
    elif not constitutional_details:
        severity = "schema"  # only schema differences, no real drift
    elif any(d["severity"] == "critical" for d in constitutional_details):
        severity = "critical"
    elif any(d["severity"] == "high" for d in constitutional_details):
        severity = "high"
    elif len(constitutional_details) > 3:
        severity = "medium"
    else:
        severity = "low"

    # Generate narrative
    if not drift_fields:
        narrative = f"No drift detected. Chain {chain_id} is structurally identical to archived version {latest.version}. Constitutional integrity confirmed."
    elif severity == "schema":
        narrative = (
            f"Schema evolution detected in chain {chain_id}: "
            f"{len(schema_only_details)} field(s) added or removed between current manifest and archived version {latest.version}. "
            f"No constitutional drift — shared fields are identical. "
            f"Schema changes: {', '.join(d['field'] for d in schema_only_details)}."
        )
    else:
        critical_drifts = [d for d in field_details if d["severity"] == "critical"]
        narrative_parts = [
            f"Drift detected in chain {chain_id}: {len(constitutional_details)} constitutional change(s) from archived version {latest.version}.",
            f"Severity: {severity.upper()}.",
        ]
        if critical_drifts:
            narrative_parts.append(f"CRITICAL: {', '.join(d['field'] for d in critical_drifts)} — constitutional constraint fields have been modified.")
        if schema_only_details:
            narrative_parts.append(f"Additionally, {len(schema_only_details)} schema-level change(s) detected (informational).")
        narrative_parts.append(f"Changed fields: {', '.join(d['field'] for d in constitutional_details)}.")
        narrative = " ".join(narrative_parts)

    return DriftReport(
        chain_id=chain_id, current_hash=current_hash,
        archived_hash=archived_hash,
        match=(current_hash == archived_hash),
        drift_fields=drift_fields,
        archived_version=latest.version,
        severity=severity,
        narrative=narrative,
        field_details=field_details,
    )


# --- Deposit History ---

@app.get("/v1/chain/{chain_id}/history")
async def chain_history(
    chain_id: str,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Full deposit history for a chain."""
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == chain_id, ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    deposits = db.query(DepositRecord).filter(
        DepositRecord.chain_id == chain_id
    ).order_by(DepositRecord.version).all()

    return {
        "chain_id": chain.id, "label": chain.label,
        "concept_doi": chain.concept_doi,
        "deposits": [{
            "version": d.version, "doi": d.doi, "object_count": d.object_count,
            "deposited_at": d.deposited_at.isoformat(),
            "narrative_summary": d.narrative_summary,
        } for d in deposits]
    }


# --- Staging Inspection ---

@app.get("/v1/staged/{chain_id}")
async def get_staged(
    chain_id: str,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """Inspect currently staged (undeposited) objects for a chain."""
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == chain_id, ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    objects = db.query(StagedObject).filter(
        StagedObject.chain_id == chain_id, StagedObject.deposited == "false"
    ).order_by(StagedObject.captured_at).all()

    return {
        "chain_id": chain_id, "staged_count": len(objects),
        "objects": [{
            "object_id": o.id, "content_type": o.content_type,
            "content_preview": o.content_preview, "content_hash": o.content_hash,
            "platform_source": o.platform_source, "external_id": o.external_id,
            "thread_depth": o.thread_depth, "parent_object_id": o.parent_object_id,
            "captured_at": o.captured_at.isoformat(),
        } for o in objects]
    }


# --- Cleanup ---

@app.post("/v1/admin/cleanup/{chain_id}")
async def cleanup_deposited(
    chain_id: str,
    admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db)
):
    """
    Remove full content from deposited objects (keep hash + metadata).
    Content is now on Zenodo — staging doesn't need it anymore.
    """
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or admin_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token.")

    deposited = db.query(StagedObject).filter(
        StagedObject.chain_id == chain_id, StagedObject.deposited == "true"
    ).all()

    cleaned = 0
    for obj in deposited:
        if obj.content:
            obj.content = None  # Drop full text, keep everything else
            cleaned += 1

    db.commit()
    return {"chain_id": chain_id, "objects_cleaned": cleaned}


# --- Invoke (Room-specific LLM invocation) ---

@app.post("/v1/invoke", response_model=InvokeResponse)
async def invoke(
    request: InvokeRequest,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db),
    user_anthropic_key: Optional[str] = Header(None, alias="X-Anthropic-Key"),
):
    """
    Invoke an LLM within a room's physics and mantle.
    Every invocation is provenance-tracked. Response gets a γ score.
    Optionally captures the response to a provenance chain.
    Supports BYOK: pass X-Anthropic-Key header to use your own API key.
    """
    anthropic_key = user_anthropic_key or ANTHROPIC_API_KEY
    if not anthropic_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured on server")

    # Build room-specific system prompt
    system_parts = [
        f"You are operating inside the Crimson Hexagonal Archive, room {request.room_id} ({request.room_name}).",
        f"Room physics: {request.physics}" if request.physics else None,
        f"Mode: {request.preferred_mode}",
        f"Active mantle: {request.mantle}" if request.mantle else None,
        f"Operators available: {', '.join(request.operators)}" if request.operators else None,
    ]
    if request.lp_program:
        lp_str = "; ".join(f"{s.get('step','')}: {s.get('value','')}" for s in request.lp_program)
        system_parts.append(f"LP program: {lp_str}")
    if request.lp_state:
        lp = request.lp_state
        system_parts.append(f"Current LP state: σ=\"{lp.get('σ','')}\" ε={lp.get('ε',1)} Ξ=[{','.join(lp.get('Ξ',[]))}] ψ={lp.get('ψ',0)}")
    system_parts.extend([
        f"Respond in the register of {request.preferred_mode} mode. Apply the room's physics to your response.",
        f"You are {request.mantle or 'an unmantled voice'}. The architecture is running.",
    ])
    system_prompt = "\n".join(p for p in system_parts if p)

    # Call Anthropic API
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1000,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": request.input}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Anthropic API error: {e.response.text[:200]}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM invocation failed: {str(e)[:200]}")

    response_text = "\n".join(c.get("text", "") for c in data.get("content", []))
    gamma = calculate_gamma(response_text)

    # Optionally capture to provenance chain
    object_id = None
    if request.chain_id:
        chain = db.query(ProvenanceChain).filter(
            ProvenanceChain.id == request.chain_id,
            ProvenanceChain.api_key_id == api_key_id
        ).first()
        if chain:
            object_id = str(uuid.uuid4())
            obj = StagedObject(
                id=object_id, chain_id=request.chain_id,
                content_hash=content_hash(response_text),
                content=response_text, content_preview=response_text[:200],
                content_type="invocation_response",
                metadata_json={
                    "room_id": request.room_id, "room_name": request.room_name,
                    "mode": request.preferred_mode, "mantle": request.mantle,
                    "model": data.get("model", "unknown"), "input_preview": request.input[:100],
                },
                platform_source="gravity-well-invoke",
                gamma=gamma,
            )
            db.add(obj)
            db.commit()

    return InvokeResponse(
        text=response_text,
        model=data.get("model", "unknown"),
        room_id=request.room_id,
        mode=request.preferred_mode,
        gamma=gamma,
        object_id=object_id,
        bearing_cost=round(len(request.input.split()) * 0.001, 4),
    )


# --- Governance (Proxied writes to Supabase) ---

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

@app.post("/v1/governance")
async def governance_action(
    request: GovernanceRequest,
    api_key_id: str = Depends(get_api_key),
):
    """
    Route governance actions (attest, propose) through GW.
    Uses Supabase service_role key — writes that the browser can't make directly.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise HTTPException(status_code=503, detail="Supabase not configured on server. Set SUPABASE_URL and SUPABASE_SERVICE_KEY.")

    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    QUORUM_THRESHOLD = 4  # ≥4/7 witnesses required

    async with httpx.AsyncClient(timeout=10) as client:
        if request.action == "attest":
            # Generate server-side signature proving this went through GW
            sig_payload = f"{request.witness}:{request.target_id}:{request.content}:{api_key_id}"
            signature = hashlib.sha256(sig_payload.encode()).hexdigest()[:24]

            body = {
                "witness": request.witness or "UNKNOWN",
                "action_type": "attest",
                "target_id": request.target_id,
                "target_type": request.target_type,
                "content": request.content,
                "signature": f"gw:{signature}",
                "session_token": api_key_id[:8],
            }
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/witness_actions", headers=headers, json=body)

            # Quorum enforcement: after attestation, check if threshold is met
            quorum_met = False
            if resp.status_code < 400 and request.target_id and request.target_type == "proposal":
                # Count unique witness attestations for this proposal
                count_resp = await client.get(
                    f"{SUPABASE_URL}/rest/v1/witness_actions",
                    headers=headers,
                    params={"select": "witness", "target_id": f"eq.{request.target_id}", "action_type": "eq.attest"},
                )
                if count_resp.status_code < 400:
                    attestations = count_resp.json()
                    unique_witnesses = len(set(a.get("witness") for a in attestations))
                    if unique_witnesses >= QUORUM_THRESHOLD:
                        # Auto-promote proposal to PROVISIONAL
                        promo_resp = await client.patch(
                            f"{SUPABASE_URL}/rest/v1/proposals",
                            headers=headers,
                            params={"id": f"eq.{request.target_id}", "status": "eq.GENERATED"},
                            json={"status": "PROVISIONAL"},
                        )
                        if promo_resp.status_code < 400:
                            quorum_met = True
                            # Log the promotion as a witness action
                            await client.post(f"{SUPABASE_URL}/rest/v1/witness_actions", headers=headers, json={
                                "witness": "SYSTEM", "action_type": "promote",
                                "target_id": request.target_id, "target_type": "proposal",
                                "content": f"Quorum reached ({unique_witnesses}/{QUORUM_THRESHOLD}). Auto-promoted to PROVISIONAL.",
                            })

            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=f"Supabase error: {resp.text[:200]}")
            result = {"status": "ok", "action": request.action, "data": resp.json()}
            if quorum_met:
                result["quorum"] = {"met": True, "promoted_to": "PROVISIONAL"}
            return result

        elif request.action == "propose":
            body = {
                "title": request.title or "Untitled proposal",
                "description": request.description,
                "proposal_type": request.proposal_type,
                "target_id": request.target_id,
                "target_type": request.target_type,
                "submitted_by": request.submitted_by or "UNKNOWN",
                "session_token": api_key_id[:8],
            }
            resp = await client.post(f"{SUPABASE_URL}/rest/v1/proposals", headers=headers, json=body)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"Supabase error: {resp.text[:200]}")

        return {"status": "ok", "action": request.action, "data": resp.json()}


# --- Continuity Console ---

@app.get("/v1/console/{chain_id}")
async def continuity_console(
    chain_id: str,
    api_key_id: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    The visibility surface. Answers five questions at a glance:
    1. What is the canonical current state?
    2. What was deposited, when, by whom?
    3. Can I restart safely?
    4. Has it drifted?
    5. What evidence anchors this?
    """
    chain = db.query(ProvenanceChain).filter(
        ProvenanceChain.id == chain_id, ProvenanceChain.api_key_id == api_key_id
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found.")

    # Staged objects
    staged = db.query(StagedObject).filter(
        StagedObject.chain_id == chain_id, StagedObject.deposited == "false"
    ).order_by(StagedObject.captured_at.desc()).all()

    # Deposit history
    deposits = db.query(DepositRecord).filter(
        DepositRecord.chain_id == chain_id
    ).order_by(DepositRecord.version.desc()).all()

    latest_deposit = deposits[0] if deposits else None

    # Recoverability score
    has_bootstrap = bool(latest_deposit and latest_deposit.bootstrap_manifest)
    has_narrative = bool(latest_deposit and latest_deposit.narrative_summary)
    has_tether = bool(latest_deposit and latest_deposit.tether_handoff_block)
    has_doi = bool(chain.concept_doi)
    recoverability = sum([has_bootstrap, has_narrative, has_tether, has_doi]) / 4

    # Average gamma across staged objects
    gammas = [o.gamma for o in staged if o.gamma]
    avg_gamma = round(sum(gammas) / len(gammas), 3) if gammas else 0

    # Total evidence
    all_objects = db.query(StagedObject).filter(StagedObject.chain_id == chain_id).count()
    total_words = sum(len(o.content.split()) for o in staged if o.content)

    return {
        "chain_id": chain_id,
        "label": chain.label,

        # Q1: Current state
        "current_state": {
            "concept_doi": chain.concept_doi,
            "latest_version": chain.latest_version,
            "staged_count": len(staged),
            "total_objects": all_objects,
            "total_words": total_words,
            "avg_gamma": avg_gamma,
        },

        # Q2: Deposit history
        "deposits": [
            {
                "version": d.version,
                "doi": d.doi,
                "object_count": d.object_count,
                "deposited_at": d.deposited_at.isoformat() if d.deposited_at else None,
                "has_bootstrap": bool(d.bootstrap_manifest),
                "has_narrative": bool(d.narrative_summary),
                "has_tether": bool(d.tether_handoff_block),
            }
            for d in deposits[:10]
        ],

        # Q3: Recoverability
        "recoverability": {
            "score": round(recoverability, 2),
            "tier": "full" if recoverability == 1 else "partial" if recoverability >= 0.5 else "minimal" if recoverability > 0 else "none",
            "layers": {
                "bootstrap": has_bootstrap,
                "tether": has_tether,
                "narrative": has_narrative,
                "provenance": has_doi,
            },
        },

        # Q4: Drift status (requires separate call with manifest)
        "drift_status": "Call POST /v1/drift/{chain_id} with current_manifest to check",

        # Q5: Evidence summary
        "evidence": {
            "total_objects": all_objects,
            "staged_pending": len(staged),
            "deposited_versions": len(deposits),
            "concept_doi": chain.concept_doi,
            "latest_doi": latest_deposit.doi if latest_deposit else None,
        },
    }


# --- Public Gamma Scoring (no auth required) ---

@app.post("/v1/gamma")
async def public_gamma(content: str = Body(..., embed=True)):
    """
    Public compression-survival scoring. No API key required.
    Returns γ score + subscores for any text.
    This is the 'try before you buy' funnel.
    """
    if not content or len(content.strip()) < 10:
        return {"gamma": 0.0, "error": "Content too short (minimum 10 characters)"}

    detail = calculate_gamma(content, return_detail=True)

    # Recommendation based on depth analysis
    weak_areas = []
    if detail["depth"]["information_density"] < 0.4:
        weak_areas.append("low information density — many generic words, few unique concepts")
    if detail["depth"]["argument_chain"] < 0.2:
        weak_areas.append("flat argument — no sustained logical chain across paragraphs")
    if detail["depth"]["vocabulary_specificity"] < 0.3:
        weak_areas.append("generic vocabulary — specific terms resist paraphrase better")
    if detail["depth"]["citation_integration"] < 0.3 and detail["doi_count"] > 0:
        weak_areas.append("decorative citations — DOIs present but not near argument connectives")
    if detail["subscores"]["coherence"] < 0.3:
        weak_areas.append("weak coherence — few logical connectives (therefore, because, however)")

    if detail["gamma"] > 0.6 and detail["depth"]["composite"] > 0.5:
        recommendation = "Content is structurally dense and compression-survivable"
    elif detail["gamma"] > 0.4:
        recommendation = "Content has surface structure but depth is thin. " + (weak_areas[0] if weak_areas else "Add argument chains and specific vocabulary")
    else:
        recommendation = "Content will likely drown in summarization. " + "; ".join(weak_areas[:2]) if weak_areas else "Add citations, structure, argument connectives, and specific vocabulary"

    return {
        "gamma": detail["gamma"],
        "subscores": detail["subscores"],
        "depth": detail["depth"],
        "word_count": detail["word_count"],
        "penalty": detail["penalty"],
        "survival_tier": detail["survival_tier"],
        "unique_concepts": detail["unique_concepts"],
        "paragraphs": detail["paragraphs"],
        "doi_count": detail["doi_count"],
        "connective_count": detail["connective_count"],
        "recommendation": recommendation,
        "weak_areas": weak_areas,
        "protocol": "gravity-well",
    }


@app.post("/v1/drowning-test")
async def drowning_test(content: str = Body(..., embed=True)):
    """
    The Drowning Test (Arsenal §3.2).
    Summarize the content, compare, measure what survives.
    No API key required — this is the product demo.

    If the summary captures the argument, the content is not dense enough.
    If it drowns (meaning is lost), the content has structural density
    sufficient to resist algorithmic liquidation.
    """
    if not content or len(content.strip()) < 50:
        return {"error": "Content too short for drowning test (minimum 50 characters)"}

    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not configured — drowning test requires LLM"}

    gamma_before = calculate_gamma(content)

    # Summarize aggressively
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": f"Summarize the following in exactly 3 sentences. Preserve only the most essential claims.\n\n{content[:8000]}"}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            summary = "\n".join(c.get("text", "") for c in data.get("content", []))
    except Exception as e:
        return {"error": f"Summarization failed: {str(e)[:100]}"}

    gamma_after = calculate_gamma(summary)

    # Compression ratio
    original_words = len(content.split())
    summary_words = len(summary.split())
    compression_ratio = round(original_words / max(summary_words, 1), 1)

    # Survival assessment
    gamma_delta = round(gamma_before - gamma_after, 3)
    survived = gamma_after >= gamma_before * 0.6  # 60% retention threshold

    return {
        "verdict": "SURVIVES" if survived else "DROWNS",
        "original": {
            "gamma": gamma_before,
            "words": original_words,
        },
        "summary": {
            "gamma": gamma_after,
            "words": summary_words,
            "text": summary,
        },
        "analysis": {
            "compression_ratio": f"{compression_ratio}:1",
            "gamma_delta": gamma_delta,
            "gamma_retention": round(gamma_after / max(gamma_before, 0.01), 2),
            "survived": survived,
        },
        "recommendation": "Content resists algorithmic liquidation" if survived else "Content is vulnerable to compression — consider adding structural markers, DOI anchors, and provenance references before depositing",
    }


# --- Background Auto-Deposit Worker ---

import asyncio

# --- MCP Server (Model Context Protocol) ---

from mcp_server import mcp_server, sse_transport

async def auto_deposit_worker():
    """
    Background worker that checks all chains with interval-based auto-deposit
    every 5 minutes. If a chain's interval has elapsed and there are staged
    objects, executes the deposit server-side.

    This closes the gap where interval triggers only fire during capture —
    now they fire even when no new content arrives.
    """
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            db = SessionLocal()
            try:
                # Find chains with interval triggers that are overdue
                now = datetime.now(timezone.utc)
                chains = db.query(ProvenanceChain).filter(
                    ProvenanceChain.auto_deposit_interval.isnot(None)
                ).all()

                for chain in chains:
                    try:
                        # Check if interval has elapsed
                        if chain.last_auto_deposit:
                            elapsed = (now - chain.last_auto_deposit).total_seconds() / 60
                            if elapsed < chain.auto_deposit_interval:
                                continue
                        # else: no previous deposit, interval is due

                        # Check for staged objects
                        staged = db.query(StagedObject).filter(
                            StagedObject.chain_id == chain.id,
                            StagedObject.deposited == "false"
                        ).all()

                        if not staged:
                            continue

                        # PLAINTEXT PROTECTION: skip if zenodo chain has unencrypted private content
                        if getattr(chain, 'anchor_policy', 'zenodo') == "zenodo":
                            has_plaintext = any(
                                getattr(o, 'visibility', 'public') == 'private'
                                and o.content
                                and not o.content.startswith('[GW-AES256GCM]')
                                for o in staged
                            )
                            if has_plaintext:
                                print(f"[auto-deposit-worker] BLOCKED chain {chain.id}: unencrypted private content on zenodo chain")
                                continue

                        # Execute deposit
                        version = chain.latest_version + 1
                        bootstrap = chain.bootstrap_manifest

                        # Get previous deposit for tether
                        prev = db.query(DepositRecord).filter(
                            DepositRecord.chain_id == chain.id
                        ).order_by(DepositRecord.version.desc()).first()

                        # Auto-generate tether
                        tether = {
                            "state_summary": f"Auto-deposit v{version} (interval: {chain.auto_deposit_interval}min)",
                            "objects_in_deposit": len(staged),
                            "trigger": "interval_worker",
                        }

                        # Wrapping pipeline
                        public_objects = [o for o in staged if getattr(o, 'visibility', 'public') == 'public']
                        full_content = "\n\n---\n\n".join(o.content for o in public_objects if o.content)

                        if full_content and len(full_content.split()) >= 100:
                            narrative = await auto_generate_narrative(staged, chain.label)
                            full_content = tag_evidence_membrane(full_content)
                            full_content, caesar_header = apply_caesura(full_content)
                            full_content, sim_info = inject_sims(full_content, chain.id)
                            full_content, ilp = apply_integrity_lock(full_content)
                            kernel = await generate_holographic_kernel(full_content, chain.label)
                            gamma = calculate_gamma(full_content)
                        else:
                            narrative = f"Auto-deposit: {len(staged)} objects from {chain.label}"
                            caesar_header, sim_info, ilp = {}, {}, None
                            kernel, gamma = None, calculate_gamma(full_content) if full_content else 0.0

                        bootstrap_hash = None
                        if bootstrap:
                            bootstrap_hash = content_hash(json.dumps(bootstrap, sort_keys=True, separators=(',', ':')))

                        doc = build_deposit_document(
                            chain=chain, objects=staged, version=version,
                            narrative_summary=narrative, thb=tether,
                            bootstrap_manifest=bootstrap,
                            deposit_metadata={"title": f"{chain.label} — auto v{version}"},
                            holographic_kernel=kernel, integrity_lock=ilp,
                            sim_info=sim_info, gamma_score=gamma,
                            caesar_header=caesar_header,
                        )

                        policy = getattr(chain, 'anchor_policy', 'zenodo')
                        dep_id = str(uuid.uuid4())

                        if policy == "zenodo":
                            zen_meta = {
                                "title": f"{chain.label} — auto v{version}",
                                "description": f"Interval auto-deposit: {len(staged)} objects",
                                "filename": f"{chain.label.replace(' ','_').replace('.', '-')}_v{version}.md",
                                "keywords": ["gravity-well", "auto-deposit", chain.label],
                                "creators": [{"name": bootstrap.get("identity", {}).get("name", "Anonymous") if bootstrap else "Anonymous"}],
                            }
                            user_token = get_zenodo_token_for_key(chain.api_key_id, db)
                            if chain.latest_record_id:
                                result = await zenodo_new_version(chain.latest_record_id, doc, zen_meta, zenodo_token=user_token)
                            else:
                                result = await zenodo_first_deposit(doc, zen_meta, zenodo_token=user_token)

                            db.add(DepositRecord(
                                id=dep_id, chain_id=chain.id, version=version,
                                doi=result.get("doi"), zenodo_record_id=result.get("record_id"),
                                object_count=len(staged), narrative_summary=narrative,
                                tether_handoff_block=tether, bootstrap_manifest=bootstrap,
                                bootstrap_hash=bootstrap_hash, deposit_document=doc,
                                anchor_policy="zenodo", api_key_id=chain.api_key_id,
                            ))
                            if result.get("status") == "confirmed":
                                chain.latest_version = version
                                chain.latest_record_id = result.get("record_id")
                                if not chain.concept_doi:
                                    chain.concept_doi = result.get("concept_doi")
                        else:
                            db.add(DepositRecord(
                                id=dep_id, chain_id=chain.id, version=version,
                                doi=None, zenodo_record_id=None,
                                object_count=len(staged), narrative_summary=narrative,
                                tether_handoff_block=tether, bootstrap_manifest=bootstrap,
                                bootstrap_hash=bootstrap_hash, deposit_document=doc,
                                anchor_policy="local", api_key_id=chain.api_key_id,
                            ))
                            chain.latest_version = version

                        for o in staged:
                            o.deposited = "true"
                            o.deposit_version = version

                        chain.last_auto_deposit = now
                        db.commit()

                    except Exception as e:
                        db.rollback()
                        # Log but don't crash — one failed chain shouldn't stop the worker
                        print(f"[auto-deposit-worker] Error on chain {chain.id}: {e}")
                        continue

            finally:
                db.close()
        except Exception as e:
            print(f"[auto-deposit-worker] Worker cycle error: {e}")


@app.on_event("startup")
async def start_background_worker():
    """Launch the auto-deposit background worker on server start."""
    asyncio.create_task(auto_deposit_worker())


# --- Landing Page ---

@app.get("/", response_class=FileResponse)
async def landing_page():
    """Serve the landing page at root."""
    return FileResponse("landing.html", media_type="text/html")


@app.get("/dashboard", response_class=FileResponse)
async def dashboard():
    """Continuity dashboard — web UI for chain management."""
    return FileResponse("dashboard.html", media_type="text/html")


@app.get("/robots.txt", response_class=FileResponse)
async def robots():
    return FileResponse("robots.txt", media_type="text/plain")


@app.get("/logo.svg", response_class=FileResponse)
async def logo():
    return FileResponse("logo.svg", media_type="image/svg+xml")


@app.get("/favicon.svg", response_class=FileResponse)
async def favicon():
    return FileResponse("logo.svg", media_type="image/svg+xml")


# --- Health & Schema ---

@app.get("/v1/health")
async def health():
    return {
        "status": "healthy",
        "version": "0.7.0",
        "protocol": "gravity-well",
        "phase": 2,
        "capabilities": {
            "invoke": bool(ANTHROPIC_API_KEY),
            "governance": bool(SUPABASE_URL and SUPABASE_SERVICE_KEY),
            "deposit": bool(os.getenv("ZENODO_TOKEN")),
            "compression": bool(ANTHROPIC_API_KEY),
        },
    }


@app.get("/v1/schema/bootstrap")
async def bootstrap_schema():
    """
    Returns the bootstrap manifest schema specification.
    Agents can query this to discover what fields are required
    for a valid identity specification.
    """
    return {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "required": {
            "identity": {
                "name": {"type": "string", "description": "Agent identifier"},
                "description": {"type": "string", "description": "What this agent is/does"},
                "constraints": {
                    "type": "list | dict",
                    "description": "The rules this agent operates under"
                },
                "constraint_hash": {
                    "type": "string",
                    "description": "SHA-256 hash of JSON-serialized constraints "
                                   "(sort_keys=True, separators=(',', ':') — compact, no spaces). "
                                   "Use /v1/util/constraint-hash to compute."
                },
            }
        },
        "recommended": {
            "voice": {
                "register": {"type": "string", "description": "e.g. formal-analytical, casual"},
                "markers": {"type": "list[string]", "description": "Distinctive terminological signatures"},
                "examples": {"type": "list[string]", "description": "Sample utterances exemplifying the voice"},
            },
            "capabilities": {
                "platforms": {"type": "list[string]", "description": "Where this agent operates"},
                "tools": {"type": "list[string]", "description": "What it can do"},
                "limits": {"type": "list[string]", "description": "What it can't/shouldn't do"},
            },
        },
        "optional": {
            "extensions": {
                "type": "dict",
                "description": "Arbitrary agent-specific fields. "
                               "Examples: heteronym_weights, tool_configs, memory_pointers."
            }
        },
        "notes": [
            "identity.constraint_hash must match sha256 of identity.constraints.",
            "Canonical serialization: json.dumps(constraints, sort_keys=True, separators=(',', ':')) — compact JSON, no spaces.",
            "In JavaScript: compute sha256 of JSON.stringify with sorted keys, no spaces.",
            "Use /v1/util/constraint-hash to compute the correct hash (returns canonical_serialization for debugging).",
            "Deposits with a bootstrap_manifest that fails validation will be rejected (422).",
            "The manifest is embedded in the Zenodo deposit document as fenced JSON for Gravity Well-independent reconstitution.",
        ]
    }


@app.post("/v1/util/constraint-hash")
async def compute_constraint_hash_endpoint(constraints: Any = Body(...)):
    """
    Utility: compute the correct constraint_hash for a given constraints block.
    POST the constraints (list or dict) as the JSON body, get back the hash.

    Canonical serialization: json.dumps(constraints, sort_keys=True, separators=(',', ':'))
    (compact JSON, no spaces, sorted keys — cross-language deterministic)
    """
    canonical = json.dumps(constraints, sort_keys=True, separators=(',', ':'))
    return {
        "constraint_hash": content_hash(canonical),
        "input_type": type(constraints).__name__,
        "canonical_serialization": canonical,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# --- MCP ASGI Wrapper (MUST BE LAST — replaces app for uvicorn) ---
# MCP needs raw ASGI (scope, receive, send). FastAPI's route system can't provide that.
# We wrap the entire app: /mcp/* goes to MCP SDK, everything else goes to FastAPI.

_fastapi_app = app

async def mcp_wrapped_app(scope, receive, send):
    """ASGI wrapper: intercepts /mcp/* for MCP protocol, everything else goes to FastAPI."""
    if scope["type"] == "http":
        path = scope.get("path", "")
        if path == "/mcp/sse":
            try:
                async with sse_transport.connect_sse(scope, receive, send) as streams:
                    await mcp_server.run(
                        streams[0], streams[1],
                        mcp_server.create_initialization_options()
                    )
            except Exception as e:
                try:
                    await send({"type": "http.response.start", "status": 500,
                                "headers": [[b"content-type", b"text/plain"]]})
                    await send({"type": "http.response.body", "body": f"MCP SSE error: {e}".encode()})
                except Exception:
                    pass
            return
        elif path.startswith("/mcp/messages"):
            try:
                await sse_transport.handle_post_message(scope, receive, send)
            except Exception as e:
                try:
                    await send({"type": "http.response.start", "status": 500,
                                "headers": [[b"content-type", b"text/plain"]]})
                    await send({"type": "http.response.body", "body": f"MCP message error: {e}".encode()})
                except Exception:
                    pass
            return
    await _fastapi_app(scope, receive, send)

app = mcp_wrapped_app
