"""Focused Reports prototype -- "Promotion Report: Next 12 Months" (deterministic tests, NO Luna call).

Proves that the prompt is assembled from the existing Kundali calculation + the existing Career Report evidence + a
few concise transit facts, that the transit facts are correct (frozen clock, cross-checked against an independent
ephemeris primitive), that the customer question is simple and present, that no heuristic shadbala / PII / unrelated
astrology is sent, and that the prototype is isolated from the production report pipeline.
"""
import contextlib
import datetime
import io
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.pop("OPENAI_API_KEY", None)  # this prototype must never be able to reach Luna

import pytz  # noqa: E402

import transit_engine  # noqa: E402
from smart_transit_engine import get_planet_position_on  # noqa: E402
from summary_blocks import _house_from_lagna, build_summary_blocks_with_transit  # noqa: E402
from modules.payments.report_structured_output import parse_structured_response, validate_required_hero_fields  # noqa: E402
from modules.focused_reports import promotion_next_12_months as report  # noqa: E402
from modules.focused_reports import promotion_transit_evidence as evidence_module  # noqa: E402
from modules.payments.report_date_format import EN_MONTHS, HI_MONTHS, normalize_customer_dates  # noqa: E402

REPO = Path(__file__).resolve().parent
IST = pytz.timezone("Asia/Kolkata")
FROZEN_NOW = IST.localize(datetime.datetime(2026, 9, 21, 12, 0, 0))

FIXTURE = dict(name="Fixture Person", dob="1990-06-15", tob="14:30", pob="Lucknow", lat=26.8467, lon=80.9462)


def frozen_clock():
    return patch("transit_engine._ist_now", return_value=FROZEN_NOW)


def fixture_kundali():
    from full_kundali_api import calculate_full_kundali
    with contextlib.redirect_stdout(io.StringIO()):
        return calculate_full_kundali(FIXTURE["name"], FIXTURE["dob"], FIXTURE["tob"], FIXTURE["lat"], FIXTURE["lon"], language="en")


