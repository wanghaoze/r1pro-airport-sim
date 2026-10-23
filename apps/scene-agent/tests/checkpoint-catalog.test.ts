import test from 'node:test';
import assert from 'node:assert/strict';
import {checkpointCatalog} from '../lib/checkpoint-catalog.ts';
test('public catalog strips private paths, weights, jobs and model configuration',()=>{
 const raw={receivedAt:1000,capturedAt:900,rooms:[{private:true}],recentJobs:[{private:true}],secret:'never',checkpoints:[{id:'cp_a',label:'Saved model',updates:10000,closed:true,checkpoint:'/private/weights',spec:{secret:'never'},receipt:'/private/receipt'},{id:'unfinished',closed:false}],modelAdapters:[{id:'model',label:'Adapter',family:'g05',configured:true,modelConfig:{secret:'never'},status:'private /path'}]};
 const output=checkpointCatalog(raw,1001);assert.equal(output.checkpoints.length,1);assert.equal(output.checkpoints[0].family,'pi05');assert.equal(output.live,true);
 for(const word of ['never','/private','/path','recentJobs','modelConfig','receipt','unfinished'])assert.ok(!JSON.stringify(output).includes(word));
 assert.equal(output.actionSafetyMode,'robot_limits');
});
test('stale and absent snapshots are explicit, not live or fabricated checkpoints',()=>{
 assert.equal(checkpointCatalog({receivedAt:1000},46000).live,false);
 assert.equal(checkpointCatalog({receivedAt:1000},999).live,false);
 assert.deepEqual(checkpointCatalog({}).checkpoints,[]);
 assert.equal(checkpointCatalog({}).receivedAt,null);
});
