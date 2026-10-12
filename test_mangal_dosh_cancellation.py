"""
Mangal Dosh cancellation activation (2026-10) -- the three cancellation rules already written in
services/mangalik_dosh_logic.py, now supplied with the data they read. Conditions are exactly as coded:

  1. Mars own/exalted sign: Aries, Scorpio, Capricorn (already worked).
  2. Jupiter in a Kendra (1/4/7/10) from Lagna OR from Moon -- Jupiter's houses are counted like Mars':
     whole-sign from the chart, inclusive sign count from the Moon.
  3. Jupiter aspecting Mars or in the same sign as Mars. Aspects are the chart's own drishti list
     (full_kundali_api.calculate_drishti_for_planets); conjunction means the same sign (whole-sign house),
     not a close-degree conjunction -- the convention chandra_mangal.py already uses.

Each rule removes one trigger (Lagna/Moon); the severity mapping is unchanged. Owner decisions (2026-10):
Lagna + Moon only (no Venus reference); Jupiter-in-Kendra is a Jyotishasha project convention; Mercury and
Venus never cancel automatically; no new conditions, planets, aspects, weights or severity formulas.

Synthetic charts via the Swiss Ephemeris stand-in from test_mangal_dosh_p0. No network, database or AI.
Run:  python test_mangal_dosh_cancellation.py
"""
import os
import sys
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import full_kundali_api as FK  # noqa: E402
import summary_blocks as SB  # noqa: E402
from modules.love.mangal_dosh_comparator import compare_mangal_dosh  # noqa: E402
from modules.services.static_astrology_extractor import extract_static_dosh  # noqa: E402
from services import mangalik_dosh_logic as MD  # noqa: E402
from test_mangal_dosh_p0 import REAL_SWE, _StandInSwe  # noqa: E402

ARIES, TAURUS, GEMINI, CANCER, LEO, VIRGO, LIBRA, SCORPIO, SAG, CAP, AQUARIUS, PISCES = range(12)


def _lon(sign):
    return sign * 30 + 15.0


def chart_planets(asc, moon, mars, jupiter, venus=TAURUS, mercury=TAURUS, sun=TAURUS, saturn=TAURUS, rahu=TAURUS):
    """Every body placed explicitly (15 deg into its sign); the exact planet list the engine receives."""
    FK.swe = _StandInSwe({"ASC": _lon(asc), REAL_SWE.MOON: _lon(moon), REAL_SWE.MARS: _lon(mars), REAL_SWE.JUPITER: _lon(jupiter),
                          REAL_SWE.VENUS: _lon(venus), REAL_SWE.MERCURY: _lon(mercury), REAL_SWE.SUN: _lon(sun),
                          REAL_SWE.SATURN: _lon(saturn), REAL_SWE.MEAN_NODE: _lon(rahu)})
    try:
        planets = FK.calculate_planet_positions("1990-06-15", "12:00", 28.6139, 77.2090)
        drishti = FK.calculate_drishti_for_planets(planets)  # same enrichment calculate_full_kundali() applies
        for p in planets:
            p["aspecting"] = drishti[p["name"]]["aspecting"]
            p["aspected_by"] = drishti[p["name"]]["aspected_by"]
        return planets
    finally:
        FK.swe = REAL_SWE


def full_kundali(language="en", **pos):
    defaults = dict(venus=TAURUS, mercury=TAURUS, sun=TAURUS, saturn=TAURUS, rahu=TAURUS)
    defaults.update(pos)
    FK.swe = _StandInSwe({"ASC": _lon(defaults["asc"]), REAL_SWE.MOON: _lon(defaults["moon"]), REAL_SWE.MARS: _lon(defaults["mars"]),
                          REAL_SWE.JUPITER: _lon(defaults["jupiter"]), REAL_SWE.VENUS: _lon(defaults["venus"]),
                          REAL_SWE.MERCURY: _lon(defaults["mercury"]), REAL_SWE.SUN: _lon(defaults["sun"]),
                          REAL_SWE.SATURN: _lon(defaults["saturn"]), REAL_SWE.MEAN_NODE: _lon(defaults["rahu"])})
    try:
        return FK.calculate_full_kundali("SYNTHETIC Cancellation", "1990-06-15", "12:00", 28.6139, 77.2090, language=language)
    finally:
        FK.swe = REAL_SWE


