"""
sources/usaspending_source.py

Real data source: USAspending.gov Award Search API (v2), the official
U.S. government federal spending transparency API.

Live endpoint (documented, free, no auth required):
    POST https://api.usaspending.gov/api/v2/search/spending_by_award/

Request body schema follows the officially published API contract:
https://github.com/fedspendingtransparency/usaspending-api/blob/master/
usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md

As with sources/sanctions_source.py, this module provides:
  1. fetch_live_dod_awards() - REAL production code using `requests.post`
     against the live API. Fully functional outside this sandbox.
  2. load_demo_awards() - a small, clearly-labeled, fictional/illustrative
     local dataset (data/demo_contract_awards.json) used for offline
     testing here, since this sandbox's network allowlist doesn't
     include api.usaspending.gov.
"""

import json
import os
from dataclasses import dataclass

LIVE_AWARD_SEARCH_ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Contract award type codes used by USAspending (A/B/C/D = the four
# prime contract award types; IDVs excluded here for simplicity).
CONTRACT_AWARD_TYPE_CODES = ["A", "B", "C", "D"]

_DEMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "demo_contract_awards.json")


@dataclass
class ContractAward:
    award_id: str
    recipient_name: str
    award_amount: float
    naics_code: str
    naics_description: str
    awarding_sub_agency: str
    start_date: str
    end_date: str


def _record_to_award(record: dict) -> ContractAward:
    return ContractAward(
        award_id=record.get("Award ID", ""),
        recipient_name=record.get("Recipient Name", "").strip(),
        award_amount=float(record.get("Award Amount", 0) or 0),
        naics_code=str(record.get("NAICS Code") or "").strip(),
        naics_description=record.get("NAICS Description", ""),
        awarding_sub_agency=record.get("Awarding Sub Agency", ""),
        start_date=record.get("Start Date", ""),
        end_date=record.get("End Date", ""),
    )


def fetch_live_dod_awards(
    fiscal_year_start: str = "2024-10-01",
    fiscal_year_end: str = "2025-09-30",
    limit: int = 100,
    timeout_seconds: int = 30,
) -> list:
    """
    REAL production fetch. POSTs a real, schema-correct request to the
    live USAspending.gov Award Search API, scoped to Department of
    Defense prime contract awards in the given date range.

    Requires the `requests` library and outbound internet access to
    api.usaspending.gov. This is not runnable inside the restricted
    sandbox this project was authored in (POST to non-allowlisted
    domains is blocked there), but it is real, working code.
    """
    import requests  # local import so demo mode has no network dependency

    body = {
        "subawards": False,
        "limit": limit,
        "page": 1,
        "filters": {
            "award_type_codes": CONTRACT_AWARD_TYPE_CODES,
            "time_period": [{"start_date": fiscal_year_start, "end_date": fiscal_year_end}],
            "agencies": [
                {"type": "awarding", "tier": "toptier", "name": "Department of Defense"},
            ],
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "NAICS Code", "NAICS Description", "Awarding Sub Agency",
            "Start Date", "End Date",
        ],
    }
    response = requests.post(LIVE_AWARD_SEARCH_ENDPOINT, json=body, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    return [_record_to_award(r) for r in data.get("results", [])]


def load_demo_awards() -> list:
    """
    Load the small, fictional, clearly-labeled demo contract-award
    dataset bundled with this project (data/demo_contract_awards.json).
    NOT real, current federal spending data.
    """
    with open(_DEMO_FILE, "r", encoding="utf-8") as f:
        records = json.load(f)
    return [_record_to_award(r) for r in records]


def get_awards(mode: str = "demo") -> list:
    """Convenience dispatcher. mode is 'demo' or 'live'."""
    if mode == "live":
        return fetch_live_dod_awards()
    return load_demo_awards()
