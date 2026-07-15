"""
sources/sanctions_source.py

Real data source: U.S. Treasury OFAC Sanctions List Service (SLS).

Live endpoints (documented, free, no auth required):
    https://sanctionslistservice.ofac.treas.gov/api/download/SDN.CSV
    https://sanctionslistservice.ofac.treas.gov/api/download/ADD.CSV

This module provides two ways to get sanctions data:

  1. fetch_live_sdn_list() / fetch_live_add_list() - hit the REAL
     Treasury endpoints above with `requests`. Fully functional
     production code. Work when you run this project on your own
     machine (or any environment with normal internet access).

  2. load_demo_sdn_list() / load_demo_add_list() - load small LOCAL,
     CLEARLY-LABELED demo files (data/demo_sanctions_sample.csv,
     data/demo_add_sample.csv). This exists because the sandboxed
     environment this project was originally built in only allows
     outbound network access to a small allowlist of coding domains
     (pypi, github, npm, etc.) -- NOT to treasury.gov. The demo files
     are fictional/illustrative data, NOT a real, current snapshot of
     any government sanctions list. Never treat them as authoritative.

Both paths return the data in the same normalized format so the rest
of the pipeline doesn't care which one was used.

ADD.CSV is OFAC's address file: one row per known address for an SDN
entity, joined back to SDN.CSV on ent_num. An entity can have zero,
one, or several address rows (e.g. multiple known offices) -- that's
real data, not a data-quality issue, so get_address_countries() returns
*all* countries found per ent_num rather than picking one arbitrarily.
"""

import csv
import io
import os
from collections import defaultdict
from dataclasses import dataclass

# Real, documented Treasury OFAC Sanctions List Service endpoints.
# See: https://sanctionslistservice.ofac.treas.gov (official Treasury SLS)
LIVE_SDN_CSV_ENDPOINT = "https://sanctionslistservice.ofac.treas.gov/api/download/SDN.CSV"
LIVE_ADD_CSV_ENDPOINT = "https://sanctionslistservice.ofac.treas.gov/api/download/ADD.CSV"

# OFAC's SDN.CSV column layout, per their published data specification:
# ent_num, SDN_Name, SDN_Type, SDN_Program, Title, Call_Sign, Vess_type,
# Tonnage, GRT, Vess_flag, Vess_owner, Remarks
SDN_CSV_COLUMNS = [
    "ent_num", "sdn_name", "sdn_type", "sdn_program", "title",
    "call_sign", "vess_type", "tonnage", "grt", "vess_flag",
    "vess_owner", "remarks",
]

# OFAC's ADD.CSV column layout, per their published data specification:
# Ent_num, Add_num, Address, City_State_Province_Postal_Code, Country, Add_remarks
ADD_CSV_COLUMNS = [
    "ent_num", "add_num", "address",
    "city_state_province_postal_code", "country", "add_remarks",
]

_DEMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "demo_sanctions_sample.csv")
_DEMO_ADD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "demo_add_sample.csv")


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


# matcher.py's IDF weighting needs a corpus large enough for common
# legal-suffix tokens to show up at a realistic frequency -- the real
# live SDN list (~19,000 entries) provides that naturally, but the 4
# hand-authored demo entries in data/demo_sanctions_sample.csv don't (a
# word absent from all 4 gets treated as maximally rare, which distorts
# demo-mode confidence tiers). Rather than bloating that small,
# readable, hand-authored fixture with dozens of filler rows, this
# padding is generated in code and clearly labeled as synthetic -- it
# is not even fictional-illustrative business data, just word-frequency
# filler so demo mode's IDF math behaves the way live mode's does.
_DEMO_PADDING_SUFFIX_COUNTS = [("INC", 25), ("LLC", 20), ("LTD", 20), ("CORP", 10)]


def _generate_demo_padding_entries() -> list:
    entries = []
    i = 0
    for suffix, count in _DEMO_PADDING_SUFFIX_COUNTS:
        for _ in range(count):
            i += 1
            entries.append(SanctionsEntry(
                ent_num=f"9900{i}",
                name=f"PADDING FILLER{i} WORD{i} {suffix}",
                sdn_type="entity",
                program="DEMO-PADDING",
                remarks=(
                    "SYNTHETIC CORPUS PADDING -- not a real or even fictional-illustrative "
                    "business; exists only to give demo-mode IDF token weighting realistic "
                    "word-frequency statistics. See sources/sanctions_source.py."
                ),
            ))
    return entries


def load_demo_sdn_list() -> list:
    """
    Load the small, fictional, clearly-labeled demo sanctions dataset
    bundled with this project (data/demo_sanctions_sample.csv), for
    offline testing and demonstration. NOT real sanctions data.

    Also appends synthetic, clearly-labeled corpus padding (see
    _generate_demo_padding_entries()) so IDF-weighted matching has
    enough data to behave the way it does against the real live list.
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
    entries.extend(_generate_demo_padding_entries())
    return entries


def get_sanctions_list(mode: str = "demo") -> list:
    """Convenience dispatcher. mode is 'demo' or 'live'."""
    if mode == "live":
        return fetch_live_sdn_list()
    return load_demo_sdn_list()


def _parse_add_csv_text(csv_text: str) -> dict:
    """
    Parse raw OFAC ADD.CSV text (no header row) into {ent_num: [country, ...]}.
    "-0-" is OFAC's own placeholder for an empty field.
    """
    countries_by_ent = defaultdict(list)
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if not row or len(row) < 5:
            continue
        padded = row + [""] * (len(ADD_CSV_COLUMNS) - len(row))
        record = dict(zip(ADD_CSV_COLUMNS, padded))
        ent_num = record["ent_num"].strip()
        country = record["country"].strip()
        if ent_num and country and country != "-0-":
            countries_by_ent[ent_num].append(country)
    return dict(countries_by_ent)


def fetch_live_add_list(timeout_seconds: int = 30) -> dict:
    """
    REAL production fetch. Hits the live Treasury OFAC SLS address
    endpoint and returns {ent_num: [country, ...]} for every SDN entity
    that has at least one known address on file.

    Requires the `requests` library and outbound internet access to
    sanctionslistservice.ofac.treas.gov.
    """
    import requests  # local import so demo mode never requires it to be network-capable
    response = requests.get(LIVE_ADD_CSV_ENDPOINT, timeout=timeout_seconds)
    response.raise_for_status()
    return _parse_add_csv_text(response.text)


def load_demo_add_list() -> dict:
    """
    Load the small, fictional, clearly-labeled demo address dataset
    bundled with this project (data/demo_add_sample.csv), for offline
    testing and demonstration. NOT real OFAC address data.
    """
    with open(_DEMO_ADD_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    lines = text.splitlines()
    reader = csv.DictReader(lines)
    countries_by_ent = defaultdict(list)
    for row in reader:
        ent_num = row["ent_num"].strip()
        country = row.get("country", "").strip()
        if ent_num and country:
            countries_by_ent[ent_num].append(country)
    return dict(countries_by_ent)


def get_address_countries(mode: str = "demo") -> dict:
    """Convenience dispatcher. mode is 'demo' or 'live'. Returns {ent_num: [country, ...]}."""
    if mode == "live":
        return fetch_live_add_list()
    return load_demo_add_list()
