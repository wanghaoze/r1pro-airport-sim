// Public metadata only. Never spread the workstation snapshot into this response.
export function checkpointCatalog(snapshot:any, now=Date.now()) {
 const checkpoints=(Array.isArray(snapshot?.checkpoints)?snapshot.checkpoints:[])
  .filter((c:any)=>typeof c.id==='string'&&c.closed===true)
  .map((c:any)=>({id:c.id,label:String(c.label||c.id),family:String(c.family||'pi05'),
   updates:Number.isSafeInteger(c.updates)&&c.updates>=0?c.updates:0,closed:true,
   source:String(c.source||'unknown'),policyHorizon:Number.isInteger(c.policyHorizon)?c.policyHorizon:20,
   status:c.source==='external_model_endpoint'?'Endpoint registered; runtime validation required':'Saved checkpoint; task success not implied'}));
 const modelAdapters=(Array.isArray(snapshot?.modelAdapters)?snapshot.modelAdapters:[])
  .map((m:any)=>({id:String(m.id),family:String(m.family),label:String(m.label),configured:m.configured===true,
   status:m.configured===true?'Endpoint registered; runtime validation required':'Compatible checkpoint configuration required'}));
 const receivedAt=typeof snapshot?.receivedAt==='number'?snapshot.receivedAt:null;
 const gpuInventory={devices:(Array.isArray(snapshot?.gpuInventory?.devices)?snapshot.gpuInventory.devices:[]).filter((d:any)=>Number.isInteger(d.index)).map((d:any)=>({index:d.index,name:String(d.name||'GPU'),totalMiB:Number(d.totalMiB),freeMiB:Number(d.freeMiB)})),sampledAt:snapshot?.gpuInventory?.sampledAt??null,error:snapshot?.gpuInventory?.error?'GPU inventory unavailable':null};
 const filterLimits=Object.fromEntries(['maxStepRad','maxVelocityRadS','maxTrackingErrorRad','maxObservationAgeSeconds'].filter(k=>Number.isFinite(snapshot?.filterLimits?.[k])).map(k=>[k,snapshot.filterLimits[k]]));
 return {checkpoints,modelAdapters,gpuInventory,filterLimits,capturedAt:typeof snapshot?.capturedAt==='number'?snapshot.capturedAt:null,
  receivedAt,live:receivedAt!==null&&now>=receivedAt&&now-receivedAt<45000,
  storage:'workstation',actionSafetyMode:'robot_limits'};
}
