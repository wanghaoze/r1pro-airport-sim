"""Refresh/check the implementation appendix inside the single task specification.

No simulator or network is required. --write updates only the marked appendix;
authors must review and edit the human-readable workflow in the same change.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/SCENE_TASK_SPEC.md"
START = "<!-- GENERATED-CONTRACT:START -->"
END = "<!-- GENERATED-CONTRACT:END -->"
sys.path.insert(0, str(ROOT))


def sources():
    paths = list((ROOT / "r1pro_teleop").glob("*.py"))
    paths += list((ROOT / "r1pro_teleop/airport_fsm").glob("*.py"))
    paths += list((ROOT / "r1pro_teleop/experiments").glob("*.py"))
    paths += list((ROOT / "r1pro_teleop/vla").glob("*.py"))
    paths += list((ROOT / "r1pro_teleop/real2sim").glob("*.py"))
    paths += list((ROOT / "scripts").glob("*real2sim*.py"))
    paths += list((ROOT / "r1pro_teleop/single_tray_lab").glob("*.py"))
    paths += list((ROOT / "r1pro_teleop/single_tray_3table").glob("*.py"))
    # Exported web-agent contracts and adapters are reviewed with the same spec.
    paths += [p for p in (ROOT / "exports/web_scene_agent_v1").rglob("*")
              if p.suffix in (".py", ".json", ".md", ".ps1", ".sh")
              and "__pycache__" not in p.parts]
    # Only application source; never node_modules, credentials, build output or CAD binaries.
    for folder in ("app", "lib", "gpu", "db", "tests", "drizzle"):
        paths += [p for p in (ROOT / "apps/scene-agent" / folder).rglob("*")
                  if p.suffix in (".py", ".ts", ".tsx", ".json", ".sql")
                  and "__pycache__" not in p.parts]
    paths += [ROOT / 'runs/failure_videos/update_scene_video_index.py']
    # Include new project-owned data, training and milestone entry points too;
    # their workflow must still be reviewed in the human-written specification.
    for pattern in ('studio_*.py', '*isaac*.py', '*pi05*.py', '*vla*.py', '*action8*.py', '*complete_task*.py', '*task_complete*.py', '*single_tray*.py', '*three_table*.py', '*three_action*.py'):
        paths += list((ROOT / 'scripts').glob(pattern))
    paths += [ROOT / "scripts" / name for name in (
        "prepare_vla_dataset.py", "convert_vla_lerobot.py", "train_pi05_airport.py",
        "serve_pi05_airport.py", "serve_pi05_galaxea_robot.py", "control_galaxea_servers.py", "run_galaxea_client_record_compat.py", "galaxea_client_oneclick.sh", "evaluate_pi05_airport.py", "render_vla_native_sources.py",
        "generate_pickup_lerobot.py", "rerender_pickup_camera_shells.py", "compare_pickup120.py", "export_project_interactions.py", "run_real_sim_pickplace.py", "train_pi05_real_sim50.py", "watch_real_sim_transfer.py",
        "plan_complete_task_actions.py", "materialize_complete_task_actions.py",
        "render_task_complete_sources.py")]
    paths += list((ROOT / "prompts/airport_experiments").glob("*.md"))
    paths += list((ROOT / "configs").glob("*.json"))
    paths += list((ROOT / "schemas").glob("*.json"))
    paths += [ROOT / "scripts" / name for name in (
        "project.py", "generate_airport_scenes.py", "upgrade_airport_fourcam.py",
        "repair_airport_initial_settle.py", "collect_airport_batches.py", "sync_task_spec.py",
        "deploy_experiments.py", "experiment_server_smoke.py", "collect_failure_videos.py", "control_regression.py", "control_ablation.py")]
    return sorted(set(paths))


def render():
    from r1pro_teleop.airport_fsm.contracts import Config, State
    faults, events, phases = {}, {}, {}
    hashes = {}
    for path in sources():
        rel = path.relative_to(ROOT).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            location = f"{rel}:{node.lineno}"
            if name in ("Fault", "ValueError") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                code = node.args[0].value
                # Keep machine-readable codes, not arbitrary prose ValueErrors.
                if name == "Fault" or (code.isidentifier() and code.islower()):
                    recoverable = next((ast.unparse(k.value) for k in node.keywords if k.arg == "recoverable"),
                                       "False" if name == "Fault" else
                                       "生成器捕获ValueError时重采样" if path.name == "airport_scenes.py" else
                                       "输入/实验拒绝；不自动重试")
                    faults.setdefault(code, []).append((location, recoverable))
            if name == "transition" and len(node.args) > 1:
                # Conditional phase selection (pull vs adjust) is part of the
                # public dictionary as well as literal transition arguments.
                for value in ast.walk(node.args[1]):
                    if isinstance(value, ast.Constant) and isinstance(value.value,str):
                        phases.setdefault(value.value, []).append(location)
            if name == "emit" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                events.setdefault(str(node.args[1].value), []).append(location)
    rows = ["", "## 附录：当前实现字典与配置快照（自动维护）", "",
            "由 scripts/sync_task_spec.py 生成。错误码表覆盖静态调用点；同名码可有不同恢复属性，实际还受上下文覆盖。", "",
            "### FSM枚举", "", "、".join(f"`{s.value}`" for s in State), "",
            "### 实际transition调用的phase", ""]
    rows += [f"- `{key}`：" + "；".join(f"`{p}`" for p in sorted(set(loc))) for key, loc in sorted(phases.items())]
    rows += ["", "### 证据事件emit字典", ""]
    rows += [f"- `{key}`：" + "；".join(f"`{p}`" for p in sorted(set(loc))) for key, loc in sorted(events.items())]
    rows += ["", "### 静态错误码与具体恢复声明", "", "| 错误码 | 调用位置及 recoverable 声明 |", "|---|---|"]
    for key, locations in sorted(faults.items()):
        cells = "<br>".join(f"`{loc}` → `{rec}`" for loc, rec in sorted(set(locations)))
        rows.append(f"| `{key}` | {cells} |")
    rows += ["", "### 生效配置（含未显式填写的默认值）", "",
             "正式配置使用 Config.load 合并默认值，不只抄 JSON 中显式字段。smoke 仅在 expected_scenes=12、split_counts=[8,2,2] 上不同。", "",
             "```json", json.dumps(Config.load(ROOT / "configs/airport_primitives3.json").dump(), ensure_ascii=False, indent=2), "```", "",
             "### 实现来源指纹", "", "用于发现源码修改后忘记同步规范；不表示新版本已经完成物理验证。", "",
             "```json", json.dumps(hashes, indent=2), "```", ""]
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    original = DOC.read_text(encoding="utf8")
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("Specification must have one generated region")
    prefix, rest = original.split(START, 1)
    old, suffix = rest.split(END, 1)
    new = render()
    if args.write:
        DOC.write_text(prefix + START + new + END + suffix, encoding="utf8")
        print("Updated appendix; review workflow, constraints and change log manually.")
    elif old != new:
        print("Task specification is stale. Review docs/SCENE_TASK_SPEC.md and run --write.", file=sys.stderr)
        return 1
    else:
        print("Task specification source fingerprints and generated dictionaries are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
