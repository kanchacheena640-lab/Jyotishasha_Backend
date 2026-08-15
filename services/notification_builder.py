import os
from services.personalization_engine import (
    get_users_for_transit,
    get_users_for_dasha_change,
    get_current_dasha_users
)
from services.relative_day import get_relative_day, TODAY, TOMORROW, YESTERDAY
from services.card_service import build_good_morning_card
from datetime import date, timedelta
from models import AstroEvent

LINK_MAP = {
    "ekadashi": "jyotishasha.com/ekadashi",
    # future:
    # "pradosh": "jyotishasha.com/pradosh",
    # "amavasya": "jyotishasha.com/amavasya",
}

_DAY_WORD = {
    TODAY: "Today",
    TOMORROW: "Tomorrow",
    YESTERDAY: "Yesterday",
}

# ---------------------------------------------------------------------------
# N3 -- Personalized Planetary Transit content.
#
# Source of truth for every value below (do not hand-edit without re-checking
# the source): planet slugs, house-ordinal strings and the
# "{slug}-in-{ordinal}-house" URL formula are the EXACT conventions verified
# against jyotishasha-frontend/lib/planetInHouse/*/skeleton.ts (PLANET_SLUG/
# PLANET_EN/PLANET_HI, identical across all 9 planet directories) and
# lib/planetInHouse/houseData.ts (ORDINALS, HOUSE_LABELS). Reusing these
# verbatim is what guarantees the constructed URL always resolves to a real,
# existing article, and that the push copy's house wording matches the
# article it links to.
# ---------------------------------------------------------------------------
SITE_URL = "https://www.jyotishasha.com"

_HOUSE_ORDINALS = [
    "1st", "2nd", "3rd", "4th", "5th", "6th",
    "7th", "8th", "9th", "10th", "11th", "12th",
]

_HOUSE_LABEL_HI = [
    "प्रथम भाव", "द्वितीय भाव", "तृतीय भाव", "चतुर्थ भाव",
    "पंचम भाव", "षष्ठ भाव", "सप्तम भाव", "अष्टम भाव",
    "नवम भाव", "दशम भाव", "एकादश भाव", "द्वादश भाव",
]

_PLANET_HI = {
    "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
    "Jupiter": "बृहस्पति", "Venus": "शुक्र", "Saturn": "शनि",
    "Rahu": "राहु", "Ketu": "केतु",
}


def _planet_in_house_url(planet: str, house: int, lang: str) -> str | None:
    """
    Deterministic Planet-in-House article URL, matching the website's own
    slug formula exactly (`${planetSlug}-in-${ordinal}-house`). Returns None
    for an out-of-range house or unrecognized planet rather than guessing a
    URL that might not exist.
    """
    if not planet or not (1 <= house <= 12):
        return None

    planet_slug = planet.strip().lower()
    if planet_slug not in {p.lower() for p in _PLANET_HI}:
        return None

    slug = f"{planet_slug}-in-{_HOUSE_ORDINALS[house - 1]}-house"
    prefix = "/hi" if lang == "hi" else ""
    return f"{SITE_URL}{prefix}/planet-in-house/{slug}"


def build_transit_content(planet: str, house: int, lang: str):
    """
    The single place that turns a personalized (planet, house) transit
    result into T-1 notification title/body/url -- shared by both the
    Bell/push content below and any future caller, the same pattern
    build_event_content()/build_panchang_content() already establish.

    This is NOT a fully personalized prediction -- the destination article
    is generic Planet-in-House educational content. The personalization is
    solely which house applies to this user's own natal chart; the copy
    below is careful to only ever claim that (WHAT transits, WHERE in this
    user's chart, WHY to look), never a specific outcome.

    `lang` must already be resolved to "en" or "hi" by the caller (see
    get_user_notifications() below) -- this function does no further
    fallback/guessing, matching every other content builder in this file.
    """
    if lang == "hi":
        planet_label = _PLANET_HI.get(planet, planet)
        house_label = _HOUSE_LABEL_HI[house - 1]
        title = f"{planet_label} कल आपके {house_label} में प्रवेश करेगा"
        body = f"यह गोचर आपके {house_label} को प्रभावित करेगा। पूरी जानकारी के लिए टैप करें।"
    else:
        house_label = f"{_HOUSE_ORDINALS[house - 1]} House"
        title = f"{planet} Transit Tomorrow: {house_label}"
        body = f"{planet} moves into your {house_label} tomorrow. Tap to see what this means for you."

    return {
        "title": title,
        "body": body,
        "url": _planet_in_house_url(planet, house, lang),
    }


