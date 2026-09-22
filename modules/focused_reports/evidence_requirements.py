"""Minimum fact declarations, not new evidence builders or astrology rules.

Sources were inspected for their actual outputs. Natal positions, house/lord
facts and full MD/AD sequences exist for any fully specified person. Transit
primitives supply sign boundaries and dated motion. Career collectors select
these declared facts. No prediction/strength score is required for interpretation.
"""
from modules.focused_reports.prompt_contract import EvidenceRequirement as R

NATAL_SOURCE = ("full_kundali_api.py:calculate_full_kundali",)
HOUSE_SOURCE = ("summary_blocks.py:build_house_lord_facts",)
DASHA_SOURCE = ("summary_blocks.py:_build_dasha_window_summary",)
TRANSIT_SOURCE = ("transit_engine.py:get_current_sign_residency",
                  "transit_engine.py:get_next_12_rashi_segments",
                  "smart_transit_engine.py:get_planet_position_on")

NATAL = R("birth_chart_summary", "Birth Chart Summary", "Natal Lagna and planet sign/house placements.",
          ("summary_blocks.py:build_summary_blocks_with_transit",))
HOUSES = R("house_lord_summary", "House & Lord Facts", "Relevant houses including empty houses, signs and lord placements.", HOUSE_SOURCE)
CAREER = R("career_yoga_summary", "Career-Yoga Evidence", "Only the existing computed career yogas, never invented yogas.",
           ("summary_blocks.py:_build_career_yoga_summary",))
WEALTH = R("wealth_yoga_summary", "Financial Indications", "Existing computed wealth-yoga facts, not guaranteed wealth.",
           ("summary_blocks.py:_build_wealth_yoga_summary",))
MD_AD = R("dasha_window_summary", "Current Dasha Window", "Current MD/AD and available upcoming MD/AD windows with dates.", DASHA_SOURCE)
LONG_DASHA = R("dasha_sequence", "Dasha Timeline", "Full supplied multi-year MD/AD sequence, not just the next two sub-periods.",
               ("summary_blocks.py:_flatten_dasha_sequence",))
JUPITER = R("Jupiter", "Relevant Transits", "Jupiter sign residence, house from natal Lagna and separate motion periods.", TRANSIT_SOURCE, "transits")
SATURN = R("Saturn", "Relevant Transits", "Saturn sign residence, house from natal Lagna and separate motion periods.", TRANSIT_SOURCE, "transits")
RAHU = R("Rahu", "Relevant Transits", "Rahu sign residence and supported motion facts, houses from natal Lagna.", TRANSIT_SOURCE, "transits")
USER_NATAL = R("user_natal", "Your Natal Facts", "Primary person's natal positions and relevant house/lord facts.", NATAL_SOURCE + HOUSE_SOURCE)
PARTNER_NATAL = R("partner_natal", "Partner Natal Facts", "Partner's own natal positions and house/lord facts from their full birth data.", NATAL_SOURCE + HOUSE_SOURCE)
KOOTAS = R("compatibility_facts", "Compatibility Facts", "Existing Ashtakoot factors with actual component scores, not a new relationship score.",
           ("modules/love/ashtakoot_love.py:compute_ashtakoot",))
DUAL_DASHA = R("both_dasha_windows", "Both Dasha Windows", "Separately attributed MD/AD windows for both full birth charts.",
               ("summary_blocks.py:_flatten_dasha_sequence",))
DUAL_TRANSIT = R("both_relevant_transits", "Both Transit Contexts", "Jupiter/Saturn residence and motion mapped separately to each natal Lagna.", TRANSIT_SOURCE)

# Selecting relevant factors is Luna's interpretation of existing facts, not
# an approved deterministic prediction mapping or a new backend yoga engine.
PROMOTION = (NATAL, HOUSES, CAREER, MD_AD, JUPITER, SATURN, RAHU)
CAREER_TIMING = PROMOTION
MONEY_TIMING = (NATAL, HOUSES, WEALTH, MD_AD, JUPITER, SATURN)
BUSINESS_TIMING = (NATAL, HOUSES, CAREER, WEALTH, MD_AD, JUPITER, SATURN)
MARRIAGE_TIMING = (NATAL, HOUSES, MD_AD, JUPITER, SATURN)
FOREIGN_TIMING = (NATAL, HOUSES, MD_AD, JUPITER, SATURN, RAHU)
EDUCATION_TIMING = (NATAL, HOUSES, MD_AD, JUPITER, SATURN)
PROPERTY_TIMING = (NATAL, HOUSES, MD_AD, JUPITER, SATURN)
LIFE_TIMING = (NATAL, HOUSES, LONG_DASHA, JUPITER, SATURN)
NATAL_DIRECTION = (NATAL, HOUSES)
DUAL_COMPARISON = (USER_NATAL, PARTNER_NATAL, KOOTAS)
DUAL_TIMING = DUAL_COMPARISON + (DUAL_DASHA, DUAL_TRANSIT)
