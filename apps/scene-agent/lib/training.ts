import {executionSettings} from './execution-settings.ts';
import {assert,validateSelection} from './core.ts';

export function flexibleTrainingPlan(data:any,snapshot:any){
  assert(data.autoEvaluate===undefined||typeof data.autoEvaluate==='boolean','Automatic evaluation must be enabled or disabled');
  const datasets=validateSelection(data.datasetIds);
  const realPercent=data.realPercent;
  assert(Number.isInteger(realPercent)&&realPercent>=0&&realPercent<=100,'Real percentage must be an integer from 0 to 100');
  const steps=data.steps;
  assert(Number.isInteger(steps)&&steps>=1&&steps<=100000,'Training steps must be an integer from 1 to 100000');
  assert(realPercent===0||datasets.includes('real_pickplace_v2'),'Select real data when its percentage is above 0');
  assert(realPercent===100||datasets.some(id=>id!=='real_pickplace_v2'),'Select simulation data when its percentage is above 0');
  const activeDatasets=datasets.filter(id=>id==='real_pickplace_v2'?realPercent>0:realPercent<100);
  const registered=snapshot?.datasets||[];
  assert(activeDatasets.every(id=>registered.some((d:any)=>d.id===id)),'Dataset registry is not ready');
  return {...executionSettings(data,snapshot,true),schema:'studio_training/1',scope:'fixed_base_pickplace_only',datasets:activeDatasets,
    realPercent,simulationPercent:100-realPercent,steps,warmupSteps:Math.min(500,Math.floor(steps/20)),batchSize:8,seed:42,method:'duration_weighted_sampling_BC_LoRA',
    initialization:'registered_parent_weights_new_optimizer',validationDomain:'fixed_real_val_test',
    simulationHoldout:false,rewardEnabled:false,status:'planned',trainingStarted:false,autoEvaluate:data.autoEvaluate!==false,
    message:'Independent run directory. Original Train/Val/Test are preserved. Source validation and training start when the GPU is available.'};
}

export function automaticEvaluationPlan(){
  return {schema:'studio_auto_evaluation/1',trainingRun:'current',checkpointSelection:'latest_final',sceneSetId:'isaac32_20261017',
    roomIds:Array.from({length:32},(_,i)=>i),framesPerAction:200,split:'test',baseline:'real_only_10000',teacherFallback:false};
}

export function evaluationPlan(data:any,snapshot:any):any{
  const ids=data.checkpointIds;
  assert(Array.isArray(ids)&&ids.length>0&&ids.length<=(data.kind==='evaluation.mse'?4:1)&&new Set(ids).size===ids.length,'Select 1–4 MSE checkpoints or one VLA checkpoint');
  assert(ids.every(id=>typeof id==='string'&&snapshot?.checkpoints?.some((c:any)=>c.id===id&&c.closed===true)),'Checkpoint is unregistered or not fully saved');
  if(data.kind==='evaluation.mse'){
    assert(ids.every(id=>!snapshot.checkpoints.find((c:any)=>c.id===id)?.family||snapshot.checkpoints.find((c:any)=>c.id===id)?.family==='pi05'),'MSE protocol currently supports registered pi0.5 checkpoints');
    assert(['val','test'].includes(data.split),'MSE uses fixed real Val/Test only');
    return {...executionSettings(data,snapshot),schema:'studio_mse/1',checkpointIds:ids,split:data.split,protocol:'real_all_frames_h20_noise42000_v1',
      horizon:20,stride:1,baseChannelsExcluded:true,units:{arms:'rad²',grippers:'mm²'},robotExecution:false};
  }
  assert(data.sceneSetId==='isaac32_20261017','Scene set is not registered');
  assert(Array.isArray(data.roomIds)&&data.roomIds.length>0&&data.roomIds.length<=32&&new Set(data.roomIds).size===data.roomIds.length&&data.roomIds.every((n:any)=>Number.isInteger(n)&&n>=0&&n<32),'Invalid room selection');
  const live=data.kind==='evaluation.live';
  if(live) assert(Number.isInteger(data.maxSimulationSeconds)&&data.maxSimulationSeconds>=1&&data.maxSimulationSeconds<=10000,'Maximum simulation duration must be a whole number from 1 to 10000 seconds');
  // Live duration owns the execution budget; model horizon is a separate contract.
  const framesPerAction=live?data.maxSimulationSeconds*20:data.framesPerAction;
  assert(Number.isInteger(framesPerAction)&&framesPerAction>=20&&framesPerAction<=(live?200000:1200),'VLA action frame budget must be a whole number from 20 to 1200');
  const transport=data.transport||'file';
  assert(['file','ros2'].includes(transport),'Select file or ROS 2 transport');
  assert(transport==='ros2'||ids.every(id=>!snapshot.checkpoints.find((c:any)=>c.id===id)?.family||snapshot.checkpoints.find((c:any)=>c.id===id)?.family==='pi05'),'External models require ROS 2 transport');
  const selectedModel=snapshot.checkpoints.find((c:any)=>c.id===ids[0]);
  if(data.kind==='evaluation.live'){
    assert(['baseline','realtime'].includes(data.runtimeProfile??'baseline'),'Invalid runtime profile');
    assert(['strict','clip_diagnostic','robot_limits'].includes(data.actionSafetyMode??'strict'),'Invalid action safety mode');
    assert(Number.isInteger(data.maxSimulationSeconds)&&data.maxSimulationSeconds>=1&&data.maxSimulationSeconds<=10000,'Simulation duration must be 1–10000 seconds');
    assert(data.roomIds.length===1,'Live evaluation uses one room per run');
    assert(Number.isInteger(data.maxWallSeconds)&&data.maxWallSeconds>=0&&data.maxWallSeconds<=604800,'Run wall time must be 0–604800 seconds (0 disables the overall wall guard)');
    assert(Number.isInteger(data.inferenceTimeoutSeconds)&&data.inferenceTimeoutSeconds>=1&&data.inferenceTimeoutSeconds<=300,'Inference timeout must be 1–300 seconds');
    assert(transport==='ros2','Live evaluation requires ROS 2');
  }
  const policyHorizon=selectedModel.policyHorizon||(selectedModel.family==='g05'?1:20);
  return {...executionSettings(data,snapshot),schema:'studio_vla/1',actionSafetyMode:'robot_limits',transport,checkpointIds:ids,sceneSetId:data.sceneSetId,roomIds:data.roomIds,framesPerAction,
    ...(data.kind==='evaluation.live'?{liveEvaluation:true,runtimeProfile:data.runtimeProfile??'baseline',realtimePacing:true,maxSimulationSeconds:data.maxSimulationSeconds,maxWallSeconds:data.maxWallSeconds,inferenceTimeoutSeconds:data.inferenceTimeoutSeconds}:{}),
    fps:20,executionHorizon:Math.min(5,policyHorizon),policyHorizon,baseActuatorMask:'fixed_episode_base',teacherFallback:false,
    scope:'training_scene_native_closed_loop_diagnostic',heldOutGeneralization:false,trainingEligible:false};
}
