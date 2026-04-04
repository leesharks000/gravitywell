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

from sqlalchemy import create_engine, Column, String, DateTime, Float, JSON, Text, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

import httpx

# --- App ---

app = FastAPI(
    title="Gravity Well Protocol",
    description="Compression, wrapping, and anchoring microservice for durable provenance chains",
    version="0.4.1"
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
    """Output of drift detection comparison."""
    chain_id: str
    current_hash: str
    archived_hash: Optional[str]
    match: bool
    drift_fields: List[str]  # which fields changed
    archived_version: Optional[int]


class DriftRequest(BaseModel):
    """Input for drift detection."""
    current_manifest: Dict[str, Any]


# === Core Functions ===

def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def calculate_gamma(content: str) -> float:
    """PLACEHOLDER heuristic. Marker for where real analysis goes."""
    score = 0.0
    markers = ["##", "|", "```", "doi:", "http", "archive", "provenance"]
    score += min(sum(0.1 for m in markers if m in content.lower()), 0.5)
    wc = len(content.split())
    if wc > 100: score += 0.2
    if wc > 500: score += 0.1
    return round(min(score, 1.0), 3)


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
| Protocol | Gravity Well v0.4.1 |

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


def auto_generate_narrative(objects: list, chain_label: str) -> str:
    """
    PLACEHOLDER — Auto-generate narrative compression.

    This is where the real product lives. Future versions will use
    AI-mediated compression (Assembly Chorus methodology, operative
    semiotics, etc.) to produce summaries that survive the summarizer layer.

    For now: structural summary only.
    """
    content_types = {}
    platforms = set()
    total_words = 0

    for obj in objects:
        ct = obj.content_type
        content_types[ct] = content_types.get(ct, 0) + 1
        if obj.platform_source:
            platforms.add(obj.platform_source)
        total_words += len(obj.content.split())

    type_summary = ", ".join(f"{count} {ct}" for ct, count in content_types.items())
    platform_summary = ", ".join(platforms) if platforms else "direct capture"
    max_depth = max((obj.thread_depth for obj in objects), default=0)

    return (
        f"Structural summary for {chain_label}: "
        f"{len(objects)} objects captured ({type_summary}) "
        f"from {platform_summary}. "
        f"Total corpus: ~{total_words} words across {max_depth + 1} thread depth levels. "
        f"[PLACEHOLDER: This summary will be replaced by AI-mediated narrative compression "
        f"in production — the compression layer is the product.]"
    )


# === Zenodo Integration ===

async def zenodo_first_deposit(content: str, metadata: dict) -> dict:
    """Create a new Zenodo record (first version in a chain)."""
    token = os.getenv("ZENODO_TOKEN")
    if not token:
        return {"status": "skipped", "error": "ZENODO_TOKEN not configured"}

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


async def zenodo_new_version(latest_record_id: str, content: str, metadata: dict) -> dict:
    """Create a new version of an existing Zenodo record."""
    token = os.getenv("ZENODO_TOKEN")
    if not token:
        return {"status": "skipped", "error": "ZENODO_TOKEN not configured"}

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
    db.add(ApiKey(id=key_id, key_hash=hash_key(raw_key), label=label or f"key-{key_id[:8]}", is_active="true"))
    db.commit()
    return {"key_id": key_id, "api_key": raw_key, "label": label,
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
        narrative = auto_generate_narrative(objects, chain.label)

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
        result = await zenodo_new_version(chain.latest_record_id, doc, zen_meta)
    else:
        # First deposit in this chain
        result = await zenodo_first_deposit(doc, zen_meta)

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

    # Field-level diff
    drift_fields = []
    archived = latest.bootstrap_manifest
    all_keys = set(list(request.current_manifest.keys()) + list(archived.keys()))
    for key in sorted(all_keys):
        current_val = request.current_manifest.get(key)
        archived_val = archived.get(key)
        if current_val != archived_val:
            drift_fields.append(key)

    return DriftReport(
        chain_id=chain_id, current_hash=current_hash,
        archived_hash=archived_hash,
        match=(current_hash == archived_hash),
        drift_fields=drift_fields,
        archived_version=latest.version
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


# --- Health & Schema ---

@app.get("/v1/health")
async def health():
    return {"status": "healthy", "version": "0.4.0", "protocol": "gravity-well", "phase": 0}


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
