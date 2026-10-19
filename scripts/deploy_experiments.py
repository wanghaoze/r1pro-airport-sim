"""Server-side fresh release deployment; invoke with a non-base Conda Python.

Copies only self-contained project resources from an existing release. No old
collections, experiments, source fingerprints or installed environments are rewritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile


def deploy(archive, asset_release, destination):
    if not (Path(sys.prefix) / "conda-meta").is_dir() or (Path(sys.prefix) / "condabin").exists():
        raise RuntimeError("Use non-base Conda")
    archive, asset_release, destination = map(lambda p: Path(p).resolve(), (archive, asset_release, destination))
    if destination.exists():
        raise FileExistsError(destination)
    if not (asset_release / "resources/scenes/server_v7/manifest.json").is_file():
        raise RuntimeError("Expected self-contained server_v7 resources")
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            target.relative_to(destination)
            if item.filename.startswith(("resources/", "outputs/", "runs/", ".secrets/", ".conda/")):
                raise ValueError("unexpected_bundle_entry")
        destination.mkdir(parents=True)
        bundle.extractall(destination)
    shutil.copytree(asset_release / "resources", destination / "resources")
    if (asset_release / "outputs").exists():
        shutil.copytree(asset_release / "outputs", destination / "outputs")
    # This release owns its source scenes and assets; do not reference old collection paths.
    record = {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "resource_source_release": str(asset_release), "destination": str(destination),
              "environment": sys.prefix, "simulation_only": True, "existing_collections_modified": False}
    (destination / "EXPERIMENT_DEPLOYMENT.json").write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True); p.add_argument("--asset-release", required=True)
    p.add_argument("--destination", required=True)
    a = p.parse_args()
    deploy(a.archive, a.asset_release, a.destination)
