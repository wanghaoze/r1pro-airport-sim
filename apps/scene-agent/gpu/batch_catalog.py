"""Read-only lineage: configured rooms != passed pairs != frozen training pairs."""
from collections import Counter
from pathlib import Path
import hashlib
import json

def read(path, default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {} if default is None else default

def source(pair):
    return pair.get('source_room') or next((s.get('source_room') for s in pair.get('segments',[]) if s.get('source_room')),None)

def catalog(root):
    root=Path(root);production=root/'runs/isaacsim_parallel_pickplace300_20261017_v1'
    frozen_path=root/'runs/real_isaac300_timeweighted_pi05_20261017_v1/frozen_simulation.json'
    frozen=read(frozen_path);progress=read(production/'progress_manifest.json')
    selected={source(p) for p in frozen.get('pairs',[])}-{None}
    qualified=set()
    # Production summary may cap its embedded pairs at the frozen target. Read each closed batch source instead.
    for manifest in production.glob('batch_*/native/dataset/batches/*/manifest.json'):
        receipt=read(manifest)
        if receipt.get('ready') and receipt.get('complete_source_pairs')==1 and receipt.get('action_segments')==2:
            segments=receipt.get('segments',[])
            if {s.get('prompt') for s in segments}=={'Pick up the tray','Place the tray'} and len({s.get('source_room') for s in segments})==1:
                key=source(receipt)
                if key:qualified.add(key)
    rows=[]
    for batch in sorted(production.glob('batch_[0-9]*')):
        config=read(batch/'config.json');prefix=str(batch/'native/rooms')+'/'
        accepted={p for p in qualified if p.startswith(prefix)};included={p for p in selected if p.startswith(prefix)}
        planned=len(config.get('cases',[]));exit_receipt=read(batch/'native.exit.json')
        rows.append(dict(id=batch.name,datasetId='isaac300_20261017',datasetVersion='dataset_v1',split='train',
            plannedRooms=planned,qualifiedPairs=len(accepted),trainingPairs=len(included),actionSegments=len(included)*2,
            excludedPairs=len(accepted-included),status='closed' if exit_receipt.get('returncode')==0 else 'See source receipt',
            sourceDirectory=str(batch),manifest=str(production/'dataset_v1/manifest.json')))
    return dict(rows=rows,qualifiedPairs=len(qualified),trainingPairs=len(selected),actionSegments=len(selected)*2,
        frozenManifest=str(frozen_path),frozenSha256=hashlib.sha256(frozen_path.read_bytes()).hexdigest() if frozen_path.exists() else None,
        scope='fixed_base_pickplace_only',note='Qualified overflow is not appended to the frozen 300-pair training release. Evaluation rooms never auto-enter training.')
