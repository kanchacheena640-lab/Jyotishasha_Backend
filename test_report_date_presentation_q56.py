"""
Q5.6B -- global customer date presentation for the 25 paid reports (24 standard_v1 + relationship_future_report/love_premium_v1).

CONTRACT under test (modules/payments/report_date_format.py + the shared renderer):
  internal / DB / API / calculation dates stay ISO "YYYY-MM-DD";
  the CUSTOMER sees  English "31 March 1985"  /  Hindi "31 मार्च 1985"
  ranges             "15 October 2026 to 20 April 2027"  /  "15 अक्टूबर 2026 से 20 अप्रैल 2027".
  Luna copies supplied dates exactly as given (never the presentation authority); the code presents them.

No AI call, no network, no DB, no email, no PDF file (the renderer's HTML->PDF step is patched out; the HTML it would render is inspected).
"""
import copy
import io
import json
import logging
import os
import re
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from modules.payments.report_date_format import (  # noqa: E402
    EN_MONTHS, HI_MONTHS, format_customer_date, format_customer_date_range, normalize_customer_dates,
    normalize_customer_payload, numeric_slash_date_fields,
)
import pdf_generator_weasy as renderer  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def read(path):
    with open(os.path.join(HERE, path), encoding="utf-8") as handle:
        return handle.read()


F, R, N, P = format_customer_date, format_customer_date_range, normalize_customer_dates, normalize_customer_payload
HI_1985 = "31 मार्च 1985"

