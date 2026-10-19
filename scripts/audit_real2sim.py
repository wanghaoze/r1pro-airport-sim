"""Audit every original real episode against an explicit simulation model."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.real2sim.trajectory import from_record, sha256, write_json
from r1pro_teleop.real2sim import r1pro_map
from r1pro_teleop.real2sim.backends import MujocoBackend


def audit(manifests, model, output):
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    backend = MujocoBackend(model, r1pro_map())
    rows = []
    identities = set()
    for path in manifests:
        manifest = json.loads(Path(path).read_text())
        for record in manifest["episodes"]:
            key = (record["dataset"], record["episode_index"])
            if key in identities: raise ValueError("real2sim_duplicate_audit_episode")
            identities.add(key)
            t = from_record(record)
            limits = backend.limit_audit(t)
            rows.append(dict(dataset=record["dataset"], episode_index=record["episode_index"],
                        split=record["split"], prompt=record["prompt"], frames=len(t.timestamps),
                        duration_s=float(t.seconds[-1]), limits=limits,
                        torso_peak_to_peak_rad=np.ptp(t.feedback[:, 16:], axis=0).tolist(),
                        parquet_sha256=record["parquet_sha256"]))
    write_json(output, dict(schema="real2sim_source_audit/1", model=str(model), model_sha256=sha256(model),
               manifests={str(p): sha256(p) for p in manifests}, episodes=rows,
               total_episodes=len(rows), total_original_frames=sum(e["frames"] for e in rows),
               episodes_with_outside_commands=sum(any(j["command"]["outside_count"] for j in e["limits"]) for e in rows),
               episodes_with_outside_feedback=sum(any(j["feedback"]["outside_count"] for j in e["limits"]) for e in rows),
               task_success_not_evaluated=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", action="append", required=True)
    p.add_argument("--model", required=True); p.add_argument("--output", required=True)
    args = p.parse_args(); audit(args.manifest, args.model, args.output)
