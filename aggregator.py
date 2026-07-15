"""
aggregator.py

Turns a flat list of ContractAward records (from sources/usaspending_source.py)
into one ContractorProfile per unique recipient name.
"""

from collections import defaultdict
from models import ContractorProfile


def build_contractor_profiles(awards: list) -> list:
    by_recipient = defaultdict(list)
    for award in awards:
        by_recipient[award.recipient_name].append(award)

    profiles = []
    for recipient_name, recipient_awards in by_recipient.items():
        total_value = sum(a.award_amount for a in recipient_awards)
        largest = max(a.award_amount for a in recipient_awards)
        naics_codes = sorted({a.naics_code for a in recipient_awards if a.naics_code})
        naics_descriptions = sorted({a.naics_description for a in recipient_awards if a.naics_description})
        sub_agencies = sorted({a.awarding_sub_agency for a in recipient_awards if a.awarding_sub_agency})
        profiles.append(ContractorProfile(
            recipient_name=recipient_name,
            total_award_value=total_value,
            award_count=len(recipient_awards),
            naics_codes=naics_codes,
            naics_descriptions=naics_descriptions,
            largest_award_value=largest,
            awarding_sub_agencies=sub_agencies,
            awards=recipient_awards,
        ))
    return profiles
