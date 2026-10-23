import {assert} from '@/lib/core';
import {body,database,error,gpuOperator,json,worker,user,sameOrigin} from '@/lib/server';
const valid=(id:unknown)=>typeof id==='string'&&/^[A-Za-z0-9_-]{8,80}$/.test(id);
export async function PUT(request:Request){try{
  worker(request);const data=await body(request,4*1024*1024);assert(valid(data.jobId),'Invalid live job ID');
  assert(data.simulationOnly===true&&Number.isFinite(data.sampledAt),'Invalid live snapshot');
  await database().prepare('INSERT INTO agent_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at').bind('live:'+data.jobId,JSON.stringify(data),Date.now()).run();
  return json({ok:true});
}catch(e){return error(e);}}
export async function GET(request:Request){try{
  gpuOperator(request);const id=new URL(request.url).searchParams.get('jobId');assert(valid(id),'Select a live evaluation');
  const row=await database().prepare('SELECT value,updated_at FROM agent_state WHERE key=?').bind('live:'+id).first<any>();
  return json(row?{...JSON.parse(row.value),receivedAt:row.updated_at}:{jobId:id,stage:'awaiting_worker',frame:null,downloads:[]});
}catch(e){return error(e);}}

export async function POST(request:Request){try{
 sameOrigin(request);gpuOperator(request);const owner=user(request),data=await body(request);assert(valid(data.jobId),'Select a policy run to stop');
 const db=database(),job=await db.prepare('SELECT * FROM agent_jobs WHERE id=? AND user_id=?').bind(data.jobId,owner).first<any>();
 assert(job&&['evaluation.live','evaluation.vla'].includes(job.kind),'Policy job not found in this workspace');
 if(['completed','failed','cancelled'].includes(job.status))return json({jobId:job.id,status:job.status,stopRequested:false});
 await db.prepare('INSERT INTO agent_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at').bind('cancel:'+job.id,JSON.stringify({jobId:job.id,requestedAt:Date.now()}),Date.now()).run();
 await db.prepare("UPDATE agent_jobs SET status='cancelled',result=?,updated_at=? WHERE id=? AND user_id=? AND status='queued'").bind(JSON.stringify({message:'Stopped by user before claim'}),Date.now(),job.id,owner).run();
 return json({jobId:job.id,status:'stop_requested',stopRequested:true});
}catch(e){return error(e);}}
