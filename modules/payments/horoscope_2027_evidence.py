"""Personalized Horoscope 2027 -- deterministic evidence (no AI).

Every astrological fact the report states comes from here; Luna only writes
interpretation around these facts (see horoscope_2027_narrative.py).

Sources, both already used by the paid-report pipeline:
  * the customer's natal chart: full_kundali_api.calculate_full_kundali()
    (whole-sign houses from the Lagna, planet signs/degrees/nakshatras,
    house aspects, Vimshottari Mahadasha/Antardasha periods);
  * data/transits/transit_master_2027.json: the validated 2027 transit master
    (Lahiri, mean nodes, IST; same conventions as transit_engine.py). It holds
    every 2027 sign change / retrograde / direct station, the slow-planet
    residency periods and the 2027 eclipses (the backend has no eclipse
    calculation of its own). test_horoscope_2027.py re-checks every 2027
    ingress in the file against the live ephemeris engine.

Houses are whole-sign. Natal houses (kept in full, with aspects, for the AI
prompt and the contradiction checks; the customer PDF shows a short chart
summary instead of a house-by-house reading) use the Lagna. Transits are given from BOTH the Lagna and the Moon sign (Gochar);
Sade Sati and Dhaiya are, by definition, counted from the Moon sign.

Any inconsistency in the chart raises ReportMetadataError before the AI call,
so a bad chart becomes report_stage="Failed" (recoverable), never a wrong PDF.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional

from modules.payments.report_structured_output import ReportMetadataError

PRODUCT_SLUG = "personalized_horoscope_2027"
EVIDENCE_SCHEMA = "horoscope_2027_evidence_v1"
YEAR = 2027
YEAR_START = date(YEAR, 1, 1)
YEAR_END = date(YEAR, 12, 31)

MASTER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "transits", "transit_master_2027.json",
)

SIGNS = ("Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces")
GRAHAS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
}
SLOW_PLANETS = ("Jupiter", "Saturn", "Rahu", "Ketu")
FAST_PLANETS = ("Sun", "Mercury", "Venus", "Mars")

# Saturn's house from the natal Moon sign -> Sade Sati phase / Dhaiya kind.
SADE_SATI_PHASES = {12: "rising", 1: "peak", 2: "setting"}
DHAIYA_KINDS = {4: "kantaka", 8: "ashtama"}


@lru_cache(maxsize=1)
def load_transit_master() -> dict:
    with open(MASTER_PATH, encoding="utf-8") as f:
        return json.load(f)


def house_from(sign: str, reference_sign: str) -> int:
    """Whole-sign house of `sign` counted from `reference_sign` (1..12)."""
    return (SIGNS.index(sign) - SIGNS.index(reference_sign)) % 12 + 1


def _day(ist: str) -> date:
    return date.fromisoformat(ist[:10])


def _iso(d: date) -> str:
    return d.isoformat()


def _overlaps(start: date, end: date) -> bool:
    return start <= YEAR_END and end >= YEAR_START


def _fail(message: str):
    raise ReportMetadataError(f"horoscope 2027 evidence: {message}")


# ---------------------------------------------------------------------------
# Natal chart
# ---------------------------------------------------------------------------
def _natal_planets(kundali: dict, lagna: str) -> Dict[str, dict]:
    planets: Dict[str, dict] = {}
    for row in kundali.get("planets") or []:
        name = row.get("name")
        if name not in GRAHAS:
            continue  # the "Ascendant (Lagna)" row
        if name in planets:
            _fail(f"planet {name} appears twice")
        sign = row.get("sign")
        if sign not in SIGNS:
            _fail(f"{name} has unknown sign {sign!r}")
        house = int(row.get("house") or 0)
        if house != house_from(sign, lagna):
            _fail(f"{name} house {house} does not match its sign {sign} from Lagna {lagna}")
        planets[name] = {
            "sign": sign,
            "house": house,
            "degree": round(float(row.get("degree") or 0.0), 2),
            "nakshatra": row.get("nakshatra") or "",
            "pada": row.get("pada"),
        }
    missing = [g for g in GRAHAS if g not in planets]
    if missing:
        _fail(f"missing natal planet(s): {', '.join(missing)}")
    if house_from(planets["Ketu"]["sign"], planets["Rahu"]["sign"]) != 7:
        _fail("Rahu and Ketu are not in opposite signs")
    return planets


def _house_table(planets: Dict[str, dict], lagna: str, house_aspects: dict) -> List[dict]:
    houses = []
    for number in range(1, 13):
        sign = SIGNS[(SIGNS.index(lagna) + number - 1) % 12]
        lord = SIGN_LORDS[sign]
        raw = (house_aspects or {})
        aspects = [p for p in (raw.get(number) or raw.get(str(number)) or []) if p in GRAHAS]
        houses.append({
            "house": number,
            "sign": sign,
            "lord": lord,
            "lord_house": planets[lord]["house"],
            "occupants": [g for g in GRAHAS if planets[g]["house"] == number],
            "aspected_by": sorted(set(aspects), key=GRAHAS.index),
        })
    return houses


# ---------------------------------------------------------------------------
# 2027 transits
# ---------------------------------------------------------------------------
def _slow_segments(master: dict, lagna: str, moon: str) -> Dict[str, List[dict]]:
    residency = master["residency"]
    segments: Dict[str, List[dict]] = {}
    for planet in ("Jupiter", "Saturn", "Rahu"):
        rows = []
        for r in residency[planet]:
            start, end = _day(r["from_ist"]), _day(r["to_ist"])
            if _overlaps(start, end):
                rows.append({"sign": r["sign"], "from": _iso(start), "to": _iso(end)})
        if not rows:
            _fail(f"transit master has no 2027 residency for {planet}")
        segments[planet] = rows
    segments["Ketu"] = [dict(r, sign=SIGNS[(SIGNS.index(r["sign"]) + 6) % 12]) for r in segments["Rahu"]]
    for planet, rows in segments.items():
        for r in rows:
            r["house_from_lagna"] = house_from(r["sign"], lagna)
            r["house_from_moon"] = house_from(r["sign"], moon)
    return segments


def _events(master: dict, lagna: str, moon: str) -> List[dict]:
    events = []
    for planet in SLOW_PLANETS[:2] + FAST_PLANETS:  # Jupiter, Saturn + fast planets (nodes have no 2027 change)
        for e in master["events"].get(planet, []):
            day = _day(e["ist"])
            if not (YEAR_START <= day <= YEAR_END):
                continue
            sign = e.get("to") or e.get("sign")
            if sign not in SIGNS:
                _fail(f"transit master event for {planet} has unknown sign {sign!r}")
            events.append({
                "planet": planet,
                "type": e["type"],  # ingress | retrograde | direct
                "date": _iso(day),
                "sign": sign,
                "from_sign": e.get("from"),
                "house_from_lagna": house_from(sign, lagna),
                "house_from_moon": house_from(sign, moon),
            })
    events.sort(key=lambda x: (x["date"], GRAHAS.index(x["planet"])))
    return events


def _eclipses(master: dict, lagna: str, moon: str) -> List[dict]:
    out = []
    for e in master.get("eclipses_2027", []):
        vis = e.get("india_visibility")
        visible_in, solar_magnitudes = [], []
        if isinstance(vis, dict):
            for city, info in vis.items():
                if not isinstance(info, dict):
                    continue
                if e["kind"] == "lunar" and info.get("max_visible"):
                    visible_in.append(city)
                elif e["kind"] == "solar" and float(info.get("magnitude") or 0) > 0:
                    visible_in.append(city)
                    solar_magnitudes.append(float(info["magnitude"]))
        out.append({
            "date": e["max_ist"][:10],
            "kind": e["kind"],  # solar | lunar
            "type": e["type"],
            "sign": e["sign"],
            "nakshatra": e.get("nakshatra", ""),
            "house_from_lagna": house_from(e["sign"], lagna),
            "house_from_moon": house_from(e["sign"], moon),
            "visible_in_india": bool(visible_in),
            # A solar eclipse seen from India with magnitude < 1 is only a partial eclipse there,
            # whatever its global type (the 2 August 2027 total eclipse is partial in India).
            "partial_in_india": bool(solar_magnitudes) and max(solar_magnitudes) < 1,
        })
    return out


def _saturn_moon_periods(saturn_segments: List[dict]) -> Dict[str, List[dict]]:
    sade_sati, dhaiya = [], []
    for seg in saturn_segments:
        h = seg["house_from_moon"]
        if h in SADE_SATI_PHASES:
            sade_sati.append({"phase": SADE_SATI_PHASES[h], "sign": seg["sign"], "from": seg["from"], "to": seg["to"]})
        if h in DHAIYA_KINDS:
            dhaiya.append({"kind": DHAIYA_KINDS[h], "sign": seg["sign"], "from": seg["from"], "to": seg["to"]})
    return {"sade_sati": sade_sati, "dhaiya": dhaiya}


# ---------------------------------------------------------------------------
# Dasha
# ---------------------------------------------------------------------------
def _dasha_periods(kundali: dict) -> List[dict]:
    periods = []
    for maha in kundali.get("Mahadasha") or []:
        m_start, m_end = date.fromisoformat(maha["start"]), date.fromisoformat(maha["end"])
        if not _overlaps(m_start, m_end):
            continue
        for antar in maha.get("antardashas") or []:
            a_start, a_end = date.fromisoformat(antar["start"]), date.fromisoformat(antar["end"])
            if _overlaps(a_start, a_end):
                periods.append({
                    "mahadasha": maha["mahadasha"], "maha_from": maha["start"], "maha_to": maha["end"],
                    "antardasha": antar["planet"], "from": antar["start"], "to": antar["end"],
                })
    if not periods:
        _fail("no Mahadasha/Antardasha period overlaps 2027")
    for p in periods:
        if p["mahadasha"] not in GRAHAS or p["antardasha"] not in GRAHAS:
            _fail(f"unknown dasha lord in {p}")
    # Antardashas must cover the whole year without gaps.
    if date.fromisoformat(periods[0]["from"]) > YEAR_START or date.fromisoformat(periods[-1]["to"]) < YEAR_END:
        _fail("dasha periods do not cover all of 2027")
    for a, b in zip(periods, periods[1:]):
        if a["to"] != b["from"]:
            _fail(f"gap between dasha periods ending {a['to']} and starting {b['from']}")
    return periods


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------
def _month_bounds(month: int):
    start = date(YEAR, month, 1)
    end = (date(YEAR + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
    return start, end


def _active(rows: List[dict], start: date, end: date) -> List[dict]:
    return [r for r in rows if date.fromisoformat(r["from"]) <= end and date.fromisoformat(r["to"]) >= start]


def _major_changes(month: int, events: List[dict], eclipses: List[dict], dashas: List[dict]) -> List[dict]:
    """What materially changes the monthly guidance: a Jupiter or Saturn sign
    change or station (Sade Sati/Dhaiya start and end with Saturn's sign
    changes), an eclipse, or a new dasha period. Fast-planet movements (Sun,
    Mercury, Venus, Mars) refine a month's advice but never start a new focus,
    so a month without any of these continues the previous month's focus."""
    start, end = _month_bounds(month)
    changes = [{"kind": "transit", "planet": e["planet"], "type": e["type"], "date": e["date"], "sign": e["sign"]}
               for e in events if e["planet"] in ("Jupiter", "Saturn") and start <= date.fromisoformat(e["date"]) <= end]
    changes += [{"kind": "eclipse", "date": e["date"], "sign": e["sign"]}
                for e in eclipses if start <= date.fromisoformat(e["date"]) <= end]
    changes += [{"kind": "dasha", "date": d["from"], "mahadasha": d["mahadasha"], "antardasha": d["antardasha"]}
                for d in dashas if start <= date.fromisoformat(d["from"]) <= end]
    return sorted(changes, key=lambda c: c["date"])


