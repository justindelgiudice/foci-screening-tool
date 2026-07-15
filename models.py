"""
models.py

Shared data containers used across the pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ContractorProfile:
    """All DoD awards aggregated for one recipient (contractor) name."""
    recipient_name: str
    total_award_value: float
    award_count: int
    naics_codes: List[str]
    naics_descriptions: List[str]
    largest_award_value: float
    awarding_sub_agencies: List[str]
    # The individual award records this profile was aggregated from, kept
    # so totals/concentration can be checked against the source data.
    awards: List = field(default_factory=list)

    @property
    def concentration_ratio(self) -> float:
        if self.total_award_value == 0:
            return 0.0
        return self.largest_award_value / self.total_award_value


@dataclass
class CountryAttribution:
    """
    Real, sourced country data for a matched sanctions entity -- never
    a guess. Populated from two OFAC-published sources (see
    country_attribution.py): the ADD.CSV address file joined on
    ent_num, and known structured phrases in the SDN remarks field
    ("nationality X", "citizen X", "Nationality of Registration X").
    If neither source yields anything, `countries` stays empty and
    `display` reports "country unknown" rather than inferring one.
    """
    countries: List[str] = field(default_factory=list)
    source: str = ""  # e.g. "OFAC address record (ADD.CSV); SDN remarks"
    concern_countries: List[str] = field(default_factory=list)

    @property
    def is_country_of_concern(self) -> bool:
        return bool(self.concern_countries)

    @property
    def display(self) -> str:
        return ", ".join(self.countries) if self.countries else "country unknown"


@dataclass
class SanctionsMatch:
    matched_entity_name: str
    matched_entity_program: str
    similarity_score: float
    confidence: str  # "high" or "moderate"
    # Tokenized (not stripped) versions of both names -- kept for display.
    normalized_contractor_name: str = ""
    normalized_entity_name: str = ""
    country: CountryAttribution = field(default_factory=CountryAttribution)
    # Per-token IDF-weighting breakdown from matcher.py's
    # idf_weighted_similarity() -- each entry has token/idf/matched_to/
    # char_ratio/contribution, sorted highest-contribution first. This
    # is what the score was actually computed on; kept so a match can
    # be audited token-by-token rather than trusted as a black box.
    scoring_detail: List[dict] = field(default_factory=list)
    # The (up to 3) contractor-name tokens that drove most of the score
    # -- e.g. "VANTAGE, PRECISION" -- for a quick one-line summary of
    # scoring_detail without the full breakdown.
    top_contributing_tokens: str = ""


@dataclass
class RiskFinding:
    category: str
    description: str
    points: int
    # Short, literal statement of the condition that fired and the
    # actual value compared against the threshold, e.g.
    # "similarity_score (88.4) >= HIGH_CONFIDENCE_THRESHOLD (88.0)".
    rule: str = ""


@dataclass
class ScoredContractor:
    contractor: ContractorProfile
    sanctions_match: Optional[SanctionsMatch]
    risk_score: int
    findings: List[RiskFinding] = field(default_factory=list)
    recommendation: str = "PASS"
    # One explicit, human-readable sentence stating why this contractor
    # got the score it did -- e.g. "Flagged because X in Russia matches
    # at 88.4%, and contractor holds 334511 awards." Built in
    # risk_engine.py so the reasoning is stated once, not left implicit
    # in the per-finding descriptions.
    headline_reason: str = ""
