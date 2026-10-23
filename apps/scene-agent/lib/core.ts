export type Room = {id:number;name:string;robot_base_pose:number[];tray_pose:number[];robot_color:string;tray_color:string;parent_scene_id:string;split:string;seed:number};
export type Changes = Partial<Pick<Room,"robot_base_pose"|"tray_pose"|"robot_color"|"tray_color">>;
export type Edit = {room:number;changes:Changes};
// sRGB swatches corresponding to the source materials' linear base colors.
export const DEFAULT_COLORS = {robot:"#CDD0D3",tray:"#A15E6D"} as const;
export const DATASET_IDS = ["isaac300_20261017", "real_pickplace_v2", "isaac32_narrow_20261016", "isaac32_wide_20261016"];
export class ContractError extends Error { status:number; constructor(message:string,status=400){super(message);this.status=status;} }
export function assert(condition:unknown, message:string):asserts condition {if(!condition)throw new ContractError(message);}
export function validateEdits(value:unknown):Edit[]{
  assert(Array.isArray(value)&&value.length>0&&value.length<=32,"Select 1–32 rooms");
  const ids=new Set<number>();
  for(const edit of value){
    assert(edit&&typeof edit==="object"&&Object.keys(edit).every(k=>["room","changes"].includes(k)),"Unknown edit field");
    assert(Number.isInteger(edit.room)&&edit.room>=0&&edit.room<32&&!ids.has(edit.room),"Invalid or duplicate room ID");ids.add(edit.room);
    const changes=edit.changes;
    assert(changes&&typeof changes==="object"&&!Array.isArray(changes)&&Object.keys(changes).length>0,"Edits cannot be empty");
    for(const [key,value] of Object.entries(changes)){
      assert(["robot_base_pose","tray_pose","robot_color","tray_color"].includes(key),"This scene field is not editable");
      if(key.endsWith("_color"))assert(typeof value==="string"&&/^#[0-9a-fA-F]{6}$/.test(value),"Use an opaque #RRGGBB color");
      else assert(Array.isArray(value)&&value.length===(key==="tray_pose"?4:3)&&value.every(n=>typeof n==="number"&&Number.isFinite(n)),"Pose values must be finite, in meters/radians");
    }
  }
  return value;
}
export function applyEdits(rooms:Room[], edits:Edit[]):Room[]{
  validateEdits(edits);
  return rooms.map(room=>{const edit=edits.find(e=>e.room===room.id);return edit?{...room,...structuredClone(edit.changes)}:{...room};});
}
export function validateSelection(ids:unknown):string[]{
  assert(Array.isArray(ids)&&ids.length>0&&ids.every(id=>typeof id==="string"&&DATASET_IDS.includes(id))&&new Set(ids).size===ids.length,"Select registered datasets");
  return ids;
}
export function trainingPlan(ids:unknown,snapshot:any){
  const selected=validateSelection(ids);
  const approved=selected.length===2&&selected.includes("isaac300_20261017")&&selected.includes("real_pickplace_v2");
  const count=Number(snapshot?.production?.qualified_pairs||0);
  return {recipe:approved?"real50_isaac300_duration_bc":"custom_selection",scope:"fixed_base_pickplace_only",
    datasets:selected,method:"duration_weighted_sampling_BC",steps:10000,batchSize:8,
    ready:approved&&count>=300,approvedRecipe:approved,
    status:approved?(count>=300?"ready_for_server_revalidation":"waiting_for_data"):"blocked",
    reasons:approved?(count>=300?["GPU will verify frozen manifests and existing processes before starting"]:[`New complete sources: ${count}/300; the existing supervisor is waiting for data`]):["This legacy attachment uses new 300 pairs + real 50/50", "The historical 59 pairs are Train only; they do not replace new sources or a simulation holdout"],
    validationDomain:"Fixed real Val/Test; simulation Train only",trainingStarted:false};
}

const COLORS:Record<string,string>={"蓝":"#3B82F6","白":"#E2E8F0","红":"#EF4444","绿":"#34D399","黄":"#FBBF24","橙":"#FB923C","紫":"#A78BFA","黑":"#27272A","灰":"#94A3B8",blue:"#3B82F6",white:"#E2E8F0",red:"#EF4444",green:"#34D399",yellow:"#FBBF24",black:"#27272A"};
function color(text:string){const hex=text.match(/#[a-f0-9]{6}\b/i);if(hex)return hex[0];return Object.entries(COLORS).find(([word])=>text.toLowerCase().includes(word))?.[1];}
export function parseBasicIntent(text:string, rooms:Room[], selected:number[], snapshot:any):{reply:string;edits:Edit[];mode:string}{
  assert(typeof text==="string"&&text.trim().length>0&&text.length<=2000,"Enter an instruction up to 2,000 characters");
  const matched=[...text.matchAll(/(?:room[_\s]*|房间\s*)(\d{1,2})/gi)].map(m=>Number(m[1]));
  const targets=/全部|所有|all rooms/i.test(text)?rooms.map(r=>r.id):(matched.length?[...new Set(matched)]:selected);
  assert(targets.length>0&&targets.every(id=>Number.isInteger(id)&&id>=0&&id<32),"Select a room (0–31)");
  if(/恢复(?:场景|实验室|默认)?(?:的)?原色|恢复原始配色|restore.*(?:original|default).*(?:colors|materials)/i.test(text)&&!/机器人|robot|托盘|tray/i.test(text))return {reply:"Restored original materials: black and silver robot, burgundy tray and original markings.",edits:targets.map(room=>({room,changes:{robot_color:DEFAULT_COLORS.robot,tray_color:DEFAULT_COLORS.tray}})),mode:"basic"};
  if(/训练|数据|进度|多少|training|progress|dataset/i.test(text)&&!/颜色|改成|位姿|移动|color|move|rotate/i.test(text))return {reply:`Training: ${snapshot?.training?.actual_completed_updates??0} / ${snapshot?.training?.target_updates??10000} actual updates. Stage: ${snapshot?.training?.stage||"disconnected"}. Open Data & training for recipes, evaluations and measured results.`,edits:[],mode:"basic"};
  const edits:Edit[]=[];
  for(const id of targets){
    const room=rooms.find(r=>r.id===id)!;const changes:Changes={};
    const clauses=text.split(/[，,。；;\n]/);
    for(const clause of clauses){
      const isTray=/托盘|tray/i.test(clause),isRobot=/机器人|robot|底盘/i.test(clause);
      if(!isTray&&!isRobot)continue;
      const shade=/恢复.*(?:原色|原始配色)|restore.*(?:original|default)/i.test(clause)?DEFAULT_COLORS[isTray?"tray":"robot"]:color(clause);if(shade)changes[isTray?"tray_color":"robot_color"]=shade;
      const key=isTray?"tray_pose":"robot_base_pose";const pose=(changes[key]||room[key]).slice();let moved=false;
      const yaw=clause.match(/(?:旋转|转动|朝向(?:设为|改为)?|rotate(?:\s+(?:the\s+)?(?:robot|tray))?|yaw(?:\s+(?:to|=))?)\s*([+-]?[\d.]+)\s*(度|°|degrees?|deg|rad|弧度)/i);
      if(yaw){const v=Number(yaw[1])*(/度|°|deg/i.test(yaw[2])?Math.PI/180:1);pose[isTray?3:2]=/朝向|yaw/i.test(clause)?v:pose[isTray?3:2]+v;moved=true;}
      const shift=clause.match(/(?:向|往)(左|右|前|后)\s*(?:移动|移)?\s*([\d.]+)\s*(厘米|cm|毫米|mm|米|m)/i)||clause.match(/\b(left|right|forward|backward|back)\s*(?:by\s*)?([\d.]+)\s*(cm|mm|meters?|metres?|m)\b/i);
      if(shift){const d=Number(shift[2])*(/厘米|cm/i.test(shift[3])?.01:/毫米|mm/i.test(shift[3])?.001:1);const angle=room.robot_base_pose[2];const dir=shift[1];const sign=/右|后|right|back/i.test(dir)?-1:1;const sideways=/左|右|left|right/i.test(dir);pose[0]+=sign*d*(sideways?-Math.sin(angle):Math.cos(angle));pose[1]+=sign*d*(sideways?Math.cos(angle):Math.sin(angle));moved=true;}
      for(const axis of clause.matchAll(/\b(x|y|z)\s*(?:=|设为|改为|到)\s*([+-]?[\d.]+)/gi)){const index="xyz".indexOf(axis[1].toLowerCase());if(index===2&&!isTray)continue;pose[index]=Number(axis[2]);moved=true;}
      if(moved)changes[key]=pose;
    }
    if(Object.keys(changes).length)edits.push({room:id,changes});
  }
  if(!edits.length)return {reply:"Basic command mode. Try “Make the tray blue”, “Move the robot left 10 cm” or “Rotate the robot 15 degrees”. GPT API is required for broader conversation.",edits:[],mode:"basic"};
  validateEdits(edits);
  return {reply:`Updated the draft preview for ${targets.length===1?`room_${String(targets[0]).padStart(3,"0")}`:`${targets.length} rooms`}. Physical state is unchanged. Save a version to sync the draft to the GPU workspace.`,edits,mode:"basic"};
}
