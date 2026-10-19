"""Append-only pre-action observer for a shared legacy mobile Runtime.

This module never steps physics, solves IK, changes targets or changes old Trace
fields. The controller supplies its existing stable grasp confirmations and
payload-support measurements. Unavailable evidence rejects source qualification.
"""
import json
from pathlib import Path
import numpy as np
from ..vla.data_three_table_single_tray import PROFILE,RULE_REVISION,FINAL_ORIENTATION_DEFINITION,TABLE_IDS

def table_front_region_violation(table,position):
    """Original aisle-facing world front; derive extents from actual rotation."""
    from ..single_tray_lab.three_table_scene import table_front
    normal=table_front(table)[:2];center=np.asarray(table['center_world'])[:2]
    size=np.asarray(table['dimensions_m'])[:2];yaw=float(table.get('yaw_world',0))
    rotation=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
    tangent=rotation[:,int(np.argmax(size))]
    normal_extent=float(np.sum(abs(rotation.T@normal)*size/2))
    tangent_extent=float(np.sum(abs(rotation.T@tangent)*size/2))
    displacement=np.asarray(position)[:2]-center
    return bool(displacement@normal<normal_extent or abs(displacement@tangent)>tangent_extent)

class ObservedTrace:
    def __init__(self,trace,observer):self.trace=trace;self.observer=observer
    def __getattr__(self,key):return getattr(self.trace,key)
    def append(self,row):
        o=self.observer
        if o.pending is None:raise ValueError('missing_pre_action_observer_snapshot')
        if o.pending_frame!=self.trace.count:raise ValueError('observer_frame_alignment_changed')
        if hasattr(o,'pending_qpos') and (not np.array_equal(row['qpos'],o.pending_qpos) or row['sim_time']!=o.pending_time):raise ValueError('observer_pre_action_physics_state_changed')
        enriched=dict(row);enriched.update({'task_numeric/'+k:v for k,v in o.pending.items()})
        if hasattr(o,'guard_samples'):
            if len(o.guard_samples)!=int(row['executed_substeps']):raise ValueError('actual_guard_substep_coverage_changed')
            for key,shape,dtype in (('sim_time',(),float),('tray_corners_world',(8,3),float),('table_contact_counts',(3,),np.int32),('push_contact_domain',(),bool)):
                values=np.zeros((o.r.sim.nstep,)+shape,dtype=dtype)
                for i,sample in enumerate(o.guard_samples):values[i]=sample[key]
                enriched['task_guard/'+key]=values
        self.trace.append(enriched);o.pending=None