class TransitEvidenceTests(unittest.TestCase):
    def setUp(self):
        patcher = frozen_clock()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.evidence = evidence_module.build_promotion_transit_evidence("Libra")
        self.by_planet = {item["planet"]: item for item in self.evidence["planets"]}

    def test_only_the_three_selected_planets_each_with_a_reason(self):
        self.assertEqual(evidence_module.PROMOTION_TRANSIT_PLANETS, ("Jupiter", "Saturn", "Rahu"))
        self.assertEqual([p["planet"] for p in self.evidence["planets"]], ["Jupiter", "Saturn", "Rahu"])
        for planet in evidence_module.PROMOTION_TRANSIT_PLANETS:
            self.assertGreater(len(evidence_module.SELECTION_REASONS[planet]), 60)
            self.assertEqual(self.by_planet[planet]["reason"], evidence_module.SELECTION_REASONS[planet])
        for excluded in ("Sun", "Moon", "Mars", "Mercury", "Venus", "Ketu"):
            self.assertNotIn(excluded, self.by_planet)

    def test_horizon_is_exactly_twelve_months_from_the_engines_own_clock(self):
        self.assertEqual(self.evidence["as_of"], "2026-09-21")
        self.assertEqual(self.evidence["horizon_end"], "2027-09-21")
        self.assertEqual(evidence_module._add_months(datetime.date(2028, 2, 29), 12), datetime.date(2029, 2, 28))
        self.assertEqual(evidence_module._add_months(datetime.date(2026, 12, 31), 12), datetime.date(2027, 12, 31))

    def test_current_facts_agree_with_the_live_transit_engine(self):
        positions = transit_engine.get_current_positions()["positions"]
        for planet, item in self.by_planet.items():
            current = item["current"]
            self.assertEqual(current["sign"], positions[planet]["rashi"])
            self.assertEqual(current["motion"], positions[planet]["motion"])
            self.assertEqual(current["house_from_lagna"], _house_from_lagna(current["sign"], "Libra"))
            self.assertIsNotNone(current["until"])
            self.assertGreaterEqual(current["until"], self.evidence["as_of"])

    def test_pinned_facts_for_the_frozen_date(self):
        jupiter, saturn, rahu = (self.by_planet[p] for p in ("Jupiter", "Saturn", "Rahu"))
        self.assertEqual((jupiter["current"]["sign"], jupiter["current"]["house_from_lagna"], jupiter["current"]["until"]), ("Cancer", 10, "2026-10-30"))
        self.assertEqual([(c["on"], c["to_sign"], c["house_from_lagna"], c["motion"]) for c in jupiter["changes_in_horizon"]], [
            ("2026-10-31", "Leo", 11, "Direct"),
            ("2027-01-25", "Cancer", 10, "Retrograde"),
            ("2027-06-26", "Leo", 11, "Direct"),
        ])
        self.assertEqual([c["until"] for c in jupiter["changes_in_horizon"][:2]], ["2027-01-24", "2027-06-25"])
        self.assertTrue(jupiter["changes_in_horizon"][-1]["continues_beyond_horizon"])
        self.assertEqual((saturn["current"]["sign"], saturn["current"]["house_from_lagna"], saturn["current"]["motion"], saturn["current"]["until"]),
                         ("Pisces", 6, "Retrograde", "2027-06-02"))
        self.assertEqual([(c["on"], c["to_sign"], c["house_from_lagna"]) for c in saturn["changes_in_horizon"]], [("2027-06-03", "Aries", 7)])
        self.assertEqual((rahu["current"]["sign"], rahu["current"]["house_from_lagna"], rahu["current"]["until"]), ("Aquarius", 5, "2026-12-04"))
        self.assertEqual([(c["on"], c["to_sign"], c["house_from_lagna"], c["motion"]) for c in rahu["changes_in_horizon"]], [("2026-12-05", "Capricorn", 4, "Retrograde")])

    def test_change_lists_are_consistent_and_inside_the_horizon(self):
        for planet, item in self.by_planet.items():
            previous_sign, previous_until = item["current"]["sign"], item["current"]["until"]
            for change in item["changes_in_horizon"]:
                self.assertEqual(change["from_sign"], previous_sign, f"{planet}: chain continuity")
                self.assertGreater(change["on"], previous_until)
                self.assertLessEqual(change["on"], self.evidence["horizon_end"])
                self.assertGreaterEqual(change["until"], change["on"])
                self.assertEqual(change["house_from_lagna"], _house_from_lagna(change["to_sign"], "Libra"))
                previous_sign, previous_until = change["to_sign"], change["until"]
            self.assertLessEqual(len(item["changes_in_horizon"]), 4, "no huge timelines")

    def test_sign_boundaries_match_an_independent_ephemeris_primitive(self):
        """get_planet_position_on() is a separate code path from the ingress-boundary search."""
        for planet, item in self.by_planet.items():
            for change in item["changes_in_horizon"]:
                before = (datetime.date.fromisoformat(change["on"]) - datetime.timedelta(days=1)).isoformat()
                self.assertEqual(get_planet_position_on(f"{before} 23:59", planet)["rashi"], change["from_sign"], (planet, change["on"]))
                self.assertEqual(get_planet_position_on(f"{change['on']} 23:59", planet)["rashi"], change["to_sign"], (planet, change["on"]))
            current = item["current"]
            self.assertEqual(get_planet_position_on(f"{current['until']} 23:59", planet)["rashi"], current["sign"], (planet, "until"))

    def test_houses_follow_the_natal_lagna(self):
        other = {p["planet"]: p for p in evidence_module.build_promotion_transit_evidence("Aries")["planets"]}
        for planet in ("Jupiter", "Saturn", "Rahu"):
            self.assertEqual(other[planet]["current"]["sign"], self.by_planet[planet]["current"]["sign"])
            self.assertNotEqual(other[planet]["current"]["house_from_lagna"], self.by_planet[planet]["current"]["house_from_lagna"])
        self.assertEqual(other["Jupiter"]["current"]["house_from_lagna"], _house_from_lagna("Cancer", "Aries"))

    def test_sign_residence_and_motion_are_separate_facts(self):
        for planet, item in self.by_planet.items():
            self.assertIn("sign_residence", item)
            self.assertIn("motion_periods", item)
            for segment in item["sign_residence"]:
                self.assertEqual(set(segment), {"sign", "house_from_lagna", "from", "through", "continues_beyond_horizon"})
                self.assertNotIn("motion", segment, "a sign-stay segment carries no motion")
            for period in item["motion_periods"]:
                self.assertEqual(set(period), {"motion", "from", "through", "continues_beyond_horizon"})
                self.assertIn(period["motion"], ("Direct", "Retrograde"))
                self.assertNotIn("sign", period, "a motion period carries no sign")
        text = evidence_module.render_promotion_transit_summary(self.evidence, "en")
        self.assertEqual(text.count("Sign residence:"), 3)
        self.assertEqual(text.count("Motion:"), 3)
        for line in text.splitlines():
            if line.startswith("Sign residence:"):
                self.assertNotRegex(line, r"Direct|Retrograde", "the residence line never mentions motion")
            if line.startswith("Motion:"):
                self.assertNotRegex(line, r"Cancer|Leo|Pisces|Aries|Aquarius|Capricorn|house", "the motion line never mentions a sign or house")
        self.assertNotIn(", Retrograde, until", text)
        self.assertNotIn("now in", text)

    def test_residence_segments_are_derived_from_the_existing_sign_change_facts(self):
        for planet, item in self.by_planet.items():
            segments = item["sign_residence"]
            self.assertEqual(len(segments), 1 + len(item["changes_in_horizon"]))
            self.assertEqual((segments[0]["sign"], segments[0]["from"], segments[0]["through"]),
                             (item["current"]["sign"], None, item["current"]["until"]))
            for segment, change in zip(segments[1:], item["changes_in_horizon"]):
                self.assertEqual((segment["sign"], segment["from"], segment["through"]), (change["to_sign"], change["on"], change["until"]))

    def test_pinned_motion_periods_for_the_frozen_date(self):
        def simple(planet):
            return [(p["motion"], p["from"], p["through"], p["continues_beyond_horizon"]) for p in self.by_planet[planet]["motion_periods"]]
        self.assertEqual(simple("Saturn"), [
            ("Retrograde", None, "2026-12-11", False),
            ("Direct", "2026-12-12", "2027-08-09", False),
            ("Retrograde", "2027-08-10", "2027-09-21", True),
        ])
        self.assertEqual(simple("Jupiter"), [
            ("Direct", None, "2026-12-13", False),
            ("Retrograde", "2026-12-14", "2027-04-13", False),
            ("Direct", "2027-04-14", "2027-09-21", True),
        ])
        self.assertEqual(simple("Rahu"), [("Retrograde", None, "2027-09-21", True)])

    def test_motion_boundaries_match_the_existing_ephemeris_primitive(self):
        """transit_engine._planet_motion_on_day is a separate function from the one the periods are built with."""
        def motion_on(planet, iso_date):
            day = datetime.date.fromisoformat(iso_date)
            return transit_engine._planet_motion_on_day(planet, IST.localize(datetime.datetime.combine(day, datetime.time.min)))
        for planet, item in self.by_planet.items():
            periods = item["motion_periods"]
            for period in periods:
                self.assertEqual(motion_on(planet, period["through"]), period["motion"], (planet, "last day", period))
                if period["from"]:
                    self.assertEqual(motion_on(planet, period["from"]), period["motion"], (planet, "first day", period))
                    before = (datetime.date.fromisoformat(period["from"]) - datetime.timedelta(days=1)).isoformat()
                    self.assertNotEqual(motion_on(planet, before), period["motion"], (planet, "day before the change", period))
            for previous, following in zip(periods, periods[1:]):
                self.assertEqual(following["from"], (datetime.date.fromisoformat(previous["through"]) + datetime.timedelta(days=1)).isoformat())
                self.assertNotEqual(previous["motion"], following["motion"])
            self.assertEqual(periods[-1]["through"], self.evidence["horizon_end"])

    def test_motion_is_computed_not_hard_coded(self):
        with patch("transit_engine._ist_now", return_value=IST.localize(datetime.datetime(2027, 3, 1, 12, 0, 0))):
            later = {p["planet"]: p for p in evidence_module.build_promotion_transit_evidence("Libra")["planets"]}
        jupiter = later["Jupiter"]["motion_periods"]
        self.assertEqual((jupiter[0]["motion"], jupiter[0]["through"]), ("Retrograde", "2027-04-13"))
        self.assertEqual((jupiter[1]["motion"], jupiter[1]["from"]), ("Direct", "2027-04-14"))
        self.assertEqual([p["motion"] for p in later["Saturn"]["motion_periods"]][:2], ["Direct", "Retrograde"])

    def test_internal_evidence_keeps_iso_dates(self):
        for item in self.evidence["planets"]:
            for segment in item["sign_residence"]:
                for key in ("from", "through"):
                    if segment[key]:
                        self.assertRegex(segment[key], r"^\d{4}-\d{2}-\d{2}$")
            for period in item["motion_periods"]:
                for key in ("from", "through"):
                    if period[key]:
                        self.assertRegex(period[key], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(self.evidence["as_of"], r"^\d{4}-\d{2}-\d{2}$")

    def test_rendered_summary_is_concise_and_uses_the_customer_date_format(self):
        text = evidence_module.render_promotion_transit_summary(self.evidence, "en")
        self.assertLess(len(text), 1_500)
        self.assertIn("Sign residence: Cancer (10th house) through 30 October 2026; Leo (11th house) from 31 October 2026 through 24 January 2027; "
                      "Cancer (10th house) from 25 January 2027 through 25 June 2027; Leo (11th house) from 26 June 2027, continuing beyond this period.", text)
        self.assertIn("Motion: Direct through 13 December 2026; Retrograde from 14 December 2026 through 13 April 2027; "
                      "Direct again from 14 April 2027, continuing beyond this period.", text)
        self.assertIn("Sign residence: Pisces (6th house) through 2 June 2027; Aries (7th house) from 3 June 2027, continuing beyond this period.", text)
        self.assertIn("Motion: Retrograde through 11 December 2026; Direct from 12 December 2026 through 9 August 2027; "
                      "Retrograde again from 10 August 2027, continuing beyond this period.", text)
        self.assertIn("Sign residence: Aquarius (5th house) through 4 December 2026; Capricorn (4th house) from 5 December 2026, continuing beyond this period.", text)
        self.assertIn("Motion: Retrograde throughout this period.", text)
        self.assertIn("Ketu is always in the sign directly opposite Rahu.", text)
        self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", text), "no ISO date in the text Luna receives")
        for other in ("Sun\n", "Moon\n", "Mars\n", "Mercury\n", "Venus\n"):
            self.assertNotIn(other, text)


class PromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.en = report.build_promotion_report_prompt(cls.kundali, "en")
            cls.hi = report.build_promotion_report_prompt(cls.kundali, "hi")
            cls.blocks = build_summary_blocks_with_transit(cls.kundali, transit_engine.get_current_positions())

    def test_customer_question_is_simple_natural_and_bilingual(self):
        self.assertEqual(report.CUSTOMER_QUESTION["en"], "Is this a good time for my promotion?")
        self.assertEqual(report.CUSTOMER_QUESTION["hi"], "क्या यह समय मेरे प्रमोशन के लिए अच्छा है?")
        self.assertIn('"Is this a good time for my promotion?"', self.en.prompt)
        self.assertIn('"क्या यह समय मेरे प्रमोशन के लिए अच्छा है?"', self.hi.prompt)
        self.assertEqual(self.en.customer_question, report.CUSTOMER_QUESTION["en"])
        self.assertEqual(self.hi.customer_question, report.CUSTOMER_QUESTION["hi"])
        self.assertEqual(report.PRICE_RUPEES, 51)
        self.assertEqual(report.REPORT_KEY, "promotion_next_12_months")

    def test_uses_exactly_the_four_career_report_evidence_blocks_unchanged(self):
        self.assertEqual(report.CAREER_EVIDENCE_BLOCKS,
                         ("birth_chart_summary", "house_lord_summary", "career_yoga_summary", "dasha_window_summary"))
        career_template = (REPO / "prompts" / "career_report_en.txt").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r"\{([a-z_]+)\}", career_template)), sorted(report.CAREER_EVIDENCE_BLOCKS))
        for name in report.CAREER_EVIDENCE_BLOCKS:
            self.assertEqual(self.en.career_evidence[name], self.blocks[name], name)
            self.assertIn(normalize_customer_dates(self.blocks[name], "en"), self.en.prompt, name)
            self.assertIn(normalize_customer_dates(self.blocks[name], "hi"), self.hi.prompt, name)
        self.assertIn("Current window:", self.en.career_evidence["dasha_window_summary"])
        self.assertIn("You have a Libra Ascendant.", self.en.career_evidence["birth_chart_summary"])

    def test_transit_block_is_in_the_prompt_and_the_dates_come_from_the_backend(self):
        self.assertIn(self.en.transit_summary, self.en.prompt)
        self.assertIn(self.hi.transit_summary, self.hi.prompt)
        self.assertIn(f"is {self.en.report_period}", self.en.prompt)
        self.assertEqual(self.en.report_date, "2026-09-21")     # internal ISO is kept on the object
        self.assertEqual(self.en.horizon_end, "2027-09-21")
        self.assertEqual(self.en.report_period, "21 September 2026 to 21 September 2027")

    def test_evidence_payload_matches_the_prompt_data_section(self):
        for part in self.en.evidence_payload.split("\n\n"):
            self.assertIn(part, self.en.prompt)

    def test_no_heuristic_shadbala_and_no_unrelated_astrology(self):
        for built in (self.en, self.hi):
            lowered = built.prompt.lower()
            self.assertNotIn("shadbala", lowered)
            self.assertNotIn("shadbal", lowered)
            for term in ("pratyantar", "pratyantara", "navamsa", "navamsha", "ashtakavarga", "bindu", "vimshopak"):
                self.assertNotIn(term, lowered)
            self.assertIsNone(re.search(r"\bd-?(9|10)\b", lowered))
            for unrelated in ("manglik", "kaalsarp", "sadhesati", "sade sati", "gemstone", "aspect_summary", "wealth yog"):
                self.assertNotIn(unrelated, lowered)
        self.assertIn("shadbala", self.kundali["planets"][0])  # the heuristic field exists upstream; this prototype never reads it

    def test_prompt_carries_no_customer_pii(self):
        for built in (self.en, self.hi):
            for secret in (FIXTURE["name"], "Fixture", FIXTURE["dob"], FIXTURE["tob"], FIXTURE["pob"], "26.8467", "80.9462"):
                self.assertNotIn(secret, built.prompt)

    def test_placeholders_are_resolved_and_the_wire_format_is_the_existing_one(self):
        for built in (self.en, self.hi):
            self.assertIsNone(re.search(r"\{[a-z_]+\}", built.prompt), "unresolved placeholder")
            self.assertEqual(built.prompt.count("===META==="), 1)
            self.assertEqual(built.prompt.count("===REPORT==="), 1)
            self.assertIn('"label": "Promotion Outlook"', built.prompt)
            self.assertIn("valid JSON", built.prompt)

    def test_the_prompt_lets_luna_reason_but_forbids_inventing_facts(self):
        text = self.en.prompt
        self.assertIn("You MAY use Jyotish reasoning", text)
        self.assertIn("MUST NOT calculate, change or invent any planetary position, sign, house, transit date or Dasha date", text)
        self.assertIn("never an exact day", text)
        self.assertIn("never guaranteed", text)
        self.assertIn("do not force one", text)
        self.assertIn("include this section only if the astrology genuinely justifies it", text)
        hi = self.hi.prompt
        self.assertIn("Jyotish reasoning", hi)
        self.assertIn("नई रचना नहीं कर सकते", hi)
        self.assertGreater(len(re.findall(r"[ऀ-ॿ]", hi)), 1500, "the Hindi prompt is genuinely Hindi")
        self.assertIn("exactly as given", hi)

    def test_prompt_size_is_modest(self):
        # Ceilings raised modestly (9,000->10,200 / 11,000->12,000) for the shared master's own approved,
        # always-on additions: the timing-overlap (retrograde sub-period) sentence and the obstacle/dosha
        # guardrail paragraph, both in modules/focused_reports/prompts/master_{en,hi}.txt -- reused by every
        # prompt, including Promotion's, not something Promotion's own spec grew.
        self.assertLess(len(self.en.prompt), 10_200)
        self.assertLess(len(self.hi.prompt), 12_000)
        self.assertLess(len(self.en.transit_summary), 1_500)
        self.assertLess(len(self.en.evidence_payload), 3_500)

    def test_existing_structured_parser_accepts_a_response_in_the_promised_shape(self):
        synthetic = (
            "===META===\n"
            '{"answer_hero": {"label": "Promotion Outlook", "value": "Moderately Supportive, Stronger Later in the Year", '
            '"interpretation": "Jupiter in the 10th house frames the year.", "evidence": ["Jupiter is in Cancer (10th house) until 2026-10-30"]}, '
            '"action_items": ["Document your wins", "Talk to your manager"]}\n'
            "===REPORT===\n**Will You Get a Promotion?**\nThe outlook is supportive."
        )
        metadata, narrative = parse_structured_response(synthetic)
        hero = validate_required_hero_fields(metadata, ("label", "value", "interpretation", "evidence"))
        self.assertEqual(hero["label"], report.HERO_LABEL)
        self.assertTrue(narrative.startswith("**Will You Get a Promotion?**"))


class CustomerDateFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.en = report.build_promotion_report_prompt(cls.kundali, "en")
            cls.hi = report.build_promotion_report_prompt(cls.kundali, "hi")

    def test_english_customer_dates_are_day_month_name_year(self):
        self.assertEqual(self.en.report_period, "21 September 2026 to 21 September 2027")
        for date_text in ("31 October 2026", "24 January 2027", "3 June 2027", "9 August 2027", "1 July 2025", "28 November 2027"):
            self.assertIn(date_text, self.en.prompt)
        self.assertIsNone(re.search(r"(?<!\d)0\d (?:%s)" % "|".join(EN_MONTHS), self.en.prompt), "no leading zero on the day")

    def test_hindi_customer_dates_use_hindi_month_names(self):
        self.assertEqual(self.hi.report_period, "21 सितंबर 2026 से 21 सितंबर 2027")
        for date_text in ("31 अक्टूबर 2026", "24 जनवरी 2027", "3 जून 2027", "9 अगस्त 2027", "1 जुलाई 2025", "28 नवंबर 2027"):
            self.assertIn(date_text, self.hi.prompt)
        for english_month in EN_MONTHS:
            self.assertNotRegex(self.hi.transit_summary, r"\d{1,2} %s \d{4}" % english_month)
        for date_match in re.findall(r"\d{1,2} (?:%s) \d{4}" % "|".join(HI_MONTHS), self.hi.transit_summary):
            self.assertIsNone(re.match(r"0\d ", date_match))

    def test_ranges_use_to_in_english_and_se_in_hindi(self):
        self.assertIn("21 September 2026 to 30 October 2026", self.en.prompt)          # the format example Luna is given
        self.assertIn("21 सितंबर 2026 से 30 अक्टूबर 2026", self.hi.prompt)
        self.assertNotIn(" से ", self.en.report_period)
        self.assertNotIn(" to ", self.hi.report_period)

    def test_no_iso_date_and_no_iso_format_mention_anywhere_in_the_prompt(self):
        for built in (self.en, self.hi):
            self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", built.prompt), "ISO date leaked into the prompt")
            self.assertNotIn("YYYY", built.prompt)
            self.assertIsNone(re.search(r"\d{1,2}/\d{1,2}/\d{4}", built.prompt))
        self.assertIn("Never write a date in any other format", self.en.prompt)

    def test_internal_structures_stay_iso(self):
        self.assertRegex(self.en.report_date, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(self.en.career_evidence["dasha_window_summary"], r"from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}")
        self.assertNotRegex(self.en.prompt_evidence["dasha_window_summary"], r"\d{4}-\d{2}-\d{2}")

    def test_finalize_customer_output_removes_any_iso_date_luna_might_still_write(self):
        raw = (
            "===META===\n"
            '{"answer_hero": {"label": "Promotion Outlook", "value": "Moderately Supportive", '
            '"interpretation": "Jupiter is in the 10th house until 2026-10-30.", "evidence": ["Mercury Antardasha runs to 2027-11-28"]}, '
            '"action_items": ["Prepare before 2027-01-25"]}\n'
            "===REPORT===\n**Will You Get a Promotion?**\nFrom **2026-09-21 to 2026-10-30** the outlook is supportive; https://example.com/?d=2026-10-31 stays untouched."
        )
        english = report.finalize_customer_output(raw, "en")
        self.assertEqual(english["hero"]["interpretation"], "Jupiter is in the 10th house until 30 October 2026.")
        self.assertEqual(english["hero"]["evidence"], ["Mercury Antardasha runs to 28 November 2027"])
        self.assertEqual(english["action_items"], ["Prepare before 25 January 2027"])
        self.assertIn("From **21 September 2026 to 30 October 2026**", english["report"])
        self.assertIn("https://example.com/?d=2026-10-31", english["report"])          # existing normalizer never rewrites URLs
        hindi = report.finalize_customer_output(raw, "hi")
        self.assertEqual(hindi["hero"]["interpretation"], "Jupiter is in the 10th house until 30 अक्टूबर 2026.")
        self.assertIn("21 सितंबर 2026 to 30 अक्टूबर 2026", hindi["report"])
        for output in (english, hindi):
            visible = str(output["hero"]) + str(output["action_items"]) + output["report"].replace("https://example.com/?d=2026-10-31", "")
            self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", visible))


class FocusedLengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.en = report.build_promotion_report_prompt(cls.kundali, "en")
            cls.hi = report.build_promotion_report_prompt(cls.kundali, "hi")

    def test_english_prompt_asks_for_a_focused_400_to_500_word_report_without_padding(self):
        text = self.en.prompt
        self.assertIn("about 400 to 500 words in total", text)
        self.assertIn("Do not pad it to reach that length", text)
        self.assertIn("do not remove astrology that the answer needs", text)
        self.assertIn("Do not repeat the same interpretation in more than one section", text)

    def test_english_prompt_defines_the_concise_section_flow_in_order(self):
        text = self.en.prompt
        headings = ["**Direct Answer**", "**Why Your Chart Says This**", "**Strongest Periods**",
                    "**Slower or Watch Period**", "**What You Should Do**", "**Bottom Line**"]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("2 to 3 lines", text)
        self.assertIn("include this section only if the astrology genuinely justifies it", text)
        self.assertIn("2 to 3 concise practical actions", text)
        self.assertIn("1 to 2 lines that answer the original question again", text)
        for retired in ("**What Your Chart Shows**", "**Periods That Look Stronger**", "**In Short**"):
            self.assertNotIn(retired, text)

    def test_hindi_prompt_has_the_same_length_and_flow_contract(self):
        text = self.hi.prompt
        self.assertIn("400 से 500 शब्द", text)
        self.assertIn("बात न बढ़ाएँ", text)
        headings = ["**सीधा जवाब**", "**आपकी Chart ऐसा क्यों कहती है**", "**सबसे मजबूत समय**",
                    "**धीमा या ध्यान रखने वाला समय**", "**आपको क्या करना चाहिए**", "**सीधी बात**"]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))

    def test_the_meta_example_asks_for_two_evidence_items_not_three(self):
        self.assertIn('"evidence": ["<a real fact from the data above>", "<a second real fact>"]', self.en.prompt)
        self.assertNotIn("<a third if genuinely relevant>", self.en.prompt)

    def test_prompt_states_that_residence_and_motion_are_separate(self):
        self.assertIn('"Sign residence" is which sign and house the planet occupies and when it moves on', self.en.prompt)
        self.assertIn('"Motion" is whether it is Direct or Retrograde and when that changes', self.en.prompt)
        self.assertIn("never assume a planet is retrograde just because it stays in a sign", self.en.prompt)
        self.assertIn("Sign residence", self.hi.prompt)
        self.assertIn("Retrograde", self.hi.prompt)


