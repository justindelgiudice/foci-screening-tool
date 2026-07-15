"""
risk_engine.py

Foreign-nexus-first Defense-Supply-Chain Risk Score (0-100).

The dominant, and only *independent*, score component is the sanctions/
entity-list match itself, weighted by the matched entity's real country
(from country_attribution.py): a match to an entity tied to a country
of concern (China, Russia, Iran, North Korea) scores highest, a match
to another foreign country scores lower, and a match where the country
can't be determined from real data scores lowest of the three -- but
still counts, because being on the OFAC SDN list is itself the foreign-
nexus signal.

Sensitive-NAICS exposure and single-award concentration are demoted to
*contextual modifiers*: they only add points on top of an existing
foreign-nexus finding. With no sanctions match at all, a contractor
scores 0 regardless of its NAICS mix or concentration -- those signals
describe what kind of work a *flagged* contractor does, they don't by
themselves establish foreign exposure.

Thresholds and point values are illustrative, the same way a first-pass
compliance screening tool's weights would be before being calibrated
against a real historical case set.
"""

from models import RiskFinding, ScoredContractor
from matcher import best_sanctions_match, build_token_idf, HIGH_CONFIDENCE_THRESHOLD, MODERATE_CONFIDENCE_THRESHOLD

# Real NAICS codes covering defense-sensitive technology categories.
SENSITIVE_NAICS = {
    "334511": "Search, Detection, Navigation, Guidance, Aeronautical, and Nautical Systems",
    "336414": "Guided Missile and Space Vehicle Manufacturing",
    "334220": "Radio and Television Broadcasting and Wireless Communications Equipment",
    "334413": "Semiconductor and Related Device Manufacturing",
    "541715": "Research and Development in the Physical, Engineering, and Life Sciences",
}

# --- Foreign nexus: dominant score component ---
HIGH_CONFIDENCE_SANCTIONS_POINTS = 50
MODERATE_CONFIDENCE_SANCTIONS_POINTS = 25

# Country weighting layered on top of the confidence points above.
# Countries of concern score highest; a resolved-but-not-of-concern
# foreign country scores a small amount higher than an unresolved one,
# since a confirmed foreign country is still more informative than none.
CONCERN_COUNTRY_BONUS = 30
OTHER_COUNTRY_BONUS = 5
UNKNOWN_COUNTRY_BONUS = 0

# --- Contextual modifiers: only ever added on top of a foreign-nexus finding ---
SENSITIVE_NAICS_MODIFIER = 10
MULTI_SENSITIVE_NAICS_MODIFIER = 5
CONCENTRATION_MODIFIER = 5
CONCENTRATION_THRESHOLD = 0.80  # single award >= 80% of total value

INVESTIGATE_THRESHOLD = 60
REVIEW_THRESHOLD = 30


