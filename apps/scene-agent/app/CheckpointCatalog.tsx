"use client";
import {useState} from 'react';
import {Database,RefreshCw} from 'lucide-react';
import {displayText} from '@/lib/display';
export default function CheckpointCatalog({gpu,onRefresh,onEvaluate}:{gpu:any;onRefresh:()=>Promise<void>;onEvaluate:(id:string)=>void}){
 const [query,setQuery]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const rows=(gpu.checkpoints||[]).filter((c:any)=>c.closed===true);
 const visible=rows.filter((c:any)=>`${displayText(c.label)} ${c.family||'pi05'} ${c.updates}`.toLowerCase().includes(query.toLowerCase()));
 async function refresh(){setBusy(true);setError('');try{await onRefresh();}catch(e){setError(e instanceof Error?e.message:'Refresh failed');}finally{setBusy(false);}}
 return <section className="page-content checkpoint-page"><div className="page-title"><div><div className="eyebrow">WORKSTATION MODEL LIBRARY</div><h1>Checkpoints</h1><p>Saved models on the workstation, available from this GPT Site.</p></div><button className="button" disabled={busy} onClick={refresh}><RefreshCw size={15}/>{busy?'Refreshing…':'Refresh checkpoints'}</button></div>
 <div className="checkpoint-summary"><strong>{rows.length} registered checkpoints</strong><span>{gpu.live?'Workstation connected':'Last received snapshot'}</span><span>{gpu.receivedAt?new Date(gpu.receivedAt).toLocaleString('en-GB'):'Waiting for first synchronization'}</span></div>
 <p className="monitor-note">Weights stay on the workstation. Evaluations run there with the mandatory robot joint and speed filter. Sign in as the owner to submit jobs. A saved checkpoint is not a successful task result.</p>
 <label className="checkpoint-search">Find a model<input className="field" aria-label="Search checkpoints" placeholder="Model family, training mix or steps" value={query} onChange={e=>setQuery(e.target.value)}/></label>
 {error&&<p role="alert">{error}</p>}
 <div className="checkpoint-cards">{visible.map((c:any)=><article className="checkpoint-card" key={c.id}><div className="list-heading"><Database size={20}/><span>{(c.family||'pi05').toUpperCase()}</span></div><h2>{displayText(c.label)}</h2><dl><div><dt>Training updates</dt><dd>{c.updates>0?c.updates.toLocaleString():'Not reported'}</dd></div><div><dt>Policy horizon</dt><dd>{c.policyHorizon||20} frames</dd></div><div><dt>Storage</dt><dd>Workstation</dd></div></dl><p>{c.status||'Registered checkpoint; runtime validation required'}</p><code>{c.id}</code><button className="button" onClick={()=>onEvaluate(c.id)}>Use in policy evaluation</button></article>)}</div>
 {!visible.length&&<div className="empty"><h2>{rows.length?'No matching checkpoints':'No checkpoints received yet'}</h2><p>{rows.length?'Try another search.':'Refresh after the workstation worker reconnects.'}</p></div>}
 {gpu.modelAdapters?.some((m:any)=>!m.configured)&&<section className="checkpoint-pending"><h2>Model adapters awaiting configuration</h2>{gpu.modelAdapters.filter((m:any)=>!m.configured).map((m:any)=><p key={m.id}><strong>{m.label}</strong> · Compatible checkpoint configuration required</p>)}<p>These adapters are not additional usable checkpoints.</p></section>}
 </section>;
}
