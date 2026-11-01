// Dashboard counts span outages; selected charts describe the latest encounter only.
export function historySeries(points,field){
 let ordered=points.filter(p=>Number.isFinite(p.timestamp)).slice().sort((a,b)=>a.timestamp-b.timestamp);
 ordered=[...new Map(ordered.map(p=>[p.timestamp,p])).values()];
 // Missing rate samples mean no plotted hits; missing altitude must never become zero.
 if(field==='hits')ordered=ordered.map(p=>Number.isFinite(p.hits)?p:{...p,hits:0});
 const values=ordered.filter(p=>Number.isFinite(p[field]));
 const segments=values.length?[values]:[];
 const numbers=values.map(p=>p[field]);
 let min=Math.min(0,...numbers),max=Math.max(1,...numbers);
 if(field==='altitude'&&numbers.length){
  min=Math.min(...numbers);max=Math.max(...numbers);
 }
 const start=values[0]?.timestamp??0,end=Math.max(values.at(-1)?.timestamp??start,start+60);
 return {points:values,segments,start,end,min,max};
}

// Keep permanent observations intact; the browser remembers where chart history starts.
export function visibleHistory(points,clearedAt){
 return clearedAt>0?points.filter(point=>point.timestamp>clearedAt):points;
}
