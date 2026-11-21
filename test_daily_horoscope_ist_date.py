"""Regression: the daily horoscope date (heading, `date`, {DATE}) is the IST
calendar date, not the server's (UTC on Render). Between 00:00 and 05:30 IST
the UTC date is still yesterday; /api/daily-horoscope used datetime.now()
(server-local) and showed yesterday's date, while /api/daily-horoscope-summary
and the rotation already used Asia/Kolkata.

The clock is frozen at fixed instants and the server is simulated as UTC
(naive datetime.now() returns UTC), so the result does not depend on the
machine's own timezone. The rotation is stubbed: no database row is read or
written, and nothing leaves the process.

LOCAL ONLY: DATABASE_URL must point at the local `jyotishasha_local` database
(app import safety check); the test itself never queries it.

Run: python test_daily_horoscope_ist_date.py
"""
import os
import sys
import unittest
from datetime import datetime as _real_datetime, timezone
from unittest import mock
from urllib.parse import urlparse

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_u = urlparse(os.environ.get("DATABASE_URL", ""))
if _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/jyotishasha_local":
    raise SystemExit("REFUSING TO RUN: test_daily_horoscope_ist_date.py needs DATABASE_URL = the local jyotishasha_local database.")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")

from app import app  # noqa: E402
import routes.daily_horoscope as dh  # noqa: E402

_ITEM = {"intro": "Dear {SIGN}, on {DATE} the stars align.", "paragraph": "P {DATE}",
         "tips": "T {SIGN}", "lucky_color": "Ivory", "lucky_number": "4"}
ROTATION = ({s: dict(_ITEM) for s in dh.ZODIACS}, {s: dict(_ITEM) for s in dh.ZODIACS})


def frozen_utc_server(instant_utc):
    """A datetime stand-in for a server whose local clock is UTC."""
    class _Frozen(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instant_utc.replace(tzinfo=None)  # naive server-local = UTC
            return instant_utc.astimezone(tz)
    return _Frozen


def utc(*args):
    return _real_datetime(*args, tzinfo=timezone.utc)


# (UTC instant, IST meaning, expected EN date, expected HI date)
CASES = [
    (utc(2026, 11, 20, 18, 29), "23:59 IST 20 Nov", "20 November 2026", "20 नवंबर 2026"),
    (utc(2026, 11, 20, 18, 30), "00:00 IST 21 Nov (midnight)", "21 November 2026", "21 नवंबर 2026"),
    (utc(2026, 11, 20, 19, 0), "00:30 IST 21 Nov", "21 November 2026", "21 नवंबर 2026"),
    (utc(2026, 11, 20, 23, 59), "05:29 IST 21 Nov", "21 November 2026", "21 नवंबर 2026"),
    (utc(2026, 11, 21, 0, 0), "05:30 IST 21 Nov (UTC catches up)", "21 November 2026", "21 नवंबर 2026"),
    (utc(2026, 12, 31, 18, 45), "00:15 IST 1 Jan (year boundary)", "01 January 2027", "1 जनवरी 2027"),
]


class DailyHoroscopeIstDateTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.rotation = mock.patch.object(dh, "get_cached_rotation", return_value=ROTATION)
        self.rotation.start()

    def tearDown(self):
        self.rotation.stop()

    def get(self, instant, path):
        with mock.patch.object(dh, "datetime", frozen_utc_server(instant)):
            r = self.client.get(path)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        return r.get_json()

    def test_full_horoscope_en_uses_ist_date(self):
        for instant, label, en, _ in CASES:
            with self.subTest(label):
                body = self.get(instant, "/api/daily-horoscope?sign=aries&lang=en")
                self.assertEqual(body["date"], en)
                self.assertEqual(body["heading"], f"Today's Daily Horoscope for Aries – {en}")
                self.assertEqual(body["intro"], f"Dear Aries, on {en} the stars align.")
                self.assertEqual(body["paragraph"], f"P {en}")
                self.assertEqual((body["sign"], body["lang"]), ("aries", "en"))

    def test_full_horoscope_hi_uses_ist_date(self):
        for instant, label, _, hi in CASES:
            with self.subTest(label):
                body = self.get(instant, "/api/daily-horoscope?sign=leo&lang=hi")
                self.assertEqual(body["date"], hi)
                self.assertEqual(body["heading"], f"आज का राशिफल सिंह – {hi}")
                self.assertEqual(body["intro"], f"Dear सिंह, on {hi} the stars align.")
                self.assertEqual(body["tips"], "T सिंह")

    def test_summary_already_ist_and_agrees_with_full_horoscope(self):
        for instant, label, en, _ in CASES:
            for lang in ("en", "hi"):
                with self.subTest(label, lang=lang):
                    summary = self.get(instant, f"/api/daily-horoscope-summary?lang={lang}")
                    self.assertEqual(summary["date"], en)
                    self.assertEqual(set(summary["data"]), set(dh.ZODIACS))
                    full = self.get(instant, "/api/daily-horoscope?sign=aries&lang=en")
                    self.assertEqual(full["date"], summary["date"])

    def test_invalid_sign_still_400(self):
        r = self.client.get("/api/daily-horoscope?sign=pluto&lang=en")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
