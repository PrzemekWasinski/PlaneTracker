import {chromium} from '@playwright/test';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
const page=await browser.newPage({viewport:{width:1920,height:1080}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/config',r=>r.fulfill({json:{home:{lat:51.69,lon:-.037},mapStyle:'http://127.0.0.1:4182/style.json'}}));
await page.route('**/style.json',r=>r.fulfill({json:{version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#11191d'}}]}}));
let aircraft=[{icao:'407123',callsign:'BAW247',lat:51.8,lon:.1,altitude:35000,speed:472,heading:80,verticalRate:0,squawk:'7000',history:[{timestamp:1000,altitude:34000,hits:2},{timestamp:1060,altitude:35000,hits:4}],positionHits:1200,distanceKm:32,registration:'G-ZBKN',manufacturer:'Boeing',model:'787-9',airline:'British Airways',trail:[[-.1,51.75],[.1,51.8]]}];
await page.route('**/api/state',r=>r.fulfill({json:{nearbyHourly:[{timestamp:1000,nearby:2},{timestamp:4600,nearby:4}],history:[{timestamp:1000,active:1,total:1,altitude:35000,hits:2},{timestamp:1060,active:2,total:2,altitude:36000,hits:4}],polar:{bins:Array.from({length:36},(_,i)=>i===0?120:i===9?60:0),total:180},receiver:{status:'live',hitRate:2},aircraft,stats:{total:742,airlines:42,models:68,furthest:260,highest:41000,maxSpeed:552,maxHits:2084,topAirline:'British Airways',topAircraft:'A320',topManufacturer:'Airbus',historyAvailable:true,date:'2026-09-20'},system:{cpu:17,memory:38,temperature:46,diskUsed:21.4},logs:[{id:1,time:Date.now()/1000,message:'Receiver connected',level:'info'}]}}));
await page.goto('http://127.0.0.1:4182/');
await page.waitForFunction(()=>document.querySelector('.selected .hex')?.textContent.startsWith('Auto'));
const original=aircraft[0];
aircraft=[original,{...original,icao:'ABC456',callsign:'NEAR123',distanceKm:1,lat:51.7,lon:0}];
await page.waitForFunction(()=>document.querySelector('.identity strong')?.textContent==='NEAR123');
await page.getByRole('button',{name:'Select BAW247'}).click();
await page.waitForFunction(()=>document.querySelector('.selected .hex')?.textContent.startsWith('Manual'));
await page.waitForTimeout(1200);
if(await page.locator('.identity strong').textContent()!=='BAW247')throw Error('Manual selection lost');
await page.locator('.map canvas').click({position:{x:300,y:200}});
await page.waitForFunction(()=>document.querySelector('.identity strong')?.textContent==='NEAR123');
await page.getByRole('button',{name:'Select BAW247'}).click();aircraft=[aircraft[1]];
await page.waitForFunction(()=>document.querySelector('.identity strong')?.textContent==='NEAR123'&&document.querySelector('.selected .hex')?.textContent.startsWith('Auto'));
aircraft=[original];await page.getByRole('button',{name:'Select BAW247'}).waitFor();
await page.getByRole('button',{name:'Follow',exact:true}).click();
const clock=page.locator('.statistics time');await clock.waitFor();
const before=await clock.getAttribute('datetime');await page.waitForFunction(previous=>document.querySelector('.statistics time').getAttribute('datetime')!==previous,before);
if(await page.getByLabel('Find aircraft').count()||await page.getByRole('button',{name:'Zoom in'}).count())throw Error('Removed controls remain');
await page.getByRole('button',{name:'Fullscreen',exact:true}).click();
await page.getByRole('button',{name:'Exit fullscreen',exact:true}).click();
const placement=await page.evaluate(()=>{const rect=c=>document.querySelector(c).getBoundingClientRect();return rect('.receiver').left<rect('.selected.panel').left&&rect('.logs').left===rect('.graphs').left&&rect('.logs').width===rect('.graphs').width&&rect('.logs').top>rect('.graphs').bottom});
if(!placement||await page.locator('.filters').count())throw Error('Panel arrangement failed');
if(await page.locator('.polar-sector').count()!==2)throw Error('Polar sectors missing');
await page.getByText('180 hits / 15 min',{exact:true}).waitFor();
if(await page.locator('.history-line').count()!==4)throw Error('History lines missing');
await page.locator('.model').getByText('Boeing 787-9',{exact:true}).waitFor();
await page.getByText('46\u00b0C',{exact:true}).waitFor();
await page.screenshot({path:'test-results/redesign.png'});
const clipped=await page.locator('.panel').evaluateAll(es=>es.filter(e=>e.scrollHeight>e.clientHeight+3).map(e=>e.className));if(clipped.length)throw Error('Clipped: '+clipped);
for(const [width,height] of [[1920,1080],[1366,768],[900,900],[390,844]]){
 await page.setViewportSize({width,height});
 const layout=await page.evaluate(()=>{const radar=document.querySelector('.radar').getBoundingClientRect();return {square:Math.abs(radar.width-radar.height)<2,right:[...document.querySelectorAll('.panel')].every(e=>e.getBoundingClientRect().left>=radar.right),overflow:document.documentElement.scrollWidth>innerWidth}});
 if((width<=1100&&!layout.square)||layout.overflow||(width>1100&&!layout.right))throw Error('Layout at '+width+': '+JSON.stringify(layout));
}
if(errors.length)throw Error(errors.join('\n'));console.log('PASS: full-HD layout, selection, follow, search, live clock and panel arrangement; no JavaScript errors');
}finally{await browser.close()}
