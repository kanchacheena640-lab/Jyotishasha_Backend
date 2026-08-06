"""
test_family.py
--------------
Local-only entry point for the AI Prediction Lab's Family Profile.
Mirrors test_love.py's/test_career.py's/test_finance.py's/
test_health.py's exact structure and workflow for the FAMILY segment.

Workflow:
    Existing Backend -> Kundali Payload -> Context Builder -> Prompt Builder
    -> OpenAI -> AI Response

This script does not touch Flask, Celery, the database, or any existing
production route. It only imports the existing kundali engine directly.
It never makes, and must never be read as, a claim about any specific
family member other than the profile owner.
"""

import json
import os
import sys
from datetime import datetime

# Windows consoles default to cp1252, which cannot encode the emoji
# characters the existing backend prints (e.g. inside full_kundali_api.py's
# own exception handlers). Reconfiguring stdout here -- in this new,
# local-only script -- avoids that crash without touching any production
# file.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from full_kundali_api import calculate_full_kundali
from services.ai_prediction_lab.family_context_builder import build_family_profile_context
from services.ai_prediction_lab.family_prompt_builder import build_family_profile_prompt
from services.ai_prediction_lab.current_family_phase_context import build_current_family_phase_context
from services.ai_prediction_lab.current_family_phase_prompt_builder import build_current_family_phase_prompt
from services.ai_prediction_lab.family_action_context import build_family_action_context
from services.ai_prediction_lab.family_action_guidance_prompt_builder import build_family_action_guidance_prompt
from services.ai_prediction_lab import openai_client

# ----------------------------------------------------------------------
# Same demo birth data every other segment's test script uses (Ravi,
# Lucknow, Uttar Pradesh, India) -- so all five segments' outputs for
# the same chart are directly comparable during manual review.
# ----------------------------------------------------------------------
DEMO_PERSON = {
    "name": "Ravi",
    "dob": "1985-03-31",
    "tob": "19:45",
    "pob": "Lucknow, Uttar Pradesh, India",
    "lat": 26.8467,
    "lon": 80.9462,
    "language": "en",
}

OUTPUT_ROOT = os.path.join(
    os.path.dirname(__file__), "services", "ai_prediction_lab", "output", "family_profile"
)


