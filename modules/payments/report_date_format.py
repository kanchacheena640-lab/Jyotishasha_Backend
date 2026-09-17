# modules/payments/report_date_format.py

"""
report_date_format.py -- Paid Report Platform, Q3 Batch 1 (visual QA
correction round).

ONE shared, reusable presentation-layer date formatter for every
customer-facing date in a paid-report PDF (Report Date, DOB,
answer_hero timing, timeline date ranges). Converts the canonical
internal "YYYY-MM-DD" ISO shape (Order.dob's own validated format --
see modules/payments/order_service.py::_validate_dob(); the same shape
smart_transit_engine's entering_date/exit_date already use) to the
customer-facing DD/MM/YYYY shape.

This is presentation ONLY -- it never touches, recomputes, or
re-validates any canonical/internal date value. Nothing upstream of
this module (Order.dob storage, kundali/dasha/transit calculation,
smart_transit_engine's own return shape) changes at all; this is
purely how a date STRING is displayed once it reaches a PDF template.

Never raises: an unparseable input is returned unchanged (as a string)
rather than crashing report generation over a formatting nuance --
this module's own failure mode must always be "look slightly wrong",
never "the report failed to generate."
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

_ISO_FORMAT = "%Y-%m-%d"
_CUSTOMER_FORMAT = "%d/%m/%Y"


def format_customer_date(value) -> str:
    """Canonical 'YYYY-MM-DD' string (or a date/datetime object) ->
    customer-facing 'DD/MM/YYYY' string. Anything else (None, an
    already-non-ISO string, an unparseable value) is returned as a
    plain string unchanged -- never raises."""
    if isinstance(value, (date, datetime)):
        return value.strftime(_CUSTOMER_FORMAT)
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), _ISO_FORMAT).strftime(_CUSTOMER_FORMAT)
        except ValueError:
            return value
    if value is None:
        return ""
    return str(value)


def format_customer_date_range(start, end, separator: str = " – ") -> Optional[str]:
    """Formats a start/end pair together, e.g. '29/03/2025 – 02/06/2027'.
    Returns None if BOTH start and end are falsy (nothing to show) --
    matches every other optional-component convention in this
    codebase (None = render nothing)."""
    if not start and not end:
        return None
    return f"{format_customer_date(start)}{separator}{format_customer_date(end)}"
