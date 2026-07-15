"""
report.py

Renders the terminal dashboard: one summary block per contractor plus
an overall summary line.
"""

_BAR_WIDTH = 78

_FLAG = {
    "PASS": "[PASS]",
    "REVIEW RECOMMENDED": "[REVIEW]",
    "INVESTIGATE FURTHER": "[FLAGGED]",
}


def _score_bar(score: int) -> str:
    filled = round(score / 100 * 30)
    return "#" * filled + "-" * (30 - filled)


def render_contractor_report(scored) -> str:
    c = scored.contractor
    lines = []
    lines.append("=" * _BAR_WIDTH)
    lines.append(f"CONTRACTOR: {c.recipient_name}")
    lines.append(
        f"DoD Awards Tracked: {c.award_count}   "
        f"Total Value: ${c.total_award_value:,.0f}   "
        f"Largest Single Award: ${c.largest_award_value:,.0f} "
        f"({c.concentration_ratio * 100:.1f}% concentration)"
    )
    lines.append(f"NAICS Codes: {', '.join(c.naics_codes) if c.naics_codes else 'n/a'}")
    lines.append(f"Awarding Sub-Agencies: {', '.join(c.awarding_sub_agencies) if c.awarding_sub_agencies else 'n/a'}")

    if scored.sanctions_match is not None:
        m = scored.sanctions_match
        concern_flag = " [COUNTRY OF CONCERN]" if m.country.is_country_of_concern else ""
        lines.append("-" * _BAR_WIDTH)
        lines.append(f"MATCHED ENTITY COUNTRY: {m.country.display}{concern_flag}")
        lines.append(
            f"SANCTIONS MATCH DETAIL: entity='{m.matched_entity_name}'   "
            f"list/program='{m.matched_entity_program}'   "
            f"raw similarity={m.similarity_score}%   "
            f"tier={m.confidence}"
        )

    lines.append("-" * _BAR_WIDTH)
    lines.append(f"RISK SCORE: {scored.risk_score}/100   [{_score_bar(scored.risk_score)}]")
    flag = _FLAG.get(scored.recommendation, scored.recommendation)
    lines.append(f"RECOMMENDATION: {flag} {scored.recommendation}")
    if scored.headline_reason:
        lines.append(f"REASON: {scored.headline_reason}")

    if scored.findings:
        lines.append("-" * _BAR_WIDTH)
        lines.append("FINDINGS:")
        for f in scored.findings:
            lines.append(f"  (+{f.points:>3}) {f.category}")
            lines.append(f"        {f.description}")
    else:
        lines.append("-" * _BAR_WIDTH)
        lines.append("FINDINGS: None detected.")

    lines.append("=" * _BAR_WIDTH)
    return "\n".join(lines)


def render_full_report(scored_contractors: list, data_mode: str) -> str:
    header = [
        "#" * _BAR_WIDTH,
        "DEFENSE CONTRACTOR FOREIGN-EXPOSURE DASHBOARD".center(_BAR_WIDTH),
        f"Data mode: {data_mode.upper()}".center(_BAR_WIDTH),
        "#" * _BAR_WIDTH,
        "",
    ]
    if data_mode == "demo":
        header.append(
            "NOTE: Running in DEMO mode -- contractor and sanctions data below is "
            "fictional/illustrative, bundled for offline testing. Run with --mode live "
            "(on a machine with normal internet access) to screen real USAspending.gov "
            "contract data against the real OFAC sanctions list.\n"
        )

    body = "\n\n".join(render_contractor_report(sc) for sc in scored_contractors)

    flagged = [sc for sc in scored_contractors if sc.recommendation != "PASS"]
    summary = [
        "",
        "-" * _BAR_WIDTH,
        f"SUMMARY: {len(scored_contractors)} contractors screened, "
        f"{len(flagged)} flagged for review or investigation.",
        "-" * _BAR_WIDTH,
    ]
    return "\n".join(header) + body + "\n".join(summary)
