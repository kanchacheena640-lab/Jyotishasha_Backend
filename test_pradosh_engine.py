"""Pradosh engine + /api/events/pradosh tests (standalone check() convention).

No database, network, FCM or production access: the API is exercised through a
minimal Flask app that registers only the events blueprint.

Run:  python test_pradosh_engine.py

REFERENCE DATA BELOW IS TEST DATA ONLY (never read by the engine): every Pradosh
Vrat listed by Drik Panchang for New Delhi (28°38'08"N 77°13'28"E,
Asia/Kolkata) for 2025-2030, read 2026-11-27 from
drikpanchang.com/vrats/pradoshdates.html?year=YYYY. Drik prints minutes only.
Matching Drik shows the convention is implemented as intended; it does not by
itself establish scriptural correctness (see services/pradosh_engine.py).
"""

import copy
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from services import pradosh_engine as p  # noqa: E402
import routes.routes_events as routes_module  # noqa: E402
from routes.routes_events import routes_events  # noqa: E402

DELHI_DRIK = (28.6356, 77.2244)      # Drik's New Delhi
LUCKNOW = (26.8467, 80.9462)         # location used by the notification scheduler
passed = failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


# date | name | month, paksha | puja start | puja end | Trayodashi begins | Trayodashi ends
DRIK_ROWS = """
2025-01-11 | Shani Pradosh Vrat | Pausha, Shukla | 05:43 PM | 08:26 PM | 08:21 AM, Jan 11 | 06:33 AM, Jan 12
2025-01-27 | Soma Pradosh Vrat | Magha, Krishna | 05:56 PM | 08:34 PM | 08:54 PM, Jan 26 | 08:34 PM, Jan 27
2025-02-09 | Ravi Pradosh Vrat | Magha, Shukla | 07:25 PM | 08:42 PM | 07:25 PM, Feb 09 | 06:57 PM, Feb 10
2025-02-25 | Bhauma Pradosh Vrat | Phalguna, Krishna | 06:18 PM | 08:49 PM | 12:47 PM, Feb 25 | 11:08 AM, Feb 26
2025-03-11 | Bhauma Pradosh Vrat | Phalguna, Shukla | 06:27 PM | 08:53 PM | 08:13 AM, Mar 11 | 09:11 AM, Mar 12
2025-03-27 | Guru Pradosh Vrat | Chaitra, Krishna | 06:36 PM | 08:56 PM | 01:42 AM, Mar 27 | 11:03 PM, Mar 27
2025-04-10 | Guru Pradosh Vrat | Chaitra, Shukla | 06:44 PM | 08:59 PM | 10:55 PM, Apr 09 | 01:00 AM, Apr 11
2025-04-25 | Shukra Pradosh Vrat | Vaishakha, Krishna | 06:53 PM | 09:03 PM | 11:44 AM, Apr 25 | 08:27 AM, Apr 26
2025-05-09 | Shukra Pradosh Vrat | Vaishakha, Shukla | 07:01 PM | 09:08 PM | 02:56 PM, May 09 | 05:29 PM, May 10
2025-05-24 | Shani Pradosh Vrat | Jyeshtha, Krishna | 07:20 PM | 09:13 PM | 07:20 PM, May 24 | 03:51 PM, May 25
2025-06-08 | Ravi Pradosh Vrat | Jyeshtha, Shukla | 07:18 PM | 09:19 PM | 07:17 AM, Jun 08 | 09:35 AM, Jun 09
2025-06-23 | Soma Pradosh Vrat | Ashadha, Krishna | 07:22 PM | 09:23 PM | 01:21 AM, Jun 23 | 10:09 PM, Jun 23
2025-07-08 | Bhauma Pradosh Vrat | Ashadha, Shukla | 07:23 PM | 09:24 PM | 11:10 PM, Jul 07 | 12:38 AM, Jul 09
2025-07-22 | Bhauma Pradosh Vrat | Shravana, Krishna | 07:18 PM | 09:22 PM | 07:05 AM, Jul 22 | 04:39 AM, Jul 23
2025-08-06 | Budha Pradosh Vrat | Shravana, Shukla | 07:08 PM | 09:16 PM | 02:08 PM, Aug 06 | 02:27 PM, Aug 07
2025-08-20 | Budha Pradosh Vrat | Bhadrapada, Krishna | 06:56 PM | 09:07 PM | 01:58 PM, Aug 20 | 12:44 PM, Aug 21
2025-09-05 | Shukra Pradosh Vrat | Bhadrapada, Shukla | 06:38 PM | 08:55 PM | 04:08 AM, Sep 05 | 03:12 AM, Sep 06
2025-09-19 | Shukra Pradosh Vrat | Ashwina, Krishna | 06:21 PM | 08:43 PM | 11:24 PM, Sep 18 | 11:36 PM, Sep 19
2025-10-04 | Shani Pradosh Vrat | Ashwina, Shukla | 06:03 PM | 08:30 PM | 05:09 PM, Oct 04 | 03:03 PM, Oct 05
2025-10-18 | Shani Pradosh Vrat | Kartika, Krishna | 05:48 PM | 08:20 PM | 12:18 PM, Oct 18 | 01:51 PM, Oct 19
2025-11-03 | Soma Pradosh Vrat | Kartika, Shukla | 05:34 PM | 08:11 PM | 05:07 AM, Nov 03 | 02:05 AM, Nov 04
2025-11-17 | Soma Pradosh Vrat | Margashirsha, Krishna | 05:27 PM | 08:07 PM | 04:47 AM, Nov 17 | 07:12 AM, Nov 18
2025-12-02 | Bhauma Pradosh Vrat | Margashirsha, Shukla | 05:24 PM | 08:07 PM | 03:57 PM, Dec 02 | 12:25 PM, Dec 03
2025-12-17 | Budha Pradosh Vrat | Pausha, Krishna | 05:27 PM | 08:11 PM | 11:57 PM, Dec 16 | 02:32 AM, Dec 18
2026-01-01 | Guru Pradosh Vrat | Pausha, Shukla | 05:35 PM | 08:19 PM | 01:47 AM, Jan 01 | 10:22 PM, Jan 01
2026-01-16 | Shukra Pradosh Vrat | Magha, Krishna | 05:47 PM | 08:29 PM | 08:16 PM, Jan 15 | 10:21 PM, Jan 16
2026-01-30 | Shukra Pradosh Vrat | Magha, Shukla | 05:59 PM | 08:37 PM | 11:09 AM, Jan 30 | 08:25 AM, Jan 31
2026-02-14 | Shani Pradosh Vrat | Phalguna, Krishna | 06:10 PM | 08:44 PM | 04:01 PM, Feb 14 | 05:04 PM, Feb 15
2026-03-01 | Ravi Pradosh Vrat | Phalguna, Shukla | 06:21 PM | 07:09 PM | 08:43 PM, Feb 28 | 07:09 PM, Mar 01
2026-03-16 | Soma Pradosh Vrat | Chaitra, Krishna | 06:30 PM | 08:54 PM | 09:40 AM, Mar 16 | 09:23 AM, Mar 17
2026-03-30 | Soma Pradosh Vrat | Chaitra, Shukla | 06:38 PM | 08:57 PM | 07:09 AM, Mar 30 | 06:55 AM, Mar 31
2026-04-15 | Budha Pradosh Vrat | Vaishakha, Krishna | 06:47 PM | 09:00 PM | 12:12 AM, Apr 15 | 10:31 PM, Apr 15
2026-04-28 | Bhauma Pradosh Vrat | Vaishakha, Shukla | 06:54 PM | 09:04 PM | 06:51 PM, Apr 28 | 07:51 PM, Apr 29
2026-05-14 | Guru Pradosh Vrat | Jyeshtha, Krishna | 07:04 PM | 09:09 PM | 11:20 AM, May 14 | 08:31 AM, May 15
2026-05-28 | Guru Pradosh Vrat | Jyeshtha, Shukla | 07:12 PM | 09:15 PM | 07:56 AM, May 28 | 09:50 AM, May 29
2026-06-12 | Shukra Pradosh Vrat | Jyeshtha, Krishna | 07:36 PM | 09:20 PM | 07:36 PM, Jun 12 | 04:07 PM, Jun 13
2026-06-27 | Shani Pradosh Vrat | Jyeshtha, Shukla | 07:23 PM | 09:23 PM | 10:22 PM, Jun 26 | 12:43 AM, Jun 28
2026-07-12 | Ravi Pradosh Vrat | Ashadha, Krishna | 07:22 PM | 09:24 PM | 02:04 AM, Jul 12 | 10:29 PM, Jul 12
2026-07-26 | Ravi Pradosh Vrat | Ashadha, Shukla | 07:16 PM | 09:21 PM | 01:57 PM, Jul 26 | 04:14 PM, Jul 27
2026-08-10 | Soma Pradosh Vrat | Shravana, Krishna | 07:05 PM | 09:14 PM | 08:00 AM, Aug 10 | 04:54 AM, Aug 11
2026-08-25 | Bhauma Pradosh Vrat | Shravana, Shukla | 06:51 PM | 09:04 PM | 06:20 AM, Aug 25 | 07:59 AM, Aug 26
2026-09-08 | Bhauma Pradosh Vrat | Bhadrapada, Krishna | 06:35 PM | 08:52 PM | 02:42 PM, Sep 08 | 12:30 PM, Sep 09
2026-09-24 | Guru Pradosh Vrat | Bhadrapada, Shukla | 06:16 PM | 08:39 PM | 10:50 PM, Sep 23 | 11:18 PM, Sep 24
2026-10-08 | Guru Pradosh Vrat | Ashwina, Krishna | 05:59 PM | 08:27 PM | 11:16 PM, Oct 07 | 10:15 PM, Oct 08
2026-10-23 | Shukra Pradosh Vrat | Ashwina, Shukla | 05:44 PM | 08:16 PM | 02:35 PM, Oct 23 | 01:36 PM, Oct 24
2026-11-06 | Shukra Pradosh Vrat | Kartika, Krishna | 05:33 PM | 08:09 PM | 10:30 AM, Nov 06 | 10:47 AM, Nov 07
2026-11-22 | Ravi Pradosh Vrat | Kartika, Shukla | 05:25 PM | 08:06 PM | 04:56 AM, Nov 22 | 02:36 AM, Nov 23
2026-12-06 | Ravi Pradosh Vrat | Margashirsha, Krishna | 05:24 PM | 08:07 PM | 12:51 AM, Dec 06 | 02:22 AM, Dec 07
2026-12-21 | Soma Pradosh Vrat | Margashirsha, Shukla | 05:36 PM | 08:13 PM | 05:36 PM, Dec 21 | 02:23 PM, Dec 22
2027-01-05 | Bhauma Pradosh Vrat | Pausha, Krishna | 05:38 PM | 08:21 PM | 06:15 PM, Jan 04 | 08:39 PM, Jan 05
2027-01-20 | Budha Pradosh Vrat | Pausha, Shukla | 05:50 PM | 08:31 PM | 04:41 AM, Jan 20 | 01:11 AM, Jan 21
2027-02-03 | Budha Pradosh Vrat | Magha, Krishna | 06:02 PM | 08:39 PM | 01:50 PM, Feb 03 | 04:31 PM, Feb 04
2027-02-18 | Guru Pradosh Vrat | Magha, Shukla | 06:13 PM | 08:46 PM | 02:27 PM, Feb 18 | 11:14 AM, Feb 19
2027-03-05 | Shukra Pradosh Vrat | Phalguna, Krishna | 06:23 PM | 08:51 PM | 09:53 AM, Mar 05 | 12:03 PM, Mar 06
2027-03-20 | Shani Pradosh Vrat | Phalguna, Shukla | 06:32 PM | 08:45 PM | 11:17 PM, Mar 19 | 08:45 PM, Mar 20
2027-04-04 | Ravi Pradosh Vrat | Chaitra, Krishna | 06:40 PM | 08:58 PM | 04:26 AM, Apr 04 | 05:23 AM, Apr 05
2027-04-18 | Ravi Pradosh Vrat | Chaitra, Shukla | 06:48 PM | 09:01 PM | 07:42 AM, Apr 18 | 06:08 AM, Apr 19
2027-05-03 | Soma Pradosh Vrat | Vaishakha, Krishna | 08:03 PM | 09:06 PM | 08:03 PM, May 03 | 07:30 PM, May 04
2027-05-17 | Soma Pradosh Vrat | Vaishakha, Shukla | 07:06 PM | 09:10 PM | 04:28 PM, May 17 | 04:03 PM, May 18
2027-06-02 | Budha Pradosh Vrat | Jyeshtha, Krishna | 07:15 PM | 09:17 PM | 08:28 AM, Jun 02 | 06:34 AM, Jun 03
2027-06-16 | Budha Pradosh Vrat | Jyeshtha, Shukla | 07:21 PM | 09:21 PM | 02:30 AM, Jun 16 | 03:20 AM, Jun 17
2027-07-01 | Guru Pradosh Vrat | Ashadha, Krishna | 07:23 PM | 09:24 PM | 06:14 PM, Jul 01 | 03:23 PM, Jul 02
2027-07-15 | Guru Pradosh Vrat | Ashadha, Shukla | 07:21 PM | 09:23 PM | 02:40 PM, Jul 15 | 04:34 PM, Jul 16
2027-07-31 | Shani Pradosh Vrat | Shravana, Krishna | 07:13 PM | 09:19 PM | 02:18 AM, Jul 31 | 10:57 PM, Jul 31
2027-08-14 | Shani Pradosh Vrat | Shravana, Shukla | 07:02 PM | 09:11 PM | 05:21 AM, Aug 14 | 07:53 AM, Aug 15
2027-08-29 | Ravi Pradosh Vrat | Bhadrapada, Krishna | 06:46 PM | 09:01 PM | 09:35 AM, Aug 29 | 06:12 AM, Aug 30
2027-09-13 | Soma Pradosh Vrat | Bhadrapada, Shukla | 06:29 PM | 08:48 PM | 10:12 PM, Sep 12 | 12:39 AM, Sep 14
2027-09-27 | Soma Pradosh Vrat | Ashwina, Krishna | 06:12 PM | 08:36 PM | 04:55 PM, Sep 27 | 01:54 PM, Sep 28
2027-10-12 | Bhauma Pradosh Vrat | Ashwina, Shukla | 05:55 PM | 08:24 PM | 04:13 PM, Oct 12 | 05:48 PM, Oct 13
2027-10-27 | Budha Pradosh Vrat | Kartika, Krishna | 05:40 PM | 08:14 PM | 01:03 AM, Oct 27 | 10:49 PM, Oct 27
2027-11-11 | Guru Pradosh Vrat | Kartika, Shukla | 05:30 PM | 08:08 PM | 10:07 AM, Nov 11 | 10:20 AM, Nov 12
2027-11-25 | Guru Pradosh Vrat | Margashirsha, Krishna | 05:24 PM | 08:06 PM | 10:50 AM, Nov 25 | 09:47 AM, Nov 26
2027-12-11 | Shani Pradosh Vrat | Margashirsha, Shukla | 05:25 PM | 08:09 PM | 02:53 AM, Dec 11 | 01:42 AM, Dec 12
2027-12-25 | Shani Pradosh Vrat | Pausha, Krishna | 05:31 PM | 08:15 PM | 11:08 PM, Dec 24 | 11:31 PM, Dec 25
2028-01-09 | Ravi Pradosh Vrat | Pausha, Shukla | 05:55 PM | 08:24 PM | 05:55 PM, Jan 09 | 03:36 PM, Jan 10
2028-01-23 | Ravi Pradosh Vrat | Magha, Krishna | 05:52 PM | 08:33 PM | 02:22 PM, Jan 23 | 04:08 PM, Jan 24
2028-02-08 | Bhauma Pradosh Vrat | Magha, Shukla | 06:05 PM | 08:41 PM | 06:51 AM, Feb 08 | 03:46 AM, Feb 09
2028-02-22 | Bhauma Pradosh Vrat | Phalguna, Krishna | 06:16 PM | 08:47 PM | 08:07 AM, Feb 22 | 10:44 AM, Feb 23
2028-03-08 | Budha Pradosh Vrat | Phalguna, Shukla | 06:25 PM | 08:52 PM | 05:27 PM, Mar 08 | 02:01 PM, Mar 09
2028-03-23 | Guru Pradosh Vrat | Chaitra, Krishna | 06:34 PM | 08:55 PM | 02:56 AM, Mar 23 | 05:33 AM, Mar 24
2028-04-07 | Shukra Pradosh Vrat | Chaitra, Shukla | 06:43 PM | 08:59 PM | 01:51 AM, Apr 07 | 10:32 PM, Apr 07
2028-04-22 | Shani Pradosh Vrat | Vaishakha, Krishna | 06:51 PM | 09:02 PM | 09:03 PM, Apr 21 | 10:56 PM, Apr 22
2028-05-06 | Shani Pradosh Vrat | Vaishakha, Shukla | 07:00 PM | 09:07 PM | 08:48 AM, May 06 | 06:05 AM, May 07
2028-05-21 | Ravi Pradosh Vrat | Jyeshtha, Krishna | 07:09 PM | 09:12 PM | 01:19 PM, May 21 | 02:01 PM, May 22
2028-06-04 | Ravi Pradosh Vrat | Jyeshtha, Shukla | 07:16 PM | 09:18 PM | 03:29 PM, Jun 04 | 01:48 PM, Jun 05
2028-06-20 | Bhauma Pradosh Vrat | Ashadha, Krishna | 07:22 PM | 09:22 PM | 03:21 AM, Jun 20 | 02:47 AM, Jun 21
2028-07-04 | Bhauma Pradosh Vrat | Ashadha, Shukla | 07:23 PM | 09:24 PM | 11:17 PM, Jul 03 | 10:56 PM, Jul 04
2028-07-19 | Budha Pradosh Vrat | Shravana, Krishna | 07:19 PM | 09:23 PM | 03:21 PM, Jul 19 | 01:37 PM, Jul 20
2028-08-02 | Budha Pradosh Vrat | Shravana, Shukla | 07:11 PM | 09:18 PM | 09:24 AM, Aug 02 | 10:25 AM, Aug 03
2028-08-18 | Shukra Pradosh Vrat | Bhadrapada, Krishna | 06:57 PM | 09:08 PM | 01:43 AM, Aug 18 | 10:59 PM, Aug 18
2028-09-01 | Shukra Pradosh Vrat | Bhadrapada, Shukla | 06:42 PM | 08:58 PM | 10:30 PM, Aug 31 | 12:34 AM, Sep 02
2028-09-16 | Shani Pradosh Vrat | Ashwina, Krishna | 06:25 PM | 08:45 PM | 10:51 AM, Sep 16 | 07:29 AM, Sep 17
2028-09-30 | Shani Pradosh Vrat | Ashwina, Shukla | 06:08 PM | 08:33 PM | 02:33 PM, Sep 30 | 05:04 PM, Oct 01
2028-10-15 | Ravi Pradosh Vrat | Kartika, Krishna | 07:16 PM | 08:21 PM | 07:16 PM, Oct 15 | 03:45 PM, Oct 16
2028-10-30 | Soma Pradosh Vrat | Kartika, Shukla | 05:37 PM | 08:12 PM | 08:50 AM, Oct 30 | 11:08 AM, Oct 31
2028-11-14 | Bhauma Pradosh Vrat | Margashirsha, Krishna | 05:28 PM | 08:07 PM | 03:40 AM, Nov 14 | 12:35 AM, Nov 15
2028-11-29 | Budha Pradosh Vrat | Margashirsha, Shukla | 05:24 PM | 08:06 PM | 04:13 AM, Nov 29 | 05:42 AM, Nov 30
2028-12-13 | Budha Pradosh Vrat | Pausha, Krishna | 05:26 PM | 08:10 PM | 12:55 PM, Dec 13 | 10:49 AM, Dec 14
2028-12-29 | Shukra Pradosh Vrat | Pausha, Shukla | 05:34 PM | 08:18 PM | 11:21 PM, Dec 28 | 11:36 PM, Dec 29
2029-01-12 | Shukra Pradosh Vrat | Magha, Krishna | 05:44 PM | 08:26 PM | 11:50 PM, Jan 11 | 11:06 PM, Jan 12
2029-01-27 | Shani Pradosh Vrat | Magha, Shukla | 05:56 PM | 08:35 PM | 04:49 PM, Jan 27 | 03:40 PM, Jan 28
2029-02-10 | Shani Pradosh Vrat | Phalguna, Krishna | 06:08 PM | 08:43 PM | 12:48 PM, Feb 10 | 01:29 PM, Feb 11
2029-02-26 | Soma Pradosh Vrat | Phalguna, Shukla | 06:19 PM | 08:49 PM | 07:29 AM, Feb 26 | 05:04 AM, Feb 27
2029-03-12 | Soma Pradosh Vrat | Chaitra, Krishna | 06:28 PM | 08:53 PM | 03:42 AM, Mar 12 | 05:29 AM, Mar 13
2029-03-27 | Bhauma Pradosh Vrat | Chaitra, Shukla | 06:52 PM | 08:56 PM | 06:52 PM, Mar 27 | 03:34 PM, Mar 28
2029-04-11 | Budha Pradosh Vrat | Chaitra, Krishna | 06:45 PM | 08:59 PM | 07:51 PM, Apr 10 | 10:14 PM, Apr 11
2029-04-26 | Guru Pradosh Vrat | Chaitra, Shukla | 06:53 PM | 09:03 PM | 03:21 AM, Apr 26 | 11:43 PM, Apr 26
2029-05-10 | Guru Pradosh Vrat | Vaishakha, Krishna | 07:02 PM | 09:08 PM | 12:29 PM, May 10 | 02:54 PM, May 11
2029-05-25 | Shukra Pradosh Vrat | Vaishakha, Shukla | 07:11 PM | 09:14 PM | 09:55 AM, May 25 | 06:34 AM, May 26
2029-06-09 | Shani Pradosh Vrat | Jyeshtha, Krishna | 07:18 PM | 09:19 PM | 04:54 AM, Jun 09 | 06:47 AM, Jun 10
2029-06-23 | Shani Pradosh Vrat | Jyeshtha, Shukla | 07:22 PM | 09:23 PM | 03:52 PM, Jun 23 | 01:17 PM, Jun 24
2029-07-09 | Soma Pradosh Vrat | Ashadha, Krishna | 07:22 PM | 09:22 PM | 08:30 PM, Jul 08 | 09:22 PM, Jul 09
2029-07-23 | Soma Pradosh Vrat | Ashadha, Shukla | 07:17 PM | 08:59 PM | 10:28 PM, Jul 22 | 08:59 PM, Jul 23
2029-08-07 | Bhauma Pradosh Vrat | Shravana, Krishna | 07:07 PM | 09:15 PM | 10:48 AM, Aug 07 | 10:19 AM, Aug 08
2029-08-21 | Bhauma Pradosh Vrat | Shravana, Shukla | 06:54 PM | 09:06 PM | 06:53 AM, Aug 21 | 06:38 AM, Aug 22
2029-09-06 | Guru Pradosh Vrat | Bhadrapada, Krishna | 06:37 PM | 08:54 PM | 11:30 PM, Sep 05 | 09:40 PM, Sep 06
2029-09-19 | Budha Pradosh Vrat | Bhadrapada, Shukla | 06:21 PM | 08:43 PM | 05:58 PM, Sep 19 | 06:57 PM, Sep 20
2029-10-05 | Shukra Pradosh Vrat | Ashwina, Krishna | 06:02 PM | 08:29 PM | 10:45 AM, Oct 05 | 07:50 AM, Oct 06
2029-10-19 | Shukra Pradosh Vrat | Ashwina, Shukla | 05:47 PM | 08:19 PM | 08:18 AM, Oct 19 | 10:17 AM, Oct 20
2029-11-04 | Ravi Pradosh Vrat | Kartika, Krishna | 05:34 PM | 08:10 PM | 08:57 PM, Nov 03 | 05:29 PM, Nov 04
2029-11-18 | Ravi Pradosh Vrat | Kartika, Shukla | 05:26 PM | 08:06 PM | 01:53 AM, Nov 18 | 04:27 AM, Nov 19
2029-12-03 | Soma Pradosh Vrat | Margashirsha, Krishna | 05:24 PM | 08:07 PM | 06:40 AM, Dec 03 | 03:16 AM, Dec 04
2029-12-18 | Bhauma Pradosh Vrat | Margashirsha, Shukla | 05:28 PM | 08:12 PM | 09:54 PM, Dec 17 | 12:21 AM, Dec 19
2030-01-01 | Bhauma Pradosh Vrat | Pausha, Krishna | 05:35 PM | 08:19 PM | 04:23 PM, Jan 01 | 01:34 PM, Jan 02
2030-01-17 | Guru Pradosh Vrat | Pausha, Shukla | 05:48 PM | 08:05 PM | 06:33 PM, Jan 16 | 08:05 PM, Jan 17
2030-01-31 | Guru Pradosh Vrat | Magha, Krishna | 05:59 PM | 08:37 PM | 02:26 AM, Jan 31 | 12:34 AM, Feb 01
2030-02-15 | Shukra Pradosh Vrat | Magha, Shukla | 06:11 PM | 08:45 PM | 01:38 PM, Feb 15 | 01:42 PM, Feb 16
2030-03-01 | Shukra Pradosh Vrat | Phalguna, Krishna | 06:21 PM | 08:50 PM | 01:04 PM, Mar 01 | 12:22 PM, Mar 02
2030-03-17 | Ravi Pradosh Vrat | Phalguna, Shukla | 06:31 PM | 08:54 PM | 05:36 AM, Mar 17 | 04:08 AM, Mar 18
2030-03-31 | Ravi Pradosh Vrat | Chaitra, Krishna | 06:38 PM | 08:57 PM | 12:42 AM, Mar 31 | 01:14 AM, Apr 01
2030-04-15 | Soma Pradosh Vrat | Chaitra, Shukla | 06:47 PM | 09:00 PM | 06:03 PM, Apr 15 | 03:25 PM, Apr 16
2030-04-29 | Soma Pradosh Vrat | Vaishakha, Krishna | 06:55 PM | 09:04 PM | 01:42 PM, Apr 29 | 03:22 PM, Apr 30
2030-05-15 | Budha Pradosh Vrat | Vaishakha, Shukla | 07:05 PM | 09:10 PM | 03:32 AM, May 15 | 12:14 AM, May 16
2030-05-29 | Budha Pradosh Vrat | Jyeshtha, Krishna | 07:13 PM | 09:15 PM | 04:14 AM, May 29 | 06:40 AM, May 30
2030-06-13 | Guru Pradosh Vrat | Jyeshtha, Shukla | 07:20 PM | 09:20 PM | 10:55 AM, Jun 13 | 07:27 AM, Jun 14
2030-06-28 | Shukra Pradosh Vrat | Ashadha, Krishna | 07:23 PM | 09:24 PM | 08:02 PM, Jun 27 | 10:36 PM, Jun 28
2030-07-12 | Shukra Pradosh Vrat | Ashadha, Shukla | 07:22 PM | 09:24 PM | 05:13 PM, Jul 12 | 02:00 PM, Jul 13
2030-07-27 | Shani Pradosh Vrat | Shravana, Krishna | 07:15 PM | 09:20 PM | 12:21 PM, Jul 27 | 02:17 PM, Jul 28
2030-08-11 | Ravi Pradosh Vrat | Shravana, Shukla | 07:04 PM | 08:49 PM | 11:23 PM, Aug 10 | 08:49 PM, Aug 11
2030-08-26 | Soma Pradosh Vrat | Bhadrapada, Krishna | 06:49 PM | 09:03 PM | 04:17 AM, Aug 26 | 05:01 AM, Aug 27
2030-09-09 | Soma Pradosh Vrat | Bhadrapada, Shukla | 06:33 PM | 08:51 PM | 06:32 AM, Sep 09 | 04:56 AM, Sep 10
2030-09-24 | Bhauma Pradosh Vrat | Ashwina, Krishna | 07:14 PM | 08:39 PM | 07:14 PM, Sep 24 | 06:34 PM, Sep 25
2030-10-08 | Bhauma Pradosh Vrat | Ashwina, Shukla | 05:59 PM | 08:27 PM | 03:49 PM, Oct 08 | 03:31 PM, Oct 09
2030-10-24 | Guru Pradosh Vrat | Kartika, Krishna | 05:43 PM | 08:16 PM | 09:05 AM, Oct 24 | 07:09 AM, Oct 25
2030-11-07 | Guru Pradosh Vrat | Kartika, Shukla | 05:32 PM | 08:09 PM | 04:22 AM, Nov 07 | 05:29 AM, Nov 08
2030-11-23 | Shani Pradosh Vrat | Margashirsha, Krishna | 05:25 PM | 07:05 PM | 09:54 PM, Nov 22 | 07:05 PM, Nov 23
2030-12-07 | Shani Pradosh Vrat | Margashirsha, Shukla | 05:24 PM | 08:08 PM | 08:39 PM, Dec 06 | 10:57 PM, Dec 07
2030-12-22 | Ravi Pradosh Vrat | Pausha, Krishna | 05:29 PM | 08:14 PM | 09:41 AM, Dec 22 | 06:23 AM, Dec 23
"""
DRIK_COUNTS = {2025: 24, 2026: 25, 2027: 25, 2028: 25, 2029: 24, 2030: 25}


