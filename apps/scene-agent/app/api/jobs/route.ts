import {assert,trainingPlan} from "@/lib/core";
import {body,database,error,gpuOperator,gpuSnapshot,json,sameOrigin,user,workspace} from "@/lib/server";
import {flexibleTrainingPlan,evaluationPlan,automaticEvaluationPlan} from '@/lib/training';
export async function POST(request:Request){try{
  sameOrigin(request);const id=user(request),data=await body(request),db=database();
  assert(typeof data.requestId==="string"&&/^[a-zA-Z0-9_-]{8,80}$/.test(data.requestId),"Invalid request ID");
  assert(["scene.sync","training.attach","training.plan","training.create","evaluation.mse","evaluation.vla","evaluation.live","evaluation.auto"].includes(data.kind),"Unsupported job type");
  if(data.kind!=='training.plan')gpuOperator(request);
  let payload,status="queued",result=null;
  if(data.kind==="scene.sync"){const scene=await workspace(id);assert(scene.revision===data.revision,"Save the current version first");payload={revision:scene.revision,rooms:scene.rooms,profile:"isaac32_fixed_base_pickplace"};}
  else if(data.kind==='training.create'||data.kind==='training.plan'){payload=flexibleTrainingPlan(data,await gpuSnapshot());if(data.kind==='training.plan'){status='planned';result=payload;}}
  else if(data.kind==='evaluation.auto'){
    payload=automaticEvaluationPlan();
    const existing=await db.prepare("SELECT * FROM agent_jobs WHERE user_id=? AND kind='evaluation.auto' ORDER BY created_at DESC LIMIT 1").bind(id).first<any>();
    if(existing)return json({...existing,payload:JSON.parse(existing.payload),result:existing.result?JSON.parse(existing.result):null});
  }
  else if(data.kind.startsWith('evaluation.'))payload=evaluationPlan(data,await gpuSnapshot());
  else {payload=trainingPlan(data.datasetIds,await gpuSnapshot());if(!payload.approvedRecipe){status=payload.status;result=payload;}}
  const prior=await db.prepare("SELECT * FROM agent_jobs WHERE id=? AND user_id=?").bind(data.requestId,id).first<any>();
  if(prior){assert(prior.kind===data.kind&&prior.payload===JSON.stringify(payload),"Request ID already used for different content");return json({...prior,result:prior.result?JSON.parse(prior.result):null});}
  const now=Date.now();await db.prepare("INSERT INTO agent_jobs(id,user_id,kind,payload,status,result,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)").bind(data.requestId,id,data.kind,JSON.stringify(payload),status,result?JSON.stringify(result):null,now,now).run();
  return json({id:data.requestId,status,kind:data.kind,payload,result});
}catch(e){return error(e);}}
