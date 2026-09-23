# vrptw-route-planner

A command-line tool and Python package for the capacitated vehicle routing
problem with time windows (CVRPTW). It generates random scenarios, builds
routes with two construction heuristics, can improve them with local search,
checks every constraint, and prints a per-stop timeline. It uses only the
Python standard library.

## Problem model

- **Depot**: one, at a point `(x, y)` on a flat plane (kilometres).
- **Fleet**: `vehicles` identical vehicles with a `capacity`, a `speed` in
  km/h and a `shift_length` in minutes.
- **Customers**: `id`, `x`, `y`, `demand`, a time window `[ready, due]` in
  minutes from the start of the shift, and a `service` time in minutes.
- **Distance** is Euclidean. **Travel time** in minutes is
  `60 * distance_km / speed_kmh`.
- **Rules for a feasible plan**:
  - vehicles leave the depot no earlier than time 0;
  - a vehicle that arrives before `ready` waits;
  - service must start no later than `due`;
  - each vehicle must be back at the depot by `shift_length`;
  - the demand served on one route must not exceed `capacity`;
  - every customer is visited exactly once;
  - there are no more routes than vehicles.
- The solvers minimise **total distance**. The number of vehicles used is
  reported too, but it is not an objective.

## Requirements

- Python 3.10 or newer. The code uses only the standard library.
- Tested only with Python 3.12.3 on Linux.
- There are no third-party dependencies, so `requirements.txt` holds only a
  comment.
- Nothing needs installing. Run the commands below from the repository root
  with `PYTHONPATH=src`.

## Usage

### Generate a scenario

```
PYTHONPATH=src python3 -m vrptw generate --customers 30 --layout clustered --seed 2 --out out/scenario.json
```

Without `--out`, the scenario JSON goes to standard output. The options are:

| option | default | meaning |
|---|---|---|
| `--customers N` | 25 | number of customers |
| `--layout` | `uniform` | `uniform`: points spread over the square. `clustered`: points drawn from Gaussian clusters |
| `--seed S` | 1 | random seed; the same settings and seed give an identical file |
| `--area KM` | 50 | side of the square region |
| `--clusters K`, `--spread KM` | 4, 4.0 | number of clusters and their standard deviation (clustered layout) |
| `--depot` | `center` | `center` or `corner` (0, 0) |
| `--demand LOW,HIGH` | 1,10 | integer demand range |
| `--service LOW,HIGH` | 5,15 | service time range, minutes |
| `--window LOW,HIGH` | 60,180 | time-window width range, minutes |
| `--capacity Q` | 60 | vehicle capacity |
| `--vehicles V` | derived | fleet size. The default is `max(3, 2 * ceil(total_demand / capacity), ceil(customers / 3))` |
| `--speed KMH` | 40 | vehicle speed |
| `--shift MIN` | 480 | shift length |

The generator places each customer's time window so that a vehicle driving
straight from the depot can serve it and return before the end of the
shift. If the settings make that impossible (for example, a very short
shift), it stops with an error. The default fleet size leaves plenty of
room. Time windows can force more routes than the capacity bound suggests,
and the fleet size is only an upper limit.

### Solve

```
PYTHONPATH=src python3 -m vrptw solve --scenario examples/uniform-20.json --solver savings --improve --json out/plan.json
```

- `--solver` is `nearest` (the default) or `savings`.
- `--improve` runs local search after construction.
- `--nn-metric` is `time` (the default) or `distance`, and applies to the
  nearest solver only.
- `--json OUT` also writes the plan and its timeline as JSON.
- `--no-timeline` prints each route as a list of stops instead of the full
  timeline.

Here is the start of the output of the command above, copied from a run of
that exact command. Times are minutes from the start of the shift.

