import {createServer} from 'node:http';
import {readFileSync,statSync} from 'node:fs';
import {dirname,resolve,extname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import * as bootstrap from '../app/api/bootstrap/route';
import * as checkpoints from '../app/api/checkpoints/route';
import * as scene from '../app/api/scene/route';
import * as chat from '../app/api/chat/route';
import * as jobs from '../app/api/jobs/route';
import * as worker from '../app/api/worker/route';
import * as artifacts from '../app/api/artifacts/route';
import * as live from '../app/api/live/route';
import * as models from './models';
const routes:Record<string,any>={bootstrap,checkpoints,scene,chat,jobs,worker,artifacts,models,live};
const root=resolve(dirname(fileURLToPath(import.meta.url)),'public');
const host=process.env.STUDIO_HOST||'127.0.0.1',port=Number(process.env.STUDIO_PORT||9080);
const mime:Record<string,string>={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.glb':'model/gltf-binary','.mp4':'video/mp4','.zip':'application/zip','.png':'image/png','.md':'text/markdown; charset=utf-8'};
const server=createServer(async(req,res)=>{try{
 const url=new URL(req.url||'/',`http://${req.headers.host||host+':'+port}`);
 if(url.pathname==='/api/health'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({ok:true,mode:'offline',authentication:'disabled',pid:process.pid}));return;}
 if(url.pathname.startsWith('/api/')){
  const fn=routes[url.pathname.slice(5)]?.[req.method||'GET'];if(!fn){res.writeHead(404);res.end('Unknown API');return;}
  const chunks:Buffer[]=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>33*1024*1024){res.writeHead(413);res.end();return;}chunks.push(chunk);}
  const headers=new Headers();for(const [k,v] of Object.entries(req.headers))if(v)headers.set(k,Array.isArray(v)?v.join(','):v);
  const request=new Request(url,{method:req.method,headers,...(!['GET','HEAD'].includes(req.method||'GET')?{body:Buffer.concat(chunks)}:{})});
  const response:Response=await fn(request);res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));return;
 }
 let path=resolve(root,'.'+decodeURIComponent(url.pathname));if(path!==root&&!path.startsWith(root+sep)){res.writeHead(403);res.end();return;}
 if(url.pathname==='/'||!extname(path))path=resolve(root,'index.html');
 if(!statSync(path).isFile())throw Error('Not found');res.setHeader('Content-Type',mime[extname(path)]||'application/octet-stream');res.end(readFileSync(path));
 }catch(e){res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({error:e instanceof Error?e.message:String(e)}));}});
server.listen(port,host,()=>console.log(`Offline Scene Studio http://${host}:${port} — no sign-in required`));
for(const signal of ['SIGINT','SIGTERM'] as const)process.on(signal,()=>server.close(()=>process.exit(0)));
