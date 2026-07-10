# Regression checks for services/event_resolver.py resource.url generation.
# Pure functions, no DB / Flask app context needed -- run with:
#   python test_event_resolver.py

from services.event_resolver import resolve_resource, build_resource_url


class FakeEvent:
    def __init__(self, meta):
        self.meta = meta


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    return condition


results = []

# 1. The reported bug: Yogini Ekadashi must resolve to the canonical
#    frontend page, not the legacy truncated-slug URL.
yogini = resolve_resource(FakeEvent({"type": "ekadashi", "slug": "yogini"}))
results.append(check(
    "Yogini Ekadashi resource.id unchanged",
    yogini["id"] == "ekadashi/yogini"
))
results.append(check(
    "Yogini Ekadashi resource.type unchanged",
    yogini["type"] == "authority"
))
results.append(check(
    "Yogini Ekadashi resource.url is canonical",
    yogini["url"] == "https://www.jyotishasha.com/ekadashi/yogini-ekadashi"
))

# 2. Adhik-maas names already contain "Ekadashi" in the slug -- must not
#    be double-suffixed.
padmini = resolve_resource(FakeEvent({"type": "ekadashi", "slug": "padmini-ekadashi"}))
results.append(check(
    "Adhik-maas slug is not double-suffixed",
    padmini["url"] == "https://www.jyotishasha.com/ekadashi/padmini-ekadashi"
))

# 3. Other resource sub-types are untouched by the ekadashi-specific fix
#    (legacy scheme, unchanged from before this change).
pradosh = resolve_resource(FakeEvent({"type": "pradosh", "slug": "pradosh-vrat"}))
results.append(check(
    "Non-ekadashi resource.url keeps the legacy scheme (English has no /en/)",
    pradosh["url"] == "https://jyotishasha.com/pradosh/pradosh-vrat"
))

# 4. Events with no slug/type still resolve to None (unchanged contract).
results.append(check(
    "Event without slug/type resolves to None",
    resolve_resource(FakeEvent({})) is None
))

# 5. Unknown resource_type still yields no fabricated URL.
results.append(check(
    "Unknown resource_type returns no URL",
    build_resource_url("unknown_type", "ekadashi/yogini") is None
))

# 6. lang="hi" still falls back correctly for the legacy scheme, and is
#    ignored (no path segment) for the ekadashi canonical scheme.
pradosh_hi = resolve_resource(FakeEvent({"type": "pradosh", "slug": "pradosh-vrat"}), lang="hi")
results.append(check(
    "Legacy scheme still honors lang",
    pradosh_hi["url"] == "https://jyotishasha.com/hi/pradosh/pradosh-vrat"
))

yogini_hi = resolve_resource(FakeEvent({"type": "ekadashi", "slug": "yogini"}), lang="hi")
results.append(check(
    "Ekadashi canonical URL has no lang segment",
    yogini_hi["url"] == "https://www.jyotishasha.com/ekadashi/yogini-ekadashi"
))

if all(results):
    print(f"\n{len(results)}/{len(results)} checks passed")
else:
    print(f"\n{sum(results)}/{len(results)} checks passed")
    raise SystemExit(1)
