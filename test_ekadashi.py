import json
import unittest
from datetime import date, datetime
from pathlib import Path

from flask import Flask

from routes.routes_ekadashi import ekadashi_bp
from services.ekadashi_engine import generate_year


DATA_DIR = Path(__file__).parent / "data" / "ekadashi"
LUCKNOW = (26.8467, 80.9462)
# Drik Panchang, Lucknow (geoname-id=1264733), primary Ekadashi dates.
EXPECTED_DATES = {
    2026: (
        "01-14 01-29 02-13 02-27 03-15 03-29 04-13 04-27 05-13 05-27 06-11 "
        "06-25 07-10 07-25 08-09 08-23 09-07 09-22 10-06 10-22 11-05 11-20 12-04 12-20"
    ),
    2027: (
        "01-03 01-18 02-02 02-17 03-04 03-18 04-02 04-17 05-02 05-16 06-01 "
        "06-14 06-30 07-14 07-29 08-12 08-28 09-11 09-26 10-11 10-25 11-10 11-24 12-09 12-23"
    ),
}
EXPECTED_ALTERNATES = {
    "2026-07-10": "2026-07-11",
    "2026-08-23": "2026-08-24",
    "2026-11-20": "2026-11-21",
    "2027-01-18": "2027-01-19",
    "2027-07-29": "2027-07-30",
    "2027-10-25": "2027-10-26",
}


class EkadashiCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendars = {year: generate_year(year, *LUCKNOW) for year in EXPECTED_DATES}
        cls.rows = {
            row["vrat_date"]: row
            for calendar in cls.calendars.values()
            for row in calendar["ekadashi_list"]
        }

    def test_complete_calendars_match_lucknow_reference(self):
        for year, dates in EXPECTED_DATES.items():
            with self.subTest(year=year):
                calendar = self.calendars[year]
                expected = [f"{year}-{day}" for day in dates.split()]
                self.assertEqual(calendar["count"], len(expected))
                self.assertEqual([r["vrat_date"] for r in calendar["ekadashi_list"]], expected)
                for path in DATA_DIR.glob(f"ekadashi_{year}*.json"):
                    # Full equality, including the corrected (Purnimanta) tithi.month labels.
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8")), calendar)

    def test_month_labels_are_purnimanta(self):
        # Shared Lunar Month Engine fix: tithi.month is the Purnimanta month (Drik), in the
        # engine output AND the shipped JSON (Utpanna = Margashirsha Krishna, Mokshada =
        # Margashirsha Shukla, Padmini/Parama = Adhik Jyeshtha, Nirjala = Nija Jyeshtha).
        expected = {"2026-12-04": "Margashirsha", "2026-12-20": "Margashirsha", "2026-05-27": "Jyeshtha",
                    "2026-06-11": "Jyeshtha", "2026-06-25": "Jyeshtha", "2027-01-03": "Pausha", "2027-12-23": "Pausha"}
        shipped = {}
        for year in EXPECTED_DATES:
            data = json.loads((DATA_DIR / f"ekadashi_{year}.json").read_text(encoding="utf-8"))
            shipped.update({r["vrat_date"]: r["tithi"]["month"] for r in data["ekadashi_list"]})
        for day, month in expected.items():
            self.assertEqual(self.rows[day]["tithi"]["month"], month)
            self.assertEqual(shipped[day], month)

    def test_alternates_and_adhik_observances(self):
        actual = {
            day: row["alternate_observances"][0]["vrat_date"]
            for day, row in self.rows.items()
            if row.get("alternate_observances")
        }
        self.assertEqual(actual, EXPECTED_ALTERNATES)
        for day, slug in (
            ("2026-05-27", "padmini-ekadashi"),
            ("2026-06-11", "parama-ekadashi"),
        ):
            self.assertEqual(self.rows[day]["slug"], slug)
            self.assertTrue(self.rows[day]["tithi"]["is_adhik"])

    def test_all_existing_detail_slugs_are_retained(self):
        expected = (
            "aja amalaki apara devshayani devutthana indira jaya kamada kamika mohini "
            "mokshada nirjala padmini papankusha papmochini parama parsva putrada-pausha "
            "putrada-shravana rama saphala shattila utpanna varuthini vijaya yogini"
        )
        self.assertEqual(
            {row["slug"].removesuffix("-ekadashi") for row in self.rows.values()},
            set(expected.split()),
        )

    def test_lucknow_parana_reference_windows(self):
        cases = (
            ("2026-12-04", False, "2026-12-05", "06:41", "08:47", "pratahkal"),
            ("2026-07-10", False, "2026-07-11", "13:34", "16:19", "aparahna"),
            ("2027-05-02", False, "2027-05-03", "05:27", "08:06", "pratahkal"),
            ("2027-06-14", False, "2027-06-15", "13:30", "16:16", "aparahna"),
            ("2027-07-29", False, "2027-07-30", "13:33", "16:14", "aparahna"),
            ("2027-07-29", True, "2027-07-31", "05:30", "08:11", "after_dwadashi"),
        )
        for day, alternate, parana_day, start, end, rule in cases:
            with self.subTest(day=day, alternate=alternate):
                row = self.rows[day]
                parana = (row["alternate_observances"][0] if alternate else row)["parana"]
                self.assertEqual(parana["parana_date"], parana_day)
                self.assertEqual(parana["rule"], rule)
                for key, expected in (("start", start), ("end", end)):
                    delta = datetime.fromisoformat(parana[key]) - datetime.fromisoformat(
                        f"{parana_day} {expected}"
                    )
                    self.assertLessEqual(abs(delta.total_seconds()), 120)
        utpanna = self.rows["2026-12-04"]["parana"]
        self.assertEqual(utpanna["dwadashi_end"], "2026-12-06 00:52")

    def test_all_parana_windows_are_ordered_and_respect_dwadashi(self):
        for row in self.rows.values():
            for occurrence in [row, *row.get("alternate_observances", [])]:
                with self.subTest(day=occurrence["vrat_date"]):
                    p = occurrence["parana"]
                    self.assertLess(p["start"], p["end"])
                    self.assertLessEqual(p["hari_vasara_end"], p["start"])
                    self.assertEqual(date.fromisoformat(p["parana_date"]).toordinal(),
                                     date.fromisoformat(occurrence["vrat_date"]).toordinal() + 1)
                    if p["rule"] == "after_dwadashi":
                        self.assertLessEqual(p["dwadashi_end"], p["start"])
                    else:
                        self.assertLessEqual(p["end"], p["dwadashi_end"])


class EkadashiApiTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(ekadashi_bp)
        self.client = app.test_client()

    def test_existing_list_and_detail_consumer_contracts(self):
        for year, count in ((2026, 24), (2027, 25)):
            for lang in ("en", "hi"):
                response = self.client.get(f"/api/ekadashi/all?year={year}&lang={lang}")
                self.assertEqual(response.status_code, 200)
                body = response.get_json()
                self.assertEqual(set(body), {"status", "year", "count", "data"})
                self.assertEqual(body["count"], count)
                for slug in {row["slug"].removesuffix("-ekadashi") for row in body["data"]}:
                    response = self.client.get(
                        f"/api/ekadashi/find-by-slug/{slug}-ekadashi?year={year}&lang={lang}"
                    )
                    self.assertEqual(response.status_code, 200)
                    detail = response.get_json()
                    self.assertEqual(set(detail), {"status", "year", "data"})
                    self.assertEqual(detail["data"]["slug"].removesuffix("-ekadashi"), slug)
                    self.assertIsInstance(detail["data"]["parana"]["start"], str)
                    self.assertIsInstance(detail["data"]["parana"]["end"], str)

    def test_exact_date_and_multiple_occurrences(self):
        url = "/api/ekadashi/find-by-slug/saphala"
        legacy = self.client.get(f"{url}?year=2027").get_json()
        self.assertEqual(legacy["data"]["vrat_date"], "2027-01-03")
        response = self.client.get(f"{url}?date=2027-12-23&include_occurrences=true")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["data"]["parana"]["parana_date"], "2027-12-24")
        self.assertEqual(
            [r["vrat_date"] for r in body["occurrences"]], ["2027-01-03", "2027-12-23"]
        )

    def test_exact_alternate_date(self):
        response = self.client.get(
            "/api/ekadashi/find-by-slug/kamika-ekadashi?year=2027&date=2027-07-30"
        )
        self.assertEqual(response.status_code, 200)
        row = response.get_json()["data"]
        self.assertEqual(row["vrat_date"], "2027-07-30")
        self.assertEqual(row["tradition"], "Gauna/Vaishnava")
        self.assertEqual(row["parana"]["rule"], "after_dwadashi")

    def test_invalid_and_missing_dates(self):
        url = "/api/ekadashi/find-by-slug/saphala"
        for query, status in (
            ("year=2026&date=2027-12-23", 400),
            ("date=20271223", 400),
            ("date=2027-02-29", 400),
            ("date=2027-12-22", 404),
            ("year=2029", 404),
        ):
            self.assertEqual(self.client.get(f"{url}?{query}").status_code, status)


if __name__ == "__main__":
    unittest.main()
