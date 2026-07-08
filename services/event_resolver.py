# services/event_resolver.py
#
# AstroEvent -> Resource identity ONLY.
# This module must never know about Flutter, navigation, CTA, screens,
# WebViews, checkout, or any other presentation concept. It answers a
# single content question: "does this event have an associated resource,
# and if so, what type/id/canonical-url identifies it?"

BASE_URL = "https://jyotishasha.com"

# Languages the site actually publishes canonical URLs for. An
# unsupported/unknown lang falls back to "en" rather than producing
# a URL for a locale that doesn't exist -- see build_resource_url().
SUPPORTED_LANGS = {"en", "hi"}

# One URL template per resource.type. A type with no entry here has
# no known URL scheme yet, so build_resource_url() returns None for
# it instead of guessing a shape.
_URL_BUILDERS = {
    "authority": lambda resource_id, lang: f"{BASE_URL}/{lang}/{resource_id}",
}


def build_resource_url(resource_type, resource_id, lang="en"):
    """
    Derive the canonical production URL for a resource from its
    existing type + id only. Never fabricates a URL for a resource
    type with no known scheme -- returns None instead.
    """
    builder = _URL_BUILDERS.get(resource_type)
    if not builder:
        return None

    safe_lang = lang if lang in SUPPORTED_LANGS else "en"
    return builder(resource_id, safe_lang)


def resolve_resource(event, lang="en"):
    """
    Resolve an AstroEvent row to a generic resource pointer.

    Returns:
        {"type": <resource type>, "id": <resource id>,
         "url": <canonical url or None>, "meta": {}}
        or None when the event has no associated resource.

    Never fabricates data: a resource is only returned when the
    event's own stored meta already carries the fields needed to
    identify it (today: "type" + "slug", as written by producers
    like ekadashi_engine.build_ekadashi_json). Event categories that
    don't populate these fields correctly resolve to None. Likewise,
    "url" is only ever a value this module can actually derive from
    type + id -- never a fabricated guess.
    """
    meta = event.meta or {}
    slug = meta.get("slug")
    sub_type = meta.get("type")

    if not slug or not sub_type:
        return None

    resource_type = "authority"
    resource_id = f"{sub_type}/{slug}"

    return {
        "type": resource_type,
        "id": resource_id,
        "url": build_resource_url(resource_type, resource_id, lang),
        "meta": {}
    }
