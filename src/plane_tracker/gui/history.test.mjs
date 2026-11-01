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
 assert.equal(chart.segments.length,1);
 assert.equal(chart.points.length,2);
 assert.equal(chart.min,30000);
 assert.equal(chart.max,30100);
});
test('flat, negative and empty altitude histories have finite bounds',()=>{
 for(const points of [[],[{timestamp:10,altitude:35000}],[{timestamp:10,altitude:-200}]]){
  const chart=historySeries(points,'altitude');
  assert.ok(Number.isFinite(chart.min)&&Number.isFinite(chart.max));
  assert.ok(chart.max>=chart.min);
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

test('altitude bounds follow exact new high and low readings without padding',()=>{
 const points=[{timestamp:100,altitude:10000},{timestamp:110,altitude:9000}];
 assert.equal(historySeries(points,'altitude').max,10000);
 assert.equal(historySeries(points,'altitude').min,9000);
 points.push({timestamp:120,altitude:8000});
 assert.equal(historySeries(points,'altitude').min,8000);
 assert.equal(historySeries(points,'altitude').max,10000);
 points.push({timestamp:130,altitude:11000});
 assert.equal(historySeries(points,'altitude').min,8000);
 assert.equal(historySeries(points,'altitude').max,11000);
 const flat=historySeries([{timestamp:100,altitude:35000}],'altitude');
 assert.equal(flat.min,35000);assert.equal(flat.max,35000);
});

test('altitude time axis begins at the first valid altitude, ignoring leading unknowns',()=>{
 const chart=historySeries([{timestamp:100,altitude:null},{timestamp:120,altitude:null},{timestamp:140,altitude:9000},{timestamp:200,altitude:8000}], 'altitude');
 assert.equal(chart.start,140);
 assert.equal(chart.points[0].timestamp,chart.start);
 assert.equal(chart.segments.length,1);
});
test('message silence is zero and never breaks the line',()=>{
 const chart=historySeries([{timestamp:100,hits:120},{timestamp:160,hits:0},{timestamp:220,hits:null},{timestamp:300,hits:90}], 'hits');
 assert.equal(chart.segments.length,1);
 assert.deepEqual(chart.points.map(p=>p.hits),[120,0,0,90]);
 assert.equal(chart.start,100);
});
