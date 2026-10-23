import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {sameOrigin,body,error,json} from '../lib/server';
export async function POST(request:Request){try{
 sameOrigin(request);const data=await body(request);
 const script=resolve(dirname(fileURLToPath(import.meta.url)),'../scripts/studio_configure_model.py');
 const output=await new Promise<string>((accept,reject)=>{const p=execFile(process.env.STUDIO_PYTHON||'/home/michelle/miniconda3/envs/r1pro-tray/bin/python',[script],{timeout:30000},(err,stdout,stderr)=>{if(err){try{reject(new Error(JSON.parse(stdout).error));}catch{reject(new Error('Model registration failed. Check path and metadata.'));}}else accept(stdout);});p.stdin!.end(JSON.stringify(data));});
 return json(JSON.parse(output));
 }catch(e){return error(e);}}
