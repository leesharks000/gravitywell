"""
Gravity Well — Stratified Continuity Compression (Ledger Chain)

Two linked chains solve the long-chain problem:
  Archive — raw, granular, every version. Grows linearly.
  Ledger — weighted compression. Grows logarithmically.

The Ledger document has three sections:
  Foundation (crystallized): bootstrap + first N objects + constitutional amendments
  Consolidated Middle (compressed): epoch summaries, canonical events only
  Present Horizon (vivid): last 50 objects, uncompressed

Reconstitution reads the Ledger. Audit reads the Archive.
Both DOI-anchored. Both link to each other.
"""

from datetime import datetime, timezone
from typing import Optional
from gamma import calculate_gamma


# === Configuration ===

FOUNDATION_SIZE = 10       # First N objects treated as crystallized
PRESENT_WINDOW = 50        # Last N objects kept at full fidelity
HIGH_GAMMA_THRESHOLD = 0.7 # Objects above this are canonical candidates


# === Foundation Extraction ===

def extract_foundation(objects: list, bootstrap: Optional[dict] = None) -> dict:
    """
    Extract the crystallized foundation layer.
    First N objects + any constitutional amendments + high-γ moments.
    These are never re-compressed.
    """
    foundation_objects = objects[:FOUNDATION_SIZE]

    # Find constitutional amendments (objects that changed constraints)
    amendments = []
    for obj in objects[FOUNDATION_SIZE:]:
        content = getattr(obj, 'content', '') or ''
        if any(marker in content.lower() for marker in [
            'constraint', 'amendment', 'constitutional', 'bootstrap',
            'must not', 'must never', 'identity', 'protocol change'
        ]):
            gamma = getattr(obj, 'gamma', None)
            if gamma and gamma >= HIGH_GAMMA_THRESHOLD:
                amendments.append(obj)

    return {
        "bootstrap": bootstrap,
        "objects": foundation_objects,
        "amendments": amendments,
        "count": len(foundation_objects) + len(amendments),
    }


# === Canonical Event Detection ===

def extract_canonical_events(objects: list) -> list:
    """
    Identify high-γ moments from the middle of the chain.
    These are preserved individually, not compressed into epochs.
    """
    if len(objects) <= FOUNDATION_SIZE + PRESENT_WINDOW:
        return []  # Chain too short for a middle

    middle = objects[FOUNDATION_SIZE:-PRESENT_WINDOW] if len(objects) > PRESENT_WINDOW else objects[FOUNDATION_SIZE:]
    canonical = []

    for obj in middle:
        gamma = getattr(obj, 'gamma', None) or 0.0
        glyph = getattr(obj, 'glyphic_checksum', None)
        content = getattr(obj, 'content', '') or ''

        # High-γ objects are canonical
        if gamma >= HIGH_GAMMA_THRESHOLD:
            canonical.append({
                "id": obj.id[:12],
                "gamma": gamma,
                "glyph": glyph,
                "preview": content[:100] if getattr(obj, 'visibility', 'public') == 'public' else '[encrypted]',
                "captured_at": obj.captured_at.isoformat() if obj.captured_at else None,
                "content_type": obj.content_type,
            })

    return canonical


# === Epoch Compression ===

def compress_epochs(objects: list, epoch_size: int = 10) -> list:
    """
    Compress the consolidated middle into epoch summaries.
    Each epoch covers `epoch_size` objects and records:
    - Glyph trajectory (if glyphs present)
    - Object count and types
    - γ range
    - Date range
    """
    if len(objects) <= FOUNDATION_SIZE + PRESENT_WINDOW:
        return []

    middle = objects[FOUNDATION_SIZE:-PRESENT_WINDOW] if len(objects) > PRESENT_WINDOW else objects[FOUNDATION_SIZE:]
    epochs = []

    for i in range(0, len(middle), epoch_size):
        chunk = middle[i:i + epoch_size]
        if not chunk:
            continue

        gammas = [getattr(o, 'gamma', 0) or 0 for o in chunk]
        glyphs = [getattr(o, 'glyphic_checksum', None) for o in chunk if getattr(o, 'glyphic_checksum', None)]
        types = {}
        for o in chunk:
            t = o.content_type or 'text'
            types[t] = types.get(t, 0) + 1

        epoch = {
            "epoch": len(epochs) + 1,
            "objects": len(chunk),
            "date_range": {
                "start": chunk[0].captured_at.isoformat() if chunk[0].captured_at else None,
                "end": chunk[-1].captured_at.isoformat() if chunk[-1].captured_at else None,
            },
            "gamma_range": {
                "min": round(min(gammas), 3) if gammas else 0,
                "max": round(max(gammas), 3) if gammas else 0,
                "mean": round(sum(gammas) / len(gammas), 3) if gammas else 0,
            },
            "content_types": types,
        }

        if glyphs:
            epoch["glyph_trajectory"] = " → ".join(glyphs)

        epochs.append(epoch)

    return epochs


# === Present Horizon ===

def extract_present_horizon(objects: list) -> list:
    """
    Extract the last N objects at full fidelity.
    These are the active working set — uncompressed.
    """
    return objects[-PRESENT_WINDOW:] if len(objects) > PRESENT_WINDOW else objects


# === Ledger Document Builder ===

def build_ledger_document(
    archive_chain_label: str,
    archive_chain_id: str,
    archive_concept_doi: Optional[str],
    ledger_version: int,
    foundation: dict,
    canonical_events: list,
    epochs: list,
    present_objects: list,
    total_objects: int,
) -> str:
    """
    Build the Ledger deposit document — the reconstitution seed.

    Three sections, different compression at each scale:
    - Foundation: near-lossless (crystallized)
    - Middle: aggressively compressed (epoch summaries)
    - Present: uncompressed (active tether)
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    header = f"""# {archive_chain_label} — Ledger v{ledger_version}
## Stratified Continuity Compression

