# lahiri_mode.py
#
# U4C.2B -- the ONE shared, minimal helper establishing Swiss
# Ephemeris's sidereal mode on the CALLING THREAD, immediately before
# any sidereal calculation.
#
# Root cause (see U4C.2A's audit): pyswisseph's swe.set_sid_mode()
# state is THREAD-LOCAL, not process-global -- proved directly by
# spawning a fresh Python thread in the same process as an already-set
# main thread and observing a different ayanamsa. Calling it once at
# module import time (the pattern nearly every astrology module in
# this codebase used before this task) only protects the thread that
# performed that import -- typically the main thread. Any OTHER thread
# (a Flask/Werkzeug worker thread handling one HTTP request, a Celery
# worker running in a threaded/eventlet/gevent pool, any directly
# spawned background thread) that never itself calls
# swe.set_sid_mode(swe.SIDM_LAHIRI) silently computes with Swiss
# Ephemeris's own un-set default (mode 0 == SIDM_FAGAN_BRADLEY),
# producing sidereal longitudes offset by a constant ~0.8832 degrees
# from true Lahiri -- confirmed in U4C.2A to be large enough to change
# a planet's Rashi near a sign boundary (a real instant: Mercury
# reads Virgo under true Lahiri, Leo under the un-set default).
#
# Contract: call ensure_lahiri_mode() at the START of every
# authoritative Jyotish calculation function that performs a sidereal
# Swiss Ephemeris call, on whatever thread is actually executing it --
# never rely on import order, a previous function having already run,
# or any particular WSGI/Celery threading model. The call itself is a
# single, cheap C-extension call (see U4C.2B's own performance
# measurement) -- safe and intended to be called on every invocation,
# not cached away or called "once" per thread/request.
#
# This file intentionally contains NOTHING else -- no astrology math,
# no ephemeris PATH configuration (a deliberately separate concern,
# proven unrelated to this bug in U4C.2A Sec.5/6 -- see U4C.2B Sec.15),
# just this one guard.

import swisseph as swe


def ensure_lahiri_mode() -> None:
    """Establishes SIDM_LAHIRI on the CALLING thread. Idempotent and
    cheap enough to call immediately before every sidereal calculation
    -- see U4C.2B report Sec.17 for the measured overhead."""
    swe.set_sid_mode(swe.SIDM_LAHIRI)
