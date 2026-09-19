"""
Q4.4B -- relationship_future_report: the customer-facing report contract.

Defects found in the Q4.4 English sample (deterministic astrology was correct; presentation was not):
  1. internal identifiers (A_FULL_DUAL, partner_data_mode) were printed in customer prose;
  2. the prompt's "Title -- instruction" section lines leaked the instruction into rendered headings;
  3. a report with full birth data for both people talked about a "DOB-only comparison";
  4. raw engine jargon ("status pass/partial", "remainder 9") was printed;
  5. the partner's identity was missing (covered by test_love_identity_q44b.py).

This file pins the fixes. No AI call, no network, no DB. Astrology is NOT under test here beyond proving it is passed through untouched.
"""
import copy
import hashlib
import io
import json
import os
import re
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from full_kundali_api import calculate_full_kundali  # noqa: E402
from modules.love.love_data_collector import collect_love_report_data  # noqa: E402
from modules.love.love_prompt_builder import (  # noqa: E402
    INTERNAL_IDENTIFIERS, RELATIONSHIP_SECTION_TITLES, build_love_premium_prompt, find_internal_leaks, normalize_relationship_headings,
)
from modules.payments.report_structured_output import parse_structured_response  # noqa: E402

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON  # noqa: E402  (the synthetic certificate the repo's own boot tests use)
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
import modules.love.love_premium_task as premium  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


ORDER_PRIMARY = dict(name="Rohan Mehta", dob="1988-11-03", tob="07:20", pob="Mumbai, Maharashtra, India", latitude="19.0760", longitude="72.8777")
PARTNER_LIVE = dict(name="Kavya Nair", dob="1991-02-14", tob="18:05", pob="Chennai, Tamil Nadu, India", latitude=13.0827, longitude=80.2707)
WIRE_START, WIRE_END = "\nReturn exactly this machine-readable format.", "\nDisclaimer:\n"
PIN_WIRE = "8712f6314bb26977"      # the ===META=== / ===REPORT=== wire block, unchanged since before Q4.4A

_kundali = {}


def kundali(language):
    if language not in _kundali:
        _kundali[language] = calculate_full_kundali(
            name=ORDER_PRIMARY["name"], dob=ORDER_PRIMARY["dob"], tob=ORDER_PRIMARY["tob"],
            lat=float(ORDER_PRIMARY["latitude"]), lon=float(ORDER_PRIMARY["longitude"]), language=language)
    return copy.deepcopy(_kundali[language])


def collect(partner, language):
    return collect_love_report_data(order={**ORDER_PRIMARY, "language": language, "partner": partner},
                                    user_kundali=kundali(language), language=language, boy_is_user=True)


def evidence_of(prompt):
    return json.loads(prompt.split("Deterministic evidence:\n")[1])


def instructions_of(prompt):
    return prompt[:prompt.index(WIRE_START)]


payloads = {(lang, mode): collect(dict(PARTNER_LIVE) if mode == "full" else {"name": PARTNER_LIVE["name"], "dob": PARTNER_LIVE["dob"]}, lang)
            for lang in ("en", "hi") for mode in ("full", "partial")}
prompts = {key: build_love_premium_prompt(value) for key, value in payloads.items()}