def build_event_content(event):
    """
    The single place that turns a vrat/festival AstroEvent into
    notification title/body/data -- used for both the personalized Bell
    (get_user_notifications' EVENT section) and the Step 5A topic
    broadcast (event_scheduler.py), so both always say the same thing.
    Not user-specific: same event always produces the same content.

    Today/Tomorrow/Yesterday wording comes from relative_day.py -- the
    one place that compares event.date to "now" -- never hand-rolled
    here, which is what previously let this text disagree with
    card_service's Event Detail wording for the same event.
    """
    event_type = getattr(event, "type", None)
    event_name = getattr(event, "name", None)
    event_id = getattr(event, "id", None)
    event_date = getattr(event, "date", None)

    if event_type not in ["vrat", "festival"] or not event_id:
        return None

    relative_day = get_relative_day(event_date)
    day_word = _DAY_WORD.get(relative_day, "Today")

    name_lower = (event_name or "").lower()

    link = None
    for key in LINK_MAP:
        if key in name_lower:
            link = LINK_MAP[key]
            break

    if link:
        body = f"""{event_name} {day_word} 🙏

        Vrat vidhi, mahatva aur Paran time jaane
        👉 Read Full Guide

        {link}"""
    else:
        body = f"""{event_name} {day_word} 🙏

        Is din ka vishesh mahatva hai
        Niyamon ka dhyan rakhein"""

    title = f"{event_name} {day_word}" if relative_day in _DAY_WORD else event_name

    return {
        "title": title,
        "body": body,
        "data": {
            "type": "event",
            "event_id": str(event_id)
        }
    }


def build_panchang_content(event):
    """
    The single place that turns the daily "panchang" AstroEvent into
    title/body/data -- used for both the Bell/push (get_user_notifications'
    PANCHANG section) and the Resource API (routes_event_resource.py), so
    the notification and the Summary screen it opens always say the same
    thing. Reuses card_service.build_good_morning_card() for the Abhijit
    Muhurta / Rahu Kaal text instead of recomputing it.
    """
    event_id = getattr(event, "id", None)
    event_date = getattr(event, "date", None)
    meta = getattr(event, "meta", None) or {}

    if not event_id:
        return None

    good_morning = build_good_morning_card(meta) or {}
    times = good_morning.get("meta", {})
    tithi_name = (meta.get("tithi") or {}).get("name") or "Not available"

    body = (
        f"Today's Tithi: {tithi_name}\n"
        f"Best Time (Shubh): {times.get('abhijit', 'Not available')}\n"
        f"Avoid Time (Ashubh): {times.get('rahu_kaal', 'Not available')}"
    )

    data = {
        "type": "panchang",
        "event_id": str(event_id)
    }
    if event_date is not None:
        data["date"] = str(event_date)

    return {
        "title": "🌅 Today's Panchang",
        "body": body,
        "data": data
    }