def _months(segments, events, eclipses, dashas, moon_periods) -> List[dict]:
    months = []
    for month in range(1, 13):
        start, end = _month_bounds(month)
        major = _major_changes(month, events, eclipses, dashas)
        months.append({
            "month": month,
            "from": _iso(start),
            "to": _iso(end),
            "dashas": [{"mahadasha": d["mahadasha"], "antardasha": d["antardasha"], "from": d["from"], "to": d["to"]}
                       for d in _active(dashas, start, end)],
            "slow_planets": {p: _active(rows, start, end) for p, rows in segments.items()},
            "events": [e for e in events if start <= date.fromisoformat(e["date"]) <= end],
            "eclipses": [e for e in eclipses if start <= date.fromisoformat(e["date"]) <= end],
            "sade_sati": _active(moon_periods["sade_sati"], start, end),
            "dhaiya": _active(moon_periods["dhaiya"], start, end),
            "major_changes": major,
            # January opens the year, so it always sets its own focus.
            "continues_previous": month > 1 and not major,
        })
    return months


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _allowed_dates(evidence: dict) -> List[str]:
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
            try:
                date.fromisoformat(value)
                found.add(value)
            except ValueError:
                pass

    walk({k: v for k, v in evidence.items() if k != "allowed_dates"})
    return sorted(found)


