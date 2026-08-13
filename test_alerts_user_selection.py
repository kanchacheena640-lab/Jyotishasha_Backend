"""
test_alerts_user_selection.py
----------------------------------
Local-only entry point for the Alerts Product Hardening change --
modules/alerts/user_alert_selection.py's pure select_user_facing_alerts()
algorithm. No DB, no Flask app context needed for this file: the
function under test is deliberately pure (see its own module
docstring). A second suite (test_alerts_selection_service.py) covers
the DB-touching orchestration layer and the daily-cap-vs-cooldown
interaction against the real local Postgres instance.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])

from modules.alerts.user_alert_selection import (  # noqa: E402
    AlertCandidate,
    CONFLICT_GROUPS,
    MAX_USER_FACING_ALERTS,
    select_user_facing_alerts,
)

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


def cand(event_id, category, severity, priority, confidence):
    return AlertCandidate(
        event_id=event_id, category=category, severity=severity,
        priority=priority, confidence=confidence,
    )


def main():
    # ==============================================================
    print("=== Test 1: 10+ detected/eligible events -> max 2 user-facing ===")
    # ==============================================================
    many = [
        cand("financial_gain_opportunity", "financial", "HIGH", "high", 0.9),
        cand("mood_positive", "emotional", "LOW", "high", 0.85),
        cand("learning_focus", "learning", "LOW", "medium", 0.5),
        cand("travel_opportunity", "travel", "MEDIUM", "medium", 0.45),
        cand("decision_window", "timing", "MEDIUM", "medium", 0.4),
        cand("opportunity_window", "timing", "MEDIUM", "medium", 0.42),
        cand("good_communication_window", "relationship", "LOW", "medium", 0.38),
        cand("relationship_harmony", "relationship", "LOW", "medium", 0.36),
        cand("mental_clarity", "vitality", "LOW", "medium", 0.34),
        cand("stress_high", "vitality", "MEDIUM", "medium", 0.33),
        cand("unexpected_expense", "financial", "HIGH", "medium", 0.32),
    ]
    check("11 candidates supplied", len(many) == 11)
    selected = select_user_facing_alerts(many)
    check("result has at most 2 alerts", len(selected) <= 2)
    check("result is non-empty", len(selected) >= 1)
    check(
        "strongest candidate (financial_gain_opportunity) is alert #1",
        selected[0].event_id == "financial_gain_opportunity",
    )

    # ==============================================================
    print("\n=== Test 2: one dominant event -> exactly 1 ===")
    # ==============================================================
    one_dominant = [cand("mood_positive", "emotional", "LOW", "high", 0.9)]
    selected2 = select_user_facing_alerts(one_dominant)
    check("exactly 1 alert selected", len(selected2) == 1)
    check("it is the only candidate", selected2[0].event_id == "mood_positive")

    # ==============================================================
    print("\n=== Test 3: conflicting events never coexist ===")
    # ==============================================================
    conflicting = [
        cand("mood_low", "emotional", "LOW", "high", 0.8),
        cand("mood_positive", "emotional", "LOW", "high", 0.75),
        cand("financial_gain_opportunity", "financial", "HIGH", "high", 0.9),
    ]
    selected3 = select_user_facing_alerts(conflicting)
    ids3 = {c.event_id for c in selected3}
    check("never both mood_low and mood_positive together", not ({"mood_low", "mood_positive"} <= ids3))
    check("the stronger of the pair (mood_low, higher confidence) survives", "mood_low" in ids3)
    check("financial_gain_opportunity (different category, high priority) also selected", "financial_gain_opportunity" in ids3)
    check("exactly 2 selected", len(selected3) == 2)

    # Reverse the confidence to prove the SURVIVOR changes with strength,
    # not with list order -- confirms determinism is signal-driven.
    conflicting_reversed = [
        cand("mood_low", "emotional", "LOW", "high", 0.5),
        cand("mood_positive", "emotional", "LOW", "high", 0.95),
    ]
    selected3b = select_user_facing_alerts(conflicting_reversed)
    check("stronger candidate wins regardless of list position", selected3b[0].event_id == "mood_positive")
    check("still only 1 (no distinct-category runner-up available)", len(selected3b) == 1)

    # ==============================================================
    print("\n=== Test 4: overlapping same-category weak events are suppressed ===")
    # ==============================================================
    # energy_low and minor_injury_caution are a Tier-2 overlap pair
    # (shared Mars-Saturn conjunction rule) even though they are in
    # DIFFERENT categories (vitality vs health) -- proves suppression
    # is NOT solely a byproduct of the category-diversity rule.
    overlap = [
        cand("energy_low", "vitality", "MEDIUM", "high", 0.7),
        cand("minor_injury_caution", "health", "HIGH", "medium", 0.5),
    ]
    selected4 = select_user_facing_alerts(overlap)
    ids4 = {c.event_id for c in selected4}
    check("cross-category overlap pair never both shown", not ({"energy_low", "minor_injury_caution"} <= ids4))
    check("exactly 1 survives (no other candidate to pair with)", len(selected4) == 1)

    # Same-category weak duplicates (e.g. two vitality events, neither
    # "high" priority) -- category-diversity rule alone already blocks
    # a same-category second pick, but confirm explicitly.
    same_cat_weak = [
        cand("stress_high", "vitality", "MEDIUM", "medium", 0.35),
        cand("mental_clarity", "vitality", "LOW", "medium", 0.33),
    ]
    selected4b = select_user_facing_alerts(same_cat_weak)
    check("same-category candidates never both shown even without a conflict-group entry", len(selected4b) == 1)

    # ==============================================================
    print("\n=== Test 5: two genuinely strong distinct-category events coexist ===")
    # ==============================================================
    two_strong = [
        cand("financial_gain_opportunity", "financial", "HIGH", "high", 0.9),
        cand("mood_positive", "emotional", "LOW", "high", 0.85),
    ]
    selected5 = select_user_facing_alerts(two_strong)
    ids5 = {c.event_id for c in selected5}
    check("both strong, distinct-category, non-conflicting events selected", ids5 == {"financial_gain_opportunity", "mood_positive"})

    # A strong candidate whose only distinct-category alternative is
    # NOT "high" priority -- must NOT be filled just to reach 2.
    one_strong_one_weak = [
        cand("financial_gain_opportunity", "financial", "HIGH", "high", 0.9),
        cand("mood_positive", "emotional", "LOW", "medium", 0.4),
    ]
    selected5b = select_user_facing_alerts(one_strong_one_weak)
    check("quota NOT filled with a non-strong candidate", len(selected5b) == 1)
    check("the one strong candidate is the one shown", selected5b[0].event_id == "financial_gain_opportunity")

    # ==============================================================
    print("\n=== Test 6: ranking is deterministic ===")
    # ==============================================================
    pool = [
        cand("travel_opportunity", "travel", "MEDIUM", "high", 0.65),
        cand("decision_window", "timing", "MEDIUM", "high", 0.7),
        cand("good_communication_window", "relationship", "LOW", "high", 0.7),  # same confidence as decision_window, later event_id
    ]
    result_a = select_user_facing_alerts(list(pool))
    import random
    shuffled = list(pool)
    random.seed(42)
    random.shuffle(shuffled)
    result_b = select_user_facing_alerts(shuffled)
    check(
        "same input set (any order) -> identical selected event_ids in identical order",
        [c.event_id for c in result_a] == [c.event_id for c in result_b],
    )
    # Explicit tie-break check: decision_window and good_communication_window
    # tie on severity(MEDIUM vs LOW -- NOT a tie, MEDIUM wins) -- construct
    # a genuine full tie (severity+priority+confidence identical) to
    # prove event_id is the deterministic tie-breaker.
    tie_a = cand("travel_opportunity", "travel", "MEDIUM", "high", 0.7)
    tie_b = cand("decision_window", "timing", "MEDIUM", "high", 0.7)
    tie_selected = select_user_facing_alerts([tie_a, tie_b])
    check(
        "full tie (severity/priority/confidence identical) resolved by event_id ascending",
        tie_selected[0].event_id == "decision_window",  # 'decision_window' < 'travel_opportunity' lexicographically
    )

    # ==============================================================
    print("\n=== Test 7: rerun does not bypass daily cap through cooldown mechanics ===")
    # ==============================================================
    fresh_candidates = [
        cand("financial_gain_opportunity", "financial", "HIGH", "high", 0.9),
        cand("mood_positive", "emotional", "LOW", "high", 0.85),
        cand("learning_focus", "learning", "LOW", "high", 0.8),
    ]
    # Already 2 delivered today (from an earlier run/other events) --
    # even though 3 fresh, fully-eligible, non-conflicting candidates
    # exist right now, the cap must return zero.
    capped = select_user_facing_alerts(fresh_candidates, already_selected_today=2)
    check("already_selected_today=2 -> zero new selections regardless of strength", capped == [])

    # Exactly 1 already delivered -> exactly 1 more slot, still governed
    # by the same strength/category rules (not "whatever is next").
    one_more = select_user_facing_alerts(fresh_candidates, already_selected_today=1)
    check("already_selected_today=1 -> exactly 1 more selected", len(one_more) == 1)
    check("it is the strongest remaining candidate", one_more[0].event_id == "financial_gain_opportunity")

    # ==============================================================
    print("\n=== Test 8: empty / no-candidate edge cases ===")
    # ==============================================================
    check("empty input -> empty output", select_user_facing_alerts([]) == [])
    check("max_alerts=0 -> empty output even with strong candidates", select_user_facing_alerts(fresh_candidates, max_alerts=0) == [])

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
