# Defense Contractor Foreign-Exposure Dashboard — Project Writeup

## What it does

A screening tool that cross-references U.S. federal defense contract
award data against the Treasury OFAC sanctions/entity list, scoring
contractors primarily on **foreign nexus**: whether a contractor's name
matches a sanctioned entity, and, if so, what country that entity is
really tied to. It aggregates awards per contractor, scores each one
0-100, and renders results as a terminal dashboard or a Flask web UI,
sorted highest-risk first.

It is a triage aid, not an adjudication tool: it narrows a large
contractor list down to a short list worth a human's attention.

## Real data sources

1. **USAspending.gov Award Search API** (`api.usaspending.gov`) — the
   official federal spending transparency API. `sources/usaspending_source.py`
   POSTs a schema-correct request scoped to Department of Defense
   prime contract awards.
2. **OFAC Sanctions List Service — SDN.CSV** (`sanctionslistservice.ofac.treas.gov`)
   — the official Treasury API for the Specially Designated Nationals
   (SDN) list. `sources/sanctions_source.py` downloads and parses the
   real `SDN.CSV` file.
3. **OFAC Sanctions List Service — ADD.CSV** (same service) — OFAC's
   address file. Joined to the SDN list on `ent_num` to get a real
   country for a matched entity. `sources/sanctions_source.py` also
   downloads and parses this file.

All three are free, public, no-auth-required. A `--mode demo` (default)
also exists, backed by small local fixture files (`data/demo_contract_awards.json`,
`data/demo_sanctions_sample.csv`, `data/demo_add_sample.csv`) for
offline testing; `--mode live` hits the real endpoints.

## Architecture

```
sources/
  usaspending_source.py   # live + demo DoD award data
  sanctions_source.py     # live + demo OFAC SDN.CSV + ADD.CSV data
data/
  demo_contract_awards.json
  demo_sanctions_sample.csv
  demo_add_sample.csv
models.py                  # shared dataclasses (ContractorProfile, SanctionsMatch,
                            #   CountryAttribution, RiskFinding, ScoredContractor)
aggregator.py               # raw awards -> one profile per contractor
matcher.py                   # rapidfuzz name matching, contractor vs. SDN list
country_attribution.py        # resolves a real country for a match (ADD.CSV + remarks)
risk_engine.py                  # foreign-nexus-first scoring
report.py                        # terminal dashboard renderer
app.py                             # Flask web UI
main.py                             # CLI entry point (--mode demo|live)
test_execution.py                    # automated verification suite
```

Pipeline: `get_awards()` + `get_sanctions_list()` + `get_address_countries()`
→ `build_contractor_profiles()` → `score_all()` (which calls
`best_sanctions_match()`, which calls `resolve_country()`, per
contractor) → `render_full_report()` / Flask template.

## How the risk scoring works

**Foreign nexus is the dominant, and only independent, score
component.** With no sanctions/entity-list match, a contractor scores
**0** regardless of its NAICS mix or award concentration. Those two
signals are demoted to contextual *modifiers* — they only ever add
points on top of an existing match:

| Component | Points |
|---|---|
| High-confidence name match (≥88% similarity) | 50 |
| Moderate-confidence name match (75-87%) | 25 |
| **+** matched entity's country is a country of concern (China, Russia, Iran, North Korea) | +30 |
| **+** matched entity's country is a real, resolved, other foreign country | +5 |
| **+** matched entity's country could not be determined from real data | +0 |
| *(modifier)* also holds award(s) in a sensitive defense-tech NAICS category | +10 |
| *(modifier)* also holds awards across 2+ sensitive NAICS categories | +5 |
| *(modifier)* single award ≥80% of total tracked value | +5 |

Thresholds: ≥60 → **Investigate Further**, 30-59 → **Review
Recommended**, <30 → **Pass**.

Name matching uses `rapidfuzz.fuzz.token_sort_ratio`. The 88%/75%
thresholds were set from a small empirical read of real output during
development (near-identical re-registered names scored ~90, distinct
names topped out ~40) — not calibrated against a real historical FOCI
case set.

Country attribution (`country_attribution.py`) only ever pulls from
two real OFAC sources — the ADD.CSV address join and known remarks
phrasing (`nationality X`, `citizen X`, `Nationality of Registration
X`) — and explicitly reports **"country unknown"** rather than
inferring one from the entity's name or sanctions program tag when
neither source has an answer.

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

## Findings: restructuring around foreign nexus

