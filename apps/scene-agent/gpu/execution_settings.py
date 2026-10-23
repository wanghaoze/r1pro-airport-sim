"""Observed physical GPU inventory and per-request validated device selection."""
import csv
import subprocess
import time

def gpu_inventory():
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu=index,uuid,name,memory.total,memory.free','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8)
        if p.returncode:raise RuntimeError(p.stderr.strip())
        rows=[dict(index=int(r[0]),uuid=r[1].strip(),name=r[2].strip(),totalMiB=int(r[3]),freeMiB=int(r[4])) for r in csv.reader(p.stdout.splitlines())]
        return dict(devices=rows,sampledAt=time.time(),error=None)
    except Exception as exc:return dict(devices=[],sampledAt=time.time(),error=str(exc))

def selection(payload, kind, inventory=None):
    observed=inventory or gpu_inventory();available={d['index'] for d in observed['devices']}
    if not available:raise ValueError('GPU inventory unavailable: '+str(observed.get('error')))
    if kind=='training.create':
        ids=payload.get('trainingGpuIds',sorted(available))
        if not isinstance(ids,list) or not ids or any(type(i)!=int for i in ids) or len(ids)!=len(set(ids)) or 8%len(ids):raise ValueError('invalid_training_GPU_selection')
    elif kind=='evaluation.mse':ids=[payload.get('inferenceGpu',min(available))]
    else:ids=[payload.get('simulationGpu',min(available)),payload.get('inferenceGpu',min(available))]
    if any(type(i)!=int or i not in available for i in ids):raise ValueError('selected_GPU_not_present')
    return list(dict.fromkeys(ids))

def availability(payload,kind):
    inventory=gpu_inventory()
    try:ids=selection(payload,kind,inventory)
    except ValueError as exc:return str(exc)
    for d in inventory['devices']:
        if d['index'] in ids and d['freeMiB']<24000:return f"GPU {d['index']} has {d['freeMiB']} MiB free; waiting for at least 24000 MiB without stopping other services"
    if kind=='training.create':
        p=subprocess.run(['nvidia-smi','--query-compute-apps=gpu_uuid,used_gpu_memory','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8)
        if p.returncode:return 'Cannot verify selected training GPU processes'
        uuids={d['uuid'] for d in inventory['devices'] if d['index'] in ids}
        for row in csv.reader(p.stdout.splitlines()):
            if row and row[0].strip() in uuids and float(row[1])>4096:return 'Selected training GPU has an existing model process; waiting'
    return None
