"""
Mangal Dosh P0 corrections (2026-10) -- Moon-to-Mars house counting and the paid-report Manglik line.

Source of truth: the Mangal Dosh + Ashtakoot forensic audit.
  * Houses are counted sign-to-sign, inclusively: house = ((mars_sign - reference_sign) % 12) + 1.
    Moon in Gemini, Mars in Libra -> Gemini 1, Cancer 2, Leo 3, Virgo 4, Libra 5 -> 5th.
  * summary_blocks' manglik_summary must come from the engine's own status.strength.

Scope guards pinned here on purpose (NOT claims that today's behaviour is the final rule):
  * No Venus-based count, dosh houses unchanged, Dosh Bhang (cancellation) behaviour unchanged.
  * Ashtakoot scores are independent of Mars and unchanged by this work.

Planet positions come from a Swiss Ephemeris stand-in (only longitudes and the Ascendant are replaced;
every calculation after that is production code). Synthetic people only. No network, no database, no AI.
Run:  python test_mangal_dosh_p0.py
"""
import hashlib
import json
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_kundali_api as FK  # noqa: E402
import modules.love.ashtakoot_love as AK  # noqa: E402
import summary_blocks as SB  # noqa: E402
from services import mangalik_dosh_logic as MD  # noqa: E402

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
DOSH_HOUSES = {1, 2, 4, 7, 8, 12}
REAL_SWE = FK.swe
ROOT = os.path.dirname(os.path.abspath(__file__))


def expected_house(reference_sign, mars_sign):
    return ((mars_sign - reference_sign) % 12) + 1


class _StandInSwe:
    """Real swisseph, except the sidereal longitudes under test (ayanamsa 0, Ascendant chosen)."""

    def __init__(self, longitudes):
        self.longitudes = longitudes

    def __getattr__(self, name):
        return getattr(REAL_SWE, name)

    def houses(self, jd, lat, lon, hsys):
        cusps, ascmc = REAL_SWE.houses(jd, lat, lon, hsys)
        ascmc = list(ascmc)
        ascmc[0] = self.longitudes["ASC"]
        return cusps, tuple(ascmc)

    def get_ayanamsa(self, jd):
        return 0.0

    get_ayanamsa_ut = get_ayanamsa

    def calc(self, jd, planet, flags=0):
        return ((self.longitudes[planet], 0.0, 1.0, 0.0, 0.0, 0.0), flags)

    calc_ut = calc


def _longitudes(asc, moon, mars, jupiter=None, venus=None):
    """Sign indices (0-based); every body 15 deg into its sign. Unlisted bodies sit two signs after the Lagna."""
    rest = (asc + 2) % 12

    def lon(sign):
        return sign * 30 + 15.0

    return {
        "ASC": lon(asc), REAL_SWE.MOON: lon(moon), REAL_SWE.MARS: lon(mars),
        REAL_SWE.JUPITER: lon(rest if jupiter is None else jupiter), REAL_SWE.VENUS: lon(rest if venus is None else venus),
        REAL_SWE.SUN: lon(rest), REAL_SWE.MERCURY: lon(rest), REAL_SWE.SATURN: lon(rest), REAL_SWE.MEAN_NODE: lon(rest),
    }


def planets_for(asc, moon, mars, **kw):
    """The exact planet list calculate_full_kundali() hands to the Mangal engine."""
    FK.swe = _StandInSwe(_longitudes(asc, moon, mars, **kw))
    try:
        return FK.calculate_planet_positions("1990-06-15", "12:00", 28.6139, 77.2090)
    finally:
        FK.swe = REAL_SWE


def full_kundali_for(asc, moon, mars, language="en", **kw):
    FK.swe = _StandInSwe(_longitudes(asc, moon, mars, **kw))
    try:
        return FK.calculate_full_kundali("SYNTHETIC Mangal", "1990-06-15", "12:00", 28.6139, 77.2090, language=language)
    finally:
        FK.swe = REAL_SWE


def mangal_for(asc, moon, mars, **kw):
    planets = planets_for(asc, moon, mars, **kw)
    return MD.build_manglik_dosh({"planets": planets, "lagna_sign": SIGNS[asc]})