print("\n=== 1: the customer heading is structurally separate from the AI instruction (10 sections, EN + HI) ===")
for lang in ("en", "hi"):
    prompt = prompts[(lang, "full")]
    lines = prompt.split("\n")
    idx = [i for i, ln in enumerate(lines) if re.match(r"^\d+\.\s", ln)]
    titles = RELATIONSHIP_SECTION_TITLES[lang]
    check(f"1[{lang}]: exactly 10 approved titles", len(titles) == 10 and len(set(titles)) == 10)
    check(f"1[{lang}]: exactly 10 numbered lines, numbered 1..10", [int(lines[i].split(".")[0]) for i in idx] == list(range(1, 11)))
    check(f"1[{lang}]: every numbered line IS the clean approved title -- nothing appended", all(lines[i] == f"{n}. {titles[n - 1]}" for n, i in enumerate(idx, 1)))
    check(f"1[{lang}]: no heading contains a dash / colon / bracket separator that could carry an instruction",
          all(not re.search(r"\s(?:—|–|--|-)\s|[:\[\]()]", titles[n - 1]) for n in range(1, 11)))
    check(f"1[{lang}]: each heading is followed by exactly one separate bracketed private-instruction line",
          all(lines[i + 1].startswith("   [Private instruction") and lines[i + 1].endswith("]") and not re.match(r"^\d+\.", lines[i + 1]) for i in idx))
    check(f"1[{lang}]: the instruction text lives ONLY on the bracket lines, never on a heading line",
          all("Private instruction" not in lines[i] and "[" not in lines[i] for i in idx))
    check(f"1[{lang}]: the prompt explicitly tells the model to print the heading verbatim and never print/attach the instruction",
          ("copy it exactly" in prompt and "never print" in prompt) if lang == "en" else ("बिल्कुल वैसा ही" in prompt and "कभी न लिखें" in prompt))
    check(f"1[{lang}]: partial-data prompt has the identical heading structure", [ln for ln in prompts[(lang, "partial")].split("\n") if re.match(r"^\d+\.\s", ln)] == [lines[i] for i in idx])

en_titles, hi_titles = RELATIONSHIP_SECTION_TITLES["en"], RELATIONSHIP_SECTION_TITLES["hi"]
check("1: EN section semantics (order) unchanged: outlook, snapshot, koota evidence, dynamics, 5th/7th, strengths, attention, dasha, guidance, summary",
      [t.split()[0] for t in en_titles] == ["Relationship", "Compatibility", "Koota-Wise", "Emotional", "5th", "Strengths", "Areas", "Current", "Practical", "Summary"])
check("1: HI section semantics (order) unchanged and Hindi headings stay modern Hinglish, EN and HI have the same count",
      len(hi_titles) == len(en_titles) == 10 and [t.split()[-1] for t in hi_titles][-1] == "Summary" and "किन बातों पर ध्यान दें" in hi_titles)
check("1: no Sanskritized regression in the Hindi headings", not any(w in " ".join(hi_titles) for w in ("गतिशीलता", "कूटवार", "अनुकूलता का सार", "पाँचवें", "सातवें", "व्यावहारिक", "अस्वीकरण")))

print("\n=== 2: the deterministic heading normalizer (safety net if the model still appends an instruction) ===")
for lang in ("en", "hi"):
    titles = RELATIONSHIP_SECTION_TITLES[lang]
    for sep in (" — ", " -- ", " - ", ": ", " (", " – "):
        dirty = "\n".join(f"{n}. {t}{sep}state the actual total and explain" + (")" if sep == " (" else "") for n, t in enumerate(titles, 1))
        cleaned = normalize_relationship_headings(dirty, lang)
        check(f"2[{lang}]: '{sep.strip() or 'space'}' suffixes on all 10 headings are cut back to the approved title",
              cleaned.split("\n") == [f"{n}. {t}" for n, t in enumerate(titles, 1)])
bold = normalize_relationship_headings("**1. Relationship Outlook — synthesize the outlook**", "en")
check("2: bold-wrapped heading is cleaned and keeps its markdown wrapper", bold == "**1. Relationship Outlook**")
clean = "\n".join(f"{n}. {t}\nBody text for section {n}." for n, t in enumerate(en_titles, 1))
check("2: an already-clean report is returned byte-identical", normalize_relationship_headings(clean, "en") == clean)
prose = "3. Koota-Wise Compatibility Evidence overall looks steady.\n2. Some other numbered point about Compatibility Snapshot: not a heading"
check("2: prose that merely starts with a title (no separator) and non-approved numbered lines are NOT touched", normalize_relationship_headings(prose, "en") == prose)
body = "Rohan and Kavya connect well — 3. not a heading at line start.\n1. Relationship Outlook\nText — with a dash."
check("2: body text containing dashes is never altered", normalize_relationship_headings(body, "en") == body)
check("2: None / empty input is safe", normalize_relationship_headings("", "en") == "" and normalize_relationship_headings(None, "hi") == "")