def _t12(text, ref):
    m = re.match(r"(\d\d):(\d\d) (AM|PM)(?:, (\w{3}) (\d\d))?", text.strip())
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)
    if m.group(4):
        mon = datetime.strptime(m.group(4), "%b").month
        y = ref.year + (1 if ref.month == 12 and mon == 1 else -1 if ref.month == 1 and mon == 12 else 0)
        return datetime(y, mon, int(m.group(5)), h, int(m.group(2)))
    return datetime(ref.year, ref.month, ref.day, h, int(m.group(2)))


DRIK = []
for line in DRIK_ROWS.strip().splitlines():
    f = [x.strip() for x in line.split("|")]
    d = date.fromisoformat(f[0])
    month, paksha = [x.strip() for x in f[2].split(",")]
    DRIK.append({"date": d, "name": f[1], "month": month, "paksha": paksha,
                 "puja": (_t12(f[3], d), _t12(f[4], d)), "tb": _t12(f[5], d), "te": _t12(f[6], d)})


def naive(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=None)


def minutes(a, b):
    return abs((a - b).total_seconds()) / 60


def all_records(lat_lon, years=range(2025, 2031)):
    out = []
    for y in years:
        out.extend(p.get_pradosh_calendar(y, *lat_lon))
    return out


# ---------------------------------------------------------------------------
print("\n[1] Reference set: 148 Drik dates 2025-2030 (New Delhi)")
check("reference rows parsed (148) and per-year counts", len(DRIK) == 148
      and all(sum(1 for x in DRIK if x["date"].year == y) == n for y, n in DRIK_COUNTS.items()))
