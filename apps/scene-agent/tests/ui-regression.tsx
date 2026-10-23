import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import {VlaResults} from '../app/AutoEvaluations';
import {resetRooms} from '../lib/reset';
import initial from '../lib/initial-snapshot.json';
import {evaluationPlan} from '../lib/training';
const failure={type:'ValueError',message:'policy_action_budget_exhausted',traceback:'retained on server'};
const html=renderToStaticMarkup(<VlaResults report={{passedPairs:0,modelFailures:1,infrastructureFailures:1,totalRooms:2,rooms:[{roomId:0,reason:failure},{roomId:1,reason:null}]}}/>);
assert.match(html,/ValueError: policy_action_budget_exhausted/);assert.match(html,/0 passed \/ 1 evaluable rooms/);
const altered=initial.rooms.map(r=>({...structuredClone(r),robot_base_pose:[1,2,3],tray_pose:[3,2,1,.5],robot_color:'#123456',tray_color:'#654321'}));
const one=resetRooms(altered,[3]);assert.deepEqual(one[3],initial.rooms[3]);assert.deepEqual(one[2],altered[2]);
assert.deepEqual(resetRooms(altered,altered.map(r=>r.id)),initial.rooms);assert.notDeepEqual(altered,initial.rooms);
const snapshot={checkpoints:[{id:'g05',closed:true,family:'g05'}]};
const req={kind:'evaluation.vla',checkpointIds:['g05'],sceneSetId:'isaac32_20261017',roomIds:[3],framesPerAction:20,transport:'ros2'};
assert.equal(evaluationPlan(req,snapshot).transport,'ros2');assert.throws(()=>evaluationPlan({...req,transport:'file'},snapshot));assert.throws(()=>evaluationPlan({...req,kind:'evaluation.mse',split:'test'},snapshot));
console.log('Passed: structured VLA failure renders; denominator retained; selected/all-room reset; external models require ROS2; MSE rejects incompatible family');

const protectedHtml=renderToStaticMarkup(<VlaResults report={{actionSafetyMode:'robot_limits',pureModelSuccessEligible:false,passedPairs:0,diagnosticPassedPairs:2,modelFailures:1,infrastructureFailures:1,evaluatedRooms:3,totalRooms:4,successRate:null}}/>);
assert.match(protectedHtml,/Excluded from pure model rate/);
assert.match(protectedHtml,/2 filtered task passes \/ 3 evaluable rooms/);
assert.doesNotMatch(protectedHtml,/0\.0%/);
console.log('Passed: filtered task passes never become a misleading pure-model success rate');

import CheckpointCatalog from '../app/CheckpointCatalog';
const catalogHtml=renderToStaticMarkup(<CheckpointCatalog gpu={{checkpoints:[{id:'pi05_test',label:'Test 10000',updates:10000,closed:true,family:'pi05',policyHorizon:20},{id:'g05_test',label:'G0.5',updates:0,closed:true,family:'g05',policyHorizon:1}],modelAdapters:[{id:'groot',label:'GR00T',configured:false}],live:false}} onRefresh={async()=>{}} onEvaluate={()=>{}}/>);
assert.match(catalogHtml,/2 registered checkpoints/);assert.match(catalogHtml,/10,000/);assert.match(catalogHtml,/Not reported/);assert.match(catalogHtml,/Last received snapshot/);assert.match(catalogHtml,/GR00T/);assert.match(catalogHtml,/not additional usable checkpoints/);
console.log('Passed: checkpoint cards distinguish saved steps, unknown steps and unconfigured adapters');
