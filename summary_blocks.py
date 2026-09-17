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


# Q1.5 -- Paid Report Product Intelligence Data Foundation.
#
# Standard sign-rulership (Vedic astrology's own universal convention,
# not invented here): this exact mapping already exists, byte-for-byte
# identical, in services/gemstone_recommender.py::PLANET_OWNERSHIP,
# services/foreign_travel.py::SIGN_LORDS, and services/
# full_kundali_service.py::SIGN_LORDS (cross-checked against all
# three before writing this). A fourth small, local, dependency-free
# copy is written here deliberately rather than importing any of
# those: services/full_kundali_service.py is a large aggregator whose
# own module-level import chain pulls in full_kundali_api.py (which
# itself constructs a Flask app at import time) plus numerous other
# services -- importing it into this otherwise dependency-free,
# hot-path report-context module would be exactly the kind of
# unnecessary coupling problem Q1's own _ordinal() decision already
# established the precedent for avoiding.
SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}


def build_house_lord_facts(kundali: dict) -> list:
    """
    Q1.5 -- structured, deterministic house-by-house facts for all 12
    houses, ALWAYS all 12 regardless of occupancy: an empty house is
    never dropped, since sign/lord/lord-placement are all derivable
    from the natal Lagna alone, independent of whether any planet
    happens to sit in that house. Each entry:
        {house, sign, lord, lord_house, lord_sign, occupying_planets}
    lord_house/lord_sign are None only when the lord planet's own
    placement genuinely isn't resolvable from `kundali["planets"]`
    (never guessed). Public (no leading underscore): later PDF/table
    work (Q2/Q3) may want this structured shape directly, not only the
    flattened prompt-facing string house_lord_summary below reads.
    Returns [] if lagna_sign is unrecognized -- never fabricates a
    house from an unknown Ascendant.
    """
    lagna_sign = kundali.get("lagna_sign")
    if lagna_sign not in SIGN_ORDER:
        return []

    planets = kundali.get("planets", [])
    placement_by_planet = {}
    occupants_by_house = {}
    for p in planets:
        name = p.get("name")
        house = p.get("house")
        if not name or name == "Ascendant (Lagna)":
            continue
        placement_by_planet[name] = {"house": house, "sign": p.get("sign")}
        if house:
            occupants_by_house.setdefault(house, []).append(name)

    lagna_index = SIGN_ORDER.index(lagna_sign)
    facts = []
    for house_num in range(1, 13):
        sign = SIGN_ORDER[(lagna_index + house_num - 1) % 12]
        lord = SIGN_LORDS.get(sign)
        lord_placement = placement_by_planet.get(lord) if lord else None
        facts.append({
            "house": house_num,
            "sign": sign,
            "lord": lord,
            "lord_house": lord_placement["house"] if lord_placement else None,
            "lord_sign": lord_placement["sign"] if lord_placement else None,
            "occupying_planets": occupants_by_house.get(house_num, []),
        })
    return facts


def _build_house_lord_summary(house_facts: list) -> str:
    """Prompt-friendly flattening of build_house_lord_facts() -- one
    sentence per house, EMPTY houses explicitly stated as such (never
    silently omitted) while still carrying their sign/lord/lord-
    placement facts."""
    if not house_facts:
        return "House-lord data not available."

    lines = []
    for f in house_facts:
        occupants = ", ".join(f["occupying_planets"]) if f["occupying_planets"] else "no planet placed"
        if f["lord"] and f["lord_house"]:
            lord_text = f"its lord {f['lord']} is placed in {_ordinal(f['lord_house'])} house ({f['lord_sign']})"
        elif f["lord"]:
            lord_text = f"its lord {f['lord']}'s own placement is not available"
        else:
            lord_text = "its lord could not be determined"
        lines.append(f"House {f['house']} ({f['sign']}): {occupants}; {lord_text}.")
    return " ".join(lines)