```
Scenario   uniform-n20-seed1
Customers  20 (total demand 132)
Fleet      7 vehicles, capacity 60, speed 40 km/h, shift 480 min
Solver     savings + local search
Distance   291.00 km
Vehicles   4 of 7
Served     20 of 20
Feasible   yes
Search     moves applied: 1 (2-opt 1, relocate 0, exchange 0); 292.02 -> 291.00 km

Vehicle 1: 7 stops, 89.77 km, load 51/60, leaves 21.9, returns 363.5
    # customer      window  arrive   wait   start  depart   load
    1       19      43-174    47.6    0.0    47.6    61.6      6
    2        6      25-171    70.9    0.0    70.9    81.9     13
    3       12      64-189    90.6    0.0    90.6    97.6     16
    4       10       3-124   124.0    0.0   124.0   129.0     24
    5        7     108-263   139.7    0.0   139.7   154.7     33
    6       20     304-427   171.1  132.9   304.0   315.0     42
    7        2     308-433   325.5    0.0   325.5   336.5     51
...
```

In the timeline, `load` is the demand delivered so far on that route. Each
vehicle leaves the depot as late as it can without starting any stop after
its due time and without coming back later than it would by leaving at
time 0. The delay is the route's forward time slack, capped by its total
waiting (Savelsbergh, 1992). The departure time does not change the route's
distance, return time or feasibility. In a plan that meets every time
window, a wait that is still shown cannot be removed by leaving at another
time, because an earlier stop on that route already starts exactly at its
due time (for vehicle 1 above, customer 10 at 124.0). Only a different stop
order could remove it. When `check` evaluates a plan in which a stop is
already late, the departure is not delayed in a way that would make that
stop any later.

### Check a solution file

```
PYTHONPATH=src python3 -m vrptw check --scenario examples/uniform-20.json --solution out/plan.json
```

This re-evaluates the routes stored in the solution file against the
scenario and prints the same report. Any violations are listed, for
example a missed due time, a capacity overrun, a late return, a customer
missing or visited twice, an unknown id, or too many routes.

### Compare all solver variants

```
PYTHONPATH=src python3 -m vrptw compare --scenario examples/clustered-30.json
```

This runs nearest (time metric), nearest (distance metric) and savings, each
with and without local search, and prints one table row per run.

### Exit status

| status | meaning |
|---|---|
| 0 | the command worked and the plan is feasible |
| 1 | a plan was produced or checked, but it breaks at least one constraint |
| 2 | the input is unusable: an unreadable file, an invalid scenario or solution file, or, for `solve` and `compare` only, a customer that no vehicle could serve (for example, demand above capacity) |

`check` does not refuse a scenario with such a customer. It evaluates the
routes it is given, lists the problem as a violation (for example, a load
above capacity) and exits with status 1.

## Algorithms

**Nearest neighbour** (`--solver nearest`) builds one route at a time. From
the current stop it moves to the closest unvisited customer that can still be
appended without breaking capacity, the customer's due time, or the return
to the depot by the end of the shift.

- With `--nn-metric time`, "closest" means the customer whose service could
  start soonest. That counts waiting for a window to open as well as
  driving.
- With `--nn-metric distance`, it means the geographically closest customer.
- If every vehicle has been used and customers remain, each of them is
  inserted at its cheapest feasible position in an existing route. Any that
  still do not fit are reported as unassigned, and the plan is infeasible.

**Savings** (`--solver savings`) is the parallel Clarke-Wright method.

- Each customer starts on its own out-and-back route.
- Customer pairs are processed in decreasing order of
  `d(depot,i) + d(depot,j) - d(i,j)`.
- Two routes are joined when `i` and `j` sit at the ends of different routes
  and the joined route passes the capacity, time-window and shift checks.
  A route may be reversed to bring the two ends together.
- The fleet size is not enforced during construction. If the result needs
  more routes than there are vehicles, the evaluation reports it.

**Local search** (`--improve`) repeatedly applies the first improving move
it finds. It searches three neighbourhoods, in this order:

- *2-opt*: reverse a segment within a route;
- *relocate*: move one customer to another route;
- *exchange*: swap two customers on different routes.

