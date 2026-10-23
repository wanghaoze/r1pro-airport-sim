// Node 24 adapter for the same API routes used by the hosted Site.
import {DatabaseSync} from 'node:sqlite';
import {mkdirSync,readFileSync,existsSync,writeFileSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const data=resolve(process.env.STUDIO_DATA||'offline-data');mkdirSync(data,{recursive:true});
const sqlite=new DatabaseSync(join(data,'studio.sqlite'));sqlite.exec('PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;');
const schema=readFileSync(join(dirname(fileURLToPath(import.meta.url)),'schema.sql'),'utf8').replaceAll('CREATE TABLE ','CREATE TABLE IF NOT EXISTS ');sqlite.exec(schema);
function statement(sql:string,values:any[]=[]):any{return {bind:(...v:any[])=>statement(sql,v),first:async()=>sqlite.prepare(sql).get(...values)??null,all:async()=>({results:sqlite.prepare(sql).all(...values)}),run:async()=>({meta:{changes:Number(sqlite.prepare(sql).run(...values).changes)}})}}
const bucket=join(data,'artifacts');mkdirSync(bucket,{recursive:true});
function source(key:string){
  const local=resolve(bucket,key);if(!local.startsWith(bucket+'/')&&!local.startsWith(bucket+'\\'))throw Error('Invalid artifact path');
  if(existsSync(local))return local;
  const [job,hash,name]=key.split('/');const project=process.env.AIRPORT_PROJECT;
  if(!project)return local;
  const p=join(project,'runs/web_mse_figures_20261019_v1',job,name);
  if(existsSync(p)&&createHash('sha256').update(readFileSync(p)).digest('hex').startsWith(hash))return p;
  return local;
}
export const env:any={LOCAL_MODE:'1',GPU_WORKER_TOKEN:process.env.GPU_WORKER_TOKEN,OPENAI_API_KEY:process.env.OPENAI_API_KEY,
 DB:{prepare:statement},BUCKET:{
 head:async(key:string)=>{const p=source(key);return existsSync(p)?{customMetadata:{sha256:createHash('sha256').update(readFileSync(p)).digest('hex')}}:null;},
 get:async(key:string)=>{const p=source(key);return existsSync(p)?{body:readFileSync(p)}:null;},
 put:async(key:string,bytes:ArrayBuffer)=>{const p=resolve(bucket,key);if(!p.startsWith(bucket+'/')&&!p.startsWith(bucket+'\\'))throw Error('Invalid artifact path');mkdirSync(dirname(p),{recursive:true});writeFileSync(p,Buffer.from(bytes));}
 }};
