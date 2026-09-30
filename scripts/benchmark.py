"""Offline C101 demo: independently checked routes, quality and resource record."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
import tracemalloc
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vrptw.benchmark import load_solomon  # noqa: E402
from vrptw.planner import solve  # noqa: E402
from vrptw.validation import audit_routes  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "benchmark")
    parser.add_argument("--max-moves", type=int, default=1000,
                        help="local-search accepted-move budget; default 1000")
    args = parser.parse_args(argv)
    if args.max_moves < 0:
        parser.error("--max-moves must be nonnegative")
    path = ROOT / "benchmarks" / "c101.txt"
    reference = json.loads((path.with_suffix(".reference.json")).read_text(encoding="utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != reference["instance_sha256"]:
        raise ValueError("C101 fixture hash differs from recorded official input")
    scenario = load_solomon(path)
    if scenario.name != reference["instance"] or len(scenario.customers) != reference["customers"]:
        raise ValueError("benchmark must use the full recorded 100-customer C101 instance")
    reference_audit = audit_routes(scenario, reference["routes"],
                                   claimed_distance=reference["distance"], distance_tolerance=0.005)
    if not reference_audit.feasible or reference_audit.vehicles_used != reference["vehicles"]:
        raise ValueError(f"published route reference failed independent audit: {reference_audit}")
    records = []
    for solver, metric in (("nearest", "time"), ("nearest", "distance"), ("savings", "time")):
        for improved in (False, True):
            # One fresh matrix per run. Timing includes tracing overhead and
            # construction/improvement, but not import, IO or independent audit.
            tracemalloc.start()
            start = time.perf_counter()
            try:
                solution = solve(scenario, solver, nn_metric=metric, improve=improved,
                                 max_moves=args.max_moves)
                runtime = time.perf_counter() - start
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            audit = audit_routes(scenario, solution.routes)
            record = {
                "solver": solver,
                "nn_metric": metric if solver == "nearest" else None,
                "improved": improved,
                "seed": None,  # deterministic algorithms; no random restart
                "max_moves": args.max_moves if improved else None,
                "search": solution.search,
                "runtime_seconds": runtime,
                "peak_python_bytes": peak,
                **asdict(audit),
                "routes": solution.routes,
                "unassigned": solution.unassigned,
            }
            records.append(record)
            label = solver + (f"/{metric}" if solver == "nearest" else "")
            print(f"{label:17} improve={str(improved):5} feasible={str(audit.feasible):5} "
                  f"vehicles={audit.vehicles_used:2} distance={audit.total_distance:9.2f} "
                  f"time={runtime:.3f}s peak_python={peak}B")
    report = {
        "format": "vrptw-benchmark-v1",
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                        "os": platform.system(), "os_release": platform.release(),
                        "machine": platform.machine(), "processor": platform.processor()},
        "measurement": "single run per variant; perf_counter with tracemalloc enabled; Python allocation peak, not RSS",
        "solver_objective": "total distance only, subject to fleet size and hard constraints",
        "instance_sha256": digest,
        "reference": reference,
        "reference_audit": asdict(reference_audit),
        "runs": records,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    fields = ("solver", "nn_metric", "improved", "seed", "max_moves", "feasible", "vehicles_used",
              "total_distance", "runtime_seconds", "peak_python_bytes")
    with (args.out / "results.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"Published reference: {reference['vehicles']} vehicles / {reference['distance']:.2f}; "
          "vehicles-first objective, best known, not a proof of optimality.")
    print(f"Wrote {args.out / 'results.json'} and results.csv")
    return 0 if all(r["feasible"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
