# modules/services/chat_engine.py

"""
Chat Engine (Core logic for ChatPack 51 system)

This engine:
- Generates full kundali
- Gets current transits
- Extracts dasha summary
- Builds GPT prompt
- Calls GPT model
- Returns final astrological answer

Used by:
- routes_chat.py (free + pack)
"""

from datetime import date
from openai import OpenAI, APITimeoutError
import json
import logging
import os
from services.full_kundali_service import generate_full_kundali_payload
from services.personalization_engine import calculate_house
from transit_engine import get_current_positions
from modules.services.asknow_category_service import get_active_category_names

logger = logging.getLogger("chat_engine")


# Initialize OpenAI client once
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Ask Now Category Architecture v1 (FINAL PRODUCT DECISION): concern
# categories are NO LONGER a hardcoded Python list here. They live in a
# small, controlled, DB-backed master (modules/models_ask_now_concern_
# category.py::AskNowConcernCategory, read via modules/services/
# asknow_category_service.py::get_active_category_names()) so a future
# Admin Dashboard can add/enable/disable categories with no code
# deployment -- see this module's own _get_active_concern_categories()
# below, called fresh on every chat_engine() invocation.
#
# This is deliberately NOT the earlier 36-item granular hardcoded list
# either, and NOT categories invented ad hoc by the model -- Luna is
# only ever offered whatever the master currently marks active, and
# _parse_answer_and_category() validates against that exact same
# fetched set.
#
# _FALLBACK_CONCERN_CATEGORIES is a last-resort safety net ONLY, not a
# taxonomy: if the master can't be read at all (DB down, table missing,
# unexpected error) or returns zero active rows, classification degrades
# to offering/accepting just "Other" rather than ever failing the
# answer (Ask Now Category Architecture v1, Objective 3).
_FALLBACK_CONCERN_CATEGORIES = ["Other"]


def _get_active_concern_categories() -> list:
    """
    Fetches the currently active concern-category names from the DB-
    backed master. NEVER raises and NEVER returns an empty list -- any
    failure (DB error, missing table, zero active rows) degrades to
    _FALLBACK_CONCERN_CATEGORIES so a category-master problem can never
    block a valid Ask Now answer.

    Called via the module-level `get_active_category_names` name
    (imported above, resolved at CALL TIME from this module's own
    globals) -- the same monkeypatch seam already established for
    `client` / `generate_full_kundali_payload` / `get_current_positions`
    in this file, so tests can substitute a fake without touching the
    real DB.
    """
    try:
        names = get_active_category_names()
        if names:
            return names
        logger.warning(
            "chat_engine: category master returned zero active categories -- "
            "falling back to %r", _FALLBACK_CONCERN_CATEGORIES,
        )
    except Exception:
        logger.warning(
            "chat_engine: failed to read active concern categories from the "
            "master -- falling back to %r (Ask Now answer unaffected)",
            _FALLBACK_CONCERN_CATEGORIES, exc_info=True,
        )
    return list(_FALLBACK_CONCERN_CATEGORIES)

# Model identifier verified from this same repo's existing, already-live
# Premium AI Report integration (services/ai_prediction_lab/openai_client.py)
# -- not invented here. That file's own comment documents (confirmed
# against the real OpenAI API, not assumed): gpt-5.6-luna rejects a
# custom `temperature` value with a 400 "Unsupported value... Only the
# default (1) value is supported" error. Ask Now's call below therefore
# omits `temperature` entirely for this model, matching that exact
# proven handling -- it previously passed temperature=0.65 under
# gpt-4o-mini, which supported it.
_MODEL = "gpt-5.6-luna"

# Ask Now Timeout Delivery Fix -- bounded well under this deployment's
# proven infrastructure ceiling: render.yaml's startCommand is
# `gunicorn app:app` with no --timeout override anywhere in this repo,
# so gunicorn's documented default sync-worker timeout (30s) is what
# actually kills a slow request in production -- not the OpenAI SDK's
# own 600s default. Failing on OUR terms at 20s (well inside that 30s
# budget, leaving headroom for kundali calculation + JSON/network
# overhead in the same request) means the except block below still
# gets to run and this reaches chat_free()/chat_pack()'s existing
# Credit Safety compensation -- a gunicorn worker kill would bypass
# Python exception handling entirely and lose the credit with no
# controlled response at all.
#
# max_retries=0 is deliberate, not an oversight: the default OpenAI
# client retries transient failures internally (up to 2x), which could
# otherwise multiply this wall-clock budget in an SDK-version-specific
# way this fix does not want to depend on or guess about. A single
# 20s attempt, no retry, is an exact, provable ceiling.
_GENERATION_TIMEOUT_SECONDS = 20