class ThreeTableObserver:
    def __init__(self,runtime,manifest,*,numeric_provider,confirmation_rule,max_contacts=256,guard_domain_provider=None):
        if manifest.get('task_rule_revision')!=RULE_REVISION:raise ValueError('fresh_observer_rule_required')
        if runtime.trace is None or runtime.trace.count!=0 :raise ValueError('live_raw2_trace_required')
        self.guard_domain_provider=guard_domain_provider;self.guard_samples=[]
        self.r=runtime;self.scene=manifest;self.provider=numeric_provider;self.capacity=max_contacts;self.confirmation_rule=dict(confirmation_rule)
        if confirmation_rule.get('schema')!='airport_existing_grasp_confirmation_rule/1' or confirmation_rule.get('stable_duration_s')!=.15 or confirmation_rule.get('contact_n')!=runtime.cfg.criteria.contact_n or not confirmation_rule.get('rule_id'):raise ValueError('existing_controller_confirmation_rule_required')
        self.origin=np.asarray(runtime.sim.base_joint_state(),float).copy();self.pending=None;self.pending_frame=None
        self.release_starts={};self.pending_releases={};self.stage3_requested=False;self.confirmed=np.zeros(2,bool);self.push_stage=0;self.action=None;self.spans=[];self.table=None;self.manipulating=False
        self.old_observation=runtime.observation;self.old_tick=runtime.tick;self.old_guard=runtime.guard;self.original_trace=runtime.trace
        runtime.record_ctrl_substeps=True
        self.original_trace.file.attrs['schema']='airport_fsm_raw/2'
        record_metadata=json.loads(self.original_trace.file.attrs['metadata_json']);record_metadata['recorded_substep_controls_without_interpolation']=not runtime.cfg.substep_control_enabled
        record_metadata['source_model_parameters']=dict(schema='airport_recorded_initial_actuator_limits/1',actuator_forcerange=runtime.m.actuator_forcerange.tolist(),actuator_forcelimited=runtime.m.actuator_forcelimited.tolist(),source='actual_runtime_model_after_existing_limits_configuration',unchanged_xml_parameter_arrays={key:getattr(runtime.m,key).tolist() for key in ('actuator_gear','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','cam_pos','cam_quat','cam_fovy','cam_ipd')},restored_arrays=['actuator_forcerange'],other_arrays_verified_against_source_xml=True)
        self.original_trace.file.attrs['metadata_json']=json.dumps(record_metadata,allow_nan=False)
        runtime.trace=ObservedTrace(runtime.trace,self);runtime.observation=self.observation;runtime.tick=self.tick;runtime.guard=self.guard
        runtime.trace.event('three_table_observer_attached',task_profile=PROFILE,task_rule_revision=RULE_REVISION,
            final_orientation_definition=FINAL_ORIENTATION_DEFINITION,source='simulation/program_generated',
            observation_semantics='all task_numeric fields are measured BEFORE the recorded action interval',
            base_origin_joint_state=self.origin.tolist(),original_control_unchanged=True)
    def detach(self):
        self.r.observation=self.old_observation;self.r.trace=self.original_trace;self.r.tick=self.old_tick;self.r.guard=self.old_guard
    def begin_action(self,label,*,table_id=None,manipulating=False):
        if self.action is not None:raise ValueError('action_already_open')
        if label not in ('pick_empty','place_empty','push_loaded'):raise ValueError('unknown_action')
        self.action=(label,self.original_trace.count);self.set_operation_region(table_id,manipulating)
        self.r.trace.event('action_start',action_label=label,task_rule_revision=RULE_REVISION)
    def set_operation_region(self,table_id,manipulating):
        if table_id is not None and table_id not in TABLE_IDS:raise ValueError('unregistered_operation_table')
        if manipulating and table_id is None:raise ValueError('manipulation_table_required')
        self.table=table_id;self.manipulating=bool(manipulating)
    def set_push_stage(self,stage):
        if stage not in (0,1,2,3,4) or stage<self.push_stage:raise ValueError('push_stage_order_changed')
        if stage==3:
            self.stage3_requested=True;self.r.trace.event('push_stage_intent',stage=3,actual_lowforce_release_not_yet_verified=True);return
        self.push_stage=stage;self.r.trace.event('actual_push_stage',stage=stage)
    def confirm_grasp(self,sides,*,stable_frames,contact_n):
        # Stable history must be supplied by the actual controller; no phase
        # labels or provisional contact set this flag.
        if stable_frames<3 or self.original_trace.count-stable_frames+1<0 or contact_n!=self.r.cfg.criteria.contact_n:raise ValueError('existing_stable_confirmation_required')
        obs=self.old_observation();forces=np.asarray(obs['gripper_contact_force']).reshape(-1,2)[0]
        jaw=np.asarray(self.r.sim.state())[[7,15]]
        for side in sides:
            i=('left','right').index(side)
            if forces[i]<=contact_n:raise ValueError('actual_confirmed_contact_missing')
            self.confirmed[i]=True
        self.r.trace.event('grasp_confirmed',schema='airport_actual_grasp_confirmation_event/1',confirmation_rule_id=self.confirmation_rule['rule_id'],stable_start_frame=self.original_trace.count-stable_frames+1,after_existing_close_confirmation=True,sides=list(sides),stable_frames=int(stable_frames),
            contact_n=float(contact_n),gripper_contact_force=forces.tolist(),measured_jaw=jaw.tolist(),
            target_jaw=np.asarray(self.r.sim.target)[[7,15]].tolist(),semantics='controller_existing_stable_contact_confirmation')
    def begin_release(self,sides):
        for side in sides:self.release_starts[side]=self.original_trace.count
        self.r.trace.event('actual_release_command_started',sides=list(sides),target_jaw=np.asarray(self.r.sim.target)[[7,15]].tolist())
    def release_grasp(self,sides):
        # An accepted opening command is an intent, not proof that contact has
        # already disappeared. Real pre-action force verifies the later moment.
        for side in sides:
            start=self.release_starts.get(side)
            if self.confirmation_rule.get('release_evidence_mode')=='existing_low_force_commanded_open' and start is None:raise ValueError('actual_release_command_start_required')
            self.pending_releases[side]=start
        self.r.trace.event('actual_release_command_completed_not_contact_confirmation',sides=list(sides))
    def _observe_releases(self,forces,jaw,command):
        for side,start in list(self.pending_releases.items()):
            i=('left','right').index(side);rule=self.confirmation_rule
            if forces[i]>rule['contact_n']:continue
            mode=rule.get('release_evidence_mode','existing_measured_opening_minimum')
            if mode=='existing_low_force_commanded_open':
                opening=np.asarray(rule['existing_open_command_m'],dtype=command.dtype)
                if command[i]<opening:continue
                details=dict(release_command_start_frame=start,after_existing_release_verification=True)
            else:
                if jaw[i]<rule['release_opening_min_m']:continue
                details={}
            self.confirmed[i]=False
            self.r.trace.event('grasp_released',schema='airport_actual_grasp_confirmation_event/1',confirmation_rule_id=rule['rule_id'],sides=[side],measured_contact_force_n=float(forces[i]),measured_opening_m=float(jaw[i]),actual_command_opening_m=float(command[i]),confirmation_semantics='first_actual_lowforce_pre_action_observation_after_existing_open_command_completion',**details)
            del self.pending_releases[side]
        if self.stage3_requested and not self.confirmed[1] and 'right' not in self.pending_releases:
            self.push_stage=3;self.stage3_requested=False;self.r.trace.event('actual_push_stage',stage=3,verified_actual_right_release=True)
    def complete_action(self,*,verified,measured_endpoint_frame,**details):
        if not verified or self.action is None:raise ValueError('verified_open_action_required')
        label,a=self.action;b=self.original_trace.count
        if not a<=measured_endpoint_frame<b:raise ValueError('endpoint_must_be_actual_recorded_pre_action_frame')
        if not bool(self.original_trace.file['transition_completed'][measured_endpoint_frame]):raise ValueError('endpoint_transition_incomplete')
        span=dict(action_label=label,start_frame=a,end_frame=b,measured_endpoint_frame=measured_endpoint_frame,verified=True,**details)
        self.spans.append(span);self.r.trace.event('action_complete',**span);self.action=None
    def environment_event(self,journal):
        if journal.get('schema')!='airport_passenger_environment_transition/1':raise ValueError('actual_payload_journal_required')
        import hashlib
        self.r.trace.event('observer_environment_journal_bound',environment_journal_sha256=hashlib.sha256(json.dumps(journal,sort_keys=True,allow_nan=False).encode()).hexdigest(),payload_only=True)
    def observation(self):
        # Guards inspect observations at every substep. They must never replace
        # the interval's original pre-action training observation.
        return self.old_observation()
    def tick(self,*args,**kwargs):
        if self.pending is not None:raise ValueError('nested_observer_tick')
        self.pending=self.capture();self.pending_frame=self.original_trace.count
        self.pending_qpos=self.r.d.qpos.copy();self.pending_time=float(self.r.d.time);self.guard_samples=[]
        try:return self.old_tick(*args,**kwargs)
        finally:self.pending=None
    def guard(self):
        try:return self.old_guard()
        finally:
            if self.pending is not None:
                sample=self.capture(include_environment=False)
                self.guard_samples.append(dict(sim_time=float(self.r.d.time),tray_corners_world=sample['tray_corners_world'],table_contact_counts=sample['table_contact_counts'],push_contact_domain=bool(self.guard_domain_provider()) if self.guard_domain_provider else False))
    def capture(self,*,include_environment=True):
        r=self.r;m,d=r.m,r.d;tray=d.body(self.scene['tray'].get('body','tray'));R=tray.xmat.reshape(3,3)
        p=np.zeros((2,self.capacity,3));n=np.zeros_like(p);active=np.zeros((2,self.capacity),bool);counts=np.zeros(3,np.int32);sizes=np.zeros(2,int);forces=np.zeros(2)
        for ci,c in enumerate(d.contact):
            if min(c.geom)<0:continue
            bodies=[int(m.geom_bodyid[g]) for g in c.geom];force=np.zeros(6);r.mj.mj_contactForce(m,d,ci,force)
            if tray.id not in bodies:continue
            other=bodies[1] if bodies[0]==tray.id else bodies[0];name=m.body(other).name
            ancestor=other
            while ancestor>0:
                ancestor_name=m.body(ancestor).name
                if ancestor_name in TABLE_IDS:counts[TABLE_IDS.index(ancestor_name)]+=1;break
                ancestor=int(m.body_parentid[ancestor])
            # Table support follows the existing live controller: every real
            # MuJoCo tray/table contact counts, including low-force contacts.
            # Finger-contact force qualification remains unchanged.
            if force[0]<=.05:continue
            for side,i in (('left',0),('right',1)):
                if name.startswith(side+'_gripper_finger'):
                    j=sizes[i]
                    if j>=self.capacity:raise ValueError('actual_contact_capacity_exceeded')
                    p[i,j]=(c.pos-tray.xpos)@R;n[i,j]=np.asarray(c.frame[:3])@R;active[i,j]=True;sizes[i]+=1;forces[i]+=force[0]
        dims=np.asarray(self.scene['tray']['size']);corners=np.array([[x,y,z] for x in (-dims[0]/2,dims[0]/2) for y in (-dims[1]/2,dims[1]/2) for z in (0,dims[2])])@R.T+tray.xpos
        footprint=[];front_violation=False
        for t in self.scene['tables']:
            center=np.asarray(t['center_world']);size=np.asarray(t['dimensions_m']);yaw=float(t.get('yaw_world',0));T=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]])
            footprint.append((t['table_id'],bool(np.all(abs((corners[:,:2]-center[:2])@T)<=size[:2]/2))))
            if self.manipulating and self.table==t['table_id']:
                front_violation=table_front_region_violation(t,d.body('base_link').xpos)
        env=self.provider() if include_environment else {}
        required=('payload_loaded','payload_mass','floor_contact','tray_clearance','tray_goal_reached')
        if include_environment and any(k not in env for k in required):raise ValueError('actual_environment_numeric_missing')
        base=np.asarray(r.sim.base_joint_state());state=np.asarray(r.sim.state());command=np.asarray(r.sim.target)
        if include_environment:self._observe_releases(forces,state[[7,15]],command[[7,15]])
        B=d.body('base_link').xmat.reshape(3,3)
        return dict(env,state19=np.r_[state,base-self.origin].astype(np.float32),action19=np.r_[command,r.sim.base_target].astype(np.float32),
            gripper_contact_force=forces,gripper_grasp_confirmed=self.confirmed.copy(),gripper_openings=state[[7,15]],gripper_command_openings=command[[7,15]],
            support_contact=np.int32(counts.sum()),table_contact_counts=counts,tray_footprint_on_table=np.array([dict(footprint)[t] for t in TABLE_IDS],bool),
            tray_position=tray.xpos.copy(),tray_corners_world=corners,tray_long_axis_world=R[:,0].copy(),robot_forward_world=B[:,0].copy(),robot_left_world=B[:,1].copy(),
            base_front_violation=np.bool_(front_violation),push_stage=np.int32(self.push_stage),
            operation_table_index=np.int32(-1 if self.table is None else TABLE_IDS.index(self.table)),operation_manipulation=np.bool_(self.manipulating),
            gripper_tray_contact_points_local=p,gripper_tray_contact_normals_local=n,gripper_tray_contact_active=active)

