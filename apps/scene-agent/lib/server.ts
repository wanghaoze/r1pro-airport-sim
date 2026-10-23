import { env } from "cloudflare:workers";
import { ContractError } from "./core";
import initial from "./initial-snapshot.json";

export function database(){if(!env.DB)throw new ContractError("Database is unavailable",503);return env.DB;}
export function settings(){return env as unknown as {LOCAL_MODE?:string;GPU_WORKER_TOKEN?:string;GPU_OWNER_EMAIL?:string;OPENAI_API_KEY?:string;OPENAI_MODEL?:string};}
export function canOperateGpu(request:Request){if(settings().LOCAL_MODE==='1')return true;const expected=settings().GPU_OWNER_EMAIL;return Boolean(expected&&request.headers.get('oai-authenticated-user-id')&&request.headers.get('oai-authenticated-user-email')?.toLowerCase()===expected.toLowerCase());}
export function gpuOperator(request:Request){if(!canOperateGpu(request))throw new ContractError('Only the project owner can submit GPU jobs',403);}
export function user(request:Request){if(settings().LOCAL_MODE==='1')return "local-workstation";const id=request.headers.get("oai-authenticated-user-id");if(!id)throw new ContractError("Sign in with ChatGPT first",401);return id;}
export function sameOrigin(request:Request){const origin=request.headers.get("origin");if(origin&&origin!==new URL(request.url).origin)throw new ContractError("Cross-origin request rejected",403);}
export async function body(request:Request,maxLength=250000){const raw=await request.text();if(raw.length>maxLength)throw new ContractError("Request is too large",413);try{return JSON.parse(raw);}catch{throw new ContractError("Invalid JSON");}}
export function json(data:unknown,status=200){return Response.json(data,{status,headers:{"Cache-Control":"private, no-store"}});}
export function error(e:unknown){return json({error:e instanceof Error?e.message:"Request failed"},e instanceof ContractError?e.status:500);}
export async function workspace(id:string){
  const db=database();await db.prepare("INSERT OR IGNORE INTO scene_workspaces(user_id,revision,rooms,updated_at) VALUES(?,0,?,?)").bind(id,JSON.stringify(initial.rooms),Date.now()).run();
  const row=await db.prepare("SELECT * FROM scene_workspaces WHERE user_id=?").bind(id).first<any>();
  return {...row,rooms:JSON.parse(row.rooms)};
}
export async function gpuSnapshot(){
  const row=await database().prepare("SELECT value,updated_at FROM agent_state WHERE key='gpu'").first<any>();
  return row?{...JSON.parse(row.value),receivedAt:row.updated_at,live:Date.now()-row.updated_at<45000}:{...initial,live:false,receivedAt:null};
}
export async function saveWorkspace(id:string,expected:number,rooms:unknown,summary:string){
  const now=Date.now(),db=database();
  const result=await db.prepare("UPDATE scene_workspaces SET rooms=?,revision=revision+1,updated_at=? WHERE user_id=? AND revision=?").bind(JSON.stringify(rooms),now,id,expected).run();
  if(!result.meta.changes)throw new ContractError("Scene changed in another window. Refresh and retry.",409);
  const version=crypto.randomUUID();
  await db.prepare("INSERT INTO scene_versions(id,user_id,revision,rooms,summary,created_at) VALUES(?,?,?,?,?,?)").bind(version,id,expected+1,JSON.stringify(rooms),summary,now).run();
  return {version,revision:expected+1,rooms,updatedAt:now};
}
export function worker(request:Request){const configured=settings().GPU_WORKER_TOKEN;const supplied=request.headers.get("x-worker-token");if(!configured||!supplied||supplied.length!==configured.length)throw new ContractError("Worker authentication failed",403);let difference=0;for(let i=0;i<supplied.length;i++)difference|=supplied.charCodeAt(i)^configured.charCodeAt(i);if(difference)throw new ContractError("Worker authentication failed",403);}
