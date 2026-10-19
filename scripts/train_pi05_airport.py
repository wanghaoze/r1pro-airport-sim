"""Run project-owned pi05 mobile19 LoRA extension inside a non-base Conda env."""
from pathlib import Path
import argparse
import dataclasses
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.training import TrainingSpec, launch_training


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--normalize-only", action="store_true")
    parser.add_argument("--dagger-manifest", help="Verified train-only aggregation manifest for a new round")
    parser.add_argument("--parent-status", help="Completed parent training_status.json; uses its saved params")
    parser.add_argument("--dagger-ratio", type=float, help="Fraction of supervised chunks from DAgger, in (0,1)")
    args = parser.parse_args()
    values = json.loads(Path(args.config).read_text(encoding="utf-8"))
    spec = TrainingSpec(**values)
    overrides = {}
    if args.dagger_manifest is not None:
        overrides["aggregation_manifest"] = args.dagger_manifest
    if args.parent_status is not None:
        parent = json.loads(Path(args.parent_status).read_text(encoding="utf-8"))
        overrides.update(parent_trained_status=args.parent_status,
                         base_params=str(Path(parent["checkpoint"]) / "params"))
    if args.dagger_ratio is not None:
        overrides["dagger_mix_ratio"] = args.dagger_ratio
    spec = dataclasses.replace(spec, **overrides)
    print(json.dumps(launch_training(spec, normalize_only=args.normalize_only), indent=2))


if __name__ == "__main__":
    main()