# ---------------------------------------------------------------------------------------------------------------
# 1. House counting
# ---------------------------------------------------------------------------------------------------------------
class MoonHouseCounting(unittest.TestCase):
    def test_fallback_formula_every_house_pair(self):
        """All 144 (Moon house, Mars house) pairs through the engine's own helper."""
        for moon_house in range(1, 13):
            for mars_house in range(1, 13):
                planets = [{"name": "Moon", "house": moon_house}, {"name": "Mars", "house": mars_house}]
                _, from_moon = MD._compute_house_from_moon_fallback(planets)
                self.assertEqual(from_moon, ((mars_house - moon_house) % 12) + 1, (moon_house, mars_house))

    def test_production_pipeline_all_144_moon_mars_signs(self):
        """Every Moon sign x Mars sign through calculate_planet_positions() + the engine. The Lagna is placed
        seven signs from the Moon so the two references never coincide."""
        failures = []
        for moon in range(12):
            for mars in range(12):
                report = mangal_for(asc=(moon + 7) % 12, moon=moon, mars=mars)
                exp = expected_house(moon, mars)
                got = report["context"]["mars_house_from_moon"]
                trig = report["evaluation"]["triggers"]["from_moon"]
                if got != exp or trig != (exp in DOSH_HOUSES):
                    failures.append(f"Moon {SIGNS[moon]} Mars {SIGNS[mars]}: expected {exp}, engine {got}, trigger {trig}")
        self.assertEqual(failures, [], f"{len(failures)} of 144 wrong; first: {failures[:3]}")

    def test_lagna_counting_all_144_unchanged(self):
        failures = []
        for asc in range(12):
            for mars in range(12):
                report = mangal_for(asc=asc, moon=(asc + 5) % 12, mars=mars)
                exp = expected_house(asc, mars)
                if report["context"]["mars_house_from_lagna"] != exp or report["evaluation"]["triggers"]["from_lagna"] != (exp in DOSH_HOUSES):
                    failures.append((SIGNS[asc], SIGNS[mars]))
        self.assertEqual(failures, [])

    def test_edge_cases(self):
        self.assertEqual(mangal_for(asc=0, moon=4, mars=4)["context"]["mars_house_from_moon"], 1)    # same sign -> 1st
        self.assertEqual(mangal_for(asc=0, moon=11, mars=0)["context"]["mars_house_from_moon"], 2)   # Pisces -> Aries
        self.assertEqual(mangal_for(asc=0, moon=0, mars=11)["context"]["mars_house_from_moon"], 12)  # Aries -> Pisces
        self.assertEqual(mangal_for(asc=0, moon=9, mars=3)["context"]["mars_house_from_moon"], 7)    # opposite signs

    def test_gemini_moon_libra_mars_is_5th_end_to_end(self):
        """The reported case, through calculate_full_kundali() exactly as the tool page and love match use it.
        Jupiter in Taurus: no Kendra from Lagna/Moon and no aspect on Mars, so no cancellation applies."""
        k = full_kundali_for(asc=0, moon=2, mars=6, jupiter=1)
        md = k["manglik_dosh"]
        self.assertEqual((next(p["sign"] for p in k["planets"] if p["name"] == "Moon"),
                          next(p["sign"] for p in k["planets"] if p["name"] == "Mars")), ("Gemini", "Libra"))
        self.assertEqual(md["context"]["mars_house_from_moon"], 5)
        self.assertEqual(md["context"]["mars_house_from_lagna"], 7)
        self.assertEqual(md["evaluation"]["triggers"], {"from_lagna": True, "from_moon": False})
        self.assertEqual(md["status"]["strength"], "Partial")  # one trigger (Lagna 7th), no mitigation
        self.assertFalse(any(p.startswith("From the Moon") for p in md["report_paragraphs"]))

    def test_moon_paragraph_states_the_correct_house(self):
        md = mangal_for(asc=5, moon=0, mars=3)  # Moon Aries, Mars Cancer -> 4th (dosh house)
        para = next(p for p in md["report_paragraphs"] if p.startswith("From the Moon"))
        self.assertTrue(para.startswith("From the Moon, Mars occupies the 4 house"), para)
        self.assertEqual(md["context"]["mars_house_from_moon"], 4)