def mangal(**pos):
    planets = chart_planets(**pos)
    return MD.build_manglik_dosh({"planets": planets, "lagna_sign": "x"})


def flags(md):
    f = md["context"]["cancellation_flags"]
    return (f["mars_own_or_exalted"], f["jupiter_in_kendra_from_lagna_or_moon"], f["benefic_aspect_or_conjunction_on_mars"])


# Mars in Libra from an Aries Lagna = 7th (trigger). Parking sign Taurus: no Kendra, aspect or conjunction on Libra.
class EachRuleAlone(unittest.TestCase):
    def test_no_cancellation(self):
        md = mangal(asc=ARIES, moon=VIRGO, mars=LIBRA, jupiter=TAURUS)  # Moon Virgo -> Mars 2nd (trigger)
        self.assertEqual(flags(md), (False, False, False))
        self.assertEqual(md["evaluation"]["triggers"], {"from_lagna": True, "from_moon": True})
        self.assertEqual((md["status"]["strength"], md["evaluation"]["mitigations"]), ("Strong", []))

    def test_own_or_exalted_only(self):
        # Jupiter in Leo: 2nd/12th, aspects Sagittarius/Aquarius/Aries -- never Capricorn (Taurus would, by 9th drishti).
        md = mangal(asc=ARIES, moon=VIRGO, mars=CAP, jupiter=LEO)  # Mars Capricorn: 10th L (no), 5th M (no)
        md2 = mangal(asc=CANCER, moon=VIRGO, mars=CAP, jupiter=LEO)  # 7th from Cancer Lagna (trigger), 5th M
        self.assertEqual(flags(md2), (True, False, False))
        self.assertEqual(md2["status"]["strength"], "Cancelled")
        self.assertEqual(md["status"]["strength"], "None")  # no trigger -> no cancellation needed

    def test_jupiter_kendra_from_lagna_only(self):
        md = mangal(asc=ARIES, moon=PISCES, mars=LIBRA, jupiter=CANCER)  # Jupiter 4th L; aspects Sc/Cp/Pi, not Libra
        self.assertEqual((md["context"]["jupiter_house_from_lagna"], md["context"]["jupiter_house_from_moon"]), (4, 5))
        self.assertEqual(flags(md), (False, True, False))
        self.assertEqual(md["evaluation"]["triggers"], {"from_lagna": True, "from_moon": True})  # Mars 8th from Pisces
        self.assertEqual(md["status"]["strength"], "Partial")  # 2 triggers - 1 mitigation

    def test_jupiter_kendra_from_moon_only(self):
        md = mangal(asc=ARIES, moon=LEO, mars=LIBRA, jupiter=SCORPIO)  # Jupiter 8th L, 4th from Moon Leo
        self.assertEqual((md["context"]["jupiter_house_from_lagna"], md["context"]["jupiter_house_from_moon"]), (8, 4))
        self.assertEqual(flags(md), (False, True, False))
        self.assertEqual(md["status"]["strength"], "Cancelled")  # 1 trigger (Lagna 7th; Moon 3rd) - 1 mitigation

    def test_jupiter_same_sign_as_moon_is_first_kendra(self):
        md = mangal(asc=ARIES, moon=SAG, mars=LIBRA, jupiter=SAG)  # inclusive count: Moon's own sign is the 1st
        self.assertEqual(md["context"]["jupiter_house_from_moon"], 1)
        self.assertTrue(flags(md)[1])

    def test_jupiter_aspect_only(self):
        md = mangal(asc=ARIES, moon=LEO, mars=LIBRA, jupiter=GEMINI)  # Jupiter 5th drishti from Gemini falls on Libra
        self.assertEqual((md["context"]["jupiter_house_from_lagna"], md["context"]["jupiter_house_from_moon"]), (3, 11))
        self.assertEqual(flags(md), (False, False, True))
        self.assertEqual(md["context"]["benefic_aspects_on_mars"], ["Jupiter"])
        self.assertEqual(md["status"]["strength"], "Cancelled")

    def test_jupiter_same_sign_conjunction_only(self):
        # Mars and Jupiter in Taurus: 2nd from Lagna (trigger, not a Kendra), 9th from Moon Virgo (neither).
        md = mangal(asc=ARIES, moon=VIRGO, mars=TAURUS, jupiter=TAURUS)
        self.assertEqual((md["context"]["jupiter_house_from_lagna"], md["context"]["jupiter_house_from_moon"]), (2, 9))
        self.assertEqual(flags(md), (False, False, True))
        self.assertEqual((md["context"]["benefic_conjunctions_with_mars"], md["context"]["benefic_aspects_on_mars"]), (["Jupiter"], []))
        self.assertEqual(md["status"]["strength"], "Cancelled")  # 1 trigger - 1

    def test_venus_and_mercury_never_cancel(self):
        """Owner decision: Mercury and Venus are not cancellation planets, by aspect or by same-sign conjunction."""
        cases = {
            "venus aspect": dict(venus=ARIES),          # 7th drishti onto Libra
            "mercury aspect": dict(mercury=ARIES),
            "venus conjunction": dict(venus=LIBRA),
            "mercury conjunction": dict(mercury=LIBRA),
            "both, both ways": dict(venus=LIBRA, mercury=ARIES),
        }
        for label, extra in cases.items():
            md = mangal(asc=ARIES, moon=VIRGO, mars=LIBRA, jupiter=TAURUS, **extra)
            self.assertEqual(flags(md), (False, False, False), label)
            self.assertEqual((md["context"]["benefic_aspects_on_mars"], md["context"]["benefic_conjunctions_with_mars"]), ([], []), label)
            self.assertEqual(md["status"]["strength"], "Strong", label)  # 2 triggers, nothing cancels
        # Their data is still there for every other calculation.
        planets = chart_planets(asc=ARIES, moon=VIRGO, mars=LIBRA, jupiter=TAURUS, venus=ARIES, mercury=LIBRA)
        mars = next(p for p in planets if p["name"] == "Mars")
        self.assertIn("Venus (7th drishti)", mars["aspected_by"])
        self.assertEqual(next(p for p in planets if p["name"] == "Mercury")["house"], mars["house"])

    def test_malefics_and_the_ascendant_never_cancel(self):
        # Saturn and the Sun conjunct Mars, Rahu aspects it, and the Ascendant appears in its aspect list.
        md = mangal(asc=ARIES, moon=VIRGO, mars=LIBRA, jupiter=TAURUS, saturn=LIBRA, sun=LIBRA, rahu=GEMINI)
        planets = chart_planets(asc=ARIES, moon=VIRGO, mars=LIBRA, jupiter=TAURUS, saturn=LIBRA, sun=LIBRA, rahu=GEMINI)
        mars = next(p for p in planets if p["name"] == "Mars")
        self.assertTrue(any(a.startswith("Ascendant") for a in mars["aspected_by"]))
        self.assertTrue(any(a.startswith("Rahu") for a in mars["aspected_by"]))
        self.assertEqual(flags(md), (False, False, False))
        self.assertEqual(md["context"]["benefic_conjunctions_with_mars"], [])
        self.assertEqual(md["status"]["strength"], "Strong")