A move is applied only if it reduces total distance and every route it
touches stays feasible. Distance therefore never goes up and feasibility is
kept. A route emptied by a relocation is removed. The search stops when no
neighbourhood has an improving move, or after 100,000 moves (a safety limit).

## File formats

A scenario file (see `examples/`) looks like this:

```json
{
  "format": "vrptw-scenario",
  "version": 1,
  "name": "uniform-n20-seed1",
  "units": {"distance": "km", "time": "min", "speed": "km/h"},
  "depot": {"x": 25.0, "y": 25.0},
  "fleet": {"vehicles": 7, "capacity": 60, "speed": 40.0, "shift_length": 480},
  "generator": {"customers": 20, "layout": "uniform", "seed": 1, "...": "..."},
  "customers": [
    {"id": 1, "x": 6.72, "y": 42.37, "demand": 5, "ready": 92, "due": 248, "service": 6},
    ...
  ]
}
```

- Customer ids must be unique positive integers.
- In hand-written files `ready`, `due` and `service` are optional. They
  default to 0, `shift_length` and 0.
- The `generator` block records the settings that produced the file, and is
  optional.

A solution file written by `--json` contains:

- `solver`, `improved` and `options`;
- `routes`: lists of customer ids in visiting order;
- `unassigned`;
- a `summary` with the distance, vehicles used, the feasible flag and any
  violations;
- the local-search statistics;
- the full `timeline`.

Only `routes` is needed by `check`, so a file such as
`{"routes": [[3, 1], [2]]}` can be checked. The `format` field may be left
out, but if it is present it must be `"vrptw-solution"`.

## Example scenarios

The three files in `examples/` are synthetic. They were produced by this
program, contain no real places or addresses, and can be regenerated with
these commands:

```
PYTHONPATH=src python3 -m vrptw generate --customers 20 --layout uniform --seed 1 --out examples/uniform-20.json
PYTHONPATH=src python3 -m vrptw generate --customers 30 --layout clustered --seed 2 --out examples/clustered-30.json
PYTHONPATH=src python3 -m vrptw generate --customers 50 --layout clustered --clusters 5 --depot corner --seed 3 --out examples/clustered-50-corner.json
```

These files are output of this program's generator. They contain no
third-party data, so no data license applies to them.

SHA256 sums of the committed files (from `sha256sum examples/*.json`). The
commands above regenerate them byte for byte:

```
cfbd7b429bfbe63df8b9d0909a9ea2252d6657dec98b9166a98e744eea27e7e4  examples/uniform-20.json
91ab4b563dd7e02ae4c579f629fa918d0117ba6b68596676089dd7e2cf8bbb4b  examples/clustered-30.json
eba7a6993c1f89a8cdf96aeba95fcd4cd8792d354cd7f27215b590be9c53c81f  examples/clustered-50-corner.json
```

## Results on the example scenarios

The numbers below come from one run of
`PYTHONPATH=src python3 -m vrptw compare --scenario examples/<file>.json` for
each file, using Python 3.12.3. The runs are deterministic, so repeating a
command should give the same table. Every plan listed was feasible.

`uniform-20.json` (20 customers, 7 vehicles available):

| solver | local search | distance km | vehicles | moves |
|---|---|---|---|---|
| nearest/time | no | 459.52 | 3 | - |
| nearest/time | yes | 305.85 | 3 | 18 |
| nearest/distance | no | 384.70 | 5 | - |
| nearest/distance | yes | 307.12 | 4 | 19 |
| savings | no | 292.02 | 4 | - |
| savings | yes | 291.00 | 4 | 1 |

`clustered-30.json` (30 customers, 10 vehicles available):

| solver | local search | distance km | vehicles | moves |
|---|---|---|---|---|
| nearest/time | no | 486.66 | 3 | - |
| nearest/time | yes | 284.32 | 3 | 26 |
| nearest/distance | no | 509.39 | 6 | - |
| nearest/distance | yes | 247.16 | 4 | 63 |
| savings | no | 250.15 | 4 | - |
| savings | yes | 243.56 | 4 | 6 |

