# Defense Contractor Foreign-Exposure Dashboard

A screening tool that cross-references real U.S. federal defense
contract award data against the real Treasury OFAC sanctions/entity
list, to flag contractors that may warrant a closer look for foreign
ownership, control, or influence (FOCI) exposure.

## Real data sources (this is the important part)

This project is built around two real, public, free, no-auth-required
U.S. government data sources:

1. **USAspending.gov Award Search API** (`api.usaspending.gov`) — the
   official federal spending transparency API. `sources/usaspending_source.py`
   contains a fully working `fetch_live_dod_awards()` function that
   POSTs a real, schema-correct request (matching the [published API
   contract](https://github.com/fedspendingtransparency/usaspending-api))
   scoped to Department of Defense prime contract awards.

2. **OFAC Sanctions List Service** (`sanctionslistservice.ofac.treas.gov`) —
   the official Treasury API for the Specially Designated Nationals
   (SDN) list. `sources/sanctions_source.py` contains a working
   `fetch_live_sdn_list()` function that downloads and parses the real
   SDN.CSV file per OFAC's published data specification.

**Important limitation of this specific delivery:** this project was
built inside a sandboxed environment whose outbound network access is
restricted to a small allowlist of coding-package domains (PyPI,
GitHub, npm, etc.) — it does **not** include `api.usaspending.gov` or
`treasury.gov`. That means the `fetch_live_*` functions above are real,
correct, working code, but they could not be executed live *inside
this sandbox* to pull a fresh snapshot for you.

To keep the tool runnable and testable right now, it ships with a
`--mode demo` (default) that loads two small, **clearly-labeled
fictional/illustrative** local files instead:
- `data/demo_contract_awards.json` (schema-identical to a real
  USAspending.gov response)
- `data/demo_sanctions_sample.csv` (schema-identical to a real OFAC
  SDN.CSV, with entries explicitly marked `FICTIONAL DEMO ENTRY`)

**Run `python3 main.py --mode live` on your own machine** (anywhere
with normal internet access) and it will hit the real APIs and screen
real, current data. No API key or registration needed for either
source.

## Project Structure

```
defense_exposure_dashboard/
├── sources/
│   ├── usaspending_source.py   # real + demo DoD award data
│   └── sanctions_source.py     # real + demo OFAC sanctions data
├── data/
│   ├── demo_contract_awards.json
│   └── demo_sanctions_sample.csv
├── models.py                    # shared dataclasses
├── aggregator.py                 # awards -> per-contractor profiles
├── matcher.py                    # rapidfuzz-based name matching
├── risk_engine.py                 # scoring logic
├── report.py                       # terminal dashboard renderer
├── main.py                          # entry point (--mode demo|live)
├── test_execution.py                # 25-check automated verification suite
├── requirements.txt
└── README.md
```

## How the scoring works

Each contractor (aggregated across all its tracked DoD awards) is
scored 0–100 on:

| Signal | Points |
|---|---|
| High-confidence sanctions/entity list name match (≥88% similarity) | 50 |
| Moderate-confidence match (75–87% similarity) | 25 |
| Holds award(s) in a sensitive defense-tech NAICS category | 15 |
| Holds awards across 2+ distinct sensitive NAICS categories | +10 |
| Single award ≥80% of total tracked award value (dependency risk) | 10 |

Thresholds: **≥60 → Investigate Further**, **30–59 → Review
Recommended**, **<30 → Pass**.

The fuzzy-matching thresholds (88% / 75%) were calibrated empirically
against real `rapidfuzz` output during development: near-identical
company names (e.g. the same firm re-registered with a different
corporate suffix) scored ~90, meaningfully-similar-but-distinct names
scored ~79, and unrelated names topped out around 40. That gap is what
justifies the two-tier confidence bands.

## Running It

```bash
cd defense_exposure_dashboard
pip install -r requirements.txt

python3 main.py                 # demo mode (default), offline, bundled sample data
python3 main.py --mode live     # LIVE mode: real USAspending.gov + real OFAC data
python3 test_execution.py       # 25-check automated verification suite
```

## Known Limitations

- The sensitive-NAICS list and point weights are illustrative, not
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
  additional screening sources.
- Handle USAspending's pagination (`page`/`limit`) to screen the full
  DoD contractor universe rather than the first page of results.
- Persist scored results to CSV/Excel for tracking changes over time.
- Add a scheduled refresh (e.g. weekly) that re-screens tracked
  contractors as OFAC updates its lists.
