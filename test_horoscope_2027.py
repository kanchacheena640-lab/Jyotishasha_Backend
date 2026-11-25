"""Personalized Horoscope 2027 -- evidence, validation, assembly and wiring.

No database, no OpenAI call, no PDF written, no email sent. The AI client is a
stub that returns fixed JSON.

Run: python -m unittest test_horoscope_2027 -v
"""
import json
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from full_kundali_api import calculate_full_kundali
from smart_transit_engine import get_planet_position_on
from modules.payments import horoscope_2027_evidence as he
from modules.payments import horoscope_2027_narrative as hn
from modules.payments.order_service import OrderValidationError, validate_report_order_fields
from modules.payments.report_ai_client import ReportAICompletion
from modules.payments.report_structured_output import ReportMetadataError

ROOT = Path(__file__).resolve().parent
CHARTS = [  # (dob, tob, lat, lon)
    ("1990-05-15", "10:30", 26.8467, 80.9462),
    ("1985-11-02", "05:45", 19.0760, 72.8777),
    ("2001-02-28", "23:10", 28.6139, 77.2090),
]
DRISHTI = {"Mars": (4, 7, 8), "Jupiter": (5, 7, 9), "Saturn": (3, 7, 10), "Rahu": (5, 7, 9), "Ketu": (5, 7, 9)}


def _kundali(i=0, language="en"):
    dob, tob, lat, lon = CHARTS[i]
    return calculate_full_kundali(name="Test", dob=dob, tob=tob, lat=lat, lon=lon, language=language)


def _filler(words, language):
    base = ("Steady effort and calm planning bring good progress in this area of life during the year. "
            if language == "en" else
            "इस वर्ष जीवन के इस क्षेत्र में धैर्य और शांत योजना से अच्छी प्रगति होती है। ").split()
    return " ".join(base[i % len(base)] for i in range(words))


def _responses(language, words=70, month_words=55):
    a = {"headline": _filler(25, language), "overview": _filler(130, language),
         "houses": {str(n): _filler(words, language) for n in range(1, 13)},
         "dasha": _filler(90, language), "transits": _filler(110, language)}
    b = {"months": {str(n): _filler(month_words, language) for n in range(1, 13)},
         "guidance": [_filler(20, language) for _ in range(5)], "summary": _filler(70, language)}
    return a, b


def _stub(parts):
    it = iter(json.dumps(p, ensure_ascii=False) for p in parts)
    return lambda prompt: ReportAICompletion(content=next(it), model="stub", input_tokens=10, output_tokens=20,
                                             total_tokens=30, duration_seconds=0.5)


