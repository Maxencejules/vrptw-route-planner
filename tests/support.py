"""Shared helpers for the test suite.

Importing this module puts ``src/`` on ``sys.path`` so the tests run with
``python -m unittest discover -s tests`` from the repository root without
installing the package.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from vrptw import Customer, Depot, Fleet, Instance, Scenario  # noqa: E402
from vrptw.validation import exhaustive_tiny  # noqa: E402


def make_scenario(
    points,
    *,
    depot=(0.0, 0.0),
    vehicles=1,
    capacity=100,
    speed=60.0,
    shift=1000,
    demands=None,
    windows=None,
    services=None,
    name="hand-made",
):
    """Build a scenario from a list of (x, y) points.

    With the default speed of 60 km/h one kilometre takes one minute, which
    keeps hand calculations simple. Customer ids are 1..n in list order.
    """
    customers = []
    for k, (x, y) in enumerate(points):
        ready, due = windows[k] if windows else (0, shift)
        customers.append(
            Customer(
                id=k + 1,
                x=x,
                y=y,
                demand=demands[k] if demands else 1,
                ready=ready,
                due=due,
                service=services[k] if services else 0,
            )
        )
    return Scenario(
        name=name,
        depot=Depot(*depot),
        fleet=Fleet(vehicles=vehicles, capacity=capacity, speed=speed, shift_length=shift),
        customers=customers,
    )


def brute_force_optimum(scenario):
    """Exact minimum total distance by enumeration (tiny instances only).

    Every ordering of the customers is cut into consecutive routes in every
    possible way; plans with more routes than vehicles or an infeasible
    route are skipped. Returns ``None`` if no plan is feasible.
    """
    return exhaustive_tiny(scenario).distance
