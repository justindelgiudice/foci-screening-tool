"""
risk_engine.py

Combines three real, checkable signals into a Foreign-Exposure /
Defense-Supply-Chain Risk Score (0-100):

  1. Fuzzy-matched hit against the sanctions/entity screening list
     (high confidence >=88 similarity, moderate confidence 75-87).
  2. Whether the contractor holds NAICS codes in sensitive defense-tech
     categories (guidance systems, munitions, semiconductors, comms,
     physical/engineering R&D).
  3. Revenue concentration: how dependent the contractor is on a single
     award (a single-client/single-award dependency is itself a
     supply-chain fragility signal worth surfacing, independent of any
     sanctions hit).

Thresholds and point values are illustrative, the same way a first-pass
compliance screening tool's weights would be before being calibrated
against a real historical case set.
"""

from models import RiskFinding, ScoredContractor
from matcher import best_sanctions_match

# Real NAICS codes covering defense-sensitive technology categories.
SENSITIVE_NAICS = {
    "334511": "Search, Detection, Navigation, Guidance, Aeronautical, and Nautical Systems",
    "336414": "Guided Missile and Space Vehicle Manufacturing",
    "334220": "Radio and Television Broadcasting and Wireless Communications Equipment",
    "334413": "Semiconductor and Related Device Manufacturing",
    "541715": "Research and Development in the Physical, Engineering, and Life Sciences",
}

HIGH_CONFIDENCE_SANCTIONS_POINTS = 50
MODERATE_CONFIDENCE_SANCTIONS_POINTS = 25
SENSITIVE_NAICS_POINTS = 15
MULTI_SENSITIVE_NAICS_BONUS = 10
CONCENTRATION_POINTS = 10
CONCENTRATION_THRESHOLD = 0.80  # single award >= 80% of total value

INVESTIGATE_THRESHOLD = 60
REVIEW_THRESHOLD = 30


def score_contractor(contractor, sanctions_entries: list) -> ScoredContractor:
    findings = []
    score = 0

    match = best_sanctions_match(contractor.recipient_name, sanctions_entries)
    if match is not None:
        if match.confidence == "high":
            points = HIGH_CONFIDENCE_SANCTIONS_POINTS
            findings.append(RiskFinding(
                category="Sanctions/Entity List Match (High Confidence)",
                description=(
                    f"'{contractor.recipient_name}' matches sanctions/entity list entry "
                    f"'{match.matched_entity_name}' ({match.matched_entity_program}) at "
                    f"{match.similarity_score}% name similarity."
                ),
                points=points,
            ))
        else:
            points = MODERATE_CONFIDENCE_SANCTIONS_POINTS
            findings.append(RiskFinding(
                category="Sanctions/Entity List Match (Moderate Confidence)",
                description=(
                    f"'{contractor.recipient_name}' is a moderate fuzzy match to sanctions/entity "
                    f"list entry '{match.matched_entity_name}' ({match.matched_entity_program}) at "
                    f"{match.similarity_score}% name similarity -- recommend manual review."
                ),
                points=points,
            ))
        score += points

    sensitive_hits = [code for code in contractor.naics_codes if code in SENSITIVE_NAICS]
    if sensitive_hits:
        descriptions = ", ".join(f"{code} ({SENSITIVE_NAICS[code]})" for code in sensitive_hits)
        findings.append(RiskFinding(
            category="Sensitive Defense-Technology NAICS Exposure",
            description=f"Holds award(s) in sensitive technology categories: {descriptions}.",
            points=SENSITIVE_NAICS_POINTS,
        ))
        score += SENSITIVE_NAICS_POINTS

        if len(sensitive_hits) >= 2:
            findings.append(RiskFinding(
                category="Multiple Sensitive-Technology Categories",
                description=(
                    f"Contractor holds awards across {len(sensitive_hits)} distinct sensitive "
                    f"NAICS categories, indicating broader access to sensitive technology areas."
                ),
                points=MULTI_SENSITIVE_NAICS_BONUS,
            ))
            score += MULTI_SENSITIVE_NAICS_BONUS

    if contractor.concentration_ratio >= CONCENTRATION_THRESHOLD:
        findings.append(RiskFinding(
            category="Single-Award Revenue Concentration",
            description=(
                f"{contractor.concentration_ratio * 100:.1f}% of this contractor's tracked DoD "
                f"award value comes from a single award -- a dependency/fragility signal worth "
                f"noting alongside any other findings."
            ),
            points=CONCENTRATION_POINTS,
        ))
        score += CONCENTRATION_POINTS

    score = max(0, min(100, score))
    if score >= INVESTIGATE_THRESHOLD:
        recommendation = "INVESTIGATE FURTHER"
    elif score >= REVIEW_THRESHOLD:
        recommendation = "REVIEW RECOMMENDED"
    else:
        recommendation = "PASS"

    return ScoredContractor(
        contractor=contractor,
        sanctions_match=match,
        risk_score=score,
        findings=findings,
        recommendation=recommendation,
    )


def score_all(contractors: list, sanctions_entries: list) -> list:
    return [score_contractor(c, sanctions_entries) for c in contractors]
