# modules/alerts/exceptions.py

"""
Exception types for the Micro Event Engine. Kept as its own small
hierarchy -- not shared with modules/ai_report_engine/exceptions.py --
because the Alerts Engine is required to be completely independent from
the Premium Generators.
"""


class AlertsEngineError(Exception):
    """Base class for every error the Micro Event Engine raises."""


class EventConfigError(AlertsEngineError):
    """Raised when config/micro_events.json is missing, malformed, or
    fails validation (e.g. an unsupported condition type, or a rule
    weight outside [0, 1])."""


class UnsupportedConditionError(AlertsEngineError):
    """Raised when a rule's `condition` value isn't one the Rule
    Evaluator knows how to check. Adding a genuinely new condition TYPE
    is a code change (modules/alerts/rule_interface.py); adding a new
    EVENT that reuses existing condition types is configuration only."""


class InvalidRuleValueError(AlertsEngineError):
    """Raised when a rule's `condition` type IS recognized, but its
    `value` payload doesn't match the shape that condition requires
    (e.g. `house_in` given a string instead of a list of house numbers,
    or `natal_lord_house_in` missing its `natal_house` key). Both this
    and UnsupportedConditionError are raised by
    rule_interface.validate_rule_condition() -- called once per rule at
    EventRegistry load time (event_registry.py), and re-raised there as
    EventConfigError, so a malformed rule fails at startup instead of
    the first time it's actually evaluated."""
