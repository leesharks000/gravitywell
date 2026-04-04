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
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone
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
    version="0.6.0"
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
    A provenance chain = one concept DOI on Zenodo.
    Each agent, thread, or continuity stream gets one chain.
    Versions accumulate as deposits are made.
    """
    __tablename__ = "provenance_chains"
    id = Column(String, primary_key=True)
    label = Column(String, index=True)                # e.g. "crimsonhexagon-moltbook"
    concept_doi = Column(String, nullable=True)        # Zenodo concept DOI (set after first deposit)
    concept_record_id = Column(String, nullable=True)  # Zenodo concept record ID
    latest_record_id = Column(String, nullable=True)   # Latest published record ID (for newversion)
    latest_version = Column(Integer, default=0)
    api_key_id = Column(String, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_json = Column(JSON, default={})           # Chain-level metadata


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


class DepositRecord(Base):
    """
    Record of each Zenodo deposit (each version in a chain).
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


class CaptureResponse(BaseModel):
    object_id: str
    chain_id: str
    content_hash: str
    captured_at: datetime
    staged_count: int  # how many undeposited objects now in this chain


class ChainCreateRequest(BaseModel):
    """Create a new provenance chain (= future concept DOI)."""
    label: str = Field(..., min_length=1, max_length=200)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChainResponse(BaseModel):
    chain_id: str
    label: str
    concept_doi: Optional[str]
    latest_version: int
    staged_count: int


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
    severity: str = "none"  # none | low | medium | high | critical
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


def calculate_gamma(content: str) -> float:
    """
    Calculate compression-survival score (γ).
    High γ = content survives LLM summarization with referential integrity intact.
    Four-layer scoring: citation density, structural integrity, argument coherence, provenance markers.
    """
    import re
    if not content or len(content.strip()) < 10:
        return 0.0

    scores = []

    # Layer 1: Citation density (0.0-1.0) — DOI anchors, URLs, references per 1000 chars
    doi_count = len(re.findall(r'10\.\d{4,}/[^\s\)]+', content))
    url_count = len(re.findall(r'https?://[^\s\)]+', content))
    ref_density = (doi_count * 3 + url_count) / max(len(content) / 1000, 1)
    scores.append(("citation", min(ref_density * 0.3, 1.0)))

    # Layer 2: Structural integrity (0.0-1.0) — headers, tables, code, lists
    headers = len(re.findall(r'^#{1,6}\s', content, re.M))
    tables = content.count('|') // 3  # rough table row estimate
    code_blocks = len(re.findall(r'```', content)) // 2
    lists = len(re.findall(r'^\s*[-*]\s', content, re.M))
    struct_markers = headers + tables + code_blocks + lists
    struct_score = min(struct_markers / max(len(content.split('\n\n')), 1), 1.0)
    scores.append(("structure", struct_score))

    # Layer 3: Argument coherence (0.0-1.0) — discourse markers, paragraph density
    coherence_words = re.findall(r'\b(therefore|thus|because|however|consequently|furthermore|moreover|specifically|in particular|as a result|this means|it follows)\b', content.lower())
    paragraphs = max(len(content.split('\n\n')), 1)
    coherence = min(len(coherence_words) / paragraphs, 1.0)
    scores.append(("coherence", coherence))

    # Layer 4: Provenance markers (0.0-1.0) — dates, versions, hashes, author attribution
    has_date = 1.0 if re.search(r'\d{4}-\d{2}-\d{2}', content) else 0.0
    has_version = 1.0 if re.search(r'v\d+\.\d+', content, re.I) else 0.0
    has_hash = 1.0 if re.search(r'[a-f0-9]{32,}', content) else 0.0
    has_author = 1.0 if re.search(r'(author|creator|by\s+\w+|ORCID)', content, re.I) else 0.0
    prov_score = (has_date + has_version + has_hash + has_author) / 4
    scores.append(("provenance", prov_score))

    # Composite: weighted average
    weights = {"citation": 0.30, "structure": 0.25, "coherence": 0.25, "provenance": 0.20}
    gamma = sum(weights[name] * score for name, score in scores)

    # Bonus: length maturity (very short content penalized)
    wc = len(content.split())
    if wc < 50:
        gamma *= 0.5
    elif wc < 200:
        gamma *= 0.8

    return round(min(gamma, 1.0), 3)


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


