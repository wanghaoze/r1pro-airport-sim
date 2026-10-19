"""CMA-ES on a bounded numeric space, only after a viable fresh-run seed exists."""
from pathlib import Path
import uuid
import numpy as np

from .common import BOUNDS, read, candidate, assert_campaign
from .campaign import evaluate
from ..airport_fsm.contracts import atomic_json


def search(root, seed_summary, space, *, generations=2, population=4, workers=2,
           repeats=1, timeout=1800, random_seed=0):
    import cma
    root = Path(root).resolve()
    assert_campaign(root)
    seed_summary = Path(seed_summary).resolve()
    seed_summary.relative_to(root / "experiments")
    record = read(seed_summary)
    if record.get("group") != "development" or record.get("origin") != "fresh" or record.get("stage"):
        raise ValueError("search_requires_fresh_development_seed")
    winner = record.get("winner")
    if not winner:
        raise ValueError("search_requires_viable_seed")
    incumbent = candidate(winner)
    if not space or generations < 1 or population < 4:
        raise ValueError("invalid_search_budget")
    keys = sorted(space)
    lo, hi, initial = [], [], []
    for key in keys:
        if key not in BOUNDS or len(space[key]) != 2:
            raise ValueError("forbidden_search_space")
        a, b = space[key]
        if not np.isfinite([a, b]).all() or not BOUNDS[key][0] <= a < b <= BOUNDS[key][1]:
            raise ValueError("search_space_out_of_bounds")
        value = incumbent["params"].get(key, 0.)
        if not a <= value <= b:
            raise ValueError("seed_outside_search_space")
        lo.append(a); hi.append(b); initial.append((value-a)/(b-a))
    lo, hi = np.asarray(lo), np.asarray(hi)
    search_id = "search_" + uuid.uuid4().hex[:12]
    directory = root / "searches" / search_id
    directory.mkdir(parents=True, exist_ok=False)
    atomic_json(directory / "plan.json", {"seed_summary": str(seed_summary), "space": space,
                                          "generations": generations, "population": population,
                                          "repeats": repeats, "random_seed": random_seed})
    # Scalar search is supported by using CMA's fixed companion coordinate.
    dim = len(keys)
    x0 = initial if dim > 1 else [initial[0], .5]
    options = {"bounds": [0., 1.], "popsize": population, "seed": random_seed + 1,
               "verbose": -9, "verb_log": 0, "maxiter": generations}
    if dim == 1:
        options["fixed_variables"] = {1: .5}
    optimizer = cma.CMAEvolutionStrategy(x0, .15, options)
    summaries = []
    for generation in range(generations):
        population_values = optimizer.ask()
        specs = [dict(incumbent, name="incumbent")]
        for i, values in enumerate(population_values):
            params = dict(incumbent["params"])
            params.update(zip(keys, (lo + np.asarray(values[:dim])*(hi-lo)).tolist()))
            specs.append({"name": f"g{generation}_p{i}", "strategy": incumbent["strategy"], "params": params})
        summary = evaluate(root, specs, run=f"{search_id}_g{generation}", workers=workers,
                           repeats=repeats, timeout=timeout)
        scores = {}
        for entry in summary["ranking"]:
            # One extra complete success dominates ALL possible time savings.
            successes = -entry["ranking_key"][0]
            count = len(entry["rows"])
            time_sum = min(entry["ranking_key"][1], count * 600.)
            scores[entry["candidate"]["name"]] = (count-successes) + time_sum/(count*600.+1.)
        optimizer.tell(population_values, [scores[s["name"]] for s in specs[1:]])
        best = summary["winner"]
        if best and scores[best["name"]] < scores["incumbent"]:
            incumbent = best
        summaries.append(summary["run"])
        atomic_json(directory / "progress.json", {"generations_done": generation+1,
                                                   "incumbent": incumbent, "running": generation+1 < generations})
    result = {"winner": incumbent, "runs": summaries, "requires_fresh_verification": True,
              "scope": "in-search comparisons only; no out-of-sample non-regression claim"}
    atomic_json(directory / "result.json", result)
    return result