print("\n=== 3: prompt leakage -- internal names appear ONLY inside the 'never write this' rule, never as evidence or headings ===")
MODE_IDS = ("A_FULL_DUAL", "B_DOB_ONLY_HYBRID", "partner_data_mode")
for lang in ("en", "hi"):
    for mode in ("full", "partial"):
        prompt = prompts[(lang, mode)]
        ev_text = prompt.split("Deterministic evidence:\n")[1]
        instr = instructions_of(prompt)
        sections = "\n".join(ln for ln in instr.split("\n") if re.match(r"^\d+\.\s|^   \[Private", ln))
        check(f"3[{lang}/{mode}]: no mode identifier, key or status label in the evidence the model sees",
              not any(tok in ev_text for tok in MODE_IDS) and not re.search(r"status\W*(?:pass|partial)|remainder", ev_text))
        check(f"3[{lang}/{mode}]: no mode identifier in the section headings / their instructions", not any(tok in sections for tok in MODE_IDS))
        rule = "CUSTOMER-FACING CONTRACT" if lang == "en" else "Customer के लिए नियम"
        rule_text = instr[instr.index(rule):]
        rule_text = rule_text[:rule_text.index("\n\n")] if "\n\n" in rule_text else rule_text
        check(f"3[{lang}/{mode}]: the general no-internal-terminology rule names every forbidden identifier (with examples)",
              all(tok in rule_text for tok in ("A_FULL_DUAL", "B_DOB_ONLY_HYBRID", "partner_data_mode", "astro_facts", "compiled_report", "signals", "verdict_level")))
        check(f"3[{lang}/{mode}]: the rule also forbids status labels and raw engine output",
              ("status pass" in rule_text and "status partial" in rule_text and "remainder" in rule_text) if lang == "en"
              else ("status pass" in rule_text and "status partial" in rule_text and "remainder" in rule_text))
        stray = [tok for tok in MODE_IDS if tok in instr.replace(rule_text, "")]
        check(f"3[{lang}/{mode}]: the identifiers are mentioned nowhere else in the instructions ({stray or 'none'})", not stray)
    check(f"3[{lang}]: the prompt does NOT blanket-ban 'bride'/'groom' (it prefers names where natural)",
          "bride" in prompts[(lang, 'full')] and not re.search(r"never (?:use|write|say) ['\"]?(?:bride|groom)", prompts[(lang, 'full')], re.I))
    check(f"3[{lang}]: it asks for names where the two people are discussed, not in every paragraph",
          ("Do not repeat names in every paragraph" in prompts[(lang, 'full')]) if lang == "en" else ("हर paragraph में नाम न दोहराएँ" in prompts[(lang, 'full')]))
    check(f"3[{lang}]: it still refuses to invent a Manglik status", ("Manglik" in prompts[(lang, 'full')]) and ("(for example a Manglik status)" in prompts[(lang, 'full')] if lang == "en" else "Manglik की स्थिति" in prompts[(lang, 'full')]))

