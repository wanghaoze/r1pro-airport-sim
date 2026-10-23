import test from 'node:test';
import assert from 'node:assert/strict';
import {flexibleTrainingPlan,evaluationPlan} from '../lib/training.ts';
import {executionSettings} from '../lib/execution-settings.ts';
const snapshot={datasets:[{id:'real_pickplace_v2'},{id:'isaac300_20261017'}],checkpoints:[{id:'saved',closed:true},{id:'writing',closed:false}]};
test('10000 second cap, disabled wall guard and selected GPUs survive every model contract',()=>{
 for(const family of ['pi05','g05','groot']){
  const state={...snapshot,gpuInventory:{devices:[{index:0},{index:1}]},checkpoints:[{id:'saved',closed:true,family}]};
  const input={kind:'evaluation.live',checkpointIds:['saved'],sceneSetId:'isaac32_20261017',roomIds:[0],transport:'ros2',maxSimulationSeconds:10000,maxWallSeconds:0,inferenceTimeoutSeconds:30,simulationGpu:1,inferenceGpu:0,filterSettings:{maxStepRad:.02,maxVelocityRadS:.4}};
  const plan=evaluationPlan(input,state);assert.equal(plan.framesPerAction,200000);assert.equal(plan.maxWallSeconds,0);assert.equal(plan.simulationGpu,1);assert.equal(plan.inferenceGpu,0);assert.deepEqual(plan.filterSettings,input.filterSettings);
  assert.throws(()=>evaluationPlan({...input,maxSimulationSeconds:10001},state));
  assert.throws(()=>evaluationPlan({...input,filterSettings:{maxStepRad:.2}},state));
  assert.throws(()=>evaluationPlan({...input,simulationGpu:2},state));
 }
});
test('one or two training GPUs accepted; duplicate and forged devices rejected',()=>{
 const state={gpuInventory:{devices:[{index:0},{index:1}]}};
 for(const ids of [[0],[1],[0,1]])assert.deepEqual(executionSettings({trainingGpuIds:ids},state,true),{trainingGpuIds:ids});
 for(const ids of [[0,0],[2],[],['1']])assert.throws(()=>executionSettings({trainingGpuIds:ids},state,true));
});
test('ratio endpoints omit unused domains and exact target is retained',()=>{
  const p=flexibleTrainingPlan({datasetIds:['real_pickplace_v2','isaac300_20261017'],realPercent:100,steps:500},snapshot);
  assert.deepEqual(p.datasets,['real_pickplace_v2']);assert.equal(p.steps,500);
  assert.throws(()=>flexibleTrainingPlan({datasetIds:['real_pickplace_v2'],realPercent:1,steps:500},snapshot));
  assert.throws(()=>flexibleTrainingPlan({datasetIds:['real_pickplace_v2'],realPercent:101,steps:500},snapshot));
});
test('MSE rejects train and unclosed checkpoints',()=>{
  assert.throws(()=>evaluationPlan({kind:'evaluation.mse',checkpointIds:['writing'],split:'test'},snapshot));
  assert.throws(()=>evaluationPlan({kind:'evaluation.mse',checkpointIds:['saved'],split:'train'},snapshot));
  assert.equal(evaluationPlan({kind:'evaluation.mse',checkpointIds:['saved'],split:'val'},snapshot).stride,1);
});
test('VLA preserves train-scene diagnostic and explicit base actuator mask',()=>{
  const p=evaluationPlan({kind:'evaluation.vla',checkpointIds:['saved'],sceneSetId:'isaac32_20261017',roomIds:[0,31],framesPerAction:200},snapshot);
  assert.equal(p.teacherFallback,false);assert.equal(p.heldOutGeneralization,false);
  assert.throws(()=>evaluationPlan({kind:'evaluation.vla',checkpointIds:['saved'],sceneSetId:'isaac32_20261017',roomIds:[0,0],framesPerAction:200},snapshot));
});

test('all execution requests force robot filter including legacy strict requests',()=>{
  for(const actionSafetyMode of [undefined,'strict','clip_diagnostic','robot_limits']){
    const data={kind:'evaluation.vla',checkpointIds:['saved'],sceneSetId:'isaac32_20261017',roomIds:[0],framesPerAction:200,actionSafetyMode};
    assert.equal(evaluationPlan(data,snapshot).actionSafetyMode,'robot_limits');
    assert.equal(evaluationPlan({...data,kind:'evaluation.live',transport:'ros2',maxSimulationSeconds:1,maxWallSeconds:300,inferenceTimeoutSeconds:60},snapshot).actionSafetyMode,'robot_limits');
  }
  assert.equal(evaluationPlan({kind:'evaluation.mse',checkpointIds:['saved'],split:'test'},snapshot).actionSafetyMode,undefined);
});
