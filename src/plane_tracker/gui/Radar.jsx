import React,{useEffect,useRef,useState} from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

const empty={type:'FeatureCollection',features:[]};
const planePath='M0 -16L3 -6L15 2L15 5L3 2L3 11L7 15L7 17L0 14L-7 17L-7 15L-3 11L-3 2L-15 5L-15 2L-3 -6Z';
const blankStyle={version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#000000'}}]};
export function Icon({name}){
 const paths={plus:'M12 5v14M5 12h14',minus:'M5 12h14',home:'m3 11 9-8 9 8M5 10v11h14V10M9 21v-7h6v7',full:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',target:'M12 2v4m0 12v4M2 12h4m12 0h4M18 12a6 6 0 1 1-12 0 6 6 0 0 1 12 0',search:'M16 16l5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'};
 return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]}/></svg>;
}
export default function Radar({config,aircraft,selected,onSelect,follow,onFollowChange,trails,showLabels,unit,connection}){
 const host=useRef(),mapRef=useRef(),markers=useRef(new Map()),homeMarker=useRef();
 const current=useRef();current.current={aircraft,selected,onSelect,follow,onFollowChange,trails,showLabels};
 const [mapError,setMapError]=useState(false),[ready,setReady]=useState(0),[fullscreen,setFullscreen]=useState(false);
 useEffect(()=>{
  const changed=()=>setFullscreen(Boolean(document.fullscreenElement));
  document.addEventListener('fullscreenchange',changed);
  return()=>document.removeEventListener('fullscreenchange',changed);
 },[]);
 useEffect(()=>{
  if(!config||!host.current)return;
  let map;
  try{map=new maplibregl.Map({container:host.current,style:blankStyle,center:[config.home.lon,config.home.lat],zoom:7.2,minZoom:3,maxZoom:15,attributionControl:true,canvasContextAttributes:{antialias:true},dragRotate:false,pitchWithRotate:false});}
  catch{setMapError(true);return}
  mapRef.current=map;
  map.addControl(new maplibregl.ScaleControl({maxWidth:90,unit:unit==='NM'?'nautical':unit==='MI'?'imperial':'metric'}),'bottom-left');
  const addLayers=()=>{
   if(!map.getSource('trails'))map.addSource('trails',{type:'geojson',data:empty});
   if(!map.getLayer('trails'))map.addLayer({id:'trails',type:'line',source:'trails',paint:{'line-color':['case',['==',['get','selected'],true],'#ffffff','#38c94b'],'line-width':['case',['==',['get','selected'],true],2.5,1.3],'line-opacity':['case',['==',['get','selected'],true],.85,.36]}});
   setReady(v=>v+1);
  };
  map.on('style.load',addLayers);
  map.on('error',()=>setMapError(true));
  map.on('idle',()=>{if(!styleFailed&&map.isStyleLoaded()&&map.areTilesLoaded())setMapError(false)});
  map.on('dragstart',()=>current.current.onFollowChange(false));
  map.on('click',()=>current.current.onSelect(null));
  const home=document.createElement('div');home.className='home-marker';home.title='Receiver';
  homeMarker.current=new maplibregl.Marker({element:home}).setLngLat([config.home.lon,config.home.lat]).addTo(map);
  const abort=new AbortController();
  let styleFailed=false;
  fetch(config.mapStyle,{signal:abort.signal})
   .then(response=>{if(!response.ok)throw Error('Map style unavailable');return response.json()})
   .then(style=>{if(!abort.signal.aborted)map.setStyle(style)})
   .catch(error=>{if(error.name!=='AbortError'){styleFailed=true;setMapError(true)}});
  const resize=new ResizeObserver(()=>map.resize());resize.observe(host.current);
  return()=>{abort.abort();resize.disconnect();markers.current.forEach(m=>m.marker.remove());markers.current.clear();map.remove();mapRef.current=null;};
 },[config]);
 useEffect(()=>{
  const map=mapRef.current;if(!map)return;
  const ids=new Set(aircraft.map(p=>p.icao));
  for(const [id,item] of markers.current)if(!ids.has(id)){item.marker.remove();markers.current.delete(id)}
  for(const p of aircraft){
   let item=markers.current.get(p.icao);
   if(!item){
    const element=document.createElement('button');element.className='aircraft-marker';element.type='button';
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','-20 -20 40 40');
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',planePath);icon.append(path);
    const label=document.createElement('span');label.className='aircraft-label';
    const call=document.createElement('strong'),airline=document.createElement('small'),model=document.createElement('small'),alt=document.createElement('small');label.append(call,airline,model,alt);element.append(icon,label);
    element.addEventListener('click',e=>{e.stopPropagation();current.current.onSelect(p.icao)});
    const marker=new maplibregl.Marker({element,anchor:'center'}).setLngLat([p.lon,p.lat]).addTo(map);
    item={marker,element,icon,label,call,airline,model,alt};markers.current.set(p.icao,item);
   }
   item.marker.setLngLat([p.lon,p.lat]);item.element.classList.toggle('selected',p.icao===selected);
   const known=value=>typeof value==='string'&&!['','-','unknown','n/a'].includes(value.trim().toLowerCase())?value.trim():'';
   const flight=known(p.callsign)||'Unknown';
   const airline=known(p.airline)||'Unknown';
   const manufacturer=known(p.manufacturer),model=known(p.model);
   const modelName=(manufacturer&&!model.toLowerCase().startsWith(manufacturer.toLowerCase())?[manufacturer,model].filter(Boolean).join(' '):model)||'Unknown';
   const altitude=Number.isFinite(p.altitude)?p.altitude.toLocaleString('en-GB',{maximumFractionDigits:0})+' ft':'Unknown';
   item.element.setAttribute('aria-label',`Select ${flight}, ${airline}, ${modelName}, altitude ${altitude}`);
   item.element.title=`${flight}\n${airline}\n${modelName}\n${altitude}`;
   item.icon.style.transform='rotate('+(p.heading??0)+'deg)';
   item.call.textContent=flight;item.airline.textContent=airline;item.model.textContent=modelName;item.alt.textContent=altitude;
   item.label.hidden=!showLabels;
  }
  const source=map.getSource('trails');
  if(source)source.setData({type:'FeatureCollection',features:aircraft.filter(p=>p.trail.length>1&&(trails==='all'||(trails==='selected'&&p.icao===selected))).map(p=>({type:'Feature',geometry:{type:'LineString',coordinates:p.trail},properties:{selected:p.icao===selected}}))});
  const target=aircraft.find(p=>p.icao===selected);
  if(follow&&target)map.easeTo({center:[target.lon,target.lat],duration:850});
 },[aircraft,selected,follow,trails,showLabels,ready]);
 function centerHome(){onFollowChange(false);mapRef.current?.easeTo({center:[config.home.lon,config.home.lat],duration:600})}
 async function toggleFullscreen(){try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch{setFullscreen(false)}}
 return <section className="radar">
  <div className="map" ref={host} aria-label="Live radar map"/>
  <div className="map-top">
   <div className="map-status"><i className={connection==='live'?'live':'offline'}/><span>{connection==='live'?'Live':connection==='stale'?'Stale':connection==='disconnected'?'Disconnected':'No receiver'}</span><b>{aircraft.length}</b></div>
   <button type="button" className="fullscreen-button" aria-label="Center on home" title="Center on home" onClick={centerHome}><Icon name="home"/></button>
   <button className="fullscreen-button" aria-label={fullscreen?"Exit fullscreen":"Fullscreen"} title="Fullscreen" onClick={toggleFullscreen}><Icon name="full"/></button>
  </div>
  {mapError&&<div className="map-error" role="status">Map unavailable</div>}

 </section>;
}