def _allowed_placements(natal: dict, segments: dict, events: List[dict], master: dict, lagna: str, moon: str) -> dict:
    """Every house/sign each planet legitimately occupies in this report:
    natal, plus every 2027 transit position (from the Lagna or the Moon).
    Used by the narrative validator to block only PROVEN contradictions."""
    allowed = {g: {"signs": {natal[g]["sign"]}, "houses": {natal[g]["house"]}} for g in GRAHAS}
    for planet, rows in segments.items():
        for r in rows:
            allowed[planet]["signs"].add(r["sign"])
            allowed[planet]["houses"].update({r["house_from_lagna"], r["house_from_moon"]})
    for row in master.get("positions_2027_01_01_0000_IST", []):
        planet = row.get("planet")
        if planet in FAST_PLANETS:
            allowed[planet]["signs"].add(row["sign"])
            allowed[planet]["houses"].update({house_from(row["sign"], lagna), house_from(row["sign"], moon)})
    for e in events:
        for sign in (e["sign"], e.get("from_sign")):
            if sign in SIGNS:
                allowed[e["planet"]]["signs"].add(sign)
                allowed[e["planet"]]["houses"].update({house_from(sign, lagna), house_from(sign, moon)})
    # The transiting Moon visits every sign each month: no Moon transit claim can be disproved.
    allowed["Moon"] = {"signs": set(SIGNS), "houses": set(range(1, 13))}
    return {g: {"signs": sorted(v["signs"], key=SIGNS.index), "houses": sorted(v["houses"])} for g, v in allowed.items()}


