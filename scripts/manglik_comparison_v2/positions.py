# Exact AST source segments from production; dependencies injected by loader.
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

def get_nakshatra_pada(degree):
    nak_size = 13 + 1/3  # 13°20' = 13.3333 degrees
    total = degree % 360
    nak_index = int(total // nak_size)
    pada = int(((total % nak_size) / (nak_size / 4)) + 1)
    return NAKSHATRAS[nak_index], pada

def calculate_planet_positions(dob, tob, lat, lon):
    # T3 -- dob/tob are interpreted as LOCAL CIVIL TIME AT THE
    # BIRTHPLACE (resolved from lat/lon), not IST. utc_time is
    # timezone-aware (tzinfo=UTC); its own .year/.month/.day/.hour/
    # .minute already reflect the correct UTC calendar date -- which
    # may legitimately differ from dob's calendar date (UTC rollover)
    # for many foreign birthplaces. lat/lon are used here ONLY to
    # resolve the historical birth timezone; they are passed to
    # swe.houses() below UNCHANGED for the Ascendant/house calculation
    # -- timezone correction changes the astronomical instant, never
    # the customer's own birth coordinates.
    utc_time = resolve_birth_utc_datetime(dob, tob, lat, lon)

    jd_ut = swe.julday(utc_time.year, utc_time.month, utc_time.day,
                       utc_time.hour + utc_time.minute / 60.0)

    # U4C.2B -- was a raw swe.set_sid_mode(swe.SIDM_LAHIRI) call;
    # switched to the shared ensure_lahiri_mode() helper for
    # consistency with every other guarded calculation entry point in
    # the codebase. Behavior is byte-for-byte identical -- this was
    # already the correct, self-contained, call-time pattern (U4A.1);
    # U4C.2A additionally proved the underlying mechanism is per-
    # THREAD, not merely process-global-via-import-order as originally
    # documented, which is exactly why this call-time guard (rather
    # than relying on any import having already run) was already the
    # right fix and remains unchanged here.
    ensure_lahiri_mode()
    FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

    cusps, ascmc = swe.houses(jd_ut, float(lat), float(lon), b'P')
    tropical_lagna = ascmc[0]
    ayanamsa = swe.get_ayanamsa(jd_ut)
    asc_deg = (tropical_lagna - ayanamsa) % 360
    asc_sign_index = int(asc_deg // 30)
    asc_sign = SIGNS[asc_sign_index]
    asc_nak, asc_pada = get_nakshatra_pada(asc_deg)

    house_map = {(asc_sign_index + i) % 12: i + 1 for i in range(12)}

    planets = {
        'Sun': swe.SUN,
        'Moon': swe.MOON,
        'Mercury': swe.MERCURY,
        'Venus': swe.VENUS,
        'Mars': swe.MARS,
        'Jupiter': swe.JUPITER,
        'Saturn': swe.SATURN,
        'Rahu': swe.MEAN_NODE,
        'Ketu': 'South_Node'
    }

    planet_data = []
    for name, planet in planets.items():
        if planet == 'South_Node':
            rahu = swe.calc(jd_ut, swe.MEAN_NODE, FLAGS)[0][0]
            degree = (rahu + 180) % 360
        else:
            degree = swe.calc(jd_ut, planet, FLAGS)[0][0]
        sign_index = int(degree // 30)
        nakshatra, pada = get_nakshatra_pada(degree)

        planet_data.append({
            'name': name,
            'degree': round(degree % 30, 2),
            'sign': SIGNS[sign_index],
            'house': house_map[sign_index],
            'nakshatra': nakshatra,
            'pada': pada,
            # SNR-2B -- ADDITIVE full-precision sidereal longitude
            # (0 <= longitude < 360), the same unrounded value `degree`/
            # `sign` above are derived from. Navamsa (D9) and Darakaraka
            # need it: the rounded `degree` can misplace a planet that
            # sits within 0.01 deg of a 3deg20' Navamsa boundary. Every
            # existing field keeps its exact previous value/meaning.
            'longitude': degree % 360,
        })

    planet_data.append({
        'name': 'Ascendant (Lagna)',
        'degree': round(asc_deg % 30, 2),
        'sign': asc_sign,
        'house': 1,
        'nakshatra': asc_nak,
        'pada': asc_pada,
        'longitude': asc_deg,  # SNR-2B -- additive; asc_deg is already % 360
    })

    return sorted(planet_data, key=lambda x: (x['house'], x['name']))

DRISHTI_RULES = {
    "Saturn": [3, 7, 10],
    "Mars": [4, 7, 8],
    "Jupiter": [5, 7, 9],
    "Rahu": [5, 7, 9],
    "Ketu": [5, 7, 9]
}

def calculate_drishti_for_planets(planets):
    drishti_rules = DRISHTI_RULES

    house_planet_map = {i: [] for i in range(1, 13)}
    for p in planets:
        house_planet_map[p['house']].append(p['name'])

    aspect_data = {p['name']: {"aspecting": [], "aspected_by": []} for p in planets}

    for p in planets:
        rules = drishti_rules.get(p['name'], [7])
        for drishti_count in rules:
            target_house = (p['house'] + drishti_count - 1) % 12 or 12
            if house_planet_map.get(target_house):
                aspect_data[p['name']]["aspecting"].append(
                    f"{', '.join(house_planet_map[target_house])} ({drishti_count}th drishti)"
            )

    for p in planets:
        for other in planets:
            if other['name'] == p['name']:
                continue
            rules = drishti_rules.get(other['name'], [7])
            for drishti_count in rules:
                target_house = (other['house'] + drishti_count - 1) % 12 or 12
                if target_house == p['house']:
                    aspect_data[p['name']]["aspected_by"].append(
                        f"{other['name']} ({drishti_count}th drishti)"
                    )

    return aspect_data