recs = all_records(DELHI_DRIK)
resolved = {r["date"]: r for r in recs if r["status"] == "resolved"}
unresolved = [r for r in recs if r["status"] == "unresolved"]
drik_dates = {x["date"].isoformat() for x in DRIK}
check("one record per Drik entry in every year (resolved + unresolved)",
      all(sum(1 for r in recs if r["anchor_date"][:4] == str(y)) == n for y, n in DRIK_COUNTS.items()),
      {y: sum(1 for r in recs if r["anchor_date"][:4] == str(y)) for y in DRIK_COUNTS})
check("147 resolved dates equal Drik's dates exactly (no extra, none missing)",
      set(resolved) == drik_dates - {"2029-11-04"}, sorted(set(resolved) ^ (drik_dates - {"2029-11-04"})))
check("exactly one unresolved case: 2029-11-04 no_overlap, no date, no Puja Muhurat, candidates listed",
      len(unresolved) == 1 and unresolved[0]["resolution"] == "no_overlap" and unresolved[0]["anchor_date"] == "2029-11-04"
      and unresolved[0]["date"] is None and unresolved[0]["puja_muhurat"] is None and unresolved[0]["pradosh_kaal"] is None
      and unresolved[0]["candidates"] == [], unresolved)
check("unresolved Trayodashi timings are still reported (Drik: 08:57 PM Nov 03 -> 05:29 PM Nov 04)",
      minutes(naive(unresolved[0]["tithi"]["trayodashi_begins"]), datetime(2029, 11, 3, 20, 57)) <= 2
      and minutes(naive(unresolved[0]["tithi"]["trayodashi_ends"]), datetime(2029, 11, 4, 17, 29)) <= 2)

