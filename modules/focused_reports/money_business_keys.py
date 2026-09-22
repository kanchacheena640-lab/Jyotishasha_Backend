"""Explicit registrations; new catalog rows never enable generation implicitly."""
MONEY_QUESTION_KEYS = (
    "financial_improvement_timing", "income_increase_timing", "money_growth_periods",
    "financial_pressure_easing", "debt_pressure_easing",
)
BUSINESS_QUESTION_KEYS = (
    "business_start_timing", "business_growth_timing", "best_business_periods",
    "business_expansion_timing", "business_slowdown_easing", "new_venture_partnership_timing",
)
MONEY_BUSINESS_QUESTION_KEYS = MONEY_QUESTION_KEYS + BUSINESS_QUESTION_KEYS
MULTI_YEAR_KEYS = ("money_growth_periods", "best_business_periods")