print("\n=== 1: shared formatter -- format_customer_date(value, language) ===")
check("1: EN 1985-03-31 -> 31 March 1985", F("1985-03-31", "en") == "31 March 1985")
check("1: HI 1985-03-31 -> 31 मार्च 1985", F("1985-03-31", "hi") == HI_1985)
check("1: language defaults to English", F("1985-03-31") == "31 March 1985")
check("1: the 12 English month names are exact", EN_MONTHS == ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"))
check("1: the 12 Hindi month names are exact", HI_MONTHS == ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"))
check("1: every month converts in both languages", all(F(f"2026-{m:02d}-10", "en") == f"10 {EN_MONTHS[m - 1]} 2026" and F(f"2026-{m:02d}-10", "hi") == f"10 {HI_MONTHS[m - 1]} 2026" for m in range(1, 13)))
check("1: no leading zero on the day", F("2027-04-05", "en") == "5 April 2027" and F("2027-04-05", "hi") == "5 अप्रैल 2027")
check("1: digits stay ASCII (no Devanagari digits)", not re.search(r"[०-९]", F("2027-04-05", "hi")))
check("1: leap day 2024-02-29 (EN/HI)", F("2024-02-29", "en") == "29 February 2024" and F("2024-02-29", "hi") == "29 फ़रवरी 2024")
check("1: invalid 2026-02-30 is unchanged (not a valid date)", F("2026-02-30", "en") == "2026-02-30" and F("2026-02-30", "hi") == "2026-02-30")
check("1: invalid 2023-02-29 (non-leap year) is unchanged", F("2023-02-29", "en") == "2023-02-29")
check("1: invalid month/day (2026-13-01, 2026-00-10, 2026-04-31) are unchanged", all(F(v, "en") == v for v in ("2026-13-01", "2026-00-10", "2026-04-31")))
check("1: non-canonical shapes are unchanged (1990-6-5, 31/03/1985, 31-03-1985)", all(F(v, "en") == v for v in ("1990-6-5", "31/03/1985", "31-03-1985")))
check("1: surrounding whitespace on a valid ISO string is tolerated", F(" 1985-03-31 ", "en") == "31 March 1985")
check("1: already formatted text is not damaged (idempotent)", F("31 March 1985", "en") == "31 March 1985" and F(F("1985-03-31", "en"), "en") == "31 March 1985" and F(HI_1985, "hi") == HI_1985)
check("1: year-only 2027 is unchanged", F("2027", "en") == "2027")
check("1: None -> empty string, never raises", F(None, "en") == "")
check("1: unknown / missing / odd language falls back to English", all(F("1985-03-31", lang) == "31 March 1985" for lang in ("fr", "xx", "", None, 5)))
check("1: hi-IN / HI count as Hindi", F("1985-03-31", "hi-IN") == HI_1985 and F("1985-03-31", "HI") == HI_1985)
check("1: date object", F(date(2026, 10, 15), "en") == "15 October 2026" and F(date(2026, 10, 15), "hi") == "15 अक्टूबर 2026")
check("1: datetime object shows ITS OWN calendar date (no timezone conversion)",
      F(datetime(2026, 9, 20, 23, 59, tzinfo=timezone.utc), "en") == "20 September 2026"
      and F(datetime(2026, 9, 20, 23, 59, tzinfo=timezone(timedelta(hours=-8))), "en") == "20 September 2026")
check("1: never raises on odd input", all(isinstance(F(v, "en"), str) for v in (object(), 5, 3.5, [], {}, True)))

print("\n=== 2: date ranges -- format_customer_date_range ===")
check("2: EN range", R("2026-10-15", "2027-04-20", "en") == "15 October 2026 to 20 April 2027")
check("2: HI range", R("2026-10-15", "2027-04-20", "hi") == "15 अक्टूबर 2026 से 20 अप्रैल 2027")
check("2: language defaults to English", R("2026-10-15", "2027-04-20") == "15 October 2026 to 20 April 2027")
check("2: start-only EN / HI", R("2026-10-15", None, "en") == "from 15 October 2026" and R("2026-10-15", "", "hi") == "15 अक्टूबर 2026 से")
check("2: end-only EN / HI", R(None, "2027-04-20", "en") == "until 20 April 2027" and R("", "2027-04-20", "hi") == "20 अप्रैल 2027 तक")
check("2: both missing -> None (component omitted)", R(None, None, "en") is None and R("", "", "hi") is None)
check("2: an invalid end passes through unchanged rather than raising", R("2026-10-15", "2026-02-30", "en") == "15 October 2026 to 2026-02-30")
check("2: date objects work", R(date(2026, 10, 15), date(2027, 4, 20), "hi") == "15 अक्टूबर 2026 से 20 अप्रैल 2027")
check("2: no numeric day/month format is ever produced", not re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", R("2026-10-15", "2027-04-20", "en") + R("2026-10-15", "2027-04-20", "hi")))

print("\n=== 3: free-text normalizer -- normalize_customer_dates ===")
check("3: prose range EN", N("From 2026-10-15 to 2027-04-20.", "en") == "From 15 October 2026 to 20 April 2027.")
check("3: prose range HI", N("2026-10-15 से 2027-04-20 तक", "hi") == "15 अक्टूबर 2026 से 20 अप्रैल 2027 तक")
check("3: sentence-final period", N("It ends on 2026-10-15.", "en") == "It ends on 15 October 2026.")
check("3: comma / semicolon / colon", N("2025-07-01, 2026-01-02; 2027-03-04: done", "en") == "1 July 2025, 2 January 2026; 4 March 2027: done")
check("3: parentheses", N("(2026-10-15)", "en") == "(15 October 2026)")
check("3: markdown bold / italic / bullets / headings / bold-then-colon",
      N("**2025-07-01** to *2027-11-28*\n- 2026-01-02\n3. Period 2026-03-04\n**2026-05-06:** starts", "en")
      == "**1 July 2025** to *28 November 2027*\n- 2 January 2026\n3. Period 4 March 2026\n**6 May 2026:** starts")
check("3: Hindi glued suffix", N("2025-07-01से शुरू", "hi") == "1 जुलाई 2025से शुरू")
check("3: Hindi text before the date", N("तारीख2025-07-01 तक", "hi") == "तारीख1 जुलाई 2025 तक")
check("3: a date at the very start / end of the text", N("2026-10-15", "en") == "15 October 2026" and N("on 2026-10-15", "en") == "on 15 October 2026")
check("3: idempotent -- normalizing twice gives the same result", all(N(N(t, lang), lang) == N(t, lang) for t, lang in (("2026-10-15 to 2027-04-20.", "en"), ("2025-07-01 से 2027-11-28 तक", "hi"), ("nothing here", "en"), ("", "en"))))
check("3: already formatted text is not damaged", N("born on 31 March 1985 and 15 अक्टूबर 2026", "en") == "born on 31 March 1985 and 15 अक्टूबर 2026")
check("3: invalid calendar dates stay untouched", all(N(f"on {v} only", "en") == f"on {v} only" for v in ("2026-02-30", "2023-02-29", "2026-13-01", "2026-04-31", "2026-00-05")))
check("3: a valid and an invalid date in one sentence -> only the valid one converts", N("2026-02-30 and 2026-02-28", "en") == "2026-02-30 and 28 February 2026")
check("3: year-only and month-year text are untouched", N("in 2027, around October 2026 and 2027-", "en") == "in 2027, around October 2026 and 2027-")
check("3: leap day in prose", N("born 2024-02-29", "hi") == "born 29 फ़रवरी 2024")
check("3: empty / None / non-strings are returned unchanged", N("", "en") == "" and N(None, "en") is None and N(5, "en") == 5)

print("\n=== 3b: protected / non-date values are NEVER rewritten ===")
PROTECTED = [
    ("URL path", "see https://www.jyotishasha.com/blog/2026-10-15/post"),
    ("URL query (ISO-looking value)", "https://x.com/?d=2026-10-15&e=1"),
    ("URL fragment / www", "www.example.com/2026-10-15 and http://a.b/c?from=2026-10-15&to=2027-04-20"),
    ("play-store style URL", "https://play.google.com/store/apps/details?id=com.jyotishasha.app&d=2026-10-15"),
    ("e-mail", "write to user2026-10-15@example.com or 2026-10-15@x.io"),
    ("phone numbers", "Call +91 9555-107-203, 011-2345-6789 or +1 (202) 555-0143"),
    ("prices", "Total ₹1,051.00, $2026-10, ₹2,026"),
    ("degrees", "Moon at 19.95° Aquarius and Lagna 2.35° Libra, 13.22"),
    ("koota scores", "Ashtakoot compatibility: 32.5/36, Tara 1.5/3, Nadi 8/8"),
    ("order ids", "Order ORD-2026-10-15-0042 / order_2026-10-15 / #2026-10-15 / REF2026-10-15"),
    ("version strings", "app v2026-10-15.1 build 2026-10-15-rc1 v1.2.3"),
    ("ISO timestamps / time-glued", "created 2026-10-15T10:30:00Z, 2026-10-15T00:00, 2026-10-15 10:30:00, 2026-10-15 19:45, 12:30:2026-10-15, 2026-10-15:10"),
    ("ISO interval syntax", "2026-10-15/2027-04-20 and 2026-10-15--2027-04-20 and 2026-10-15..2027-04-20"),
    ("glued identifier", "REF-2026-10-15X and X2026-10-15 and 2026-10-15_v2"),
    ("decimal / percent", "2026-10-15.5 and 2026-10-15%"),
    ("numeric slash date (ambiguous, NOT reinterpreted)", "on 03/04/2025 and 12/11/2026"),
    ("numeric hyphen date (ambiguous, NOT reinterpreted)", "on 31-03-1985 and 03-04-2025"),
    ("years / ranges of years", "2025-2027 and 1985–1990 and FY2026-27"),
    ("times", "at 19:45 or 07:20 IST"),
    ("plain numbers", "House 7, 32.5 points, 1,051 users, 2027"),
]
for label, text in PROTECTED:
    check(f"3b: unchanged -- {label}", N(text, "en") == text and N(text, "hi") == text)
check("3b: a real date NEXT TO a URL converts, the URL does not",
      N("Valid from 2026-10-15 -- see https://x.com/2026-10-15/a?d=2026-10-15.", "en") == "Valid from 15 October 2026 -- see https://x.com/2026-10-15/a?d=2026-10-15.")
check("3b: a real date NEXT TO an e-mail converts, the e-mail does not", N("On 2026-10-15 mail a2026-10-15@x.io now", "en") == "On 15 October 2026 mail a2026-10-15@x.io now")
_MIXED = [
    ("The current Mercury-Mercury period, from 2025-07-01 to 2027-11-28, favors learning; Saturn at 12.5° (see https://x.com/?d=2026-10-15).",
     "The current Mercury-Mercury period, from 1 July 2025 to 28 November 2027, favors learning; Saturn at 12.5° (see https://x.com/?d=2026-10-15)."),
    ("Order 2026-10-15-9 stays; 2026-10-15 becomes words. ₹51 and 32.5/36 stay.", "Order 2026-10-15-9 stays; 15 October 2026 becomes words. ₹51 and 32.5/36 stay."),
    ("Call 9555-107-203 before 2026-12-31.", "Call 9555-107-203 before 31 December 2026."),
]
check("3b: mixed text -- ONLY the standalone ISO dates change, every other character is preserved exactly",
      all(N(source, "en") == expected for source, expected in _MIXED))

print("\n=== 4: payload normalizer -- normalize_customer_payload ===")
hero = {"label": "Career Outlook", "value": "Steady", "interpretation": "Period 2025-07-01 to 2027-11-28 supports focus.",
        "evidence": ["Mercury runs 2025-07-01 - 2027-11-28", "Score 32.5/36", "Order 2026-10-15-7"], "timing": "2026-10-15 to 2027-04-20", "n": 5, "ok": True, "none": None,
        "nested": {"2026-10-15": ["a 2026-10-15", ("b 2026-10-15",)]}}
before = copy.deepcopy(hero)
out = P(hero, "en")
check("4: the source object is never mutated", hero == before)
check("4: a COPY is returned (new containers)", out is not hero and out["evidence"] is not hero["evidence"] and out["nested"] is not hero["nested"])
check("4: string values are normalized", out["interpretation"] == "Period 1 July 2025 to 28 November 2027 supports focus." and out["timing"] == "15 October 2026 to 20 April 2027")
check("4: list items are normalized, protected ones are not", out["evidence"] == ["Mercury runs 1 July 2025 - 28 November 2027", "Score 32.5/36", "Order 2026-10-15-7"])
check("4: KEYS are never rewritten, even ISO-looking ones", list(out["nested"].keys()) == ["2026-10-15"])
check("4: tuple type and nested values are preserved", out["nested"]["2026-10-15"] == ["a 15 October 2026", ("b 15 October 2026",)] and isinstance(out["nested"]["2026-10-15"][1], tuple))
check("4: non-string values are preserved (int / bool / None)", out["n"] == 5 and out["ok"] is True and out["none"] is None)
check("4: structure and key order are preserved", list(out.keys()) == list(hero.keys()))
check("4: Hindi payload uses Hindi months", P({"t": "2026-10-15 से"}, "hi") == {"t": "15 अक्टूबर 2026 से"})
check("4: None / int / plain values pass through", P(None, "en") is None and P(7, "en") == 7 and P("x", "en") == "x")
check("4: idempotent", P(P(hero, "en"), "en") == P(hero, "en"))

print("\n=== 5: non-fatal numeric slash-date diagnostic ===")
check("5: reports field names and counts only", numeric_slash_date_fields({"a": "on 03/04/2025 and 12/11/2026", "b": ["x", {"c": "1/2/2025"}], "d": "no dates 32.5/36"}) == {"a": 2, "b": 1})
check("5: empty when nothing is left", numeric_slash_date_fields({"a": "15 October 2026", "b": None, "c": 5}) == {} and numeric_slash_date_fields(None) == {})
check("5: fractions / scores / month-year are not flagged", numeric_slash_date_fields({"a": "32.5/36 and 1.5/3 and 12/2026 and 3/4"}) == {})
check("5: the diagnostic never echoes customer text", all(isinstance(v, int) for v in numeric_slash_date_fields({"a": "03/04/2025"}).values()))

print("\n=== 6: prompt contract -- ISO in, human out; the old DD/MM/YYYY instruction is gone ===")
prompt_dir = os.path.join(HERE, "prompts")
prompt_files = sorted(f for f in os.listdir(prompt_dir) if f.endswith(".txt"))
check("6: the 50 prompt files are all scanned", len(prompt_files) == 50)
check("6: NO prompt asks for DD/MM/YYYY any more", not [f for f in prompt_files if "DD/MM/YYYY" in read(f"prompts/{f}")])
hi_files = [f for f in prompt_files if f.endswith("_hi.txt") and f != "relationship_future_report_hi.txt"]
check("6: 24 Hindi standard prompts carry the copy-exactly contract", len(hi_files) == 24 and all("बिल्कुल वैसे ही (exactly as given) लिखें" in read(f"prompts/{f}") and "किसी दूसरे numeric format में न बदलें" in read(f"prompts/{f}") for f in hi_files))
love_en = ("love_disappointment_report_en.txt", "love_marriage_report_en.txt", "love_relationship_report_en.txt")
check("6: 3 English love prompts carry the copy-exactly contract", all("copy each supplied date exactly as given (YYYY-MM-DD); never convert it to another numeric format" in read(f"prompts/{f}") for f in love_en))
check("6: no prompt still tells Luna to convert YYYY-MM-DD", not [f for f in prompt_files if "उसे इसी format में बदलकर लिखें" in read(f"prompts/{f}")])
check("6: the relationship prompt builder source has no DD/MM/YYYY", "DD/MM/YYYY" not in read("modules/love/love_prompt_builder.py"))
from modules.love.love_prompt_builder import build_love_premium_prompt  # noqa: E402
_fixed = lambda lang: dict(language=lang, compiled_report={}, astro_facts={}, compatibility={"case": "A_FULL_DUAL", "ashtakoot": {"total_score": 32.5, "max_score": 36.0, "kootas": {}}},
                           user_house_lord_facts=[], user_dasha_context={"window_summary": "Current window: Mercury Mahadasha - Mercury Antardasha, from 2025-07-01 to 2027-11-28."})
for lang in ("en", "hi"):
    prompt = build_love_premium_prompt(_fixed(lang))
    check(f"6[{lang}]: relationship prompt tells Luna to copy dates exactly as given", "exactly as given" in prompt and "DD/MM/YYYY" not in prompt)
    check(f"6[{lang}]: relationship evidence still carries the ISO dates (ISO in)", "from 2025-07-01 to 2027-11-28" in prompt)
check("6: the prompt-feed builders stay ISO (internal format untouched)", "report_date_format" not in read("summary_blocks.py"))
import summary_blocks as sb  # noqa: E402
_maha = {"mahadasha": "Mercury", "end": "2042-07-01"}
_antar = {"planet": "Mercury", "start": "2025-07-01", "end": "2027-11-28"}
_kundali = {"current_mahadasha": _maha, "current_antardasha": _antar,
            "Mahadasha": [{"mahadasha": "Mercury", "antardashas": [
                {"planet": "Mercury", "start": "2025-07-01", "end": "2027-11-28"}, {"planet": "Ketu", "start": "2027-11-28", "end": "2028-11-24"},
                {"planet": "Venus", "start": "2028-11-24", "end": "2031-09-25"}]}]}
_feed = sb._build_dasha_window_summary(_kundali, _maha, _antar)
check("6: dasha_window_summary (fed to 44 prompts) is still ISO", "from 2025-07-01 to 2027-11-28" in _feed and "2042-07-01" in _feed)
for slug in ("career_report", "sadhesati_report"):
    for lang in ("en", "hi"):
        template = read(f"prompts/{slug}_{lang}.txt")
        names = {m for m in re.findall(r"(?<!{){([a-z_]+)}(?!})", template)}
        blocks = {n: "X" for n in names}
        blocks["dasha_window_summary"] = _feed
        rendered = template.format(**blocks)
        check(f"6: {slug}_{lang} rendered with real ISO dasha data: ISO in the data, no DD/MM/YYYY instruction", "2025-07-01" in rendered and "DD/MM/YYYY" not in rendered)

print("\n=== 7: batch modules pass the report language to every range formatter ===")
for path, expected in (("modules/payments/report_q3_batch1.py", 1), ("modules/payments/report_q3_batch2.py", 2), ("modules/payments/report_q3_batch5.py", 2)):
    calls = re.findall(r"format_customer_date_range\(([^()]*)\)", read(path))
    calls = [c for c in calls if "start" in c or "entering" in c or "antar" in c]
    check(f"7: {path}: {expected} range call site(s), each passes `language`", len(calls) == expected and all(c.strip().endswith("language") for c in calls))

from modules.payments.report_q3_batch2 import compute_dasha_window_timeline  # noqa: E402
from modules.payments.report_q3_batch5 import compute_sadhesati_hero, compute_jupiter_transit_hero  # noqa: E402
from modules.payments.report_q3_batch1 import compute_saturn_transit_hero  # noqa: E402
_tl_en = compute_dasha_window_timeline(_kundali, language="en")
_tl_hi = compute_dasha_window_timeline(_kundali, language="hi")
check("7: Dasha timeline EN uses word-month ranges", [e["date_range"] for e in _tl_en["entries"]] == ["1 July 2025 to 28 November 2027", "28 November 2027 to 24 November 2028", "24 November 2028 to 25 September 2031"])
check("7: Dasha timeline HI uses Hindi months", [e["date_range"] for e in _tl_hi["entries"]] == ["1 जुलाई 2025 से 28 नवंबर 2027", "28 नवंबर 2027 से 24 नवंबर 2028", "24 नवंबर 2028 से 25 सितंबर 2031"])
check("7: the calculation itself is unchanged -- the kundali dates are still ISO strings", _kundali["current_antardasha"]["start"] == "2025-07-01" and _antar["end"] == "2027-11-28")
_sade = {"sadhesati": {"status": "Active", "phase": "2nd Phase", "moon_rashi": "Cancer", "saturn_rashi": "Leo",
                       "phase_dates": {"first_phase": {"start": "2020-01-01", "end": "2021-01-01"}, "second_phase": {"start": "2022-01-01", "end": "2023-06-15"}, "third_phase": {"start": "2024-01-01", "end": "2025-01-01"}}}}
_s_en, _s_hi = compute_sadhesati_hero(_sade, language="en"), compute_sadhesati_hero(_sade, language="hi")
check("7: Sade Sati timing + timeline EN", _s_en["timing"] == "1 January 2022 to 15 June 2023" and _s_en["timeline"]["entries"][0]["date_range"] == "1 January 2022 to 15 June 2023")
check("7: Sade Sati timing + timeline HI", _s_hi["timing"] == "1 जनवरी 2022 से 15 जून 2023" and _s_hi["timeline"]["entries"][0]["date_range"] == "1 जनवरी 2022 से 15 जून 2023")
_residency = {"entering_date": "2026-06-02", "exit_date": "2026-10-30", "to_rashi": "Cancer"}
_jup = {"lagna_sign": "Aries", "transit_summary": {"positions": {"Jupiter": {"rashi": "Cancer", "degree": 10.0, "motion": "direct"}, "Saturn": {"rashi": "Pisces", "degree": 5.0, "motion": "direct"}}}}
with patch("modules.payments.report_q3_batch5.get_current_sign_residency", return_value=_residency), patch("modules.payments.report_q3_batch1.get_current_sign_residency", return_value=_residency):
    _j_en, _j_hi = compute_jupiter_transit_hero(_jup, language="en"), compute_jupiter_transit_hero(_jup, language="hi")
    _sat_en, _sat_hi = compute_saturn_transit_hero(_jup, language="en"), compute_saturn_transit_hero(_jup, language="hi")
check("7: Jupiter transit timing EN / HI", _j_en["timing"] == "2 June 2026 to 30 October 2026" and _j_hi["timing"] == "2 जून 2026 से 30 अक्टूबर 2026")
check("7: Jupiter transit timeline entry EN / HI", _j_en["timeline"]["entries"][0]["date_range"] == _j_en["timing"] and _j_hi["timeline"]["entries"][0]["date_range"] == _j_hi["timing"])
check("7: Saturn transit timing EN / HI", _sat_en["timing"] == "2 June 2026 to 30 October 2026" and _sat_hi["timing"] == "2 जून 2026 से 30 अक्टूबर 2026")

print("\n=== 8: shared renderer -- the presentation boundary for standard_v1 AND love_premium_v1 ===")


def render_html(language="en", **overrides):
    captured = {}

    class FakeHTML:
        def __init__(self, string=None, base_url=None):
            captured["html"] = string

        def write_pdf(self, path):
            return None

    args = dict(output_path=os.path.join(HERE, "tmp", "q56_unused.pdf"), user_info={"name": "Ravi Om Joshi", "dob": "1985-03-31", "tob": "19:45", "pob": "Lucknow"},
                summary_blocks={}, gpt_response="1. Career Outlook\nBody.", kundali_drawing=None, used_placeholders=[], product="career_report", language=language)
    args.update(overrides)
    with patch.object(renderer, "HTML", FakeHTML), patch("os.makedirs"):
        renderer.generate_pdf_report_weasy(**args)
    return captured["html"]


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<style.*?</style>", " ", re.sub(r"<[^>]+>", " ", html), flags=re.S))


LOGGER = logging.getLogger("pdf_generator_weasy")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


NARRATIVE_EN = ("1. Current Period\nThe Mercury-Mercury period runs from 2025-07-01 to 2027-11-28. See https://www.jyotishasha.com/x?d=2026-10-15.\n\n"
                "2. Notes\n- Order ORD-2026-10-15-9 and phone 9555-107-203 stay. Moon at 19.95° and 32.5/36 stay.\n- Born on 1985-03-31.")
HERO_EN = {"label": "Career Outlook", "value": "Steady growth", "interpretation": "The period 2025-07-01 to 2027-11-28 supports focus.",
           "evidence": ["Mercury period: 2025-07-01 to 2027-11-28", "Ashtakoot compatibility: 32.5/36"], "timing": "2026-10-15 to 2027-04-20", "caution": "Avoid haste until 2027-11-28."}
ACTIONS_EN = {"heading": "Suggested Next Steps", "items": ["Review goals by 2026-12-31.", "Keep 2027 flexible."]}
TIMELINE = {"heading": "Current & Upcoming Dasha Windows", "entries": [{"label": "Mercury – Ketu", "date_range": "2027-11-28 to 2028-11-24", "note": "Upcoming window 2027-11-28", "current": False}]}
TABLES = [{"heading": "Windows", "headers": ["Start", "End"], "rows": [["2026-01-02", "2026-03-04"], ["Order 2026-10-15-1", "₹51"]]}]
RESULT_CARDS = [{"label": "Peak", "value": "2027-04-20", "detail": "from 2026-10-15"}]
FACT_CARDS = [{"heading": "Dates", "text": "Begins 2026-10-15.", "items": ["2027-04-20 ends"]}]
NOTICES = [{"heading": "Note", "text": "Valid till 2027-04-20"}]
HIGHLIGHTS = [{"heading": "Key", "text": "Since 2026-10-15"}]
GEM = {"planet": "Venus", "gemstone": "Diamond", "substone": "White Zircon", "reason": "Dasha from 2025-07-01", "caution": "Wear after 2026-10-15"}
APP = {"heading": "Get the app", "benefit_text": "Daily guidance", "play_store_url": "https://play.google.com/store/apps/details?id=x&d=2026-10-15", "app_store_url": None}

en_args = dict(gpt_response=NARRATIVE_EN, answer_hero=HERO_EN, action_list=ACTIONS_EN, timeline=TIMELINE, tables=TABLES, result_cards=RESULT_CARDS, fact_cards=FACT_CARDS,
               notices=NOTICES, highlights=HIGHLIGHTS, gemstone=GEM, disclaimer="Valid guidance as of 2026-09-20.", app_download=APP)
snapshot = copy.deepcopy(en_args)
user = {"name": "Ravi Om Joshi", "dob": "1985-03-31", "tob": "19:45", "pob": "Lucknow"}
user_snapshot = copy.deepcopy(user)
handler = Capture()
LOGGER.addHandler(handler)
html_en = render_html("en", user_info=user, **en_args)
txt_en = text_of(html_en)
check("8: DOB is written in words (EN)", "31 March 1985" in txt_en and "1985-03-31" not in txt_en and "31/03/1985" not in txt_en)
check("8: Report Date is written in words (EN) and keeps the server-date source",
      re.search(r"Report Date: (\d{1,2}) ([A-Z][a-z]+) (\d{4})", txt_en) is not None
      and re.search(r"Report Date: ([0-9]{1,2}) %s %d" % (EN_MONTHS[datetime.now().month - 1], datetime.now().year), txt_en) is not None)
check("8: narrative ISO dates are converted", "runs from 1 July 2025 to 28 November 2027" in txt_en and "Born on 31 March 1985" in txt_en)
check("8: answer_hero (value / interpretation / evidence / timing / caution) is converted",
      "period 1 July 2025 to 28 November 2027 supports" in txt_en and "Mercury period: 1 July 2025 to 28 November 2027" in txt_en
      and "15 October 2026 to 20 April 2027" in txt_en and "until 28 November 2027" in txt_en)
check("8: action_list / timeline / tables / cards / notices / highlights / gemstone are converted",
      all(s in txt_en for s in ("Review goals by 31 December 2026", "28 November 2027 to 24 November 2028", "Upcoming window 28 November 2027", "2 January 2026", "4 March 2026",
                                "from 15 October 2026", "20 April 2027", "Begins 15 October 2026", "Valid till 20 April 2027", "Since 15 October 2026", "Dasha from 1 July 2025", "Wear after 15 October 2026")))
check("8: the disclaimer is converted too", "Valid guidance as of 20 September 2026" in txt_en)
check("8: NO ISO calendar date reaches the customer HTML text", not re.search(r"\b(?:19|20)\d\d-\d\d-\d\d\b", re.sub(r"https?://\S+", "", txt_en.replace("ORD-2026-10-15-9", "").replace("ORD-2026-10-15-1", "").replace("2026-10-15-1", ""))))
check("8: URLs are not corrupted (in the narrative AND app_download)", "https://www.jyotishasha.com/x?d=2026-10-15" in html_en and "https://play.google.com/store/apps/details?id=x&amp;d=2026-10-15" in html_en)
check("8: order ids, phone numbers, degrees, scores, prices are not corrupted", all(s in txt_en for s in ("ORD-2026-10-15-9", "9555-107-203", "19.95°", "32.5/36", "₹51", "Order 2026-10-15-1")))
check("8: customer identity data is not corrupted (name, TOB, POB)", all(s in txt_en for s in ("Ravi Om Joshi", "TOB: 19:45", "POB: Lucknow")))
check("8: the caller's objects are never mutated (Order DOB stays ISO)", en_args == snapshot and user == user_snapshot and user["dob"] == "1985-03-31")
check("8: no numeric slash date left -> no diagnostic warning", not handler.messages)

html_hi = render_html("hi", user_info=user, gpt_response="1. मौजूदा दौर\nयह दौर 2025-07-01 से 2027-11-28 तक है।\n\n2. सलाह\n- 2026-10-15 से शुरू करें।",
                      answer_hero={"label": "Career Outlook", "value": "स्थिर", "interpretation": "2025-07-01 से 2027-11-28 तक फोकस रखें।", "evidence": ["Dasha: 2025-07-01 से 2027-11-28"], "timing": "2026-10-15 से 2027-04-20"},
                      timeline={"heading": "अभी और आगे की Dasha Periods", "entries": [{"label": "Mercury – Ketu", "date_range": "2027-11-28 से 2028-11-24", "note": "आने वाली अवधि", "current": False}]},
                      action_list={"heading": "आपके लिए Next Steps", "items": ["2026-12-31 तक review करें।"]})
txt_hi = text_of(html_hi)
check("8: DOB is written in Hindi words (HI)", HI_1985 in txt_hi and "1985-03-31" not in txt_hi and "31/03/1985" not in txt_hi)
check("8: Report Date is written with a Hindi month (HI)", re.search(r"Report की तारीख: \d{1,2} (?:%s) \d{4}" % "|".join(HI_MONTHS), txt_hi) is not None)
check("8: HI narrative / hero / timeline / action list use Hindi months",
      all(s in txt_hi for s in ("यह दौर 1 जुलाई 2025 से 28 नवंबर 2027 तक है", "15 अक्टूबर 2026 से शुरू करें", "1 जुलाई 2025 से 28 नवंबर 2027 तक फोकस", "Dasha: 1 जुलाई 2025 से 28 नवंबर 2027",
                                "15 अक्टूबर 2026 से 20 अप्रैल 2027", "28 नवंबर 2027 से 24 नवंबर 2028", "31 दिसंबर 2026 तक review")))
check("8: no ISO dates remain in the Hindi output", not re.search(r"\b(?:19|20)\d\d-\d\d-\d\d\b", txt_hi))
check("8: Hindi output has no English month names inside the converted dates", not re.search(r"\d{1,2} (?:%s) \d{4}" % "|".join(EN_MONTHS), txt_hi))

print("\n=== 8b: relationship identity card (love_premium_v1 renderer path) ===")
for lang, want_a, want_b in (("en", ("3 November 1988", "14 February 1991"), ("1988-11-03", "1991-02-14")), ("hi", ("3 नवंबर 1988", "14 फ़रवरी 1991"), ("1988-11-03", "1991-02-14"))):
    html = render_html(lang, user_info={"name": "Rohan Mehta", "dob": "1988-11-03", "tob": "07:20", "pob": "Mumbai, Maharashtra, India"}, product="relationship_future_report",
                       partner_info={"name": "Kavya Nair", "dob": "1991-02-14", "tob": "18:05", "pob": "Chennai, Tamil Nadu, India", "latitude": 13.08},
                       gpt_response="1. Relationship Outlook\nText from 2025-07-01.", answer_hero=HERO_EN)
    txt = text_of(html)
    check(f"8b[{lang}]: primary AND partner DOB use word-month format", all(w in txt for w in want_a))
    check(f"8b[{lang}]: no ISO / numeric DOB anywhere in the relationship page", not any(x in txt for x in want_b) and "03/11/1988" not in txt and "14/02/1991" not in txt)
    check(f"8b[{lang}]: the cover, identity card and chart caption all carry the converted dates (>= 3 occurrences of the primary DOB)", txt.count(want_a[0]) >= 2)
    check(f"8b[{lang}]: partner TOB / POB and coordinates handling unchanged", "18:05" in txt and "Chennai, Tamil Nadu, India" in txt and "13.08" not in html)

print("\n=== 9: numeric slash dates are NOT reinterpreted; a non-fatal warning is logged ===")
handler.messages.clear()
html_slash = render_html("en", user_info=user, gpt_response="1. Period\nLuna wrote 03/04/2025 and 05/06/2025 here, plus 2026-10-15.",
                         answer_hero={"label": "x", "value": "y", "interpretation": "see 12/11/2026", "evidence": ["e"]})
txt_slash = text_of(html_slash)
check("9: the report still renders (the warning never blocks generation)", "Luna wrote" in txt_slash)
check("9: slash dates are left exactly as written (never guessed as 3 April or 4 March)", "03/04/2025" in txt_slash and "05/06/2025" in txt_slash and "12/11/2026" in txt_slash)
check("9: the ISO date in the same text is still converted", "plus 15 October 2026" in txt_slash)
check("9: exactly one warning is logged, naming fields + counts", len(handler.messages) == 1 and "gpt_response" in handler.messages[0] and "answer_hero" in handler.messages[0])
check("9: the warning contains NO customer text, dates, names or DOB",
      not any(s in handler.messages[0] for s in ("03/04/2025", "05/06/2025", "12/11/2026", "Ravi", "1985", "Luna wrote", "Lucknow")))
check("9: the warning carries the counts (gpt_response: 2, answer_hero: 1)", "'gpt_response': 2" in handler.messages[0] and "'answer_hero': 1" in handler.messages[0])

print("\n=== 10: the REAL relationship task -> real renderer, Luna mocked (EN + HI) ===")
from test_worker_boot_lazy_clients import _FAKE_FCM_JSON  # noqa: E402
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
import modules.love.love_premium_task as premium  # noqa: E402

PRIMARY = dict(name="Rohan Mehta", dob="1988-11-03", tob="07:20", pob="Mumbai, Maharashtra, India", latitude="19.0760", longitude="72.8777")
PARTNER = dict(name="Kavya Nair", dob="1991-02-14", tob="18:05", pob="Chennai, Tamil Nadu, India", latitude=13.0827, longitude=80.2707)


def run_relationship(language, body, hero):
    order = SimpleNamespace(id=717171, name=PRIMARY["name"], email="fixture@example.invalid", phone=None, product="relationship_future_report", dob=PRIMARY["dob"], tob=PRIMARY["tob"],
                            pob=PRIMARY["pob"], latitude=PRIMARY["latitude"], longitude=PRIMARY["longitude"], language=language, payment_status="PAID", status="PAID",
                            report_stage="Pending", pdf_url=None, created_at=None, partner_payload=dict(PARTNER), processing_started_at=None)
    query = MagicMock()
    query.get.return_value = order
    seen, out = {}, {}
    completion = SimpleNamespace(content="===META===\n" + json.dumps({"hero": hero}, ensure_ascii=False) + "\n===REPORT===\n" + body, model="gpt-5.6-luna",
                                 input_tokens=1, output_tokens=1, total_tokens=2, duration_seconds=0.1)
    reader = open

    def safe_open(path, mode="r", *args, **kwargs):
        return io.StringIO() if "w" in mode else reader(path, mode, *args, **kwargs)

    def fake_ai(prompt):
        seen["prompt"] = prompt
        return completion

    def real_render(**kw):
        captured = {}

        class FakeHTML:
            def __init__(self, string=None, base_url=None):
                captured["html"] = string

            def write_pdf(self, path):
                return None

        with patch.object(renderer, "HTML", FakeHTML):
            renderer.generate_pdf_report_weasy(**{**kw, "output_path": os.path.join(HERE, "tmp", "q56_unused.pdf")})
        out["html"] = captured["html"]
        out["kw"] = kw

    with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        stack.enter_context(patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("DB access forbidden")))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")))
        stack.enter_context(patch.object(premium, "Order", SimpleNamespace(query=query)))
        stack.enter_context(patch.object(premium, "db", SimpleNamespace(session=MagicMock())))
        stack.enter_context(patch.object(premium, "record_event"))
        stack.enter_context(patch.object(premium, "deliver_generated_report"))
        stack.enter_context(patch.object(premium, "generate_kundali_drawing", return_value=None))
        stack.enter_context(patch.object(premium, "generate_pdf_report", side_effect=real_render))
        stack.enter_context(patch.object(premium, "generate_report_completion", side_effect=fake_ai))
        stack.enter_context(patch.object(premium, "open", safe_open, create=True))
        stack.enter_context(patch("os.makedirs"))
        premium.generate_love_premium_report(order.id)
    return order, seen, out


for lang, body, hero in (
    ("en", "1. Relationship Outlook\nRohan and Kavya share a steady base. The Mercury period runs from 2025-07-01 to 2027-11-28.\n2. Compatibility Snapshot\nFull birth details were used.",
     {"label": "Relationship Outlook", "value": "Warm and steady", "interpretation": "The period 2025-07-01 to 2027-11-28 supports patience.", "evidence": ["Moon is in the 5th house.", "Dasha: 2027-11-28 to 2028-11-24"], "action_items": ["Talk calmly before 2026-12-31."]}),
    ("hi", "1. आपके Relationship का Outlook\nRohan और Kavya का base अच्छा है। Mercury का दौर 2025-07-01 से 2027-11-28 तक है।\n2. Compatibility का Snapshot\nपूरे जन्म विवरण इस्तेमाल हुए।",
     {"label": "Relationship Outlook", "value": "शांत और स्थिर", "interpretation": "2025-07-01 से 2027-11-28 तक धैर्य रखें।", "evidence": ["Moon 5th House में है।", "Dasha: 2027-11-28 से 2028-11-24"], "action_items": ["2026-12-31 से पहले बात करें।"]}),
):
    order, seen, out = run_relationship(lang, body, hero)
    txt = text_of(out["html"])
    check(f"10[{lang}]: the task reached Ready", order.report_stage == "Ready")
    check(f"10[{lang}]: Luna was GIVEN ISO dates and the copy-exactly instruction (ISO in)", re.search(r"from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}", seen["prompt"]) is not None and "exactly as given" in seen["prompt"] and "DD/MM/YYYY" not in seen["prompt"])
    check(f"10[{lang}]: the customer HTML shows NO ISO date", not re.search(r"\b(?:19|20)\d\d-\d\d-\d\d\b", txt))
    if lang == "en":
        check("10[en]: narrative + hero + evidence + action items in words",
              all(s in txt for s in ("runs from 1 July 2025 to 28 November 2027", "period 1 July 2025 to 28 November 2027 supports", "Dasha: 28 November 2027 to 24 November 2028", "before 31 December 2026")))
        check("10[en]: both DOBs (primary + partner) in words", "3 November 1988" in txt and "14 February 1991" in txt)
    else:
        check("10[hi]: narrative + hero + evidence + action items in Hindi words",
              all(s in txt for s in ("दौर 1 जुलाई 2025 से 28 नवंबर 2027 तक", "1 जुलाई 2025 से 28 नवंबर 2027 तक धैर्य", "Dasha: 28 नवंबर 2027 से 24 नवंबर 2028", "31 दिसंबर 2026 से पहले")))
        check("10[hi]: both DOBs (primary + partner) in Hindi words", "3 नवंबर 1988" in txt and "14 फ़रवरी 1991" in txt)
    check(f"10[{lang}]: the stored order / partner payload is untouched (ISO) and nothing but text was rendered",
          order.dob == "1988-11-03" and order.partner_payload == PARTNER and out["kw"]["user_info"]["dob"] == "1988-11-03" and out["kw"]["partner_info"]["dob"] == "1991-02-14")

LOGGER.removeHandler(handler)
print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