print("\n[2] Classification, Paksha and month labels (all 148)")
name_bad, paksha_bad, month_bad, puja_bad, tith_bad = [], [], [], [], []
for x in DRIK:
    key = x["date"].isoformat()
    r = resolved.get(key) or next(u for u in unresolved if u["anchor_date"] == key)
    if r["status"] == "resolved" and r["name"]["en"] != x["name"]:
        name_bad.append((key, x["name"], r["name"]["en"]))
    if r["paksha"]["en"] != x["paksha"]:
        paksha_bad.append(key)
    if r["lunar_month"]["purnimanta"]["base_en"] != x["month"]:
        month_bad.append((key, x["month"], r["lunar_month"]["purnimanta"]))
    if minutes(naive(r["tithi"]["trayodashi_begins"]), x["tb"]) > 2 or minutes(naive(r["tithi"]["trayodashi_ends"]), x["te"]) > 2:
        tith_bad.append(key)
    if r["status"] == "resolved":
        pm = r["puja_muhurat"]
        if minutes(naive(pm["start"]), x["puja"][0]) > 2 or minutes(naive(pm["end"]), x["puja"][1]) > 2:
            puja_bad.append((key, pm, x["puja"]))
check("weekday names (all seven forms) match Drik for 147 resolved dates", not name_bad, name_bad)
check("all seven weekday classifications occur", {r["classification"]["key"] for r in resolved.values()}
      == {"ravi", "soma", "bhauma", "budha", "guru", "shukra", "shani"})
