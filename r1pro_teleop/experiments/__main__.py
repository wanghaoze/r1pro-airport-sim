"""python -m r1pro_teleop.experiments --help"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .common import ROOT, read, name, require_conda
from ..airport_fsm.contracts import atomic_json


def parser():
    p = argparse.ArgumentParser(description="MuJoCo simulation experiment tools; diagnostic outputs only")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("init")
    q.add_argument("--source", required=True); q.add_argument("--output", required=True)
    for group in ("development", "holdout", "regression"):
        q.add_argument("--" + group, nargs="+", required=True)
    for cmd in ("sweep", "search", "verify"):
        q = sub.add_parser(cmd)
        q.add_argument("--root", required=True)
        q.add_argument("--workers", type=int, default=2)
        q.add_argument("--repeats", type=int, default=1)
        q.add_argument("--timeout", type=float, default=1800)
        if cmd == "sweep":
            q.add_argument("--candidates", required=True)
            q.add_argument("--run")
            q.add_argument("--checkpoint")
            q.add_argument("--stage", choices=["settled", "approach", "lift"])
        elif cmd == "search":
            q.add_argument("--seed-summary", required=True); q.add_argument("--space", required=True)
            q.add_argument("--generations", type=int, default=2)
            q.add_argument("--population", type=int, default=4)
        else:
            q.add_argument("--candidate", required=True)
    q = sub.add_parser("worker", help=argparse.SUPPRESS); q.add_argument("request")
    q = sub.add_parser("diagnose"); q.add_argument("--source", required=True); q.add_argument("--output", required=True)
    for cmd in ("report", "history", "status"):
        q = sub.add_parser(cmd); q.add_argument("--root", required=True)
    q = sub.add_parser("assess"); q.add_argument("--root", required=True); q.add_argument("--record", required=True)
    q = sub.add_parser("scene-view")
    q.add_argument("--root", required=True); q.add_argument("--trace", required=True)
    q.add_argument("--output", required=True); q.add_argument("--frame", type=int, default=-1)
    q = sub.add_parser("launch", help="Detach a tools CLI command, with status/result files")
    q.add_argument("--root", required=True); q.add_argument("--name", required=True)
    q.add_argument("args", nargs=argparse.REMAINDER)
    q = sub.add_parser("job", help=argparse.SUPPRESS); q.add_argument("request")
    return p


def launch(root, job_name, args):
    require_conda()
    args = args[1:] if args and args[0] == "--" else args
    if not args or args[0] not in ("sweep", "search", "verify"):
        raise ValueError("invalid_background_command")
    root = Path(root).resolve()
    # The background command must operate on this campaign, not an unrelated path.
    parsed = parser().parse_args(args)
    if Path(parsed.root).resolve() != root:
        raise ValueError("background_campaign_mismatch")
    directory = root / "jobs" / name(job_name)
    directory.mkdir(parents=True, exist_ok=False)
    request = directory / "request.json"
    atomic_json(request, {"args": args, "directory": str(directory)})
    env = os.environ.copy(); env["PYTHONPATH"] = str(ROOT)
    options = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    with open(directory / "output.log", "x", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "-m", "r1pro_teleop.experiments", "job", str(request)],
                                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, **options)
    atomic_json(directory / "launch.json", {"pid": proc.pid, "started": time.time()})
    return {"pid": proc.pid, "job": str(directory)}


def main(argv=None):
    a = parser().parse_args(argv)
    from . import tools
    try:
        if a.command == "init":
            result = tools.init_campaign(a.source, a.output, a.development, a.holdout, a.regression)
            result = {"output": a.output, "groups": result["groups"]}
        elif a.command == "sweep":
            result = tools.sweep(a.root, read(a.candidates), run=a.run, workers=a.workers,
                                 repeats=a.repeats, timeout=a.timeout, checkpoint=a.checkpoint, stage=a.stage)
        elif a.command == "search":
            result = tools.search(a.root, a.seed_summary, read(a.space), generations=a.generations,
                                  population=a.population, workers=a.workers, repeats=a.repeats, timeout=a.timeout)
        elif a.command == "verify":
            result = tools.verify(a.root, read(a.candidate), workers=a.workers, repeats=a.repeats, timeout=a.timeout)
        elif a.command == "worker":
            from .worker import worker
            result = worker(a.request)
        elif a.command == "diagnose":
            result = tools.diagnose(a.source, a.output)
            result = {k: v for k, v in result.items() if k != "rows"}
        elif a.command == "report":
            result = tools.report(a.root)
        elif a.command == "history":
            result = tools.history(a.root)
        elif a.command == "assess":
            result = tools.assess(a.root, **read(a.record))
        elif a.command == "scene-view":
            result = tools.scene_view(a.root, a.trace, a.output, a.frame)
        elif a.command == "launch":
            result = launch(a.root, a.name, a.args)
        elif a.command == "status":
            result = {"progress": [{"path": str(p), **read(p)} for pattern in
                       ("experiments/*/progress.json", "searches/*/progress.json", "jobs/*/status.json")
                       for p in sorted(Path(a.root).glob(pattern))]}
        elif a.command == "job":
            record = read(a.request); directory = Path(record["directory"])
            atomic_json(directory / "status.json", {"state": "running", "pid": os.getpid()})
            code = main(record["args"])
            atomic_json(directory / "status.json", {"state": "completed" if code == 0 else "failed", "exit_code": code})
            return code
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 2 if a.command == "verify" and not result["passed"] else 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