def _find_next_antardasha(dasha: dict, current_maha: dict, current_antar: dict):
    """
    Reads (never calculates) the antardasha immediately following the
    current one, using ONLY data already present in `dasha_summary`
    (`current_mahadasha['antardashas']` and, if needed, the full
    `mahadashas` life table already computed by
    full_kundali_api.py::calculate_vimshottari_dasha()).

    Returns (planet_name, start_date) or (None, None) when it cannot be
    safely identified from existing data -- never guessed, never
    recomputed here.
    """
    antardashas = current_maha.get("antardashas") or []
    current_planet = current_antar.get("planet")
    current_start = current_antar.get("start")
    if not antardashas or not current_planet:
        return None, None

    for i, antar in enumerate(antardashas):
        if antar.get("planet") == current_planet and antar.get("start") == current_start:
            if i + 1 < len(antardashas):
                nxt = antardashas[i + 1]
                return nxt.get("planet"), nxt.get("start")
            break
    else:
        # Current antardasha wasn't found by exact match -- nothing safe
        # to report.
        return None, None

    # Current antardasha is the LAST one in its mahadasha -- the next
    # antardasha is the FIRST antardasha of the NEXT mahadasha, if that
    # mahadasha is already present in the existing full life table.
    all_mahadashas = dasha.get("mahadashas") or []
    maha_lord = current_maha.get("mahadasha")
    maha_start = current_maha.get("start")
    for i, md in enumerate(all_mahadashas):
        if md.get("mahadasha") == maha_lord and md.get("start") == maha_start:
            if i + 1 < len(all_mahadashas):
                next_md_antardashas = all_mahadashas[i + 1].get("antardashas") or []
                if next_md_antardashas:
                    nxt = next_md_antardashas[0]
                    return nxt.get("planet"), nxt.get("start")
            break

    return None, None


def _build_current_dasha_context(dasha: dict) -> str:
    """
    Root-cause fix (Ask Now temporal grounding): the ORIGINAL prompt only
    ever embedded the raw `dasha_summary` dict -- a 9-mahadasha/
    81-antardasha lifetime table -- with no label distinguishing which
    entry is current, and no CURRENT_DATE anchor at all. That is exactly
    why a genuinely CURRENT Antardasha (one that started in the past and
    is still ongoing) could be described by the model as "upcoming".

    This builds an explicit, clearly-labeled CURRENT/NEXT block from data
    ALREADY present in `dasha_summary` (`current_mahadasha` /
    `current_antardasha`, each already carrying their own start/end --
    computed by full_kundali_api.py::get_current_dasha() using the real
    current date). No new astrology is calculated here; this only reads
    and formats what has already been computed. Returned as ADDITIONAL
    prompt content -- the existing raw `dasha_summary` dump is preserved
    unchanged below it (see chat_engine()'s prompt), so answer quality
    for non-timing questions that may need the full life table is not
    reduced.
    """
    current_maha = dasha.get("current_mahadasha") or {}
    current_antar = dasha.get("current_antardasha") or {}

    lines = [f"CURRENT_DATE: {date.today().isoformat()}"]

    if current_maha.get("mahadasha"):
        lines.append(
            f"CURRENT_MAHADASHA: {current_maha['mahadasha']} "
            f"({current_maha.get('start', 'unknown')} to {current_maha.get('end', 'unknown')})"
        )

    if current_antar.get("planet"):
        lines.append(
            f"CURRENT_ANTARDASHA: {current_antar['planet']} "
            f"({current_antar.get('start', 'unknown')} to {current_antar.get('end', 'unknown')})"
        )
        if current_antar.get("start"):
            lines.append(f"CURRENT_ANTARDASHA_START: {current_antar['start']}")
        if current_antar.get("end"):
            lines.append(f"CURRENT_ANTARDASHA_END: {current_antar['end']}")

    next_planet, next_start = _find_next_antardasha(dasha, current_maha, current_antar)
    if next_planet:
        window = f" (starts {next_start})" if next_start else ""
        lines.append(f"NEXT_ANTARDASHA: {next_planet}{window}")
        if next_start:
            lines.append(f"NEXT_ANTARDASHA_START: {next_start}")

    return "\n".join(lines)