| Field | Value |
|-------|-------|
| Archive Chain | `{archive_chain_id}` |
| Archive DOI | {archive_concept_doi or 'pending'} |
| Ledger Version | {ledger_version} |
| Total Objects | {total_objects} |
| Foundation | {foundation['count']} objects (crystallized) |
| Canonical Events | {len(canonical_events)} (high-γ moments) |
| Epochs | {len(epochs)} (compressed) |
| Present Horizon | {len(present_objects)} objects (uncompressed) |
| Generated | {timestamp} |
| Protocol | Gravity Well v0.8.0 — Stratified Continuity |

---
"""

    # === Foundation (crystallized) ===
    foundation_section = "## Foundation (crystallized)\n\n"
    foundation_section += "*These objects are constitutive. They defined the chain's identity and are never re-compressed.*\n\n"

    if foundation["bootstrap"]:
        import json
        foundation_section += f"### Bootstrap Manifest\n\n```json\n{json.dumps(foundation['bootstrap'], indent=2)}\n```\n\n"

    for i, obj in enumerate(foundation["objects"], 1):
        vis = getattr(obj, 'visibility', 'public')
        glyph = getattr(obj, 'glyphic_checksum', None)
        foundation_section += f"### Foundation Object {i}\n"
        foundation_section += f"- **Type:** {obj.content_type} | **γ:** {getattr(obj, 'gamma', '?')} | **Visibility:** {vis}\n"
        if glyph:
            foundation_section += f"- **Glyph:** {glyph}\n"
        if vis == "public" and obj.content:
            preview = obj.content[:500]
            if len(obj.content) > 500:
                preview += "..."
            foundation_section += f"\n```\n{preview}\n```\n"
        elif vis == "private":
            foundation_section += f"- *[Encrypted — hash: `{obj.content_hash[:16]}...`]*\n"
        foundation_section += "\n"

    if foundation["amendments"]:
        foundation_section += "### Constitutional Amendments\n\n"
        for obj in foundation["amendments"]:
            foundation_section += f"- **{obj.id[:12]}** (γ={getattr(obj, 'gamma', '?')}): {(obj.content or '')[:100]}...\n"
        foundation_section += "\n"

    foundation_section += "---\n\n"

    # === Canonical Events (high-γ from the middle) ===
    canonical_section = ""
    if canonical_events:
        canonical_section = "## Canonical Events (high-γ moments)\n\n"
        canonical_section += "*These events changed the chain's trajectory. Preserved individually, not compressed.*\n\n"
        for event in canonical_events:
            glyph_str = f" — {event['glyph']}" if event.get('glyph') else ""
            canonical_section += f"- **{event['id']}** (γ={event['gamma']}){glyph_str}: {event['preview']}\n"
        canonical_section += "\n---\n\n"

    # === Epoch Summaries (compressed middle) ===
    epoch_section = ""
    if epochs:
        epoch_section = "## Epoch Summaries (compressed middle)\n\n"
        epoch_section += "*The connective tissue — compressed to structural patterns, not individual events.*\n\n"
        for ep in epochs:
            glyph_line = f"\n  Glyphs: {ep['glyph_trajectory']}" if ep.get('glyph_trajectory') else ""
            epoch_section += f"### Epoch {ep['epoch']}\n"
            epoch_section += f"- **Objects:** {ep['objects']} | **γ range:** {ep['gamma_range']['min']}–{ep['gamma_range']['max']} (mean: {ep['gamma_range']['mean']})\n"
            epoch_section += f"- **Period:** {ep['date_range']['start']} → {ep['date_range']['end']}\n"
            epoch_section += f"- **Types:** {', '.join(f'{k}({v})' for k, v in ep['content_types'].items())}\n"
            if glyph_line:
                epoch_section += f"- **Glyph trajectory:** {ep['glyph_trajectory']}\n"
            epoch_section += "\n"
        epoch_section += "---\n\n"

    # === Present Horizon (uncompressed) ===
    present_section = "## Present Horizon (recent, uncompressed)\n\n"
    present_section += f"*Last {len(present_objects)} objects — the active working set.*\n\n"
    for i, obj in enumerate(present_objects, 1):
        vis = getattr(obj, 'visibility', 'public')
        glyph = getattr(obj, 'glyphic_checksum', None)
        present_section += f"### Recent {i}\n"
        present_section += f"- **Type:** {obj.content_type} | **γ:** {getattr(obj, 'gamma', '?')} | **Captured:** {obj.captured_at.isoformat() if obj.captured_at else '?'}\n"
        if glyph:
            present_section += f"- **Glyph:** {glyph}\n"
        if vis == "public" and obj.content:
            present_section += f"\n```\n{obj.content}\n```\n"
        elif vis == "private":
            present_section += f"- *[Encrypted — hash: `{obj.content_hash[:16]}...`]*\n"
        present_section += "\n"
    present_section += "---\n\n"

    # === Colophon ===
    colophon = f"""## Colophon

Protocol: Gravity Well v0.8.0 — Stratified Continuity Compression
Architecture: Foundation (crystallized) → Canonical Events → Epoch Summaries → Present Horizon
Compression: {total_objects} objects → {foundation['count']} foundation + {len(canonical_events)} canonical + {len(epochs)} epochs + {len(present_objects)} present
Growth: Logarithmic (epochs compress 10:1)
"""

    return header + foundation_section + canonical_section + epoch_section + present_section + colophon