def build_horoscope_2027_evidence(kundali: dict) -> dict:
    lagna = kundali.get("lagna_sign")
    moon = kundali.get("rashi")
    if lagna not in SIGNS or moon not in SIGNS:
        _fail(f"missing Lagna/Moon sign (lagna={lagna!r}, moon={moon!r})")
    natal = _natal_planets(kundali, lagna)
    if natal["Moon"]["sign"] != moon:
        _fail("natal Moon sign does not match the chart's Moon sign")

    master = load_transit_master()
    segments = _slow_segments(master, lagna, moon)
    events = _events(master, lagna, moon)
    eclipses = _eclipses(master, lagna, moon)
    moon_periods = _saturn_moon_periods(segments["Saturn"])
    dashas = _dasha_periods(kundali)

    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "year": YEAR,
        "lagna": {"sign": lagna, "lord": SIGN_LORDS[lagna], "lord_house": natal[SIGN_LORDS[lagna]]["house"]},
        "moon": {"sign": moon, "house": natal["Moon"]["house"], "nakshatra": natal["Moon"]["nakshatra"],
                 "pada": natal["Moon"]["pada"]},
        "planets": natal,
        "houses": _house_table(natal, lagna, kundali.get("house_aspects")),
        "slow_transits": segments,
        "events": events,
        "eclipses": eclipses,
        "sade_sati": moon_periods["sade_sati"],
        "dhaiya": moon_periods["dhaiya"],
        "dashas": dashas,
        "months": _months(segments, events, eclipses, dashas, moon_periods),
        "allowed_placements": _allowed_placements(natal, segments, events, master, lagna, moon),
    }
    evidence["allowed_dates"] = _allowed_dates(evidence)
    return evidence
