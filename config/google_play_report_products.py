"""Authoritative Google Play one-time product policy for paid reports."""

STANDARD_REPORT_PRODUCT_ID = "reports51"
RELATIONSHIP_REPORT_SLUG = "relationship_future_report"
RELATIONSHIP_REPORT_PRODUCT_ID = "relationship_report199"


def expected_report_product_id(report_slug: str, price_rupees: int) -> str:
    """Return the Play product approved for this canonical registry product."""
    if report_slug == RELATIONSHIP_REPORT_SLUG:
        if price_rupees != 199:
            raise ValueError("Relationship report registry price must be INR 199.")
        return RELATIONSHIP_REPORT_PRODUCT_ID
    if price_rupees == 51:
        return STANDARD_REPORT_PRODUCT_ID
    raise ValueError(
        f"No Google Play product is configured for report {report_slug!r} "
        f"at INR {price_rupees!r}."
    )
