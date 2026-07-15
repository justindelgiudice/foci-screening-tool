"""
matcher.py

Fuzzy-matches contractor names against the sanctions/entity list using
rapidfuzz. Thresholds below were calibrated empirically (see the
project's development notes / README) against real rapidfuzz output:

  - Near-identical names (e.g. same firm re-registered under a new
    corporate suffix) scored ~90 with token_sort_ratio.
  - Moderately similar names (shared distinctive words, different
    suffix/legal form) scored ~79.
  - Unrelated company names scored 34-42.

That gap (unrelated names topping out around 42, real near-matches
starting around 79) is what justifies the two-tier thresholds here.
Any production deployment should re-validate these thresholds against
its own real name universe before relying on them.
"""

import re

from rapidfuzz import fuzz
from models import SanctionsMatch

HIGH_CONFIDENCE_THRESHOLD = 88.0   # near-identical name (e.g. suffix swap)
MODERATE_CONFIDENCE_THRESHOLD = 75.0  # meaningfully similar, worth review

# Generic corporate-form words that inflate token_sort_ratio between
# otherwise-unrelated companies (e.g. "CFM INTERNATIONAL INC" vs "IAC
# INTERNATIONAL INC." scored 88% despite sharing no distinctive
# characters -- the score was almost entirely "INTERNATIONAL INC").
# Stripped before scoring so the ratio reflects the distinctive part of
# each name; the original names are kept for display everywhere else.
_BOILERPLATE_TOKENS = {
    "INC", "LLC", "CORP", "CORPORATION", "INTERNATIONAL",
    "CO", "LTD", "GROUP", "HOLDINGS",
}
_TOKEN_SPLIT_RE = re.compile(r"[^A-Z0-9]+")


def _normalize_for_matching(name: str) -> str:
    tokens = [t for t in _TOKEN_SPLIT_RE.split(name.upper()) if t]
    meaningful = [t for t in tokens if t not in _BOILERPLATE_TOKENS]
    # If a name is nothing but boilerplate (rare), fall back to the
    # unstripped tokens rather than matching against an empty string.
    return " ".join(meaningful) if meaningful else " ".join(tokens)


def best_sanctions_match(contractor_name: str, sanctions_entries: list):
    """
    Returns the best-scoring SanctionsMatch for this contractor name
    against the full sanctions/entity list, or None if nothing clears
    the moderate-confidence threshold.
    """
    best_score = 0.0
    best_entry = None
    normalized_contractor = _normalize_for_matching(contractor_name)
    for entry in sanctions_entries:
        score = fuzz.token_sort_ratio(normalized_contractor, _normalize_for_matching(entry.name))
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is None or best_score < MODERATE_CONFIDENCE_THRESHOLD:
        return None

    confidence = "high" if best_score >= HIGH_CONFIDENCE_THRESHOLD else "moderate"
    return SanctionsMatch(
        matched_entity_name=best_entry.name,
        matched_entity_program=best_entry.program,
        similarity_score=round(best_score, 1),
        confidence=confidence,
    )
