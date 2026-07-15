# Defense Contractor Foreign-Exposure Dashboard — Project Writeup

## What it does

A screening tool that cross-references U.S. federal defense contract
award data against the Treasury OFAC sanctions/entity list, flagging
contractors whose name resembles a sanctioned entity, who hold awards
in sensitive defense-tech categories, or who depend heavily on a
single award. It aggregates awards per contractor, scores each one
0-100, and prints a terminal dashboard sorted highest-risk first.

It is a triage aid, not an adjudication tool: it narrows a large
contractor list down to a short list worth a human's attention.

## Real data sources

1. **USAspending.gov Award Search API** (`api.usaspending.gov`) — the
   official federal spending transparency API. `sources/usaspending_source.py`
   POSTs a schema-correct request scoped to Department of Defense
   prime contract awards.
2. **OFAC Sanctions List Service** (`sanctionslistservice.ofac.treas.gov`)
   — the official Treasury API for the Specially Designated Nationals
   (SDN) list. `sources/sanctions_source.py` downloads and parses the
   real `SDN.CSV` file.

Both are free, public, no-auth-required. A `--mode demo` (default)
also exists, backed by small local fixture files (`data/demo_contract_awards.json`,
`data/demo_sanctions_sample.csv`) for offline testing; `--mode live`
hits the real endpoints.

## Architecture

```
sources/
  usaspending_source.py   # live + demo DoD award data
  sanctions_source.py     # live + demo OFAC SDN data
data/
  demo_contract_awards.json
  demo_sanctions_sample.csv
models.py                 # shared dataclasses (ContractorProfile, SanctionsMatch,
                           #   RiskFinding, ScoredContractor)
aggregator.py              # raw awards -> one profile per contractor
matcher.py                  # rapidfuzz name matching, contractor vs. SDN list
risk_engine.py                # combines match + NAICS + concentration into a score
report.py                      # terminal dashboard renderer
main.py                         # entry point (--mode demo|live)
test_execution.py               # automated verification suite
```

Pipeline: `get_awards()` → `build_contractor_profiles()` →
`score_all()` (which calls `best_sanctions_match()` per contractor) →
`render_full_report()`.

## How the risk scoring works

Each contractor is scored 0-100:

| Signal | Points |
|---|---|
| High-confidence sanctions match (≥88% similarity) | 50 |
| Moderate-confidence match (75-87%) | 25 |
| Award(s) in a sensitive defense-tech NAICS category | 15 |
| Awards across 2+ sensitive NAICS categories | +10 |
| Single award ≥80% of total tracked value | 10 |

Thresholds: ≥60 → **Investigate Further**, 30-59 → **Review
Recommended**, <30 → **Pass**.

Name matching uses `rapidfuzz.fuzz.token_sort_ratio`. The 88%/75%
thresholds were set from a small empirical read of real output during
development (near-identical re-registered names scored ~90, distinct
names topped out ~40) — not calibrated against a real historical FOCI
case set.

## Findings: the false-positive problem

Running `--mode live` against real USAspending + OFAC data surfaced
two flagged contractors that don't hold up on inspection:

| Contractor | Matched SDN entity | Program | Similarity | Tier |
|---|---|---|---|---|
| CFM INTERNATIONAL INC | IAC INTERNATIONAL INC. | SDNTK | 88.4% | high |
| RTX CORPORATION | RIF CORPORATION | RUSSIA-EO14024 | 86.7% | moderate |

**CFM International** is the real GE/Safran jet engine joint venture.
**RTX Corporation** is Raytheon's post-2023 corporate rebrand. Neither
has any actual connection to the matched SDN entries — "CFM" and "IAC"
share no letters; "RTX" and "RIF" share one. `token_sort_ratio` scored
these pairs high almost entirely because both names also contain
`INTERNATIONAL INC` or `CORPORATION`, which is boilerplate, not
signal.

**Why it happens:** `token_sort_ratio` scores similarity across the
whole token set. When a large fraction of a short company name is a
generic corporate-form word, that word dominates the score, and the
distinctive part of the name (the part that would actually indicate a
real relationship) gets diluted. Short names are hit hardest because
boilerplate is a bigger share of the total token count.

**What I did:** added `_normalize_for_matching()` in `matcher.py`,
which strips a fixed set of legal-suffix tokens — `INC`, `LLC`,
`CORP`, `CORPORATION`, `INTERNATIONAL`, `CO`, `LTD`, `GROUP`,
`HOLDINGS` — from both names before scoring (display strings are
untouched; only the scoring input changes). Re-running live confirmed
CFM International and RTX both drop to a clean PASS. A regression
test (`test_execution.py`, Test 9) locks this in, alongside a check
that stripping doesn't suppress a genuine near-identical match.

**Why this doesn't fully solve it:** the same live re-run immediately
produced new borderline (75-82%) matches on a different axis — pairs
like `MICROTECHNOLOGIES LLC` / `SECRET TECHNOLOGIES` and `FLUKE
ELECTRONICS CORP` / `MILUR ELECTRONICS LLC`, driven by generic
industry words (`TECHNOLOGIES`, `ELECTRONICS`, `SYSTEMS`, `SOLUTIONS`,
`SERVICES`, `ENGINEERING`, `GLOBAL`, `COMMUNICATIONS`) that aren't
legal suffixes and so aren't on the stripped list. A stopword list can
only ever cover words known in advance to be non-distinctive; the
universe of generic-but-plausible business vocabulary is open-ended,
and stripping more of it aggressively risks eating real signal (e.g. a
genuine shell company literally named after its parent's industry).
There is no fixed list that converges to zero false positives on
`token_sort_ratio` over free-text company names — the underlying
approach only ever produces a candidate list for human review, never a
confirmed hit.

## What I'd build next

- Weight matches by the length/rarity of the overlapping tokens
  (e.g. IDF-style weighting) instead of a binary stopword list, so
  common industry words contribute less to the score without being
  hard-coded.
- Add a secondary corroborating signal before flagging on name alone —
  address overlap, registered-agent overlap, or DUNS/UEI cross-reference
  where available — so a name match alone can't reach the
  "Investigate Further" tier.
- Pull OFAC's Consolidated Sanctions List and the BIS Entity List in
  addition to the SDN list.
- Handle USAspending pagination to screen the full DoD contractor
  universe, not just the first page.
- Persist scored results over time to catch changes as OFAC updates
  its lists, rather than only ever showing a point-in-time snapshot.
