# routes/routes_event_resource.py
#
# Event Resource API for the Notification Platform.
# Independent of POST /api/cards: no shared route, no shared behavior,
# reuses card_service's content builders as pure functions only.

from flask import Blueprint, request, jsonify
from models import AstroEvent
from services.event_adapters.festival_adapter import normalize_type
from services.card_service import build_festival_card, build_planet_card
from services.event_resolver import resolve_resource

event_resource_bp = Blueprint(
    "event_resource", __name__, url_prefix="/api/events"
)

_CONTENT_BUILDERS = {
    "vrat": build_festival_card,
    "festival": build_festival_card,
    "transit": lambda event_dict: build_planet_card([event_dict]),
}


def _event_category(event):
    # AstroEvent.type is already normalized at save time
    # (festival_adapter.normalize_event). meta["type"], when present,
    # still holds the original raw sub-type (e.g. "ekadashi"), so only
    # that raw value may be passed through normalize_type() -- running
    # it on the already-normalized column would misclassify it
    # (e.g. "vrat" -> "festival", since "vrat" isn't a recognized raw input).
    raw_subtype = (event.meta or {}).get("type")
    return normalize_type(raw_subtype) if raw_subtype else event.type


def _event_content(event, lang):
    category = _event_category(event)

    event_dict = {
        "name": event.name,
        "name_en": event.name,
        "name_hi": event.name,
        "type": category,
        "meta": event.meta or {},
        # so build_festival_card can compute the real Today/Tomorrow/
        # Yesterday wording via relative_day.py instead of assuming one
        "date": event.date,
    }

    builder = _CONTENT_BUILDERS.get(category)
    card = builder(event_dict) if builder else None

    if not card:
        return event.name, ""

    title = card.get(f"title_{lang}") or card.get("title_en") or event.name
    body = card.get(f"content_{lang}") or card.get("content_en") or ""
    return title, body


@event_resource_bp.route("/<int:event_id>/resource", methods=["GET"])
def get_event_resource(event_id):
    event = AstroEvent.query.get(event_id)

    if not event:
        return jsonify({"error": "Event not found"}), 404

    lang = request.args.get("lang", "en")
    title, body = _event_content(event, lang)

    event_date = event.date
    date_str = (
        event_date.strftime("%Y-%m-%d")
        if hasattr(event_date, "strftime")
        else str(event_date)[:10]
    )

    return jsonify({
        "schema_version": 1,
        "event": {
            "id": event.id,
            "type": event.type,
            "title": title,
            "body": body,
            "date": date_str,
        },
        "resource": resolve_resource(event, lang)
    })
