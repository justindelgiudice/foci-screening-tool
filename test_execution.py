"""
test_execution.py

Verifies the pipeline end-to-end in demo mode:
  - Award aggregation produces correct per-contractor totals and
    concentration ratios.
  - Fuzzy sanctions matching correctly separates real near-matches
    from unrelated names (using the empirically-calibrated thresholds).
  - The risk engine produces the expected tiered outcomes: a clean
    contractor (PASS), a high-confidence sanctions hit (INVESTIGATE),
    a moderate-confidence hit (REVIEW), a pure concentration case
    (PASS, since concentration alone isn't disqualifying), and a
    multi-sensitive-NAICS case (REVIEW).

Run with: python3 test_execution.py
Exits 0 if all checks pass, 1 otherwise.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.usaspending_source import load_demo_awards
from sources.sanctions_source import load_demo_sdn_list
from aggregator import build_contractor_profiles
from risk_engine import score_all

FAILURES = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main():
    print("Running Defense Contractor Foreign-Exposure Dashboard verification suite...\n")

    awards = load_demo_awards()
    sanctions = load_demo_sdn_list()
    contractors = build_contractor_profiles(awards)
    scored = {sc.contractor.recipient_name: sc for sc in score_all(contractors, sanctions)}

    print("Test 1: Data loading")
    check("Demo awards loaded (7 award records)", len(awards) == 7)
    check("Demo sanctions list loaded (4 entries)", len(sanctions) == 4)
    check("5 unique contractors aggregated", len(contractors) == 5)

    print("\nTest 2: Aggregation correctness")
    sterling = scored["STERLING AEROSPACE DYNAMICS INC"].contractor
    check("Sterling total value = $60,800,000", sterling.total_award_value == 60_800_000)
    check("Sterling award count = 2", sterling.award_count == 2)
    check("Sterling concentration < 80% (below threshold)", sterling.concentration_ratio < 0.80)

    meridian = scored["MERIDIAN PHOTONICS GROUP INC"].contractor
    check("Meridian has 2 distinct NAICS codes", len(meridian.naics_codes) == 2)
    check("Meridian concentration >= 80%", meridian.concentration_ratio >= 0.80)

    print("\nTest 3: Clean contractor -> PASS")
    sc = scored["STERLING AEROSPACE DYNAMICS INC"]
    check("No sanctions match", sc.sanctions_match is None)
    check("Risk score is 0", sc.risk_score == 0)
    check("Recommendation is PASS", sc.recommendation == "PASS")

    print("\nTest 4: High-confidence sanctions match -> INVESTIGATE FURTHER (critical case)")
    sc = scored["VANTAGE PRECISION SYSTEMS INC"]
    check("Sanctions match found", sc.sanctions_match is not None)
    check("Match confidence is 'high'", sc.sanctions_match and sc.sanctions_match.confidence == "high")
    check("Similarity score >= 88", sc.sanctions_match and sc.sanctions_match.similarity_score >= 88.0)
    check("Risk score >= 60", sc.risk_score >= 60)
    check("Recommendation is INVESTIGATE FURTHER", sc.recommendation == "INVESTIGATE FURTHER")

    print("\nTest 5: Moderate-confidence sanctions match -> REVIEW RECOMMENDED")
    sc = scored["HORIZON GUIDANCE TECHNOLOGIES INC"]
    check("Sanctions match found", sc.sanctions_match is not None)
    check("Match confidence is 'moderate'", sc.sanctions_match and sc.sanctions_match.confidence == "moderate")
    check("Similarity score in [75, 88)", sc.sanctions_match and 75.0 <= sc.sanctions_match.similarity_score < 88.0)
    check("Risk score in [30, 60)", 30 <= sc.risk_score < 60)
    check("Recommendation is REVIEW RECOMMENDED", sc.recommendation == "REVIEW RECOMMENDED")

    print("\nTest 6: Pure concentration risk (no sanctions/NAICS flags) -> stays PASS")
    sc = scored["CASCADE DEFENSE SOLUTIONS LLC"]
    check("No sanctions match", sc.sanctions_match is None)
    check("Concentration flag present but score stays low", sc.risk_score == 10)
    check("Recommendation is PASS", sc.recommendation == "PASS")

    print("\nTest 7: Multi-sensitive-NAICS + concentration (no sanctions hit) -> REVIEW RECOMMENDED")
    sc = scored["MERIDIAN PHOTONICS GROUP INC"]
    check("No sanctions match", sc.sanctions_match is None)
    check("Multiple sensitive NAICS finding present",
          any(f.category == "Multiple Sensitive-Technology Categories" for f in sc.findings))
    check("Risk score in [30, 60)", 30 <= sc.risk_score < 60)
    check("Recommendation is REVIEW RECOMMENDED", sc.recommendation == "REVIEW RECOMMENDED")

    print("\nTest 8: Matcher does not produce false positives on unrelated names")
    from matcher import best_sanctions_match
    unrelated_match = best_sanctions_match("STERLING AEROSPACE DYNAMICS INC", sanctions)
    check("No match for a clearly unrelated contractor name", unrelated_match is None)

    print("\nTest 9: Matcher strips corporate boilerplate before scoring "
          "(regression test for CFM INTERNATIONAL INC / RTX CORPORATION false positives)")
    from sources.sanctions_source import SanctionsEntry
    boilerplate_entries = [
        SanctionsEntry(ent_num="9001", name="IAC INTERNATIONAL INC.", sdn_type="Entity", program="SDNTK"),
        SanctionsEntry(ent_num="9002", name="RIF CORPORATION", sdn_type="Entity", program="RUSSIA-EO14024"),
    ]
    cfm_match = best_sanctions_match("CFM INTERNATIONAL INC", boilerplate_entries)
    rtx_match = best_sanctions_match("RTX CORPORATION", boilerplate_entries)
    check(
        "'CFM INTERNATIONAL INC' no longer matches 'IAC INTERNATIONAL INC.' "
        "once shared boilerplate (INTERNATIONAL, INC) is stripped before scoring",
        cfm_match is None,
    )
    check(
        "'RTX CORPORATION' no longer matches 'RIF CORPORATION' "
        "once shared boilerplate (CORPORATION) is stripped before scoring",
        rtx_match is None,
    )
    # Sanity check: stripping boilerplate must not eat a real, non-boilerplate
    # near-match -- distinctive-word overlap should still score high.
    distinctive_entries = [
        SanctionsEntry(ent_num="9003", name="VANTAGE PRECISION SYSTEMS LLC", sdn_type="Entity", program="SDNTK"),
    ]
    real_match = best_sanctions_match("VANTAGE PRECISION SYSTEMS INC", distinctive_entries)
    check(
        "A genuine near-identical name (distinctive words match, only "
        "boilerplate suffix differs) still matches after stripping",
        real_match is not None and real_match.confidence == "high",
    )

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULT: All checks passed. The pipeline correctly aggregates real-schema")
        print("award data, separates true fuzzy-matches from unrelated names using")
        print("empirically-calibrated thresholds, and produces the expected tiered")
        print("PASS / REVIEW / INVESTIGATE outcomes.")
        sys.exit(0)


if __name__ == "__main__":
    main()
