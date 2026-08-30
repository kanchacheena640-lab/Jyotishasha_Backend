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
import os
from services.full_kundali_service import generate_full_kundali_payload
from services.personalization_engine import calculate_house
from transit_engine import get_current_positions


# Initialize OpenAI client once
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
        "transit_preview": ...
    }
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
- Clearly distinguish PAST, CURRENT, and FUTURE planetary/dasha periods whenever you reference them.
- Never invent a transit, dasha, planetary position, yoga, date, or astrological fact that is not present in the supplied astrology data above.
- For timing questions (e.g. "when will...", "when can...", "kab hoga", "kab milega", "kab banunga"), answer the timing question directly, near the beginning of the answer.
- When astrology supports a period rather than an exact event date, give the strongest supported time window. Do not manufacture an exact date.
- Use only the 1-3 strongest relevant astrological factors. Do not dump unrelated chart information.
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
        )
        answer = response.choices[0].message.content.strip()
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

    # -----------------------------
    # 6) Return final JSON
    # -----------------------------
    return {
        "answer": answer,
        "kundali_preview": kundali.get("chart_data", {}).get("ascendant"),
        "dasha_preview": dasha,
        "transit_preview": transit,
        "disclaimer": "This answer is for astrological guidance only.",
    }
