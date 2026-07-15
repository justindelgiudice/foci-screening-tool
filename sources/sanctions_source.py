"""
sources/sanctions_source.py

Real data source: U.S. Treasury OFAC Sanctions List Service (SLS).

Live endpoint (documented, free, no auth required):
    https://sanctionslistservice.ofac.treas.gov/api/download/SDN.CSV

This module provides two ways to get sanctions data:

  1. fetch_live_sdn_list() - hits the REAL Treasury endpoint above with
     `requests`. This is fully functional production code. It will work
     when you run this project on your own machine (or any environment
     with normal internet access).

  2. load_demo_sdn_list() - loads a small LOCAL, CLEARLY-LABELED demo
     file (data/demo_sanctions_sample.csv). This exists because the
     sandboxed environment this project was originally built in only
     allows outbound network access to a small allowlist of coding
     domains (pypi, github, npm, etc.) -- NOT to treasury.gov. The demo
     file is fictional/illustrative data, NOT a real, current snapshot
     of any government sanctions list. Never treat it as authoritative.

Both paths return the data in the same normalized format so the rest
of the pipeline doesn't care which one was used.
"""

import csv
import io
import os
from dataclasses import dataclass

# Real, documented Treasury OFAC Sanctions List Service endpoint.
# See: https://sanctionslistservice.ofac.treas.gov (official Treasury SLS)
LIVE_SDN_CSV_ENDPOINT = "https://sanctionslistservice.ofac.treas.gov/api/download/SDN.CSV"

# OFAC's SDN.CSV column layout, per their published data specification:
# ent_num, SDN_Name, SDN_Type, SDN_Program, Title, Call_Sign, Vess_type,
# Tonnage, GRT, Vess_flag, Vess_owner, Remarks
SDN_CSV_COLUMNS = [
    "ent_num", "sdn_name", "sdn_type", "sdn_program", "title",
    "call_sign", "vess_type", "tonnage", "grt", "vess_flag",
    "vess_owner", "remarks",
]

_DEMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "demo_sanctions_sample.csv")


@dataclass
class SanctionsEntry:
    ent_num: str
    name: str
    sdn_type: str
    program: str
    remarks: str = ""


def _parse_sdn_csv_text(csv_text: str) -> list:
    """Parse raw OFAC SDN.CSV text (no header row) into SanctionsEntry objects."""
    entries = []
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if not row or len(row) < 4:
            continue
        padded = row + [""] * (len(SDN_CSV_COLUMNS) - len(row))
        record = dict(zip(SDN_CSV_COLUMNS, padded))
        entries.append(SanctionsEntry(
            ent_num=record["ent_num"].strip(),
            name=record["sdn_name"].strip(),
            sdn_type=record["sdn_type"].strip(),
            program=record["sdn_program"].strip(),
            remarks=record.get("remarks", "").strip(),
        ))
    return entries


def fetch_live_sdn_list(timeout_seconds: int = 30) -> list:
    """
    REAL production fetch. Hits the live Treasury OFAC SLS endpoint and
    returns the current SDN list as a list of SanctionsEntry.

    Requires the `requests` library and outbound internet access to
    sanctionslistservice.ofac.treas.gov. This will work on a normal
    machine; it is not runnable inside the restricted sandbox this
    project was authored in.
    """
    import requests  # local import so demo mode never requires it to be network-capable
    response = requests.get(LIVE_SDN_CSV_ENDPOINT, timeout=timeout_seconds)
    response.raise_for_status()
    return _parse_sdn_csv_text(response.text)


def load_demo_sdn_list() -> list:
    """
    Load the small, fictional, clearly-labeled demo sanctions dataset
    bundled with this project (data/demo_sanctions_sample.csv), for
    offline testing and demonstration. NOT real sanctions data.
    """
    with open(_DEMO_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    # Demo file has a header row (unlike the real raw SDN.CSV), so skip it.
    lines = text.splitlines()
    reader = csv.DictReader(lines)
    entries = []
    for row in reader:
        entries.append(SanctionsEntry(
            ent_num=row["ent_num"].strip(),
            name=row["sdn_name"].strip(),
            sdn_type=row["sdn_type"].strip(),
            program=row["sdn_program"].strip(),
            remarks=row.get("remarks", "").strip(),
        ))
    return entries


def get_sanctions_list(mode: str = "demo") -> list:
    """Convenience dispatcher. mode is 'demo' or 'live'."""
    if mode == "live":
        return fetch_live_sdn_list()
    return load_demo_sdn_list()