print("\n=== 4: raw koota engine fields are stripped from the evidence; name / score / maximum / meaning are kept ===")
RAW = ("status", "bride_to_groom_remainder", "groom_to_bride_remainder", "positions")
for mode in ("full", "partial"):
    raw = payloads[("en", mode)]["compatibility"]["ashtakoot"]
    shown = evidence_of(prompts[("en", mode)])["ashtakoot"]
    check(f"4[{mode}]: the engine really produced raw fields (so the strip is doing something)", any(f in koota for koota in raw["kootas"].values() for f in RAW))
    check(f"4[{mode}]: no raw field survives in any koota", not any(f in koota for koota in shown["kootas"].values() for f in RAW))
    check(f"4[{mode}]: every koota keeps its score and maximum, identical to the engine", all(shown["kootas"][k]["score"] == raw["kootas"][k]["score"] and shown["kootas"][k]["max"] == raw["kootas"][k]["max"] for k in raw["kootas"]))
    check(f"4[{mode}]: astrology passes through untouched -- total/max and every non-raw koota attribute equal the engine's",
          shown["total_score"] == raw["total_score"] and shown["max_score"] == raw["max_score"]
          and all({k: v for k, v in raw["kootas"][n].items() if k not in RAW} == shown["kootas"][n] for n in raw["kootas"]))
    check(f"4[{mode}]: the payload handed to the prompt builder was not mutated by the strip", any(f in koota for koota in payloads[("en", mode)]["compatibility"]["ashtakoot"]["kootas"].values() for f in RAW))

print("\n=== 5: full-data vs partial-data behaviour ===")
for lang in ("en", "hi"):
    full_ev = evidence_of(prompts[(lang, "full")])["partner_birth_data"]
    part_ev = evidence_of(prompts[(lang, "partial")])["partner_birth_data"]
    check(f"5[{lang}]: full data -> completeness 'full' and a summary free of any DOB-only / Moon-only / hybrid / mode wording",
          full_ev["completeness"] == "full" and not re.search(r"DOB[- ]only|Moon|hybrid|fallback|dual|A_FULL|only the partner", full_ev["summary"], re.I))
    check(f"5[{lang}]: DOB-only data -> completeness 'partial' and a summary that states the genuine limitation",
          part_ev["completeness"] == "partial" and "Only the partner's date of birth" in part_ev["summary"] and "Moon" in part_ev["summary"] and "not available" in part_ev["summary"])
    check(f"5[{lang}]: the internal case names never appear in either summary", not any(tok in json.dumps(full_ev) + json.dumps(part_ev) for tok in MODE_IDS))
    prompt = prompts[(lang, "full")]
    if lang == "en":
        check("5[en]: full-data wording is offered to the model verbatim ('full birth details for both people were used')",
              "full birth details for both people were used" in prompt)
        check("5[en]: partial-data limitation instruction is preserved (Moon-based from date of birth only; never invent Lagna/houses/time/place; never claim full details)",
              "Moon-based from the date of birth only" in prompt and "never invent the partner's ascendant, houses, birth time or place" in prompt and "never say that full details were used" in prompt)
    else:
        check("5[hi]: full-data wording is offered to the model ('दोनों लोगों के पूरे जन्म विवरण इस्तेमाल हुए हैं')", "दोनों लोगों के पूरे जन्म विवरण इस्तेमाल हुए हैं" in prompt)
        check("5[hi]: partial-data limitation instruction is preserved (Moon, जन्मतिथि से; Lagna/House/जन्म समय/जन्म स्थान कभी न बनाएँ)",
              "सिर्फ जन्मतिथि से Moon के आधार पर" in prompt and "partner का Lagna, House, जन्म समय या जन्म स्थान कभी न बनाएँ" in prompt)
unavail = evidence_of(build_love_premium_prompt({**payloads[("en", "full")], "compatibility": {**payloads[("en", "full")]["compatibility"], "case": "SOMETHING_ELSE"}}))
check("5: an unrecognised case is described as 'unavailable' (never guessed as full)", unavail["partner_birth_data"]["completeness"] == "unavailable")
check("5: the engine still decides the case -- live full-shape payload is A_FULL_DUAL, DOB-only payload is B_DOB_ONLY_HYBRID (behaviour preserved)",
      payloads[("en", "full")]["compatibility"]["case"] == "A_FULL_DUAL" and payloads[("en", "partial")]["compatibility"]["case"] == "B_DOB_ONLY_HYBRID")

