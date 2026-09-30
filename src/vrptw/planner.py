"""Single entry point that runs a construction solver and optional improvement."""

from __future__ import annotations

from .instance import Instance
from .local_search import improve as improve_routes
from .model import Scenario
from .nearest import nearest_neighbour
from .savings import clarke_wright
from .solution import Solution

SOLVERS = ("nearest", "savings")


def solve(
    scenario: Scenario,
    solver: str = "nearest",
    improve: bool = False,
    nn_metric: str = "time",
    inst: Instance | None = None,
    max_moves: int = 100_000,
) -> Solution:
    """Build a plan for ``scenario``.

    Raises ``InfeasibleScenarioError`` when some customer cannot be served
    even by a vehicle of its own (for example, demand above capacity).
    """
    if solver not in SOLVERS:
        raise ValueError(f"solver must be one of {', '.join(SOLVERS)}")
    inst = inst or Instance(scenario)
    inst.require_servable()

    options: dict = {}
    if solver == "nearest":
        routes, left_over = nearest_neighbour(inst, metric=nn_metric)
        options["nn_metric"] = nn_metric
    else:
        routes, left_over = clarke_wright(inst), []

    search: dict = {}
    if improve:
        routes, stats = improve_routes(inst, routes, max_moves=max_moves)
        options["max_moves"] = max_moves
        search = stats.to_dict()

    return Solution(
        routes=[[inst.ids[n] for n in r] for r in routes],
        unassigned=[inst.ids[n] for n in left_over],
        solver=solver,
        improved=improve,
        options=options,
        search=search,
    )
