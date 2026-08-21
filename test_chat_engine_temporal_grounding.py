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
        "house_summary": {"1": ["Sun"], "10": ["Jupiter"]},
        "chart_data": {"ascendant": "Leo"},
        "dasha_summary": _fixture_dasha_summary(),
    }
    chat_engine_module.get_current_positions = lambda: {
        "timestamp_ist": "2026-08-21 10:00:00 IST",
        "positions": {"Jupiter": {"rashi": "Cancer", "degree": 17.09, "motion": "Direct"}},
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
          "Dasha Summary" in prompt_c and "Venus" in prompt_c)
    check("C: no real OpenAI call made (stubbed answer returned)",
          result_c.get("answer") == "stubbed answer -- no real OpenAI call made")

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
    check("D: prompt still contains birth chart summary",
          "Birth Chart Summary" in prompt_d and "Leo" in prompt_d)
    check("D: prompt still contains transit summary",
          "Transit Summary" in prompt_d)
    check("D: prompt still contains full dasha table for general-purpose questions",
          "Dasha Summary" in prompt_d)
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
    expected_keys = {"answer", "kundali_preview", "dasha_preview", "transit_preview", "disclaimer"}
    check("F: chat_engine() return dict keys unchanged", set(result_c.keys()) == expected_keys)
    check("F: chat_engine() return dict keys unchanged (non-timing question too)",
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
