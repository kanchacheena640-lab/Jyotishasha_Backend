"""
test_current_phase_timing_contract.py
----------------------------------------
Regression tests for the CURRENT_PHASE / CURRENT_TIMING contract cleanup
(Fix 1 -- removal of the legacy, unused 5th "Current Timing (Next 2-3
Days)" section from all 5 CURRENT_PHASE prompt templates).

Pure, offline, no OpenAI call, no database, no Flask app import needed --
these prompt builders are plain Python string-formatting functions.
Verifies the actual .txt template files on disk (not a copy/mock), so a
regression here means the real, deployed prompt has drifted.

Also verifies backward compatibility: an EXISTING cached CURRENT_PHASE
response containing the old, legacy 5th section (generated before this
fix) still parses/renders with exactly its first 4 headings recognized --
this test never invalidates or needs to regenerate any cache, it only
checks the prompt template's own (forward) contract.
"""

import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.ai_prediction_lab.current_love_phase_prompt_builder import (  # noqa: E402
    build_current_love_phase_prompt,
)
from services.ai_prediction_lab.current_career_phase_prompt_builder import (  # noqa: E402
    build_current_career_phase_prompt,
)
from services.ai_prediction_lab.current_finance_phase_prompt_builder import (  # noqa: E402
    build_current_finance_phase_prompt,
)
from services.ai_prediction_lab.current_health_phase_prompt_builder import (  # noqa: E402
    build_current_health_phase_prompt,
)
from services.ai_prediction_lab.current_family_phase_prompt_builder import (  # noqa: E402
    build_current_family_phase_prompt,
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


_HEADING_PATTERN = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)

_EXPECTED_HEADINGS = [
    "Current Phase",
    "Next Phase Change",
    "Watch Out For",
    "Remedy For This Phase",
]

# One builder call per segment, with the minimal fake context each
# accepts safely (every `.get(key, {})` inside the builder defaults to
# an empty dict; every `.get(x) or "Unknown"` value handles a missing
# key) -- no real astrology/OpenAI call, purely exercising the prompt
# template's own `.format()` call and text content.
_BUILDERS = {
    "LOVE": lambda: build_current_love_phase_prompt(
        birth_date="1990-01-01", birth_time="10:00", birth_place="Delhi, India",
        relationship_dna="Sample DNA text.",
        context={"next_phase_change_date": "2026-09-01"},
        language="en",
    ),
    "CAREER": lambda: build_current_career_phase_prompt(
        birth_date="1990-01-01", birth_time="10:00", birth_place="Delhi, India",
        career_dna="Sample DNA text.",
        context={"next_phase_change_date": "2026-09-01"},
        language="en",
    ),
    "FINANCE": lambda: build_current_finance_phase_prompt(
        birth_date="1990-01-01", birth_time="10:00", birth_place="Delhi, India",
        financial_dna="Sample DNA text.",
        context={"next_phase_change_date": "2026-09-01"},
        language="en",
    ),
    "HEALTH": lambda: build_current_health_phase_prompt(
        birth_date="1990-01-01", birth_time="10:00", birth_place="Delhi, India",
        health_dna="Sample DNA text.",
        context={"next_phase_change_date": "2026-09-01"},
        language="en",
    ),
    "FAMILY": lambda: build_current_family_phase_prompt(
        birth_date="1990-01-01", birth_time="10:00", birth_place="Delhi, India",
        family_dna="Sample DNA text.",
        context={"next_phase_change_date": "2026-09-01"},
        language="en",
    ),
}


def main():
    print("=== Test 1-4: every CURRENT_PHASE segment prompt has exactly the 4 required headings ===")
    for segment, builder in _BUILDERS.items():
        prompt = builder()
        headings = _HEADING_PATTERN.findall(prompt)

        check(f"{segment}: prompt builds without error (no KeyError/format exception)", isinstance(prompt, str) and len(prompt) > 0)
        check(f"{segment}: exactly 4 '## ' headings", len(headings) == 4)
        check(f"{segment}: headings are exactly [Current Phase, Next Phase Change, Watch Out For, Remedy For This Phase], in order", headings == _EXPECTED_HEADINGS)

        print(f"\n=== Test: {segment} -- no legacy Current Timing section ===")
        check(f"{segment}: no 'Current Timing (Next 2-3 Days)' heading present", "Current Timing (Next 2-3 Days)" not in prompt)
        check(f"{segment}: no residual 'FIVE'/'five sections' count language", "five" not in prompt.lower())
        check(f"{segment}: no embedded Quick Tip requirement for CURRENT_PHASE", "Quick tip:" not in prompt and "Quick Tip:" not in prompt)

        print(f"\n=== Test: {segment} -- Next Phase Change (NEXT_PHASE_CHANGE_DATE) untouched ===")
        check(f"{segment}: NEXT_PHASE_CHANGE_DATE is substituted with the real supplied value", "NEXT_PHASE_CHANGE_DATE = 2026-09-01" in prompt)
        check(f"{segment}: 'Around <date>' placeholder line still present in OUTPUT FORMAT", "Around <date>" in prompt)
        check(f"{segment}: NEXT PHASE CHANGE RULES section still present", "NEXT PHASE CHANGE RULES" in prompt)

    print("\n=== Test: backward compatibility -- an OLD cached response (with the legacy 5th section) still parses to its first 4 headings correctly ===")
    # Simulates a real, already-cached CURRENT_PHASE response generated
    # BEFORE this fix (still contains the legacy 5th section) -- this
    # test never touches any real cache row, it only proves the SAME
    # heading-splitting logic Flutter uses (## prefix, multiline) still
    # correctly extracts the first 4 real sections regardless of a 5th,
    # unrecognized trailing section being present.
    legacy_cached_response = (
        "## Current Phase\n\nSome current phase text.\n\n"
        "## Next Phase Change\n\nAround 18 August 2026\n\n"
        "## Watch Out For\n\nSome watch out text.\n\n"
        "## Remedy For This Phase\n\nSome remedy text.\n\n"
        "## Current Timing (Next 2-3 Days)\n\nLegacy unused text. Quick tip: legacy tip.\n"
    )
    legacy_headings = dict()
    matches = list(_HEADING_PATTERN.finditer(legacy_cached_response))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(legacy_cached_response)
        legacy_headings[heading] = legacy_cached_response[start:end].strip()

    check("legacy cached response still yields 'Current Phase' text", legacy_headings.get("Current Phase") == "Some current phase text.")
    check("legacy cached response still yields 'Next Phase Change' text", legacy_headings.get("Next Phase Change") == "Around 18 August 2026")
    check("legacy cached response still yields 'Watch Out For' text", legacy_headings.get("Watch Out For") == "Some watch out text.")
    check("legacy cached response still yields 'Remedy For This Phase' text", legacy_headings.get("Remedy For This Phase") == "Some remedy text.")
    check("legacy 5th section is present in the parsed map but simply an extra, ignorable key (proves nothing breaks by its presence)", "Current Timing (Next 2-3 Days)" in legacy_headings)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