The original scoring model treated a sanctions match, sensitive-NAICS
exposure, and award concentration as three independent, additive
signals — meaning a contractor with no sanctions match at all could
still land in REVIEW purely on NAICS mix + concentration (this is
exactly what happened to MERIDIAN PHOTONICS GROUP INC in the demo
data: 2 sensitive NAICS codes + 100% concentration scored 35/100 with
zero foreign-nexus evidence). That doesn't match what this tool is
supposed to measure — foreign ownership, control, or influence — so
NAICS and concentration are now demoted to *modifiers* that only ever
add points on top of an existing match. With no match, the score is
exactly 0, full stop. `test_execution.py` Test 7 locks this in as the
core invariant.

The country data backing the concern-country weighting comes from a
real join, not an assumption: `sources/sanctions_source.py` now also
fetches OFAC's `ADD.CSV` (the address file) and joins it to the SDN
list on `ent_num`. Re-running `--mode live` after this change surfaced
a real-world case worth noting: **SAVOIR FAIRE SERVICES LLC** matched
`GOMEI AIR SERVICES CO., LTD.` at 76.9%, and that entity has *two*
separate real address records on file — one in Hong Kong, one in
mainland China. The join correctly keeps both (`countries = ["Hong
Kong", "China"]`) rather than picking one arbitrarily, and correctly
flags the match as a country of concern because China is among the
resolved countries even though it isn't the only one. Country
attribution also correctly refused to guess where OFAC's own data
didn't support one: **AHTNA GLOBAL LLC**'s match had no address record
and no nationality/citizenship phrasing in its remarks, so it displays
as "country unknown" rather than inferring a country from the entity's
name or sanctions program tag — even though the entity's SDN program
tag alone might have tempted a guess.

**Limitation worth flagging honestly:** country attribution is only as
good as OFAC's own address/remarks data for a given entity. Plenty of
SDN entries have no address on file and no nationality phrasing at
all — those matches are correctly labeled "country unknown," but that
also means a real foreign-nexus match can end up under-weighted (0
country bonus instead of +30) simply because OFAC's records are thin
for that particular entity, not because the actual foreign nexus is
weak. This tool would rather under-weight an unresolved case than
guess a country and risk asserting something OFAC's own data doesn't
support.

## Findings: IDF weighting and the limits of name matching

The corporate-boilerplate stopword list (previous section) fixed matches
driven by legal-form suffixes, but the very next live run surfaced the
same failure mode one level up: two more junk matches driven entirely by
common *industry* words that were never on the stopword list because
they aren't legal suffixes.

| Contractor | Matched SDN entity | Program | Similarity | Driven entirely by |
|---|---|---|---|---|
| SAVOIR FAIRE SERVICES LLC | GOMEI AIR SERVICES CO., LTD. | SDGT] [IFSR | 76.9% | `SERVICES` |
| AT&T ENTERPRISES, LLC | OSTEC ENTERPRISE LTD | RUSSIA-EO14024 | 75.0% | `ENTERPRISE(S)` |

`SAVOIR`/`FAIRE` share nothing with `GOMEI`/`AIR`; `AT&T` shares nothing
with `OSTEC`. A maintained stopword list can never close this class of
false positive, because the set of generic-but-plausible business words
(`SERVICES`, `ENTERPRISE`, `SYSTEMS`, `SOLUTIONS`, `TECHNOLOGIES`,
`GLOBAL`, `COMMUNICATIONS`, ...) is open-ended.

**What I did:** replaced the stopword list entirely with inverse-document-
frequency (IDF) token weighting, computed once per run directly from the
sanctions list itself (`matcher.build_token_idf()`). A token's weight is
inversely proportional to how many SDN entity names contain it — no
maintained list, just real corpus statistics. Matching stays fast at
~19,000 entries via a two-phase design: a cheap `token_sort_ratio` pass
picks a candidate shortlist, then the (more expensive, per-token) IDF-
weighted score is computed only for that shortlist. Verified: `build_token_idf`
over the full live SDN list takes 0.03s; the whole live run (award fetch +
SDN fetch + ADD.CSV fetch + scoring 67 contractors) takes ~6s, unchanged
from before the IDF change.

**Result:** re-running `--mode live` dropped flagged contractors from
**11 to 3**.

**But all 3 remaining flags are still explainable as artifacts, not real
signal** — I checked each one by hand rather than trusting the score:

| Contractor | Matched entity | Country | Similarity | Distinctive-token char similarity |
|---|---|---|---|---|
| AGVIQ LLC | AVIV LLC | Russia | 77.5% | `AGVIQ` vs `AVIV` = 67% |
| CFM INTERNATIONAL INC | IAC INTERNATIONAL INC. | United States | 76.4% | `CFM` vs `IAC` = 33% |
| MICROTECHNOLOGIES LLC | ALEL TECHNOLOGIES LLC | United States | 81.5% | `MICRO` vs `ALEL` = 0% |

- **CFM/IAC and MICRO/ALEL** are residual versions of the exact problem
  IDF weighting targets: `INTERNATIONAL`/`INC`/`TECHNOLOGIES`/`LLC` are
  common but not *maximally* common in the real ~19,000-entry corpus, so
  they still carry enough leftover weight to clear the 75% floor when the
  distinctive tokens (`CFM`/`IAC`, `MICRO`/`ALEL`) contribute almost
  nothing. IDF demoted these from INVESTIGATE/high-confidence hits to
  weak REVIEW-tier scores (35 and 30), but didn't fully zero them out.
- **AGVIQ/LLC vs AVIV/LLC** looked, at first pass, like the one case
  worth taking seriously — 67% character overlap between two short,
  unusual, foreign-sounding tokens is a real, non-coincidental signal by
  the matcher's own logic, and the match resolved to Russia (a country
  of concern), pushing it to INVESTIGATE. But **AGVIQ is a real, known
  Alaska Native Corporation** — a U.S. 8(a) entity, part of the same ANC
  family as UIC and Bowhead — not a Russia-linked firm. The name
  similarity is a genuine short-string coincidence, and no amount of
  better token weighting fixes that: `AGVIQ` and `AVIV` are just
  similar-looking words that belong to unrelated companies. This is
  domain knowledge the matcher has no way to know.

