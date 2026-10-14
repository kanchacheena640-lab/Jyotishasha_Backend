"""Reuse existing synthetic audit/pada fixtures; test only closure corrections."""
import ast
import itertools
from pathlib import Path
import subprocess
import types
import unittest
import modules.love.ashtakoot_love as AK

ROOT = Path(__file__).resolve().parent


class AshtakootClosure(unittest.TestCase):
    def test_unknown_rashi_never_fabricates_nadi_cancellation(self):
        for a, b in (("Unknown A", "Unknown B"), ("Unknown", "Unknown"), ([], "Aries")):
            result = AK.nadi_koota({"nakshatra": "Ashwini", "rashi": a}, {"nakshatra": "Ashwini", "rashi": b})
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["score"], 0)
            self.assertNotIn("cancelled", result)

    def test_valid_11664_pair_scores_unchanged_from_approved_baseline(self):
        # Reuse the 108 pada midpoint domain defined in the existing verification.
        source = (ROOT / "test_ashtakoot_phase1_corrections.py").read_text(encoding="utf-8")
        namespace = {"SIGNS": list(AK.RASHI_LORD), "NAKS": AK.NAKSHATRAS_27}
        namespace["SIGNS"] = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
        nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in ("moon", "moon_at")
                 or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PADAS" for t in n.targets)]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "reused_fixture", "exec"), namespace)
        baseline = types.ModuleType("approved_ashtakoot")
        raw = subprocess.check_output(["git","show","94e6741:modules/love/ashtakoot_love.py"], cwd=ROOT)
        exec(compile(raw,"approved_ashtakoot","exec"),baseline.__dict__)
        count = 0
        for x, y in itertools.product(namespace["PADAS"], repeat=2):
            bride, groom = namespace["moon_at"](x), namespace["moon_at"](y)
            old, new = baseline.compute_ashtakoot(bride,groom), AK.compute_ashtakoot(bride,groom)
            self.assertEqual(new["kootas"], old["kootas"])
            self.assertEqual(new["total_score"], old["total_score"])
            self.assertEqual(new["total_score"], sum(k["score"] for k in new["kootas"].values()))
            self.assertEqual(new["max_score"], 36)
            count += 1
        self.assertEqual(count, 11664)


if __name__ == "__main__":
    unittest.main()
