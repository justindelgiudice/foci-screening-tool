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

    @property
    def concentration_ratio(self) -> float:
        if self.total_award_value == 0:
            return 0.0
        return self.largest_award_value / self.total_award_value


@dataclass
class SanctionsMatch:
    matched_entity_name: str
    matched_entity_program: str
    similarity_score: float
    confidence: str  # "high" or "moderate"


@dataclass
class RiskFinding:
    category: str
    description: str
    points: int


@dataclass
class ScoredContractor:
    contractor: ContractorProfile
    sanctions_match: Optional[SanctionsMatch]
    risk_score: int
    findings: List[RiskFinding] = field(default_factory=list)
    recommendation: str = "PASS"