check("Hindi names use the weekday classification", resolved["2026-12-21"]["name"]["hi"] == "सोम प्रदोष व्रत"
      and resolved["2027-01-05"]["name"]["hi"] == "भौम प्रदोष व्रत" and resolved["2027-03-20"]["name"]["hi"] == "शनि प्रदोष व्रत")
check("Paksha matches Drik for all 148", not paksha_bad, paksha_bad)
check("Purnimanta month matches Drik for all 148", not month_bad, month_bad[:3])
check("Trayodashi begin/end within 2 min of Drik for all 148", not tith_bad, tith_bad)
check("Puja Muhurat start/end within 2 min of Drik for all 147 resolved", not puja_bad, puja_bad[:2])
adhik = {k: resolved[k]["lunar_month"]["purnimanta"] for k in ("2026-05-14", "2026-05-28", "2026-06-12", "2026-06-27", "2029-03-27", "2029-04-11")}
check("Adhik Maas labelled explicitly (Adhik Jyeshtha 2026, Adhik Chaitra 2029; Nija months not)",
      [(v["en"], v["is_adhik"]) for v in adhik.values()] == [("Jyeshtha", False), ("Adhik Jyeshtha", True), ("Adhik Jyeshtha", True),
                                                             ("Jyeshtha", False), ("Adhik Chaitra", True), ("Adhik Chaitra", True)]
      and adhik["2026-05-28"]["hi"] == "अधिक ज्येष्ठ", adhik)
