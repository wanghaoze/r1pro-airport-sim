"use client";
import {useEffect,useState} from 'react';
export function DiagnosticDetails({items}:{items:any[]}){
 return <div className="diagnostic-details">{items.map((e,i)=><details key={i}><summary>{e.source||`Error ${i+1}`}{e.truncated?' · log tail (full log in diagnostics download)':''}</summary><pre>{e.text||JSON.stringify(e,null,2)}</pre></details>)}</div>;
}
export default function ErrorConsole({jobs}:{jobs:any[]}){
 const [errors,setErrors]=useState<any[]>([]);
 useEffect(()=>{
  const record=(source:string,text:string)=>setErrors(old=>{const previous=old.find(e=>e.source===source&&e.text===text);return previous?old.map(e=>e===previous?{...e,count:e.count+1}:e):[...old,{source,text,count:1,time:new Date().toISOString()}];});
  const onError=(e:Event)=>{if(e instanceof ErrorEvent)record(e.filename||'Browser',e.error?.stack||e.message);else{const target=e.target as HTMLMediaElement&HTMLScriptElement&HTMLLinkElement;record(target?.currentSrc||target?.src||target?.href||'Browser resource',target?.error?.message||`Failed to load ${target?.tagName||'resource'}`);}};
  const onReject=(e:PromiseRejectionEvent)=>record('Unhandled promise',e.reason?.stack||String(e.reason));
  const original=window.fetch;
  const observed:typeof fetch=async(...args)=>{try{const r=await original(...args);if(!r.ok){const text=await r.clone().text();record(String(args[0]),`HTTP ${r.status}\n${text}`);}return r;}catch(e){record(String(args[0]),e instanceof Error?e.stack||e.message:String(e));throw e;}};
  const originalConsole=console.error;
  const observedConsole:typeof console.error=(...args)=>{record('Browser console',args.map(v=>v instanceof Error?v.stack||v.message:typeof v==='string'?v:(()=>{try{return JSON.stringify(v)}catch{return String(v)}})()).join(' '));originalConsole(...args);};
  console.error=observedConsole;window.fetch=observed;window.addEventListener('error',onError,true);window.addEventListener('unhandledrejection',onReject);
  return()=>{if(console.error===observedConsole)console.error=originalConsole;if(window.fetch===observed)window.fetch=original;window.removeEventListener('error',onError,true);window.removeEventListener('unhandledrejection',onReject);};
 },[]);
 const failures=jobs.filter(j=>j.status==='failed'||j.result?.error||j.result?.report?.infrastructureFailures||j.result?.report?.modelFailures).map(j=>({source:`${j.kind} · ${j.id} · ${j.status}`,text:JSON.stringify(j.result,null,2)}));
 const rows=[...errors.map(e=>({...e,source:`${e.source} · ${e.time} · ${e.count} occurrence(s)`})),...failures];
 return <details className="error-console"><summary>Errors & diagnostics ({rows.length})</summary><p>Browser/API errors from this session and errors from loaded jobs. Select a policy run for its complete structured failure and service logs. Repeated identical browser errors are counted.</p><DiagnosticDetails items={rows}/>{!rows.length&&<p>No captured errors.</p>}</details>;
}