print("\n=== 6: the customer-text leak detector (used as the deterministic guard) ===")
LEAKY = {
    "A_FULL_DUAL": "This is an A_FULL_DUAL comparison.", "B_DOB_ONLY_HYBRID": "Mode B_DOB_ONLY_HYBRID applies.", "partner_data_mode": "partner_data_mode says full.",
    "partner_birth_data": "partner_birth_data: full", "astro_facts": "From astro_facts we see", "compiled_report": "compiled_report shows", "verdict_level": "verdict_level is High",
}
for token, text in LEAKY.items():
    check(f"6: '{token}' is always a leak (full or partial data)", token in find_internal_leaks(text, full_data=True) and token in find_internal_leaks(text, full_data=False))
check("6: every INTERNAL_IDENTIFIERS entry is detected", all(find_internal_leaks(tok, full_data=False) for tok in INTERNAL_IDENTIFIERS))
for text in ("Varna: status pass.", "Nadi has status partial here.", "Gana - status: pass", "The koota STATUS = fail"):
    check(f"6: engine status label detected in {text!r}", "engine status label" in find_internal_leaks(text, full_data=False))
check("6: leaked prompt scaffolding is detected", bool(find_internal_leaks("[Private instruction, never print: x]", full_data=False)) and bool(find_internal_leaks("Customer heading: 1.", full_data=False)))
for text in ("This is a DOB-only comparison.", "A Moon-only view of the partner.", "A hybrid approach.", "Full-dual analysis."):
    check(f"6: fallback wording {text!r} is a leak when full birth data was used", "fallback-mode wording" in find_internal_leaks(text, full_data=True))
    check(f"6: ...and is NOT flagged for a genuine partial-data report (limitation may be stated)", find_internal_leaks(text, full_data=False) == [])
GOOD = ("Full birth details for both people were used in this comparison. Rohan's Moon is in Aquarius and Kavya's Moon is in Libra. "
        "The bride's and groom's Nadi scores 8 out of 8. Bhakoot gives 7 out of 7. Status of the Dasha is running. The Gana koota is a strength.")
check("6: normal astrology prose (Moon, bride/groom, koota scores, 'Dasha status', 'Full birth details ... were used') is clean", find_internal_leaks(GOOD, full_data=True) == [])
check("6: a genuine partial-data limitation sentence is clean", find_internal_leaks("Kavya's analysis is Moon-based, from the date of birth only.", full_data=False) == [])
check("6: empty / None input is safe", find_internal_leaks("", full_data=True) == [] and find_internal_leaks(None, full_data=True) == [])

print("\n=== 7: the REAL premium task enforces the contract on what the model returns (AI + PDF mocked) ===")
CLEAN_BODY = "1. Relationship Outlook\nRohan and Kavya share a steady base.\n2. Compatibility Snapshot\nFull birth details for both people were used.\n3. Koota-Wise Compatibility Evidence\nVarna 1 out of 1."


def run_task(language, body, partner=None, hero_overrides=None):
    partner = dict(PARTNER_LIVE) if partner is None else partner
    order = SimpleNamespace(
        id=616161, name=ORDER_PRIMARY["name"], email="fixture@example.invalid", phone=None, product="relationship_future_report",
        dob=ORDER_PRIMARY["dob"], tob=ORDER_PRIMARY["tob"], pob=ORDER_PRIMARY["pob"], latitude=ORDER_PRIMARY["latitude"], longitude=ORDER_PRIMARY["longitude"],
        language=language, payment_status="PAID", status="PAID", report_stage="Pending", pdf_url=None, created_at=None,
        partner_payload=partner, processing_started_at=None)
    query = MagicMock()
    query.get.return_value = order
    pdf = {}
    hero = {"label": "Relationship Outlook", "value": "Warm and steady", "interpretation": "Grounded in the supplied evidence.",
            "evidence": ["Moon is in the 5th house."], "action_items": ["Talk calmly."]}
    hero.update(hero_overrides or {})
    completion = SimpleNamespace(content="===META===\n" + json.dumps({"hero": hero}, ensure_ascii=False) + "\n===REPORT===\n" + body, model="gpt-5.6-luna",
                                 input_tokens=1, output_tokens=1, total_tokens=2, duration_seconds=0.1)
    reader = open

    def safe_open(path, mode="r", *args, **kwargs):
        return io.StringIO() if "w" in mode else reader(path, mode, *args, **kwargs)

    with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        stack.enter_context(patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("DB access forbidden")))
        stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("network forbidden")))
        stack.enter_context(patch.object(premium, "Order", SimpleNamespace(query=query)))
        stack.enter_context(patch.object(premium, "db", SimpleNamespace(session=MagicMock())))
        stack.enter_context(patch.object(premium, "record_event"))
        stack.enter_context(patch.object(premium, "deliver_generated_report"))
        stack.enter_context(patch.object(premium, "generate_kundali_drawing", return_value=None))
        stack.enter_context(patch.object(premium, "generate_pdf_report", side_effect=lambda **kw: pdf.update(kw)))
        stack.enter_context(patch.object(premium, "generate_report_completion", return_value=completion))
        stack.enter_context(patch.object(premium, "open", safe_open, create=True))
        stack.enter_context(patch("os.makedirs"))
        premium.generate_love_premium_report(order.id)
    return order, pdf