def _build_targeted_aspect_summary(kundali: dict, house_facts: list) -> str:
    """Deterministic, targeted aspect facts reusing ONLY
    full_kundali_api.py::DRISHTI_RULES (via kundali["house_aspects"],
    the same table calculate_drishti_for_planets() already uses for
    the existing aspect_summary) -- no new astrological doctrine.
    States which planets' special aspects reach the 7th house and the
    7th lord's own house (the single most-requested cross-report
    fact), plus Saturn/Venus/Moon's own aspect targets and whether
    each reaches the 7th house. Facts only -- deliberately never says
    "afflicted"/"malefic"/"benefic": this codebase has no existing,
    reusable benefic/malefic doctrine, and inventing one here would
    violate this phase's own "reuse only existing rules" instruction.
    Interpretation of these facts stays the report prompt's job (Q3)."""
    house_aspects = kundali.get("house_aspects") or {}
    if not house_aspects or not house_facts:
        return "Targeted aspect data not available."

    facts_by_house = {f["house"]: f for f in house_facts}
    lines = []

    aspecting_7th = house_aspects.get(7, [])
    lines.append(
        f"Planets aspecting the 7th house: {', '.join(aspecting_7th) if aspecting_7th else 'none'}."
    )

    seventh = facts_by_house.get(7)
    if seventh and seventh["lord"] and seventh["lord_house"]:
        lord_house = seventh["lord_house"]
        aspecting_lord_house = house_aspects.get(lord_house, [])
        lines.append(
            f"The 7th house lord ({seventh['lord']}) is placed in house {lord_house} ({seventh['lord_sign']}). "
            f"Planets aspecting that house: {', '.join(aspecting_lord_house) if aspecting_lord_house else 'none'}."
        )

    planets_by_name = {p.get("name"): p for p in kundali.get("planets", []) if p.get("name")}
    for planet in ("Saturn", "Venus", "Moon"):
        if planet not in planets_by_name:
            continue
        targets = sorted(h for h, occupants in house_aspects.items() if planet in occupants)
        if targets:
            ordinals = ", ".join(_ordinal(h) for h in targets)
            reaches_7th = "including the 7th house" if 7 in targets else "not including the 7th house"
            lines.append(f"{planet} aspects the {ordinals} house(s) from its own position ({reaches_7th}).")

    return " ".join(lines)


_SADHESATI_PHASE_KEY_MAP = {
    "1st Phase": "first_phase", "2nd Phase": "second_phase", "3rd Phase": "third_phase",
}


def _build_sadhesati_summary(kundali: dict) -> str:
    """Surfaces services/sadhesati_report_generator.py's own
    deterministic result (already computed in kundali["sadhesati"] by
    full_kundali_api.py, previously unused by any paid-report prompt --
    the same class of pre-Q1 disconnect gemstone_suggestion had).

    Deliberately does NOT use that function's own `short_description`
    active-case wording verbatim, and independently re-resolves the
    current window's dates from the RAW `phase_dates` dict rather than
    trusting that function's own internal date fields: inspection
    found a real, pre-existing key-mismatch bug there -- classify_
    sade_sati() emits phase labels "1st Phase"/"2nd Phase"/"3rd Phase",
    but that function's own internal lookup derives its `phase_dates`
    key as "1st_phase" (phase.lower().replace(" ", "_")) while
    `phase_dates` itself is actually keyed "first_phase"/"second_
    phase"/"third_phase" -- so that function's own start_date/end_date
    are always empty strings for the Active case. Reported here, NOT
    fixed (sadhesati_report_generator.py is untouched, out of this
    phase's scope) -- this function sidesteps the bug entirely by
    reading the raw, correctly-keyed `phase_dates` dict directly via
    the mapping above, so it is unaffected by it."""
    info = kundali.get("sadhesati") or {}
    status = info.get("status")
    if status not in ("Active", "Inactive"):
        return "Sade Sati data not available."

    moon_rashi = info.get("moon_rashi")
    saturn_rashi = info.get("saturn_rashi")
    phase_dates = info.get("phase_dates") or {}

    if status == "Inactive":
        base = "You are not currently under Saturn's Sade Sati."
        upcoming = phase_dates.get("first_phase")
        if upcoming and upcoming.get("start"):
            base += (
                f" Your next Sade Sati is expected to begin around {upcoming['start']} "
                f"and continue until approximately {upcoming.get('end', 'an unknown date')}."
            )
        return base

    phase = info.get("phase")
    window_key = _SADHESATI_PHASE_KEY_MAP.get(phase)
    window = phase_dates.get(window_key) if window_key else None

    base = f"You are currently in the {phase} of Sade Sati (Moon sign {moon_rashi}, Saturn transiting {saturn_rashi})."
    if window and window.get("start") and window.get("end"):
        base += f" This phase runs from {window['start']} to {window['end']}."
    return base


