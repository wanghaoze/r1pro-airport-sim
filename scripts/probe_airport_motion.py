"""Isolated diagnostic attempt: never publishes a training dataset."""
import argparse
import json
from pathlib import Path
from r1pro_teleop.airport_fsm.contracts import Config
from r1pro_teleop.airport_fsm.machine import run_attempt

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root',type=Path,required=True)
p.add_argument('--scene-id',required=True)
p.add_argument('--config',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
scene=a.source_root/'scenes'/a.scene_id
result=run_attempt(json.loads((scene/'scene.json').read_text()),scene/'mobile.xml',
                   Config.load(a.config),a.output,0)
print(json.dumps({k:result.get(k) for k in ('scene_id','physics_success','simulation_seconds','failure_code','recovery_used')}))
