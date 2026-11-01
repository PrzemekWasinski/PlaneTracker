import test from 'node:test';
import assert from 'node:assert/strict';
import {historySeries,visibleHistory} from './history.mjs';

test('dashboard lines bridge shutdown gaps and missing samples',()=>{
 for(const field of ['active','total']){
  const chart=historySeries([{timestamp:100,[field]:3},{timestamp:160,[field]:null},{timestamp:15000,[field]:7}],field);
  assert.equal(chart.segments.length,1);
  assert.deepEqual(chart.segments[0].map(p=>p[field]),[3,7]);
 }
});
test('selected charts preserve missing measurements instead of plotting zeros',()=>{
 const chart=historySeries([{timestamp:100,altitude:30000},{timestamp:110,altitude:null},{timestamp:120,altitude:30100}], 'altitude');
 assert.equal(chart.segments.length,2);
 assert.equal(chart.points.length,2);
 assert.ok(chart.min<30000 && chart.min>29000);
 assert.ok(chart.max>30100);
});
test('flat, negative and empty altitude histories have finite nonzero scales',()=>{
 for(const points of [[],[{timestamp:10,altitude:35000}],[{timestamp:10,altitude:-200}]]){
  const chart=historySeries(points,'altitude');
  assert.ok(chart.max>chart.min);
  assert.ok(chart.end>chart.start);
 }
});
test('timestamps are sorted and duplicate points do not create vertical spikes',()=>{
 const chart=historySeries([{timestamp:20,hits:100},{timestamp:10,hits:50},{timestamp:20,hits:120}], 'hits');
 assert.deepEqual(chart.points.map(p=>p.hits),[50,120]);
});

test('clearing hides every graph through the cutoff and preserves subsequent samples',()=>{
 const points=[{timestamp:100,active:3,total:8,altitude:3000,hits:60},{timestamp:200,active:4,total:9,altitude:3100,hits:120}];
 assert.deepEqual(visibleHistory(points,0),points);
 assert.deepEqual(visibleHistory(points,200),[]);
 assert.deepEqual(visibleHistory([...points,{timestamp:201,active:2,total:9,altitude:3200,hits:90}],200).map(p=>p.timestamp),[201]);
 assert.equal(points.length,2);
});
