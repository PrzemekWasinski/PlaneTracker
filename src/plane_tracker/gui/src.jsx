import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Radar,{Icon} from './Radar';
import './style.css';

const empty={receiver:{status:'waiting',hitRate:null},aircraft:[],stats:{},system:{},logs:[]};
const factors={NM:1/1.852,KM:1,MI:1/1.609344};
const fmt=(v,suffix='',digits=0)=>v===null||v===undefined?'—':Number(v).toLocaleString('en-GB',{maximumFractionDigits:digits})+suffix;
function Panel({name,children,className='',action}){return <section className={'panel '+className}><header><h2>{name}</h2>{action}</header>{children}</section>}
function HistoryGraph({name,field,points}){
 const values=points.filter(p=>Number.isFinite(p[field])), max=Math.max(1,...values.map(p=>p[field]));
 const start=points[0]?.timestamp||0,end=points.at(-1)?.timestamp||start;
 const x=p=>38+212*(p.timestamp-start)/Math.max(60,end-start),y=p=>78-64*p[field]/max;
 const segments=[];let current=[];
 for(const p of points){if(!Number.isFinite(p[field])||(current.length&&p.timestamp-current.at(-1).timestamp>(field==='nearby'?3700:90))){if(current.length)segments.push(current);current=[]}if(Number.isFinite(p[field]))current.push(p)}if(current.length)segments.push(current);
 const stamp=t=>new Date(t*1000).toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});
 return <div className="empty-graph"><span>{name}</span><svg viewBox="0 0 260 100" role="img" aria-label={name+' history'}>
 {[14,46,78].map(y=><line key={y} x1="50" x2="250" y1={y} y2={y}/>)}<text className="y-axis-label" x="30" y="17" textAnchor="end">{Math.round(max)}</text><text className="y-axis-label" x="30" y="80" textAnchor="end">0</text>
 {segments.map((segment,i)=><polyline className="history-line" key={i} points={segment.map(p=>`${x(p)},${y(p)}`).join(' ')}/>)}
 {values.map(p=><circle className="history-dot" key={p.timestamp} cx={x(p)} cy={y(p)} r="2"><title>{stamp(p.timestamp)}: {p[field]}</title></circle>)}
 {points.length>0?<><text x="50" y="97">{stamp(start)}</text><text x="250" y="97" textAnchor="end">{stamp(end)}</text></>:<text x="55" y="47">Collecting history</text>}
 </svg></div>;
}
function SegmentDisplay({value}){
 const digits=['abcdef','bc','abdeg','abcdg','bcfg','acdfg','acdefg','abc','abcdefg','abcdfg'];
 const shapes={a:[3,0,12,3],b:[15,3,3,12],c:[15,18,3,12],d:[3,30,12,3],e:[0,18,3,12],f:[0,3,3,12],g:[3,15,12,3]};
 return <span className="segment-display" aria-hidden="true">{[...value].map((c,i)=><svg key={i} preserveAspectRatio="none" viewBox={/\d/.test(c)?'0 0 18 33':'0 0 8 33'}>{/\d/.test(c)?Object.entries(shapes).map(([key,[x,y,width,height]])=><rect key={key} x={x} y={y} width={width} height={height} strokeWidth="1" stroke={digits[+c].includes(key)?'currentColor':'#492126'} fill={digits[+c].includes(key)?'currentColor':'#492126'}/>):c===':'?<><circle cx="4" cy="10" r="1.6"/><circle cx="4" cy="23" r="1.6"/></>:<path d="M1 28L7 5" stroke="currentColor" strokeWidth="2"/>}</svg>)}</span>;
}
function PolarPlot({data}){
 const bins=data?.bins||Array(36).fill(0),maximum=Math.max(1,...bins);
 const point=(angle,r)=>[100+Math.sin(angle*Math.PI/180)*r,100-Math.cos(angle*Math.PI/180)*r];
 return <figure className="polar-figure"><svg className="empty-polar" viewBox="0 0 200 200" role="img" aria-label="Position messages by bearing over the last minute">
 {[.25,.5,.75,1].map(f=><g key={f}><circle cx="100" cy="100" r={f*80}/><text x="104" y={100-f*80+9}>{Math.ceil(maximum*f)}</text></g>)}
 {[0,45,90,135].map(a=><line key={a} x1="100" y1="20" x2="100" y2="180" transform={'rotate('+a+' 100 100)'}/>)}
 {bins.map((count,i)=>{const r=80*count/maximum,[x1,y1]=point(i*10-4.5,r),[x2,y2]=point(i*10+4.5,r);return count>0?<path className="polar-sector" key={i} d={`M100 100L${x1} ${y1}A${r} ${r} 0 0 1 ${x2} ${y2}Z`}><title>{i*10} degrees: {count.toLocaleString()} messages</title></path>:null})}
 <text x="96" y="10">N</text><text x="190" y="104">E</text><text x="97" y="198">S</text><text x="0" y="104">W</text>
 </svg></figure>;
}
function Clock(){
 const [now,setNow]=useState(()=>new Date());
 useEffect(()=>{const timer=setInterval(()=>setNow(new Date()),1000);return()=>clearInterval(timer)},[]);
 const value=now.toLocaleTimeString('en-GB');
 return <time className="date" dateTime={now.toISOString()} aria-label={value} title="Local time"><SegmentDisplay value={value}/></time>;
}
function LogPanel({logs}){
 const rows=useRef(null),resumeTimer=useRef(null),paused=useRef(false),lastTop=useRef(0);
 const newestId=logs[0]?.id;
 function showNewest(){
  const box=rows.current;if(!box)return;
  box.scrollTop=box.scrollHeight;lastTop.current=box.scrollTop;
 }
 function pauseFollow(){
  paused.current=true;clearTimeout(resumeTimer.current);
  resumeTimer.current=setTimeout(()=>{paused.current=false;showNewest()},60000);
 }
 function handleScroll(){
  const top=rows.current.scrollTop;
  if(Math.abs(top-lastTop.current)>.5){lastTop.current=top;pauseFollow()}
 }
 useLayoutEffect(()=>{if(!paused.current)showNewest()},[newestId]);
 useEffect(()=>()=>clearTimeout(resumeTimer.current),[]);
 return <Panel name="Logs" className="logs"><div className="log-rows" ref={rows} tabIndex={0} aria-label="Log messages" onScroll={handleScroll} onWheel={pauseFollow} onTouchMove={pauseFollow} onKeyDown={event=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key))pauseFollow()}}>{[...logs].reverse().map(row=><div className={'log-row '+row.level} key={row.id}><time>{new Date(row.time*1000).toLocaleTimeString('en-GB')}</time><p>{row.message}</p></div>)}</div></Panel>;
}
function App(){
 const [data,setData]=useState(empty),[config,setConfig]=useState(null),[connected,setConnected]=useState(true);
 const [manualSelection,setManualSelection]=useState(null),[follow,setFollow]=useState(false);
 const unit='NM',trails='all',labels=true;
 useEffect(()=>{
  let stopped=false,timer,controller;
  async function poll(){
   controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),5000);
   try{
    const response=await fetch('/api/state',{signal:controller.signal,cache:'no-store'});if(!response.ok)throw Error();
    const state=await response.json();
    if(!stopped){setData(state);setConnected(true)}
   }catch{if(!stopped)setConnected(false)}
   finally{clearTimeout(timeout);if(!stopped)timer=setTimeout(poll,1000)}
  }
  poll();return()=>{stopped=true;clearTimeout(timer);controller?.abort()};
 },[]);
 useEffect(()=>{
  let stopped=false,timer;const controller=new AbortController();
  async function load(){try{const r=await fetch('/api/config',{signal:controller.signal});if(!r.ok)throw Error();const c=await r.json();if(!stopped)setConfig(c)}catch{if(!stopped)timer=setTimeout(load,3000)}}
  load();return()=>{stopped=true;controller.abort();clearTimeout(timer)};
 },[]);
 const sourceStatus=connected?data.receiver.status:'disconnected';
 const live=sourceStatus==='live';
 const aircraft=live?data.aircraft:[];
 const available=live?data.aircraft:[];
 const manualPlane=available.find(p=>p.icao===manualSelection);
 const nearest=aircraft.reduce((best,p)=>Number.isFinite(p.distanceKm)&&(!best||p.distanceKm<best.distanceKm)?p:best,null);
 const plane=manualPlane||nearest;
 const selected=plane?.icao||null;
 useEffect(()=>{if(manualSelection&&!manualPlane){setManualSelection(null);setFollow(false)}},[manualSelection,manualPlane]);
 const s=data.stats,health=data.system;
 const model=plane?.model||'';
 const manufacturer=plane?.manufacturer?.trim()||'';
 // Older caches may contain only the unambiguous Airbus A3xx model family.
 const displayManufacturer=manufacturer||(/^A3(?:00|10|18|19|20|21|30|40|50|80)(?:[ -]|$)/i.test(model)?'Airbus':'');
 const modelName=displayManufacturer&&!model.toLowerCase().startsWith(displayManufacturer.toLowerCase())?`${displayManufacturer} ${model}`.trim():model;
 const distanceText=v=>fmt(v===null||v===undefined?null:v*factors[unit],' '+unit,1);

 return <main>
  <aside className="left-column">
   <Panel name="Stats Today" className="statistics" action={<Clock/>}>
    <div className="big-stats"><div><label>Total aircraft</label><strong>{fmt(s.total)}</strong></div><div><label>Active</label><strong className="accent">{live?data.aircraft.length:'—'}</strong></div></div>
    <div className="service-status">{[['API',connected&&s.apiAvailable],['ADS-B Receiver',live],['Firebase',connected&&s.firebaseAvailable]].map(([name,active])=><span key={name} title={name==='API'?'Aircraft metadata API: last lookup result':name==='Firebase'?'Firebase: last upload result':'ADS-B receiver feed'} aria-label={`${name}: ${active?'active':'inactive'}`}><i className={active?'active':'inactive'} aria-hidden="true"/>{name}</span>)}</div>
    <dl className="stats-grid">{[['Top Airline',s.topAirline||'?'],['Top Aircraft',s.topAircraft||'?'],['Top Manufacturer',s.topManufacturer||'?'],['Airlines',fmt(s.airlines)],['Aircraft',fmt(s.models)],['Max Distance',distanceText(s.furthest)],['Max Altitude',fmt(s.highest,' ft')],['Max Speed',fmt(s.maxSpeed,' kt')],['Max Messages',fmt(s.maxHits)]].map(([k,v])=><div key={k}><dt>{k}</dt><dd title={v}>{v}</dd></div>)}</dl>

    {s.historyError&&<span className="history-error">History unavailable</span>}
   </Panel>
   <Panel name="Performance" className="receiver">
    <div className="receiver-body"><PolarPlot data={data.polar}/>
    <dl className="health">{[['CPU',fmt(health.cpu,'%')],['RAM',fmt(health.memory,'%')],['Disk',fmt(health.diskUsed,'%')],['Temp',fmt(health.temperature,'\u00b0C')],['Messages / S',fmt(live?data.receiver.hitRate:null,'',1)]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></div>
   </Panel>
   <LogPanel logs={data.logs}/>
  </aside>
  {config?<Radar config={config} aircraft={aircraft} selected={selected} onSelect={id=>{setManualSelection(id);if(!id)setFollow(false)}} follow={follow} onFollowChange={setFollow} trails={trails} showLabels={labels} unit={unit} connection={sourceStatus}/>:<section className="radar loading-map" role="status">Connecting</section>}
  <aside className="right-column">
   <Panel name="Selected Aircraft" className="selected" action={<span className="hex" title={manualPlane?"Manual selection":"Auto: nearest aircraft"}>{manualPlane?"Manual":"Auto"}</span>}>
    <div className="aircraft-overview"><div className="identity"><div className="flight-identity"><strong>{plane?.callsign||'—'}</strong><span className="icao-code" title="ICAO aircraft code">{plane?.icao||'—'}</span></div><span>{plane?.airline||'—'}</span></div>
    </div><div className="model"><span>{modelName||'—'}</span><span>{plane?.registration||'—'}</span></div>
    <dl className="flight-grid">{[['Altitude',fmt(plane?.altitude,' ft')],['Speed',fmt(plane?.speed,' kt')],['V/Rate',fmt(plane?.verticalRate,' ft/min')],['Distance',distanceText(plane?.distanceKm)],['Squawk',plane?.squawk||'—'],['Messages',fmt(plane?.positionHits)]].map(([k,v])=><div key={k}><dt title={k==='Messages'?'Observed position updates today; deduplicated by position timestamp':undefined}>{k}</dt><dd>{v}</dd></div>)}</dl>
    <button className={'follow '+(follow?'on':'')} disabled={!plane} onClick={()=>setFollow(!follow)}><Icon name="target"/>{follow?'Following':'Follow'}</button>
   </Panel>
   <Panel name="History" className="graphs"><div className="chart-grid">{[['Active Aircraft','active'],['Total','total'],['Selected Aircraft Altitude (ft)','altitude'],['Selected Aircraft Messages / Min','hits']].map(([name,field])=><HistoryGraph key={field} name={name} field={field} points={['altitude','hits'].includes(field)?(plane?.history||[]):(data.history||[])}/>)}</div></Panel>

  </aside>
 </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
