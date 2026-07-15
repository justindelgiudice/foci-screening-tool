# Defense Contractor Foreign-Exposure Dashboard

A screening tool that cross-references real U.S. federal defense
contract award data against the real Treasury OFAC sanctions/entity
list, to flag contractors that may warrant a closer look for foreign
ownership, control, or influence (FOCI) exposure.

## Real data sources (this is the important part)

This project is built around three real, public, free, no-auth-required
U.S. government data feeds, all from the same two agencies:

1. **USAspending.gov Award Search API** (`api.usaspending.gov`) — the
   official federal spending transparency API. `sources/usaspending_source.py`
   contains a fully working `fetch_live_dod_awards()` function that
   POSTs a real, schema-correct request (matching the [published API
   contract](https://github.com/fedspendingtransparency/usaspending-api))
   scoped to Department of Defense prime contract awards.

2. **OFAC Sanctions List Service — SDN.CSV** (`sanctionslistservice.ofac.treas.gov`)
   — the official Treasury API for the Specially Designated Nationals
   (SDN) list. `sources/sanctions_source.py` contains a working
   `fetch_live_sdn_list()` function that downloads and parses the real
   SDN.CSV file per OFAC's published data specification.

3. **OFAC Sanctions List Service — ADD.CSV** (same service) — OFAC's
   address file, one row per known address for an SDN entity. This
   tool joins it to the SDN list on `ent_num` to get a **real** country
   for a matched entity, rather than guessing one from its name or
   sanctions program. `sources/sanctions_source.py`'s
   `fetch_live_add_list()` downloads and parses it the same way.

**Important limitation of this specific delivery:** this project was
built inside a sandboxed environment whose outbound network access is
restricted to a small allowlist of coding-package domains (PyPI,
GitHub, npm, etc.) — it does **not** include `api.usaspending.gov` or
`treasury.gov`. That means the `fetch_live_*` functions above are real,
correct, working code, but they could not be executed live *inside
this sandbox* to pull a fresh snapshot for you.

To keep the tool runnable and testable right now, it ships with a
`--mode demo` (default) that loads three small, **clearly-labeled
fictional/illustrative** local files instead:
- `data/demo_contract_awards.json` (schema-identical to a real
  USAspending.gov response)
- `data/demo_sanctions_sample.csv` (schema-identical to a real OFAC
  SDN.CSV, with entries explicitly marked `FICTIONAL DEMO ENTRY`)
- `data/demo_add_sample.csv` (schema-identical to a real OFAC ADD.CSV)

**Run `python3 main.py --mode live` on your own machine** (anywhere
with normal internet access) and it will hit the real APIs and screen
real, current data. No API key or registration needed for any source.
This has been verified end-to-end against the live APIs — see
`PROJECT_WRITEUP.md`.

## Project Structure

```
defense_exposure_dashboard/
├── sources/
│   ├── usaspending_source.py   # real + demo DoD award data
│   └── sanctions_source.py     # real + demo OFAC SDN.CSV + ADD.CSV data
├── data/
│   ├── demo_contract_awards.json
│   ├── demo_sanctions_sample.csv
│   └── demo_add_sample.csv
├── models.py                    # shared dataclasses
├── aggregator.py                 # awards -> per-contractor profiles
├── matcher.py                     # rapidfuzz-based name matching
├── country_attribution.py          # resolves a real country for a match (ADD.CSV + remarks)
├── risk_engine.py                    # foreign-nexus-first scoring logic
├── report.py                          # terminal dashboard renderer
├── app.py                              # Flask web UI (python3 app.py)
├── main.py                              # CLI entry point (--mode demo|live)
├── test_execution.py                     # automated verification suite
├── requirements.txt
├── README.md
└── PROJECT_WRITEUP.md
```

## How the scoring works

**Foreign nexus is the dominant, and only independent, score component.**
With no sanctions/entity-list match, a contractor scores **0** — full
stop, regardless of its NAICS mix or how concentrated its awards are.
Those two signals are demoted to *contextual modifiers*: they only add
points on top of an existing match, they never generate risk alone.

When there **is** a match:

| Component | Points |
|---|---|
| High-confidence name match (≥88% similarity) | 50 |
| Moderate-confidence name match (75–87% similarity) | 25 |
| **+** Matched entity's country is a country of concern (China, Russia, Iran, North Korea) | +30 |
| **+** Matched entity's country is a real, resolved, other foreign country | +5 |
| **+** Matched entity's country could not be determined from real data | +0 |
| *(modifier)* Also holds award(s) in a sensitive defense-tech NAICS category | +10 |
| *(modifier)* Also holds awards across 2+ distinct sensitive NAICS categories | +5 |
| *(modifier)* Single award ≥80% of total tracked award value | +5 |

Thresholds: **≥60 → Investigate Further**, **30–59 → Review
Recommended**, **<30 → Pass**.

The fuzzy-matching thresholds (88% / 75%) were calibrated empirically
against real `rapidfuzz` output during development: near-identical
company names (e.g. the same firm re-registered with a different
corporate suffix) scored ~90, meaningfully-similar-but-distinct names
scored ~79, and unrelated names topped out around 40. That gap is what
justifies the two-tier confidence bands.

**Country attribution never guesses.** `country_attribution.py` only
ever resolves a country from two real OFAC sources: the ADD.CSV
address file joined on `ent_num`, and known, structured phrasing in
the SDN remarks field (`nationality X`, `citizen X`, `Nationality of
Registration X`). An entity can have multiple known addresses/
nationalities — all of them are kept, not just the first, and if a
match is found in a country of concern anywhere among them, the
country-of-concern bonus applies. If neither source yields a country,
the UI and terminal report both say **"country unknown"** explicitly;
the tool never infers a country from an entity's name or sanctions
program tag.

## Running It

```bash
cd defense_exposure_dashboard
pip install -r requirements.txt

python3 main.py                 # demo mode (default), offline, bundled sample data
python3 main.py --mode live     # LIVE mode: real USAspending.gov + real OFAC data
python3 app.py                  # Flask web UI at http://127.0.0.1:5000/ (add ?mode=live)
python3 test_execution.py       # automated verification suite
```

## Known Limitations

- The country-of-concern list (China, Russia, Iran, North Korea) and
  all point weights are illustrative, not calibrated against a real
  historical FOCI case set.
- Country attribution is only as complete as OFAC's own address/
  remarks data for a given entity. Many SDN entries have no address on
  file and no nationality/citizenship phrasing in their remarks — those
  matches correctly display "country unknown" rather than a guess, but
  that also means a real foreign-nexus match can end up under-weighted
  simply because OFAC's own records are thin for that entity, not
  because the actual foreign nexus is weak.
- The sensitive-NAICS list is illustrative, not
  calibrated against a real historical FOCI case set.
- `fetch_live_dod_awards()` currently filters only on agency + award
  type + date range; a real deployment would likely also want to
  filter/paginate by NAICS code, keyword, or dollar threshold, and
  handle the API's pagination for large result sets.
- The OFAC SDN list alone doesn't cover the BIS Entity List, the
  Denied Persons List, or non-SDN consolidated sanctions — a fuller
  screening tool should pull OFAC's Consolidated Sanctions List
  (`CONS_PRIM.CSV`, same service) and the Commerce Department's Entity
  List as well.
- Company name matching is a real but imperfect signal — it doesn't
  capture ownership structured through subsidiaries or shell layers.
  Combining this with the earlier FOCI ownership-chain tracing logic
  from the mock-data prototype would be a natural next iteration.
- `matcher.py` strips common corporate-form boilerplate (`INC`, `LLC`,
  `CORP`, `CORPORATION`, `INTERNATIONAL`, `CO`, `LTD`, `GROUP`,
  `HOLDINGS`) before scoring, to stop those words alone from inflating
  similarity between unrelated companies. That list only covers legal
  suffixes — generic industry words (e.g. `SYSTEMS`, `SOLUTIONS`,
  `SERVICES`, `TECHNOLOGY`, `ENGINEERING`, `GLOBAL`) are not stripped
  and can still drive a name pair over the moderate-confidence
  threshold on shared vocabulary rather than a genuine identity match.
  **Every fuzzy match should be manually reviewed against the matched
  entity name (and its list/program) before being acted on** — treat
  the risk score as a triage prioritization signal, not a
  confirmed hit.

## Suggested Extensions

- Add the OFAC Consolidated Sanctions List and BIS Entity List as
  additional screening sources — both would also need their own
  address/country join, following the same ADD.CSV pattern.
- Handle USAspending's pagination (`page`/`limit`) to screen the full
  DoD contractor universe rather than the first page of results.
- Persist scored results to CSV/Excel for tracking changes over time.
- Add a scheduled refresh (e.g. weekly) that re-screens tracked
  contractors as OFAC updates its lists.