for lang in ("en", "hi"):
    order, pdf = run_task(lang, CLEAN_BODY)
    check(f"7[{lang}]: a clean report reaches Ready with both names in the narrative", order.report_stage == "Ready" and "Rohan" in pdf["gpt_response"] and "Kavya" in pdf["gpt_response"])
    for label, body in (("mode identifier in the narrative", CLEAN_BODY + "\nThis A_FULL_DUAL case is strong."),
                        ("partner_data_mode in the narrative", CLEAN_BODY + "\npartner_data_mode was full."),
                        ("'status pass' in the narrative", CLEAN_BODY + "\nVarna: status pass."),
                        ("'status partial' in the narrative", CLEAN_BODY + "\nNadi: status partial."),
                        ("fallback wording although full birth data was used", CLEAN_BODY + "\nThis is a DOB-only comparison."),
                        ("Moon-only wording although full birth data was used", CLEAN_BODY + "\nA Moon-only view."),
                        ("leaked private instruction", CLEAN_BODY + "\n[Private instruction, never print: x]")):
        order, pdf = run_task(lang, body)
        check(f"7[{lang}]: {label} -> fail closed (report stage Failed, nothing rendered or delivered)", order.report_stage == "Failed" and "gpt_response" not in pdf)
    order, pdf = run_task(lang, CLEAN_BODY, hero_overrides={"value": "Warm, status pass"})
    check(f"7[{lang}]: an engine label in the hero value -> fail closed", order.report_stage == "Failed")
    order, pdf = run_task(lang, CLEAN_BODY, hero_overrides={"interpretation": "Mode is A_FULL_DUAL."})
    check(f"7[{lang}]: a mode identifier in the hero interpretation -> fail closed", order.report_stage == "Failed")
    order, pdf = run_task(lang, CLEAN_BODY, hero_overrides={"action_items": ["Do not rely on partner_data_mode."]})
    check(f"7[{lang}]: a mode identifier in an action item -> fail closed", order.report_stage == "Failed")
    order, pdf = run_task(lang, CLEAN_BODY, hero_overrides={"evidence": ["Verdict A_FULL_DUAL", "status pass on Varna", "Moon is in the 5th house."]})
    check(f"7[{lang}]: leaking hero evidence items are dropped, the clean one and the engine-owned Ashtakoot line stay",
          order.report_stage == "Ready" and pdf["answer_hero"]["evidence"][1:] == ["Moon is in the 5th house."] and "/36" in pdf["answer_hero"]["evidence"][0])
    dirty_headings = "\n".join(f"{n}. {t} — state the actual total and explain\nBody {n} about Rohan and Kavya." for n, t in enumerate(RELATIONSHIP_SECTION_TITLES[lang], 1))
    order, pdf = run_task(lang, dirty_headings)
    heads = [ln for ln in pdf["gpt_response"].split("\n") if re.match(r"^\d+\.\s", ln)]
    check(f"7[{lang}]: instruction suffixes the model appends to headings never reach the renderer", order.report_stage == "Ready" and heads == [f"{n}. {t}" for n, t in enumerate(RELATIONSHIP_SECTION_TITLES[lang], 1)])

