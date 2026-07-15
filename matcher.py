"""
matcher.py

Fuzzy-matches contractor names against the sanctions/entity list.

Replaces an earlier fixed-stopword-list approach (which only stripped
legal-form suffixes like INC/LLC/CORP) with inverse-document-frequency
(IDF) token weighting computed over the sanctions list itself. The
stopword list fixed one failure mode but not a closely related one:
matches driven entirely by generic-but-not-legal-suffix business words
(SERVICES, ENTERPRISE, SYSTEMS, TECHNOLOGIES, ...) that appear in a
large fraction of SDN entity names and so carry almost no distinguishing
signal, e.g. observed on real live data:

  - "SAVOIR FAIRE SERVICES LLC" matched "GOMEI AIR SERVICES CO., LTD."
    at 76.9% under token_sort_ratio + stopword stripping, driven
    entirely by the shared, extremely common word SERVICES -- SAVOIR/
    FAIRE share nothing with GOMEI/AIR.
  - "AT&T ENTERPRISES, LLC" matched "OSTEC ENTERPRISE LTD" at 75.0%,
    driven entirely by ENTERPRISES/ENTERPRISE -- AT&T shares nothing
    with OSTEC.

IDF weighting fixes this generically instead of via a maintained list:
a token's weight is inversely proportional to how many SDN entity
names contain it, computed once over the real sanctions list at match
time (see build_token_idf()). Legal suffixes and generic industry
words both end up with low weight naturally, because both appear in a
large fraction of entity names.

Performance note: computing the IDF-weighted score against all
~19,000+ SDN entries per contractor would be too slow for a live page
load (nested per-token character comparisons, not a single C-level
ratio call). Matching is therefore two-phase:
  1. A fast rapidfuzz token_sort_ratio pass over the whole list picks
     a shortlist of candidates.
  2. The IDF-weighted score is computed only for that shortlist to
     pick the final match and score.
This is a real completeness/speed tradeoff: a true match could in
principle fall outside the shortlist, but a true match virtually
always has *some* raw string overlap, so a generous pool size
(CANDIDATE_POOL_SIZE) makes that very unlikely in practice.
"""

import math
import re
from collections import Counter

from rapidfuzz import fuzz
from models import SanctionsMatch
from country_attribution import resolve_country

HIGH_CONFIDENCE_THRESHOLD = 88.0   # near-identical name (e.g. suffix swap)
MODERATE_CONFIDENCE_THRESHOLD = 75.0  # meaningfully similar, worth review

CANDIDATE_POOL_SIZE = 30

_TOKEN_SPLIT_RE = re.compile(r"[^A-Z0-9]+")


def _tokenize(name: str) -> list:
    return [t for t in _TOKEN_SPLIT_RE.split(name.upper()) if t]


def build_token_idf(sanctions_entries: list) -> dict:
    """
    Smoothed IDF for every token appearing in the sanctions list's
    entity names: idf(t) = ln((N + 1) / (df(t) + 1)) + 1, where N is
    the number of entities and df(t) is how many distinct entity names
    contain t at least once. Always > 0; a token in nearly every name
    (INC, LLC, SERVICES, ...) approaches the floor (~1.0); a token
    unique to one name approaches the ceiling (ln(N+1)+1).

    Call this once per sanctions_entries list (e.g. in risk_engine.score_all)
    and pass the result into best_sanctions_match for every contractor --
    recomputing it per contractor would mean re-tokenizing the entire
    SDN list once per contractor for no reason.
    """
    n = len(sanctions_entries)
    doc_frequency = Counter()
    for entry in sanctions_entries:
        for token in set(_tokenize(entry.name)):
            doc_frequency[token] += 1
    return {token: math.log((n + 1) / (freq + 1)) + 1 for token, freq in doc_frequency.items()}


def _idf(token: str, idf_table: dict, max_idf: float) -> float:
    # A token entirely absent from the corpus (typo, or a word that
    # appears in the contractor's name but in literally no SDN entity
    # name) is at least as distinctive as the rarest token we've seen.
    return idf_table.get(token, max_idf)


