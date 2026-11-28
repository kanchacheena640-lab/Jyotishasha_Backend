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

# 3. Sub-types without a canonical builder keep the legacy scheme
#    (unchanged from before; "navratri" has no canonical builder).
legacy = resolve_resource(FakeEvent({"type": "navratri", "slug": "navratri"}))
results.append(check(
    "Non-canonical resource.url keeps the legacy scheme (English has no /en/)",
    legacy["url"] == "https://jyotishasha.com/navratri/navratri"
))

# 3b. Pradosh now resolves to the live evergreen page (was a legacy 404 URL).
pradosh = resolve_resource(FakeEvent({"type": "pradosh", "slug": "pradosh-vrat"}))
pradosh_hi_live = resolve_resource(FakeEvent({"type": "pradosh", "slug": "pradosh-vrat"}), lang="hi")
results.append(check(
    "Pradosh resource.url is the live /panchang/pradosh page (EN and HI)",
    pradosh["url"] == "https://www.jyotishasha.com/panchang/pradosh"
    and pradosh_hi_live["url"] == "https://www.jyotishasha.com/hi/panchang/pradosh"
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
legacy_hi = resolve_resource(FakeEvent({"type": "navratri", "slug": "navratri"}), lang="hi")
results.append(check(
    "Legacy scheme still honors lang",
    legacy_hi["url"] == "https://jyotishasha.com/hi/navratri/navratri"
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
