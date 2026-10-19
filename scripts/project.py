"""Portable project checks and immutable four-camera scene preparation.

Run from any directory. All runtime inputs resolve inside this project; historical
provenance strings may name the original machine but are never dereferenced here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(compile_models=False):
    """Check every bundled scene dependency, then optionally compile samples."""
    counts = {}
    checked = 0
    models = []
    for group in ("smoke", "formal"):
        directory = ROOT / "resources/scenes" / group
        rows = json.loads((directory / "manifest.json").read_text())["scenes"]
        counts[group] = len(rows)
        ids = set()
        for row in rows:
            source = (directory / row["json"]).resolve()
            if not source.is_relative_to(directory):
                raise ValueError("Scene path escapes project")
            spec = json.loads(source.read_text())
            if spec["scene_id"] in ids:
                raise ValueError("Duplicate scene id")
            ids.add(spec["scene_id"])
            xml = source.with_name(spec.get("scene_file", "scene.xml"))
            assert hashlib.sha256(xml.read_bytes()).hexdigest() == spec["xml_sha256"]
            for node in ET.parse(xml).iter():
                if node.get("file"):
                    asset = (xml.parent / node.get("file")).resolve()
                    if not asset.is_relative_to(ROOT) or not asset.is_file():
                        raise ValueError(f"Missing/external asset: {asset}")
                    checked += 1
            if len(models) < 3:
                models.append(xml)
    assert counts == {"smoke": 12, "formal": 400}, counts
    from r1pro_teleop.airport_fsm.contracts import Config
    Config.load(ROOT / "configs/airport_primitives3.json").validate()
    Config.load(ROOT / "configs/airport_primitives3_smoke.json").validate()
    compiled = []
    if compile_models:
        import mujoco
        for xml in models:
            model = mujoco.MjModel.from_xml_path(str(xml))
            compiled.append({"xml": str(xml.relative_to(ROOT)), "nq": model.nq,
                             "ncam": model.ncam})
    return {"portable_dependencies": True, "scene_counts": counts,
            "asset_references_checked": checked, "compiled": compiled,
            "physics_preflight_performed": False,
            "note": "Compilation is not a two-second settling or task-success test."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("--compile", action="store_true")
    p.add_argument("--report", type=Path)
    p = sub.add_parser("fourcam")
    p.add_argument("--set", choices=("smoke", "formal"), default="smoke")
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check":
        result = check(args.compile)
        text = json.dumps(result, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("x", encoding="utf8") as stream:
                stream.write(text + "\n")
        print(text)
    else:
        # The upgrader creates a new directory and refuses overwrites. It uses
        # measured K and explicit unverified optical-frame assumptions, not a
        # claim that complete camera calibration has been solved.
        subprocess.run([sys.executable, str(ROOT / "scripts/upgrade_airport_fourcam.py"),
                        "--manifest", str(ROOT / "resources/scenes" / args.set / "manifest.json"),
                        "--audit", str(ROOT / "resources/calibration/camera_audit.json"),
                        "--output", str(args.output.resolve())], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
