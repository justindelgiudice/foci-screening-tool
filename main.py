"""
main.py

Entry point. Fetches DoD award data + sanctions/entity list data,
aggregates awards into contractor profiles, screens each contractor,
and prints the terminal dashboard.

Usage:
    python3 main.py                 # demo mode (default) -- offline, bundled sample data
    python3 main.py --mode live     # LIVE mode -- real USAspending.gov + real OFAC data
                                     # (requires `requests` and normal internet access;
                                     #  will not work inside this project's original
                                     #  restricted-network sandbox)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources.usaspending_source import get_awards
from sources.sanctions_source import get_sanctions_list
from aggregator import build_contractor_profiles
from risk_engine import score_all
from report import render_full_report


def run(mode: str = "demo"):
    awards = get_awards(mode=mode)
    sanctions_entries = get_sanctions_list(mode=mode)

    contractors = build_contractor_profiles(awards)
    scored = score_all(contractors, sanctions_entries)
    # Sort highest risk first so the most important findings are on top.
    scored.sort(key=lambda sc: sc.risk_score, reverse=True)

    print(render_full_report(scored, data_mode=mode))
    return scored


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Defense Contractor Foreign-Exposure Dashboard")
    parser.add_argument(
        "--mode", choices=["demo", "live"], default="demo",
        help="'demo' (default) uses bundled offline sample data. 'live' hits the real "
             "USAspending.gov and OFAC APIs (requires internet access)."
    )
    args = parser.parse_args()
    run(mode=args.mode)