class RulesTogether(unittest.TestCase):
    def test_all_three(self):
        md = mangal(asc=ARIES, moon=ARIES, mars=ARIES, jupiter=ARIES)  # own sign, Jupiter 1st (Kendra), conjunct
        self.assertEqual(flags(md), (True, True, True))
        self.assertEqual(md["evaluation"]["mitigations"],
                         ["Mars in own/exalted sign", "Jupiter in Kendra (from Lagna/Moon)", "Benefic aspect/conjunction on Mars"])
        self.assertEqual(md["status"]["strength"], "Cancelled")  # 2 triggers - 3

    def test_two_rules_two_triggers(self):
        # Jupiter in Aries: 1st from Lagna (Kendra) and its 7th drishti falls on Mars in Libra.
        md = mangal(asc=ARIES, moon=PISCES, mars=LIBRA, jupiter=ARIES)
        self.assertEqual(md["evaluation"]["triggers"], {"from_lagna": True, "from_moon": True})
        self.assertEqual(flags(md), (False, True, True))
        self.assertEqual(md["context"]["benefic_aspects_on_mars"], ["Jupiter"])
        self.assertEqual(md["status"]["strength"], "Cancelled")  # 2 triggers - 2

    def test_severity_mapping_unchanged(self):
        for (fl, fm, mits), exp in {(True, True, 0): "Strong", (True, True, 1): "Partial", (True, True, 2): "Cancelled",
                                    (True, False, 0): "Partial", (True, False, 1): "Cancelled", (False, False, 3): "None"}.items():
            self.assertEqual(MD._severity_score(fl, fm, mits > 0, mits > 1, mits > 2)[0], exp)


