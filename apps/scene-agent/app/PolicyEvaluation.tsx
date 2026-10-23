"use client";

import {GpuSelect,FilterSettings} from './ExecutionControls';
import {DiagnosticDetails} from './ErrorConsole';
import {DEFAULT_FILTER} from '@/lib/execution-settings';
import {useEffect,useState} from 'react';

import {requestId} from '@/lib/request-id';

import {displayText} from '@/lib/display';

import initial from '@/lib/initial-snapshot.json';

import SceneViewport from './SceneViewport';



export default function PolicyEvaluation({gpu,jobs,canOperate,onRefresh,onNotice,initialCheckpoint=''}:{initialCheckpoint?:string;gpu:any;jobs:any[];canOperate:boolean;onRefresh:()=>Promise<void>;onNotice:(s:string)=>void}){

  const [benchmark,setBenchmark]=useState<any>(null);

  useEffect(()=>{fetch('/help/runtime-comparison.json').then(r=>r.ok?r.json():null).then(setBenchmark).catch(()=>{});},[]);

  const safety='robot_limits';
  const [runtimeProfile,setRuntimeProfile]=useState('realtime'),[simGpu,setSimGpu]=useState(''),[inferGpu,setInferGpu]=useState(''),[filterSettings,setFilterSettings]=useState({...DEFAULT_FILTER}),[stopPending,setStopPending]=useState(false);

  const [room,setRoom]=useState(0),[checkpoint,setCheckpoint]=useState(initialCheckpoint),[seconds,setSeconds]=useState(10000),[timeout,setInferenceTimeout]=useState(30),[wall,setWall]=useState(0),[busy,setBusy]=useState(false),[selected,setSelected]=useState(''),[snapshot,setSnapshot]=useState<any>(null),[error,setError]=useState(''),[fit,setFit]=useState(0),[now,setNow]=useState(Date.now());

  const runs=jobs.filter(j=>j.kind==='evaluation.live');

  function resetPreview(){setSelected('');setSnapshot(null);setError('');setFit(x=>x+1);}

  useEffect(()=>{if(!selected){setSnapshot(null);setError('');return;}let active=true,handle:ReturnType<typeof setTimeout>;setSnapshot(null);setError('');

    async function poll(){try{const r=await fetch('/api/live?jobId='+encodeURIComponent(selected));const d:any=await r.json();if(!r.ok)throw Error(d.error);if(active){setSnapshot(d);setError('');setNow(Date.now());}}catch(e){if(active)setError(e instanceof Error?e.message:'Live connection lost');}finally{if(active)handle=setTimeout(poll,250);}}

    poll();return()=>{active=false;clearTimeout(handle);};},[selected]);

  const durationError=Number.isInteger(seconds)&&seconds>=1&&seconds<=10000?'':'Enter a whole number from 1 to 10000 seconds.';
  async function start(){if(durationError){onNotice(durationError);return;}setBusy(true);try{const r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'evaluation.live',filterSettings,...(simGpu!==''?{simulationGpu:+simGpu}:{}),...(inferGpu!==''?{inferenceGpu:+inferGpu}:{}),actionSafetyMode:safety,runtimeProfile,requestId:requestId(),checkpointIds:[checkpoint],sceneSetId:'isaac32_20261017',roomIds:[room],maxSimulationSeconds:seconds,inferenceTimeoutSeconds:timeout,maxWallSeconds:wall,transport:'ros2'})});const d:any=await r.json();if(!r.ok)throw Error(d.error);setSelected(d.id);setStopPending(false);onNotice('Independent policy evaluation queued. Live poses appear after Isaac initialization.');await onRefresh();}catch(e){onNotice(e instanceof Error?e.message:'Could not start evaluation');}finally{setBusy(false);}}

  async function stop(){setStopPending(true);try{const r=await fetch('/api/live',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jobId:selected})});const d=await r.json();if(!r.ok)throw Error(d.error);onNotice('Stop requested. Waiting for the workstation to close this run and preserve its recordings.');await onRefresh();}catch(e){setStopPending(false);onNotice(e instanceof Error?e.message:String(e));}}
  const actualRoom=snapshot?.roomId??runs.find(r=>r.id===selected)?.payload.roomIds?.[0]??room;

  const stage=snapshot?.stage||runs.find(r=>r.id===selected)?.status||'Waiting for status',terminal=['completed','failed','cancelled'].includes(snapshot?.status||runs.find(r=>r.id===selected)?.status),age=snapshot?.frameSampledAt?Math.max(0,now/1000-snapshot.frameSampledAt):null;

  const secondsDone=snapshot?.simulationSeconds??0,configured=snapshot?.configuration?.maxSimulationSeconds;

  const reason=snapshot?.report?.rooms?.[0]?.reason;const reasonText=typeof reason==='object'?reason?.message:reason;

  const outcome=!snapshot&&selected?'Loading run status':terminal?(snapshot?.report?.passedPairs>0?'Ended · Task passed':reasonText==='simulation_time_budget_reached'?'Ended · Simulation time limit reached':snapshot?.report?.modelFailures>0?'Ended · Model action rejected':'Ended · Evaluation stopped'):selected?(['waiting_gpu','queued','claimed'].includes(stage)?'Queued':stage.includes('initial')||stage==='preparing'?'Initializing':'Running'):'Ready to start';

  const joint=reasonText?.startsWith('policy_action_outside_mechanical_joint_range:')?reasonText.split(':')[1].split(';')[0]:null;

  const stopText=joint?`Model output exceeded the mechanical range of ${joint}. Execution stopped before applying the rejected action. Increasing the time limit will not resolve this.`:reasonText||snapshot?.message;



  return <section className="page-content policy-evaluation"><div className="page-title"><div><div className="eyebrow">SINGLE POLICY · NATIVE SIMULATION</div><h1>Policy evaluation</h1><p>Choose any registered room and checkpoint. Observe the actual rollout, then download that run's recordings.</p></div></div>

    {benchmark&&<div className="evaluation-card"><h2>Measured runtime comparison · Room 000</h2><p>Same checkpoint, room, simulation budget and robot action limits. {benchmark.note}</p><div style={{overflowX:'auto'}}><table><thead><tr><th>Runtime</th><th>Executed</th><th>Rollout wall time</th><th>Physics steps</th><th>Model wait</th><th>Real-time factor</th></tr></thead><tbody>{benchmark.runs.map((r:any)=><tr key={r.jobId}><td>{r.profile}</td><td>{r.frames} frames / {r.simulationSeconds.toFixed(2)} s</td><td>{r.rolloutWallSeconds.toFixed(2)} s</td><td>{r.physicsSeconds.toFixed(2)} s</td><td>{r.waitSeconds.toFixed(2)} s</td><td>{r.realtimeFactor.toFixed(2)}×</td></tr>)}</tbody></table></div><p>1.00× means real-time simulation. Initialization and warmup are reported separately in the JSON report. This is a speed comparison, not task success.</p><div className="figure-downloads">{benchmark.runs.map((r:any)=><div key={r.jobId}><p><strong>{r.profile} / recorded wall-clock speed</strong></p><video controls preload="metadata" src={r.wallVideo} style={{width:"100%",maxWidth:480}}/><p><button className="button" onClick={()=>setSelected(r.jobId)}>View {r.profile} run</button> <a className="button" href={r.wallVideo+'&download=1'} download>Download {r.profile} · actual wall-clock video</a></p></div>)}<a className="button" href="/help/runtime-comparison.json" download>Download measured comparison JSON</a></div></div>}<div className="policy-layout"><aside className="evaluation-card policy-config"><h2>New independent run</h2>

      <label>Room<select className="field" aria-label="Policy room" value={room} onChange={e=>{setRoom(+e.target.value);resetPreview();}}>{initial.rooms.map(r=><option key={r.id} value={r.id}>Room {String(r.id).padStart(3,'0')}</option>)}</select></label>

      <label>Model checkpoint<select className="field" aria-label="Policy checkpoint" value={checkpoint} onChange={e=>setCheckpoint(e.target.value)}><option value="">Select registered checkpoint</option>{(gpu.checkpoints||[]).map((c:any)=><option key={c.id} value={c.id}>{displayText(c.label)} · {c.family||'pi05'}</option>)}</select></label>

      <label>Isaac physics profile<select className="field" aria-label="Isaac physics profile" value={runtimeProfile} onChange={e=>setRuntimeProfile(e.target.value)}><option value="realtime">Realtime · CPU PhysX + GPU rendering</option><option value="baseline">GPU PhysX + GPU rendering</option></select></label><GpuSelect inventory={gpu.gpuInventory} label="Simulation / rendering GPU" value={simGpu} onChange={setSimGpu}/><GpuSelect inventory={gpu.gpuInventory} label="Model inference GPU" value={inferGpu} onChange={setInferGpu}/><p>NVIDIA Isaac Sim · PhysX. Realtime profile uses CPU physics and the selected GPU for rendering; model inference uses its selected GPU. Three.js is the browser preview only.</p><FilterSettings value={filterSettings} onChange={setFilterSettings} limits={gpu.filterLimits}/>
      <div className="monitor-note"><strong>Robot filter always enabled</strong><p>Joint and gripper bounds, arm speed and step limits, feedback freshness and tracking guards apply to every policy. Raw outputs are retained; filtered runs are excluded from pure model success rates.</p></div><label>Maximum simulation duration (seconds)<input className="field" aria-label="Maximum simulation duration" type="number" min="1" max="10000" value={seconds} onChange={e=>setSeconds(+e.target.value)}/></label>

      <p>Default extended run: 10000 seconds (200000 action frames), with no overall wall-clock guard. This is a finite cap. Model waiting time is excluded from simulation time. Task success, physical limits or errors can end the run earlier.</p>

      <details><summary>Advanced time limits</summary><label>Single inference timeout (seconds)<input className="field" aria-label="Single inference timeout" type="number" min="1" max="300" value={timeout} onChange={e=>setInferenceTimeout(+e.target.value)}/></label><label>Overall wall-clock guard (seconds)<input className="field" aria-label="Overall wall-clock guard" type="number" min="0" max="604800" value={wall} onChange={e=>setWall(+e.target.value)}/></label><p>0 disables the overall wall-clock guard. Inference and startup timeouts still apply. A nonzero guard includes checkpoint and Isaac initialization. Media finalization may take longer.</p></details>

      <p role={durationError?"alert":undefined}>{durationError||`${seconds} seconds = ${seconds*20} physics action frames at 20 Hz.`}</p><button className="button primary full" disabled={busy||!canOperate||!checkpoint||!!durationError} onClick={start}>{busy?'Submitting…':'Start policy evaluation'}</button>

      <p className="monitor-note">Registered initial room state · Pick → Place · fixed base · no teacher or IK fallback. Evaluation data never enters training automatically. G0.5 retains its 30 Hz training / 20 Hz diagnostic label; missing gripper outputs stop execution.</p>

      <button className="button full" disabled={!selected||terminal||!canOperate||stopPending} onClick={stop}>{stopPending?'Stop requested…':'Stop policy'}</button>
      <h2>Previous runs</h2><select className="field" aria-label="Select policy run" value={selected} onChange={e=>{setSelected(e.target.value);setStopPending(false);}}><option value="">Select a run</option>{runs.map(j=><option key={j.id} value={j.id}>Room {j.payload.roomIds?.[0]} · {j.payload.checkpointIds?.[0]} · {j.id.slice(0,8)} · {j.status}</option>)}</select>

    </aside><div className="policy-observation"><div className="evaluation-card"><div className="list-heading"><h2>Room {String(actualRoom).padStart(3,'0')} · {!selected?'Original room state':terminal?(snapshot?.frame==null?'Run stopped before native frames':'Final measured state'):'Live observation'}</h2><button className="button" onClick={resetPreview}>Reset preview</button><button className="button" onClick={()=>setFit(x=>x+1)}>Fit view</button></div><p><strong>{outcome}</strong> · {secondsDone.toFixed(2)} / {configured??'—'} s simulation · {snapshot?.frame??0} executed frames</p>{['clip_diagnostic','robot_limits'].includes(snapshot?.configuration?.actionSafetyMode)&&<div className="policy-stop"><strong>PROTECTED POLICY DIAGNOSTIC</strong><p>Out-of-range actions are explicitly clipped and logged. This run is excluded from pure model success rates.</p></div>}{terminal&&<div role="status" className="policy-stop"><strong>Stop reason</strong><p>{stopText||"Run ended; detailed report is not yet available."}</p><p>The simulator is stopped. This is the final recorded pose, not a stalled live stream.</p></div>}{selected&&<><p className="monitor-note">Checkpoint {snapshot?.checkpointId||'—'} · Overall wall time {snapshot?.report?.elapsedWallSeconds?.toFixed(2)??'—'} s</p><p>Last frame wall time: {snapshot?.rolloutWallSeconds?.toFixed(2)??'—'} s · Model: {terminal?'Stopped — last reply is historical':snapshot?.inference?.stage==='inferring'?'Running inference; simulator waiting':snapshot?.inference?.stage==='reply_received'?'Reply received; validating / executing actions':snapshot?.inference?.stage??'Waiting'} · Last request: {snapshot?.inference?.latencySeconds?.toFixed(2)??'—'} s</p></>}

      {error&&<p role="alert">{error} — retaining the last measured state.</p>}{!terminal&&age!==null&&<p className="monitor-note">Pose sample age {age.toFixed(1)} s. {terminal?'Run finished; viewing its final state.':age>3?'No new physical frame; the view is frozen while waiting.':'Live state polling; no interpolated or invented motion.'}</p>}

      <div className="policy-viewport"><SceneViewport key={selected||`initial-${actualRoom}-${fit}`} room={initial.rooms[actualRoom] as any} grid={false} fit={fit} live={selected?snapshot:null} liveMode={!!selected}/></div>

      <p className="monitor-note">{!selected&&"Original room preview. Start creates a new simulator run from its registered initial state. Resetting this preview does not cancel a running job. "}Interactive 3D uses measured native body poses on the website's source geometry. Native cameras below are the exact simulator rendering. Rendering and inference may run slower than 20 Hz wall-clock speed.</p>

      <div className="policy-cameras">{['overview','head_left','left_wrist','right_wrist'].map(name=><figure key={name}>{snapshot?.images?.[name]?<img src={snapshot.images[name]} alt={'Native '+name+' camera'}/>:<div className="curve-empty">Waiting for native frame</div>}<figcaption>{name.replaceAll('_',' ')}</figcaption></figure>)}</div>

      </div><div className="evaluation-card"><h2>This run's result & downloads</h2><h3>Errors, logs & actual runtime</h3><DiagnosticDetails items={[...(snapshot?.diagnostics||[]),...(snapshot?.report?[{source:'Complete run report',text:JSON.stringify(snapshot.report,null,2)}]:[]),...(snapshot?.engine?[{source:'Measured engine / GPU configuration',text:JSON.stringify(snapshot.engine,null,2)}]:[]),...(snapshot?.configuration?[{source:'Frozen run settings',text:JSON.stringify(snapshot.configuration,null,2)}]:[]),...(snapshot?.mediaError?[{source:'Media error',text:snapshot.mediaError}]:[])]}/><p>{stopText||'Start or select an evaluation.'}</p>{snapshot?.report?.totalRooms!=null&&<p>Pick / Place passed: {snapshot.report.passedPairs} / {snapshot.report.totalRooms} · {snapshot.report.temporalComparison}</p>}<div className="figure-downloads">{(snapshot?.downloads||[]).map((f:any)=><a className="button" key={f.name} href={f.url+'&download=1'} download>{f.name.endsWith('.mp4')?'Download video · ':'Download '}{f.name.replaceAll('_',' ')}</a>)}</div>{!snapshot?.downloads?.length&&<p>{!selected?'Original room state':terminal?(snapshot?.frame==null?'No native frames were recorded; this run has no motion video.':'Finalizing this run’s media; a video is available only if native frames were recorded.'):'Recordings become downloadable after this run stops and encoders close.'}</p>}<p className="monitor-note">Videos play on the 20 Hz simulation timeline; actual waiting and timing remain in the run report. {snapshot?.mediaError}</p><code>{selected}</code></div></div></div>

  </section>;

}
