"""
test_execution.py

Verifies the pipeline end-to-end in demo mode:
  - Award aggregation produces correct per-contractor totals and
    concentration ratios.
  - Fuzzy sanctions matching correctly separates real near-matches
    from unrelated names (using the empirically-calibrated thresholds).
  - Country attribution comes only from real OFAC data (ADD.CSV join +
    remarks parsing) and explicitly reports "country unknown" rather
    than guessing when neither source has an answer.
  - The risk engine is foreign-nexus-first: with no sanctions match, a
    contractor scores 0 regardless of NAICS mix or concentration; with
    a match, country of origin dominates the score, and NAICS/
    concentration only ever modify an existing nexus finding.

Run with: python3 test_execution.py
Exits 0 if all checks pass, 1 otherwise.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.usaspending_source import load_demo_awards
from sources.sanctions_source import load_demo_sdn_list, load_demo_add_list
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
    address_countries = load_demo_add_list()
    contractors = build_contractor_profiles(awards)
    scored = {sc.contractor.recipient_name: sc for sc in score_all(contractors, sanctions, address_countries)}

    print("Test 1: Data loading")
    check("Demo awards loaded (7 award records)", len(awards) == 7)
    check(
        "Demo sanctions list loaded (4 hand-authored entries + 75 synthetic "
        "corpus-padding entries -- see sources.sanctions_source._generate_demo_padding_entries)",
        len(sanctions) == 79,
    )
    check("Demo address file loaded (1 ent_num with an address on file)", len(address_countries) == 1)
    check("5 unique contractors aggregated", len(contractors) == 5)

    print("\nTest 2: Aggregation correctness")
    sterling = scored["STERLING AEROSPACE DYNAMICS INC"].contractor
    check("Sterling total value = $60,800,000", sterling.total_award_value == 60_800_000)
    check("Sterling award count = 2", sterling.award_count == 2)
    check("Sterling concentration < 80% (below threshold)", sterling.concentration_ratio < 0.80)

    meridian = scored["MERIDIAN PHOTONICS GROUP INC"].contractor
    check("Meridian has 2 distinct NAICS codes", len(meridian.naics_codes) == 2)
    check("Meridian concentration >= 80%", meridian.concentration_ratio >= 0.80)

    print("\nTest 3: Clean contractor, no sanctions match -> PASS")
    sc = scored["STERLING AEROSPACE DYNAMICS INC"]
    check("No sanctions match", sc.sanctions_match is None)
    check("Risk score is 0", sc.risk_score == 0)
    check("Recommendation is PASS", sc.recommendation == "PASS")

    print("\nTest 4: High-confidence match + country of concern (Russia) -> INVESTIGATE FURTHER")
    sc = scored["VANTAGE PRECISION SYSTEMS INC"]
    check("Sanctions match found", sc.sanctions_match is not None)
    check("Match confidence is 'high'", sc.sanctions_match and sc.sanctions_match.confidence == "high")
    check("Similarity score >= 88", sc.sanctions_match and sc.sanctions_match.similarity_score >= 88.0)
    check("Country resolved to Russia via the ADD.CSV join", sc.sanctions_match.country.countries == ["Russia"])
    check("Country flagged as a country of concern", sc.sanctions_match.country.is_country_of_concern)
    check("Risk score is 95 (50 confidence + 30 concern-country + 10 NAICS + 5 concentration)", sc.risk_score == 95)
    check("Recommendation is INVESTIGATE FURTHER", sc.recommendation == "INVESTIGATE FURTHER")
    check("Headline reason names the entity and country", "Russia" in sc.headline_reason and "VANTAGE PRECISION SYSTEMS LTD" in sc.headline_reason)

    print("\nTest 5: Moderate-confidence match, country NOT resolvable -> stated as unknown, not guessed")
    sc = scored["HORIZON GUIDANCE TECHNOLOGIES INC"]
    check("Sanctions match found", sc.sanctions_match is not None)
    check("Match confidence is 'moderate'", sc.sanctions_match and sc.sanctions_match.confidence == "moderate")
    check("Similarity score in [75, 88)", sc.sanctions_match and 75.0 <= sc.sanctions_match.similarity_score < 88.0)
    check("No country resolved (no ADD.CSV row, no remarks phrasing for this entry)", sc.sanctions_match.country.countries == [])
    check("Country displays as 'country unknown', not a guess", sc.sanctions_match.country.display == "country unknown")
    check("Not flagged as a country of concern", not sc.sanctions_match.country.is_country_of_concern)
    check("Risk score is 40 (25 confidence + 0 unknown-country + 10 NAICS + 5 concentration)", sc.risk_score == 40)
    check("Recommendation is REVIEW RECOMMENDED", sc.recommendation == "REVIEW RECOMMENDED")

    print("\nTest 6: Concentration risk with NO sanctions match -> stays PASS at score 0 (concentration alone is not risk)")
    sc = scored["CASCADE DEFENSE SOLUTIONS LLC"]
    check("No sanctions match", sc.sanctions_match is None)
    check("Risk score is exactly 0 despite concentration", sc.risk_score == 0)
    check("Recommendation is PASS", sc.recommendation == "PASS")

    print("\nTest 7 (core invariant): Multi-sensitive-NAICS + high concentration, but NO sanctions match -> PASS at score 0")
    sc = scored["MERIDIAN PHOTONICS GROUP INC"]
    check("No sanctions match", sc.sanctions_match is None)
    check("No findings at all -- NAICS/concentration never fire without a foreign-nexus match", sc.findings == [])
    check("Risk score is exactly 0 regardless of 2 sensitive NAICS codes + 100% concentration", sc.risk_score == 0)
    check("Recommendation is PASS", sc.recommendation == "PASS")

    print("\nTest 8: Matcher does not produce false positives on unrelated names")
    from matcher import best_sanctions_match, build_token_idf
    unrelated_match = best_sanctions_match("STERLING AEROSPACE DYNAMICS INC", sanctions, address_countries)
    check("No match for a clearly unrelated contractor name", unrelated_match is None)

    print("\nTest 9: IDF weighting discounts common tokens instead of relying on a fixed stopword list "
          "(regression test for CFM INTERNATIONAL INC / RTX CORPORATION false positives)")
    from sources.sanctions_source import SanctionsEntry

    def padded_corpus(real_entries, common_word_counts):
        """
        real_entries: the SanctionsEntry objects actually under test.
        common_word_counts: [(word, count), ...] of filler entries to add
        so IDF has enough data to recognize those words as common -- the
        real live SDN list (~19,000 entries) provides this naturally; a
        handful of literal test entries can't, so tests must pad it in,
        the same way sources.sanctions_source pads the demo corpus.
        """
        entries = list(real_entries)
        i = 0
        for word, count in common_word_counts:
            for _ in range(count):
                i += 1
                entries.append(SanctionsEntry(
                    ent_num=f"pad-{word}-{i}", name=f"FILLER{i} PLACEHOLDER{i} {word}",
                    sdn_type="Entity", program="TEST-PADDING",
                ))
        return entries

    boilerplate_entries = [
        SanctionsEntry(ent_num="9001", name="IAC INTERNATIONAL INC.", sdn_type="Entity", program="SDNTK"),
        SanctionsEntry(ent_num="9002", name="RIF CORPORATION", sdn_type="Entity", program="RUSSIA-EO14024"),
    ]
    corpus9 = padded_corpus(boilerplate_entries, [("INTERNATIONAL", 20), ("INC", 20), ("CORPORATION", 20)])
    idf9 = build_token_idf(corpus9)
    cfm_match = best_sanctions_match("CFM INTERNATIONAL INC", corpus9, idf_table=idf9)
    rtx_match = best_sanctions_match("RTX CORPORATION", corpus9, idf_table=idf9)
    check(
        "'CFM INTERNATIONAL INC' does not match 'IAC INTERNATIONAL INC.' -- "
        "shared tokens (INTERNATIONAL, INC) are common in the corpus and score low on IDF weight",
        cfm_match is None,
    )
    check(
        "'RTX CORPORATION' does not match 'RIF CORPORATION' -- "
        "shared token (CORPORATION) is common in the corpus and scores low on IDF weight",
        rtx_match is None,
    )
    distinctive_entries = [
        SanctionsEntry(ent_num="9003", name="VANTAGE PRECISION SYSTEMS LLC", sdn_type="Entity", program="SDNTK"),
    ]
    corpus9b = padded_corpus(distinctive_entries, [("LLC", 20), ("INC", 20)])
    idf9b = build_token_idf(corpus9b)
    real_match = best_sanctions_match("VANTAGE PRECISION SYSTEMS INC", corpus9b, idf_table=idf9b)
    check(
        "A genuine near-identical name (distinctive words VANTAGE/PRECISION/SYSTEMS match, "
        "only the common legal-suffix token differs) still matches at high confidence",
        real_match is not None and real_match.confidence == "high",
    )

    print("\nTest 10: Regression test for the SAVOIR FAIRE/GOMEI and AT&T/OSTEC false positives "
          "found in live-mode output (junk matches driven entirely by common industry words)")
    # Real entity names/programs observed in the live SDN list that
    # caused these false positives before IDF weighting.
    gomei = SanctionsEntry(ent_num="l1", name="GOMEI AIR SERVICES CO., LTD.", sdn_type="Entity", program="SDGT] [IFSR")
    ostec = SanctionsEntry(ent_num="l2", name="OSTEC ENTERPRISE LTD", sdn_type="Entity", program="RUSSIA-EO14024")
    corpus13 = padded_corpus(
        [gomei, ostec],
        [("SERVICES", 25), ("ENTERPRISE", 20), ("LTD", 20), ("CO", 15)],
    )
    idf13 = build_token_idf(corpus13)

    savoir_match = best_sanctions_match("SAVOIR FAIRE SERVICES LLC", corpus13, idf_table=idf13)
    check(
        "'SAVOIR FAIRE SERVICES LLC' no longer matches 'GOMEI AIR SERVICES CO., LTD.' "
        "once SERVICES is correctly weighted as a common, low-signal token (previously 76.9% on raw token_sort_ratio)",
        savoir_match is None,
    )

    att_match = best_sanctions_match("AT&T ENTERPRISES, LLC", corpus13, idf_table=idf13)
    check(
        "'AT&T ENTERPRISES, LLC' no longer matches 'OSTEC ENTERPRISE LTD' "
        "once ENTERPRISE(S) is correctly weighted as a common, low-signal token (previously 75.0% on raw token_sort_ratio)",
        att_match is None,
    )

    print("\nTest 11: Country-of-concern weighting -- same name/confidence, different country, different score")
    from risk_engine import score_contractor
    from models import ContractorProfile

    def flat_contractor(name):
        # No NAICS, low concentration -- isolates the sanctions+country
        # contribution so the comparison below is apples to apples.
        return ContractorProfile(
            recipient_name=name, total_award_value=1000, award_count=1,
            naics_codes=[], naics_descriptions=[], largest_award_value=100,
            awarding_sub_agencies=[],
        )

    same_entry_name = "GLOBAL FICTIONAL HOLDINGS LTD"
    concern_entries = [SanctionsEntry(ent_num="8001", name=same_entry_name, sdn_type="Entity", program="TEST")]
    other_entries = [SanctionsEntry(ent_num="8002", name=same_entry_name, sdn_type="Entity", program="TEST")]
    unknown_entries = [SanctionsEntry(ent_num="8003", name=same_entry_name, sdn_type="Entity", program="TEST")]
    addr_map = {"8001": ["Russia"], "8002": ["Brazil"]}  # 8003 deliberately absent -> unknown

    sc_concern = score_contractor(flat_contractor(same_entry_name), concern_entries, addr_map)
    sc_other = score_contractor(flat_contractor(same_entry_name), other_entries, addr_map)
    sc_unknown = score_contractor(flat_contractor(same_entry_name), unknown_entries, addr_map)

    check("Country-of-concern match (Russia) scores higher than another foreign country (Brazil), all else equal",
          sc_concern.risk_score > sc_other.risk_score)
    check("A resolved-but-not-of-concern country (Brazil) scores higher than an unresolved one",
          sc_other.risk_score > sc_unknown.risk_score)
    check("Country-of-concern bonus is exactly +30 over the unknown-country baseline",
          sc_concern.risk_score - sc_unknown.risk_score == 30)
    check("Other-foreign-country bonus is exactly +5 over the unknown-country baseline",
          sc_other.risk_score - sc_unknown.risk_score == 5)

    print("\nTest 12: Remarks parsing extracts only known, real OFAC phrasing -- never invents a country")
    from country_attribution import parse_countries_from_remarks

    check("'nationality Russia;' -> ['Russia']",
          parse_countries_from_remarks("DOB 1980; nationality Russia; citizen Russia;") == ["Russia"])
    check("'Nationality of Registration Korea, North;' -> ['North Korea'] (comma-containing country handled)",
          parse_countries_from_remarks("Nationality of Registration Korea, North;") == ["North Korea"])
    check("'citizen China;' -> ['China']",
          parse_countries_from_remarks("Additional Sanctions Information; citizen China; all offices worldwide.") == ["China"])
    check("Remarks with no nationality/citizen phrasing -> [] (not a guess)",
          parse_countries_from_remarks("Website www.example.com; all offices worldwide.") == [])
    check("Empty remarks -> []", parse_countries_from_remarks("") == [])

    print("\nTest 13: ADD.CSV join keeps every known address/country for an entity, not just the first")
    from country_attribution import resolve_country

    multi_address_entry = SanctionsEntry(ent_num="7001", name="MULTI OFFICE TRADING LTD", sdn_type="Entity", program="TEST")
    multi_addr_map = {"7001": ["Switzerland", "Iran", "Panama"]}
    attribution = resolve_country(multi_address_entry, multi_addr_map)
    check("All 3 known addresses are kept, not just the first",
          attribution.countries == ["Switzerland", "Iran", "Panama"])
    check("Concern-country detection works even when the concern country isn't the first address listed",
          attribution.is_country_of_concern and attribution.concern_countries == ["Iran"])

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULT: All checks passed. The pipeline correctly aggregates real-schema")
        print("award data, resolves country attribution only from real OFAC data (never")
        print("guessing), and scores foreign nexus -- weighted by country of concern -- as")
        print("the dominant, and only independent, risk signal.")
        sys.exit(0)


if __name__ == "__main__":
    main()
