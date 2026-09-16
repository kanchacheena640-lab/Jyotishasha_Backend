# summary_blocks.py
#
# Paid Report Platform -- Q1 (Shared Astrology Data Quality Upgrade).
#
# This is the ONE shared astrology-to-text context builder feeding all
# 24 standard_v1 paid reports (relationship_future_report/love_premium_v1
# does not call this -- it uses modules/love/love_data_collector.py
# instead, and is unaffected by anything below).
#
# Q1 scope: fix the ordinal ("1th"/"2th") bug in birth_chart_summary,
# and ADD new, deterministic, backend-calculated context keys (richer
# dasha windows, richer per-planet transit facts, gemstone data) for
# Q3's future report-specific prompts to opt into. The three existing
# keys every current prompt already relies on --
# birth_chart_summary/mahadasha_summary/current_transit_summary -- keep
# their exact existing shape/computation (birth_chart_summary's text
# changes ONLY insofar as house numbers now render correctly; the
# other two are byte-for-byte unchanged). aspect_summary/manglik_summary
# were already computed and returned before Q1 -- unchanged here, just
# confirmed stable by this phase's own contract tests.
#
# No invented dates anywhere below: every date/period used comes
# straight out of full_kundali_api.py's own already-computed
# Vimshottari Mahadasha/Antardasha sequence (kundali["Mahadasha"]) --
# this module only ever reads/reorders that existing data, never
# recomputes or guesses a date.

