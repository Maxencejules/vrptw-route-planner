import json
import io
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace

import support
from support import make_scenario
from vrptw import Solution, evaluate, save_scenario, save_solution


class IndependentAuditCliTest(unittest.TestCase):
    def run_audit(self, folder, data):
        solution = folder / "solution.json"
        solution.write_text(json.dumps(data), encoding="utf-8")
        main = runpy.run_path(str(Path(support.ROOT) / "scripts" / "validate_solution.py"))["main"]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = main(["--scenario", str(folder / "scenario.json"), "--solution", str(solution)])
        return SimpleNamespace(returncode=status, stdout=out.getvalue(), stderr=err.getvalue())

    def test_saved_rounded_cost_is_accepted_but_false_claim_is_rejected(self):
        sc = make_scenario([(1, 1)])
        sol = Solution(routes=[[1]])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            save_scenario(sc, folder / "scenario.json")
            save_solution(folder / "saved.json", sc, sol, evaluate(sc, sol))
            data = json.loads((folder / "saved.json").read_text(encoding="utf-8"))
            good = self.run_audit(folder, data)
            self.assertEqual(good.returncode, 0, good.stderr)
            checked = json.loads(good.stdout)
            self.assertTrue(checked["feasible"])
            self.assertAlmostEqual(checked["total_distance"], 2**1.5)
            data["summary"]["total_distance"] += 0.001
            wrong = self.run_audit(folder, data)
            self.assertEqual(wrong.returncode, 1)
            self.assertIn("claimed distance", wrong.stdout)

    def test_routes_only_missing_duplicates_unknown_ids_and_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            save_scenario(make_scenario([(1, 0)]), folder / "scenario.json")
            cases = [({"routes": [[1]]}, 0), ({"routes": []}, 1),
                     ({"routes": [[1, 1]]}, 1), ({"routes": [[True]]}, 1),
                     ({"routes": [[99]]}, 1), ({"routes": ["1"]}, 2),
                     ({"routes": [[1]], "summary": []}, 2), ([], 2)]
            for data, status in cases:
                with self.subTest(data=data):
                    result = self.run_audit(folder, data)
                    self.assertEqual(result.returncode, status, result.stderr)


if __name__ == "__main__":
    unittest.main()