def build_deposit_document(
    chain: ProvenanceChain,
    objects: list,
    version: int,
    narrative_summary: Optional[str],
    thb: Optional[dict],
    bootstrap_manifest: Optional[dict],
    deposit_metadata: dict,
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

    header = f"""# {chain.label} — v{version}
## Gravity Well Provenance Deposit

| Field | Value |
|-------|-------|
| Chain | `{chain.id}` |
| Version | {version} |
| Concept DOI | {chain.concept_doi or 'pending (first deposit)'} |
| Objects | {len(objects)} |
| Deposited | {timestamp} |
| Protocol | Gravity Well v0.6.0 |

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

    # Object manifest
    manifest_lines = ["## Provenance Chain Objects\n"]
    for i, obj in enumerate(objects, 1):
        manifest_lines.append(f"### Object {i}: {obj.external_id or obj.id[:12]}")
        manifest_lines.append(f"- **Type:** {obj.content_type}")
        manifest_lines.append(f"- **Source:** {obj.platform_source or 'direct'}")
        manifest_lines.append(f"- **Hash:** `{obj.content_hash[:16]}...`")
        manifest_lines.append(f"- **Captured:** {obj.captured_at.isoformat()}")
        if obj.parent_object_id:
            manifest_lines.append(f"- **Parent:** `{obj.parent_object_id[:12]}...`")
        manifest_lines.append(f"- **Thread depth:** {obj.thread_depth}")
        manifest_lines.append("")
        manifest_lines.append(f"```\n{obj.content}\n```\n")
        manifest_lines.append("---\n")

    manifest = "\n".join(manifest_lines)

    # Colophon
    colophon = f"""## Colophon

This deposit was created by the Gravity Well Protocol — a compression, wrapping,
and anchoring microservice for durable provenance chains.

This document is self-contained. If retrieved from Zenodo without access to the
Gravity Well API, the Bootstrap Manifest (if present) contains the identity
specification, the Tether Handoff Block contains operational state, the Narrative
Compression contains the retrieval-layer summary, and the Provenance Chain Objects
contain the full evidence chain. Together they constitute a reconstitution seed.

Each object is hashed (SHA-256) and threaded. The chain is anchored via DOI.
"""

    return header + bootstrap_section + narrative_section + thb_section + manifest + colophon


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
            creators = metadata.get("creators", [{"name": "Sharks, Lee"}])
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
            creators = metadata.get("creators", [{"name": "Sharks, Lee"}])
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
    """Create a new provenance chain. Each chain becomes one concept DOI on Zenodo."""
    chain_id = str(uuid.uuid4())
    chain = ProvenanceChain(
        id=chain_id, label=request.label, api_key_id=api_key_id,
        metadata_json=request.metadata
    )
    db.add(chain)
    db.commit()
    return ChainResponse(
        chain_id=chain_id, label=request.label,
        concept_doi=None, latest_version=0, staged_count=0
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
        staged_count=staged
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
    obj = StagedObject(
        id=obj_id, chain_id=request.chain_id,
        content_hash=content_hash(request.content),
        content=request.content, content_preview=request.content[:200],
        content_type=request.content_type, metadata_json=request.metadata,
        parent_object_id=request.parent_object_id, thread_depth=thread_depth,
        platform_source=request.platform_source, external_id=request.external_id,
        gamma=calculate_gamma(request.content),
    )
    db.add(obj)
    db.commit()

    staged_count = db.query(StagedObject).filter(
        StagedObject.chain_id == request.chain_id, StagedObject.deposited == "false"
    ).count()

    return CaptureResponse(
        object_id=obj_id, chain_id=request.chain_id,
        content_hash=obj.content_hash, captured_at=obj.captured_at,
        staged_count=staged_count
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

    # Validate bootstrap manifest if provided
    if request.bootstrap_manifest:
        validation_errors = validate_bootstrap_manifest(request.bootstrap_manifest)
        if validation_errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Bootstrap manifest validation failed.",
                    "errors": validation_errors,
                    "schema_version": BOOTSTRAP_SCHEMA_VERSION,
                    "hint": "Required: identity.name, identity.description, "
                            "identity.constraints, identity.constraint_hash. "
                            "Use /v1/schema/bootstrap for full specification."
                }
            )

    # Version
    version = chain.latest_version + 1

    # Compression layer
    narrative = request.narrative_summary
    if not narrative and request.auto_compress:
        narrative = await auto_generate_narrative(objects, chain.label)

    # Build deposit document
    doc = build_deposit_document(
        chain=chain, objects=objects, version=version,
        narrative_summary=narrative, thb=request.tether_handoff_block,
        bootstrap_manifest=request.bootstrap_manifest,
        deposit_metadata=request.deposit_metadata,
    )

    # Hash bootstrap manifest for drift detection
    bootstrap_hash = None
    if request.bootstrap_manifest:
        bootstrap_hash = content_hash(json.dumps(request.bootstrap_manifest, sort_keys=True, separators=(',', ':')))

    # Anchor to Zenodo
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
        "filename": f"{chain.label.replace(' ', '_')}_v{version}.md",
        "keywords": ["gravity-well", "provenance", "continuity", chain.label],
        "creators": request.deposit_metadata.get("creators", [{"name": "Sharks, Lee"}]),
    }

    if chain.latest_record_id:
        # New version of existing record
        user_token = get_zenodo_token_for_key(api_key_id, db)
        result = await zenodo_new_version(chain.latest_record_id, doc, zen_meta, zenodo_token=user_token)
    else:
        # First deposit in this chain
        user_token = get_zenodo_token_for_key(api_key_id, db)
        result = await zenodo_first_deposit(doc, zen_meta, zenodo_token=user_token)

    # Record the deposit
    deposit_id = str(uuid.uuid4())
    deposit_rec = DepositRecord(
        id=deposit_id, chain_id=chain.id, version=version,
        doi=result.get("doi"), zenodo_record_id=result.get("record_id"),
        object_count=len(objects), narrative_summary=narrative,
        tether_handoff_block=request.tether_handoff_block,
        bootstrap_manifest=request.bootstrap_manifest,
        bootstrap_hash=bootstrap_hash,
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

        # Mark objects as deposited
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

    # Field-level diff with details
    drift_fields = []
    field_details = []
    archived = latest.bootstrap_manifest
    all_keys = set(list(request.current_manifest.keys()) + list(archived.keys()))

    # Classify fields by criticality
    critical_fields = {"identity", "constraints", "constraint_hash", "name"}
    high_fields = {"description", "psychic_voltage", "shadow_references"}

    for key in sorted(all_keys):
        current_val = request.current_manifest.get(key)
        archived_val = archived.get(key)
        if current_val != archived_val:
            drift_fields.append(key)
            detail = {"field": key, "changed": True}
            if key in critical_fields:
                detail["severity"] = "critical"
            elif key in high_fields:
                detail["severity"] = "high"
            else:
                detail["severity"] = "low"

            if archived_val is None:
                detail["type"] = "added"
                detail["description"] = f"Field '{key}' was added (not in archived version)"
            elif current_val is None:
                detail["type"] = "removed"
                detail["description"] = f"Field '{key}' was removed from current manifest"
            else:
                detail["type"] = "modified"
                detail["description"] = f"Field '{key}' changed from archived version"
            field_details.append(detail)

    # Determine overall severity
    if not drift_fields:
        severity = "none"
    elif any(f in critical_fields for f in drift_fields):
        severity = "critical"
    elif any(f in high_fields for f in drift_fields):
        severity = "high"
    elif len(drift_fields) > 3:
        severity = "medium"
    else:
        severity = "low"

    # Generate narrative
    if not drift_fields:
        narrative = f"No drift detected. Chain {chain_id} is structurally identical to archived version {latest.version}. Constitutional integrity confirmed."
    else:
        critical_drifts = [d for d in field_details if d["severity"] == "critical"]
        narrative_parts = [
            f"Drift detected in chain {chain_id}: {len(drift_fields)} field(s) changed from archived version {latest.version}.",
            f"Severity: {severity.upper()}.",
        ]
        if critical_drifts:
            narrative_parts.append(f"CRITICAL: {', '.join(d['field'] for d in critical_drifts)} — constitutional constraint fields have been modified.")
        narrative_parts.append(f"Changed fields: {', '.join(drift_fields)}.")
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
    db: Session = Depends(get_db)
):
    """
    Invoke an LLM within a room's physics and mantle.
    Every invocation is provenance-tracked. Response gets a γ score.
    Optionally captures the response to a provenance chain.
    """
    if not ANTHROPIC_API_KEY:
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
                    "x-api-key": ANTHROPIC_API_KEY,
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

    gamma = calculate_gamma(content)
    wc = len(content.split())

    return {
        "gamma": gamma,
        "word_count": wc,
        "survival_tier": "critical" if gamma > 0.7 else "high" if gamma > 0.5 else "medium" if gamma > 0.3 else "low",
        "recommendation": "Content is compression-survivable" if gamma > 0.5 else "Consider adding structural markers, citations, and provenance references",
        "protocol": "gravity-well",
        "note": "Full compression analysis with AI-mediated scoring available with API key via /v1/invoke",
    }


# --- Health & Schema ---

@app.get("/v1/health")
async def health():
    return {
        "status": "healthy",
        "version": "0.6.0",
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