class MissingData(unittest.TestCase):
    BASE = [{"name": "Mars", "sign": "Libra", "house": 7}, {"name": "Moon", "sign": "Virgo", "house": 6}]

    def run_engine(self, extra, **mars_fields):
        planets = [dict(p) for p in self.BASE] + extra
        next(p for p in planets if p["name"] == "Mars").update(mars_fields)
        return MD.build_manglik_dosh({"planets": planets})

    def test_no_jupiter_no_kendra(self):
        md = self.run_engine([])
        self.assertFalse(flags(md)[1])
        self.assertEqual((md["context"]["jupiter_house_from_lagna"], md["context"]["jupiter_house_from_moon"]), (0, 0))

    def test_invalid_jupiter_house_no_kendra(self):
        for h in (None, 0, 13, "x"):
            self.assertFalse(flags(self.run_engine([{"name": "Jupiter", "house": h}]))[1], h)

    def test_no_moon_only_lagna_kendra_counts(self):
        md = MD.build_manglik_dosh({"planets": [{"name": "Mars", "sign": "Libra", "house": 7}, {"name": "Jupiter", "house": 10}]})
        self.assertEqual((md["context"]["jupiter_house_from_lagna"], md["context"]["jupiter_house_from_moon"]), (10, 0))
        self.assertTrue(flags(md)[1])

    def test_unknown_mars_house_gives_no_conjunction(self):
        md = MD.build_manglik_dosh({"planets": [{"name": "Mars", "sign": "Libra"}, {"name": "Jupiter", "house": 7}]})
        self.assertEqual(md["context"]["benefic_conjunctions_with_mars"], [])
        self.assertFalse(flags(md)[2])

    def test_malformed_aspect_entries_ignored(self):
        md = self.run_engine([], aspected_by=[None, 7, {}, {"name": None}, "Jupiterish", "Saturn (7th drishti)", "Venus (7th drishti) extra"])
        self.assertFalse(flags(md)[2])
        self.assertEqual(md["context"]["benefic_aspects_on_mars"], [])

    def test_aspect_dicts_still_supported(self):
        md = self.run_engine([], aspected_by=[{"name": "Jupiter"}])
        self.assertTrue(flags(md)[2])

    def test_explicit_conjunct_list_is_respected(self):
        md = self.run_engine([{"name": "Jupiter", "house": 7}], conjunct=[])  # caller says: no conjunctions
        self.assertFalse(flags(md)[2])
        md = self.run_engine([{"name": "Jupiter", "house": 7}])                # derived from the same sign
        self.assertEqual(md["context"]["benefic_conjunctions_with_mars"], ["Jupiter"])


