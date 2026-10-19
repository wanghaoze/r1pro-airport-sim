"""Read-only diagnostic of static scene screens against v36 fixed400 outcomes.

The predeclared screens below use scene.json alone. They are not candidate
resampling rules or measures of actual trajectory feasibility. In particular,
the v36 arrival screen is post-motion and has no all-400 coverage, so using it
as a feature here would leak the terminal failure into the prediction.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SCENES = ROOT / "resources/scenes/formal"
FAILURES = HERE / "v36_failure_context_snapshot.json"
COUPLED_AUDIT = HERE / "v36_coupled_ik_audit.json"
OUTPUT = HERE / "V49_SCENE_FEASIBILITY_OFFLINE.json"

# Fixed before computing outcomes. Thresholds express the number of trays
# initially on the front belt; stack is flagged by the source support chain.
VARIANTS = {
    "front_ge_1_or_stack": 1,
    "front_ge_2_or_stack": 2,
    "front_ge_3_or_stack": 3,
}


def matrix(rows):
    c = Counter()
    for row in rows:
        actual_fail = not row["completed"]
        reject = row["reject"]
        c[("tp" if actual_fail else "fp") if reject else ("fn" if actual_fail else "tn")] += 1
    return {k: c[k] for k in ("tp", "fp", "tn", "fn")}


def main():
    manifest = json.loads((SCENES / "manifest.json").read_text(encoding="utf-8"))
    failure_report = json.loads(FAILURES.read_text(encoding="utf-8"))
    failures = {r["scene_id"]: r for r in failure_report["cases"]}
    assert len(manifest["scenes"]) == 400 and len(failures) == 220
    rows = []
    for entry in manifest["scenes"]:
        scene = json.loads((SCENES / entry["json"]).read_text(encoding="utf-8"))
        assert scene["scene_id"] == entry["scene_id"]
        failure = failures.get(entry["scene_id"])
        stack = any(t["support_parent"].startswith("tray_") for t in scene["trays"])
        rows.append(
            {
                "scene_id": entry["scene_id"],
                "difficulty": scene["difficulty"],
                "front_count": scene["front_count"],
                "stack": stack,
                "completed": failure is None,
                "failure_code": failure["failure"] if failure else None,
            }
        )
    assert sum(r["completed"] for r in rows) == 180
    assert sum(r["stack"] for r in rows) == 20

    audit = json.loads(COUPLED_AUDIT.read_text(encoding="utf-8"))
    arrival = audit.get("selected", [])
    # These signals occur after moving a carried tray. Include availability
    # only; they never enter prediction or threshold selection.
    signal_coverage = {
        "initial_reachability_scene_ids_in_local_audit": ["airport_0006_20270922"],
        "initial_reachability_all400_available": False,
        "post_motion_arrival_screen_records": len(arrival),
        "post_motion_arrival_screen_used_as_feature": False,
        "reason": "Post-motion observations are available only for selected failed cases and would leak the outcome.",
    }

    results = {}
    for name, threshold in VARIANTS.items():
        flagged = []
        for source in rows:
            row = dict(source)
            row["reject"] = row["front_count"] >= threshold or row["stack"]
            flagged.append(row)
        results[name] = {
            "rule": f"front_count >= {threshold} OR support_parent is tray",
            "overall": matrix(flagged),
            "by_difficulty": {
                d: matrix([r for r in flagged if r["difficulty"] == d])
                for d in ("ordinary", "complex")
            },
            "by_front_count": {
                str(n): matrix([r for r in flagged if r["front_count"] == n])
                for n in range(4)
            },
            "by_failure_code": {
                code: {
                    "total": sum(r["failure_code"] == code for r in flagged),
                    "flagged": sum(r["failure_code"] == code and r["reject"] for r in flagged),
                }
                for code in sorted({r["failure_code"] for r in flagged if r["failure_code"]})
            },
            "rejected_historical_success_scene_ids": [
                r["scene_id"] for r in flagged if r["completed"] and r["reject"]
            ],
        }

    report = {
        "kind": "read_only_offline_diagnostic_not_resampling_or_control_result",
        "source": {
            "scenes": str(SCENES.relative_to(ROOT)).replace("\\", "/"),
            "v36_failure_context": str(FAILURES.relative_to(ROOT)).replace("\\", "/"),
            "old400_completed": 180,
            "old400_failed": 220,
        },
        "matrix_definition": "TP=historical fail flagged; FP=historical success flagged; TN=historical success accepted; FN=historical fail accepted",
        "reachability_signal_coverage": signal_coverage,
        "variants": results,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v["overall"] for k, v in results.items()}))


if __name__ == "__main__":
    main()