def normalize_observed_trace(original,output,*,metadata):
    """Create a new derived raw2 file; preserve old control/archive bytes.

    Supplemental pre-action fields replace only the new file's numeric aliases.
    Original legacy fields remain under legacy_numeric/* for lineage/audits.
    """
    import shutil,h5py,hashlib
    original=Path(original);output=Path(output)
    if output.exists():raise FileExistsError(output)
    if metadata.get('task_profile')!=PROFILE or metadata.get('task_rule_revision')!=RULE_REVISION or metadata.get('final_orientation_definition')!=FINAL_ORIENTATION_DEFINITION:raise ValueError('fresh_derived_rule_metadata_required')
    original_sha=hashlib.sha256(original.read_bytes()).hexdigest()
    with h5py.File(original,'r') as f:
        if f.attrs.get('schema')!='airport_fsm_raw/2' or 'task_numeric' not in f:raise ValueError('actual_observed_legacy_raw2_required')
        frames=int(f.attrs['num_frames'])
        if frames<1 or any(len(ds)!=frames for ds in f['task_numeric'].values()):raise ValueError('supplemental_pre_action_frames_incomplete')
    output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,output)
    with h5py.File(output,'r+') as f:
        f.attrs['original_schema']=f.attrs['schema'];f.attrs['schema']='airport_three_table_single_tray_raw/2'
        f.attrs['original_metadata_json']=f.attrs['metadata_json'];meta=dict(metadata,original_trace=str(original),original_trace_sha256=original_sha,
            numeric_derivation='live_same_runtime_pre_action_observer',source='simulation/program_generated',
            observation_semantics='task_numeric measured before same recorded ctrl_substeps interval',training_ready=False)
        f.attrs['metadata_json']=json.dumps(meta,allow_nan=False)
        legacy=f.require_group('legacy_numeric')
        for key in list(f['task_numeric']):
            if key in f:f.copy(key,legacy,name=key);del f[key]
            f.copy('task_numeric/'+key,f,name=key)
        if 'task_guard' in f:
            counts=np.asarray(f['executed_substeps'][:],int)
            if np.any(counts<0) or np.any(counts>f['task_guard/sim_time'].shape[1]):raise ValueError('actual_guard_prefix_invalid')
            f['guard_frame_index']=np.repeat(np.arange(frames,dtype=np.int64),counts)
            for name in ('sim_time','tray_corners_world','table_contact_counts','push_contact_domain'):
                ds=f['task_guard/'+name]
                flattened=np.concatenate([ds[i,:count] for i,count in enumerate(counts)],axis=0)
                f['guard_'+name]=flattened
        for old,new in (('state','state16'),('action','action16')):
            if new not in f:f.copy(old,f,name=new)
        f.flush()
    if hashlib.sha256(original.read_bytes()).hexdigest()!=original_sha:raise ValueError('original_raw_changed_during_derivation')
    return dict(original_trace_sha256=original_sha,derived_trace_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),frames=frames,source_unchanged=True,training_ready=False)


