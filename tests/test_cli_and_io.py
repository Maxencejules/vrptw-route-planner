import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import support
from support import make_scenario

from vrptw import evaluate, generate, load_scenario, load_solution, save_scenario, save_solution, solve
from vrptw.cli import main
from vrptw.solution import SolutionError, solution_from_dict, solution_to_dict


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


class SolutionJsonTest(unittest.TestCase):
    def test_round_trip(self):
        sc = generate(customers=25, layout="clustered", seed=4)
        sol = solve(sc, "savings", improve=True)
        ev = evaluate(sc, sol)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan.json")
            save_solution(path, sc, sol, ev)
            loaded = load_solution(path)
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        self.assertEqual(loaded.routes, sol.routes)
        self.assertEqual(loaded.solver, "savings")
        self.assertTrue(loaded.improved)
        self.assertEqual(loaded.search["moves"], sol.search["moves"])
        again = evaluate(sc, loaded)
        self.assertTrue(again.feasible)
        self.assertAlmostEqual(again.total_distance, ev.total_distance)
        self.assertAlmostEqual(raw["summary"]["total_distance"], ev.total_distance, places=3)
        self.assertEqual(len(raw["timeline"]), ev.vehicles_used)

    def test_rejects_malformed_solution(self):
        sc = make_scenario([(1, 1)])
        good = solution_to_dict(sc, solve(sc), evaluate(sc, solve(sc)))
        self.assertEqual(solution_from_dict(good).routes, [[1]])
        for bad in (
            {"format": "other"},
            {"format": "other", "routes": [[1]]},
            {},
            dict(good, routes=[[1, "2"]]),
            dict(good, routes=[1]),
            {"routes": [[1]], "unassigned": 5},
            {"routes": [[1]], "unassigned": ["2"]},
            {"routes": [[1]], "options": 5},
            {"routes": [[1]], "local_search": [1]},
            {"routes": [[1]], "local_search": {"moves": None}},
            {"routes": [[1]], "local_search": {"moves": {"2-opt": "x"}}},
            {"routes": [[1]], "local_search": {"moves": {"2-opt": -1}}},
            {"routes": [[1]], "local_search": {"start_distance": None}},
            {"routes": [[1]], "local_search": {"end_distance": float("inf")}},
            {"routes": [[1]], "solver": 7},
            {"routes": [[1]], "improved": "no"},
        ):
            with self.assertRaises(SolutionError):
                solution_from_dict(bad)

    def test_routes_are_the_only_required_field(self):
        sol = solution_from_dict({"routes": [[2, 1], [3]]})
        self.assertEqual(sol.routes, [[2, 1], [3]])
        self.assertEqual(sol.unassigned, [])
        self.assertEqual(sol.solver, "")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_generate_matches_library(self):
        code, out, _ = run_cli(
            "generate", "--customers", "18", "--layout", "clustered", "--seed", "6",
            "--out", self.path("s.json"),
        )
        self.assertEqual(code, 0)
        self.assertIn("18 customers", out)
        self.assertEqual(
            load_scenario(self.path("s.json")),
            generate(customers=18, layout="clustered", seed=6),
        )

    def test_generate_to_stdout(self):
        code, out, _ = run_cli("generate", "--customers", "5", "--seed", "3", "--demand", "2,4")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["customers"]), 5)
        self.assertTrue(all(2 <= c["demand"] <= 4 for c in data["customers"]))

    def test_solve_then_check(self):
        save_scenario(generate(customers=20, seed=8), self.path("s.json"))
        code, out, _ = run_cli(
            "solve", "--scenario", self.path("s.json"), "--solver", "nearest",
            "--improve", "--json", self.path("plan.json"),
        )
        self.assertEqual(code, 0, out)
        self.assertIn("Feasible   yes", out)
        self.assertIn("nearest (nn_metric=time) + local search", out)
        code, out, _ = run_cli(
            "check", "--scenario", self.path("s.json"), "--solution", self.path("plan.json")
        )
        self.assertEqual(code, 0, out)
        self.assertIn("Feasible   yes", out)

    def test_check_reports_violations(self):
        save_scenario(generate(customers=12, seed=1), self.path("s.json"))
        run_cli("solve", "--scenario", self.path("s.json"), "--solver", "savings",
                "--json", self.path("plan.json"))
        with open(self.path("plan.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        data["routes"] = data["routes"][1:]  # drop one route
        with open(self.path("broken.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        code, out, _ = run_cli(
            "check", "--scenario", self.path("s.json"), "--solution", self.path("broken.json"),
            "--no-timeline",
        )
        self.assertEqual(code, 1)
        self.assertIn("Feasible   no", out)
        self.assertIn("not served", out)
        self.assertIn("route: depot ->", out)

    def test_check_a_file_with_only_routes(self):
        save_scenario(make_scenario([(3, 0), (3, 4), (0, 4)]), self.path("square.json"))
        with open(self.path("routes.json"), "w", encoding="utf-8") as fh:
            json.dump({"routes": [[1, 2, 3]]}, fh)
        code, out, err = run_cli(
            "check", "--scenario", self.path("square.json"), "--solution", self.path("routes.json")
        )
        self.assertEqual(code, 0, err)
        self.assertIn("Distance   14.00 km", out)
        self.assertIn("Feasible   yes", out)

    def test_infeasible_scenario_exit_code(self):
        sc = make_scenario([(1, 0)], demands=[500], capacity=10)
        save_scenario(sc, self.path("bad.json"))
        code, out, err = run_cli("solve", "--scenario", self.path("bad.json"))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("exceeds vehicle capacity", err)
        code, _, err = run_cli("compare", "--scenario", self.path("bad.json"))
        self.assertEqual(code, 2)
        self.assertIn("exceeds vehicle capacity", err)

    def test_check_reports_an_unservable_customer_as_a_violation(self):
        # check evaluates the routes it is given instead of refusing the
        # scenario, so the capacity problem is a violation with exit status 1.
        sc = make_scenario([(1, 0)], demands=[500], capacity=10)
        save_scenario(sc, self.path("bad.json"))
        with open(self.path("routes.json"), "w", encoding="utf-8") as fh:
            json.dump({"format": "vrptw-solution", "routes": [[1]]}, fh)
        code, out, _ = run_cli(
            "check", "--scenario", self.path("bad.json"), "--solution", self.path("routes.json")
        )
        self.assertEqual(code, 1)
        self.assertIn("violation: vehicle 1: load 500 exceeds capacity 10", out)

    def test_check_rejects_a_malformed_optional_field(self):
        save_scenario(make_scenario([(1, 0)]), self.path("one.json"))
        for extra in (
            {"unassigned": 5},
            {"options": 5},
            {"local_search": 5},
            {"local_search": {"moves": None}},
            {"local_search": {"start_distance": None}},
            {"improved": "no"},
        ):
            with open(self.path("bad.json"), "w", encoding="utf-8") as fh:
                json.dump(dict({"routes": [[1]]}, **extra), fh)
            code, out, err = run_cli(
                "check", "--scenario", self.path("one.json"), "--solution", self.path("bad.json")
            )
            self.assertEqual(code, 2, extra)
            self.assertEqual(out, "")
            self.assertIn("error:", err)
            self.assertNotIn("Traceback", err)

    def test_missing_file_exit_code(self):
        code, _, err = run_cli("solve", "--scenario", self.path("nope.json"))
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_compare_table(self):
        save_scenario(generate(customers=15, layout="clustered", seed=2), self.path("s.json"))
        code, out, _ = run_cli("compare", "--scenario", self.path("s.json"))
        self.assertEqual(code, 0, out)
        rows = [line for line in out.splitlines() if line.startswith(("nearest", "savings"))]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(line.split()[4] == "yes" for line in rows))

    def test_module_entry_point(self):
        save_scenario(make_scenario([(3, 0), (3, 4), (0, 4)]), self.path("square.json"))
        env = dict(os.environ, PYTHONPATH=support.SRC, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(
            [sys.executable, "-m", "vrptw", "solve", "--scenario", self.path("square.json"),
             "--solver", "savings"],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Distance   14.00 km", proc.stdout)


if __name__ == "__main__":
    unittest.main()