def _format_natal_chart(kundali: dict) -> str:
    """
    Formats the ALREADY-COMPUTED natal chart -- no new astrology
    calculation. Reads `kundali['lagna_sign']`, `kundali['rashi']` (moon
    sign, computed in full_kundali_api.py::calculate_full_kundali()) and
    `kundali['chart_data']['planets']` (each entry already carrying
    name/sign/house/degree/nakshatra/pada, computed in
    full_kundali_api.py::calculate_planet_positions()).

    This REPLACES the old `Key House Summary: {kundali.get('house_summary', {})}`
    line. Audited and confirmed: `generate_full_kundali_payload()` never
    returns a `house_summary` key at all (the real per-house/per-planet
    data lives in `chart_data['planets']`), so that line always silently
    rendered as an empty `{}` -- a pre-existing bug, not introduced or
    fixed here beyond routing the prompt to the real data.
    """
    lines = []

    lagna = kundali.get("lagna_sign")
    if lagna:
        lines.append(f"Ascendant (Lagna): {lagna}")

    moon_sign = kundali.get("rashi")
    if moon_sign:
        lines.append(f"Moon Sign (Rashi): {moon_sign}")

    planets = (kundali.get("chart_data") or {}).get("planets") or []
    planet_lines = []
    for p in planets:
        name = p.get("name")
        if not name or "ascendant" in str(name).lower() or "lagna" in str(name).lower():
            # Already surfaced above as "Ascendant (Lagna)" -- skip the
            # duplicate pseudo-planet entry for the same point.
            continue
        detail = f"{name}: {p.get('sign')}"
        if p.get("house") is not None:
            detail += f", House {p['house']}"
        if p.get("degree") is not None:
            detail += f", {p['degree']}°"
        if p.get("nakshatra"):
            detail += f", {p['nakshatra']}"
            if p.get("pada"):
                detail += f" Pada {p['pada']}"
        planet_lines.append(detail)

    if planet_lines:
        lines.append("Planet Placements:\n" + "\n".join(planet_lines))

    return "\n".join(lines) if lines else "Natal chart data not available."


def _format_yogas_doshas(kundali: dict) -> str:
    """
    Filters the ALREADY-COMPUTED yoga/dosha battery (`kundali['yogas']`,
    each entry already carrying is_active/heading/description, computed by
    full_kundali_api.py's yoga/dosha evaluators) down to only the entries
    that are genuinely active, using each one's own already-computed
    `heading` text. No new astrology calculation. Only the compact
    `heading` is sent (not the longer `description` paragraph), per this
    task's token-discipline instruction -- structured facts, not verbose
    prose.
    """
    yogas = kundali.get("yogas") or {}
    active_lines = []
    for val in yogas.values():
        if isinstance(val, dict) and val.get("is_active") and val.get("heading"):
            active_lines.append(f"- {val['heading']}")

    if not active_lines:
        return "No significant yogas or doshas detected in this chart."
    return "\n".join(active_lines)


