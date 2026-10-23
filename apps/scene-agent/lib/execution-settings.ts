import {assert} from './core.ts';
export const MAX_SIMULATION_SECONDS=10000;
export const DEFAULT_FILTER={maxStepRad:.1,maxVelocityRadS:1.5,maxTrackingErrorRad:.25,maxObservationAgeSeconds:.5};
export function executionSettings(data:any,snapshot:any,training=false){
 const devices=snapshot?.gpuInventory?.devices||[];
 const valid=(id:any)=>Number.isInteger(id)&&devices.some((d:any)=>d.index===id);
 const limits={...DEFAULT_FILTER,...snapshot?.filterLimits};
 const requested=data.filterSettings??{};
 assert(requested&&typeof requested==='object'&&!Array.isArray(requested),'Invalid filter settings');
 const filterSettings:any={};
 for(const key of Object.keys(requested)){
  assert(key in DEFAULT_FILTER,'Unknown filter setting');
  const v=requested[key];assert(typeof v==='number'&&Number.isFinite(v)&&v>0&&v<=Math.min(limits[key],DEFAULT_FILTER[key as keyof typeof DEFAULT_FILTER]),`Filter ${key} must be positive and within the robot limit`);filterSettings[key]=v;
 }
 if(training){const ids=data.trainingGpuIds;
  if(ids===undefined)return {};
  assert(Array.isArray(ids)&&ids.length>0&&ids.length<=8&&8%ids.length===0&&new Set(ids).size===ids.length&&ids.every(valid),'Select available training GPUs; GPU count must divide batch size 8');
  return {trainingGpuIds:ids};
 }
 const selected:any={filterSettings};
 for(const key of ['simulationGpu','inferenceGpu'])if(data[key]!==undefined){assert(valid(data[key]),'Selected GPU is not available in the workstation inventory');selected[key]=data[key];}
 return selected;
}
