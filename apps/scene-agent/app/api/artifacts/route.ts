import {env} from 'cloudflare:workers';
import {assert} from '@/lib/core';
import {error,gpuOperator,json,worker} from '@/lib/server';

const types:Record<string,string>={png:'image/png',csv:'text/csv; charset=utf-8',json:'application/json',zip:'application/zip',mp4:'video/mp4'};
function artifact(request:Request){
  const key=new URL(request.url).searchParams.get('key')||'';
  assert(/^[A-Za-z0-9_-]{8,80}\/[a-f0-9]{16}\/[a-z0-9_]+\.(png|csv|json|zip|mp4)$/.test(key),'Invalid artifact key');
  assert(Boolean(env.BUCKET),'Artifact storage is unavailable');
  return {key,bucket:env.BUCKET!,name:key.split('/').at(-1)!,type:types[key.split('.').at(-1)!]};
}
export async function PUT(request:Request){try{
  worker(request);const {key,bucket,type}=artifact(request),digest=request.headers.get('x-artifact-sha256')||'';
  assert(/^[a-f0-9]{64}$/.test(digest)&&key.split('/')[1]===digest.slice(0,16),'Invalid artifact digest');
  const declared=Number(request.headers.get('content-length'));
  assert(declared>0&&declared<=32*1024*1024,'Artifact size is invalid');
  const bytes=await request.arrayBuffer();assert(bytes.byteLength===declared,'Artifact length mismatch');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
  assert(hash===digest,'Artifact checksum mismatch');
  const previous=await bucket.head(key);
  if(previous){assert(previous.customMetadata?.sha256===digest,'Immutable artifact conflict');return json({ok:true});}
  await bucket.put(key,bytes,{httpMetadata:{contentType:type},customMetadata:{sha256:digest}});
  return json({ok:true});
}catch(e){return error(e);}}
export async function GET(request:Request){try{
  gpuOperator(request);const {key,bucket,name,type}=artifact(request),object=await bucket.get(key);
  if(!object)return json({error:'Artifact not found'},404);
  const download=new URL(request.url).searchParams.get('download')==='1'||!name.endsWith('.png');
  return new Response(object.body,{headers:{'Content-Type':type,'Content-Disposition':`${download?'attachment':'inline'}; filename="${name}"`,'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'}});
}catch(e){return error(e);}}