check("Amanta label differs from Purnimanta only for Krishna Paksha",
      all((r["lunar_month"]["amanta"]["key"] == r["lunar_month"]["purnimanta"]["key"]) == (r["paksha"]["key"] == "shukla" or r["lunar_month"]["amanta"]["is_adhik"])
          for r in resolved.values()))
check("Puja Muhurat never extends outside Pradosh Kaal or Trayodashi",
      all(naive(r["puja_muhurat"]["start"]) >= naive(r["pradosh_kaal"]["start"]) and naive(r["puja_muhurat"]["end"]) <= naive(r["pradosh_kaal"]["end"])
          and naive(r["puja_muhurat"]["start"]) >= naive(r["tithi"]["trayodashi_begins"]) and naive(r["puja_muhurat"]["end"]) <= naive(r["tithi"]["trayodashi_ends"])
          for r in resolved.values()))
check("Pradosh Kaal = sunset .. sunset + night/5 (e.g. ~2h44m in Jan, ~2h in Jun)",
      150 < resolved["2026-01-01"]["pradosh_kaal"]["duration_minutes"] < 170 and 115 < resolved["2027-06-16"]["pradosh_kaal"]["duration_minutes"] < 125)
check("partial overlap clipped to Trayodashi (2026-03-01 ends 7:09 PM; 2027-05-03 starts 8:03 PM)",
      minutes(naive(resolved["2026-03-01"]["puja_muhurat"]["end"]), datetime(2026, 3, 1, 19, 9)) <= 2
      and minutes(naive(resolved["2027-05-03"]["puja_muhurat"]["start"]), datetime(2027, 5, 3, 20, 3)) <= 2)
