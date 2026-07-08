# services/event_resolver.py
#
# AstroEvent -> Resource identity ONLY.
# This module must never know about Flutter, navigation, CTA, screens,
# WebViews, checkout, or any other presentation concept. It answers a
# single content question: "does this event have an associated resource,
# and if so, what type/id identifies it?"


def resolve_resource(event):
    """
    Resolve an AstroEvent row to a generic resource pointer.

    Returns:
        {"type": <resource type>, "id": <resource id>, "meta": {}}
        or None when the event has no associated resource.

    Never fabricates data: a resource is only returned when the
    event's own stored meta already carries the fields needed to
    identify it (today: "type" + "slug", as written by producers
    like ekadashi_engine.build_ekadashi_json). Event categories that
    don't populate these fields correctly resolve to None.
    """
    meta = event.meta or {}
    slug = meta.get("slug")
    sub_type = meta.get("type")

    if not slug or not sub_type:
        return None

    return {
        "type": "authority",
        "id": f"{sub_type}/{slug}",
        "meta": {}
    }
