"use client";
import {DEFAULT_FILTER} from '@/lib/execution-settings';
export function GpuSelect({inventory,label,value,onChange}:{inventory:any;label:string;value:string;onChange:(v:string)=>void}){
 return <label>{label}<select className="field" aria-label={label} value={value} onChange={e=>onChange(e.target.value)}><option value="">Server default</option>{(inventory?.devices||[]).map((g:any)=><option key={g.index} value={g.index}>GPU {g.index} · {g.name} · {(g.freeMiB/1024).toFixed(1)} GB free</option>)}</select>{inventory?.error&&<span role="alert">{inventory.error}</span>}</label>;
}
export function FilterSettings({value,onChange,limits=DEFAULT_FILTER}:{value:any;onChange:(v:any)=>void;limits?:any}){
 limits={...DEFAULT_FILTER,...limits};
 const fields:any={maxStepRad:'Maximum joint step (rad / frame)',maxVelocityRadS:'Maximum joint velocity (rad / s)',maxTrackingErrorRad:'Maximum tracking error (rad)',maxObservationAgeSeconds:'Maximum feedback age (s)'};
 return <details><summary>Joint interpolation filter · all models</summary><p>Applies to π0.5, G0.5 and GR00T after unit conversion. Limits can be tightened within the robot envelope. Each 20 Hz target is interpolated over 25 physical substeps; joint positions and gripper range remain bounded.</p>{Object.entries(fields).map(([key,label])=><label key={key}>{String(label)}<input className="field" aria-label={String(label)} type="number" min="0.000001" max={limits[key]} step="any" value={value[key]} onChange={e=>onChange({...value,[key]:+e.target.value})}/><small>Robot ceiling: {limits[key]}</small></label>)}<p>Settings are frozen per new run. Active runs retain their recorded configuration.</p></details>;
}