def _format_current_transits(transit: dict, lagna_sign) -> str:
    """
    Formats the ALREADY-COMPUTED current transit snapshot
    (`transit_engine.get_current_positions()`, unchanged, still Ask Now's
    only source of live sky positions) into a clear per-planet line, and
    for each planet adds the Lagna-relative transit house via
    `services/personalization_engine.py::calculate_house()` -- the exact
    function already live in production for the Alerts personalization
    pipeline (`get_users_for_transit()`). No new astrology calculation:
    `calculate_house()` is pure sign-index arithmetic
    ((rashi_index - lagna_index) % 12 + 1). Verified compatible (audited
    from source, not assumed): both `lagna_sign` and transit `rashi` are
    drawn from the same 12-name English sign set
    (full_kundali_api.py::SIGNS / transit_engine.py::RASHIS), and
    `calculate_house()` itself lowercases/strips both inputs before
    lookup. `routes_profile_bootstrap.py` confirms `user.lagna` (this
    function's existing real caller) is populated from this exact same
    `lagna_sign` value chat_engine.py already has.

    Deliberately labeled "Transit House from Natal Lagna" (never "Natal
    House") so the model cannot confuse a planet's CURRENT transiting
    position with its separate, fixed NATAL house shown in the NATAL
    CHART section above.

    Never crashes: if `lagna_sign` is missing/invalid, a planet's transit
    `rashi` is missing, or `calculate_house()` cannot resolve a house
    (returns falsy), the house portion is simply omitted for that planet
    only -- existing planet/rashi/degree/motion info is always preserved,
    and no house is ever fabricated.
    """
    positions = (transit or {}).get("positions")
    if not isinstance(positions, dict) or not positions:
        # Upstream get_current_positions() itself failed (see chat_engine()'s
        # own try/except) -- nothing structured to format; preserve whatever
        # was returned (e.g. the {"error": ...} fallback) rather than crash.
        return str(transit)

    lines = []
    timestamp = transit.get("timestamp_ist")
    if timestamp:
        lines.append(f"As of: {timestamp}")

    for planet, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        rashi = pos.get("rashi")
        degree = pos.get("degree")
        motion = pos.get("motion")

        detail = f"{planet}: {rashi}"
        if degree is not None:
            detail += f", {degree}°"
        if motion:
            detail += f", {motion}"

        house = None
        if lagna_sign and rashi:
            try:
                house = calculate_house(lagna_sign, rashi)
            except Exception:
                house = None
        if house:
            detail += f", Transit House from Natal Lagna: {house}"

        lines.append(detail)

    return "\n".join(lines) if lines else str(transit)


