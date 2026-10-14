"""Offline, read-only Manglik comparison against a sanitized JSONL snapshot.

No application/ORM imports, credentials, database connection or write mode.
Input rows: id, firebase_uid (opaque synthetic linkage marker), dob, tob,
pob, lat, lng, static_dosh. Do not supply names/contact details.
Output contains aggregate counts only. Run from any working directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import types

SOURCE_DIR = Path(__file__).with_name("manglik_comparison_v2")
APPROVED_COMMIT = "94e6741728b2f234ab46dcb36063611172ed4547"
ACTIVE = {"Strong", "Partial"}
STRENGTHS = ACTIVE | {"None", "Cancelled"}
PINNED_FILES = {"manglik.py", "birth_timezone.py", "lahiri.py", "positions.py"}


def verified_sources():
    manifest = json.loads((SOURCE_DIR / "provenance.json").read_text(encoding="utf-8"))
    if manifest["commit"] != APPROVED_COMMIT or set(manifest["files"]) != PINNED_FILES:
        raise RuntimeError("Unapproved source manifest")
    sources = {}
    for name in sorted(PINNED_FILES):
        data = (SOURCE_DIR / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest["files"][name]["sha256"]:
            raise RuntimeError("Pinned source integrity failure")
        sources[name] = data.decode("utf-8")
    return sources, manifest["commit"]


def load_module(name, source, injected=None):
    module = types.ModuleType(name)
    module.__dict__.update(injected or {})
    exec(compile(source, name, "exec"), module.__dict__)
    return module


class ProductionCalculator:
    """Only production chart prerequisites and Manglik evaluator are loaded."""
    def __init__(self):
        sources, self.commit = verified_sources()
        import swisseph as swe
        lahiri = load_module("pinned_lahiri", sources["lahiri.py"])
        timezone = load_module("pinned_timezone", sources["birth_timezone.py"])
        self.birth_error = timezone.BirthTimezoneError
        self.positions = load_module("pinned_positions", sources["positions.py"], {
            "swe": swe, "ensure_lahiri_mode": lahiri.ensure_lahiri_mode,
            "resolve_birth_utc_datetime": timezone.resolve_birth_utc_datetime,
        })
        self.engine = load_module("pinned_manglik", sources["manglik.py"])

    def __call__(self, profile):
        try:
            planets = self.positions.calculate_planet_positions(
                profile["dob"], profile["tob"], profile["lat"], profile["lng"])
        except self.birth_error:
            raise InvalidBirth from None
        aspects = self.positions.calculate_drishti_for_planets(planets)
        for planet in planets:
            planet["aspected_by"] = aspects[planet["name"]]["aspected_by"]
        result = self.engine.build_manglik_dosh({
            "planets": planets,
            "lagna_sign": next(p["sign"] for p in planets if "Ascendant" in p["name"]),
            "moon_sign": next(p["sign"] for p in planets if p["name"] == "Moon"),
        }, "en")
        return result["status"]["strength"]


class InvalidBirth(Exception):
    pass


def old_classification(row):
    """Unknown is never inferred to mean Non-Manglik."""
    value = row.get("static_dosh")
    if value is None:
        return "Unknown", "missing"
    if not isinstance(value, dict):
        return "Unknown", "malformed"
    if "manglik" not in value:
        return "Absent", None
    entry = value["manglik"]
    if not isinstance(entry, dict) or not isinstance(entry.get("severity"), str) or entry.get("severity") not in ACTIVE:
        return "Unknown", "malformed"
    return entry["severity"], None


def validate_birth(row):
    from datetime import datetime
    if not isinstance(row["dob"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["dob"]):
        raise InvalidBirth
    if not isinstance(row["tob"], str) or not re.fullmatch(r"\d{2}:\d{2}", row["tob"]):
        raise InvalidBirth
    try:
        datetime.strptime(row["dob"] + " " + row["tob"], "%Y-%m-%d %H:%M")
        for field, bound in (("lat", 90), ("lng", 180)):
            value = row[field]
            if isinstance(value, bool) or not math.isfinite(float(value)) or abs(float(value)) > bound:
                raise InvalidBirth
    except (ValueError, TypeError, OverflowError):
        raise InvalidBirth from None
    if not isinstance(row["pob"], str) or not row["pob"].strip():
        raise InvalidBirth


def compare_profiles(profiles, calculator):
    counts = Counter({key: 0 for key in (
        "total_profiles", "total_eligible", "successfully_compared", "changed", "unchanged",
        "unknown_comparisons", "skipped", "skipped_unlinked", "skipped_incomplete",
        "invalid", "invalid_input", "invalid_birth_resolution", "failed", "old_json_missing", "old_json_malformed",
        "manglik_to_non_manglik", "non_manglik_to_manglik", "unknown_to_manglik",
        "unknown_to_non_manglik")})
    transitions, engine_transitions = Counter(), Counter()
    for row in profiles:
        counts["total_profiles"] += 1
        if not isinstance(row, dict):
            counts["invalid"] += 1
            counts["invalid_input"] += 1
            continue
        old, issue = old_classification(row)
        if issue:
            counts["old_json_" + issue] += 1
        if row.get("firebase_uid") is None:
            counts["skipped"] += 1
            counts["skipped_unlinked"] += 1
            continue
        if any(row.get(field) in (None, "") for field in ("dob", "tob", "pob", "lat", "lng")):
            counts["skipped"] += 1
            counts["skipped_incomplete"] += 1
            continue
        eligible = False
        try:
            validate_birth(row)
            counts["total_eligible"] += 1
            eligible = True
            # Whitelisted fresh mapping: the calculator cannot mutate the input.
            birth = {key: row[key] for key in ("dob", "tob", "lat", "lng")}
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                severity = calculator(birth)
            if severity not in STRENGTHS:
                raise RuntimeError("Invalid engine output")
        except InvalidBirth:
            counts["invalid"] += 1
            counts["invalid_birth_resolution" if eligible else "invalid_input"] += 1
            continue
        except Exception:
            # Never print exception text, tracebacks, IDs or input values.
            counts["failed"] += 1
            continue
        new = severity if severity in ACTIVE else "Absent"
        counts["successfully_compared"] += 1
        transitions[f"{old} -> {new}"] += 1
        engine_transitions[f"{old} -> {severity}"] += 1
        if old == "Unknown":
            counts["unknown_comparisons"] += 1
            counts["unknown_to_manglik" if new in ACTIVE else "unknown_to_non_manglik"] += 1
        else:
            counts["unchanged" if old == new else "changed"] += 1
            if old in ACTIVE and new == "Absent":
                counts["manglik_to_non_manglik"] += 1
            elif old == "Absent" and new in ACTIVE:
                counts["non_manglik_to_manglik"] += 1
    return {"counts": dict(counts), "stored_classification_transitions": dict(sorted(transitions.items())),
            "new_engine_severity_transitions": dict(sorted(engine_transitions.items()))}


def read_snapshot(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError:
                    yield None  # counted invalid; input text never echoed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitized-snapshot", type=Path, required=True,
                        help="Owner-approved sanitized JSONL; no database connection is supported")
    args = parser.parse_args(argv)
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            calculator = ProductionCalculator()
        summary = compare_profiles(read_snapshot(args.sanitized_snapshot), calculator)
    except Exception:
        print(json.dumps({"error": "Comparison could not start or read input; details suppressed"}))
        return 1
    summary["production_commit"] = calculator.commit
    summary["scope"] = "Manglik only; offline read-only; old Absent cannot distinguish None/Cancelled"
    print(json.dumps(summary, indent=2))
    return 0


def offline_safety_audit(event, args):
    if event.startswith("socket.") or event in ("subprocess.Popen", "os.system"):
        raise RuntimeError("Offline network/process boundary")
    if event == "import" and args[0].split(".")[0] in (
        "app", "factory", "extensions", "sqlalchemy", "psycopg", "psycopg2", "sqlite3", "firebase_admin"
    ):
        raise RuntimeError("Offline database import boundary")


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.addaudithook(offline_safety_audit)
    raise SystemExit(main())
