"""
test_report_ai_client.py
-------------------------------------------------
Q3 Batch 0 -- shared paid-report AI client verification.

No real OpenAI call -- the client's own `chat.completions.create` is
monkeypatched throughout (a real network call is reserved for the
separate, explicitly-optional controlled smoke test this task also
asks for, run manually, never as part of this suite). No DB/Flask
dependency -- this module has none.

Covers:
  A. The shared model is exactly "gpt-5.6-luna" (app_config.py's
     PAID_REPORT_AI_MODEL, the one source of truth).
  B. No custom `temperature` is ever sent.
  C. Usage capture -- input/output/total tokens + duration, taken from
     the real OpenAI response shape (response.usage.*).
  D. Missing `usage` on the response degrades to None fields, never a
     fabricated number.
  E. No automatic fallback to gpt-4o-mini (or any other model) on
     failure -- the exception raised by the underlying call propagates
     unchanged, un-retried, un-downgraded.
  F. No prompt/response content is embedded in anything this module
     logs (the module logs nothing itself -- content only ever leaves
     via the returned ReportAICompletion.content field, which the
     caller, not this module, is responsible for never logging).
"""

import sys
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app_config import PAID_REPORT_AI_MODEL
import modules.payments.report_ai_client as report_ai_client

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


def _fake_response(content="A generated report.", prompt_tokens=120, completion_tokens=430, total_tokens=550, with_usage=True):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    if with_usage:
        usage = MagicMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        usage.total_tokens = total_tokens
        response.usage = usage
    else:
        response.usage = None
    return response


# =================================================================
print("=== A: shared model is exactly gpt-5.6-luna ===")
# =================================================================
check("A: app_config.PAID_REPORT_AI_MODEL is exactly 'gpt-5.6-luna'", PAID_REPORT_AI_MODEL == "gpt-5.6-luna")
check("A: report_ai_client imports the SAME constant (single source of truth, no duplicate literal)",
      report_ai_client.PAID_REPORT_AI_MODEL is PAID_REPORT_AI_MODEL)

# =================================================================
print("\n=== B/C: model + usage capture, no custom temperature ===")
# =================================================================
report_ai_client._client = None  # reset the lazy singleton for a clean test
with patch("modules.payments.report_ai_client._get_client") as mock_get_client:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = _fake_response()

    result = report_ai_client.generate_report_completion("some prompt")

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    check("B: model sent to OpenAI is exactly gpt-5.6-luna", call_kwargs.get("model") == "gpt-5.6-luna")
    check("B: no 'temperature' kwarg is ever sent (Luna rejects a custom value)", "temperature" not in call_kwargs)
    check("C: result.content is the response text, stripped", result.content == "A generated report.")
    check("C: result.model matches PAID_REPORT_AI_MODEL", result.model == "gpt-5.6-luna")
    check("C: result.input_tokens captured from response.usage.prompt_tokens", result.input_tokens == 120)
    check("C: result.output_tokens captured from response.usage.completion_tokens", result.output_tokens == 430)
    check("C: result.total_tokens captured from response.usage.total_tokens", result.total_tokens == 550)
    check("C: result.duration_seconds is a real, non-negative float", isinstance(result.duration_seconds, float) and result.duration_seconds >= 0)

# =================================================================
print("\n=== D: missing usage degrades to None, never fabricated ===")
# =================================================================
with patch("modules.payments.report_ai_client._get_client") as mock_get_client:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = _fake_response(with_usage=False)

    result = report_ai_client.generate_report_completion("some prompt")
    check("D: input_tokens is None when response.usage is absent (never fabricated)", result.input_tokens is None)
    check("D: output_tokens is None when response.usage is absent", result.output_tokens is None)
    check("D: total_tokens is None when response.usage is absent", result.total_tokens is None)
    check("D: content is still returned correctly even without usage", result.content == "A generated report.")

# =================================================================
print("\n=== E: no automatic fallback on failure ===")
# =================================================================
with patch("modules.payments.report_ai_client._get_client") as mock_get_client:
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.side_effect = RuntimeError("simulated Luna outage")

    try:
        report_ai_client.generate_report_completion("some prompt")
        check("E: a Luna call failure raises (never swallowed/retried against another model)", False)
    except RuntimeError as exc:
        check("E: a Luna call failure raises (never swallowed/retried against another model)", str(exc) == "simulated Luna outage")

    check("E: exactly one call was attempted -- no retry-with-different-model loop",
          mock_client.chat.completions.create.call_count == 1)
    check("E: the single call attempted still used gpt-5.6-luna, never a fallback model",
          mock_client.chat.completions.create.call_args.kwargs.get("model") == "gpt-5.6-luna")

# =================================================================
print("\n=== F: no fallback model literal exists anywhere in this module ===")
# =================================================================
_source = open("modules/payments/report_ai_client.py", encoding="utf-8").read()
# Precise checks: "gpt-4o-mini" DOES appear in this file's own
# docstring prose (explaining the anti-pattern this module refuses to
# implement, by name) -- what must never exist is an actual model=
# literal invoking it, or a real try/except block around the call.
check("F: no 'model=\"gpt-4o-mini\"' (or single-quoted) literal invocation exists anywhere",
      'model="gpt-4o-mini"' not in _source and "model='gpt-4o-mini'" not in _source)
_function_body = _source.split("def generate_report_completion", 1)[1]
check("F: generate_report_completion()'s own body contains no 'try:' block (nothing here catches-and-falls-back)",
      "try:" not in _function_body)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
