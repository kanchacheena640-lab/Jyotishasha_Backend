"""
test_love.py
--------------
Local-only entry point for the AI Prediction Lab's Lifetime Love Profile.

Workflow:
    Existing Backend -> Kundali Payload -> Context Builder -> Prompt Builder
    -> OpenAI -> AI Response

This script does not touch Flask, Celery, the database, or any existing
production route. It only imports the existing kundali engine directly.
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
from services.ai_prediction_lab.context_builder import build_love_profile_context
from services.ai_prediction_lab.prompt_builder import build_love_profile_prompt
from services.ai_prediction_lab.current_love_phase_context import build_current_love_phase_context
from services.ai_prediction_lab.current_love_phase_prompt_builder import build_current_love_phase_prompt
from services.ai_prediction_lab.daily_transit_context import build_daily_transit_context
from services.ai_prediction_lab.daily_love_prediction_prompt_builder import build_daily_love_prediction_prompt
from services.ai_prediction_lab.report_metadata import build_report_metadata
from services.ai_prediction_lab.report_response import build_report_response
from services.ai_prediction_lab import openai_client

# ----------------------------------------------------------------------
# Birth data for this run (Ravi, Lucknow, Uttar Pradesh, India).
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
    os.path.dirname(__file__), "services", "ai_prediction_lab", "output", "love_profile"
)


def main():
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join(OUTPUT_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # 0) Confirm which birth details this run actually used.
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
    #    user_id=None -> guest mode, no DB write (see save_dasha_to_db()).
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

    # 2) Build the Love Profile context.
    print("-> Building Love Profile context...")
    context = build_love_profile_context(kundali)
    print("[OK] Love Profile context built.")

    context_path = os.path.join(run_dir, "context.json")
    with open(context_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] context.json saved -> {context_path}")

    # 3) Build the final prompt from the template.
    print("-> Loading prompt template and building final prompt...")
    prompt = build_love_profile_prompt(context)
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

    # 5) Print the AI response in the terminal.
    print("\n" + "=" * 60)
    print("AI LOVE PROFILE RESPONSE (SECTION 1: RELATIONSHIP DNA)")
    print("=" * 60)
    print(response_text)
    print("=" * 60)

    # ------------------------------------------------------------------
    # SECTION 2: CURRENT LOVE PHASE (builds on Section 1's response)
    # ------------------------------------------------------------------
    print("\n-> Building Current Love Phase context...")
    # Reuses `context` (the Relationship Birth Summary built once, above)
    # instead of letting it be recomputed a second time.
    love_phase_context = build_current_love_phase_context(kundali, context)
    print("[OK] Current Love Phase context built.")

    love_phase_context_path = os.path.join(run_dir, "love_phase_context.json")
    with open(love_phase_context_path, "w", encoding="utf-8") as f:
        json.dump(love_phase_context, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] love_phase_context.json saved -> {love_phase_context_path}")

    print("-> Loading Current Love Phase template and building final prompt...")
    love_phase_prompt = build_current_love_phase_prompt(
        birth_date=DEMO_PERSON["dob"],
        birth_time=DEMO_PERSON["tob"],
        birth_place=DEMO_PERSON.get("pob", "Not specified"),
        relationship_dna=response_text,
        context=love_phase_context,
    )
    print("[OK] Prompt generated.")

    love_phase_prompt_path = os.path.join(run_dir, "love_phase_prompt.txt")
    with open(love_phase_prompt_path, "w", encoding="utf-8") as f:
        f.write(love_phase_prompt)
    print(f"[OK] love_phase_prompt.txt saved -> {love_phase_prompt_path}")

    print("-> Sending prompt to OpenAI...")
    love_phase_response_text, love_phase_raw_openai = openai_client.generate_with_raw(love_phase_prompt)
    print("[OK] Response received.")

    love_phase_response_path = os.path.join(run_dir, "love_phase_response.txt")
    with open(love_phase_response_path, "w", encoding="utf-8") as f:
        f.write(love_phase_response_text)
    print(f"[OK] love_phase_response.txt saved -> {love_phase_response_path}")

    love_phase_raw_path = os.path.join(run_dir, "love_phase_raw_openai.json")
    with open(love_phase_raw_path, "w", encoding="utf-8") as f:
        json.dump(love_phase_raw_openai, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] love_phase_raw_openai.json saved -> {love_phase_raw_path}")

    print("\n" + "=" * 60)
    print("AI RESPONSE (SECTION 2: CURRENT LOVE PHASE)")
    print("=" * 60)
    print(love_phase_response_text)
    print("=" * 60)

    # ------------------------------------------------------------------
    # SECTION 3: DAILY LOVE PREDICTION (builds on Sections 1 and 2)
    # ------------------------------------------------------------------
    print("\n-> Building Layer 3 daily transit context...")
    daily_transit_context = build_daily_transit_context(kundali)
    print("[OK] Daily transit context built.")

    daily_transit_context_path = os.path.join(run_dir, "daily_transit_context.json")
    with open(daily_transit_context_path, "w", encoding="utf-8") as f:
        json.dump(daily_transit_context, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] daily_transit_context.json saved -> {daily_transit_context_path}")

    print("-> Loading Daily Love Prediction template and building final prompt...")
    daily_love_prediction_prompt = build_daily_love_prediction_prompt(
        relationship_dna=response_text,
        current_love_phase=love_phase_response_text,
        daily_transit_context=daily_transit_context,
    )
    print("[OK] Prompt generated.")

    daily_love_prediction_prompt_path = os.path.join(run_dir, "daily_love_prediction_prompt.txt")
    with open(daily_love_prediction_prompt_path, "w", encoding="utf-8") as f:
        f.write(daily_love_prediction_prompt)
    print(f"[OK] daily_love_prediction_prompt.txt saved -> {daily_love_prediction_prompt_path}")

    print("-> Sending prompt to OpenAI...")
    daily_love_prediction_response_text, daily_love_prediction_raw_openai = openai_client.generate_with_raw(
        daily_love_prediction_prompt
    )
    print("[OK] Response received.")

    daily_love_prediction_response_path = os.path.join(run_dir, "daily_love_prediction_response.txt")
    with open(daily_love_prediction_response_path, "w", encoding="utf-8") as f:
        f.write(daily_love_prediction_response_text)
    print(f"[OK] daily_love_prediction_response.txt saved -> {daily_love_prediction_response_path}")

    daily_love_prediction_raw_path = os.path.join(run_dir, "daily_love_prediction_raw_openai.json")
    with open(daily_love_prediction_raw_path, "w", encoding="utf-8") as f:
        json.dump(daily_love_prediction_raw_openai, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] daily_love_prediction_raw_openai.json saved -> {daily_love_prediction_raw_path}")

    print("\n" + "=" * 60)
    print("AI RESPONSE (SECTION 3: DAILY LOVE PREDICTION)")
    print("=" * 60)
    print(daily_love_prediction_response_text)
    print("=" * 60)

    # ------------------------------------------------------------------
    # REPORT METADATA (footer info only -- not part of the AI-generated
    # report text; the report sections above are untouched).
    # Kept as its own file for backward compatibility with the previous
    # metadata-only turn.
    # ------------------------------------------------------------------
    metadata = build_report_metadata(love_phase_context)

    metadata_path = os.path.join(run_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[OK] metadata.json saved -> {metadata_path}")

    # ------------------------------------------------------------------
    # FULL RESPONSE ENVELOPE (version/language/generated_at/sections/
    # metadata) -- additive; does not replace any file above.
    # ------------------------------------------------------------------
    report = build_report_response(
        love_phase_context=love_phase_context,
        relationship_dna_text=response_text,
        current_love_phase_text=love_phase_response_text,
        daily_love_insight_text=daily_love_prediction_response_text,
        language=DEMO_PERSON["language"],
    )

    report_path = os.path.join(run_dir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"[OK] report.json saved -> {report_path}")


if __name__ == "__main__":
    main()
