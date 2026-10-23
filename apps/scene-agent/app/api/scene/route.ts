import {applyEdits,assert} from "@/lib/core";
import {body,database,error,json,sameOrigin,saveWorkspace,user,workspace} from "@/lib/server";
export async function POST(request:Request){try{
  sameOrigin(request);const id=user(request),data=await body(request),old=await workspace(id);
  assert(Number.isInteger(data.revision)&&data.revision===old.revision,"Scene version changed. Refresh first.");
  let rooms,summary;
  if(data.restoreVersion){const version=await database().prepare("SELECT rooms,revision FROM scene_versions WHERE id=? AND user_id=?").bind(data.restoreVersion,id).first<any>();assert(version,"Version not found for this user");rooms=JSON.parse(version.rooms);summary=`Restore version v${version.revision}`;}
  else {rooms=applyEdits(old.rooms,data.edits);summary=typeof data.summary==="string"?data.summary.slice(0,200):"Edit scene";}
  return json(await saveWorkspace(id,old.revision,rooms,summary));
}catch(e){return error(e);}}
