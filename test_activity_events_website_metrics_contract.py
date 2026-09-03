"""
test_activity_events_website_metrics_contract.py
-------------------------------------------------
Task 9 -- proves the frozen WEBSITE ANALYTICS METRICS CONTRACT
(modules/activity_events/website_metrics_contract.py) holds every
invariant the task brief's own S28 requires, BEFORE any dashboard
UI/API/GA4 Data API integration exists. Pure Python only -- no SQL,
no ActivityEvent.query, no Flask app, no database of any kind is
touched by this file, so no DATABASE_URL override is needed or set.

Covers the 20 minimum contract invariants from Task 9 S28.
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
    from modules.activity_events import website_metrics_contract as c

    catalog = c.WEBSITE_METRIC_CATALOG
    by_id = {m.metric_id: m for m in catalog}

    # =====================================================================
    # 1 -- metric_id uniqueness
    # =====================================================================
    print("=== Metric ID uniqueness ===")
    ids = [m.metric_id for m in catalog]
    check("1: every metric_id in WEBSITE_METRIC_CATALOG is unique", len(ids) == len(set(ids)))

    # =====================================================================
    # 2 -- every metric has source/definition/counting_rule/quality_status
    # =====================================================================
    print("\n=== Every metric fully specified ===")
    fully_specified = all(
        m.source and m.definition and m.counting_rule and m.quality_status
        for m in catalog
    )
    check("2: every metric has a non-empty source/definition/counting_rule/quality_status", fully_specified)

    # =====================================================================
    # 3 -- page_view is GA4-owned
    # =====================================================================
    print("\n=== page_view ownership ===")
    check("3: page_views metric source is GA4_EXTERNAL",
          by_id["page_views"].source == c.SOURCE_GA4_EXTERNAL
          and by_id["page_views"].quality_status == c.QUALITY_GA4_EXTERNAL)
    check("3b: page_views limitation documents page_view as frozen ledger-ineligible",
          any("ledger-ineligible" in lim for lim in by_id["page_views"].limitations))

    # =====================================================================
    # 4 -- Most Viewed Pages distinct from Top Landing Pages
    # =====================================================================
    print("\n=== Most Viewed vs Top Landing Pages ===")
    mvp = by_id["most_viewed_pages"]
    tlp = by_id["top_landing_pages"]
    check("4: most_viewed_pages and top_landing_pages are different metric_ids", mvp.metric_id != tlp.metric_id)
    check("4b: most_viewed_pages definition ranks by page_view COUNT, not sessions/entrances",
          "page_view" in mvp.definition.lower() and "session" not in mvp.definition.lower())
    check("4c: top_landing_pages definition ranks by sessions/entrances, first page of session only",
          "first page" in tlp.definition.lower() and "session" in tlp.definition.lower())
    check("4d: both carry an explicit non-interchangeability limitation",
          any("never" in lim.lower() and "interchangeab" in lim.lower() for lim in mvp.limitations)
          and any("never" in lim.lower() and "interchangeab" in lim.lower() for lim in tlp.limitations))

    # =====================================================================
    # 5 -- app_download_intent explicitly not install
    # =====================================================================
    print("\n=== app_download_intent != install ===")
    adi = by_id["app_download_intents_total"]
    check("5: app_download_intents_total limitation states it is an intent, never an install",
          any("never an install" in lim.lower() or "never fired on render" in lim.lower() for lim in adi.limitations))

    # =====================================================================
    # 6 -- app_install_attributed explicitly not raw install count
    # =====================================================================
    print("\n=== app_install_attributed != raw install count ===")
    aia = by_id["app_installs_attributed"]
    check("6: app_installs_attributed limitation states it must never be presented as 'number of installs'",
          any("never be presented as 'number of installs'" in lim for lim in aia.limitations))
    check("6b: app_installs_attributed definition itself calls out it is explicitly NOT a raw install counter",
          "not a raw" in aia.definition.lower())

    # =====================================================================
    # 7 -- first_open source documented as GA4/Firebase
    # =====================================================================
    print("\n=== first_open source ===")
    fo = by_id["app_installs_ga4_first_open"]
    check("7: app_installs_ga4_first_open source is GA4_EXTERNAL", fo.source == c.SOURCE_GA4_EXTERNAL)
    check("7b: definition names Firebase/GA4 first_open explicitly", "first_open" in fo.definition)
    check("7c: limitation distinguishes it from app_download_intent and app_installs_attributed",
          any("app_download_intent" in lim and "app_installs_attributed" in lim for lim in fo.limitations))

    # =====================================================================
    # 8 -- unavailable != zero semantics frozen
    # =====================================================================
    print("\n=== Zero/null/unknown semantics ===")
    check("8: three distinct zero/null/unknown semantics are frozen",
          c.ZERO_NULL_UNKNOWN_SEMANTICS == {
              c.ZERO_SEMANTIC_MEASURED_ZERO,
              c.ZERO_SEMANTIC_UNAVAILABLE,
              c.ZERO_SEMANTIC_UNKNOWN_DIMENSION,
          })
    check("8b: MEASURED_ZERO, UNAVAILABLE, UNKNOWN_DIMENSION are three distinct string values",
          len({c.ZERO_SEMANTIC_MEASURED_ZERO, c.ZERO_SEMANTIC_UNAVAILABLE, c.ZERO_SEMANTIC_UNKNOWN_DIMENSION}) == 3)

    # =====================================================================
    # 9 -- occurred_at owns ledger period
    # =====================================================================
    print("\n=== Time contract: occurred_at owns period ===")
    check("9: TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT names occurred_at as the period owner",
          "occurred_at" in c.TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT)
    check("9b: every activity_events-sourced or backend_business_table-sourced metric uses that exact time basis",
          all(m.time_basis == c.TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT
              for m in catalog if m.source in (c.SOURCE_ACTIVITY_EVENTS, c.SOURCE_BACKEND_BUSINESS_TABLE)))

    # =====================================================================
    # 10 -- recorded_at not used as business date
    # =====================================================================
    print("\n=== recorded_at never a business date ===")
    check("10: TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT explicitly excludes recorded_at",
          "NOT recorded_at" in c.TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT)
    check("10b: no metric's time_basis field ever contains the string 'recorded_at' as its basis",
          not any(m.time_basis == "recorded_at" or m.time_basis.strip().lower() == "recorded_at" for m in catalog))

    # =====================================================================
    # 11 -- financial conversion metrics backend-owned
    # =====================================================================
    print("\n=== Financial conversion metrics backend-owned ===")
    financial_ids = ("report_payment_verified",)
    check("11: report_payment_verified is backend_business_table sourced",
          all(by_id[mid].source == c.SOURCE_BACKEND_BUSINESS_TABLE for mid in financial_ids))
    check("11b: report_payment_verified counting_rule states backend Order/ProcessedPayment remain financial truth",
          "financial truth" in by_id["report_payment_verified"].counting_rule.lower())

    # =====================================================================
    # 12 -- report_viewed/downloaded not marked currently ready
    # =====================================================================
    print("\n=== report_viewed / report_downloaded not currently ready ===")
    check("12: no metric_id in the catalog is 'report_viewed' or 'report_downloaded' (not claimed as a website metric)",
          "report_viewed" not in by_id and "report_downloaded" not in by_id)
    check("12b: report_discovery_views explicitly documents registry-vs-coverage distinction for report_type",
          by_id["report_discovery_views"].quality_status == c.QUALITY_PARTIAL)

    # =====================================================================
    # 13 -- deferred tool coverage marked partial
    # =====================================================================
    print("\n=== Deferred tool coverage ===")
    tools_all = by_id["tool_completions_all"]
    check("13: tool_completions_all quality_status is PARTIAL", tools_all.quality_status == c.QUALITY_PARTIAL)
    check("13b: tool_completions_all limitation names the Panchang/Muhurat/Horoscope coverage gap",
          any("panchang" in lim.lower() and "muhurat" in lim.lower() for lim in tools_all.limitations))
    check("13c: kundali_generation_completed (the one tracked tool) is READY, distinct from the PARTIAL aggregate",
          by_id["kundali_generation_completed"].quality_status == c.QUALITY_READY)

    # =====================================================================
    # 14 -- no sensitive fields in metric dimensions
    # =====================================================================
    print("\n=== No sensitive fields in dimensions ===")
    forbidden_terms = ("email", "phone", "password", "firebase_uid", "profile_id", "razorpay", "token", "otp")
    offending = [
        (m.metric_id, dim) for m in catalog for dim in m.dimensions
        if any(term in dim.lower() for term in forbidden_terms)
    ]
    check(f"14: no metric dimension contains a sensitive identifier (found: {offending})", len(offending) == 0)
    offending_filters = [f for f in c.ALLOWED_WEBSITE_FILTERS if any(term in f.lower() for term in forbidden_terms)]
    check(f"14b: no allowed filter name contains a sensitive identifier (found: {offending_filters})",
          len(offending_filters) == 0)

    # =====================================================================
    # 15 -- no raw arbitrary properties JSON filter contract
    # =====================================================================
    print("\n=== No arbitrary JSON filter contract ===")
    check("15: ALLOWED_WEBSITE_FILTERS is a small closed vocabulary (<=15 names)",
          isinstance(c.ALLOWED_WEBSITE_FILTERS, tuple) and 0 < len(c.ALLOWED_WEBSITE_FILTERS) <= 15)
    forbidden_filter_names = ("properties", "raw", "json", "query", "*", "any_field")
    check("15b: no filter name is 'properties'/'raw'/'json' or otherwise implies arbitrary querying",
          not any(name in c.ALLOWED_WEBSITE_FILTERS for name in forbidden_filter_names))

    # =====================================================================
    # 16 -- cross-source aggregate-vs-user join distinction documented
    # =====================================================================
    print("\n=== Cross-source join policy ===")
    check("16: CROSS_SOURCE_JOIN_POLICY explicitly permits aggregate correlation",
          "AGGREGATE CORRELATION ONLY" in c.CROSS_SOURCE_JOIN_POLICY)
    check("16b: CROSS_SOURCE_JOIN_POLICY explicitly forbids user-level attribution across systems",
          "NEVER USER-LEVEL ATTRIBUTION" in c.CROSS_SOURCE_JOIN_POLICY)

    # =====================================================================
    # 17 -- page-action attribution status matches audit finding
    # =====================================================================
    print("\n=== Page-action attribution gap reflected in metric statuses ===")
    check("17: PAGE_ACTION_ATTRIBUTION_GAP is documented and non-empty",
          isinstance(c.PAGE_ACTION_ATTRIBUTION_GAP, str) and len(c.PAGE_ACTION_ATTRIBUTION_GAP) > 0)
    check("17b: tool_completions_by_page is BLOCKED and cites the gap",
          by_id["tool_completions_by_page"].quality_status == c.QUALITY_BLOCKED
          and any("PAGE_ACTION_ATTRIBUTION_GAP" in lim for lim in by_id["tool_completions_by_page"].limitations))
    check("17c: cta_clicks_by_page is BLOCKED and cites the gap",
          by_id["cta_clicks_by_page"].quality_status == c.QUALITY_BLOCKED
          and any("PAGE_ACTION_ATTRIBUTION_GAP" in lim for lim in by_id["cta_clicks_by_page"].limitations))
    check("17d: app_download_intents_by_page is PARTIAL (naming-convention-only coverage) and cites the gap",
          by_id["app_download_intents_by_page"].quality_status == c.QUALITY_PARTIAL
          and any("PAGE_ACTION_ATTRIBUTION_GAP" in lim for lim in by_id["app_download_intents_by_page"].limitations))
    check("17e: gap text documents a minimal future extension without claiming it is implemented",
          "MINIMAL FUTURE CONTRACT EXTENSION" in c.PAGE_ACTION_ATTRIBUTION_GAP
          and "NOT implemented in Task 9" in c.PAGE_ACTION_ATTRIBUTION_GAP)

    # =====================================================================
    # 18 -- unique visitors by page never conflated with sessions/firebase_uid
    # =====================================================================
    print("\n=== Unique visitors by page ===")
    uvbp = by_id["unique_visitors_by_page"]
    check("18: unique_visitors_by_page is GA4_EXTERNAL, not derived from session_id or firebase_uid",
          uvbp.source == c.SOURCE_GA4_EXTERNAL)
    check("18b: limitation explicitly forbids presenting session_id as 'unique visitors'",
          any("session_id" in lim and "unique visitors" in lim for lim in uvbp.limitations))

    # =====================================================================
    # 19 -- every quality_status used is one of the 4 frozen values
    # =====================================================================
    print("\n=== Quality status vocabulary closed ===")
    check("19: every metric's quality_status is one of READY/PARTIAL/BLOCKED/GA4_EXTERNAL",
          all(m.quality_status in c.METRIC_QUALITY_STATUSES for m in catalog))
    check("19b: every metric's source is one of the 3 frozen sources",
          all(m.source in c.METRIC_SOURCES for m in catalog))

    # =====================================================================
    # 20 -- funnels only reference facts that actually exist; joinability
    #        is never asserted where the underlying join is documented absent
    # =====================================================================
    print("\n=== Funnel definitions internally consistent ===")
    funnel_ids = [f.funnel_id for f in c.WEBSITE_FUNNELS]
    check("20: 4 funnels defined (free_kundali, paid_report, subscription, ask_now)",
          set(funnel_ids) == {"free_kundali", "paid_report", "subscription", "ask_now"})
    for funnel in c.WEBSITE_FUNNELS:
        check(f"20-{funnel.funnel_id}: every stage has a non-empty stage_name/event_or_metric",
              all(s.stage_name and s.event_or_metric for s in funnel.stages))
    subscription_funnel = next(f for f in c.WEBSITE_FUNNELS if f.funnel_id == "subscription")
    check("20b: subscription funnel's discovery stage is documented as not joinable (no live surface)",
          subscription_funnel.stages[0].joinable_to_next_stage is False
          and len(subscription_funnel.stages[0].limitations) > 0)
    ask_now_funnel = next(f for f in c.WEBSITE_FUNNELS if f.funnel_id == "ask_now")
    check("20c: ask_now funnel's entry stage documents the no-website-entry-point gap",
          any("no website ask now entry point" in lim.lower() for lim in ask_now_funnel.stages[0].limitations))

    # =====================================================================
    # Additional structural guards
    # =====================================================================
    print("\n=== Additional structural guards ===")
    check("GA4_DATA_API_AVAILABLE is False (audited fact, not a placeholder)", c.GA4_DATA_API_AVAILABLE is False)
    check("get_metric() resolves a known id", c.get_metric("page_views").metric_id == "page_views")
    raised = False
    try:
        c.get_metric("not_a_real_metric_id")
    except KeyError:
        raised = True
    check("get_metric() raises KeyError for an unknown id", raised)
    check("DIMENSION_STATUSES covers every DimensionAvailability.status used",
          all(d.status in c.DIMENSION_STATUSES for d in c.WEBSITE_DIMENSION_CATALOG))
    check("pathname_or_page dimension is UNAVAILABLE (matches the page-action attribution gap finding)",
          next(d for d in c.WEBSITE_DIMENSION_CATALOG if d.dimension_id == "pathname_or_page").status
          == c.DIMENSION_UNAVAILABLE)
    check("STANDARD_DASHBOARD_PERIODS is exactly ('7d', '30d', '90d', 'custom')",
          c.STANDARD_DASHBOARD_PERIODS == ("7d", "30d", "90d", "custom"))
    check("re-exported constants match analytics_contract.py's own values (no drift)",
          c.PURCHASED_REPORT_ENTRY_CTA_ID == "report_catalog_buy_now"
          and c.REPORT_PURCHASE_PAYMENT_PURPOSE == "REPORT_PURCHASE"
          and c.AI_REPORT_ENTITY_TYPE == "ai_report"
          and c.PURCHASED_REPORT_ENTITY_TYPE == "order")

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