class TransitMasterMatchesEngine(unittest.TestCase):
    """The data file is only trusted because the live engine agrees with it."""

    def test_every_2027_ingress_matches_live_ephemeris(self):
        master = he.load_transit_master()
        checked = 0
        for planet, events in master["events"].items():
            for e in events:
                if e["type"] != "ingress" or not e["ist"].startswith("2027"):
                    continue
                at = datetime.strptime(e["ist"], "%Y-%m-%d %H:%M")
                before = get_planet_position_on((at - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"), planet)
                after = get_planet_position_on((at + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"), planet)
                self.assertEqual((before["rashi"], after["rashi"]), (e["from"], e["to"]), f"{planet} {e['ist']}")
                checked += 1
        self.assertGreater(checked, 40)

    def test_every_2027_station_matches_live_motion(self):
        master = he.load_transit_master()
        for planet, events in master["events"].items():
            for e in events:
                if e["type"] not in ("retrograde", "direct") or not e["ist"].startswith("2027"):
                    continue
                at = datetime.strptime(e["ist"], "%Y-%m-%d %H:%M")
                before = get_planet_position_on((at - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"), planet)["motion"]
                after = get_planet_position_on((at + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"), planet)["motion"]
                expected = ("Direct", "Retrograde") if e["type"] == "retrograde" else ("Retrograde", "Direct")
                self.assertEqual((before, after), expected, f"{planet} {e['type']} {e['ist']}")

    def test_slow_planet_signs_on_2027_dates(self):
        for planet, rows in he._slow_segments(he.load_transit_master(), "Aries", "Aries").items():
            for r in rows:
                mid = max(r["from"], "2027-01-01")
                probe = (datetime.strptime(mid, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
                if probe < r["to"]:
                    self.assertEqual(get_planet_position_on(probe, planet)["rashi"], r["sign"], f"{planet} {probe}")


class SaturnMoonCycles(unittest.TestCase):
    def test_sade_sati_and_dhaiya_match_master_matrix_for_all_12_moon_signs(self):
        master = he.load_transit_master()
        for moon in he.SIGNS:
            saturn = he._slow_segments(master, "Aries", moon)["Saturn"]
            periods = he._saturn_moon_periods(saturn)
            matrix = master["moon_sign_matrix_2027"][moon]
            ours = [(p["sign"], p["from"]) for p in periods["sade_sati"]]
            theirs = [(p["saturn_sign"], p["from_ist"][:10]) for p in matrix["sade_sati"]]
            self.assertEqual(sorted(ours), sorted(theirs), moon)
            self.assertEqual(len(periods["dhaiya"]), len(matrix["dhaiya"]), moon)


class Evidence(unittest.TestCase):
    def test_all_12_houses_including_empty_and_consistent(self):
        for i in range(len(CHARTS)):
            k = _kundali(i)
            ev = he.build_horoscope_2027_evidence(k)
            self.assertEqual([h["house"] for h in ev["houses"]], list(range(1, 13)))
            occupants = sorted(p for h in ev["houses"] for p in h["occupants"])
            self.assertEqual(occupants, sorted(he.GRAHAS))
            self.assertTrue(any(not h["occupants"] for h in ev["houses"]), "a chart always has empty houses")
            for h in ev["houses"]:
                self.assertEqual(h["lord"], he.SIGN_LORDS[h["sign"]])
                self.assertEqual(h["lord_house"], ev["planets"][h["lord"]]["house"])
                expected = sorted({p for p, rec in ev["planets"].items()
                                   if (h["house"] - rec["house"]) % 12 + 1 in DRISHTI.get(p, (7,))},
                                  key=he.GRAHAS.index)
                self.assertEqual(h["aspected_by"], expected, f"chart {i} house {h['house']}")

    def test_dashas_cover_2027_and_dates_are_allowed(self):
        ev = he.build_horoscope_2027_evidence(_kundali(1))
        self.assertLessEqual(ev["dashas"][0]["from"], "2027-01-01")
        self.assertGreaterEqual(ev["dashas"][-1]["to"], "2027-12-31")
        self.assertIn("2027-06-03", ev["allowed_dates"])  # Saturn enters Aries
        self.assertEqual(len(ev["months"]), 12)

    def test_inconsistent_chart_fails_before_ai(self):
        k = _kundali(0)
        k["planets"] = [p for p in k["planets"] if p["name"] != "Venus"]
        with self.assertRaises(ReportMetadataError):
            he.build_horoscope_2027_evidence(k)

    def test_total_solar_eclipse_is_partial_in_india(self):
        ev = he.build_horoscope_2027_evidence(_kundali(0))
        aug = [e for e in ev["eclipses"] if e["date"] == "2027-08-02"][0]
        self.assertTrue(aug["visible_in_india"] and aug["partial_in_india"])


class Validation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = {lang: he.build_horoscope_2027_evidence(_kundali(0, lang)) for lang in hn.LANGUAGES}

    def _a(self, language="en", **override):
        a, _ = _responses(language)
        a.update(override)
        return json.dumps(a, ensure_ascii=False)

    def test_valid_responses_pass_both_languages(self):
        for lang in hn.LANGUAGES:
            prompts = hn.build_horoscope_2027_prompts(self.ev[lang], lang)
            sections, agg = hn.generate_horoscope_2027_sections(prompts, self.ev[lang], lang,
                                                                _stub(_responses(lang)))
            self.assertEqual(set(sections), set(hn.PART_KEYS["A"]) | set(hn.PART_KEYS["B"]))
            self.assertEqual(agg.total_tokens, 60)

    def test_prompt_has_facts_but_no_customer_details(self):
        prompt = hn.build_horoscope_2027_prompts(self.ev["en"], "en")[0]
        self.assertIn("HOUSE 12", prompt)
        self.assertIn("3 June 2027", prompt)
        self.assertNotIn("1990-05-15", prompt)  # birth date never sent
        self.assertNotIn("10:30", prompt)       # birth time never sent
        self.assertNotIn("Test", prompt)        # customer name never sent

    def test_invented_house_placement_is_rejected(self):
        allowed = self.ev["en"]["allowed_placements"]["Saturn"]["houses"]
        wrong = next(n for n in range(1, 13) if n not in allowed)
        houses = {str(n): _filler(70, "en") for n in range(1, 13)}
        houses["3"] += f" Saturn is now in your {hn.EN_ORDINALS[wrong]} house this year."
        with self.assertRaisesRegex(ReportMetadataError, "never in house"):
            hn.validate_part("A", self._a(houses=houses), self.ev["en"], "en")

    def test_true_placement_is_accepted(self):
        house = self.ev["en"]["slow_transits"]["Jupiter"][0]["house_from_lagna"]
        houses = {str(n): _filler(70, "en") for n in range(1, 13)}
        houses["1"] += f" Jupiter moves into your {hn.EN_ORDINALS[house]} house."
        hn.validate_part("A", self._a(houses=houses), self.ev["en"], "en")

    def test_invented_sign_and_date_and_year_are_rejected(self):
        for extra, pattern in [(" Saturn moves into Leo.", "never in Leo"),
                               (" Expect news on 14 March 2027.", "not in the report's calculated dates"),
                               (" Expect news on 2027-03-14.", "not in the report's calculated dates"),
                               (" This continues until 2035.", "outside the report's calculated periods")]:
            with self.assertRaisesRegex(ReportMetadataError, pattern):
                hn.validate_part("A", self._a(overview=_filler(130, "en") + extra), self.ev["en"], "en")

    def test_banned_wording_and_missing_house_are_rejected(self):
        with self.assertRaisesRegex(ReportMetadataError, "banned"):
            hn.validate_part("A", self._a(overview=_filler(130, "en") + " Success is guaranteed."), self.ev["en"], "en")
        houses = {str(n): _filler(70, "en") for n in range(1, 12)}
        with self.assertRaisesRegex(ReportMetadataError, "exactly the keys 1-12"):
            hn.validate_part("A", self._a(houses=houses), self.ev["en"], "en")

    def test_hindi_invented_house_is_rejected(self):
        allowed = self.ev["hi"]["allowed_placements"]["Saturn"]["houses"]
        wrong = next(n for n in range(1, 13) if n not in allowed)
        houses = {str(n): _filler(70, "hi") for n in range(1, 13)}
        houses["2"] += f" शनि आपके {hn.HI_ORDINALS_OBLIQUE[wrong]} भाव में रहेगा।"
        with self.assertRaisesRegex(ReportMetadataError, "never in house"):
            hn.validate_part("A", self._a("hi", houses=houses), self.ev["hi"], "hi")

    def test_too_short_report_is_rejected(self):
        ev = self.ev["en"]
        prompts = hn.build_horoscope_2027_prompts(ev, "en")
        with self.assertRaisesRegex(ReportMetadataError, "too short"):
            hn.generate_horoscope_2027_sections(prompts, ev, "en", _stub(_responses("en", words=30, month_words=30)))


class Assembly(unittest.TestCase):
    def test_pdf_payload(self):
        for lang in hn.LANGUAGES:
            ev = he.build_horoscope_2027_evidence(_kundali(0, lang))
            sections, _ = hn.generate_horoscope_2027_sections(hn.build_horoscope_2027_prompts(ev, lang), ev, lang,
                                                              _stub(_responses(lang)))
            report = hn.assemble_horoscope_2027_report(sections, ev, lang)
            headings = re.findall(r"^\*\*(\d+)\. ", report["narrative"], re.M)
            self.assertEqual([int(h) for h in headings], list(range(1, 29)))  # overview, 12 houses, dasha, transits, 12 months, summary
            empty = UI_EMPTY[lang]
            self.assertEqual(report["narrative"].count(empty), sum(1 for h in ev["houses"] if not h["occupants"]))
            self.assertEqual(len(report["pdf_kwargs"]["tables"]), 4)
            self.assertEqual(report["pdf_kwargs"]["narrative_style"], "plain")
            self.assertIn(hn.P(ev["dashas"][0]["mahadasha"], lang), report["answer_hero"]["value"])
            self.assertTrue(report["disclaimer"])


UI_EMPTY = {"en": "planets: none (empty house)", "hi": "ग्रह: कोई नहीं (खाली भाव)"}


class OrderValidation(unittest.TestCase):
    payload = {"name": "A", "email": "a@example.com", "phone": "9999999999", "dob": "1990-05-15", "tob": "10:30",
               "pob": "Lucknow", "latitude": "26.8", "longitude": "80.9"}

    def test_birth_time_and_place_required_for_this_product_only(self):
        product = SimpleNamespace(report_slug=he.PRODUCT_SLUG, generator="standard_v1")
        validate_report_order_fields(product, dict(self.payload))
        for bad in ({"tob": "10.30am"}, {"latitude": "0", "longitude": "0"}):
            with self.assertRaises(OrderValidationError):
                validate_report_order_fields(product, {**self.payload, **bad})
        other = SimpleNamespace(report_slug="career_report", generator="standard_v1")
        validate_report_order_fields(other, {**self.payload, "tob": "10.30am"})  # unchanged behaviour


class TaskWiring(unittest.TestCase):
    def test_tasks_branch_and_unique_filename(self):
        src = (ROOT / "tasks.py").read_text(encoding="utf-8")
        self.assertIn('output_path = f"/home/Jyotishasha/reports/{product_slug}_{order_id}.pdf"', src)
        self.assertIn("generate_horoscope_2027_sections(", src)
        self.assertLess(src.index("elif product_slug == HOROSCOPE_2027_SLUG:\n                h27_report"),
                        src.index("elif product_intel.q3_enabled:"))
        self.assertIn('**(h27_report["pdf_kwargs"] if product_slug == HOROSCOPE_2027_SLUG else {})', src)

    def test_prompt_files_exist_for_both_languages(self):
        for lang in hn.LANGUAGES:
            text = (ROOT / "prompts" / f"{he.PRODUCT_SLUG}_{lang}.txt").read_text(encoding="utf-8")
            self.assertIn("{facts_block}", text)
            self.assertIn("{part}", text)


if __name__ == "__main__":
    unittest.main()