two_day = [r for r in resolved.values() if len(r["candidates"]) == 2]
check("consecutive-day cases resolved by maximum overlap (12 in 2025-2030), chosen = larger overlap",
      len(two_day) == 12 and all(r["overlap_minutes"] == max(c["overlap_minutes"] for c in r["candidates"]) for r in two_day), len(two_day))

print("\n[3] Location differences and default location")
luck_all = all_records(LUCKNOW)
luck = {r["date"] for r in luck_all if r["status"] == "resolved"}
luck_unres = [r for r in luck_all if r["status"] == "unresolved"]
delhi = set(resolved)
check("Lucknow vs New Delhi differ only on the known cases",
      sorted(delhi - luck) == ["2025-02-09", "2027-05-03"] and sorted(luck - delhi) == ["2027-05-04", "2029-11-04"],
      (sorted(delhi - luck), sorted(luck - delhi)))
check("Lucknow Feb 2025: overlaps 62.7 vs 63.1 min -> near_tie, left undecided (not guessed)",
      [(r["anchor_date"], r["resolution"], [c["date"] for c in r["candidates"]]) for r in luck_unres]
      == [("2025-02-10", "near_tie", ["2025-02-09", "2025-02-10"])], [(r["anchor_date"], r["resolution"]) for r in luck_unres])
default = {r["date"] for r in all_records((None, None)) if r["status"] == "resolved"}
check("default location (New Delhi 28.61, 77.23) gives the same 147 dates", default == delhi, sorted(default ^ delhi))
for bad in [(40.71, -74.0), (51.5, -0.12), (50.0, 77.0), (28.6, 150.0), ("x", 77), (True, 77), (float("nan"), 77)]:
    try:
        p.get_pradosh_calendar(2026, *bad)
        check(f"unsupported/invalid location rejected {bad}", False)
    except p.PradoshInputError:
        check(f"unsupported/invalid location rejected {bad}", True)

print("\n[4] Year boundaries and IST date handling")
c25 = p.get_pradosh_calendar(2025, *DELHI_DRIK)
c28 = p.get_pradosh_calendar(2028, *DELHI_DRIK)
check("Trayodashi starting 28 Dec 2028 (Shukra Pradosh 29 Dec) is in 2028", c28[-1]["date"] == "2028-12-29")
check("2025's last (17 Dec, Pausha Krishna) and 2026's first (1 Jan, Pausha Shukla) present",
      c25[-1]["date"] == "2025-12-17" and p.get_pradosh_calendar(2026, *DELHI_DRIK)[0]["date"] == "2026-01-01")
v = p.get_pradosh_today_next(date(2025, 12, 31), *DELHI_DRIK)
check("next crosses the year (31 Dec 2025 -> 1 Jan 2026)", v["today"] is None and v["next"]["date"] == "2026-01-01")
v = p.get_pradosh_today_next(date(2026, 12, 21), *DELHI_DRIK)
check("today = Soma Pradosh 21 Dec 2026 (missed by the old engine); next = 5 Jan 2027",
      v["today"]["name"]["en"] == "Soma Pradosh Vrat" and v["next"]["date"] == "2027-01-05")
v = p.get_pradosh_today_next(date(2029, 10, 30), *DELHI_DRIK)
check("unresolved 4 Nov 2029 surfaced before next (18 Nov 2029), never as today/next",
      v["next"]["date"] == "2029-11-18" and [u["anchor_date"] for u in v["unresolved_before_next"]] == ["2029-11-04"])
check("ist_today: 2026-12-20T19:00Z is 21 Dec in IST",
      p.ist_today(datetime(2026, 12, 20, 19, 0, tzinfo=timezone.utc)) == date(2026, 12, 21)
      and p.ist_today(datetime(2026, 12, 20, 18, 29, tzinfo=timezone.utc)) == date(2026, 12, 20))
for bad_year in [1899, 2101, "2026", True, 2026.0]:
    try:
        p.get_pradosh_calendar(bad_year)
        check(f"invalid year rejected {bad_year!r}", False)
    except p.PradoshInputError:
        check(f"invalid year rejected {bad_year!r}", True)

print("\n[5] Near-tie and no-overlap logic (synthetic, engine functions only)")
real_kaal = p._pradosh_kaal
try:
    base = datetime(2030, 3, 10, 18, 0)
    def fake_kaal(day, lat, lon):
        s = datetime(day.year, day.month, day.day, 18, 0)
        return s, s + timedelta(hours=2)
    p._pradosh_kaal = fake_kaal
    # Trayodashi from 19:00 on day 1 to 19:00:30 on day 2 -> overlaps 60 min and 60.5 min: a near-tie
    r = p.resolve_span(13, base + timedelta(hours=1), base + timedelta(days=1, hours=1, seconds=30), 28.61, 77.23)
    check("near-tie flagged unresolved: no date, no Puja Muhurat, both candidates listed",
          r["resolution"] == "near_tie" and r["date"] is None and r["puja_muhurat"] is None and len(r["candidates"]) == 2, r)
    r = p.resolve_span(13, base + timedelta(hours=1), base + timedelta(days=1, hours=1, minutes=30), 28.61, 77.23)
    check("clear difference (90 vs 60 min) resolved to the later day", r["resolution"] == "max_overlap" and r["date"] == "2030-03-11")
    r = p.resolve_span(13, base + timedelta(hours=3), base + timedelta(hours=23), 28.61, 77.23)
    check("no overlap with any Pradosh Kaal -> no_overlap, unresolved", r["resolution"] == "no_overlap" and r["date"] is None)
