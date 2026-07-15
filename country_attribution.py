"""
country_attribution.py

Resolves a real country for a matched OFAC SDN entity from two real,
documented OFAC data sources -- this module never guesses or infers a
country from anything else (not the entity's name, not its sanctions
program, not the contractor it was matched to).

Sources used, in the order they're combined:

  1. ADD.CSV, OFAC's address file, joined to the SDN entry on ent_num.
     This is the entity's own registered/listed address country(ies).
  2. Known, structured phrases in the SDN remarks field: "nationality
     X", "citizen X", "Nationality of Registration X". These are real,
     recurring OFAC remarks conventions (verified against live SDN.CSV
     data), not a free-text NLP guess.

An entity can have multiple addresses/nationalities on file (e.g.
several known offices) -- all resolved countries are kept, not just
the first. If neither source yields anything, CountryAttribution.countries
stays empty and callers must display "country unknown", never a guess.
"""

import re
from typing import Dict, List

from models import CountryAttribution

# The four countries of concern this tool weights specially, per the
# FOCI screening use case (not an exhaustive list of all sanctioned
# countries -- just the ones that get an extra scoring weight).
COUNTRIES_OF_CONCERN = {"China", "Russia", "Iran", "North Korea"}

# Canonicalizes the real spellings/phrasings OFAC actually uses (verified
# against live ADD.CSV country values and SDN.CSV remarks text) to a
# single display name per country. Order matters: North/South Korea
# must be checked before a bare "Korea" would ever be (it never is, but
# keeps this safe if OFAC changes phrasing).
_CANONICAL_COUNTRY_PATTERNS = [
    (re.compile(r"north\s*korea|korea,\s*north|dprk", re.I), "North Korea"),
    (re.compile(r"south\s*korea|korea,\s*south", re.I), "South Korea"),
    (re.compile(r"china", re.I), "China"),
    (re.compile(r"russia", re.I), "Russia"),
    (re.compile(r"\biran\b", re.I), "Iran"),
]

_REGION_PREFIX_RE = re.compile(r"^region:\s*", re.I)


def _canonicalize(raw: str) -> str:
    """Maps a raw OFAC country string to a canonical display name, or
    '' if it's empty/a placeholder. Falls through to the cleaned raw
    value for countries outside the four of concern -- still real
    data, just not one we special-case."""
    raw = (raw or "").strip().strip(".")
    if not raw or raw == "-0-":
        return ""
    for pattern, canonical in _CANONICAL_COUNTRY_PATTERNS:
        if pattern.search(raw):
            return canonical
    return _REGION_PREFIX_RE.sub("", raw).strip()


# Matches the real, recurring OFAC remarks phrasings for nationality/
# citizenship, e.g. "nationality Russia;", "citizen China;",
# "Nationality of Registration Korea, North;". Captures up to the next
# semicolon (OFAC remarks are semicolon-delimited clauses) so
# comma-containing country names ("Korea, North") are captured whole.
_REMARKS_COUNTRY_RE = re.compile(
    r"(?:nationality of registration|nationality|citizen)\s+([A-Za-z,\.\s]+?)\s*(?:;|$)",
    re.I,
)


def parse_countries_from_remarks(remarks: str) -> List[str]:
    """Extracts countries from known OFAC remarks phrasing. Returns an
    empty list if the remarks field has none of these patterns -- does
    not attempt to guess a country from other text."""
    if not remarks:
        return []
    found = []
    for m in _REMARKS_COUNTRY_RE.finditer(remarks):
        canonical = _canonicalize(m.group(1))
        if canonical and canonical not in found:
            found.append(canonical)
    return found


def resolve_country(entry, address_countries_by_ent: Dict[str, List[str]]) -> CountryAttribution:
    """
    Builds the CountryAttribution for one SanctionsEntry, combining its
    ADD.CSV address countries (by ent_num) with any nationality/citizen
    phrasing in its own remarks field. Order of precedence doesn't
    matter for scoring (all resolved countries are kept), but address
    records are listed first since they're the more direct source.
    """
    address_countries = [
        c for c in (_canonicalize(raw) for raw in address_countries_by_ent.get(entry.ent_num, []))
        if c
    ]
    remarks_countries = parse_countries_from_remarks(entry.remarks)

    countries: List[str] = []
    sources = []
    if address_countries:
        sources.append("OFAC address record (ADD.CSV)")
        for c in address_countries:
            if c not in countries:
                countries.append(c)
    if remarks_countries:
        sources.append("SDN remarks (nationality/citizenship)")
        for c in remarks_countries:
            if c not in countries:
                countries.append(c)

    concern_countries = [c for c in countries if c in COUNTRIES_OF_CONCERN]
    return CountryAttribution(
        countries=countries,
        source="; ".join(sources),
        concern_countries=concern_countries,
    )
