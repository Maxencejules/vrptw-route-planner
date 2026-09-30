"""Plain-text report of a plan."""

from __future__ import annotations

from .model import Scenario
from .solution import Evaluation, Solution


def format_report(
    scenario: Scenario, solution: Solution, ev: Evaluation, show_timeline: bool = True
) -> str:
    f = scenario.fleet
    method = solution.solver or "unknown"
    construction_options = {k: v for k, v in solution.options.items() if k != "max_moves"}
    if construction_options:
        method += " (" + ", ".join(f"{k}={v}" for k, v in construction_options.items()) + ")"
    if solution.improved:
        method += " + local search"
    lines = [
        f"Scenario   {scenario.name}",
        f"Customers  {len(scenario.customers)} (total demand {scenario.total_demand:g})",
        f"Fleet      {f.vehicles} vehicles, capacity {f.capacity:g}, "
        f"speed {f.speed:g} km/h, shift {f.shift_length:g} min",
        f"Solver     {method}",
        f"Distance   {ev.total_distance:.2f} km",
        f"Vehicles   {ev.vehicles_used} of {ev.vehicles_available}",
        f"Served     {ev.served} of {ev.customers}",
        f"Feasible   {'yes' if ev.feasible else 'no'}",
    ]
    if solution.search:
        s = solution.search
        moves = s.get("moves", {})
        detail = ", ".join(f"{k} {v}" for k, v in moves.items())
        lines.append(
            f"Search     moves applied: {sum(moves.values())} ({detail}); "
            f"{s.get('start_distance', 0):.2f} -> {s.get('end_distance', 0):.2f} km"
        )
        if s.get("stopped_early"):
            lines.append(f"Search     accepted-move budget exhausted ({solution.options.get('max_moves', 'unknown')}); "
                         "local search stopped before checking every neighbourhood")
    for v in ev.violations:
        lines.append(f"  violation: {v}")

    for t in ev.routes:
        lines.append("")
        lines.append(
            f"Vehicle {t.vehicle}: {len(t.stops)} stops, {t.distance:.2f} km, "
            f"load {t.load:g}/{f.capacity:g}, leaves {t.leave_depot:.1f}, "
            f"returns {t.back_at_depot:.1f}"
        )
        if not show_timeline:
            lines.append("  route: depot -> " + " -> ".join(map(str, t.customers)) + " -> depot")
            continue
        lines.append(
            f"  {'#':>3} {'customer':>8} {'window':>11} {'arrive':>7} "
            f"{'wait':>6} {'start':>7} {'depart':>7} {'load':>6}"
        )
        for n, s in enumerate(t.stops, 1):
            c = scenario.customer(s.customer)
            window = f"{c.ready:g}-{c.due:g}"
            lines.append(
                f"  {n:>3} {s.customer:>8} {window:>11} {s.arrival:>7.1f} "
                f"{s.wait:>6.1f} {s.start:>7.1f} {s.departure:>7.1f} {s.load:>6g}"
            )
    if solution.unassigned:
        lines.append("")
        lines.append("Unassigned customers: " + ", ".join(map(str, solution.unassigned)))
    return "\n".join(lines) + "\n"