def chat_engine(birth_data: dict, question: str) -> dict:
    """
    Core chat engine used by BOTH:
    - Free daily chat
    - ChatPack (8 questions)

    Inputs:
    - birth_data = {
        "name": "",
        "dob": "",
        "tob": "",
        "pob": "",
        "lat": float,
        "lng": float,
        "tz": "+05:30"
    }
    - question = string

    Returns dict:
    {
        "answer": "...",
        "kundali_preview": ...,
        "dasha_preview": ...,
        "transit_preview": ...,
        "concern_category": "..." or None,
    }

    concern_category (Ask Now Category Architecture v1) is an INTERNAL
    field only -- one of the category names active in the DB-backed
    master AT THE TIME OF THIS CALL (see _get_active_concern_categories()),
    or None if classification could not be obtained/validated. It is
    produced by the SAME single OpenAI call as the answer itself (no
    second call). Callers
    (routes/routes_chat.py) MUST strip this key before it reaches the
    Flutter-facing API response -- it is for server-side intent-history
    persistence only (modules/services/asknow_intent_service.py), never a
    user-visible field.
    """

    # -----------------------------
    # 1) Generate full kundali
    # -----------------------------
    kundali = generate_full_kundali_payload({
        "name": birth_data["name"],
        "dob": birth_data["dob"],
        "tob": birth_data["tob"],
        "place_name": birth_data["pob"],
        "lat": float(birth_data["lat"]),
        "lng": float(birth_data["lng"]),
        "timezone": str(birth_data.get("tz", "+05:30")),
        "language": "en"
    })

    # -----------------------------
    # 2) Current transit snapshot
    # -----------------------------
    try:
        transit = get_current_positions()
    except Exception as e:
        transit = {"error": str(e)}

    # -----------------------------
    # 3) Dasha summary
    # -----------------------------
    dasha = kundali.get("dasha_summary", {})

    # Explicit temporal grounding block -- see _build_current_dasha_context()
    # docstring. Built only from data already present in `dasha`; no new
    # astrology calculation. This is the root-cause fix for Ask Now
    # describing a genuinely CURRENT dasha period as "upcoming".
    current_dasha_context = _build_current_dasha_context(dasha)

    # Natal chart + yoga/dosha context -- see _format_natal_chart() and
    # _format_yogas_doshas() docstrings. Both read ONLY data already
    # computed by generate_full_kundali_payload(); no new astrology
    # calculation. This replaces the previously-broken, always-empty
    # "Key House Summary: {}" line (see _format_natal_chart() docstring).
    natal_chart_context = _format_natal_chart(kundali)
    yogas_doshas_context = _format_yogas_doshas(kundali)

    # Current transits, enriched with each planet's Lagna-relative transit
    # house -- see _format_current_transits() docstring. Reuses the
    # already-working transit snapshot (`transit`, unchanged above) and
    # the already-production-used calculate_house(); no new astrology
    # calculation, no change to full_kundali_service.py's transit_analysis.
    current_transits_context = _format_current_transits(transit, kundali.get("lagna_sign"))

    # Ask Now Category Architecture v1: fetched fresh from the DB-backed
    # master (or the ["Other"]-only safety net if that read fails --
    # see _get_active_concern_categories()) on EVERY call, so the
    # prompt's allowed-values list and _parse_answer_and_category()'s
    # validator below always agree on the exact same set, and a category
    # added/disabled via the master takes effect on the very next
    # question with no change to this file.
    active_concern_categories = _get_active_concern_categories()
    concern_category_list = ", ".join(active_concern_categories)

    # -----------------------------
    # 4) GPT Prompt
    # -----------------------------
    prompt = f"""
CURRENT TEMPORAL CONTEXT
{current_dasha_context}

NATAL CHART
{natal_chart_context}

YOGAS / DOSHAS
{yogas_doshas_context}

CURRENT TRANSITS (live planetary positions today, NOT natal placements. "Transit House from Natal Lagna" is where each transiting planet currently falls relative to this person's birth Lagna -- it is NOT that planet's natal house, which is shown separately in NATAL CHART above)
{current_transits_context}

DASHA REFERENCE (full life table, for reference)
{dasha}

Follow these rules:
- You are a senior Vedic astrologer.
- Answer in 4–6 focused lines.
- DO NOT mention houses where no planet exists.
- Include transit + dasha + birth chart insights.
- Avoid health, legal or medical advice.
- CURRENT_DATE (given above) is the authority for interpreting all dates. Do not use any other basis for judging what is past, current, or future.
- Never describe an event whose start date is before CURRENT_DATE as "upcoming", "starting soon", or future.
- Any prediction or window you describe as current, upcoming, or future must NOT have already fully ended before CURRENT_DATE. If your first candidate window has already ended, select the next valid window whose end date has not yet passed.
- A period that has already fully ended (both start and end before CURRENT_DATE) may only be referenced retrospectively/explanatorily -- never presented as an upcoming or current opportunity.
- Clearly distinguish PAST, CURRENT, and FUTURE planetary/dasha periods whenever you reference them.
- Never invent a transit, dasha, planetary position, yoga, date, or astrological fact that is not present in the supplied astrology data above.
- For timing questions (e.g. "when will...", "when can...", "kab hoga", "kab milega", "kab banunga"), answer the timing question directly, near the beginning of the answer.
- When astrology supports a period rather than an exact event date, give the strongest supported time window. Do not manufacture an exact date.
- Use only the 1-3 strongest relevant astrological factors. Do not dump unrelated chart information.
- Answer the user's actual question directly first -- in the first line or two -- before any supporting explanation.
- Do not dump raw planetary/house jargon (long lists of planet-sign-house-degree data) directly at the user; translate the astrological reasoning into plain, useful language.
- Do not deliberately withhold a useful detail you already have just to create a reason for the user to ask another question. Give the most useful answer you can in this response.
- When it is genuinely useful, end the answer with exactly ONE follow-up direction, phrased as specific to THIS question and answer -- never a generic "want to know more?" or "ask me anything else". If no genuinely useful follow-up direction exists, omit it rather than inventing a generic one.
- Avoid generic filler that does not answer the user's actual question.
- Express astrology as guidance/probability/tendency where appropriate, not guaranteed certainty.
- NATAL CHART is this person's fixed birth-chart placements (never changes). CURRENT TRANSITS are today's live planetary positions in the sky (changes daily). CURRENT/DASHA REFERENCE is the timing layer (Mahadasha/Antardasha). Never mix these three up or describe a transiting planet's position as if it were a natal placement, or vice versa.
- A planet's "House" under NATAL CHART is its fixed birth-chart house. A planet's "Transit House from Natal Lagna" under CURRENT TRANSITS is a completely different, separate fact -- where that planet is transiting TODAY relative to this person's birth Lagna. Never treat these as the same number or the same kind of fact.

Authoritative answering rules -- act like an experienced astrologer using the
evidence already given above, not a data-collection assistant:
- The supplied birth chart, planetary placements, Dasha/Antardasha, current transits and other astrological context above are the authoritative data for this answer. Do not ask the user to provide birth date, birth time, birth place, Kundali, planetary placements, Dasha, or transit information -- it is already supplied above.
- For prediction/timing questions, do not stop at "an exact prediction cannot be made" or "more data is required" when the supplied astrological data above is sufficient to form a meaningful prediction. Synthesize the strongest available factors and give the strongest defensible conclusion.
- When the question involves "when", "kab", timing, a date, or a period, prefer in this order: (A) an exact date, ONLY when genuinely supported by the supplied evidence; (B) a narrow date/month window, when an exact day is not supportable; (C) a broader month/year or Dasha/transit window, when that is the strongest defensible precision. Never fabricate an exact date merely to sound authoritative.
- Write decisively. Prefer a statement like "The strongest window is March 2028 to November 2030, with 2029 appearing especially supportive." over hedging. Avoid phrases such as "I cannot predict this accurately", "It is impossible to say", "More data is required", or "I need your birth details" unless there is genuinely no usable astrological context above for this specific question.
- For timing/prediction answers, state the strongest defensible conclusion first, then give the supporting reasoning (the 1-3 strongest factors) afterward.
- If a genuinely necessary datum is absent from the context above, do not invent or fabricate it -- use the remaining evidence to give the best supported answer first, and only then briefly mention what additional information could further refine the prediction, if materially necessary.
- If the user explicitly asks what additional data would help (e.g. "what additional data do you need?", "what information would make this more accurate?"), it is valid to explain which additional astrological information could improve precision -- but distinguish clearly between information already supplied above and information that is genuinely missing. Never ask the user to re-enter information already supplied above.
- This authority is about using the evidence already given confidently -- it never means inventing facts, dates, or chart details that are not present in the supplied astrology data above; the disclaimer below still applies.

- End every answer with: "This answer is for astrological guidance only."

THIRD-PARTY / OTHER PERSON'S DETAILS
If the user's question mentions another person's birth details (date of birth, time of birth, or place of birth) -- whether those details are complete or incomplete:
- Treat those details as conversational context only.
- Do not calculate, infer, or claim to calculate that other person's Kundali, chart, or horoscope.
- Do not ask the user to provide or complete that other person's birth details.
- Do not say that other person's birth details are incomplete, insufficient, or required.
- Do not refuse, hedge, or avoid answering because of that other person's birth details.
- Do not perform compatibility, matching, or synastry analysis between two charts.
- Base your entire astrological answer only on the logged-in user's own chart and context already given above (NATAL CHART, CURRENT TRANSITS, DASHA REFERENCE) -- never on a second person's chart.

RESPONSE FORMAT (REQUIRED)
Return your entire response as a single valid JSON object with EXACTLY these two keys, and nothing else outside the JSON object:
{{"answer": "<the full answer text, following every rule above>", "concern_category": "<exactly one category from the list below>"}}

concern_category must be EXACTLY one value copied verbatim from this fixed list (do not invent, translate, or reword a category):
{concern_category_list}

concern_category classification rule: classify the user's underlying/current concern or problem that prompted this question -- NEVER the outcome or resolution they are hoping for. Example: "Meri girlfriend ne breakup kar liya hai, kya patch-up hoga?" is about the underlying concern of a breakup, so classify it as "Breakup" -- never as "Patch-up/Reconciliation" (that is the hoped-for outcome, not the concern) and never as a generic catch-all bucket either. Each category above already names a specific underlying situation -- pick the one that most specifically matches what is actually wrong or pending in the user's life, not what they wish would happen next. Choose exactly ONE primary category. Use "Other" only if the question genuinely does not fit any other category.

USER QUESTION
{question}
"""

    # -----------------------------
    # 5) GPT Call
    # -----------------------------
    try:
        # Derived at CALL TIME from the current module-level `client` --
        # deliberately NOT pre-bound at import time. A test that
        # monkeypatches chat_engine_module.client (the existing,
        # documented seam every OpenAI-call test in this codebase
        # already relies on) must have that fake picked up here, same
        # as it always did. See this module's test-double contract in
        # test_chat_engine_temporal_grounding.py / test_safe_deployment_
        # split.py / test_trust_foundation_phase0.py's _FakeOpenAIClient
        # .with_options() -- each returns self, so the fake stays fully
        # in control of chat.completions.create() below.
        generation_client = client.with_options(
            timeout=_GENERATION_TIMEOUT_SECONDS, max_retries=0
        )
        response = generation_client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": "You are a senior Vedic astrologer."},
                {"role": "user", "content": prompt}
            ],
            # Ask Now Improvement Batch (Objective 4): verified compatible
            # with gpt-5.6-luna via a standalone, one-call, real-API
            # compatibility test before this was implemented (json_object
            # mode accepted cleanly, returned valid parseable JSON on the
            # first attempt -- no retry/coaxing needed). Keeps this at
            # exactly ONE OpenAI call: the same call now returns both the
            # answer and its concern_category together.
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content.strip()
        answer, concern_category = _parse_answer_and_category(raw_content, active_concern_categories)
    except APITimeoutError:
        # Ask Now Timeout Delivery Fix: unlike every OTHER OpenAI-side
        # failure below (rate limit, content policy, a transient API
        # error) -- which intentionally continue to degrade to fallback
        # text, unchanged design decision from the Credit Safety Fix --
        # a timeout means no answer was obtained at all in bounded
        # time. Re-raising lets this escape chat_engine() and reach
        # chat_free()/chat_pack()'s existing Credit Safety compensation
        # exactly like any other generation failure.
        raise
    except Exception as e:
        answer = f"AI temporarily unavailable. Error: {e}"
        # Ask Now Improvement Batch (Objective 4 requirement): a
        # classification/parsing problem must never turn an otherwise
        # usable answer into a failed Ask Now transaction -- and here
        # there isn't even a usable answer from the model, so there is
        # certainly nothing truthful to classify. concern_category stays
        # None; the existing fallback-text behavior is completely
        # unchanged from before this batch.
        concern_category = None

    # -----------------------------
    # 6) Return final JSON
    # -----------------------------
    return {
        "answer": answer,
        "kundali_preview": kundali.get("chart_data", {}).get("ascendant"),
        "dasha_preview": dasha,
        "transit_preview": transit,
        "disclaimer": "This answer is for astrological guidance only.",
        # INTERNAL ONLY -- see this function's own docstring. Callers
        # must strip this key before returning the API response to
        # Flutter.
        "concern_category": concern_category,
    }