def _build_foreign_travel_summary(kundali: dict) -> str:
    """Surfaces services/foreign_travel.py::build_foreign_travel()'s
    already-computed, deterministic points -- wired into
    calculate_full_kundali() (Q1.5, see that function's own comment)
    as kundali["foreign_travel"]. That function returns each point
    bilingually ({"en": ..., "hi": ...}); this reads the "en" variant
    only, matching every other key in this module's own established,
    English-only convention (mahadasha_summary/current_transit_summary/
    etc. carry no language dimension either -- the report TEMPLATE
    file chosen by language is what varies, never this shared data
    layer). Bilingual data is still preserved in kundali["foreign_
    travel"] itself for any future consumer that needs it."""
    info = kundali.get("foreign_travel") or {}
    positive = info.get("positive_points") or []
    negative = info.get("negative_points") or []
    if not positive and not negative:
        return "Foreign travel indication data not available."

    lines = []
    if positive:
        lines.append("Supportive indications: " + " ".join(p.get("en", "") for p in positive if p.get("en")))
    if negative:
        lines.append("Cautionary indications: " + " ".join(p.get("en", "") for p in negative if p.get("en")))
    return " ".join(lines)


# Q3 Batch 3 -- deterministic yoga-evidence summaries.
#
# full_kundali_api.py already computes all 13 of these yoga evaluators
# for every order (services/dhan_yog.py, services/kuber_rajyog.py,
# services/lakshmi_yog.py, services/chandra_mangal.py, services/
# dharma_karmadhipati.py, services/rajya_sambandh_rajyog.py, services/
# parashari_rajyog.py, services/panch_mahapurush.py, services/
# gajakesari.py, services/budh_aditya.py -- see that file's own
# imports/call sites), but until now that data was never surfaced to
# any report prompt -- exactly the same "computed but disconnected"
# gap Q1 originally found and fixed for gemstone_suggestion/sadhesati.
# Nothing below recalculates or infers a yoga from raw planets; it only
# reads each evaluator's own already-returned is_active/strength/
# reasons fields (verified identical field names across all 13
# evaluators' own source before writing this) and reshapes the ACTIVE
# ones into plain text -- the same "read an already-computed field,
# reshape into text" pattern _build_gemstone_summary()/
# _build_sadhesati_summary() above already established.
#
# Fixed, short display labels per key (not each evaluator's own `name`/
# `heading` field, which is inconsistent in shape across evaluators --
# e.g. gajakesari_yog's `heading` is a full sentence, not a short
# label) -- the same convention services/ai_prediction_lab/
# career_context_builder.py and finance_context_builder.py (a separate,
# unrelated pipeline) independently already established for this exact
# same yoga subset, corroborating this is the right domain grouping.
WEALTH_YOGA_LABELS = {
    "dhan_yog": "Dhan Yog",
    "kuber_rajyog": "Kuber Rajyog",
    "lakshmi_yog": "Lakshmi Yog",
    "chandra_mangal_yog": "Chandra-Mangal Yog",
}

CAREER_YOGA_LABELS = {
    "dharma_karmadhipati_rajyog": "Dharma-Karmadhipati Rajyog",
    "rajya_sambandh_rajyog": "Rajya Sambandh Rajyog",
    "parashari_rajyog": "Parashari Rajyog",
    "panch_mahapurush_yog": "Panch Mahapurush Yog",
    "gajakesari_yog": "Gajakesari Yog",
    "budh_aditya_yog": "Budh-Aditya Yog",
}


