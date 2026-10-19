"""Bounded server smoke: core tests precede this script; always writes status/evidence.

Use --source for a newly prepared registry pointing at this release's resources.
No training export, no production takeover, no automatic 400-scene expansion.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.experiments.common import read
from r1pro_teleop.experiments.tools import init_campaign, sweep, assess
from r1pro_teleop.airport_fsm.contracts import atomic_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True); p.add_argument("--output", required=True)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    root = Path(a.output)
    dev = ["airport_0004_20270920", "airport_0006_20270922"]
    regression = ["airport_0016_20270932"]
    holdout = ["airport_0007_20270923", "airport_0218_20271134"]
    init_campaign(a.source, root, dev, holdout, regression)
    atomic_json(root / "smoke_status.json", {"stage": "checkpoint"})
    baseline = {"name": "baseline", "strategy": "baseline", "params": {}}
    settled = sweep(root, [baseline], run="settled", stage="settled", workers=a.workers)
    checkpoints = [r["checkpoint"] for e in settled["ranking"] for r in e["rows"] if r.get("stage_passed")]
    if checkpoints:
        approach = sweep(root, [baseline], run="checkpoint_approach", stage="approach",
                         checkpoint=checkpoints[0], workers=1)
        atomic_json(root / "checkpoint_smoke.json", approach)
    atomic_json(root / "smoke_status.json", {"stage": "fresh_strategy_sweep"})
    result = sweep(root, read("configs/experiment_candidates.json"), run="strategies", workers=a.workers)
    assess(root, observation="Fresh strategy smoke completed; inspect per-scene outcomes, not the CLI exit code.",
           evidence=str(root / "experiments/strategies/summary.json"),
           hypothesis="Stand-off and candidate ordering may change approach feasibility; no guaranteed gain.",
           next_action="Review nested failures, then search only if a viable fresh seed exists; verify frozen winner.",
           outcome="partial" if result["winner"] else "failed")
    atomic_json(root / "smoke_status.json", {"stage": "completed", "winner": result["winner"],
                                            "training_export_enabled": False})


if __name__ == "__main__":
    main()