class ConsistencyAndLanguage(unittest.TestCase):
    POS = dict(asc=ARIES, moon=PISCES, mars=LIBRA, jupiter=CANCER)  # Jupiter Kendra -> Partial (was Strong)

    def test_tool_love_paid_and_stored_data_agree(self):
        k = full_kundali(**self.POS)
        tool = k["manglik_dosh"]["status"]["strength"]
        love = compare_mangal_dosh(k, k)["boy"]["status"]["strength"]
        paid = SB.build_summary_blocks_with_transit(k, {})["manglik_summary"]
        stored = extract_static_dosh(k).get("manglik", {}).get("severity")
        self.assertEqual((tool, love, stored), ("Partial", "Partial", "Partial"))
        self.assertEqual(paid, "You are Mangalik (partial Mangal Dosh).")

    def test_hindi_and_english_same_result_different_text(self):
        en, hi = full_kundali(language="en", **self.POS)["manglik_dosh"], full_kundali(language="hi", **self.POS)["manglik_dosh"]
        self.assertEqual((en["language"], hi["language"]), ("en", "hi"))
        self.assertEqual(en["evaluation"], hi["evaluation"])
        for key in ("mars_house_from_lagna", "mars_house_from_moon", "jupiter_house_from_lagna", "jupiter_house_from_moon", "cancellation_flags"):
            self.assertEqual(en["context"][key], hi["context"][key], key)
        self.assertEqual(hi["status"]["is_mangalic"], MD.LANG["hi"]["human_status"]["Partial"])
        self.assertEqual(hi["heading"], "मंगल दोष विश्लेषण")
        self.assertTrue(any("गुरु" in p for p in hi["report_paragraphs"]))  # Hindi Jupiter-Kendra paragraph
        self.assertEqual(en["status"]["is_mangalic"], "Yes, you are Mangalic (Mitigated/Partial)")

    def test_hindi_text_has_no_english_planet_names(self):
        pos = dict(asc=ARIES, moon=ARIES, mars=ARIES, jupiter=ARIES)  # all three rules fire -> every paragraph
        hi = full_kundali(language="hi", **pos)["manglik_dosh"]
        en = full_kundali(language="en", **pos)["manglik_dosh"]
        text = " ".join(hi["report_paragraphs"] + hi["summary_block"]["points"])
        for word in ("Jupiter", "Venus", "Mercury", "Mars", "Moon", "Kendra", "Benefic"):
            self.assertNotIn(word, text, word)
        self.assertIn("गुरु", text)
        self.assertIn("मंगल पर गुरु की दृष्टि/एक ही राशि में युति", hi["summary_block"]["points"][1])
        self.assertEqual(hi["evaluation"]["mitigations"], en["evaluation"]["mitigations"])  # machine values stay English
        self.assertIn("Jupiter in the same sign as Mars (same-sign conjunction)", " ".join(en["report_paragraphs"]))

    def test_moon_sign_now_in_context(self):
        self.assertEqual(full_kundali(**self.POS)["manglik_dosh"]["context"]["moon_sign"], "Pisces")


class SupportParagraphWording(unittest.TestCase):
    """The benefic-support paragraph names only what applies; it never prints an empty "None ..." part."""
    CASES = {
        "aspect only": (dict(asc=ARIES, moon=LEO, mars=LIBRA, jupiter=GEMINI),
                        "Benefic support is present (aspect from Jupiter on Mars), which softens the intensity of Mars",
                        "शुभ प्रभाव उपस्थित है (मंगल पर गुरु की दृष्टि), जिससे"),
        "same sign only": (dict(asc=ARIES, moon=VIRGO, mars=TAURUS, jupiter=TAURUS),
                           "Benefic support is present (Jupiter in the same sign as Mars (same-sign conjunction)), which softens",
                           "शुभ प्रभाव उपस्थित है (गुरु की मंगल के साथ एक ही राशि में युति), जिससे"),
    }

    def paragraph(self, pos, lang):
        md = MD.build_manglik_dosh({"planets": chart_planets(**pos)}, lang)
        return next(p for p in md["report_paragraphs"] if p.startswith(("Benefic support", "शुभ प्रभाव")))

    def test_each_case_en_hi(self):
        for label, (pos, en_start, hi_start) in self.CASES.items():
            en, hi = self.paragraph(pos, "en"), self.paragraph(pos, "hi")
            self.assertTrue(en.startswith(en_start), f"{label}: {en}")
            self.assertTrue(hi.startswith(hi_start), f"{label}: {hi}")
            for text in (en, hi):
                self.assertNotIn("None", text)
                self.assertNotIn("कोई नहीं", text)

    def test_aspect_and_conjunction_together(self):
        # Hand-built: Jupiter both aspecting Mars (as listed) and in Mars' sign.
        planets = [{"name": "Mars", "sign": "Libra", "house": 7, "aspected_by": ["Jupiter (7th drishti)"]},
                   {"name": "Moon", "house": 6}, {"name": "Jupiter", "house": 7}]
        en = MD.build_manglik_dosh({"planets": planets}, "en")["report_paragraphs"]
        hi = MD.build_manglik_dosh({"planets": planets}, "hi")["report_paragraphs"]
        self.assertIn("(aspect from Jupiter on Mars; Jupiter in the same sign as Mars (same-sign conjunction))", " ".join(en))
        self.assertIn("(मंगल पर गुरु की दृष्टि; गुरु की मंगल के साथ एक ही राशि में युति)", " ".join(hi))

    def test_no_paragraph_without_support(self):
        md = MD.build_manglik_dosh({"planets": chart_planets(asc=ARIES, moon=VIRGO, mars=LIBRA, jupiter=TAURUS, venus=ARIES)}, "en")
        self.assertFalse(any(p.startswith("Benefic support") for p in md["report_paragraphs"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