`clustered-50-corner.json` (50 customers, 17 vehicles available):

| solver | local search | distance km | vehicles | moves |
|---|---|---|---|---|
| nearest/time | no | 821.73 | 6 | - |
| nearest/time | yes | 573.08 | 6 | 69 |
| nearest/distance | no | 810.55 | 8 | - |
| nearest/distance | yes | 529.75 | 5 | 81 |
| savings | no | 572.97 | 7 | - |
| savings | yes | 567.92 | 7 | 3 |

These are heuristic results. They say nothing about how far the plans are
from optimal.

## Tests

```
python3 -m unittest discover -s tests
```

Run this from the repository root. The test modules add `src/` to the import
path themselves, and no network access is needed. The latest run reported
`Ran 68 tests` and `OK`. The tests cover:

- generator determinism for a fixed seed;
- every solver variant, with and without local search, giving a feasible plan
  on uniform and clustered scenarios over several seeds;
- the same on generated layouts whose time windows stay open for a whole
  150-minute shift, so that only the end of the shift limits the routes;
- local search never increasing distance and keeping every route feasible;
- hand-checkable instances with known optimal distances, confirmed by a
  brute-force enumeration in the tests:
  - a 3 x 4 rectangle, optimum 14 km;
  - a capacity split, optimum 44 km;
  - a case where the time windows fix the visiting order, optimum 4 km;
  - a case where only the end of the shift keeps two customers on separate
    routes, optimum 40 km;
- the departure time in the timeline: the latest one that keeps every stop
  on time and the return unchanged;
- scenario and solution JSON round trips, and checking a file that holds
  only `routes`, and rejecting malformed solution files with exit status 2;
- every kind of constraint violation, and empty routes being ignored;
- infeasible input, such as demand above capacity, a window that closes
  before any vehicle can arrive, or no way back before the end of the shift;
- the command-line interface and its exit codes.

## Project layout

```
src/vrptw/
  model.py         scenario dataclasses, validation, JSON read/write
  instance.py      distance and travel-time matrices, route feasibility, unservable-customer check
  generator.py     seeded uniform / clustered scenario generator
  nearest.py       nearest-neighbour construction
  savings.py       Clarke-Wright savings construction
  local_search.py  2-opt, relocate and exchange improvement
  solution.py      solution type, evaluation and timelines, solution JSON
  planner.py       solve(): construction plus optional local search
  report.py        text report
  cli.py           argument parsing for generate / solve / check / compare
tests/             unittest suite (support.py holds shared helpers)
examples/          three generated scenarios
```

## Limitations

- These are heuristics. There is no exact solver, and results carry no
  optimality guarantee. The brute-force routine in the tests is only for
  instances of a few customers.
- The model has a single depot, identical vehicles, one route per vehicle,
  Euclidean distances and hard time windows. It has no breaks, no multiple
  trips, no pickups, and no soft windows or penalties.
- The savings solver can return more routes than there are vehicles. The
  plan is then marked infeasible rather than repaired.
- Local search scans each neighbourhood exhaustively and restarts after
  every move. It has not been tuned or measured on large instances. The
  largest scenarios used during development had 100 customers.

## References

- G. Clarke and J. W. Wright, "Scheduling of Vehicles from a Central Depot to
  a Number of Delivery Points", *Operations Research* 12(4), 1964.
- M. M. Solomon, "Algorithms for the Vehicle Routing and Scheduling Problems
  with Time Window Constraints", *Operations Research* 35(2), 1987. The
  `time` metric of the nearest solver is a simplified form of the
  time-oriented nearest neighbour described there.
- M. W. P. Savelsbergh, "The Vehicle Routing Problem with Time Windows:
  Minimizing Route Duration", *ORSA Journal on Computing* 4(2), 1992. The
  departure time in the timeline is computed from the forward time slack
  described there.
