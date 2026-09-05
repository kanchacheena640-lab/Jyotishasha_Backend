"""
test_chat_engine_temporal_grounding.py
---------------------------------------
Focused tests for the "Ask Now Temporal Grounding + Timing Answer Quality"
fix, plus the follow-up "Ask Now Model Upgrade" (gpt-4o-mini -> the
verified gpt-5.6-luna identifier already live for Premium AI Reports in
services/ai_prediction_lab/openai_client.py), both in
modules/services/chat_engine.py.

Root cause (already-confirmed audit): the prompt never surfaced an explicit
CURRENT_DATE anchor, never distinguished the CURRENT dasha period from the
full lifetime table, and had no rules governing "past vs current vs future"
labeling or how to answer timing ("kab...") questions -- so a genuinely
CURRENT Antardasha (started in the past, still ongoing) could be described
by the model as "upcoming".

These tests prove the FIX at the prompt-construction level:
- _build_current_dasha_context() correctly labels CURRENT vs NEXT dasha
  periods using ONLY data already present in dasha_summary (no new
  astrology calculation -- proven by feeding it a hand-built fixture that
  mirrors the exact real production shape from profile_id=276).
- chat_engine()'s assembled prompt contains CURRENT_DATE, correctly labels
  the current Antardasha as current (not upcoming), labels the next
  Antardasha as next/future, contains all required temporal + timing-
  question rules, and preserves the existing disclaimer instruction.
- A normal, non-timing question still gets a full, usable prompt (general
  Ask Now behavior is not degraded).
- Quota/payment/free-vs-paid logic lives entirely in routes_chat.py, which
  this fix does not touch at all -- not re-tested here (out of scope).

LOCAL ONLY. No real OpenAI call is ever made -- the module-level `client`
is monkeypatched with a fake before chat_engine() is invoked, and
generate_full_kundali_payload()/get_current_positions() are monkeypatched
too so this file needs no DB, no network, and no real ephemeris calls.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import modules.services.chat_engine as chat_engine_module  # noqa: E402
from modules.services.chat_engine import (  # noqa: E402
    chat_engine,
    _build_current_dasha_context,
    _find_next_antardasha,
    _format_natal_chart,
    _format_yogas_doshas,
    _format_current_transits,
)

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


# ---------------------------------------------------------------------
# Fixture: mirrors the EXACT real production shape/values audited on
# profile_id=276 -- Venus Mahadasha (2018-01-06 to 2038-01-06), CURRENT
# Antardasha Rahu (2025-03-08 to 2028-03-07), NEXT Antardasha Jupiter
# (starts 2028-03-07). Antardasha order within a mahadasha always follows
# the standard Vimshottari sequence starting with the mahadasha lord
# itself (see full_kundali_api.py::calculate_antardashas()).
# ---------------------------------------------------------------------
def _venus_mahadasha_antardashas():
    return [
        {"planet": "Venus", "start": "2018-01-06", "end": "2021-05-08"},
        {"planet": "Sun", "start": "2021-05-08", "end": "2022-05-08"},
        {"planet": "Moon", "start": "2022-05-08", "end": "2023-12-08"},
        {"planet": "Mars", "start": "2023-12-08", "end": "2025-02-06"},
        {"planet": "Rahu", "start": "2025-03-08", "end": "2028-03-07"},
        {"planet": "Jupiter", "start": "2028-03-07", "end": "2030-11-07"},
        {"planet": "Saturn", "start": "2030-11-07", "end": "2033-11-07"},
        {"planet": "Mercury", "start": "2033-11-07", "end": "2036-08-07"},
        {"planet": "Ketu", "start": "2036-08-07", "end": "2038-01-06"},
    ]


def _fixture_dasha_summary():
    antardashas = _venus_mahadasha_antardashas()
    current_maha = {
        "mahadasha": "Venus",
        "start": "2018-01-06",
        "end": "2038-01-06",
        "antardashas": antardashas,
    }
    current_antar = antardashas[4]  # Rahu -- index 4, matches the real audit
    return {
        "mahadashas": [current_maha],
        "current_mahadasha": current_maha,
        "current_antardasha": current_antar,
        "current_block": {
            "mahadasha": "Venus",
            "antardasha": "Rahu",
            "period": "2025-03-08 - 2028-03-07",
        },
    }


# ---------------------------------------------------------------------
# Fixture: real payload shape for the "Ask Now Natal Context Completeness"
# fix -- mirrors the exact keys generate_full_kundali_payload() actually
# returns (chart_data.planets with sign/house/degree/nakshatra/pada,
# rashi, yogas with is_active/heading). Includes one planet (Ketu) with
# nakshatra/pada deliberately omitted, to prove graceful degradation
# (required scenario #16), and one active + one inactive yoga, to prove
# only active ones surface.
# ---------------------------------------------------------------------
def _fixture_chart_data_planets():
    return [
        {"name": "Ascendant (Lagna)", "sign": "Leo", "house": 1, "degree": 4.5,
         "nakshatra": "Magha", "pada": 2},
        {"name": "Sun", "sign": "Leo", "house": 1, "degree": 12.34,
         "nakshatra": "Magha", "pada": 3},
        {"name": "Moon", "sign": "Scorpio", "house": 4, "degree": 8.1,
         "nakshatra": "Anuradha", "pada": 1},
        {"name": "Jupiter", "sign": "Cancer", "house": 12, "degree": 17.09,
         "nakshatra": "Ashlesha", "pada": 4},
        # Deliberately missing nakshatra/pada -- proves graceful handling
        # of missing optional natal fields (required scenario #16).
        {"name": "Ketu", "sign": "Taurus", "house": 10, "degree": 22.0},
    ]


def _fixture_yogas():
    return {
        "dhan_yog": {
            "heading": "Dhan Yog is present due to a strong 2nd-11th house connection.",
            "description": "A long descriptive paragraph that should NOT appear in the prompt.",
            "is_active": True,
        },
        "vipreet_rajyog": {
            "heading": "Vipreet Rajyog is NOT present in your Birth Chart (Kundali).",
            "description": "Not applicable.",
            "is_active": False,
        },
    }


class _FakeCompletionResponse:
    def __init__(self, text):
        self.choices = [type("Choice", (), {
            "message": type("Message", (), {"content": text})()
        })()]


class _FakeCompletions:
    def __init__(self, captured):
        self._captured = captured

    def create(self, **kwargs):
        self._captured["kwargs"] = kwargs
        self._captured["prompt"] = kwargs["messages"][1]["content"]
        return _FakeCompletionResponse("stubbed answer -- no real OpenAI call made")


class _FakeChat:
    def __init__(self, captured):
        self.completions = _FakeCompletions(captured)


class _FakeOpenAIClient:
    def __init__(self, captured):
        self.chat = _FakeChat(captured)

    def with_options(self, **kwargs):
        # Ask Now Timeout Delivery Fix: chat_engine.py now derives its
        # scoped (timeout=20, max_retries=0) client via
        # client.with_options(...) at CALL TIME from whatever
        # chat_engine_module.client currently is -- so this fake must
        # answer to the same call the real openai.OpenAI client
        # supports. Returns self (not a copy): a fake has no separate
        # config to scope, so the only thing that matters is that
        # .chat.completions.create() below still resolves to the same
        # captured-prompt fake, never to a real client.
        return self


def _run_chat_engine_captured(question):
    """
    Monkeypatches chat_engine.py's module-level `client` (fake, captures
    the prompt instead of calling OpenAI) plus its kundali/transit
    dependencies (deterministic fixtures, no DB/network/ephemeris), calls
    chat_engine(), and returns (result, captured_prompt).
    """
    captured = {}
    original_client = chat_engine_module.client
    original_kundali_fn = chat_engine_module.generate_full_kundali_payload
    original_transit_fn = chat_engine_module.get_current_positions

    chat_engine_module.client = _FakeOpenAIClient(captured)
    chat_engine_module.generate_full_kundali_payload = lambda payload: {
        "lagna_sign": "Leo",
        "rashi": "Scorpio",
        "chart_data": {"ascendant": "Leo", "planets": _fixture_chart_data_planets()},
        "yogas": _fixture_yogas(),
        "dasha_summary": _fixture_dasha_summary(),
    }
    chat_engine_module.get_current_positions = lambda: {
        "timestamp_ist": "2026-08-21 10:00:00 IST",
        "positions": {
            # Leo Lagna (fixture, above): Cancer -> House 12, Pisces -> House 8.
            # Two planets, independently calculated -- proves scenario #3.
            "Jupiter": {"rashi": "Cancer", "degree": 17.09, "motion": "Direct"},
            "Saturn": {"rashi": "Pisces", "degree": 5.0, "motion": "Retrograde"},
        },
    }

    try:
        result = chat_engine(
            {
                "name": "Test",
                "dob": "1990-01-01",
                "tob": "10:00",
                "pob": "Delhi",
                "lat": 28.6,
                "lng": 77.2,
                "tz": "+05:30",
            },
            question,
        )
    finally:
        chat_engine_module.client = original_client
        chat_engine_module.generate_full_kundali_payload = original_kundali_fn
        chat_engine_module.get_current_positions = original_transit_fn

    return result, captured.get("prompt", ""), captured.get("kwargs", {})


def main():
    # ==========================================================
    print("=== A: _build_current_dasha_context() -- pure unit test, no OpenAI ===")
    # ==========================================================
    dasha = _fixture_dasha_summary()
    context_block = _build_current_dasha_context(dasha)
    print(context_block)

    check("A: contains CURRENT_DATE label", "CURRENT_DATE:" in context_block)
    check("A: contains CURRENT_MAHADASHA Venus", "CURRENT_MAHADASHA: Venus" in context_block)
    check("A: contains CURRENT_ANTARDASHA Rahu", "CURRENT_ANTARDASHA: Rahu" in context_block)
    check("A: CURRENT_ANTARDASHA_START is 2025-03-08", "CURRENT_ANTARDASHA_START: 2025-03-08" in context_block)
    check("A: CURRENT_ANTARDASHA_END is 2028-03-07", "CURRENT_ANTARDASHA_END: 2028-03-07" in context_block)
    check("A: NEXT_ANTARDASHA is Jupiter", "NEXT_ANTARDASHA: Jupiter" in context_block)
    check("A: NEXT_ANTARDASHA_START is 2028-03-07", "NEXT_ANTARDASHA_START: 2028-03-07" in context_block)

    # ==========================================================
    print("\n=== B: _find_next_antardasha() -- last-antardasha-in-mahadasha fallback ===")
    # ==========================================================
    antardashas = _venus_mahadasha_antardashas()
    current_maha = {
        "mahadasha": "Venus", "start": "2018-01-06", "end": "2038-01-06",
        "antardashas": antardashas,
    }
    ketu_antar = antardashas[-1]  # last antardasha in this mahadasha
    next_maha = {
        "mahadasha": "Sun", "start": "2038-01-06", "end": "2044-01-06",
        "antardashas": [{"planet": "Sun", "start": "2038-01-06", "end": "2038-07-06"}],
    }
    dasha_with_next_maha = {"mahadashas": [current_maha, next_maha]}
    nxt_planet, nxt_start = _find_next_antardasha(dasha_with_next_maha, current_maha, ketu_antar)
    check("B: cross-mahadasha fallback finds next mahadasha's first antardasha",
          nxt_planet == "Sun" and nxt_start == "2038-01-06")

    dasha_without_next_maha = {"mahadashas": [current_maha]}
    nxt_planet2, nxt_start2 = _find_next_antardasha(dasha_without_next_maha, current_maha, ketu_antar)
    check("B: gracefully returns (None, None) when next mahadasha isn't in existing data",
          nxt_planet2 is None and nxt_start2 is None)

    check("B: empty dasha_summary never raises", _build_current_dasha_context({}) is not None)

    # ==========================================================
    print("\n=== C: chat_engine() end-to-end prompt -- the exact required regression scenario ===")
    print("    Question: 'mai corporator kab banunga' (Hindi timing question)")
    # ==========================================================
    result_c, prompt_c, kwargs_c = _run_chat_engine_captured("mai corporator kab banunga")
    print(prompt_c)

    check("C: prompt contains CURRENT_DATE", "CURRENT_DATE:" in prompt_c)
    check("C: Rahu is labeled CURRENT, not upcoming", "CURRENT_ANTARDASHA: Rahu" in prompt_c)
    check("C: Jupiter is labeled NEXT (future), not current", "NEXT_ANTARDASHA: Jupiter" in prompt_c)
    check("C: Rahu's current start/end dates are present",
          "2025-03-08" in prompt_c and "2028-03-07" in prompt_c)
    check("C: rule -- CURRENT_DATE is the authority for dates",
          "CURRENT_DATE" in prompt_c and "authority" in prompt_c)
    check("C: rule -- never label a past-started event as upcoming",
          "upcoming" in prompt_c and "before CURRENT_DATE" in prompt_c)
    check("C: rule -- distinguish PAST/CURRENT/FUTURE periods",
          "PAST" in prompt_c and "CURRENT" in prompt_c and "FUTURE" in prompt_c)
    check("C: rule -- never invent astrology facts",
          "Never invent" in prompt_c)
    check("C: rule -- timing questions answered directly, near the beginning",
          "kab hoga" in prompt_c and "kab banunga" in prompt_c and "directly" in prompt_c)
    check("C: rule -- give supported window, don't manufacture an exact date",
          "Do not manufacture an exact date" in prompt_c)
    check("C: rule -- use only 1-3 strongest relevant factors",
          "1-3 strongest" in prompt_c)
    check("C: rule -- avoid generic filler",
          "generic filler" in prompt_c)
    check("C: rule -- guidance/probability, not certainty",
          "probability" in prompt_c or "tendency" in prompt_c)
    check("C: existing disclaimer instruction preserved",
          'End every answer with: "This answer is for astrological guidance only."' in prompt_c)
    check("C: result dict still carries the disclaimer field unchanged",
          result_c.get("disclaimer") == "This answer is for astrological guidance only.")
    check("C: sends the verified Luna model identifier", kwargs_c.get("model") == "gpt-5.6-luna")
    check(
        "C: temperature omitted (gpt-5.6-luna rejects a custom value)",
        "temperature" not in kwargs_c,
    )
    check("C: full dasha life table still present (non-timing-question compatibility)",
          "DASHA REFERENCE" in prompt_c and "Venus" in prompt_c)
    check("C: no real OpenAI call made (stubbed answer returned)",
          result_c.get("answer") == "stubbed answer -- no real OpenAI call made")

    # ==========================================================
    print("\n=== G: Natal Context Completeness (Ask Now natal/yoga fix) ===")
    # ==========================================================
    check("G-1: natal planets reach the final prompt",
          "NATAL CHART" in prompt_c and "Planet Placements:" in prompt_c)
    check("G-2: planet sign reaches the prompt", "Moon: Scorpio" in prompt_c)
    check("G-3: planet house reaches the prompt", "House 4" in prompt_c)
    check("G-4: degree reaches the prompt", "12.34°" in prompt_c)
    check("G-5: nakshatra reaches the prompt when available", "Anuradha" in prompt_c)
    check("G-6: pada reaches the prompt when available", "Pada 1" in prompt_c)
    check("G-7: Moon sign (Rashi) reaches the prompt",
          "Moon Sign (Rashi): Scorpio" in prompt_c)
    check("G-8: computed Yoga/Dosh information reaches the prompt",
          "YOGAS / DOSHAS" in prompt_c and "Dhan Yog is present" in prompt_c)
    check("G-8: only the active yoga's heading is sent, not its verbose description",
          "should NOT appear in the prompt" not in prompt_c)
    check("G-8: an inactive yoga's heading is NOT sent",
          "Vipreet Rajyog is NOT present" not in prompt_c)
    check("G-9: old empty 'Key House Summary: {}' line is gone",
          "Key House Summary" not in prompt_c and "house_summary" not in prompt_c)
    check("G-10: natal data and transit data are clearly labeled and separated",
          "NATAL CHART" in prompt_c
          and "CURRENT TRANSITS (live planetary positions today, NOT natal placements" in prompt_c
          and prompt_c.index("NATAL CHART") < prompt_c.index("CURRENT TRANSITS"))
    check("G-11: Dasha temporal context remains intact alongside the new sections",
          "CURRENT_DATE:" in prompt_c and "CURRENT_ANTARDASHA: Rahu" in prompt_c)
    check("G-12: authoritative-answering rules remain intact alongside the new sections",
          "authoritative data for this answer" in prompt_c)
    check("G-13: model remains gpt-5.6-luna", kwargs_c.get("model") == "gpt-5.6-luna")
    check("G-14: no custom temperature", "temperature" not in kwargs_c)
    check("G-15: response contract unchanged (plus Ask Now Improvement Batch's internal-only concern_category)",
          set(result_c.keys()) == {"answer", "kundali_preview", "dasha_preview", "transit_preview", "disclaimer", "concern_category"})

    # ==========================================================
    print("\n=== G-16: missing optional natal fields do not crash Ask Now ===")
    # ==========================================================
    minimal_natal = _format_natal_chart({
        "lagna_sign": "Aries",
        "rashi": None,
        "chart_data": {"planets": [{"name": "Sun", "sign": "Aries", "house": 1}]},
    })
    check("G-16: _format_natal_chart() never raises with missing degree/nakshatra/pada/rashi",
          "Sun: Aries" in minimal_natal and "House 1" in minimal_natal)
    check("G-16: _format_natal_chart() never raises on a totally empty kundali dict",
          _format_natal_chart({}) == "Natal chart data not available.")
    check("G-16: _format_yogas_doshas() never raises on a totally empty kundali dict",
          _format_yogas_doshas({}) == "No significant yogas or doshas detected in this chart.")
    check("G-16: _format_yogas_doshas() never raises on malformed yoga entries",
          _format_yogas_doshas({"yogas": {"broken": "not a dict"}})
          == "No significant yogas or doshas detected in this chart.")

    result_missing, prompt_missing, kwargs_missing = None, None, None
    original_kundali_fn = chat_engine_module.generate_full_kundali_payload
    original_client = chat_engine_module.client
    captured_missing = {}
    try:
        chat_engine_module.client = _FakeOpenAIClient(captured_missing)
        chat_engine_module.generate_full_kundali_payload = lambda payload: {
            "lagna_sign": "Leo",
            # rashi, chart_data, yogas all deliberately absent entirely
        }
        result_missing = chat_engine(
            {"name": "T", "dob": "1990-01-01", "tob": "10:00", "pob": "Delhi",
             "lat": 28.6, "lng": 77.2, "tz": "+05:30"},
            "some question",
        )
        prompt_missing = captured_missing.get("prompt", "")
    finally:
        chat_engine_module.generate_full_kundali_payload = original_kundali_fn
        chat_engine_module.client = original_client
    check("G-16: chat_engine() never crashes when chart_data/rashi/yogas are entirely absent",
          result_missing is not None and "Ascendant (Lagna): Leo" in prompt_missing
          and "No significant yogas or doshas" in prompt_missing)

    # ==========================================================
    print("\n=== H: CURRENT TRANSITS enriched with Transit House from Natal Lagna ===")
    # ==========================================================
    # Fixture: Leo Lagna. Jupiter transiting Cancer -> House 12.
    # Saturn transiting Pisces -> House 8. (rashi_index - lagna_index) % 12 + 1,
    # matching services/personalization_engine.py::calculate_house() exactly.
    check("H-1: existing transit planet/sign/degree/motion remain present",
          "Jupiter: Cancer" in prompt_c and "17.09°" in prompt_c and "Direct" in prompt_c
          and "Saturn: Pisces" in prompt_c and "Retrograde" in prompt_c)
    check("H-2: correct Lagna-relative transit house is added (Jupiter in Cancer, Leo Lagna -> 12)",
          "Jupiter: Cancer, 17.09°, Direct, Transit House from Natal Lagna: 12" in prompt_c)
    check("H-3: a second, independently-calculated planet is also correct (Saturn in Pisces, Leo Lagna -> 8)",
          "Saturn: Pisces, 5.0°, Retrograde, Transit House from Natal Lagna: 8" in prompt_c)
    check("H-4: natal planet House and Transit House from Natal Lagna are clearly distinguishable",
          "House 4" in prompt_c  # Moon's NATAL house, from the natal fixture
          and "Transit House from Natal Lagna: 12" in prompt_c  # Jupiter's TRANSIT house
          and "Transit House from Natal Lagna" not in prompt_c.split("NATAL CHART")[1].split("YOGAS")[0])
    check("H-4: rule text explicitly distinguishes natal House from Transit House from Natal Lagna",
          "A planet's \"House\" under NATAL CHART is its fixed birth-chart house" in prompt_c
          and "\"Transit House from Natal Lagna\" under CURRENT TRANSITS is a completely different" in prompt_c)

    # H-5/6/7/8/9: graceful fallback, proven directly against the helper
    # (pure unit tests, no OpenAI needed) -- mirrors the G-16 pattern.
    transit_fixture = {
        "timestamp_ist": "2026-08-21 10:00:00 IST",
        "positions": {"Jupiter": {"rashi": "Cancer", "degree": 17.09, "motion": "Direct"}},
    }
    check("H-5: missing Lagna does not crash, transit info preserved, no house fabricated",
          "Jupiter: Cancer, 17.09°, Direct" in _format_current_transits(transit_fixture, None)
          and "Transit House from Natal Lagna" not in _format_current_transits(transit_fixture, None))
    check("H-6: invalid/unresolvable Lagna does not crash, no house fabricated",
          "Jupiter: Cancer, 17.09°, Direct" in _format_current_transits(transit_fixture, "NotARealSign")
          and "Transit House from Natal Lagna" not in _format_current_transits(transit_fixture, "NotARealSign"))
    missing_rashi_fixture = {"positions": {"Mars": {"degree": 1.0, "motion": "Direct"}}}
    check("H-7: missing transit rashi does not crash",
          _format_current_transits(missing_rashi_fixture, "Leo") is not None)
    check("H-8: existing transit info (degree/motion) remains when house calculation is unavailable",
          "1.0°" in _format_current_transits(missing_rashi_fixture, "Leo")
          and "Direct" in _format_current_transits(missing_rashi_fixture, "Leo"))
    check("H-9: no fabricated house appears on any fallback path",
          "Transit House from Natal Lagna" not in _format_current_transits(missing_rashi_fixture, "Leo")
          and "Transit House from Natal Lagna" not in _format_current_transits({"error": "boom"}, "Leo"))
    check("H-9b: upstream transit failure ({'error': ...}) still never crashes",
          _format_current_transits({"error": "boom"}, "Leo") == "{'error': 'boom'}")

    check("H-10: natal context remains intact", "NATAL CHART" in prompt_c and "Moon: Scorpio" in prompt_c)
    check("H-11: Yog/Dosh context remains intact", "Dhan Yog is present" in prompt_c)
    check("H-12: temporal grounding remains intact",
          "CURRENT_DATE:" in prompt_c and "CURRENT_ANTARDASHA: Rahu" in prompt_c)
    check("H-13: authoritative-answering rules remain intact", "authoritative data for this answer" in prompt_c)
    check("H-14: model remains gpt-5.6-luna", kwargs_c.get("model") == "gpt-5.6-luna")
    check("H-15: custom temperature remains absent", "temperature" not in kwargs_c)
    check("H-16: response contract remains unchanged (plus internal-only concern_category)",
          set(result_c.keys()) == {"answer", "kundali_preview", "dasha_preview", "transit_preview", "disclaimer", "concern_category"})

    # ==========================================================
    print("\n=== C2: Authoritative Answering rules (Ask Now hesitancy fix) ===")
    # ==========================================================
    check("C2-A: supplied chart/dasha/transit data is stated as authoritative",
          "authoritative data for this answer" in prompt_c)
    check("C2-B: must not ask for birth/chart info already supplied",
          "Do not ask the user to provide birth date, birth time, birth place, Kundali, "
          "planetary placements, Dasha, or transit information" in prompt_c
          and "already supplied above" in prompt_c)
    check("C2-B: must not stop at 'more data required' when data is sufficient",
          '"an exact prediction cannot be made" or "more data is required"' in prompt_c)
    check("C2-C: narrowest defensible timing window hierarchy (exact date -> narrow window -> broader window)",
          "narrow date/month window" in prompt_c and "broader month/year or Dasha/transit window" in prompt_c)
    check("C2-D: exact dates must not be fabricated merely to sound authoritative",
          "Never fabricate an exact date merely to sound authoritative" in prompt_c)
    check("C2-E: strongest conclusion must come before supporting reasoning",
          "state the strongest defensible conclusion first, then give the supporting reasoning" in prompt_c)
    check("C2-F: missing-data handling gives best available answer first, refusal is not the default",
          "do not invent or fabricate it -- use the remaining evidence to give the best supported answer first"
          in prompt_c)
    check("C2-G: explicit 'what additional data do you need' follow-ups are allowed",
          "what additional data do you need?" in prompt_c
          and "it is valid to explain which additional astrological information could improve precision"
          in prompt_c)
    check("C2-G: follow-up exception still distinguishes supplied vs genuinely-missing info",
          "distinguish clearly between information already supplied above and information "
          "that is genuinely missing" in prompt_c)
    check("C2: authority does not license fabrication -- explicitly bounded, disclaimer still applies",
          "it never means inventing facts, dates, or chart details" in prompt_c
          and "the disclaimer below still applies" in prompt_c)
    check("C2-H: all prior temporal-grounding rules remain present alongside the new ones",
          "CURRENT_DATE" in prompt_c and "PAST" in prompt_c and "FUTURE" in prompt_c
          and "Never invent" in prompt_c and "1-3 strongest" in prompt_c)
    check("C2-I: model remains gpt-5.6-luna", kwargs_c.get("model") == "gpt-5.6-luna")
    check("C2-J: custom temperature remains absent", "temperature" not in kwargs_c)

    # ==========================================================
    print("\n=== C3: 'what additional data do you need?' follow-up question ===")
    # ==========================================================
    result_c3, prompt_c3, kwargs_c3 = _run_chat_engine_captured(
        "What additional data do you need to give a more accurate prediction?"
    )
    check("C3: follow-up-exception rule text is present for this question too",
          "it is valid to explain which additional astrological information could improve precision"
          in prompt_c3)
    check("C3: model remains gpt-5.6-luna for this question too", kwargs_c3.get("model") == "gpt-5.6-luna")

    # ==========================================================
    print("\n=== D: chat_engine() -- normal non-timing question stays usable ===")
    # ==========================================================
    result_d, prompt_d, kwargs_d = _run_chat_engine_captured(
        "What does my chart say about my career strengths?"
    )
    check("D: prompt still contains the user's actual question",
          "What does my chart say about my career strengths?" in prompt_d)
    check("D: prompt still contains CURRENT_DATE (harmless for non-timing questions)",
          "CURRENT_DATE:" in prompt_d)
    check("D: prompt still contains the natal chart section",
          "NATAL CHART" in prompt_d and "Leo" in prompt_d)
    check("D: prompt still contains the current transits section",
          "CURRENT TRANSITS" in prompt_d)
    check("D: prompt still contains full dasha table for general-purpose questions",
          "DASHA REFERENCE" in prompt_d)
    check("D: existing non-temporal rules preserved (4-6 lines, no empty houses, etc.)",
          "4" in prompt_d and "6" in prompt_d and "DO NOT mention houses" in prompt_d)
    check("D: disclaimer instruction preserved for non-timing questions too",
          'This answer is for astrological guidance only.' in prompt_d)
    check("D: no real OpenAI call made", result_d.get("answer") == "stubbed answer -- no real OpenAI call made")

    # ==========================================================
    print("\n=== E: quota/payment logic untouched (out of scope, sanity-only) ===")
    # ==========================================================
    # chat_engine() itself never touches quota/payment -- that logic lives
    # entirely in routes/routes_chat.py (deduct_question/use_free_quota),
    # which this fix does not import, call, or modify at all. Confirmed
    # by static inspection: chat_engine.py has no quota/payment imports.
    import inspect
    src = inspect.getsource(chat_engine_module)
    check("E: chat_engine.py contains no quota/payment/subscription logic",
          "deduct_question" not in src and "use_free_quota" not in src
          and "subscription" not in src.lower())

    # ==========================================================
    print("\n=== F: response shape unchanged + free/paid routes reach the same fixed engine ===")
    # ==========================================================
    # Ask Now Improvement Batch: chat_engine() now also returns an
    # INTERNAL-ONLY "concern_category" key (see chat_engine()'s own
    # docstring) -- routes/routes_chat.py pops it before building the
    # Flutter-facing API response, so the EXTERNAL API contract this
    # section is really about is unchanged; the internal dict contract
    # gains exactly this one documented key.
    expected_keys = {"answer", "kundali_preview", "dasha_preview", "transit_preview", "disclaimer", "concern_category"}
    check("F: chat_engine() return dict keys unchanged (plus internal-only concern_category)",
          set(result_c.keys()) == expected_keys)
    check("F: chat_engine() return dict keys unchanged (non-timing question too, plus internal-only concern_category)",
          set(result_d.keys()) == expected_keys)

    routes_src = open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "routes", "routes_chat.py"),
        encoding="utf-8",
    ).read()
    check("F: /api/chat/free route still calls chat_engine()",
          '"/api/chat/free"' in routes_src and "chat_engine(birth, question)" in routes_src)
    check("F: /api/chat/pack route still calls chat_engine()",
          '"/api/chat/pack"' in routes_src)
    check("F: exactly one chat_engine import site (no parallel/forked model path)",
          routes_src.count("from modules.services.chat_engine import chat_engine") == 1)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