def main():
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(OUTPUT_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    print("=" * 60)
    print("BIRTH DETAILS USED FOR THIS RUN")
    print("=" * 60)
    print(f"Name : {DEMO_PERSON['name']}")
    print(f"DOB  : {DEMO_PERSON['dob']}")
    print(f"TOB  : {DEMO_PERSON['tob']}")
    print(f"POB  : {DEMO_PERSON.get('pob', 'Not specified')}")
    print(f"Lat  : {DEMO_PERSON['lat']}")
    print(f"Lon  : {DEMO_PERSON['lon']}")
    print("=" * 60 + "\n")

    # 1) Existing backend generates the kundali (single source of truth).
    print("-> Generating kundali via existing backend (full_kundali_api)...")
    kundali = calculate_full_kundali(
        name=DEMO_PERSON["name"],
        dob=DEMO_PERSON["dob"],
        tob=DEMO_PERSON["tob"],
        lat=DEMO_PERSON["lat"],
        lon=DEMO_PERSON["lon"],
        user_id=None,
        language=DEMO_PERSON["language"],
    )
    print("[OK] Kundali generated.")

    # 2) Build the Family Profile context.
    print("-> Building Family Profile context...")
    context = build_family_profile_context(kundali)
    print("[OK] Family Profile context built.")

    context_path = os.path.join(run_dir, "context.json")
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] context.json saved -> {context_path}")

    # 3) Build the final prompt from the template.
    print("-> Loading prompt template and building final prompt...")
    prompt = build_family_profile_prompt(context)
    print("[OK] Prompt generated.")

    prompt_path = os.path.join(run_dir, "prompt.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"[OK] prompt.txt saved -> {prompt_path}")

    # 4) Send to OpenAI.
    print("-> Sending prompt to OpenAI...")
    response_text, raw_openai = openai_client.generate_with_raw(prompt)
    print("[OK] Response received.")

    response_path = os.path.join(run_dir, "response.txt")
    with open(response_path, "w", encoding="utf-8") as f:
        f.write(response_text)
    print(f"[OK] response.txt saved -> {response_path}")

    raw_path = os.path.join(run_dir, "raw_openai.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_openai, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] raw_openai.json saved -> {raw_path}")

    print("\n" + "=" * 60)
    print("AI FAMILY PROFILE RESPONSE (SECTION 1: FAMILY DNA)")
    print("=" * 60)
    print(response_text)
    print("=" * 60)

    # ------------------------------------------------------------------
    # SECTION 2: CURRENT FAMILY PHASE (builds on Section 1's response)
    # ------------------------------------------------------------------
    print("\n-> Building Current Family Phase context...")
    phase_context = build_current_family_phase_context(kundali, context)
    print("[OK] Current Family Phase context built.")

    phase_context_path = os.path.join(run_dir, "family_phase_context.json")
    with open(phase_context_path, "w", encoding="utf-8") as f:
        json.dump(phase_context, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] family_phase_context.json saved -> {phase_context_path}")

    print("-> Loading Current Family Phase template and building final prompt...")
    phase_prompt = build_current_family_phase_prompt(
        birth_date=DEMO_PERSON["dob"],
        birth_time=DEMO_PERSON["tob"],
        birth_place=DEMO_PERSON.get("pob", "Not specified"),
        family_dna=response_text,
        context=phase_context,
    )
    print("[OK] Prompt generated.")

    phase_prompt_path = os.path.join(run_dir, "family_phase_prompt.txt")
    with open(phase_prompt_path, "w", encoding="utf-8") as f:
        f.write(phase_prompt)
    print(f"[OK] family_phase_prompt.txt saved -> {phase_prompt_path}")

    print("-> Sending prompt to OpenAI...")
    phase_response_text, phase_raw_openai = openai_client.generate_with_raw(phase_prompt)
    print("[OK] Response received.")

    phase_response_path = os.path.join(run_dir, "family_phase_response.txt")
    with open(phase_response_path, "w", encoding="utf-8") as f:
        f.write(phase_response_text)
    print(f"[OK] family_phase_response.txt saved -> {phase_response_path}")

    print("\n" + "=" * 60)
    print("AI RESPONSE (SECTION 2: CURRENT FAMILY PHASE)")
    print("=" * 60)
    print(phase_response_text)
    print("=" * 60)

    # ------------------------------------------------------------------
    # SECTION 3: PRACTICAL FAMILY GUIDANCE (builds on Sections 1 and 2)
    # ------------------------------------------------------------------
    print("\n-> Building family action context...")
    action_context = build_family_action_context(kundali)
    print("[OK] Family action context built.")

    action_context_path = os.path.join(run_dir, "family_action_context.json")
    with open(action_context_path, "w", encoding="utf-8") as f:
        json.dump(action_context, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] family_action_context.json saved -> {action_context_path}")

    print("-> Loading Action Guidance template and building final prompt...")
    action_prompt = build_family_action_guidance_prompt(
        family_dna=response_text,
        current_family_phase=phase_response_text,
        family_action_context=action_context,
    )
    print("[OK] Prompt generated.")

    action_prompt_path = os.path.join(run_dir, "family_action_prompt.txt")
    with open(action_prompt_path, "w", encoding="utf-8") as f:
        f.write(action_prompt)
    print(f"[OK] family_action_prompt.txt saved -> {action_prompt_path}")

    print("-> Sending prompt to OpenAI...")
    action_response_text, action_raw_openai = openai_client.generate_with_raw(action_prompt)
    print("[OK] Response received.")

    action_response_path = os.path.join(run_dir, "family_action_response.txt")
    with open(action_response_path, "w", encoding="utf-8") as f:
        f.write(action_response_text)
    print(f"[OK] family_action_response.txt saved -> {action_response_path}")

    print("\n" + "=" * 60)
    print("AI RESPONSE (SECTION 3: PRACTICAL FAMILY GUIDANCE)")
    print("=" * 60)
    print(action_response_text)
    print("=" * 60)


if __name__ == "__main__":
    main()
