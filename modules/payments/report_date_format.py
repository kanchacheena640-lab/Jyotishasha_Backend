# modules/payments/report_date_format.py

"""
report_date_format.py -- Paid Report Platform: the ONE shared, central
customer-facing date presentation layer (Q3 Batch 1, redesigned in Q5.6B).

CONTRACT
  Internal / database / API / calculation dates stay canonical ISO
  "YYYY-MM-DD" everywhere. Only what a CUSTOMER sees in a paid-report PDF
  is converted here, by language:

      English : 31 March 1985             (D Month YYYY)
      Hindi   : 31 मार्च 1985              (D <Hindi month> YYYY)
      range   : 15 October 2026 to 20 April 2027
                15 अक्टूबर 2026 से 20 अप्रैल 2027

  No leading zero on the day, ASCII digits, unknown language -> English.
  Numeric day/month formats (31/03/1985, 31-03-1985, 03/31/1985) are
  never produced: they are ambiguous between countries.

PRINCIPLE: ISO IN, HUMAN OUT AT THE PRESENTATION LAYER
  Luna is asked to COPY supplied dates exactly as given; it is never the
  presentation authority. The shared renderer (pdf_generator_weasy.py)
  runs normalize_customer_payload() over all customer-visible text, and
  the deterministic components (report_q3_batch1/2/5) format their own
  ranges with the report language.

SAFETY
  * Presentation ONLY -- nothing here touches, recomputes or re-validates
    a canonical date, and no timezone conversion is ever performed (a
    datetime is shown as its own calendar date).
  * Strict: only real calendar dates are converted (2026-02-30 is left
    untouched). Deterministic and idempotent (converted text contains no
    ISO date, so running twice is a no-op).
  * The free-text normalizer rewrites ONLY standalone valid ISO dates and
    never URLs, e-mail addresses, timestamps, ISO intervals, IDs, version
    strings, phone numbers, prices, degrees or other numbers.
  * Numeric slash dates (e.g. 03/04/2025) are deliberately NOT
    reinterpreted; count/report them with numeric_slash_date_fields().
  * Never raises: an unparseable input is returned unchanged.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Optional

EN_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
HI_MONTHS = (
    "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
    "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
)

_RANGE_WORDS = {
    "en": {"to": "to", "from": "from", "until": "until"},
    "hi": {"to": "से", "from": "से", "until": "तक"},
}

# A complete structured ISO date string (calendar validity is checked separately).
_ISO_DATE_STRING = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _language_key(language) -> str:
    """'hi' for Hindi (incl. 'hi-IN'), otherwise English (unknown -> English)."""
    return "hi" if str(language or "").strip().lower().startswith("hi") else "en"


def _in_words(day: date, language) -> str:
    months = HI_MONTHS if _language_key(language) == "hi" else EN_MONTHS
    return f"{day.day} {months[day.month - 1]} {day.year}"


def format_customer_date(value, language: str = "en") -> str:
    """Canonical 'YYYY-MM-DD' string (or a date/datetime object) ->
    customer-facing 'D Month YYYY' (English) / 'D <Hindi month> YYYY'
    (Hindi). None -> ''. An invalid calendar date (2026-02-30), an
    already-formatted string, or anything unparseable is returned
    unchanged as a plain string -- never raises. A datetime is shown as
    its own calendar date (no timezone conversion)."""
    if isinstance(value, datetime):
        return _in_words(value.date(), language)
    if isinstance(value, date):
        return _in_words(value, language)
    if isinstance(value, str):
        match = _ISO_DATE_STRING.fullmatch(value.strip())
        if match:
            try:
                return _in_words(date(int(match[1]), int(match[2]), int(match[3])), language)
            except ValueError:
                return value
        return value
    if value is None:
        return ""
    return str(value)


def format_customer_date_range(start, end, language: str = "en") -> Optional[str]:
    """Formats a start/end pair together:
        English: '15 October 2026 to 20 April 2027'
        Hindi  : '15 अक्टूबर 2026 से 20 अप्रैल 2027'
    Open-ended ranges: 'from <start>' / 'until <end>' (Hindi '<start> से' /
    '<end> तक'). Returns None if BOTH start and end are falsy (nothing
    to show) -- matches every other optional-component convention in
    this codebase (None = render nothing)."""
    if not start and not end:
        return None
    is_hindi = _language_key(language) == "hi"
    words = _RANGE_WORDS["hi" if is_hindi else "en"]
    first = format_customer_date(start, language) if start else ""
    last = format_customer_date(end, language) if end else ""
    if first and last:
        return f"{first} {words['to']} {last}"
    if first:
        return f"{first} {words['from']}" if is_hindi else f"{words['from']} {first}"
    return f"{last} {words['until']}" if is_hindi else f"{words['until']} {last}"


# ---------------------------------------------------------------------------
# Free-text normalizer (Luna narrative, hero text, component text)
# ---------------------------------------------------------------------------
# A standalone, strictly valid ISO calendar date. It must not be glued to
# other word / URL / identifier characters (order IDs, versions, e-mail,
# path segments), must not be part of a timestamp ("2026-10-15T10:30",
# "2026-10-15 10:30") and must not be one end of ISO interval syntax
# ("2026-10-15/2027-04-20", "2026-10-15..2027-04-20", "2026-10-15--...").
_LEFT_GUARD = r"(?<![0-9A-Za-z_./@#%$\-])(?<!\d:)"
_RIGHT_GUARD = r"(?![0-9A-Za-z_@\-/%]|:\d|\.\d|\.\.| \d{2}:\d{2})"
_ISO_TOKEN = re.compile(
    _LEFT_GUARD + r"((?:19|20)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])" + _RIGHT_GUARD
)
# URLs and e-mail addresses are opaque: nothing inside them is ever rewritten
# (this also protects ISO-looking query values such as "?d=2026-10-15").
_PROTECTED_SEGMENT = re.compile(
    r"(?:https?://|www\.)[^\s<>\"')\]]+|[\w.+-]+@[\w-]+\.[\w.-]+"
)


def normalize_customer_dates(text, language: str = "en"):
    """Rewrite ONLY standalone, valid ISO calendar dates inside free text:
        'From 2026-10-15 to 2027-04-20.' -> 'From 15 October 2026 to 20 April 2027.'
    Invalid calendar dates, URLs, e-mails, timestamps, ISO intervals, IDs,
    version strings, phone numbers, prices, degrees and every other
    numeric pattern are left exactly as they are. Numeric slash dates
    (03/04/2025) are NOT interpreted. Idempotent. Non-strings are
    returned unchanged."""
    if not isinstance(text, str) or not text:
        return text

    def convert(match: "re.Match[str]") -> str:
        try:
            return _in_words(date(int(match[1]), int(match[2]), int(match[3])), language)
        except ValueError:
            return match[0]

    parts = []
    position = 0
    for protected in _PROTECTED_SEGMENT.finditer(text):
        parts.append(_ISO_TOKEN.sub(convert, text[position:protected.start()]))
        parts.append(protected.group(0))
        position = protected.end()
    parts.append(_ISO_TOKEN.sub(convert, text[position:]))
    return "".join(parts)


def normalize_customer_payload(obj, language: str = "en"):
    """Recursively apply normalize_customer_dates() to every string VALUE
    in a customer-facing payload (strings, lists, tuples, dicts). Keys,
    structure and every non-string value are preserved. Returns a COPY;
    the source object is never mutated."""
    if isinstance(obj, str):
        return normalize_customer_dates(obj, language)
    if isinstance(obj, dict):
        return {key: normalize_customer_payload(value, language) for key, value in obj.items()}
    if isinstance(obj, list):
        return [normalize_customer_payload(item, language) for item in obj]
    if isinstance(obj, tuple):
        return tuple(normalize_customer_payload(item, language) for item in obj)
    return obj


# ---------------------------------------------------------------------------
# Diagnostic (never a failure): numeric slash dates left in customer text
# ---------------------------------------------------------------------------
_NUMERIC_SLASH_DATE = re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}/(?:19|20)\d{2}(?![\d/])")


def _count_numeric_slash_dates(obj) -> int:
    if isinstance(obj, str):
        return len(_NUMERIC_SLASH_DATE.findall(obj))
    if isinstance(obj, dict):
        return sum(_count_numeric_slash_dates(value) for value in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_count_numeric_slash_dates(item) for item in obj)
    return 0


def numeric_slash_date_fields(fields: Dict[str, Any]) -> Dict[str, int]:
    """{field_name: how many numeric slash dates (e.g. '03/04/2025') remain}
    for every field that still contains one. Used ONLY for a non-fatal
    warning: it returns field names and counts, never the customer's text
    or dates (no PII)."""
    counts = {name: _count_numeric_slash_dates(value) for name, value in (fields or {}).items()}
    return {name: count for name, count in counts.items() if count}
