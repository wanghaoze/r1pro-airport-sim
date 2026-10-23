import {canOperateGpu,database,error,gpuSnapshot,json,settings,user,workspace} from "@/lib/server";
export const dynamic="force-dynamic";
export async function GET(request:Request){try{
  const id=user(request);const [scene,gpu,jobs,versions]=await Promise.all([workspace(id),gpuSnapshot(),database().prepare("SELECT * FROM agent_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 30").bind(id).all<any>(),database().prepare("SELECT id,revision,summary,created_at FROM scene_versions WHERE user_id=? ORDER BY created_at DESC LIMIT 12").bind(id).all<any>()]);
  const localJobs=settings().LOCAL_MODE==='1'?(gpu.recentJobs||[]).filter((j:any)=>!jobs.results.some(x=>x.id===j.id)):[];
  return json({localMode:settings().LOCAL_MODE==='1',scene,gpu,canOperateGpu:canOperateGpu(request),jobs:[...localJobs,...jobs.results.map(j=>({...j,payload:JSON.parse(j.payload),result:j.result?JSON.parse(j.result):null}))].sort((a:any,b:any)=>b.created_at-a.created_at).slice(0,40),versions:versions.results,agentMode:settings().OPENAI_API_KEY?"gpt":"basic"});
}catch(e){return error(e);}}
