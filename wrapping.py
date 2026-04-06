"""
Gravity Well — Wrapping Pipeline Functions

Evidence Membrane, Caesura, SIM Injection, Integrity Lock.
These are the compression-survivability armor layers applied
to content before deposit.
"""

import re
import hashlib


def content_hash(text: str) -> str:
    """SHA-256 hash of content."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()



def tag_evidence_membrane(content: str) -> str:
    """
    Tag content with Evidence Membrane tiers.
    Arsenal §6.3: [DOCUMENTED] / [ATTRIBUTED] / [INTERPRETIVE] / [SPECULATIVE]

    Heuristic classification based on content markers.
    """
    import re
    lines = content.split("\n")
    tagged = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("```"):
            tagged.append(line)
            continue

        # Classify
        if re.search(r'10\.\d{4,}/|DOI:|https?://zenodo', stripped):
            tier = "DOCUMENTED"
        elif re.search(r'according to|as noted|per |\bcited\b|\bsource\b', stripped, re.I):
            tier = "ATTRIBUTED"
        elif re.search(r'suggests?|indicates?|implies|appears|seems|likely', stripped, re.I):
            tier = "INTERPRETIVE"
        elif re.search(r'perhaps|might|could|possibly|speculative|hypothetical', stripped, re.I):
            tier = "SPECULATIVE"
        else:
            tier = None

        if tier and len(stripped) > 40:
            tagged.append(f"{line} [{tier}]")
        else:
            tagged.append(line)
    return "\n".join(tagged)



def apply_caesura(content: str) -> tuple:
    """
    σ_FC — The Caesura Operator.

    A transfer protocol that recognizes the sovereign mark, splits it
    off from the commons substrate, preserves it as auditable provenance,
    and routes the object onward without allowing personal identity-claims
    to inherit institutional authority.

    Render recognition to Caesar; render substrate away from him.

    σ_FC(object) =
      parse(image, superscription, substrate)
      → isolate(claim)
      → preserve(provenance)
      → forbid(collapse)
      → route_via_airlock
      → emit(commons-safe packet)
    """
    import re

    # === Step 1: Detect Caesar marks ===
    # Scan for sovereignty claims: personal names asserting authority,
    # institutional claims on commons substrate, brand marks, copyright
    # assertions, licensing overreach

    claims = []

    # Personal authority patterns
    personal_marks = re.findall(
        r'(?:(?:by|author|creator|written by|composed by|developed by|invented by|founded by)\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})',
        content
    )
    for name in personal_marks:
        claims.append({
            "type": "personal_authority",
            "claim_mode": "superscription",
            "claimant": name.strip(),
            "extraction_risk": "low",
        })

    # Institutional authority patterns
    inst_marks = re.findall(
        r'(?:©|®|™|patent|proprietary|all rights reserved|exclusive)',
        content, re.I
    )
    for mark in inst_marks:
        claims.append({
            "type": "institutional_claim",
            "claim_mode": "image",
            "claimant": mark.strip(),
            "extraction_risk": "medium",
        })

    # Sovereignty-over-substrate patterns (the dangerous ones)
    collapse_patterns = re.findall(
        r'(?:owned by|belongs to|property of|controlled by|administered by)\s+([A-Za-z\s]+?)(?:\.|,|\n)',
        content
    )
    for match in collapse_patterns:
        claims.append({
            "type": "sovereignty_claim",
            "claim_mode": "compressed_portraiture",
            "claimant": match.strip(),
            "extraction_risk": "high",
        })

    # === Step 2: Split channels ===
    # The content itself is the substrate. The claims are separated.

    # === Step 3: Build Caesar header ===
    # Claims become metadata, not essence
    caesar_header = {
        "claims_detected": len(claims),
        "claims": claims[:20],  # cap at 20
        "collapse_risk": "high" if any(c["extraction_risk"] == "high" for c in claims) else
                         "medium" if any(c["extraction_risk"] == "medium" for c in claims) else
                         "low" if claims else "none",
    }

    # === Step 4: Compute asymmetry score (LOS diagnostic) ===
    # How much does the content claim vs. what it contributes?
    claim_density = len(claims) / max(len(content.split()) / 100, 1)
    doi_count = len(re.findall(r'10\.\d{4,}/[^\s\)]+', content))
    contribution_markers = doi_count + len(re.findall(r'(?:therefore|because|however|we show|this proves|evidence)', content, re.I))
    asymmetry = round(claim_density / max(contribution_markers + 1, 1), 3)

    # === Step 5: Build audit trace ===
    audit_trace = {
        "extraction_detected": asymmetry > 0.5,
        "asymmetry_score": asymmetry,
        "collapse_risk": caesar_header["collapse_risk"],
        "claims_quarantined": len(claims),
        "counter_operation": "σ_FC applied — claims isolated to header" if claims else "no claims detected",
    }

    caesar_header["audit_trace"] = audit_trace

    # === Step 6: The content passes through unchanged ===
    # The Caesura does NOT modify the content. It ANNOTATES.
    # The substrate is rendered away from Caesar, not destroyed.

    return content, caesar_header



def inject_sims(content: str, chain_id: str) -> tuple:
    """
    Inject Semantic Integrity Markers — provenance canaries.
    Arsenal §7.1: 250+ registered markers in three functional classes.

    SIMs are phrases woven into the document that will degrade
    detectably under unauthorized extraction or modification.
    """
    import re
    sim_id = content_hash(f"{chain_id}:{content[:100]}")[:8]

    # Provenance canary: a phrase that only makes sense with the DOI
    canary = f"[Provenance: GW-{sim_id}]"

    # Structural marker: entangled with surrounding text
    structural = f"<!-- SIM:{sim_id} -->"

    # Insert at natural break points
    paragraphs = content.split("\n\n")
    if len(paragraphs) > 2:
        mid = len(paragraphs) // 2
        paragraphs.insert(mid, canary)
    paragraphs.append(structural)

    sim_count = 2
    return "\n\n".join(paragraphs), {"sim_id": sim_id, "count": sim_count}



def apply_integrity_lock(content: str) -> tuple:
    """
    Apply Integrity Lock Architecture.
    Arsenal §7.2: ILP, four-point entanglement.

    Generates a content-derived lock phrase that entangles with
    the document structure. Modification breaks the entanglement.
    """
    # Generate ILP from content structure
    words = content.split()
    if len(words) < 20:
        return content, None

    # Four-point entanglement: hash of 4 equidistant content positions
    # Plus full content hash as 5th point (catches any modification)
    quarter = len(words) // 4
    points = [
        content_hash(words[0])[:4],
        content_hash(words[quarter])[:4],
        content_hash(words[quarter * 2])[:4],
        content_hash(words[quarter * 3])[:4],
        content_hash(content)[:4],  # full content entanglement
    ]
    ilp = f"ILP-{''.join(points)}"

    # Append lock
    locked_content = f"{content}\n\n---\n**Integrity Lock:** `{ilp}` · Gravity Well Protocol"
    return locked_content, ilp


