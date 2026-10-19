"""Reproducible source/runtime export, excluding credentials, data and weights."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'apps/scene-agent'
def export():
    files={}
    for folder in ('app','lib','gpu','offline','public','drizzle','tests','offline-dist'):
        for p in (APP/folder).rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc' or p.name.startswith('ui-test'):continue
            files[p.relative_to(APP).as_posix()]=p
    for name in ('package.json','package-lock.json','tsconfig.json','PROJECT.md'):
        if (APP/name).exists():files[name]=APP/name
    for folder in ('r1pro_teleop','scripts'):
        for p in (ROOT/folder).rglob('*.py'):
            if '__pycache__' not in p.parts:files[p.relative_to(ROOT).as_posix()]=p
    files['gpu/initial-snapshot.json']=APP/'lib/initial-snapshot.json'
    files['README.md']=ROOT/'docs/site/WORKSTATION.md'
    files['docs/POLICY_EVALUATION.md']=ROOT/'docs/site/POLICY_EVALUATION.md'
    files['docs/USER_GUIDE.md']=ROOT/'docs/site/README.md'
    files['docs/SCENE_TASK_SPEC.md']=ROOT/'docs/SCENE_TASK_SPEC.md'
    out=ROOT/'exports/scene_studio_live_policy_20261019_v5.zip';out.parent.mkdir(exist_ok=True)
    manifest={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,strict_timestamps=False) as z:
        for name,p in sorted(files.items()):z.write(p,name)
        z.writestr('source_manifest.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert not any(any(part in n.split('/') for part in ('.secrets','.git','node_modules','.wrangler')) for n in z.namelist())
    receipt=dict(path=str(out),files=len(files),bytes=out.stat().st_size,sha256=hashlib.sha256(out.read_bytes()).hexdigest(),exclusions=['credentials','Git history','node_modules','datasets','checkpoints','raw_run_videos (static diagnostic demo included)'],zipCrcPassed=True)
    (ROOT/'runs/web_live_policy_20261019_v1/export.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))
if __name__=='__main__':export()
