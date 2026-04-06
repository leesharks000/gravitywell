"""
Gravity Well — γ Compression-Survival Scorer

Surface layer: citation density, structural integrity, argument coherence, provenance markers
Depth layer: information density, redundancy, argument chain, citation integration, vocabulary specificity

Used for:
  - Public γ scoring endpoint (/v1/gamma)
  - Deposit wrapping pipeline (score content before anchoring)
  - Glyph-derived scoring (score structural topology of encrypted content)
"""

import re
from collections import Counter
from typing import Optional


def calculate_gamma(content: str = None, glyph: str = None, return_detail: bool = False):
    """
    Calculate compression-survival score (γ).
    High γ = content survives LLM summarization with referential integrity intact.

    Two input paths:
    1. Content (plaintext): full surface + depth analysis
    2. Glyph (emoji sequence): structural topology scoring for encrypted content

    Surface layer (4 scores): citation density, structural integrity, argument coherence, provenance markers.
    Depth layer (5 scores): information density, redundancy, argument chain depth, citation integration, vocabulary specificity.
    """
    import re
    from collections import Counter

    # === GLYPH-BASED SCORING (zero-knowledge γ) ===
    if glyph and (not content or content.startswith('[GW-AES256GCM]')):
        # Score from structural topology — the glyph IS the signal
        clusters = [c.strip() for c in glyph.split('→') if c.strip()]
        num_clusters = len(clusters)

        # Count actual emoji (rough: non-ASCII, non-arrow, non-space characters)
        import unicodedata
        emoji_chars = [c for c in glyph if unicodedata.category(c).startswith(('So', 'Sk', 'Sm'))]
        num_emoji = len(emoji_chars)

        # Density: emoji per cluster
        density = num_emoji / max(num_clusters, 1)

        # Structural scores from glyph characteristics
        subscores = {
            "citation": min(num_clusters * 0.1, 1.0),        # more clusters = more structured
            "structure": min(density * 0.3, 1.0),             # denser clusters = more structural
            "coherence": min(glyph.count('→') * 0.15, 1.0),  # more transitions = more argument
            "provenance": 0.5 if num_clusters > 3 else 0.25,  # glyphed content has provenance by definition
        }

        depth = {
            "information_density": min(len(set(emoji_chars)) / max(num_emoji, 1) * 1.5, 1.0),
            "redundancy": 1.0 - min(len(set(emoji_chars)) / max(num_emoji, 1), 1.0),
            "argument_chain": min(num_clusters / 5, 1.0),
            "citation_integration": 0.5,  # can't measure from glyph alone
            "vocabulary_specificity": min(len(set(emoji_chars)) / 10, 1.0),
        }

        weights = {"citation": 0.30, "structure": 0.25, "coherence": 0.25, "provenance": 0.20}
        gamma = sum(weights[k] * subscores[k] for k in weights)

        depth_weights = {"information_density": 0.30, "redundancy": 0.10, "argument_chain": 0.25,
                         "citation_integration": 0.20, "vocabulary_specificity": 0.15}
        depth["composite"] = round(sum(depth_weights[k] * depth[k] for k in depth_weights), 3)

        gamma = round(min(gamma, 1.0), 3)

        if return_detail:
            return {
                "gamma": gamma, "subscores": {k: round(v, 3) for k, v in subscores.items()},
                "depth": {k: round(v, 3) for k, v in depth.items()},
                "word_count": num_emoji, "penalty": "glyph-derived (zero-knowledge)",
                "survival_tier": "survives" if gamma >= 0.7 else "partial" if gamma >= 0.4 else "drowns",
                "unique_concepts": len(set(emoji_chars)), "paragraphs": num_clusters,
                "doi_count": 0, "connective_count": glyph.count('→'),
                "source": "glyphic_checksum",
            }
        return gamma

    # === CONTENT-BASED SCORING (standard path) ===
    if not content or len(content.strip()) < 10:
        if return_detail:
            return {"gamma": 0.0, "subscores": {}, "depth": {}, "penalty": "content too short"}
        return 0.0

    words = content.split()
    wc = len(words)
    lower_content = content.lower()
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    num_paragraphs = max(len(paragraphs), 1)
    subscores = {}

    # === SURFACE LAYER (original 4 scores) ===

    # Layer 1: Citation density (0.0-1.0)
    doi_matches = re.findall(r'10\.\d{4,}/[^\s\)]+', content)
    doi_count = len(doi_matches)
    url_count = len(re.findall(r'https?://[^\s\)]+', content))
    ref_density = (doi_count * 3 + url_count) / max(wc / 200, 1)
    subscores["citation"] = round(min(ref_density * 0.3, 1.0), 3)

    # Layer 2: Structural integrity (0.0-1.0)
    headers = len(re.findall(r'^#{1,6}\s', content, re.M))
    tables = content.count('|') // 3
    code_blocks = len(re.findall(r'```', content)) // 2
    lists = len(re.findall(r'^\s*[-*]\s', content, re.M))
    struct_markers = headers + tables + code_blocks + lists
    subscores["structure"] = round(min(struct_markers / num_paragraphs, 1.0), 3)

    # Layer 3: Argument coherence (0.0-1.0)
    CONNECTIVES = r'\b(therefore|thus|because|however|consequently|furthermore|moreover|specifically|in particular|as a result|this means|it follows|which means|in contrast|nevertheless|accordingly)\b'
    coherence_matches = re.findall(CONNECTIVES, lower_content)
    subscores["coherence"] = round(min(len(coherence_matches) / num_paragraphs, 1.0), 3)

    # Layer 4: Provenance markers (0.0-1.0)
    has_date = 1.0 if re.search(r'\d{4}-\d{2}-\d{2}|\b20[12]\d\b', content) else 0.0
    has_version = 1.0 if re.search(r'v\d+\.\d+|version\s+\d', content, re.I) else 0.0
    has_hash = 1.0 if re.search(r'[a-f0-9]{16,}', content) else 0.0
    has_author = 1.0 if re.search(r'(author|creator|by\s+\w+|ORCID|©)', content, re.I) else 0.0
    subscores["provenance"] = round((has_date + has_version + has_hash + has_author) / 4, 3)

    # === DEPTH LAYER (5 new scores) ===
    depth = {}

    # Depth 1: Information density — unique non-stopword tokens per 100 words
    STOPWORDS = {'the','a','an','is','are','was','were','be','been','being','have','has','had',
                 'do','does','did','will','would','shall','should','may','might','can','could',
                 'must','to','of','in','for','on','with','at','by','from','as','into','through',
                 'and','but','or','not','no','nor','so','yet','both','either','neither','each',
                 'every','all','any','few','more','most','other','some','such','than','too','very',
                 'just','also','about','this','that','these','those','it','its','i','we','you',
                 'he','she','they','me','us','him','her','them','my','our','your','his','their',
                 'what','which','who','whom','whose','when','where','why','how','if','then',
                 'there','here','up','out','down','over','under','again','further','once'}
    content_words = [w.lower().strip('.,;:!?()[]{}"\'-') for w in words
                     if w.lower().strip('.,;:!?()[]{}"\'-') not in STOPWORDS
                     and len(w.strip('.,;:!?()[]{}"\'-')) > 2]
    unique_content = len(set(content_words))
    density_per_100 = (unique_content / max(wc, 1)) * 100
    depth["information_density"] = round(min(density_per_100 / 40, 1.0), 3)  # 40 unique/100w = 1.0

    # Depth 2: Redundancy — repeated 3-gram ratio (high = MORE survivable but less efficient)
    trigrams = [' '.join(content_words[i:i+3]) for i in range(len(content_words)-2)]
    if trigrams:
        trigram_counts = Counter(trigrams)
        repeated = sum(1 for c in trigram_counts.values() if c > 1)
        depth["redundancy"] = round(min(repeated / max(len(trigram_counts), 1), 1.0), 3)
    else:
        depth["redundancy"] = 0.0

    # Depth 3: Argument chain depth — longest sequence of paragraphs with connectives
    max_chain = 0
    current_chain = 0
    for p in paragraphs:
        if re.search(CONNECTIVES, p.lower()):
            current_chain += 1
            max_chain = max(max_chain, current_chain)
        else:
            current_chain = 0
    depth["argument_chain"] = round(min(max_chain / 5, 1.0), 3)  # 5 consecutive = 1.0

    # Depth 4: Citation integration — are citations near argument connectives?
    # Load-bearing citations appear within 200 chars of a connective
    if doi_count > 0:
        doi_positions = [m.start() for m in re.finditer(r'10\.\d{4,}/[^\s\)]+', content)]
        connective_positions = [m.start() for m in re.finditer(CONNECTIVES, lower_content)]
        integrated = 0
        for dp in doi_positions:
            for cp in connective_positions:
                if abs(dp - cp) < 200:
                    integrated += 1
                    break
        depth["citation_integration"] = round(integrated / doi_count, 3)
    else:
        depth["citation_integration"] = 0.0

    # Depth 5: Vocabulary specificity — ratio of long/technical words to total
    # Words ≥ 8 chars and not stopwords are considered "specific"
    specific_words = [w for w in content_words if len(w) >= 8]
    depth["vocabulary_specificity"] = round(min(len(specific_words) / max(len(content_words), 1) * 2.5, 1.0), 3)

    # === COMPOSITE SCORES ===

    # Surface composite (original γ — backwards compatible)
    weights = {"citation": 0.30, "structure": 0.25, "coherence": 0.25, "provenance": 0.20}
    gamma = sum(weights[name] * score for name, score in subscores.items())

    # Depth composite
    depth_weights = {
        "information_density": 0.30,
        "redundancy": 0.10,  # Low weight — redundancy is neutral, not always good
        "argument_chain": 0.25,
        "citation_integration": 0.20,
        "vocabulary_specificity": 0.15,
    }
    depth_score = sum(depth_weights[k] * depth[k] for k in depth_weights)
    depth["composite"] = round(depth_score, 3)

    # Softer length penalties
    penalty = None
    if wc < 20:
        gamma *= 0.4
        penalty = f"very short ({wc} words)"
    elif wc < 50:
        gamma *= 0.7
        penalty = f"short ({wc} words)"
    elif wc < 200:
        gamma *= 0.9
        penalty = f"moderate ({wc} words)"

    gamma = round(min(gamma, 1.0), 3)

    # Survival tier
    if gamma >= 0.7:
        survival_tier = "survives"
    elif gamma >= 0.4:
        survival_tier = "partial"
    else:
        survival_tier = "drowns"

    if return_detail:
        return {
            "gamma": gamma,
            "subscores": subscores,
            "depth": depth,
            "word_count": wc,
            "penalty": penalty,
            "survival_tier": survival_tier,
            "unique_concepts": unique_content,
            "paragraphs": num_paragraphs,
            "doi_count": doi_count,
            "connective_count": len(coherence_matches),
        }
    return gamma

