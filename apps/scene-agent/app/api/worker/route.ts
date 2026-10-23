import {assert} from "@/lib/core";
import {body,database,error,json,worker} from "@/lib/server";
export async function POST(request:Request){try{
  worker(request);const data=await body(request,4*1024*1024),db=database(),now=Date.now();
  assert(data.workerId==="xinmatrix-scene-agent-v1","Unregistered worker identity");
  if(data.snapshot){await db.prepare("INSERT INTO agent_state(key,value,updated_at) VALUES('gpu',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at").bind(JSON.stringify(data.snapshot),now).run();}
  if(data.ack){assert(typeof data.ack.id==="string"&&["draft_synced","attached_existing","waiting_training","waiting_gpu","blocked","failed","cancelled"].includes(data.ack.status),"Invalid receipt");await db.prepare("UPDATE agent_jobs SET status=?,result=?,updated_at=? WHERE id=? AND worker_id=? AND status='claimed'").bind(data.ack.status,JSON.stringify(data.ack.result),now,data.ack.id,data.workerId).run();}
  if(data.updates){assert(Array.isArray(data.updates)&&data.updates.length<=50,'Invalid receipt count');for(const update of data.updates){assert(typeof update.id==='string'&&['waiting_training','waiting_gpu','preparing','running','completed','failed','cancelled','blocked'].includes(update.status),'Invalid progress receipt');await db.prepare("UPDATE agent_jobs SET status=?,result=?,updated_at=? WHERE id=? AND worker_id=? AND status IN ('waiting_training','waiting_gpu','preparing','running')").bind(update.status,JSON.stringify(update.result),now,update.id,data.workerId).run();}}
  const cancelled=await db.prepare("SELECT j.id FROM agent_jobs j JOIN agent_state s ON s.key='cancel:'||j.id WHERE j.worker_id=? AND j.status NOT IN ('completed','failed','cancelled')").bind(data.workerId).all<any>();
  const cancellations=cancelled.results.map((j:any)=>j.id);
  if(data.claim===true){
    const owned=await db.prepare("SELECT * FROM agent_jobs WHERE status='claimed' AND worker_id=? ORDER BY claimed_at LIMIT 1").bind(data.workerId).first<any>();
    if(owned)return json({cancellations,job:{id:owned.id,kind:owned.kind,payload:JSON.parse(owned.payload)}});
    const pending=await db.prepare("SELECT * FROM agent_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").first<any>();
    if(pending){const claimed=await db.prepare("UPDATE agent_jobs SET status='claimed',worker_id=?,claimed_at=?,updated_at=? WHERE id=? AND status='queued'").bind(data.workerId,now,now,pending.id).run();if(claimed.meta.changes)return json({cancellations,job:{id:pending.id,kind:pending.kind,payload:JSON.parse(pending.payload)}});}
  }
  return json({ok:true,job:null,cancellations});
}catch(e){return error(e);}}