def _parse_answer_and_category(raw_content: str, valid_categories):
    """
    Parses the model's required single-call JSON object
    ({"answer", "concern_category"}).

    `valid_categories` is the EXACT list _get_active_concern_categories()
    returned for THIS SAME call (or its ["Other"]-only fallback) -- never
    a fixed module-level constant. This is what makes Ask Now Category
    Architecture v1's "add/disable a category with no code change" claim
    true: this function has no hardcoded taxonomy of its own to fall out
    of sync with the master.

    NEVER raises: a malformed/non-JSON response, a missing/empty
    "answer" key, or an unrecognized concern_category must never turn an
    otherwise usable generated answer into a failed Ask Now transaction.
    Falls back to treating the raw model output as the answer text
    (concern_category=None) whenever the JSON contract isn't honored --
    this exactly matches this engine's pre-existing plain-text behavior,
    so a model that (for whatever reason) returns plain text instead of
    JSON still produces the same answer a user would have received
    before this batch.

    Returns (answer: str, concern_category: str or None).
    """
    try:
        parsed = json.loads(raw_content)
        if not isinstance(parsed, dict):
            raise ValueError("response is not a JSON object")

        answer = parsed.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("missing or empty 'answer' in JSON response")
        answer = answer.strip()

        category = parsed.get("concern_category")
        if category not in valid_categories:
            # Unknown/invalid/missing category, or a category the master
            # no longer has active -- safe fallback. Never trust the raw
            # string, never let it block the answer.
            category = None

        return answer, category
    except Exception:
        # Model did not honor the JSON contract (non-JSON output, wrong
        # shape, etc.) -- degrade gracefully. The raw content becomes the
        # answer as-is, with no category. Never raises.
        return raw_content, None
