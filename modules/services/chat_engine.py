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
from openai import OpenAI
import os
from services.full_kundali_service import generate_full_kundali_payload
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

CURRENT TRANSITS (live planetary positions, NOT natal placements)
{transit}

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
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": "You are a senior Vedic astrologer."},
                {"role": "user", "content": prompt}
            ],
        )
        answer = response.choices[0].message.content.strip()
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
