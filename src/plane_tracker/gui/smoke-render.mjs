import { chromium } from '@playwright/test';
const browser = await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
 const page = await browser.newPage({viewport:{width:1920,height:1080}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/config',r=>r.fulfill({json:{home:{lat:51.69,lon:-.037},mapStyle:'http://127.0.0.1:4181/test-style.json'}}));
 await page.route('**/test-style.json',r=>r.fulfill({json:{version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#0c171b'}}]}}));
 await page.route('**/api/state',r=>r.fulfill({json:{receiver:{status:'live',messageRate:12},aircraft:[],stats:{total:0},system:{},logs:[]}}));
 await page.goto('http://127.0.0.1:4181/');
 await page.getByRole('button',{name:'Zoom in',exact:true}).waitFor();
 await page.locator('canvas.maplibregl-canvas').waitFor();
 await page.waitForTimeout(1000);
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS: built page renders radar canvas and controls without JavaScript exceptions');
} finally { await browser.close(); }