# ---------------------------------------------------------------------------------------------------------------
# 2. Scope guards: what this change must NOT touch
# ---------------------------------------------------------------------------------------------------------------
class ScopeGuards(unittest.TestCase):
    def test_dosh_houses_unchanged(self):
        self.assertEqual(MD.MD_HOUSES, {1, 2, 4, 7, 8, 12})

    def test_no_venus_reference_yet(self):
        md = mangal_for(asc=0, moon=3, mars=6, venus=6)
        self.assertNotIn("mars_house_from_venus", md["context"])
        self.assertEqual(set(md["evaluation"]["triggers"]), {"from_lagna", "from_moon"})

    def test_own_exalted_rule_unchanged(self):
        """The one cancellation that already worked. Jupiter-Kendra and benefic aspect/conjunction were
        activated later; see test_mangal_dosh_cancellation.py."""
        own = mangal_for(asc=0, moon=3, mars=0)  # Mars in Aries (own sign) in the 1st
        self.assertTrue(own["context"]["cancellation_flags"]["mars_own_or_exalted"])
        self.assertFalse(mangal_for(asc=0, moon=3, mars=3)["context"]["cancellation_flags"]["mars_own_or_exalted"])  # Cancer

    def test_severity_table_unchanged(self):
        table = {(fl, fm, n): MD._severity_score(fl, fm, n > 0, n > 1, n > 2)[0]
                 for fl in (False, True) for fm in (False, True) for n in range(4)}
        self.assertEqual(table[(True, True, 0)], "Strong")
        self.assertEqual(table[(True, False, 0)], "Partial")
        self.assertEqual(table[(False, True, 1)], "Cancelled")
        self.assertEqual(table[(True, True, 1)], "Partial")
        self.assertEqual(table[(False, False, 0)], "None")


# ---------------------------------------------------------------------------------------------------------------
# 3. Paid-report Manglik line (summary_blocks) and its Hindi display
# ---------------------------------------------------------------------------------------------------------------
def _summary(kundali):
    return SB.build_summary_blocks_with_transit(kundali, {})["manglik_summary"]


class ManglikSummary(unittest.TestCase):
    def test_reads_engine_strength(self):
        cases = {
            "Strong": "You are Mangalik.",
            "Partial": "You are Mangalik (partial Mangal Dosh).",
            "Cancelled": "You are not Mangalik (Mangal Dosh is cancelled by special combinations).",
            "None": "You are not Mangalik.",
        }
        for strength, text in cases.items():
            self.assertEqual(_summary({"manglik_dosh": {"status": {"strength": strength}}}), text, strength)

    def test_missing_or_malformed_result_is_never_reported_as_not_manglik(self):
        for raw in ({}, {"manglik_dosh": None}, {"manglik_dosh": {}}, {"manglik_dosh": {"status": "x"}},
                    {"manglik_dosh": {"status": {"strength": "Weird"}}}, {"manglik_dosh": {"is_manglik": False}}):
            self.assertEqual(_summary(raw), "Manglik status is not available.", raw)

    def test_real_charts_manglik_and_not_manglik(self):
        # Jupiter in Gemini: no Kendra, no aspect on Mars in Taurus, so nothing cancels.
        strong = full_kundali_for(asc=1, moon=1, mars=1, jupiter=2)   # Mars Taurus: 1st from Lagna and from Moon
        self.assertEqual(strong["manglik_dosh"]["status"]["strength"], "Strong")
        self.assertEqual(_summary(strong), "You are Mangalik.")
        partial = full_kundali_for(asc=0, moon=9, mars=4, jupiter=5)  # Mars Leo: 5th from Lagna, 8th from Moon (Capricorn)
        self.assertEqual(partial["manglik_dosh"]["status"]["strength"], "Partial")
        self.assertEqual(_summary(partial), "You are Mangalik (partial Mangal Dosh).")
        none = full_kundali_for(asc=0, moon=2, mars=4, jupiter=5)      # Mars Leo: 5th from Lagna, 3rd from Moon (Gemini)
        self.assertEqual(none["manglik_dosh"]["status"]["strength"], "None")
        self.assertEqual(_summary(none), "You are not Mangalik.")

    def test_hindi_display(self):
        k = {"manglik_dosh": {"status": {"strength": "Strong"}}}
        en = _summary(k)
        self.assertEqual(SB.build_manglik_summary_display(k, "en", en), en)
        hi = SB.build_manglik_summary_display(k, "hi", en)
        self.assertEqual(hi, "आप मांगलिक हैं।")
        for strength in ("Strong", "Partial", "Cancelled", "None", None):
            kk = {"manglik_dosh": {"status": {"strength": strength}}} if strength else {}
            text = SB.build_manglik_summary_display(kk, "hi", _summary(kk))
            self.assertNotRegex(text, r"[A-Za-z]", f"English left in Hindi display for {strength}: {text}")
        self.assertEqual(SB.build_manglik_summary_display({"manglik_dosh": {"status": {"strength": "None"}}}, "hi", ""), "आप मांगलिक नहीं हैं।")

    def test_hindi_pdf_uses_hindi_display(self):
        src = open(os.path.join(ROOT, "tasks.py"), encoding="utf-8").read()
        self.assertIn('pdf_summary_blocks["manglik_summary"] = build_manglik_summary_display(', src)

    def test_marriage_prompts_still_carry_the_placeholder(self):
        for lang in ("en", "hi"):
            self.assertIn("{manglik_summary}", open(os.path.join(ROOT, "prompts", f"marriage_report_{lang}.txt"), encoding="utf-8").read())