finally:
    p._pradosh_kaal = real_kaal

print("\n[6] Caching, copies and concurrency")
info = p._calendar_cached.cache_info()
check("calendar cache bounded (maxsize 64), sun-times cache bounded (4096)",
      info.maxsize == p.CALENDAR_CACHE_SIZE == 64 and p._sun_times.cache_info().maxsize == 4096)
mut = p.get_pradosh_calendar(2026, *DELHI_DRIK)
mut[0]["date"] = "MUTATED"
mut[0]["lunar_month"]["purnimanta"]["en"] = "MUTATED"
again = p.get_pradosh_calendar(2026, *DELHI_DRIK)
check("callers get copies: mutating a result does not touch the cache",
      again[0]["date"] == "2026-01-01" and again[0]["lunar_month"]["purnimanta"]["en"] == "Pausha")
sequential = {(y, loc): p.get_pradosh_calendar(y, *loc) for y in (2026, 2027) for loc in (DELHI_DRIK, LUCKNOW)}
p.clear_caches()
jobs = [(y, loc) for y in (2026, 2027) for loc in (DELHI_DRIK, LUCKNOW)] * 3
with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(lambda j: (j, p.get_pradosh_calendar(j[0], *j[1])), jobs))
check("24 concurrent calendar requests on 8 fresh threads equal the sequential results (Lahiri per thread)",
      all(res == sequential[j] for j, res in results))
check("engine source has no hardcoded dates", not re.search(r"\b(19|20)\d\d-\d\d-\d\d\b|date\(\s*(19|20)\d\d",
                                                        open(os.path.join("services", "pradosh_engine.py"), encoding="utf-8").read()))

print("\n[7] /api/events/pradosh (backward compatible + additive)")
app = Flask(__name__)
app.register_blueprint(routes_events, url_prefix="/api/events")
c = app.test_client()
LEGACY_KEYS = {"type", "name_en", "name_hi", "slug", "date", "paksha", "sunset_time", "tithi_at_sunset"}
r = c.post("/api/events/pradosh", json={"date": "2026-12-21"})
j = r.get_json()
check("200; legacy top-level keys today/next present", r.status_code == 200 and "today" in j and "next" in j)
t = j["today"]
check("legacy item keys and formats unchanged", LEGACY_KEYS <= set(t) and t["type"] == "pradosh" and t["slug"] == "pradosh-vrat"
      and t["name_en"] == "Shukla Pradosh Vrat" and t["name_hi"] == "शुक्ल प्रदोष व्रत" and t["paksha"] == "Shukla"
      and re.fullmatch(r"\d\d:\d\d", t["sunset_time"]) and isinstance(t["tithi_at_sunset"], int), t)
check("additive: weekday name, Puja Muhurat, Trayodashi, month, both languages",
      t["vrat_name_en"] == "Soma Pradosh Vrat" and t["vrat_name_hi"] == "सोम प्रदोष व्रत" and t["display_name"] == "Soma Pradosh Vrat"
      and t["puja_muhurat"]["start"].startswith("2026-12-21T17:") and t["trayodashi"]["number"] == 13
      and t["lunar_month"]["purnimanta"]["en"] == "Margashirsha" and t["classification"]["key"] == "soma")
check("tithi_at_sunset keeps its meaning (12 here: Trayodashi starts just after sunset)", t["tithi_at_sunset"] in (12, 13))
check("next = 2027-01-05 Bhauma; meta convention; location default", j["next"]["date"] == "2027-01-05"
      and j["next"]["vrat_name_en"] == "Bhauma Pradosh Vrat" and j["meta"]["version"] == "pradosh-1" and j["location"]["is_default"])
j = c.post("/api/events/pradosh", json={"date": "2026-11-27", "language": "hi"}).get_json()
check("non-Pradosh day: today null, next 6 Dec; Hindi display_name", j["today"] is None and j["next"]["date"] == "2026-12-06"
      and j["next"]["display_name"] == "रवि प्रदोष व्रत" and j["language"] == "hi")
j = c.post("/api/events/pradosh", json={"year": 2027, "lang": "hi", "latitude": 26.8467, "longitude": 80.9462}).get_json()
check("annual calendar (year + lang alias + Lucknow): 25 records, Lucknow date 4 May 2027",
      j["year"] == 2027 and len(j["calendar"]) == 25 and "2027-05-04" in [x["date"] for x in j["calendar"]] and not j["location"]["is_default"])
j = c.post("/api/events/pradosh", json={"date": "2029-10-30", "latitude": 28.6356, "longitude": 77.2244}).get_json()
check("unresolved listed before next, without date or Puja Muhurat",
      [u["anchor_date"] for u in j["unresolved_before_next"]] == ["2029-11-04"] and j["unresolved_before_next"][0]["date"] is None
      and j["unresolved_before_next"][0]["puja_muhurat"] is None and j["next"]["date"] == "2029-11-18")
orig = routes_module.pradosh_ist_today
routes_module.pradosh_ist_today = lambda: p.ist_today(datetime(2026, 12, 20, 19, 0, tzinfo=timezone.utc))
try:
    j = c.post("/api/events/pradosh", json={}).get_json()
    check("no date -> IST today (2026-12-20T19:00Z = 21 Dec IST -> today is Soma Pradosh)", j["date"] == "2026-12-21" and j["today"]["date"] == "2026-12-21")
finally:
    routes_module.pradosh_ist_today = orig
r = c.post("/api/events/pradosh", data="")
check("empty body accepted (defaults)", r.status_code == 200)
for body, label in [('{"date": "21-12-2026"}', "bad date"), ('{"year": 2101}', "year out of range"), ('{"year": "abc"}', "bad year"),
                    ('{"latitude": 40.71, "longitude": -74}', "unsupported location"), ('{"language": "fr"}', "bad language"),
                    ("[1,2]", "non-object JSON"), ("{bad", "malformed JSON"), ('{"date": 20261221}', "non-string date")]:
    r = c.post("/api/events/pradosh", data=body, content_type="application/json")
    check(f"400 for {label}", r.status_code == 400 and "error" in r.get_json(), (r.status_code, r.get_data(as_text=True)[:120]))

print(f"\nTOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
