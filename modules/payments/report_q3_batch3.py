# modules/payments/report_q3_batch3.py

"""
report_q3_batch3.py -- Paid Report Platform, Q3 Batch 3.

Product-specific wiring for the 6 career/money/business products
(financial_report, financial_stability_report, career_report,
government_job_report, business_report, startup_suggestion_report).
Mirrors report_q3_batch1.py/report_q3_batch2.py's own established
precedent exactly: a small, per-batch sibling module holding only what
that batch's products need, never a second parallel Q3 framework.

Deliberately thinner than Batch 1/2's own helpers, for a real reason:
none of these 6 products override the answer_hero VALUE
deterministically. All 6 keep hero_value_source="ai" -- there is no
deterministic financial/career/business SCORE or CLASSIFIER anywhere
in this codebase (confirmed in the Q3 Batch 3 audit) to source a
deterministic value from, exactly the same situation Q3 Batch 2's
marriage_report/delay_in_marriage_report were already in. So this
module introduces no compute_*_hero() function at all -- there is
nothing for one to deterministically compute.

Timing: all 6 products reuse modules/payments/report_q3_batch2.py::
compute_dasha_window_timeline() UNCHANGED -- tasks.py imports it
directly from report_q3_batch2, not re-exported here, to avoid
pointless indirection. This module does not duplicate that function.

Deterministic wealth/career yoga evidence: lives in summary_blocks.py
(_build_wealth_yoga_summary()/_build_career_yoga_summary(), returned
as the new wealth_yoga_summary/career_yoga_summary context keys) --
NOT duplicated here either. Which of the two (or both) a given
product's prompt actually uses is entirely a matter of which
{wealth_yoga_summary}/{career_yoga_summary} placeholder that product's
own prompt file references -- str.format(**summary_blocks) already
ignores any key a template doesn't name, so no Python-level per-product
selection code is needed for this at all.

This module's one genuine, non-trivial piece of Batch-3-specific logic
is BATCH3_PRODUCT_SLUGS below -- used by tasks.py's own
`elif product_slug in BATCH3_PRODUCT_SLUGS:` timeline-wiring branch,
the same shape already used for Batch 2's 2-product timeline branch.

No new astrology calculation, no career/finance/government/business/
startup scoring, no job-vs-business classifier, no exact event timing
-- none of that exists anywhere in this module, by design.
"""

from __future__ import annotations

BATCH3_PRODUCT_SLUGS = frozenset({
    "financial_report",
    "financial_stability_report",
    "career_report",
    "government_job_report",
    "business_report",
    "startup_suggestion_report",
})
