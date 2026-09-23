"""Nearest-neighbour route construction.

Routes are built one at a time. From the vehicle's current position the
closest customer (by the chosen metric, see ``nearest_neighbour``) that can
still be appended without breaking capacity, its time window or the
return-by-end-of-shift limit is visited next. When no
customer fits, the route returns to the depot and the next vehicle starts.

If every vehicle has been used and customers remain, each of them (earliest
due time first) is inserted at the cheapest position of an existing route
where it fits. Customers that fit nowhere are returned as unassigned.
"""

from __future__ import annotations

from .instance import EPS, Instance

METRICS = ("distance", "time")


def nearest_neighbour(
    inst: Instance, metric: str = "time"
) -> tuple[list[list[int]], list[int]]:
    """Return ``(routes, unassigned_nodes)``.

    ``metric="distance"`` picks the geographically closest candidate.
    ``metric="time"`` picks the candidate whose service can start soonest,
    which counts waiting for a window to open as well as driving.
    Ties are broken by earlier due time, then by node number.
    """
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    dist, travel = inst.dist, inst.travel
    ready, due, service, demand = inst.ready, inst.due, inst.service, inst.demand

    pending = set(range(1, inst.size))
    routes: list[list[int]] = []
    while pending and len(routes) < inst.vehicles:
        route: list[int] = []
        here, clock, load = 0, 0.0, 0.0
        while True:
            best = None
            best_key = None
            best_start = 0.0
            for node in pending:
                if load + demand[node] > inst.capacity + EPS:
                    continue
                arrive = clock + travel[here][node]
                if arrive > due[node] + EPS:
                    continue
                start = arrive if arrive > ready[node] else ready[node]
                if start + service[node] + travel[node][0] > inst.shift + EPS:
                    continue
                gap = dist[here][node] if metric == "distance" else start - clock
                key = (gap, due[node], node)
                if best_key is None or key < best_key:
                    best, best_key, best_start = node, key, start
            if best is None:
                break
            route.append(best)
            pending.discard(best)
            load += demand[best]
            clock = best_start + service[best]
            here = best
        if not route:
            break
        routes.append(route)
    left_over = _insert_left_over(inst, routes, sorted(pending, key=lambda n: (due[n], n)))
    return routes, sorted(left_over)


def _insert_left_over(inst: Instance, routes: list[list[int]], nodes: list[int]) -> list[int]:
    """Cheapest feasible insertion of ``nodes`` into ``routes`` (in place)."""
    d = inst.dist
    unplaced = []
    for u in nodes:
        best = None
        for r in routes:
            if inst.route_load(r) + inst.demand[u] > inst.capacity + EPS:
                continue
            for k in range(len(r) + 1):
                p = r[k - 1] if k > 0 else 0
                n = r[k] if k < len(r) else 0
                cost = d[p][u] + d[u][n] - d[p][n]
                if best is not None and cost >= best[0]:
                    continue
                trial = r[:k] + [u] + r[k:]
                if inst.route_feasible(trial):
                    best = (cost, r, k)
        if best is None:
            unplaced.append(u)
        else:
            _, r, k = best
            r.insert(k, u)
    return unplaced
