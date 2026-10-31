"""Authoritative Google Play one-time product policy for paid reports."""

STANDARD_REPORT_PRODUCT_ID = "reports99"          # standard reports since the Rs51 -> Rs99 change
LEGACY_STANDARD_REPORT_PRODUCT_ID = "reports51"   # older app versions (and any Rs51 report)
RELATIONSHIP_REPORT_SLUG = "relationship_future_report"
RELATIONSHIP_REPORT_PRODUCT_ID = "relationship_report199"
STANDARD_GENERATOR = "standard_v1"

# What Google actually charges for each Play product. A Google Play order records this, not the registry price,
# so an old-app reports51 purchase after the Rs99 switch (or a reports99 one before it) is recorded as charged.
PLAY_PRODUCT_AMOUNT_PAISE = {
    LEGACY_STANDARD_REPORT_PRODUCT_ID: 5100,
    STANDARD_REPORT_PRODUCT_ID: 9900,
    RELATIONSHIP_REPORT_PRODUCT_ID: 19900,
}


def expected_report_product_id(report_slug: str, price_rupees: int) -> str:
    """Return the Play product for this registry product's price tier."""
    if report_slug == RELATIONSHIP_REPORT_SLUG:
        if price_rupees != 199:
            raise ValueError("Relationship report registry price must be INR 199.")
        return RELATIONSHIP_REPORT_PRODUCT_ID
    if price_rupees == 99:
        return STANDARD_REPORT_PRODUCT_ID
    if price_rupees == 51:
        return LEGACY_STANDARD_REPORT_PRODUCT_ID
    raise ValueError(
        f"No Google Play product is configured for report {report_slug!r} "
        f"at INR {price_rupees!r}."
    )


def accepted_report_product_ids(report_slug: str, price_rupees: int, generator: str | None = None) -> frozenset:
    """Play products a verified purchase of this registry product may carry.

    Standard reports honour both reports99 and the legacy reports51 at either registry price, so a purchase that
    Google has already charged is never refused while old and new app versions overlap with the price switch.
    """
    if generator == STANDARD_GENERATOR and report_slug != RELATIONSHIP_REPORT_SLUG and price_rupees in (51, 99):
        return frozenset({STANDARD_REPORT_PRODUCT_ID, LEGACY_STANDARD_REPORT_PRODUCT_ID})
    return frozenset({expected_report_product_id(report_slug, price_rupees)})