order, pdf = run_task("en", "1. Relationship Outlook\nKavya's chart is read through her Moon, from her date of birth only, so this is a DOB-only, Moon-only comparison.\n2. Compatibility Snapshot\nText.",
                      partner={"name": "Kavya Nair", "dob": "1991-02-14"})
check("7: a genuine partial-data report MAY state its DOB-only / Moon-only limitation (reaches Ready)", order.report_stage == "Ready" and "DOB-only" in pdf["gpt_response"])
order, pdf = run_task("en", "1. Relationship Outlook\nText A_FULL_DUAL.\n2. Compatibility Snapshot\nText.", partner={"name": "Kavya Nair", "dob": "1991-02-14"})
check("7: ...but a mode identifier is a leak even in a genuine partial-data report", order.report_stage == "Failed")

print("\n=== 8: structured output and Hindi policy are preserved ===")
for lang in ("en", "hi"):
    prompt = prompts[(lang, "full")]
    check(f"8[{lang}]: the ===META=== hero JSON ===REPORT=== wire block is byte-identical to the pre-Q4.4 contract", h(prompt[prompt.index(WIRE_START):prompt.index(WIRE_END)]) == PIN_WIRE)
    check(f"8[{lang}]: markers appear once each, META before REPORT", prompt.count("===META===") == 1 and prompt.count("===REPORT===") == 1 and prompt.index("===META===") < prompt.index("===REPORT==="))
    check(f"8[{lang}]: exactly 10 numbered sections in the whole prompt", len(re.findall(r"^\d+\.", prompt, re.M)) == 10)
    meta, narrative = parse_structured_response('===META===\n{"hero":{"label":"Relationship Outlook","value":"v","interpretation":"i","evidence":["e"],"action_items":["a"]}}\n===REPORT===\n1. Relationship Outlook\nBody')
    check(f"8[{lang}]: the unchanged parser still accepts the contract", meta["hero"]["label"] == "Relationship Outlook" and narrative.startswith("1. Relationship Outlook"))
hi_prompt = prompts[("hi", "full")]
for tok in ("Modern Conversational Hindi", "क्लिष्ट, संस्कृतनिष्ठ, academic", "DD/MM/YYYY format में लिखें", "छोटे और सीधे वाक्य", "जाने-पहचाने modern शब्द English में ही रखें"):
    check(f"8[hi]: modern-Hindi policy marker present: {tok!r}", tok in hi_prompt)
check("8[hi]: no formal/Sanskritized wording regressed into the Hindi prompt",
      not any(w in instructions_of(hi_prompt) for w in ("खरीदा गया प्रश्न", "गतिशीलता", "कूटवार", "अनुकूलता का सार", "पाँचवें", "सातवें", "व्यावहारिक", "अस्वीकरण", "उपयोगकर्ता")))
for lang in ("en", "hi"):
    prompt = prompts[(lang, "full")]
    check(f"8[{lang}]: safety rules preserved (no private thoughts, no timing, no guarantees, no gemstone, no ending the relationship)",
          all(t in prompt for t in (("thoughts", "feelings", "intentions", "fidelity", "breakup", "exact relationship event timing", "gemstone", "Do not advise ending"))) if lang == "en"
          else all(t in prompt for t in ("विचार", "भावनाएँ", "इरादे", "निष्ठा", "संबंध-विच्छेद", "निश्चित तारीख", "gemstone", "Relationship खत्म करने की सलाह न दें")))
    check(f"8[{lang}]: legacy/heuristic fields still excluded", not any(t in prompt for t in ("love_vs_arranged", "stability_score", "99%", "98%", "HEURISTIC_SECRET_MARKER")))

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