def get_user_notifications(user, events):
    """
    Returns personalized notifications for a user. There is no generic
    "global" fallback section any more -- if nothing below has anything
    eligible to say, this simply returns an empty list (v1.1 freeze:
    the generic "Aaj ka Din Mahatvapurn Hai" fallback is removed and
    must never be sent).
    """

    final_notifications = []
    seen = set()

    # ---------------------------
    # 🔹 EVENT (VRAT / FESTIVAL) -- sole owner of AstroEvent notifications
    # ---------------------------
    # One AstroEvent produces exactly one notification. This is the only
    # section allowed to turn a vrat/festival AstroEvent into a
    # notification; its dedup identity (event_scheduler.py) is the
    # AstroEvent's own id, so there is exactly one code path and one key
    # per event -- never two. Content comes from build_event_content()
    # above, shared with the Step 5A topic broadcast.
    for event in events:
        event_id = getattr(event, "id", None)

        if event_id in seen:
            continue

        # 🔒 Selection layer: morning may only select TODAY's vrat/festival;
        # evening may only select a TOMORROW reminder for one. This is a
        # selection decision (should this AstroEvent become a notification
        # right now), not content -- build_event_content() stays a pure
        # AstroEvent -> title/body/payload function with no knowledge of
        # slot or runtime context.
        relative_day = get_relative_day(getattr(event, "date", None))
        slot = os.getenv("NOTIFICATION_SLOT", "").strip().lower()

        if slot == "morning" and relative_day != TODAY:
            continue
        if slot == "evening" and relative_day != TOMORROW:
            continue
        if slot not in ("morning", "evening"):
            continue

        content = build_event_content(event)
        if not content:
            continue

        seen.add(event_id)
        final_notifications.append(content)

    # ---------------------------
    # 🔹 TRANSIT (N3 -- personalized, T-1)
    # ---------------------------
    # Product rule: exactly ONE notification per (user, transit), delivered
    # the day BEFORE the transit date -- not a same-day "already happened"
    # notice (the pre-N3 wording/timing this replaces). Mirrors the EVENT
    # section's own TOMORROW-reminder gating above (relative_day.py, never
    # hand-rolled): only the evening slot may select a transit AstroEvent
    # dated TOMORROW (relative to the actual moment this job runs, not
    # target_date) -- this is also what makes a late-running evening job
    # refuse to send once the transit day has actually begun (delayed-cron
    # safety), and what stops the morning slot from ever double-sending the
    # same transit later the same day.
    transit_map = {}

    for event in events:
        event_type = getattr(event, "type", None)
        event_id = getattr(event, "id", None)

        if event_type != "transit" or not event_id:
            continue

        try:
            transit_map[event_id] = get_users_for_transit(event)
        except Exception as e:
            print(f"❌ Transit map error for event {event_id}: {str(e)}")
            continue

    transit_slot = os.getenv("NOTIFICATION_SLOT", "").strip().lower()

    for event in events:
        event_type = getattr(event, "type", None)
        event_id = getattr(event, "id", None)
        event_date = getattr(event, "date", None)

        if event_type != "transit" or not event_id:
            continue

        if transit_slot != "evening":
            continue
        if get_relative_day(event_date) != TOMORROW:
            continue

        for u in transit_map.get(event_id, []):
            try:
                if u["user"].id != user.id:
                    continue

                event_id_str = f"transit_{event_id}_{u['planet']}_{u['house']}"

                if event_id_str in seen:
                    continue
                seen.add(event_id_str)

                # Language: resolved once, deterministically, from the
                # user's own persisted preference (modules/models_user.py::
                # AppUser.lang, N3) -- never device guesswork. Unset/
                # unrecognized values fall back to "en", matching this
                # project's existing default (see routes_profile_bootstrap.py
                # ::bootstrap_user_profile()'s own `data.get("lang", "en")`).
                lang = (getattr(user, "lang", None) or "en").strip().lower()
                if lang not in ("en", "hi"):
                    lang = "en"

                content = build_transit_content(u["planet"], u["house"], lang)

                data = {
                    "type": "transit",
                    "event_id": str(event_id),
                    "planet": u["planet"],
                    "house": str(u["house"]),
                    "language": lang,
                }
                if event_date is not None:
                    data["transit_date"] = str(event_date)
                if content["url"]:
                    data["url"] = content["url"]

                final_notifications.append({
                    "title": content["title"],
                    "body": content["body"],
                    "data": data,
                })

            except Exception as e:
                print(f"❌ Transit user error: {str(e)}")
                continue

    # ---------------------------
    # 🔹 DASHA T-5 ALERT
    # ---------------------------
    t_minus_5_users = get_users_for_dasha_change(days_before=5)

    for d in t_minus_5_users:
        if d["user"].id != user.id:
            continue

        event_id_str = f"dasha_pre_{d['user'].id}_{d['mahadasha']}_{d['antardasha']}"

        if event_id_str in seen:
            continue
        seen.add(event_id_str)

        final_notifications.append({
            "title": "⏳ Dasha Change Coming",
            "body": f"5 din baad aapki {d['mahadasha']} - {d['antardasha']} dasha shuru hogi",
            "data": {
                "type": "dasha_pre",
                "event_id": event_id_str,
                "mahadasha": d["mahadasha"],
                "antardasha": d["antardasha"],
                # N2.1 -- the authoritative UserDashaTimeline.start_date
                # this warning is about (services/personalization_engine.py
                # ::get_users_for_dasha_change(), unmodified query/selection
                # logic), so services/event_scheduler.py can derive this
                # notification's expires_at from the real transition date
                # instead of leaving it unexpired. Purely additive: event_id
                # (dedup identity), title, and body are all unchanged.
                "start_date": d["start_date"].isoformat(),
            }
        })

    # ---------------------------
    # 🔹 DASHA START (SAME DAY)
    # ---------------------------
    dasha_users = get_users_for_dasha_change()

    for d in dasha_users:
        if d["user"].id != user.id:
            continue

        event_id_str = f"dasha_{d['user'].id}_{d['mahadasha']}_{d['antardasha']}"

        if event_id_str in seen:
            continue
        seen.add(event_id_str)

        final_notifications.append({
            "title": f"{d['mahadasha']} Dasha Update 🔮",
            "body": f"{d['mahadasha']} - {d['antardasha']} phase शुरू हो गया है",
            "data": {
                "type": "dasha",
                "event_id": event_id_str,
                "mahadasha": d["mahadasha"],
                "antardasha": d["antardasha"]
            }
        })

    # ---------------------------
    # 🔹 PANCHAK
    # ---------------------------
    for event in events:
        try:
            event_type = getattr(event, "type", None)
            event_name = getattr(event, "name", None)
            event_id = getattr(event, "id", None)
            event_date = getattr(event, "date", None)

            if event_type != "panchak" or not event_id or not event_date:
                continue

            # 🔥 Only notify on the FIRST day of this Panchak window.
            # AstroEvent gets a fresh "panchak" row every day it stays active,
            # so a row dated "yesterday" means today is a continuation, not the start.
            prev_day = event_date - timedelta(days=1)

            already_running = AstroEvent.query.filter_by(
                type="panchak",
                date=prev_day
            ).first()

            if already_running:
                continue

            event_id_str = f"panchak_{event_id}"

            if event_id_str in seen:
                continue
            seen.add(event_id_str)

            final_notifications.append({
                "title": event_name or "Panchak Alert",
                "body": f"""{event_name or "Panchak"} शुरू हो गया है 🙏

        Is samay nirmaan, yatra aur mahatvapurn karyon se bachein
        Niyamon ka dhyan rakhein""",
                "data": {
                    "type": "panchak",
                    "event_id": str(event_id)
                }
            })

        except Exception as e:
            print(f"❌ Panchak event error: {str(e)}")
            continue

    # ---------------------------
    # 🔹 PANCHANG (Today's Panchang -- one per day, not personalized)
    # ---------------------------
    # Content comes from build_panchang_content() above, shared with the
    # Resource API (routes_event_resource.py), so the notification and
    # the screen it opens can never disagree about what today's Panchang says.
    for event in events:
        try:
            event_type = getattr(event, "type", None)
            event_id = getattr(event, "id", None)

            if event_type != "panchang" or not event_id:
                continue

            # 🔒 Defensive validation: the scheduler intentionally hands
            # over both today's and tomorrow's AstroEvents (other sections
            # need the look-ahead for pre-event reminders). Panchang is a
            # same-day, morning-only notification, so this must not trust
            # that it was already filtered upstream -- it refuses on its
            # own even if tomorrow's Panchang (or an evening-slot run)
            # reaches this loop.
            if os.getenv("NOTIFICATION_SLOT", "").strip().lower() != "morning":
                continue

            if get_relative_day(getattr(event, "date", None)) != TODAY:
                continue

            event_id_str = f"panchang_{event_id}"

            if event_id_str in seen:
                continue

            content = build_panchang_content(event)
            if not content:
                continue

            seen.add(event_id_str)
            final_notifications.append(content)

        except Exception as e:
            print(f"❌ Panchang notification error: {str(e)}")
            continue

    # 🔥 RETURN AT END ONLY
    return final_notifications