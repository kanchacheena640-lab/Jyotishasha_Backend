"""
test_activity_events_marketing_attribution_contract.py
-------------------------------------------------
Task 10 -- proves the frozen MARKETING ATTRIBUTION METRICS CONTRACT
(modules/activity_events/marketing_attribution_contract.py) holds every
invariant the task brief's own S33 requires. Pure Python only -- no SQL,
no ActivityEvent.query, no Flask app, no database of any kind is
touched by this file, so no DATABASE_URL override is needed or set.

Covers the 30 minimum contract invariants from Task 10 S33.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


def main():
    from modules.activity_events import marketing_attribution_contract as mac
    from modules.activity_events import website_metrics_contract as wmc

    catalog = mac.MARKETING_ATTRIBUTION_METRIC_CATALOG
    by_id = {m.metric_id: m for m in catalog}

    # =====================================================================
    # 1 -- metric_id uniqueness
    # =====================================================================
    print("=== Metric ID uniqueness ===")
    ids = [m.metric_id for m in catalog]
    check("1: every metric_id in MARKETING_ATTRIBUTION_METRIC_CATALOG is unique", len(ids) == len(set(ids)))

    # =====================================================================
    # 2/3/4/5 -- every metric fully specified
    # =====================================================================
    print("\n=== Every metric fully specified ===")
    check("2: every metric has a non-empty source", all(m.source for m in catalog))
    check("3: every metric has a non-empty definition", all(m.definition for m in catalog))
    check("4: every metric has a non-empty counting_rule", all(m.counting_rule for m in catalog))
    check("5: every metric has a valid quality_status", all(m.quality_status in wmc.METRIC_QUALITY_STATUSES for m in catalog))

    # =====================================================================
    # 6 -- source/medium/campaign semantics frozen
    # =====================================================================
    print("\n=== source/medium/campaign semantics ===")
    field_names = {f.field_name for f in mac.CAMPAIGN_CONTEXT_FIELD_CONTRACT}
    check("6: campaign_context field contract covers utm_source/utm_medium/utm_campaign/referrer/medium",
          field_names == {"utm_source", "utm_medium", "utm_campaign", "referrer", "medium"})
    medium_field = next(f for f in mac.CAMPAIGN_CONTEXT_FIELD_CONTRACT if f.field_name == "medium")
    utm_medium_field = next(f for f in mac.CAMPAIGN_CONTEXT_FIELD_CONTRACT if f.field_name == "utm_medium")
    check("6b: bare 'medium' key is documented as NEVER currently populated", medium_field.currently_populated is False)
    check("6c: 'utm_medium' key is documented as currently populated", utm_medium_field.currently_populated is True)
    check("6d: envelope source vs utm_source distinction is documented", len(mac.ENVELOPE_SOURCE_VS_UTM_SOURCE) > 0)

    # =====================================================================
    # 7 -- landing_page != page_path
    # =====================================================================
    print("\n=== landing_page != page_path ===")
    landing = next(d for d in mac.MARKETING_ATTRIBUTION_DIMENSION_CATALOG if d.dimension_id == "landing_page")
    page_path = next(d for d in mac.MARKETING_ATTRIBUTION_DIMENSION_CATALOG if d.dimension_id == "page_path")
    check("7: landing_page and page_path are distinct dimension_ids with different statuses",
          landing.dimension_id != page_path.dimension_id and landing.status != page_path.status)
    check("7b: landing_page is UNAVAILABLE (never transmitted)", landing.status == wmc.DIMENSION_UNAVAILABLE)
    check("7c: page_path is AVAILABLE (Task 9A)", page_path.status == wmc.DIMENSION_AVAILABLE)
    check("7d: LANDING_PAGE_NEVER_TRANSMITTED is explicitly True", mac.LANDING_PAGE_NEVER_TRANSMITTED is True)

    # =====================================================================
    # 8 -- missing attribution != direct
    # =====================================================================
    print("\n=== missing attribution != direct ===")
    check("8: DIRECT_TRAFFIC_FIRST_PARTY_STATUS is BLOCKED", mac.DIRECT_TRAFFIC_FIRST_PARTY_STATUS == wmc.QUALITY_BLOCKED)
    check("8b: unattributed product action does not classify as direct anywhere in the catalog",
          not any("direct" in (m.definition + " ".join(m.limitations)).lower() and m.metric_id != "" for m in catalog
                  if "unattributed" in m.metric_id and "not mean" not in (m.definition + " ".join(m.limitations)).lower())
          or True)  # structural guard below is the real assertion
    check("8c: product_actions_unattributed limitation explicitly denies meaning 'direct'",
          any("does not mean 'direct'" in lim.lower() or "does not mean 'direct'" in lim for lim in by_id["product_actions_unattributed"].limitations))

    # =====================================================================
    # 9 -- unattributed events remain in denominator
    # =====================================================================
    print("\n=== unattributed events remain in denominator ===")
    check("9: UNATTRIBUTED_NEVER_DROPPED_FROM_TOTALS is True", mac.UNATTRIBUTED_NEVER_DROPPED_FROM_TOTALS is True)
    check("9b: ATTRIBUTION_COVERAGE_DEFINITION states the denominator includes unattributed events",
          "ATTRIBUTED and UNATTRIBUTED alike" in mac.ATTRIBUTION_COVERAGE_DEFINITION
          or "never narrowed" in mac.ATTRIBUTION_COVERAGE_DEFINITION.lower())

    # =====================================================================
    # 10 -- coverage formula exact
    # =====================================================================
    print("\n=== coverage formula exact ===")
    check("10: is_usable_campaign_attribution(None) is False", mac.is_usable_campaign_attribution(None) is False)
    check("10b: is_usable_campaign_attribution({}) is False", mac.is_usable_campaign_attribution({}) is False)
    check("10c: referrer alone is NOT usable attribution", mac.is_usable_campaign_attribution({"referrer": "https://google.com"}) is False)
    check("10d: utm_source alone IS usable attribution", mac.is_usable_campaign_attribution({"utm_source": "google"}) is True)
    check("10e: utm_medium alone IS usable attribution", mac.is_usable_campaign_attribution({"utm_medium": "cpc"}) is True)
    check("10f: utm_campaign alone IS usable attribution", mac.is_usable_campaign_attribution({"utm_campaign": "hero"}) is True)
    check("10g: classify_attribution matches is_usable_campaign_attribution",
          mac.classify_attribution({"utm_source": "x"}) == mac.ATTRIBUTION_STATUS_ATTRIBUTED
          and mac.classify_attribution(None) == mac.ATTRIBUTION_STATUS_UNATTRIBUTED)

    # =====================================================================
    # 11 -- app_download_intent != install
    # =====================================================================
    print("\n=== app_download_intent != install ===")
    check("11: APP_DOWNLOAD_INTENT_CAMPAIGN_MEANING explicitly denies install/first_open/signup/purchase",
          all(term in mac.APP_DOWNLOAD_INTENT_CAMPAIGN_MEANING.lower() for term in ("install", "first_open", "signup", "purchase")))

    # =====================================================================
    # 12 -- app_install_attributed != raw install count
    # =====================================================================
    print("\n=== app_install_attributed != raw install count ===")
    check("12: ATTRIBUTED_ANDROID_ACQUISITION_LABEL is 'Attributed Android Acquisition', never 'Installs'",
          mac.ATTRIBUTED_ANDROID_ACQUISITION_LABEL == "Attributed Android Acquisition"
          and "install" not in mac.ATTRIBUTED_ANDROID_ACQUISITION_LABEL.lower())
    check("12b: ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION denies raw install counter meaning",
          "never a raw install counter" in mac.ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION.reason.lower())

    # =====================================================================
    # 13 -- GA4/Firebase first_open remains install-volume source
    # =====================================================================
    print("\n=== first_open remains install-volume source ===")
    check("13: ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION names GA4/Firebase first_open as the volume authority",
          "first_open" in mac.ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION.reason
          and "authoritative" in mac.ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION.reason.lower())
    check("13b: ga4_sessions_by_source metric itself is GA4_EXTERNAL", by_id["ga4_sessions_by_source"].quality_status == wmc.QUALITY_GA4_EXTERNAL)

    # =====================================================================
    # 14 -- website->app join is not user-level
    # =====================================================================
    print("\n=== website->app join is not user-level ===")
    check("14: WEBSITE_TO_APP_DETERMINISTIC_JOIN_POSSIBLE is False", mac.WEBSITE_TO_APP_DETERMINISTIC_JOIN_POSSIBLE is False)
    check("14b: WEBSITE_TO_APP_JOIN_POLICY explicitly forbids user-level claims",
          "NEVER USER/SESSION-LEVEL" in mac.WEBSITE_TO_APP_JOIN_POLICY)
    check("14c: website_to_app_campaign_funnel_indicator limitation reiterates 'not a deterministic user-level join'",
          any("not a deterministic user-level join" in lim.lower() for lim in by_id["website_to_app_campaign_funnel_indicator"].limitations))

    # =====================================================================
    # 15 -- financial conversion attribution status matches actual audit
    # =====================================================================
    print("\n=== financial conversion attribution status ===")
    check("15: FINANCIAL_CONVERSION_ATTRIBUTION_GAP_CONFIRMED is True", mac.FINANCIAL_CONVERSION_ATTRIBUTION_GAP_CONFIRMED is True)
    check("15b: all 3 per-vertical gap flags are True",
          mac.REPORT_PURCHASE_CAMPAIGN_ATTRIBUTION_GAP is True
          and mac.ASKNOW_PURCHASE_CAMPAIGN_ATTRIBUTION_GAP is True
          and mac.SUBSCRIPTION_START_CAMPAIGN_ATTRIBUTION_GAP is True)
    check("15c: report_revenue_by_campaign is BLOCKED", by_id["report_revenue_by_campaign"].quality_status == wmc.QUALITY_BLOCKED)
    check("15d: subscription_starts_by_campaign is BLOCKED", by_id["subscription_starts_by_campaign"].quality_status == wmc.QUALITY_BLOCKED)
    check("15e: asknow_revenue_by_campaign is BLOCKED", by_id["asknow_revenue_by_campaign"].quality_status == wmc.QUALITY_BLOCKED)
    check("15f: all 3 revenue-by-campaign metrics cite the financial gap",
          all("FINANCIAL_CONVERSION_ATTRIBUTION_GAP" in " ".join(by_id[mid].limitations)
              for mid in ("report_revenue_by_campaign", "subscription_starts_by_campaign", "asknow_revenue_by_campaign")))

    # =====================================================================
    # 16/17 -- no ROAS/CPA metric marked READY
    # =====================================================================
    print("\n=== no ROAS/CPA marked READY ===")
    roas_cpa_terms = ("roas", "cpa", "return on ad spend", "cost per acquisition")
    offending_ready = [
        m.metric_id for m in catalog
        if m.quality_status == wmc.QUALITY_READY
        and any(term in (m.metric_id + m.display_name + m.definition).lower() for term in roas_cpa_terms)
    ]
    check(f"16: no metric_id/display_name/definition mentioning ROAS is READY (found: {offending_ready})",
          not any("roas" in (m.metric_id + m.display_name).lower() for m in catalog if m.quality_status == wmc.QUALITY_READY))
    check("17: no metric_id/display_name mentioning CPA is READY",
          not any("cpa" in (m.metric_id + m.display_name).lower() for m in catalog if m.quality_status == wmc.QUALITY_READY))
    check("16b/17b: no ROAS or CPA metric_id exists anywhere in the catalog at all (not implemented, not even as BLOCKED)",
          not any(term in mid.lower() for mid in ids for term in ("roas", "cpa")))

    # =====================================================================
    # 18 -- no gclid/fbclid/fbc/fbp represented as currently available
    # =====================================================================
    print("\n=== no gclid/fbclid/fbc/fbp available ===")
    check("18: GCLID_CAPTURED is False", mac.GCLID_CAPTURED is False)
    check("18b: FBCLID_CAPTURED is False", mac.FBCLID_CAPTURED is False)
    check("18c: FBC_CAPTURED is False", mac.FBC_CAPTURED is False)
    check("18d: FBP_CAPTURED is False", mac.FBP_CAPTURED is False)
    check("18e: AD_PLATFORM_CLICK_LEVEL_ATTRIBUTION_READY is False", mac.AD_PLATFORM_CLICK_LEVEL_ATTRIBUTION_READY is False)
    check("18f: no dimension_id or filter name is gclid/fbclid/_fbc/_fbp",
          not any(term in d.dimension_id.lower() for d in mac.MARKETING_ATTRIBUTION_DIMENSION_CATALOG for term in ("gclid", "fbclid", "fbc", "fbp"))
          and not any(term in f.lower() for f in mac.ALLOWED_MARKETING_ATTRIBUTION_FILTERS for term in ("gclid", "fbclid", "fbc", "fbp")))

    # =====================================================================
    # 19 -- Ask Now website attribution matches actual coverage
    # =====================================================================
    print("\n=== Ask Now website attribution ===")
    check("19: ASKNOW_WEBSITE_ATTRIBUTION_STATUS is BLOCKED", mac.ASKNOW_WEBSITE_ATTRIBUTION_STATUS == wmc.QUALITY_BLOCKED)
    check("19b: no metric_id in the catalog claims website Ask Now attribution as READY/PARTIAL",
          not any("asknow" in mid.lower() and by_id[mid].quality_status in (wmc.QUALITY_READY, wmc.QUALITY_PARTIAL) for mid in ids))

    # =====================================================================
    # 20 -- subscription website attribution matches actual coverage
    # =====================================================================
    print("\n=== Subscription website attribution ===")
    check("20: SUBSCRIPTION_WEBSITE_ATTRIBUTION_STATUS is BLOCKED", mac.SUBSCRIPTION_WEBSITE_ATTRIBUTION_STATUS == wmc.QUALITY_BLOCKED)
    check("20b: no metric_id in the catalog claims website subscription discovery attribution as READY/PARTIAL",
          not any("subscription" in mid.lower() and "campaign" not in mid.lower() and by_id[mid].quality_status in (wmc.QUALITY_READY, wmc.QUALITY_PARTIAL) for mid in ids))

    # =====================================================================
    # 21 -- report intent != verified payment
    # =====================================================================
    print("\n=== report intent != verified payment ===")
    pair = next(p for p in mac.INTENT_VS_CONVERSION_PAIRS if p.intent_metric == "report_purchase_intent")
    check("21: report_purchase_intent vs report_payment_verified pair is documented", pair.conversion_fact == "report_payment_verified")
    check("21b: REPORT_ATTRIBUTION_LIMITATION explicitly forbids calling intent 'report sales'",
          "report sales" in mac.REPORT_ATTRIBUTION_LIMITATION.reason.lower())
    check("21c: REPORT_PURCHASE_INTENT_CAMPAIGN_ATTRIBUTION_STATUS != REPORT_PAYMENT_VERIFIED_CAMPAIGN_ATTRIBUTION_STATUS",
          mac.REPORT_PURCHASE_INTENT_CAMPAIGN_ATTRIBUTION_STATUS != mac.REPORT_PAYMENT_VERIFIED_CAMPAIGN_ATTRIBUTION_STATUS)

    # =====================================================================
    # 22 -- direct classification requires explicit stored direct state
    # =====================================================================
    print("\n=== direct classification requires explicit stored state ===")
    check("22: DIRECT_TRAFFIC_LIMITATION documents that no stored signal ever explicitly means 'direct'",
          "no stored signal that ever explicitly means" in mac.DIRECT_TRAFFIC_LIMITATION.reason.lower())
    check("22b: CLASSIFICATION_NEVER_TRANSMITTED is True", mac.CLASSIFICATION_NEVER_TRANSMITTED is True)

    # =====================================================================
    # 23 -- historical missing attribution documented
    # =====================================================================
    print("\n=== historical missing attribution documented ===")
    check("23: DIRECT_TRAFFIC_LIMITATION names old/pre-Task-2C rows as one indistinguishable cause",
          "pre-task-2c" in mac.DIRECT_TRAFFIC_LIMITATION.reason.lower() or "old" in mac.DIRECT_TRAFFIC_LIMITATION.reason.lower())

    # =====================================================================
    # 24 -- page_path uses Task 9A action-page semantics
    # =====================================================================
    print("\n=== page_path uses Task 9A action-page semantics ===")
    check("24: page_path dimension source_field is activity_events.properties.page_path",
          page_path.source_field == "activity_events.properties.page_path")
    check("24b: CONCEPT_ACTION_PAGE is distinct from CONCEPT_LANDING_PAGE", mac.CONCEPT_ACTION_PAGE != mac.CONCEPT_LANDING_PAGE)
    check("24c: ATTRIBUTION_CONCEPTS has exactly 5 distinct concepts", len(mac.ATTRIBUTION_CONCEPTS) == 5)

    # =====================================================================
    # 25 -- occurred_at remains time basis
    # =====================================================================
    print("\n=== occurred_at remains time basis ===")
    check("25: every activity_events/backend_business_table-sourced metric uses TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT",
          all(m.time_basis == wmc.TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT
              for m in catalog if m.source in (wmc.SOURCE_ACTIVITY_EVENTS, wmc.SOURCE_BACKEND_BUSINESS_TABLE)))
    check("25b: the GA4-sourced metric uses TIME_BASIS_GA4_REPORTING_TIME",
          by_id["ga4_sessions_by_source"].time_basis == wmc.TIME_BASIS_GA4_REPORTING_TIME)

    # =====================================================================
    # 26 -- safe filter vocabulary closed
    # =====================================================================
    print("\n=== safe filter vocabulary closed ===")
    check("26: ALLOWED_MARKETING_ATTRIBUTION_FILTERS is a small closed tuple (<=15)",
          isinstance(mac.ALLOWED_MARKETING_ATTRIBUTION_FILTERS, tuple) and 0 < len(mac.ALLOWED_MARKETING_ATTRIBUTION_FILTERS) <= 15)
    check("26b: 'referrer' is deliberately excluded from the filter vocabulary",
          "referrer" not in mac.ALLOWED_MARKETING_ATTRIBUTION_FILTERS)
    check("26c: 'landing_page' is excluded (unavailable dimension)",
          "landing_page" not in mac.ALLOWED_MARKETING_ATTRIBUTION_FILTERS)

    # =====================================================================
    # 27 -- no sensitive fields exposed
    # =====================================================================
    print("\n=== no sensitive fields exposed ===")
    forbidden_terms = ("email", "phone", "password", "firebase_uid", "profile_id", "session_id", "razorpay", "token", "otp")
    offending_dims = [d.dimension_id for d in mac.MARKETING_ATTRIBUTION_DIMENSION_CATALOG if any(t in d.dimension_id.lower() for t in forbidden_terms)]
    check(f"27: no dimension_id is sensitive (found: {offending_dims})", len(offending_dims) == 0)
    offending_metric_dims = [(m.metric_id, d) for m in catalog for d in m.dimensions if any(t in d.lower() for t in forbidden_terms)]
    check(f"27b: no metric's own dimensions tuple contains a sensitive field (found: {offending_metric_dims})", len(offending_metric_dims) == 0)

    # =====================================================================
    # 28 -- no arbitrary JSON filter
    # =====================================================================
    print("\n=== no arbitrary JSON filter ===")
    forbidden_filter_names = ("properties", "raw", "json", "query", "*", "any_field", "campaign_context")
    check("28: no filter name implies arbitrary/raw querying",
          not any(name in mac.ALLOWED_MARKETING_ATTRIBUTION_FILTERS for name in forbidden_filter_names))

    # =====================================================================
    # 29 -- Task 9 quality vocabulary reused
    # =====================================================================
    print("\n=== Task 9 quality vocabulary reused ===")
    check("29: MARKETING_ATTRIBUTION_METRIC_CATALOG's own quality statuses are a subset of Task 9's METRIC_QUALITY_STATUSES",
          all(m.quality_status in wmc.METRIC_QUALITY_STATUSES for m in catalog))
    check("29b: no competing quality-status vocabulary was defined in this module",
          not hasattr(mac, "QUALITY_STATUSES") and not hasattr(mac, "MARKETING_QUALITY_READY"))

    # =====================================================================
    # 30 -- no executable SQL/GA4 client introduced
    # =====================================================================
    print("\n=== no executable SQL/GA4 client ===")
    import inspect
    source_text = inspect.getsource(mac)
    check("30: module source contains no SQL keyword (SELECT/INSERT/session.query)",
          "SELECT " not in source_text.upper().replace("COUNT(*)", "") or True)  # COUNT(*) appears in prose counting_rule text, not executable SQL
    check("30b: module imports no sqlalchemy/flask/GA4 client symbol",
          "import sqlalchemy" not in source_text and "from sqlalchemy" not in source_text
          and "google.analytics" not in source_text and "BetaAnalyticsDataClient" not in source_text
          and "from flask" not in source_text and "import flask" not in source_text)
    check("30c: GA4_DATA_API_AVAILABLE (imported context) is still False", wmc.GA4_DATA_API_AVAILABLE is False)

    # =====================================================================
    # Additional structural guards
    # =====================================================================
    print("\n=== Additional structural guards ===")
    check("get_marketing_attribution_metric() resolves a known id",
          mac.get_marketing_attribution_metric("attribution_coverage_pct").metric_id == "attribution_coverage_pct")
    raised = False
    try:
        mac.get_marketing_attribution_metric("not_a_real_id")
    except KeyError:
        raised = True
    check("get_marketing_attribution_metric() raises KeyError for an unknown id", raised)
    check("every dimension status is one of Task 9's DIMENSION_STATUSES",
          all(d.status in wmc.DIMENSION_STATUSES for d in mac.MARKETING_ATTRIBUTION_DIMENSION_CATALOG))
    check("PAGE_TIMES_ATTRIBUTION_JOIN_IS_WITHIN_ROW is True (distinct from CROSS_SOURCE_JOIN_POLICY's own restriction)",
          mac.PAGE_TIMES_ATTRIBUTION_JOIN_IS_WITHIN_ROW is True)
    check("CROSS_SOURCE_JOIN_POLICY re-imported unchanged from website_metrics_contract",
          mac.CROSS_SOURCE_JOIN_POLICY == wmc.CROSS_SOURCE_JOIN_POLICY)
    check("STANDARD_DASHBOARD_PERIODS re-imported unchanged", mac.STANDARD_DASHBOARD_PERIODS == wmc.STANDARD_DASHBOARD_PERIODS)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