# ---------------------------------------------------------------------------------------------------------------
# 4. Ashtakoot is untouched and independent of Mars
# ---------------------------------------------------------------------------------------------------------------
NAKS = AK.NAKSHATRAS_27
# All 108 x 108 Moon-pada midpoints, per-koota scores, captured before the Mangal Dosh P0 change.
ASHTAKOOT_GRID_SHA256 = "ee1344c08985d6393c7de59290d31ba764288aefba60b80f7fe1e96042eb194c"


def _moon_at(lon):
    return {"rashi": SIGNS[int(lon // 30)], "nakshatra": NAKS[int(lon // (40 / 3))], "degree": lon % 30}


class AshtakootUnaffected(unittest.TestCase):
    def test_all_kootas_identical_to_before(self):
        pada = 40 / 3 / 4
        moons = [_moon_at((i + 0.5) * pada) for i in range(108)]
        grid = [[{k: v["score"] for k, v in AK.compute_ashtakoot(bride_moon=b, groom_moon=g)["kootas"].items()} for g in moons] for b in moons]
        self.assertEqual(hashlib.sha256(json.dumps(grid, sort_keys=True).encode()).hexdigest(), ASHTAKOOT_GRID_SHA256)

    def test_moving_mars_changes_mangal_not_ashtakoot(self):
        def moon_of(planets):
            m = next(p for p in planets if p["name"] == "Moon")
            return {"rashi": m["sign"], "degree": m["longitude"] % 30, "nakshatra": m["nakshatra"]}

        girl = planets_for(asc=4, moon=8, mars=3)
        boy_a = planets_for(asc=0, moon=2, mars=6)  # Mars Libra: 7th from Lagna (dosh), 5th from Moon
        boy_b = planets_for(asc=0, moon=2, mars=4)  # Mars Leo: 5th from Lagna, 3rd from Moon (no dosh)
        a = AK.compute_ashtakoot(bride_moon=moon_of(girl), groom_moon=moon_of(boy_a))
        b = AK.compute_ashtakoot(bride_moon=moon_of(girl), groom_moon=moon_of(boy_b))
        self.assertEqual({k: v["score"] for k, v in a["kootas"].items()}, {k: v["score"] for k, v in b["kootas"].items()})
        self.assertEqual(a["total_score"], b["total_score"])
        ma = MD.build_manglik_dosh({"planets": boy_a, "lagna_sign": "Aries"})["evaluation"]["triggers"]
        mb = MD.build_manglik_dosh({"planets": boy_b, "lagna_sign": "Aries"})["evaluation"]["triggers"]
        self.assertNotEqual(ma, mb)

    def test_engine_takes_no_mars_input(self):
        code = AK.compute_ashtakoot.__code__
        self.assertEqual(code.co_varnames[: code.co_argcount + code.co_kwonlyargcount], ("bride_moon", "groom_moon", "boy_is_groom"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
