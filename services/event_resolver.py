# services/event_resolver.py
#
# AstroEvent -> Resource identity ONLY.
# This module must never know about Flutter, navigation, CTA, screens,
# WebViews, checkout, or any other presentation concept. It answers a
# single content question: "does this event have an associated resource,
# and if so, what type/id/canonical-url identifies it?"

# Legacy URL scheme, used for every resource sub-type that has no
# canonical builder registered in _CANONICAL_URL_BUILDERS below.
LEGACY_BASE_URL = "https://jyotishasha.com"

# Frontend domain that actually serves canonical content pages.
FRONTEND_BASE_URL = "https://www.jyotishasha.com"

# Languages the site actually publishes canonical URLs for. An
# unsupported/unknown lang falls back to "en" rather than producing
# a URL for a locale that doesn't exist -- see build_resource_url().
SUPPORTED_LANGS = {"en", "hi"}


def _legacy_authority_url(resource_id, lang):
    """
    Pre-existing URL scheme: jyotishasha.com/<lang>/<resource_id>.
    This is the fallback for any resource sub-type that hasn't been
    given a canonical builder below, so fixing one sub-type's URL
    never changes another's.
    """
    return f"{LEGACY_BASE_URL}/{lang}/{resource_id}"


def _ekadashi_canonical_url(resource_id, lang):
    """
    Ekadashi resource ids look like "ekadashi/yogini" -- the slug is
    just the vrat's base name (see ekadashi_engine.get_ekadashi_name()),
    it never carries the word "Ekadashi". The frontend's canonical page
    always does, e.g. https://www.jyotishasha.com/ekadashi/yogini-ekadashi.
    A few adhik-maas names (e.g. "Padmini Ekadashi") already end in
    "ekadashi", so the suffix is only added when it's actually missing.
    """
    sub_type, slug = resource_id.split("/", 1)
    canonical_slug = slug if slug.endswith("-ekadashi") else f"{slug}-ekadashi"
    return f"{FRONTEND_BASE_URL}/{sub_type}/{canonical_slug}"


# Default URL builder per resource.type. A type with no entry here has
# no known URL scheme yet, so build_resource_url() returns None for
# it instead of guessing a shape.
_URL_BUILDERS = {
    "authority": _legacy_authority_url,
}

# Canonical URL builder per resource sub-type -- the segment of
# resource_id before the "/" (e.g. "ekadashi" in "ekadashi/yogini").
# This is the single source of truth for a resource's real frontend
# page, and it always wins over the generic per-resource.type builder
# above. To support a new sub-type (festivals, transit, rajyoga,
# reports, ...), register its builder here -- nothing else in this
# module needs to change, and every existing entry is unaffected.
_CANONICAL_URL_BUILDERS = {
    "ekadashi": _ekadashi_canonical_url,
}


def build_resource_url(resource_type, resource_id, lang="en"):
    """
    Derive the canonical production URL for a resource from its
    existing type + id only. Never fabricates a URL for a resource
    type with no known scheme -- returns None instead.
    """
    default_builder = _URL_BUILDERS.get(resource_type)
    if not default_builder or not resource_id:
        return None

    safe_lang = lang if lang in SUPPORTED_LANGS else "en"

    sub_type = resource_id.split("/", 1)[0]
    builder = _CANONICAL_URL_BUILDERS.get(sub_type, default_builder)
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