class IsolationTests(unittest.TestCase):
    def test_no_luna_client_or_pipeline_is_imported_by_the_prototype(self):
        forbidden = ("report_ai_client", "openai", "import tasks", "from tasks", "razorpay", "pdf_generator", "email_utils",
                     "order_service", "payment_service", "report_generation_dispatcher", "report_delivery_service")
        for path in (REPO / "modules" / "focused_reports").glob("*.py"):
            imports = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                                if line.startswith(("import ", "from ")))
            for token in forbidden:
                # PDF rendering is now explicitly supported only by the
                # adapter. Evidence/prompt imports remain PDF-free.
                if path.name == "pdf_adapter.py" and token == "pdf_generator":
                    continue
                self.assertNotIn(token, imports, f"{path.name} imports {token}")
        probe = (
            "import sys; import modules.focused_reports.promotion_next_12_months; "
            "bad=[m for m in ('openai','tasks','razorpay','weasyprint','modules.payments.report_ai_client','modules.payments.order_service_run') if m in sys.modules]; "
            "print(','.join(bad)); sys.exit(1 if bad else 0)"
        )
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "RAZORPAY"))}
        result = subprocess.run([sys.executable, "-c", probe], cwd=str(REPO), capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, f"prototype pulled in: {result.stdout} {result.stderr[-300:]}")

    def test_production_report_pipeline_files_are_untouched(self):
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain", "--", "tasks.py", "summary_blocks.py", "transit_engine.py", "pdf_generator_weasy.py",
                 "app.py", "models.py", "modules/payments", "modules/love", "prompts", "config"],
                cwd=str(REPO), capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        self.assertEqual(status, "", f"production report files changed:\n{status}")

    def test_prototype_prompts_live_inside_the_package_not_in_the_paid_report_prompt_folder(self):
        self.assertFalse(list((REPO / "prompts").glob("promotion_*")))
        self.assertTrue((REPO / "modules" / "focused_reports" / "prompts" / "promotion_next_12_months_en.txt").is_file())
        self.assertTrue((REPO / "modules" / "focused_reports" / "prompts" / "promotion_next_12_months_hi.txt").is_file())


if __name__ == "__main__":
    unittest.main()