def normalize_observer_events(original,output):
    """Keep legacy intent events while selecting explicit qualified action rows."""
    import hashlib
    original=Path(original);output=Path(output)
    if output.exists():raise FileExistsError(output)
    before=original.read_bytes();rows=[]
    for line in before.decode('utf-8').splitlines():
        if not line.strip():continue
        row=json.loads(line)
        if row.get('event') in ('action_start','action_complete') and not row.get('action_label'):
            row['original_event_name']=row['event'];row['event']='legacy_controller_'+row['event']
        rows.append(row)
    output.write_text(''.join(json.dumps(row,allow_nan=False)+'\n' for row in rows),encoding='utf-8')
    if original.read_bytes()!=before:raise ValueError('original_events_changed_during_derivation')
    return dict(original_events_sha256=hashlib.sha256(before).hexdigest(),derived_events_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),source_unchanged=True)


def audit_observed_lineage(derived):
    """Recheck original bytes and each copied/flattened numeric value."""
    import h5py,hashlib
    derived=Path(derived)
    with h5py.File(derived,'r') as child:
        meta=json.loads(child.attrs['metadata_json']);original=Path(meta['original_trace'])
        if hashlib.sha256(original.read_bytes()).hexdigest()!=meta['original_trace_sha256']:raise ValueError('original_physical_trace_changed')
        with h5py.File(original,'r') as parent:
            parent_meta=json.loads(parent.attrs['metadata_json'])
            if meta.get('source_model_parameters')!=parent_meta.get('source_model_parameters'):raise ValueError('recorded_initial_model_parameters_changed')
            if parent.attrs.get('schema')!='airport_fsm_raw/2':raise ValueError('original_physical_raw2_required')
            for key in ('qpos','qvel','integration_state','sim_time','ctrl_substeps','executed_substeps','transition_completed'):
                if not np.array_equal(child[key][:],parent[key][:]):raise ValueError('original_physical_values_changed:'+key)
            for key,ds in parent['task_numeric'].items():
                if not np.array_equal(child[key][:],ds[:]):raise ValueError('derived_live_numeric_changed:'+key)
            if 'task_guard' in parent:
                counts=parent['executed_substeps'][:].astype(int)
                if not np.array_equal(child['guard_frame_index'][:],np.repeat(np.arange(len(counts)),counts)):raise ValueError('guard_frame_lineage_changed')
                for key,ds in parent['task_guard'].items():
                    expected=np.concatenate([ds[i,:count] for i,count in enumerate(counts)],axis=0)
                    if not np.array_equal(child['guard_'+key][:],expected):raise ValueError('actual_guard_journal_lineage_changed:'+key)
        return dict(verified=True,original_trace=str(original),original_physical_trace_sha256=meta['original_trace_sha256'],derived_trace_sha256=hashlib.sha256(derived.read_bytes()).hexdigest(),copied_control_and_numeric_values_verified=True)
