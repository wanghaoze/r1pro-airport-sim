"""Continuous original Trace raw1/raw2 replay with explicit one-tray geometry."""
from pathlib import Path
import json
from types import SimpleNamespace
import h5py
from ..airport_fsm.exporter import Replay
from ..airport_fsm.contracts import Config,fingerprint,sha256_file,Fault
from ..airport_fsm.geometry import Geometry
from ..single_tray_lab.replay import SingleTrayReplay

class ThreeTableTraceReplay(Replay):
 def __init__(self,case,*,render=True):
  case=Path(case);manifest_path=case/'scene/scene.json';manifest=json.loads(manifest_path.read_text());trace=case/'attempt/trace.h5'
  if manifest.get('schema')!='airport_three_table_single_tray_scene/1' or manifest.get('task_profile')!='three_table_single_tray_action3_v1':raise Fault('new_three_table_manifest_required')
  with h5py.File(trace,'r') as f:
   meta=json.loads(f.attrs['metadata_json'])
   if f.attrs.get('schema') not in ('airport_fsm_raw/1','airport_fsm_raw/2'):raise Fault('original_trace_raw_required')
  spec=meta['scene']
  if fingerprint(spec)!=fingerprint(manifest['legacy_spec']) or meta['scene_id']!=manifest['scene_id'] or sha256_file(manifest['xml'])!=meta['scene_xml_sha256']:raise Fault('same_original_trace_manifest_identity_required')
  cfg=Config(**meta['config']).validate();self.manifest=manifest;self.environment_events={};self.environment_event_count=0
  for row in [json.loads(x) for x in (case/'attempt/events.jsonl').read_text().splitlines() if x.strip()]:
   evidence=row.get('environment_evidence')
   if evidence is not None:
    if row.get('event')!='passenger_payload_initialized' or evidence.get('schema')!='airport_passenger_environment_transition/1':raise Fault('unrecognized_environment_journal')
    self.environment_events.setdefault(row['frame'],[]).append(evidence)
  def apply_environment(frame,runtime):
   context=SimpleNamespace(mj=runtime.mj,model=runtime.m,data=runtime.d,meta={'scene':manifest})
   for evidence in self.environment_events.get(frame,[]):
    SingleTrayReplay.environment(context,evidence);self.environment_event_count+=1
  super().__init__(case,{'trace':str(trace),'scene_id':manifest['scene_id']},diagnostic=True,spec=spec,cfg=cfg,xml=manifest['xml'],geometry=Geometry(spec,expected_trays=1),render=render,before_frame=apply_environment)
  self.source_files=dict(trace=str(trace),events=str(case/'attempt/events.jsonl'),scene_json=str(manifest_path),scene_xml=manifest['xml'])