**The plain conclusion: fuzzy name matching alone is insufficient for
FOCI screening.** It detects string similarity, not ownership or
control — and by construction it never can. A perfect fuzzy matcher
still only ever answers "does this name look like that name," which is
neither necessary nor sufficient evidence of a real ownership,
subsidiary, or control relationship. AGVIQ/AVIV is the clean proof: the
match was *algorithmically correct* (67% is a real, meaningful
character-overlap signal, not noise) and still *substantively wrong*,
because the question this tool answers is not the question FOCI
screening actually needs answered.

**What real screening would require, that this tool doesn't have:**
- Beneficial ownership records (e.g. FinCEN beneficial ownership
  information) to trace who actually owns/controls a contractor, not
  just what it's named.
- SAM.gov entity registration data — which includes UEI, immediate and
  ultimate parent/owner fields — to link a contractor to its real
  corporate parent rather than inferring one from name similarity.
- Corporate registry linkage (state Secretary of State filings,
  international equivalents) to verify or refute a suspected connection
  once name matching raises a candidate.

None of that is name-string data, and no amount of better string-
matching substitutes for it.

**This tool's actual value is as a triage filter with mandatory human
review, not an automated verdict.** It correctly does one narrow thing:
turn a large contractor list (67 in this run) into a much smaller
candidate list (3, down from 11) worth a human spending time on. It
cannot, and doesn't claim to, confirm that any of those 3 candidates is
a real hit — and this run is direct proof of that, since a careful
manual check clears all 3.

## What I'd build next

The highest-priority item, by a wide margin, is the one the IDF findings
above make unavoidable: **name matching cannot be the last word, only the
first.**

- Add a real corroborating signal before flagging on name alone — SAM.gov
  entity registration data (UEI, immediate/ultimate owner fields) or
  beneficial ownership records to check whether a name-matched candidate
  has any actual ownership/control link, not just a similar-looking name.
  This is the fix AGVIQ/AVIV actually needs; better string matching
  cannot get there.
- Add corporate registry linkage (state Secretary of State filings,
  international equivalents) as a second corroborating check, so a name
  match alone can never reach the "Investigate Further" tier — it would
  require at least one non-name-based signal to agree.
- Pull OFAC's Consolidated Sanctions List and the BIS Entity List in
  addition to the SDN list, each with their own ADD.CSV-equivalent
  address join for the same real-country attribution.
- When ADD.CSV and remarks both come up empty, consider a clearly-labeled
  lower-confidence fallback (e.g. inferred from the sanctions program's
  typical country nexus) — kept separate from, and visually distinct
  from, the real-data-backed country field, so "unknown" and "inferred"
  are never conflated.
- Handle USAspending pagination to screen the full DoD contractor
  universe, not just the first page.
- Persist scored results over time to catch changes as OFAC updates
  its lists, rather than only ever showing a point-in-time snapshot.
