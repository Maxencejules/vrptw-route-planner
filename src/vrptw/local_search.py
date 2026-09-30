"""Local-search improvement for a set of feasible routes.

Three neighbourhoods are searched, in this order:

* ``2-opt``    reverse a segment inside one route;
* ``relocate`` move one customer to any position in another route;
* ``exchange`` swap two customers that are on different routes.

A move is applied only when it shortens the total distance by more than a
small tolerance and every route it touches stays feasible (capacity, time
windows, end of shift). The first such move found is applied and the search
starts again from the first neighbourhood; it stops when no neighbourhood
has an improving move. Total distance therefore never increases and
feasibility is preserved. A route emptied by ``relocate`` is dropped, which
frees a vehicle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .instance import EPS, Instance

# Minimum distance reduction (km) for a move to count as an improvement.
MIN_GAIN = 1e-9


@dataclass
class SearchStats:
    start_distance: float = 0.0
    end_distance: float = 0.0
    moves: dict[str, int] = field(
        default_factory=lambda: {"2-opt": 0, "relocate": 0, "exchange": 0}
    )
    stopped_early: bool = False

    @property
    def total_moves(self) -> int:
        return sum(self.moves.values())

    def to_dict(self) -> dict:
        return {
            "start_distance": round(self.start_distance, 3),
            "end_distance": round(self.end_distance, 3),
            "moves": dict(self.moves),
            "stopped_early": self.stopped_early,
        }


def improve(
    inst: Instance, routes: Sequence[Sequence[int]], max_moves: int = 100_000
) -> tuple[list[list[int]], SearchStats]:
    """Return improved copies of ``routes`` and statistics about the search.

    Raises ``ValueError`` if any input route is infeasible, because the
    neighbourhoods only guarantee feasibility when they start from it.
    """
    work = [list(r) for r in routes if r]
    if isinstance(max_moves, bool) or not isinstance(max_moves, int) or max_moves < 0:
        raise ValueError("max_moves must be a non-negative integer")
    for pos, r in enumerate(work, 1):
        if not inst.route_feasible(r):
            raise ValueError(f"route {pos} is infeasible; local search needs feasible routes")
    stats = SearchStats(start_distance=inst.total_distance(work))
    if max_moves == 0:
        stats.end_distance = stats.start_distance
        stats.stopped_early = True
        return work, stats
    loads = [inst.route_load(r) for r in work]
    neighbourhoods = (
        ("2-opt", _two_opt),
        ("relocate", _relocate),
        ("exchange", _exchange),
    )
    applied = 0
    while True:
        for name, search in neighbourhoods:
            if search(inst, work, loads):
                stats.moves[name] += 1
                applied += 1
                break
        else:
            break
        if applied >= max_moves:
            stats.stopped_early = True
            break
    stats.end_distance = inst.total_distance(work)
    return work, stats


def _two_opt(inst: Instance, routes: list[list[int]], loads: list[float]) -> bool:
    d = inst.dist
    for r in routes:
        path = [0] + r + [0]
        m = len(r)
        for i in range(1, m):
            a, b = path[i - 1], path[i]
            for j in range(i + 1, m + 1):
                c, e = path[j], path[j + 1]
                gain = d[a][b] + d[c][e] - d[a][c] - d[b][e]
                if gain <= MIN_GAIN:
                    continue
                candidate = r[: i - 1] + r[i - 1 : j][::-1] + r[j:]
                if _ends_in_time(inst, candidate):
                    r[:] = candidate
                    return True
    return False


def _relocate(inst: Instance, routes: list[list[int]], loads: list[float]) -> bool:
    d = inst.dist
    demand = inst.demand
    for src, r1 in enumerate(routes):
        for i, u in enumerate(r1):
            prev = r1[i - 1] if i > 0 else 0
            nxt = r1[i + 1] if i + 1 < len(r1) else 0
            removal_gain = d[prev][u] + d[u][nxt] - d[prev][nxt]
            for dst, r2 in enumerate(routes):
                if dst == src or loads[dst] + demand[u] > inst.capacity + EPS:
                    continue
                for k in range(len(r2) + 1):
                    p = r2[k - 1] if k > 0 else 0
                    n = r2[k] if k < len(r2) else 0
                    gain = removal_gain - (d[p][u] + d[u][n] - d[p][n])
                    if gain <= MIN_GAIN:
                        continue
                    new_dst = r2[:k] + [u] + r2[k:]
                    new_src = r1[:i] + r1[i + 1 :]
                    if not (_times_ok(inst, new_dst) and _times_ok(inst, new_src)):
                        continue
                    r1[:] = new_src
                    r2[:] = new_dst
                    loads[src] -= demand[u]
                    loads[dst] += demand[u]
                    if not r1:
                        del routes[src]
                        del loads[src]
                    return True
    return False


def _exchange(inst: Instance, routes: list[list[int]], loads: list[float]) -> bool:
    d = inst.dist
    demand = inst.demand
    cap = inst.capacity + EPS
    for a in range(len(routes)):
        r1 = routes[a]
        for b in range(a + 1, len(routes)):
            r2 = routes[b]
            for i, u in enumerate(r1):
                p1 = r1[i - 1] if i > 0 else 0
                n1 = r1[i + 1] if i + 1 < len(r1) else 0
                for j, v in enumerate(r2):
                    shift = demand[v] - demand[u]
                    if loads[a] + shift > cap or loads[b] - shift > cap:
                        continue
                    p2 = r2[j - 1] if j > 0 else 0
                    n2 = r2[j + 1] if j + 1 < len(r2) else 0
                    gain = (
                        d[p1][u] + d[u][n1] + d[p2][v] + d[v][n2]
                        - d[p1][v] - d[v][n1] - d[p2][u] - d[u][n2]
                    )
                    if gain <= MIN_GAIN:
                        continue
                    new1 = r1[:i] + [v] + r1[i + 1 :]
                    new2 = r2[:j] + [u] + r2[j + 1 :]
                    if not (_times_ok(inst, new1) and _times_ok(inst, new2)):
                        continue
                    r1[:] = new1
                    r2[:] = new2
                    loads[a] += shift
                    loads[b] -= shift
                    return True
    return False


def _times_ok(inst: Instance, route: Sequence[int]) -> bool:
    return not route or _ends_in_time(inst, route)


def _ends_in_time(inst: Instance, route: Sequence[int]) -> bool:
    end = inst.return_time(route)
    return end is not None and end <= inst.shift + EPS