SIGN_ORDER = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', ..., 11/12/13 ->
    'Nth' (the 11-13 exception applies for any hundred, e.g. 111th),
    otherwise by n % 10. Houses are always 1-12, but this is correct
    for any positive integer. Mirrors the same, already-proven formula
    services/adhi_rajyog.py::ordinal() uses elsewhere in this codebase
    -- written locally rather than imported from there (or from
    modules/smartchat/chart_summarizer.py's private _ordinal()) to
    avoid coupling this shared report-quality module to an unrelated
    yoga-evaluator/smartchat module for a single trivial, dependency-
    free formatting formula."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 100 % 10, "th")
    return f"{n}{suffix}"


def _house_from_lagna(rashi: str, lagna_sign: str):
    """Deterministic sign-offset house number (1-12) for a planet
    currently transiting `rashi`, relative to the natal Ascendant sign
    -- the standard whole-sign-from-Lagna convention already used
    elsewhere in this codebase (e.g. services/festivals -- rashi-to-
    house offset math). Returns None if either sign is unrecognized
    rather than guessing."""
    if rashi not in SIGN_ORDER or lagna_sign not in SIGN_ORDER:
        return None
    return ((SIGN_ORDER.index(rashi) - SIGN_ORDER.index(lagna_sign)) % 12) + 1


def _flatten_dasha_sequence(mahadashas):
    """Flatten full_kundali_api.py's calculate_vimshottari_dasha() output
    (a list of 9 Mahadashas, each carrying its own 9 Antardashas) into
    one chronological list of {mahadasha, planet, start, end} windows.
    Pure reshaping of already-computed data -- no new dates."""
    flat = []
    for md in mahadashas or []:
        maha_lord = md.get("mahadasha")
        for ad in md.get("antardashas", []) or []:
            flat.append({
                "mahadasha": maha_lord,
                "planet": ad.get("planet"),
                "start": ad.get("start"),
                "end": ad.get("end"),
            })
    return flat


def _build_dasha_window_summary(kundali: dict, current_maha: dict, current_antar: dict) -> str:
    """Richer companion to mahadasha_summary: the current window's own
    Mahadasha end date (mahadasha_summary only ever stated the
    Antardasha's end date) plus up to 2 real upcoming Antardasha
    windows -- found by locating the current Antardasha inside the
    full, already-computed sequence and reading the entries that
    already follow it (crossing into the next Mahadasha when the
    current one is the last Antardasha of its Mahadasha). Never
    invents a date; if the current window cannot be located in the
    sequence (unexpected/malformed input), returns a safe fallback
    string rather than raising -- this function feeds report text, not
    business logic, and must never break generation."""
    maha_lord = current_maha.get("mahadasha")
    maha_end = current_maha.get("end")
    antar_lord = current_antar.get("planet")
    antar_start = current_antar.get("start")
    antar_end = current_antar.get("end")

    if not (maha_lord and antar_lord and antar_start):
        return "Dasha window data not available."

    flat = _flatten_dasha_sequence(kundali.get("Mahadasha"))
    current_index = None
    for i, window in enumerate(flat):
        if window["mahadasha"] == maha_lord and window["planet"] == antar_lord and window["start"] == antar_start:
            current_index = i
            break

    lines = [
        f"Current window: {maha_lord} Mahadasha - {antar_lord} Antardasha, "
        f"from {antar_start} to {antar_end}. "
        f"The overall {maha_lord} Mahadasha runs until {maha_end}."
    ]

    if current_index is not None:
        upcoming = flat[current_index + 1: current_index + 3]
        for window in upcoming:
            lines.append(
                f"Upcoming window: {window['mahadasha']} Mahadasha - {window['planet']} "
                f"Antardasha, from {window['start']} to {window['end']}."
            )

    return " ".join(lines)


def _build_transit_facts_summary(transit: dict, lagna_sign: str) -> str:
    """Deterministic per-planet current-transit facts for every graha
    Swiss Ephemeris already returned (transit_engine.py::
    get_current_positions()), not just Lagna-lord/Saturn/Jupiter --
    plus, where the natal Lagna sign is known, which house from the
    Ascendant each planet is currently transiting (whole-sign offset,
    the same deterministic convention used elsewhere in this
    codebase). Facts only -- no interpretation, no "favorable/
    unfavorable" judgment; that stays the report prompt's job (Q3)."""
    positions = transit.get("positions", {}) if isinstance(transit, dict) else {}
    if not positions:
        return "Transit data not available."

    # Canonical, stable ordering (matches the natal DASHA_SEQUENCE
    # planet set used elsewhere in this codebase) rather than relying
    # on dict insertion order from the ephemeris call.
    canonical_order = [
        "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
    ]

    lines = []
    for planet in canonical_order:
        data = positions.get(planet)
        if not data:
            continue
        rashi = data.get("rashi")
        degree = data.get("degree")
        motion = data.get("motion")
        house = _house_from_lagna(rashi, lagna_sign) if lagna_sign else None
        if house:
            lines.append(
                f"{planet} is transiting {rashi} ({degree}°, {motion}), "
                f"your {_ordinal(house)} house from Lagna."
            )
        else:
            lines.append(f"{planet} is transiting {rashi} ({degree}°, {motion}).")

    return " ".join(lines) if lines else "Transit data not available."


def _build_gemstone_summary(kundali: dict) -> str:
    """Surfaces full_kundali_api.py's own deterministic
    recommend_gemstone_from_lagna_9th() result (already computed for
    every order today, but previously dropped before reaching any
    prompt) as a stable text fact -- never invented/re-derived here.
    Handles the function's own documented incomplete-data fallback
    shape ({"planet": None, "paragraph": "..."}, no gemstone/substone
    keys) without raising."""
    info = kundali.get("gemstone_suggestion") or {}
    planet = info.get("planet")
    gemstone = info.get("gemstone")

    if not planet or not gemstone:
        return "Gemstone recommendation data not available."

    summary = f"Your supportive planet is {planet}, associated with the gemstone {gemstone}."
    substone = info.get("substone")
    if substone:
        summary += f" A supportive sub-stone alternative is {substone}."
    return summary


def build_summary_blocks_with_transit(kundali: dict, transit: dict) -> dict:
    planets = kundali.get("planets", [])
    lagna_sign = kundali.get("lagna_sign", "")

    # 1. Birth Chart Summary -- Q1: house numbers now use correct
    # ordinal suffixes (1st/2nd/3rd/4th/...11th/12th) instead of
    # always appending "th". Same sentence shape/order as before.
    birth_lines = [f"You have a {lagna_sign} Ascendant."]
    for p in planets:
        if p['name'] != 'Ascendant (Lagna)':
            birth_lines.append(f"{p['name']} is placed in {_ordinal(p['house'])} house ({p['sign']}).")
    birth_chart_summary = " ".join(birth_lines)

    # 2. Aspect Summary (unchanged -- already computed pre-Q1, already
    # returned pre-Q1; no prompt references it yet, kept stable here).
    aspect_lines = []
    for p in planets:
        aspects = p.get("aspecting", [])
        if aspects:
            aspect_lines.append(f"{p['name']} is aspecting {', '.join(aspects)}.")
    aspect_summary = " ".join(aspect_lines)

    # 3. Manglik Summary (unchanged).
    manglik_raw = kundali.get("manglik_dosh", {})
    manglik_summary = "You are Mangalik." if manglik_raw.get("is_manglik") else "You are not Mangalik."

    # 4. Mahadasha Summary -- UNCHANGED computation (Q1 compatibility
    # requirement: existing prompts depend on this exact key/shape).
    maha = kundali.get("current_mahadasha", {})
    antar = kundali.get("current_antardasha", {})
    next_change = antar.get("end")
    mahadasha_summary = (
        f"You are currently in the Mahadasha of {maha.get('mahadasha')} and Antardasha of {antar.get('planet')}. "
        f"This phase will end on {next_change}."
    )

    # 5. Current Transit Summary -- UNCHANGED computation (Q1
    # compatibility requirement: existing prompts depend on this exact
    # key/shape).
    current_positions = transit.get("positions", {})
    lagna_lord = None
    for p in planets:
        if p.get("house") == 1:
            lagna_lord = p.get("name")
            break

    transit_lines = []
    if lagna_lord and lagna_lord in current_positions:
        lagna_data = current_positions[lagna_lord]
        transit_lines.append(
            f"Your Lagna lord {lagna_lord} is transiting in {lagna_data['rashi']} ({lagna_data['degree']}°)."
        )

    for planet in ["Saturn", "Jupiter"]:
        if planet in current_positions:
            p = current_positions[planet]
            transit_lines.append(f"{planet} is currently in {p['rashi']} at {p['degree']}°, moving {p['motion']}.")

    current_transit_summary = " ".join(transit_lines) if transit_lines else "Transit data not available."

    # 6. Q1 NEW -- richer, deterministic, backend-calculated context
    # keys. None of the 24 current prompts reference these yet (Q3
    # decides which report prompts consume which context); they are
    # additive and safe to ignore via str.format()'s own behavior of
    # only substituting placeholders a template actually names.
    dasha_window_summary = _build_dasha_window_summary(kundali, maha, antar)
    transit_facts_summary = _build_transit_facts_summary(transit, lagna_sign)
    gemstone_summary = _build_gemstone_summary(kundali)

    return {
        "birth_chart_summary": birth_chart_summary,
        "aspect_summary": aspect_summary,
        "manglik_summary": manglik_summary,
        "mahadasha_summary": mahadasha_summary,
        "current_transit_summary": current_transit_summary,
        "dasha_window_summary": dasha_window_summary,
        "transit_facts_summary": transit_facts_summary,
        "gemstone_summary": gemstone_summary,
    }
