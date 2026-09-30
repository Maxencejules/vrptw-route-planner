"""Independently audit a saved solution; exit 0 feasible, 1 rejected, 2 bad input."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vrptw.model import load_scenario  # noqa: E402
from vrptw.validation import audit_routes  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--solution", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        scenario = load_scenario(args.scenario)
        data = json.loads(args.solution.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("routes"), list):
            raise ValueError("solution must contain a routes list")
        if not all(isinstance(route, list) for route in data["routes"]):
            raise ValueError("each route must be a list")
        summary = data.get("summary", {})
        if not isinstance(summary, dict):
            raise ValueError("summary must be an object")
        # Production solution JSON rounds totals to three decimals.
        audit = audit_routes(scenario, data["routes"],
                             claimed_distance=summary.get("total_distance"),
                             distance_tolerance=0.000500001)
        print(json.dumps(asdict(audit), allow_nan=False))
        return 0 if audit.feasible else 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
