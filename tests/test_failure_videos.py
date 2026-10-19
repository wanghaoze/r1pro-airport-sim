"""Failure evidence must stay separate, intact and explicitly incomplete."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import collect_failure_videos as videos


def attempt(root, sid, aid, success=False):
    path = root / "attempts" / sid / aid
    path.mkdir(parents=True)
    videos.save(path / "result.json", {"physics_success": success, "failure_code": "init_failed"})
    return path


def test_inventory_keeps_every_failed_attempt(tmp_path):
    attempt(tmp_path, "scene_1", "a000")
    attempt(tmp_path, "scene_1", "a001")
    attempt(tmp_path, "scene_2", "a000", True)
    assert [(r["scene_id"], r["attempt"]) for r in videos.inventory(tmp_path)] == [("scene_1", "a000"), ("scene_1", "a001")]


def test_no_trace_manifest_and_resume_do_not_touch_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    root = tmp_path / "collection"
    source = attempt(root, "scene_1", "a000")
    original = (source / "result.json").read_bytes()
    manifest = videos.render(root, "scene_1", "a000")
    assert manifest["status"] == "unavailable"
    assert manifest["reason"] == "no_trace_initialization_or_worker_failure"
    assert manifest["training_candidate"] is False
    out = Path(manifest["evidence_directory"])
    assert videos.verified(out, manifest)
    assert videos.render(root, "scene_1", "a000") == manifest
    assert (source / "result.json").read_bytes() == original
    assert list(source.iterdir()) == [source / "result.json"]


def test_corrupt_evidence_not_silently_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    root = tmp_path / "collection"
    attempt(root, "scene_1", "a000")
    manifest = videos.render(root, "scene_1", "a000")
    (Path(manifest["evidence_directory"]) / "result.json").write_text("corrupted")
    with pytest.raises(RuntimeError, match="changed or incomplete"):
        videos.render(root, "scene_1", "a000")


def test_renderer_failure_retains_evidence_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    root = tmp_path / "collection"
    source = attempt(root, "scene_1", "a000")
    (source / "trace.h5").write_bytes(b"not hdf5")
    def fail(*args):
        raise RuntimeError("replay_diverged")
    monkeypatch.setattr(videos, "_render_trace", fail)
    manifest = videos.render(root, "scene_1", "a000")
    assert manifest["status"] == "render_failed"
    assert "render_error.log" in manifest["files"]
    assert "replay_diverged" in (Path(manifest["evidence_directory"]) / "render_error.log").read_text()


@pytest.mark.parametrize("value", ["../bad", "/tmp", "a/b", "a\\b", "..", "a;touch"])
def test_path_components_cannot_escape(value):
    with pytest.raises(ValueError):
        videos.component(value)


def test_transport_failure_is_case_local_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path)
    def fail(*args):
        raise RuntimeError("SSH unavailable")
    monkeypatch.setattr(videos, "remote", fail)
    args = SimpleNamespace(release="r1", run="run1", remote_python="python", root="/collection")
    result = videos.collect_case(args, {"scene_id": "scene_1", "attempt": "a000"})
    assert result["status"] == "download_failed"
    assert "SSH unavailable" in (Path(result["path"]) / "download_error.log").read_text()


def test_campaign_trials_have_distinct_case_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    for candidate in ("baseline", "preview"):
        path = tmp_path / "experiments" / "strategies" / candidate / "scene_1" / "a000"
        videos.save(path / "result.json", {"physics_success": False})
    passed = tmp_path / "experiments" / "settled" / "baseline" / "scene_1" / "a000"
    videos.save(passed / "result.json", {"physics_success": False, "stage_passed": True})
    cases = videos.inventory(tmp_path)
    assert len(cases) == 2
    assert len({videos.case_identity(c["attempt"], c["trial"]) for c in cases}) == 2
    manifests = [videos.render(tmp_path, c["scene_id"], c["attempt"], c["trial"]) for c in cases]
    assert len({m["evidence_directory"] for m in manifests}) == 2


def test_concurrent_renderer_refuses_case_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    attempt(tmp_path, "scene_1", "a000")
    out = videos.evidence_directory(tmp_path, "scene_1", "a000")
    out.mkdir(parents=True)
    (out / "render.lock").write_text("existing process")
    with pytest.raises(FileExistsError):
        videos.render(tmp_path, "scene_1", "a000")
    assert (out / "render.lock").read_text() == "existing process"


def test_variants_never_share_case_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path)
    args = SimpleNamespace(release="r1", run="ablation", variant="baseline")
    baseline = videos.destination_root(args)
    args.variant = "substep"
    assert baseline != videos.destination_root(args)
    assert baseline.parts[-2:] == ("ablation", "baseline")


def test_ssh_reset_retries_are_bounded_and_preserve_json(monkeypatch):
    attempts, sleeps = [], []
    def run(*args, **kwargs):
        attempts.append(args)
        return SimpleNamespace(returncode=255 if len(attempts) < 3 else 0,
                               stdout='{"complete":true}', stderr="Connection reset")
    monkeypatch.setattr(videos.subprocess, "run", run)
    monkeypatch.setattr(videos.time, "sleep", sleeps.append)
    args = SimpleNamespace(host="server", identity=None, remote_project="/project", timeout=60)
    assert videos.remote(args, ["python", "tool.py"]) == {"complete": True}
    assert sleeps == [2, 4]
    attempts.clear()
    monkeypatch.setattr(videos.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=255, stderr="reset"))
    with pytest.raises(RuntimeError, match="reset"):
        videos.remote(args, ["python", "tool.py"])
    assert sleeps[-4:] == [2, 4, 8, 16]


def test_reconnect_waits_then_reuses_original_render(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    attempt(tmp_path, "scene_1", "a000")
    original = videos.render(tmp_path, "scene_1", "a000")
    lock = Path(original["evidence_directory"]) / "render.lock"
    lock.write_text(str(videos.os.getpid()))
    monkeypatch.setattr(videos.time, "sleep", lambda _: lock.unlink())
    assert videos.render(tmp_path, "scene_1", "a000", wait_existing_seconds=60) == original


def archive_fixture(monkeypatch, files, entry=None):
    import io
    import tarfile
    def transfer(args, source, target, names, max_bytes):
        with tarfile.open(target, "w") as bundle:
            for name in names:
                item = tarfile.TarInfo(name)
                item.size = len(files[name])
                if entry:
                    entry(item)
                bundle.addfile(item, io.BytesIO(files[name]))
        return SimpleNamespace(returncode=0, stderr=b"")
    monkeypatch.setattr(videos, "download", transfer)
    import hashlib
    return {"evidence_directory": "/evidence", "files": {
        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in files.items()}}


def test_bundle_download_verifies_and_preserves_existing_correct_file(tmp_path, monkeypatch):
    manifest = archive_fixture(monkeypatch, {"head_left.mp4": b"left", "head_right.mp4": b"right"})
    existing = tmp_path / "head_left.mp4"
    existing.write_bytes(b"left")
    before = existing.stat().st_mtime_ns
    videos.download_files(SimpleNamespace(), manifest, tmp_path)
    assert videos.verified(tmp_path, manifest)
    assert existing.stat().st_mtime_ns == before
    assert not (tmp_path / ".download.tar.partial").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "unexpected"])
def test_bundle_rejects_unlisted_paths(tmp_path, monkeypatch, name):
    manifest = archive_fixture(monkeypatch, {"head.mp4": b"video"}, lambda entry: setattr(entry, "name", name))
    with pytest.raises(RuntimeError, match="unexpected"):
        videos.download_files(SimpleNamespace(), manifest, tmp_path)
    assert not (tmp_path / "head.mp4").exists()


@pytest.mark.parametrize("kind", [b"1", b"2"])
def test_bundle_rejects_hardlinks_and_symlinks(tmp_path, monkeypatch, kind):
    def link(entry):
        entry.type = kind
        entry.linkname = "../../escape"
    manifest = archive_fixture(monkeypatch, {"head.mp4": b"video"}, link)
    with pytest.raises(RuntimeError, match="type/size"):
        videos.download_files(SimpleNamespace(), manifest, tmp_path)


def test_bundle_corruption_preserves_old_video_and_partial(tmp_path, monkeypatch):
    manifest = archive_fixture(monkeypatch, {"head.mp4": b"video"})
    manifest["files"]["head.mp4"]["sha256"] = "bad"
    (tmp_path / "head.mp4").write_bytes(b"old")
    with pytest.raises(RuntimeError, match="checksum"):
        videos.download_files(SimpleNamespace(), manifest, tmp_path)
    assert (tmp_path / "head.mp4").read_bytes() == b"old"
    assert (tmp_path / "head.mp4.partial").read_bytes() == b"video"


def test_archive_padding_cannot_consume_disk_reserve(tmp_path, monkeypatch):
    manifest = archive_fixture(monkeypatch, {"result.json": b"{}"})
    monkeypatch.setattr(videos.shutil, "disk_usage", lambda _: SimpleNamespace(free=2 * 1024 ** 3 + 100))
    with pytest.raises(RuntimeError, match="2 GiB reserve"):
        videos.download_files(SimpleNamespace(), manifest, tmp_path)
    assert not (tmp_path / ".download.tar.partial").exists()


def test_archive_byte_budget_stops_before_oversized_write():
    import io
    out = io.BytesIO()
    with pytest.raises(RuntimeError, match="byte budget"):
        videos.copy_bounded(io.BytesIO(b"too long"), out, 3)
    assert out.getvalue() == b""


def test_local_index_distinguishes_pending_unavailable_and_server_only(tmp_path):
    group = tmp_path / "release" / "run"
    videos.save(group / "index.json", [dict(scene_id=s, attempt="a000", failure_code="physics_failed")
                                      for s in ("pending", "no_trace", "server")])
    videos.save(group / "no_trace" / "a000" / "manifest.json",
                dict(status="unavailable", reason="no_trace_initialization_or_worker_failure"))
    videos.save(group / "server" / "a000" / "manifest.json",
                dict(status="complete", evidence_directory="/server/evidence"))
    summary = videos.build_local_index(tmp_path)
    rows = json.loads((tmp_path / "failure_video_index.json").read_text())["cases"]
    by_scene = {r["scene_id"]: r for r in rows}
    assert summary["cases"] == 3
    assert by_scene["pending"]["local_status"] == "pending"
    assert by_scene["no_trace"]["local_status"] == "unavailable"
    assert "no_trace" in by_scene["no_trace"]["evidence_issue"]
    assert by_scene["server"]["local_status"] == "server_only_or_partial"
    assert by_scene["server"]["remote_evidence_directory"] == "/server/evidence"
    assert all(Path(r["head_left_path"]).is_absolute() for r in rows)


def test_local_index_preserves_variants_and_campaign_attempts(tmp_path):
    for variant in ("baseline", "alternate"):
        videos.save(tmp_path / "r1" / "ablation" / variant / "index.json", [dict(scene_id="scene", attempt="a000")])
    videos.save(tmp_path / "r2" / "smoke" / "index.json", [dict(scene_id="scene", attempt="a000", trial=t)
                for t in ("experiments/batch/first", "experiments/batch/second")])
    videos.build_local_index(tmp_path)
    rows = json.loads((tmp_path / "failure_video_index.json").read_text())["cases"]
    assert len(rows) == 4
    assert len({r["head_left_path"] for r in rows}) == 4
    assert {r["variant"] for r in rows} == {"baseline", "alternate", ""}
    assert len({r["trial"] for r in rows if r["release"] == "r2"}) == 2


def test_local_index_rechecks_sha_without_overwriting_video(tmp_path, monkeypatch):
    dest = tmp_path / "release" / "run" / "scene" / "a000"
    dest.mkdir(parents=True)
    manifest = archive_fixture(monkeypatch, {"head_left.mp4": b"left", "head_right.mp4": b"right"})
    manifest["status"] = "complete"
    videos.save(dest / "manifest.json", manifest)
    videos.save(dest / "download.json", dict(verified=True, status="complete"))
    (dest / "head_left.mp4").write_bytes(b"corrupted")
    (dest / "head_right.mp4").write_bytes(b"right")
    before = (dest / "head_left.mp4").stat().st_mtime_ns
    videos.build_local_index(tmp_path, verify_hashes=True)
    row = json.loads((tmp_path / "failure_video_index.json").read_text())["cases"][0]
    assert row["sha_verified"] is False
    assert row["sha_validation"] == "checksum_or_file_missing"
    assert row["local_status"] != "complete"
    assert (dest / "head_left.mp4").stat().st_mtime_ns == before


def test_new_render_keeps_original_jsonl_and_missing_log_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path / "project")
    source = attempt(tmp_path / "collection", "scene", "a000")
    assert videos.event_metadata(source.parents[2], "scene", "a000")["reason"] == "source_events_jsonl_missing"
    raw = b'{"event":"primitive_rejected","reason":"contact"}\n'
    (source / "events.jsonl").write_bytes(raw)
    manifest = videos.render(source.parents[2], "scene", "a000")
    assert "events.jsonl" in manifest["files"]
    assert (Path(manifest["evidence_directory"]) / "events.jsonl").read_bytes() == raw
    assert (source / "events.jsonl").read_bytes() == raw


def test_events_supplement_preserves_primary_manifest_and_download(tmp_path, monkeypatch):
    monkeypatch.setattr(videos, "PROJECT", tmp_path)
    dest = tmp_path / "runs" / "failure_videos" / "r" / "run" / "scene" / "a000"
    videos.save(dest / "manifest.json", dict(status="complete", files={}))
    videos.save(dest / "download.json", dict(verified=True, status="complete"))
    original = [(dest / n).read_bytes() for n in ("manifest.json", "download.json")]
    metadata = archive_fixture(monkeypatch, {"events.jsonl": b'{"reason":"path"}\n'})
    metadata.update(status="complete", source_path="/collection/attempts/scene/a000/events.jsonl")
    monkeypatch.setattr(videos, "remote", lambda *args: metadata)
    args = SimpleNamespace(release="r", run="run", root="/collection", remote_python="python", remote_script="tool.py")
    assert videos.supplement_events(args, dict(scene_id="scene", attempt="a000"))["status"] == "complete"
    assert [(dest / n).read_bytes() for n in ("manifest.json", "download.json")] == original
    assert json.loads((dest / "events_supplement.json").read_text())["verified"] is True
    videos.build_local_index(tmp_path / "runs" / "failure_videos", verify_hashes=True)
    row = json.loads((tmp_path / "runs" / "failure_videos" / "failure_video_index.json").read_text())["cases"][0]
    assert row["events_jsonl_sha_verified"] is True
    assert row["events_jsonl_source_path"] == metadata["source_path"]
    (dest / "events.jsonl").write_bytes(b"corrupted")
    videos.build_local_index(tmp_path / "runs" / "failure_videos", verify_hashes=True)
    row = json.loads((tmp_path / "runs" / "failure_videos" / "failure_video_index.json").read_text())["cases"][0]
    assert row["events_jsonl_sha_verified"] is False
    assert row["events_jsonl_status"] == "checksum_or_file_missing"