def score_contractor(contractor, sanctions_entries: list, address_countries_by_ent: dict = None,
                      idf_table: dict = None) -> ScoredContractor:
    match = best_sanctions_match(contractor.recipient_name, sanctions_entries, address_countries_by_ent, idf_table)

    if match is None:
        # No foreign nexus established. NAICS mix and award concentration
        # are contextual modifiers of a nexus finding, not independent
        # risk generators -- so with no nexus, no points, full stop.
        return ScoredContractor(
            contractor=contractor,
            sanctions_match=None,
            risk_score=0,
            findings=[],
            recommendation="PASS",
            headline_reason=(
                "No sanctions/entity list match found for this contractor name -- "
                "PASS regardless of NAICS mix or award concentration, since neither "
                "is treated as risk on its own."
            ),
        )

    findings = []
    score = 0

    confidence_points = (
        HIGH_CONFIDENCE_SANCTIONS_POINTS if match.confidence == "high"
        else MODERATE_CONFIDENCE_SANCTIONS_POINTS
    )

    if match.country.is_country_of_concern:
        country_bonus = CONCERN_COUNTRY_BONUS
        country_reason = f"country of concern ({', '.join(match.country.concern_countries)})"
    elif match.country.countries:
        country_bonus = OTHER_COUNTRY_BONUS
        country_reason = f"other foreign country ({match.country.display})"
    else:
        country_bonus = UNKNOWN_COUNTRY_BONUS
        country_reason = "country unknown -- no ADD.CSV or remarks data resolved a country"

    nexus_points = confidence_points + country_bonus
    score += nexus_points

    confidence_label = "High Confidence" if match.confidence == "high" else "Moderate Confidence"
    findings.append(RiskFinding(
        category=f"Foreign Sanctions Nexus ({confidence_label})",
        description=(
            f"'{contractor.recipient_name}' matches sanctions/entity list entry "
            f"'{match.matched_entity_name}' ({match.matched_entity_program}) at "
            f"{match.similarity_score}% name similarity. Matched entity country: "
            f"{match.country.display} -- {country_reason}."
        ),
        points=nexus_points,
        rule=(
            f"confidence_points ({confidence_points}, similarity={match.similarity_score}%) "
            f"+ country_bonus ({country_bonus}, {country_reason}) -> +{nexus_points}"
        ),
    ))

    # --- Contextual modifiers below: only reached because a foreign nexus already exists above ---
    sensitive_hits = [code for code in contractor.naics_codes if code in SENSITIVE_NAICS]
    if sensitive_hits:
        descriptions = ", ".join(f"{code} ({SENSITIVE_NAICS[code]})" for code in sensitive_hits)
        findings.append(RiskFinding(
            category="Sensitive Defense-Technology NAICS Exposure (modifier)",
            description=(
                f"Also holds award(s) in sensitive technology categories: {descriptions}. "
                f"This modifies the foreign-nexus finding above; it does not, by itself, "
                f"generate risk for a contractor with no sanctions match."
            ),
            points=SENSITIVE_NAICS_MODIFIER,
            rule=(
                f"foreign nexus present AND naics_codes intersects SENSITIVE_NAICS "
                f"({', '.join(sensitive_hits)}) -> +{SENSITIVE_NAICS_MODIFIER}"
            ),
        ))
        score += SENSITIVE_NAICS_MODIFIER

        if len(sensitive_hits) >= 2:
            findings.append(RiskFinding(
                category="Multiple Sensitive-Technology Categories (modifier)",
                description=(
                    f"Holds awards across {len(sensitive_hits)} distinct sensitive NAICS "
                    f"categories, broadening the foreign-nexus concern above."
                ),
                points=MULTI_SENSITIVE_NAICS_MODIFIER,
                rule=f"foreign nexus present AND len(sensitive_hits) ({len(sensitive_hits)}) >= 2 -> +{MULTI_SENSITIVE_NAICS_MODIFIER}",
            ))
            score += MULTI_SENSITIVE_NAICS_MODIFIER

    if contractor.concentration_ratio >= CONCENTRATION_THRESHOLD:
        findings.append(RiskFinding(
            category="Single-Award Revenue Concentration (modifier)",
            description=(
                f"{contractor.concentration_ratio * 100:.1f}% of this contractor's tracked DoD "
                f"award value comes from a single award, compounding the dependency risk of the "
                f"foreign-nexus finding above."
            ),
            points=CONCENTRATION_MODIFIER,
            rule=(
                f"foreign nexus present AND concentration_ratio ({contractor.concentration_ratio * 100:.1f}%) "
                f">= CONCENTRATION_THRESHOLD ({CONCENTRATION_THRESHOLD * 100:.0f}%) -> +{CONCENTRATION_MODIFIER}"
            ),
        ))
        score += CONCENTRATION_MODIFIER

    score = max(0, min(100, score))
    if score >= INVESTIGATE_THRESHOLD:
        recommendation = "INVESTIGATE FURTHER"
    elif score >= REVIEW_THRESHOLD:
        recommendation = "REVIEW RECOMMENDED"
    else:
        recommendation = "PASS"

    extra_clauses = []
    if sensitive_hits:
        extra_clauses.append(f"contractor holds award(s) in sensitive NAICS categories ({', '.join(sensitive_hits)})")
    if contractor.concentration_ratio >= CONCENTRATION_THRESHOLD:
        extra_clauses.append(f"{contractor.concentration_ratio * 100:.1f}% of tracked award value is concentrated in a single award")

    if recommendation == "PASS":
        headline = (
            f"Not flagged: matched {match.matched_entity_name} in {match.country.display} at "
            f"{match.similarity_score}% similarity, but the combined score ({score}) stays "
            f"below the REVIEW threshold ({REVIEW_THRESHOLD})."
        )
    else:
        headline = (
            f"Flagged because {match.matched_entity_name} in {match.country.display} "
            f"matches at {match.similarity_score}%"
        )
        if extra_clauses:
            headline += ", and " + "; and ".join(extra_clauses) + "."
        else:
            headline += "."

    return ScoredContractor(
        contractor=contractor,
        sanctions_match=match,
        risk_score=score,
        findings=findings,
        recommendation=recommendation,
        headline_reason=headline,
    )


def score_all(contractors: list, sanctions_entries: list, address_countries_by_ent: dict = None) -> list:
    # Built once per run, not once per contractor -- see matcher.build_token_idf().
    idf_table = build_token_idf(sanctions_entries)
    return [score_contractor(c, sanctions_entries, address_countries_by_ent, idf_table) for c in contractors]