def _directional_score(tokens_a: list, tokens_b: list, idf_table: dict, max_idf: float):
    """
    How well tokens_a's informativeness is accounted for by tokens_b,
    0-100, plus the per-token contributions (for audit/display).
    Each token in tokens_a is matched to its single best character-level
    match in tokens_b (rapidfuzz.fuzz.ratio), and that pair's
    contribution to the total is scaled by the token's IDF weight --
    so an exact match on a common word barely moves the score, while
    an exact match on a rare/distinctive word dominates it.
    """
    if not tokens_a or not tokens_b:
        return 0.0, []

    unique_b = list(set(tokens_b))
    total_weight = 0.0
    matched_weight = 0.0
    contributions = []
    for a in set(tokens_a):
        weight = _idf(a, idf_table, max_idf)
        best_b, best_ratio = max(
            ((b, fuzz.ratio(a, b)) for b in unique_b),
            key=lambda pair: pair[1],
        )
        total_weight += weight
        contribution = weight * (best_ratio / 100.0)
        matched_weight += contribution
        contributions.append({"token": a, "idf": round(weight, 2), "matched_to": best_b,
                               "char_ratio": round(best_ratio, 1), "contribution": round(contribution, 2)})

    contributions.sort(key=lambda c: c["contribution"], reverse=True)
    score = 100.0 * matched_weight / total_weight if total_weight else 0.0
    return score, contributions


def idf_weighted_similarity(name_a: str, name_b: str, idf_table: dict, max_idf: float = None):
    """
    Symmetric IDF-weighted similarity between two names, 0-100, plus
    the contractor-side per-token contributions that drove it (for
    audit/display -- "what was this score actually computed on").
    """
    if max_idf is None:
        max_idf = max(idf_table.values()) if idf_table else 1.0
    tokens_a = _tokenize(name_a)
    tokens_b = _tokenize(name_b)
    a_to_b, contributions_a = _directional_score(tokens_a, tokens_b, idf_table, max_idf)
    b_to_a, _ = _directional_score(tokens_b, tokens_a, idf_table, max_idf)
    return (a_to_b + b_to_a) / 2.0, contributions_a


def best_sanctions_match(contractor_name: str, sanctions_entries: list,
                          address_countries_by_ent: dict = None, idf_table: dict = None):
    """
    Returns the best-scoring SanctionsMatch for this contractor name
    against the full sanctions/entity list, or None if nothing clears
    the moderate-confidence threshold.

    idf_table, if given, should come from build_token_idf(sanctions_entries)
    computed once per run (see risk_engine.score_all). If omitted, it's
    computed here -- fine for one-off calls or small entry lists (e.g.
    tests), wasteful if called once per contractor against the full SDN
    list.

    address_countries_by_ent, if given, is the {ent_num: [country, ...]}
    map from sources.sanctions_source.get_address_countries() (the real
    OFAC ADD.CSV join) -- used to attach a real country to the match.
    If omitted, country attribution falls back to remarks-only.
    """
    if idf_table is None:
        idf_table = build_token_idf(sanctions_entries)
    max_idf = max(idf_table.values()) if idf_table else 1.0

    # Phase 1: fast candidate shortlist over the full list.
    contractor_upper = contractor_name.upper()
    candidates = sorted(
        sanctions_entries,
        key=lambda entry: fuzz.token_sort_ratio(contractor_upper, entry.name.upper()),
        reverse=True,
    )[:CANDIDATE_POOL_SIZE]

    # Phase 2: precise IDF-weighted re-scoring, shortlist only.
    best_score = 0.0
    best_entry = None
    best_contributions = []
    for entry in candidates:
        score, contributions = idf_weighted_similarity(contractor_name, entry.name, idf_table, max_idf)
        if score > best_score:
            best_score = score
            best_entry = entry
            best_contributions = contributions

    if best_entry is None or best_score < MODERATE_CONFIDENCE_THRESHOLD:
        return None

    confidence = "high" if best_score >= HIGH_CONFIDENCE_THRESHOLD else "moderate"
    country = resolve_country(best_entry, address_countries_by_ent or {})
    top_tokens = ", ".join(c["token"] for c in best_contributions[:3] if c["contribution"] > 0.5)
    return SanctionsMatch(
        matched_entity_name=best_entry.name,
        matched_entity_program=best_entry.program,
        similarity_score=round(best_score, 1),
        confidence=confidence,
        normalized_contractor_name=" ".join(_tokenize(contractor_name)),
        normalized_entity_name=" ".join(_tokenize(best_entry.name)),
        country=country,
        scoring_detail=best_contributions,
        top_contributing_tokens=top_tokens,
    )
