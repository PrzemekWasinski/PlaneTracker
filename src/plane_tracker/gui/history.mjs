// Dashboard counts span outages; selected charts describe the latest encounter only.
export function historySeries(points,field){
 const selected=field==='altitude'||field==='hits';
 let ordered=points.filter(p=>Number.isFinite(p.timestamp)).slice().sort((a,b)=>a.timestamp-b.timestamp);
 ordered=[...new Map(ordered.map(p=>[p.timestamp,p])).values()];
 const values=ordered.filter(p=>Number.isFinite(p[field]));
 const segments=[];let current=[];
 for(const p of ordered){
  if(!Number.isFinite(p[field])){if(selected&&current.length){segments.push(current);current=[]}continue}
  current.push(p);
 }
 if(current.length)segments.push(current);
 const numbers=values.map(p=>p[field]);
 let min=Math.min(0,...numbers),max=Math.max(1,...numbers);
 if(field==='altitude'&&numbers.length){
  const low=Math.min(...numbers),high=Math.max(...numbers),padding=Math.max(100,(high-low)*.1);
  min=low-padding;max=high+padding;
 }
 const start=ordered[0]?.timestamp??0,end=Math.max(ordered.at(-1)?.timestamp??start,start+60);
 return {points:values,segments,start,end,min,max};
}

// Keep permanent observations intact; the browser remembers where chart history starts.
export function visibleHistory(points,clearedAt){
 return clearedAt>0?points.filter(point=>point.timestamp>clearedAt):points;
}
