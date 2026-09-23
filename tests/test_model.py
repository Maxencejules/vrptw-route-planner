import json
import os
import tempfile
import unittest

import support
from support import make_scenario

from vrptw import Scenario, ScenarioError, generate, load_scenario, save_scenario


def minimal_dict():
    return {
        "format": "vrptw-scenario",
        "version": 1,
        "name": "minimal",
        "depot": {"x": 0, "y": 0},
        "fleet": {"vehicles": 2, "capacity": 10, "speed": 30, "shift_length": 300},
        "customers": [
            {"id": 1, "x": 1.5, "y": 2, "demand": 3, "ready": 0, "due": 100, "service": 5},
            {"id": 2, "x": -4, "y": 0.25, "demand": 2, "ready": 30, "due": 90, "service": 0},
        ],
    }


class ScenarioJsonTest(unittest.TestCase):
    def test_round_trip_through_dict_and_text(self):
        for layout in ("uniform", "clustered"):
            sc = generate(customers=20, layout=layout, seed=11)
            self.assertEqual(Scenario.from_dict(sc.to_dict()), sc)
            again = Scenario.loads(sc.dumps())
            self.assertEqual(again, sc)
            self.assertEqual(again.generator, sc.generator)
            self.assertEqual(again.dumps(), sc.dumps())

    def test_round_trip_through_file(self):
        sc = generate(customers=15, layout="clustered", seed=2)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scenario.json")
            save_scenario(sc, path)
            self.assertEqual(load_scenario(path), sc)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["format"], "vrptw-scenario")

    def test_hand_written_scenario_without_generator(self):
        sc = make_scenario([(1, 1), (2, 2)])
        self.assertEqual(Scenario.loads(sc.dumps()), sc)
        self.assertNotIn("generator", sc.to_dict())

    def test_optional_customer_fields_have_defaults(self):
        data = minimal_dict()
        data["customers"] = [{"id": 5, "x": 1, "y": 1, "demand": 1}]
        sc = Scenario.from_dict(data)
        c = sc.customer(5)
        self.assertEqual((c.ready, c.due, c.service), (0, 300, 0))

    def test_customer_lookup(self):
        sc = Scenario.from_dict(minimal_dict())
        self.assertEqual(sc.customer(2).ready, 30)
        with self.assertRaises(KeyError):
            sc.customer(99)

    def test_rejects_malformed_data(self):
        cases = {
            "duplicate id": lambda d: d["customers"].append(dict(d["customers"][0])),
            "empty window": lambda d: d["customers"][0].update(ready=50, due=10),
            "text number": lambda d: d["customers"][0].update(x="1.5"),
            "bool number": lambda d: d["customers"][0].update(demand=True),
            "missing coordinate": lambda d: d["customers"][0].pop("y"),
            "negative demand": lambda d: d["customers"][0].update(demand=-1),
            "zero vehicles": lambda d: d["fleet"].update(vehicles=0),
            "float vehicles": lambda d: d["fleet"].update(vehicles=2.5),
            "zero speed": lambda d: d["fleet"].update(speed=0),
            "non-positive id": lambda d: d["customers"][0].update(id=0),
            "wrong format": lambda d: d.update(format="something-else"),
            "future version": lambda d: d.update(version=99),
            "zero version": lambda d: d.update(version=0),
            "bool version": lambda d: d.update(version=True),
            "customers not list": lambda d: d.update(customers={}),
            "integer too large for a float": lambda d: d["depot"].update(x=10**400),
            "non-string name": lambda d: d.update(name=7),
            "falsy non-object generator": lambda d: d.update(generator=[]),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                data = minimal_dict()
                mutate(data)
                with self.assertRaises(ScenarioError):
                    Scenario.from_dict(data)

    def test_rejects_invalid_json_text(self):
        with self.assertRaises(ScenarioError):
            Scenario.loads("{not json")


if __name__ == "__main__":
    unittest.main()