def _build_yoga_evidence_summary(kundali: dict, yoga_labels: dict, category_word: str) -> str:
    """Shared reader for both wealth_yoga_summary and
    career_yoga_summary below. A yoga is surfaced ONLY when its own
    kundali[key] entry is a dict AND entry["is_active"] is exactly
    True (not merely truthy) -- any other shape (key missing, not a
    dict, is_active False/None/missing) is silently skipped, never
    reported as "yoga absent": these evaluators' own inactive-case
    reasons are internal diagnostic text, not a customer-facing claim
    this module is licensed to make, and a missing/malformed entry
    must never be *converted into* an absence claim it did not
    actually assert. This function therefore only ever adds POSITIVE
    evidence, exactly like gemstone_summary/sadhesati_summary's own
    established pattern -- never a negative one."""
    lines = []
    for key, label in yoga_labels.items():
        entry = kundali.get(key)
        if not isinstance(entry, dict):
            continue
        if entry.get("is_active") is not True:
            continue
        strength = entry.get("strength")
        reasons = entry.get("reasons")
        reason_text = ""
        if isinstance(reasons, list):
            first_reason = next((r for r in reasons if isinstance(r, str) and r.strip()), None)
            if first_reason:
                reason_text = f" ({first_reason.strip()})"
        if isinstance(strength, str) and strength.strip() and strength.strip().lower() != "none":
            lines.append(f"{label} is active in this chart (strength: {strength.strip()}){reason_text}.")
        else:
            lines.append(f"{label} is active in this chart{reason_text}.")

    if not lines:
        return f"No specific {category_word} yoga is confirmed active from the available deterministic evaluators."
    return " ".join(lines)


def _build_wealth_yoga_summary(kundali: dict) -> str:
    """Dhan Yog / Kuber Rajyog / Lakshmi Yog / Chandra-Mangal Yog --
    the wealth-relevant subset. See _build_yoga_evidence_summary()."""
    return _build_yoga_evidence_summary(kundali, WEALTH_YOGA_LABELS, "wealth")


def _build_career_yoga_summary(kundali: dict) -> str:
    """Dharma-Karmadhipati / Rajya Sambandh / Parashari Rajyog / Panch
    Mahapurush / Gajakesari / Budh-Aditya Yog -- the career-relevant
    subset. See _build_yoga_evidence_summary()."""
    return _build_yoga_evidence_summary(kundali, CAREER_YOGA_LABELS, "career")


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

    # 7. Q1.5 NEW -- further additive, deterministic context keys (see
    # module comment block above each builder). None of the 24 current
    # prompts reference these yet either; inert via str.format() until
    # Q3 opts specific report prompts into specific keys.
    house_facts = build_house_lord_facts(kundali)
    house_lord_summary = _build_house_lord_summary(house_facts)
    targeted_aspect_summary = _build_targeted_aspect_summary(kundali, house_facts)
    sadhesati_summary = _build_sadhesati_summary(kundali)
    foreign_travel_summary = _build_foreign_travel_summary(kundali)

    # 8. Q3 Batch 3 NEW -- further additive, deterministic context keys
    # (see the yoga-summary builders' own comment block above). None of
    # the pre-Batch-3 prompts reference these; inert via str.format()
    # until a product's own prompt opts in.
    wealth_yoga_summary = _build_wealth_yoga_summary(kundali)
    career_yoga_summary = _build_career_yoga_summary(kundali)

    return {
        "birth_chart_summary": birth_chart_summary,
        "aspect_summary": aspect_summary,
        "manglik_summary": manglik_summary,
        "mahadasha_summary": mahadasha_summary,
        "current_transit_summary": current_transit_summary,
        "dasha_window_summary": dasha_window_summary,
        "transit_facts_summary": transit_facts_summary,
        "gemstone_summary": gemstone_summary,
        "house_lord_summary": house_lord_summary,
        "targeted_aspect_summary": targeted_aspect_summary,
        "sadhesati_summary": sadhesati_summary,
        "foreign_travel_summary": foreign_travel_summary,
        "wealth_yoga_summary": wealth_yoga_summary,
        "career_yoga_summary": career_yoga_summary,
    }
