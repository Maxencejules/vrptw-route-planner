"""Command-line interface: ``generate``, ``solve``, ``check`` and ``compare``.

Exit status: 0 when the command succeeded and the plan is feasible,
1 when a plan was produced or checked but violates a constraint,
2 for unusable input (unreadable file, invalid scenario or solution file,
and, for ``solve`` and ``compare``, a customer that no vehicle can serve).
``check`` does not refuse such a scenario: it evaluates the given routes and
reports the problem as a violation (exit status 1).
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .generator import DEPOT_POSITIONS, LAYOUTS, GeneratorSettings, generate
from .instance import Instance, InfeasibleScenarioError
from .model import ScenarioError, load_scenario, save_scenario
from .nearest import METRICS
from .planner import SOLVERS, solve
from .report import format_report
from .solution import SolutionError, evaluate, load_solution, save_solution


def _range(text: str) -> tuple[int, int]:
    try:
        lo, hi = (int(p) for p in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected LOW,HIGH integers, got {text!r}") from None
    return lo, hi


def build_parser() -> argparse.ArgumentParser:
    defaults = GeneratorSettings()
    parser = argparse.ArgumentParser(
        prog="vrptw",
        description="Generate and solve capacitated vehicle routing problems with time windows.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="create a random scenario JSON file")
    g.add_argument("--customers", type=int, default=defaults.customers)
    g.add_argument("--layout", choices=LAYOUTS, default=defaults.layout)
    g.add_argument("--seed", type=int, default=defaults.seed)
    g.add_argument("--area", type=float, default=defaults.area, help="side of the square region, km")
    g.add_argument("--clusters", type=int, default=defaults.clusters)
    g.add_argument("--spread", type=float, default=defaults.cluster_spread,
                   help="cluster standard deviation, km")
    g.add_argument("--depot", choices=DEPOT_POSITIONS, default=defaults.depot)
    g.add_argument("--demand", type=_range, default=defaults.demand, metavar="LOW,HIGH")
    g.add_argument("--service", type=_range, default=defaults.service, metavar="LOW,HIGH",
                   help="service time range, minutes")
    g.add_argument("--window", type=_range, default=defaults.window, metavar="LOW,HIGH",
                   help="time-window width range, minutes")
    g.add_argument("--capacity", type=int, default=defaults.capacity)
    g.add_argument("--vehicles", type=int, default=None,
                   help="fleet size (default: derived from total demand)")
    g.add_argument("--speed", type=float, default=defaults.speed, help="km/h")
    g.add_argument("--shift", type=int, default=defaults.shift_length, help="shift length, minutes")
    g.add_argument("--out", help="output file (default: print to stdout)")

    s = sub.add_parser("solve", help="plan routes for a scenario")
    s.add_argument("--scenario", required=True, help="scenario JSON file")
    s.add_argument("--solver", choices=SOLVERS, default="nearest")
    s.add_argument("--improve", action="store_true", help="run local search after construction")
    s.add_argument("--nn-metric", choices=METRICS, default="time",
                   help="closeness measure for the nearest solver")
    s.add_argument("--json", metavar="OUT", help="also write the plan as JSON")
    s.add_argument("--no-timeline", action="store_true", help="print routes without stop times")

    c = sub.add_parser("check", help="evaluate a solution JSON file against a scenario")
    c.add_argument("--scenario", required=True)
    c.add_argument("--solution", required=True)
    c.add_argument("--no-timeline", action="store_true")

    m = sub.add_parser("compare", help="run every solver variant on a scenario and tabulate")
    m.add_argument("--scenario", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            return _generate(args)
        if args.command == "solve":
            return _solve(args)
        if args.command == "compare":
            return _compare(args)
        return _check(args)
    except (OSError, ScenarioError, SolutionError, InfeasibleScenarioError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _generate(args: argparse.Namespace) -> int:
    scenario = generate(
        customers=args.customers,
        layout=args.layout,
        seed=args.seed,
        area=args.area,
        clusters=args.clusters,
        cluster_spread=args.spread,
        depot=args.depot,
        demand=args.demand,
        service=args.service,
        window=args.window,
        capacity=args.capacity,
        vehicles=args.vehicles,
        speed=args.speed,
        shift_length=args.shift,
    )
    if args.out:
        save_scenario(scenario, args.out)
        print(
            f"wrote {args.out}: {len(scenario.customers)} customers, "
            f"{scenario.fleet.vehicles} vehicles, capacity {scenario.fleet.capacity:g}"
        )
    else:
        sys.stdout.write(scenario.dumps())
    return 0


def _solve(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    inst = Instance(scenario)
    solution = solve(scenario, args.solver, improve=args.improve, nn_metric=args.nn_metric, inst=inst)
    ev = evaluate(scenario, solution, inst)
    sys.stdout.write(format_report(scenario, solution, ev, show_timeline=not args.no_timeline))
    if args.json:
        save_solution(args.json, scenario, solution, ev)
        print(f"\nwrote {args.json}")
    return 0 if ev.feasible else 1


def _check(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    solution = load_solution(args.solution)
    ev = evaluate(scenario, solution)
    sys.stdout.write(format_report(scenario, solution, ev, show_timeline=not args.no_timeline))
    return 0 if ev.feasible else 1


COMPARE_VARIANTS = (
    ("nearest", "time"),
    ("nearest", "distance"),
    ("savings", None),
)


def _compare(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    inst = Instance(scenario)
    print(f"Scenario {scenario.name}: {len(scenario.customers)} customers, "
          f"{scenario.fleet.vehicles} vehicles available")
    header = f"{'solver':<18} {'search':<7} {'distance km':>12} {'vehicles':>9} {'feasible':>9} {'moves':>6}"
    print(header)
    print("-" * len(header))
    all_feasible = True
    for solver, metric in COMPARE_VARIANTS:
        label = solver if metric is None else f"{solver}/{metric}"
        for improve in (False, True):
            solution = solve(scenario, solver, improve=improve,
                             nn_metric=metric or "time", inst=inst)
            ev = evaluate(scenario, solution, inst)
            all_feasible = all_feasible and ev.feasible
            moves = sum(solution.search.get("moves", {}).values()) if improve else "-"
            print(f"{label:<18} {'yes' if improve else 'no':<7} {ev.total_distance:>12.2f} "
                  f"{ev.vehicles_used:>9} {'yes' if ev.feasible else 'no':>9} {moves!s:>6}")
    return 0 if all_feasible else 1
