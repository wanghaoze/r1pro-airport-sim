"""Bounded, resumable native failure evidence rendering and SSH collection.

This is diagnostic evidence only, never a training exporter. Heavy dependencies
are imported only by the server-side render command.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import traceback
import time
import uuid
import tarfile
import threading
from datetime import datetime, timezone

PROJECT = Path(os.environ.get("AIRPORT_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(PROJECT))


def component(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or value in (".", ".."):
        raise ValueError(f"Unsafe path component: {value!r}")
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def inventory(root):
    cases = []
    root = Path(root)
    paths = list(root.glob("attempts/*/a*/result.json"))
    paths += list(root.glob("experiments/*/*/*/a*/result.json"))
    for path in sorted(paths):
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("physics_success") is True or result.get("stage_passed") is True:
            continue
        trial = "/".join(path.relative_to(root).parts[:3]) if path.relative_to(root).parts[0] == "experiments" else None
        frames = result.get("frames", 0)
        if (path.parent / "trace.h5").exists():
            try:
                import h5py
                with h5py.File(path.parent / "trace.h5") as trace:
                    frames = int(trace.attrs.get("num_frames", frames))
            except (ImportError, OSError, ValueError):
                pass  # Rendering will retain a precise invalid-trace failure.
        cases.append({"scene_id": component(path.parent.parent.name), "trial": trial,
                      "frames": frames,
                      "attempt": component(path.parent.name),
                      "failure_code": result.get("failure_code", "unknown"),
                      "result_sha256": digest(path)})
    return sorted(cases, key=lambda c: (c["frames"], c["scene_id"], c["trial"] or "", c["attempt"]))


def verified(directory, manifest):
    files = manifest.get("files", {})
    return bool(files) and all((Path(directory) / component(name)).is_file()
                              and digest(Path(directory) / name) == info["sha256"]
                              for name, info in files.items())


def evidence_directory(root, scene_id, attempt):
    identity = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
    return PROJECT / "runs" / "failure_video_render" / identity / scene_id / attempt


def case_identity(attempt, trial):
    if trial:
        parts = trial.split("/")
        if len(parts) != 3 or parts[0] != "experiments":
            raise ValueError("invalid experiment trial path")
        return component(attempt) + "__" + "__".join(component(p) for p in parts[1:])
    return component(attempt)


def render(root, scene_id, attempt, trial=None, wait_existing_seconds=0):
    root = Path(root).resolve()
    identity = case_identity(attempt, trial)
    directory = root / (trial or "attempts") / component(scene_id) / component(attempt)
    collection = root / "collection" if trial else root
    out = evidence_directory(root, scene_id, identity)
    out.mkdir(parents=True, exist_ok=True)
    # One subprocess owns a case. Refuse overlapping renderers instead of racing.
    lock = out / "render.lock"
    deadline = time.monotonic() + wait_existing_seconds
    while True:
        try:
            with lock.open("x") as f:
                f.write(str(os.getpid()))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise
            # A reset SSH connection can leave the original renderer working.
            # Wait for its evidence instead of launching a competing renderer.
            try:
                owner = int(lock.read_text())
            except (FileNotFoundError, ValueError):
                time.sleep(.1)
                continue
            if sys.platform.startswith("linux") and not Path(f"/proc/{owner}").exists():
                raise RuntimeError(f"Stale render lock requires evidence review: {lock}")
            time.sleep(2)
    try:
        source_hash = digest(directory / "result.json")
        trace_hash = digest(directory / "trace.h5") if (directory / "trace.h5").exists() else None
        old = out / "manifest.json"
        if old.exists():
            previous = json.loads(old.read_text(encoding="utf-8"))
            if (previous.get("result_sha256") == source_hash
                    and previous.get("trace_sha256") == trace_hash and verified(out, previous)):
                return previous
            raise RuntimeError("Existing evidence changed or incomplete; use a fresh collection")
        manifest = {"schema": "failure_head_evidence/1", "scene_id": scene_id,
                    "attempt": attempt, "result_sha256": source_hash,
                    "trial": trial,
                    "trace_sha256": trace_hash, "training_candidate": False,
                    "environment_source": "simulation", "controller_source": "program_generated",
                    "fps": 20, "crop": False, "resize": False, "speedup": False,
                    "overlay": False, "source_collection": str(root), "files": {}}
        manifest["started_at_utc"] = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        manifest["evidence_directory"] = str(out)
        for name in ("result.json", "events.json", "events.jsonl", "segments.json", "exception.txt", "task_dag.json"):
            if (directory / name).is_file():
                shutil.copy2(directory / name, out / name)
        try:
            if trace_hash is None:
                manifest.update(status="unavailable", reason="no_trace_initialization_or_worker_failure")
            else:
                _render_trace(collection, directory, out, scene_id, manifest)
        except Exception:
            (out / "render_error.log").write_text(traceback.format_exc(), encoding="utf-8")
            manifest.update(status="render_failed", reason="see_render_error.log")
        manifest["render_wall_seconds"] = time.monotonic() - started
        manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        if manifest.get("frames"):
            manifest["replay_frames_per_wall_second"] = manifest["frames"] / manifest["render_wall_seconds"]
        for p in sorted(out.iterdir()):
            if p.is_file() and p.name not in ("manifest.json", "render.lock"):
                manifest["files"][p.name] = {"sha256": digest(p), "bytes": p.stat().st_size}
        save(out / "manifest.json", manifest)
        return manifest
    finally:
        lock.unlink()


def _render_trace(root, directory, out, scene_id, manifest):
    import av
    import h5py
    with h5py.File(directory / "trace.h5") as trace:
        if int(trace.attrs.get("num_frames", 0)) == 0:
            manifest.update(status="unavailable", reason="trace_has_no_observations")
            return
    # EGL's device order differs from nvidia-smi on this server. Resolve the
    # physical GPU by PCI identity before importing/initializing MuJoCo EGL.
    from scripts.select_r1pro_gpu import select
    device = select(0)
    os.environ["MUJOCO_GL"] = "egl"
    os.environ["MUJOCO_EGL_DEVICE_ID"] = str(device["egl_index"])
    os.environ["CUDA_VISIBLE_DEVICES"] = device["uuid"]
    manifest["render_device"] = device
    from r1pro_teleop.airport_fsm.exporter import Replay, video_metadata
    containers, streams = {}, {}
    frames = 0
    try:
        with Replay(root, {"scene_id": scene_id, "trace": str(directory / "trace.h5")}, diagnostic=True) as replay:
            shapes = {k: v for k, v in replay.shapes.items() if k in ("head_left", "head_right")}
            if set(shapes) != {"head_left", "head_right"} or any(tuple(s) != (1536, 1920, 3) for s in shapes.values()):
                raise ValueError("Expected native stereo head cameras, 1920x1536")
            # Replay still integrates every accepted control interval and checks
            # divergence. Only expensive camera rendering is restricted to heads.
            replay.shapes = shapes
            for camera in shapes:
                containers[camera] = av.open(str(out / (camera + ".mp4")), mode="w")
                stream = containers[camera].add_stream("libx264", rate=20)
                stream.width, stream.height = 1920, 1536
                stream.pix_fmt = "yuv420p"
                stream.options = {"crf": "18", "preset": "fast", "threads": "2"}
                streams[camera] = stream
            for i, images in replay:
                for camera, image in images.items():
                    frame = av.VideoFrame.from_ndarray(image, format="rgb24")
                    frame.pts = i
                    for packet in streams[camera].encode(frame):
                        containers[camera].mux(packet)
                frames += 1
            for camera, stream in streams.items():
                for packet in stream.encode():
                    containers[camera].mux(packet)
            manifest.update(frames=frames, replay_max_qpos_error=replay.maximum_error,
                            blank_frames_retained=dict(replay.blank),
                            final_source_observation_retained=True,
                            final_observation_note="Includes the last recorded pre-action observation; an incomplete control interval is not fabricated.")
    finally:
        for container in containers.values():
            container.close()
    metadata = video_metadata(out, shapes)
    if len(metadata) != 2 or any(v["frames"] != frames for v in metadata):
        raise ValueError("Encoded frame count differs from physical replay")
    manifest.update(status="complete", videos=metadata)


def ssh_command(args, tokens):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            *(["-i", args.identity] if args.identity else []), args.host,
            "cd " + shlex.quote(args.remote_project) + " && "
            + "MUJOCO_GL=egl OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 "
            + "AIRPORT_PROJECT_ROOT=" + shlex.quote(args.remote_project) + " "
            + "PYTHONPATH=" + shlex.quote(args.remote_project) + " " + shlex.join(tokens)]


def remote(args, tokens):
    for retry in range(5):
        p = subprocess.run(ssh_command(args, tokens), capture_output=True, text=True,
                           encoding="utf-8", timeout=args.timeout)
        if p.returncode != 255 or retry == 4:
            break
        time.sleep(min(30, 2 ** (retry + 1)))
    if p.returncode:
        raise RuntimeError(f"Remote exit {p.returncode}: {p.stderr[-4000:]}")
    return json.loads(p.stdout)


def destination_root(args):
    directory = PROJECT / "runs" / "failure_videos" / component(args.release) / component(args.run)
    if getattr(args, "variant", None):
        directory /= component(args.variant)
    return directory


def download(args, source, temp, names=None, max_bytes=None):
    for retry in range(5):
        with temp.open("wb") as f:
            command = ["tar", "-cf", "-", "-C", source, "--", *names] if names else ["cat", "--", source]
            if max_bytes is None:
                p = subprocess.run(ssh_command(args, command), stdout=f,
                                   stderr=subprocess.PIPE, timeout=args.timeout)
            else:
                # Bound archive bytes before writing, even if the peer misbehaves.
                error_path = temp.with_name(temp.name + ".transport.log")
                with error_path.open("wb") as error_log:
                    with subprocess.Popen(ssh_command(args, command), stdout=subprocess.PIPE, stderr=error_log) as process:
                        timer = threading.Timer(args.timeout, process.kill)
                        timer.start()
                        try:
                            copy_bounded(process.stdout, f, max_bytes)
                        except BaseException:
                            process.kill()
                            raise
                        finally:
                            process.wait()
                            timer.cancel()
                    p = subprocess.CompletedProcess(command, process.returncode,
                        stderr=error_path.read_bytes())
        if p.returncode != 255 or retry == 4:
            return p
        time.sleep(min(30, 2 ** (retry + 1)))


def copy_bounded(source, target, maximum):
    total = 0
    while chunk := source.read(1024 * 1024):
        total += len(chunk)
        if total > maximum:
            raise RuntimeError("Evidence archive exceeded declared byte budget")
        target.write(chunk)


def download_files(args, manifest, dest, archive_name=".download.tar.partial"):
    missing = {component(name): info for name, info in manifest["files"].items()
               if not (dest / component(name)).is_file() or digest(dest / name) != info["sha256"]}
    if not missing:
        return
    # GNU tar writes 512-byte headers/padding and 10240-byte output blocks.
    archive_limit = sum(((i["bytes"] + 511) // 512 + 1) * 512 for i in missing.values()) + 20480
    # Keep room for both the transport archive and extracted evidence.
    if shutil.disk_usage(dest).free < archive_limit + sum(i["bytes"] for i in missing.values()) + 2 * 1024 ** 3:
        raise RuntimeError("Insufficient local space: retain 2 GiB reserve; remote evidence kept")
    archive = dest / archive_name
    p = download(args, manifest["evidence_directory"], archive, list(missing), archive_limit)
    if p.returncode:
        raise RuntimeError("Evidence archive download failed: " + p.stderr.decode(errors="replace"))
    with tarfile.open(archive, "r:") as bundle:
        members = bundle.getmembers()
        if len(members) != len(missing) or {m.name for m in members} != set(missing):
            raise RuntimeError("Evidence archive contains missing, duplicate or unexpected files")
        for member in members:
            info = missing[member.name]
            if not member.isfile() or member.size != info["bytes"]:
                raise RuntimeError("Evidence archive entry type/size mismatch: " + member.name)
            target = dest / component(member.name)
            temp = target.with_name(target.name + ".partial")
            if shutil.disk_usage(dest).free < member.size + 2 * 1024 ** 3:
                raise RuntimeError("Insufficient local space: retain 2 GiB reserve; remote evidence kept")
            with bundle.extractfile(member) as source, temp.open("wb") as out:
                shutil.copyfileobj(source, out, length=1024 * 1024)
            if digest(temp) != info["sha256"] or temp.stat().st_size != info["bytes"]:
                raise RuntimeError("Download/checksum failed: " + member.name)
            os.replace(temp, target)
    archive.unlink()  # Only this case's disposable transport archive.


def collect_case(args, case):
    sid, attempt = component(case["scene_id"]), component(case["attempt"])
    trial = case.get("trial")
    identity = case_identity(attempt, trial)
    dest = destination_root(args) / sid / identity
    dest.mkdir(parents=True, exist_ok=True)
    save(dest / "download.json", {"verified": False, "status": "pending"})
    try:
        manifest = remote(args, [args.remote_python, getattr(args, "remote_script", "scripts/collect_failure_videos.py"), "render",
                                 "--root", args.root, "--scene-id", sid, "--attempt", attempt,
                                 "--wait-existing-seconds", str(getattr(args, "timeout", 7200)),
                                 *(["--trial", trial] if trial else [])])
        save(dest / "manifest.json", manifest)
        download_files(args, manifest, dest)
        save(dest / "manifest.json", manifest)
        save(dest / "download.json", {"verified": True, "files": manifest["files"], "status": manifest["status"]})
        return {"scene_id": sid, "attempt": attempt, "trial": trial, "status": manifest["status"], "path": str(dest)}
    except Exception:
        (dest / "download_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        save(dest / "download.json", {"verified": False, "status": "download_failed"})
        return {"scene_id": sid, "attempt": attempt, "trial": trial, "status": "download_failed", "path": str(dest)}


def event_metadata(root, scene_id, attempt, trial=None):
    identity = case_identity(attempt, trial)
    directory = Path(root).resolve() / (trial or "attempts") / component(scene_id) / component(attempt)
    source = directory / "events.jsonl"
    data = {"schema": "failure_events_supplement/1", "scene_id": scene_id, "attempt": attempt,
            "trial": trial, "source_path": str(source), "source_collection": str(Path(root).resolve()),
            "evidence_directory": str(directory), "files": {}, "training_candidate": False}
    if not (directory / "result.json").is_file():
        return dict(data, status="unavailable", reason="attempt_not_finished")
    if not source.is_file():
        return dict(data, status="unavailable", reason="source_events_jsonl_missing")
    data["files"]["events.jsonl"] = {"sha256": digest(source), "bytes": source.stat().st_size}
    return dict(data, status="complete")


def supplement_events(args, case):
    sid, attempt, trial = component(case["scene_id"]), component(case["attempt"]), case.get("trial")
    dest = destination_root(args) / sid / case_identity(attempt, trial)
    result = {"scene_id": sid, "attempt": attempt, "trial": trial, "path": str(dest)}
    # Never race a primary video transfer or alter its manifest/download state.
    if not (dest / "download.json").is_file() or not json.loads((dest / "download.json").read_text()).get("verified"):
        return dict(result, status="deferred")
    try:
        primary = json.loads((dest / "manifest.json").read_text())
        current = primary.get("files", {}).get("events.jsonl")
        if current and (dest / "events.jsonl").is_file() and digest(dest / "events.jsonl") == current["sha256"]:
            return dict(result, status="complete")
        old = dest / "events_supplement.json"
        if old.exists():
            metadata = json.loads(old.read_text())
            if metadata.get("verified") and verified(dest, metadata):
                return dict(result, status="complete")
        metadata = remote(args, [args.remote_python, args.remote_script, "event-metadata", "--root", args.root,
                                "--scene-id", sid, "--attempt", attempt, *(["--trial", trial] if trial else [])])
        if metadata["status"] == "complete":
            download_files(args, metadata, dest, archive_name=".events-download.tar.partial")
            metadata["verified"] = True
        else:
            metadata["verified"] = False
        metadata["downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
        save(old, metadata)
        return dict(result, status=metadata["status"])
    except Exception:
        (dest / "events_download_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        save(dest / "events_supplement.json", dict(status="download_failed", verified=False, reason="see events_download_error.log"))
        return dict(result, status="download_failed")


def build_local_index(root, verify_hashes=False):
    """Read evidence and pending inventories without copying any videos."""
    root = Path(root).resolve()
    cases = {}
    def read(path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default
    for path in sorted(root.glob("**/index*.json")):
        group = path.parent.relative_to(root).parts
        if len(group) not in (2, 3):
            continue
        entries = read(path, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("scene_id") or not entry.get("attempt"):
                continue
            identity = case_identity(entry["attempt"], entry.get("trial"))
            key = (*group, component(entry["scene_id"]), identity)
            cases.setdefault(key, {}).update({k: v for k, v in entry.items() if v is not None})
    for path in root.glob("**/manifest.json"):
        parts = path.parent.relative_to(root).parts
        if len(parts) in (4, 5):
            cases.setdefault(parts, {})
    rows = []
    for parts, case in sorted(cases.items()):
        dest = root.joinpath(*parts)
        manifest = read(dest / "manifest.json", {})
        downloaded = read(dest / "download.json", {})
        result = read(dest / "result.json", {})
        supplement = read(dest / "events_supplement.json", {})
        sha_ok = bool(downloaded.get("verified"))
        sha_state = "verified_at_download" if sha_ok else "not_verified"
        if sha_ok and verify_hashes:
            sha_ok = verified(dest, manifest)
            sha_state = "verified_now" if sha_ok else "checksum_or_file_missing"
        heads = [dest / "head_left.mp4", dest / "head_right.mp4"]
        has_heads = all(p.is_file() for p in heads)
        server_status = manifest.get("status", "not_yet_verified")
        if server_status == "unavailable":
            local_status = "unavailable"
        elif server_status == "render_failed":
            local_status = "render_failed"
        elif server_status == "complete" and sha_ok and has_heads:
            local_status = "complete"
        elif downloaded.get("status") == "download_failed":
            local_status = "download_failed"
        elif server_status == "complete":
            local_status = "server_only_or_partial"
        else:
            local_status = "pending"
        issue = manifest.get("reason", "")
        if downloaded.get("status") == "download_failed":
            try:
                issue = (dest / "download_error.log").read_text(encoding="utf-8").strip().splitlines()[-1]
            except (FileNotFoundError, IndexError):
                issue = "see download_error.log"
        group = parts[:-2]
        raw_events = dest / "events.jsonl"
        event_info = manifest.get("files", {}).get("events.jsonl") or supplement.get("files", {}).get("events.jsonl", {})
        event_ok = raw_events.is_file() and bool(event_info) and (sha_ok if "events.jsonl" in manifest.get("files", {}) else bool(supplement.get("verified")))
        if verify_hashes and raw_events.is_file() and event_info:
            event_ok = digest(raw_events) == event_info["sha256"]
        event_status = ("verified_now" if verify_hashes else "verified_at_download") if event_ok else ("checksum_or_file_missing" if event_info else supplement.get("status", "not_collected"))
        event_source = supplement.get("source_path", "")
        if not event_source and "events.jsonl" in manifest.get("files", {}) and manifest.get("source_collection"):
            event_source = "/".join([manifest["source_collection"].rstrip("/"), manifest.get("trial") or "attempts",
                                     parts[-2], manifest.get("attempt", case.get("attempt", parts[-1])), "events.jsonl"])
        rows.append({"release": group[0], "run": group[1],
                     "variant": group[2] if len(group) == 3 else "",
                     "scene_id": parts[-2], "attempt": manifest.get("attempt", case.get("attempt", parts[-1])),
                     "trial": manifest.get("trial", case.get("trial")) or "",
                     "attempt_directory": str(dest), "head_left_path": str(heads[0]), "head_right_path": str(heads[1]),
                     "head_left_exists": heads[0].is_file(), "head_right_exists": heads[1].is_file(),
                     "head_left_sha256": manifest.get("files", {}).get("head_left.mp4", {}).get("sha256", ""),
                     "head_right_sha256": manifest.get("files", {}).get("head_right.mp4", {}).get("sha256", ""),
                     "sha_verified": sha_ok, "sha_validation": sha_state, "local_status": local_status,
                     "server_status": server_status, "remote_evidence_directory": manifest.get("evidence_directory", ""),
                     "source_collection": manifest.get("source_collection", ""),
                     "failure_reason": result.get("failure_code") or case.get("failure_code") or "unknown",
                     "evidence_issue": issue, "frames_per_head": manifest.get("frames", 0),
                     "result_path": str(dest / "result.json") if (dest / "result.json").exists() else "",
                     "events_path": str(dest / "events.json") if (dest / "events.json").exists() else "",
                     "events_jsonl_path": str(raw_events) if raw_events.is_file() else "",
                     "events_jsonl_sha256": event_info.get("sha256", ""), "events_jsonl_sha_verified": event_ok,
                     "events_jsonl_status": event_status, "events_jsonl_source_path": event_source,
                     "events_jsonl_issue": supplement.get("reason", "")})
    counts = {status: sum(r["local_status"] == status for r in rows) for status in sorted({r["local_status"] for r in rows})}
    payload = {"schema": "failure_video_local_index/1", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "hashes_rechecked": verify_hashes, "counts": counts, "cases": rows}
    save(root / "failure_video_index.json", payload)
    csv_path = root / "failure_video_index.csv"
    temp = csv_path.with_name(csv_path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    os.replace(temp, csv_path)
    return {"cases": len(rows), "counts": counts, "json": str(root / "failure_video_index.json"), "csv": str(csv_path)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    local = sub.add_parser("index", help="Write a local JSON/CSV snapshot without copying videos")
    local.add_argument("--root", required=True)
    local.add_argument("--verify-hashes", action="store_true")
    for name in ("inventory", "render", "collect", "event-metadata", "supplement-events"):
        s = sub.add_parser(name)
        s.add_argument("--root", required=True, help="Source collection, remote absolute path for collect")
        if name in ("render", "event-metadata"):
            s.add_argument("--scene-id", required=True)
            s.add_argument("--attempt", required=True)
            s.add_argument("--trial")
            s.add_argument("--wait-existing-seconds", type=float, default=0)
        if name in ("collect", "supplement-events"):
            s.add_argument("--host", required=True)
            s.add_argument("--identity")
            s.add_argument("--remote-project", required=True)
            s.add_argument("--remote-script", default="scripts/collect_failure_videos.py", help="Use a standalone tools path to avoid changing a frozen release")
            s.add_argument("--remote-python", default="/home/michelle/miniconda3/envs/r1pro-tray/bin/python")
            s.add_argument("--release", required=True)
            s.add_argument("--run", required=True)
            s.add_argument("--variant", help="Optional variant directory beneath release/run")
            s.add_argument("--workers", type=int, choices=range(1, 5), default=2)
            s.add_argument("--timeout", type=int, default=7200)
            s.add_argument("--scene-id", action="append", help="Optional case filter; repeatable")
    args = p.parse_args()
    if args.command == "index":
        output = build_local_index(args.root, args.verify_hashes)
    elif args.command == "inventory":
        output = inventory(args.root)
    elif args.command == "render":
        output = render(args.root, args.scene_id, args.attempt, args.trial, args.wait_existing_seconds)
    elif args.command == "event-metadata":
        output = event_metadata(args.root, args.scene_id, args.attempt, args.trial)
    else:
        cases = remote(args, [args.remote_python, args.remote_script, "inventory", "--root", args.root])
        if args.scene_id:
            cases = [c for c in cases if c["scene_id"] in args.scene_id]
        index_name = "events-index.json" if args.command == "supplement-events" else "index.json"
        if args.scene_id:
            index_name = index_name.removesuffix(".json") + "-" + hashlib.sha256("\n".join(sorted(args.scene_id)).encode()).hexdigest()[:12] + ".json"
        index = destination_root(args) / index_name
        progress = {(c["scene_id"], case_identity(c["attempt"], c.get("trial"))):
                    dict(c, status="pending") for c in cases}
        save(index, list(progress.values()))
        output = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            operation = supplement_events if args.command == "supplement-events" else collect_case
            for job in as_completed([pool.submit(operation, args, c) for c in cases]):
                result = job.result()
                output.append(result)
                progress[(result["scene_id"], case_identity(result["attempt"], result.get("trial")))] = result
                save(index, list(progress.values()))
                print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
        output.sort(key=lambda c: (c["scene_id"], c["attempt"]))
        save(index, output)
    print(json.dumps(output, ensure_ascii=False))
    if args.command in ("collect", "supplement-events") and any(c["status"] != "complete" for c in output):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
