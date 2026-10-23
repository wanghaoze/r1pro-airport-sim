"""Find an already-owned checkpoint service; never trust caller supplied URLs."""
import json
import sys
from pathlib import Path
import time
import urllib.request

def find_service(root,entry):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gpu'))
    from studio_backend import read,identity
    for marker in sorted((root/'runs').glob('live_*/model_http.ready.json')):
        run=marker.parent;ready=read(marker);saved=read(run/'controller.identity.json');actual=identity(saved.get('pid'))
        if not actual or actual.get('state')=='Z' or any(actual.get(k)!=saved.get(k) for k in ('pid','start_ticks','command','cwd')):continue
        status=read(run/'live_status.json')
        if time.time()-status.get('heartbeat_unix',0)>15 or status.get('stage') not in ('server_ready','rollout_finished_server_ready'):continue
        if ready.get('checkpoint_id')!=entry['id']:continue
        original=read(run/'checkpoints.json',[])
        if len(original)!=1 or original[0].get('receiptSha256')!=entry.get('receiptSha256') or original[0].get('modelConfig')!=entry.get('modelConfig'):continue
        # Health is required for pi05. Earlier G0.5 wrapper lacks GET; validate its live process ancestry.
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{int(ready['port'])}/health",timeout=2) as r:health=json.load(r)
            if health.get('checkpointId')!=entry['id'] or health.get('ready') is not True:continue
            if health.get('actionFilterContract')!=ready.get('actionFilterContract'):continue
        except Exception:
            if entry.get('family')!='g05':continue
            found=False
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    cmd=(proc/'cmdline').read_bytes().replace(b'\0',b' ').decode()
                    if 'studio_model_http.py' not in cmd or ('--run '+str(run)+' ') not in cmd:continue
                    parent=int(proc.name)
                    for _ in range(5):
                        if parent==saved['pid']:found=True;break
                        fields=(Path('/proc')/str(parent)/'stat').read_text().rsplit(')',1)[1].split();parent=int(fields[1])
                except (OSError,ValueError):continue
            if not found:continue
        return dict(ready,sharedRun=str(run),controllerIdentity=saved,reused=True)
    return None
