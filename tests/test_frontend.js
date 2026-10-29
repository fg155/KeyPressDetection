'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const web=path.join(__dirname,'../web');
const ElapsedClock=require('../web/elapsed.js');
let now=0;const clock=new ElapsedClock(()=>now);
clock.sync({id:'one',status:'running',elapsed:0});now=12500;
assert.equal(clock.value(),12.5); // Model initialization with no progress events.
clock.sync({id:'one',status:'running',elapsed:0});
assert.equal(clock.value(),12.5); // A language redraw must not reset elapsed time.
clock.sync({id:'one',status:'stopping',elapsed:13});now=14500;
assert.equal(clock.value(),15);
clock.sync({id:'one',status:'completed',elapsed:14});now=20000;
assert.equal(clock.value(),14);
clock.sync({id:'two',status:'running',elapsed:1});now=21000;clock.pause();now=26000;
assert.equal(clock.value(),2);
clock.sync({id:'two',status:'running',elapsed:7});now=27000;
assert.equal(clock.value(),8);clock.reset();assert.equal(clock.id,null);

const nodes=['Inference','Format','Fingertip score','Delete folders'].map(text=>({textContent:text,isConnected:true,parentElement:{closest:()=>false}}));
const attribute={value:'Select video',getAttribute(key){return key==='aria-label'?this.value:null;},setAttribute(_,value){this.value=value;}};
const store=new Map([['fasterrcnn-language','en']]);
const context=vm.createContext({window:{},NodeFilter:{SHOW_TEXT:4},CustomEvent:class{},
  localStorage:{getItem:key=>store.get(key),setItem:(key,value)=>store.set(key,value)},
  document:{body:{querySelectorAll:()=>[attribute]},documentElement:{},dispatchEvent(){},
    createTreeWalker(){let index=0;return{nextNode:()=>nodes[index++]};}}});
for(const file of ['locales.js','i18n.js'])vm.runInContext(fs.readFileSync(path.join(web,file),'utf8'),context);
const i18n=context.window.I18n;i18n.bind();assert.equal(nodes[2].textContent,'Fingertip score');
i18n.set('zh');assert.equal(nodes[2].textContent,'\u6307\u5c16\u8c31');assert.equal(attribute.value,'\u9009\u62e9\u89c6\u9891');
i18n.set('en');assert.equal(nodes[3].textContent,'Delete folders');assert.equal(attribute.value,'Select video');
assert.equal(store.get('key-press-detection-language'),'en');

const html=fs.readFileSync(path.join(web,'index.html'),'utf8'),app=fs.readFileSync(path.join(web,'app.js'),'utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(ids.length,new Set(ids).size);
for(const [,id] of app.matchAll(/\$\(['"]([^'"]+)['"]\)/g))assert.ok(ids.includes(id),`Missing element ${id}`);
const formatSelect=html.match(/<select id="convert-format">(.*?)<\/select>/s)[1];
assert.equal([...formatSelect.matchAll(/<option /g)].length,1);assert.ok(formatSelect.includes('value="fingertip"'));
assert.ok(html.includes('<title>Key Press Detection</title>'));assert.ok(!html.includes('<h1'));
console.log('Frontend clock, localization, format selector and DOM references passed.');

// Both distributions serve the same markup; only backend-specific controls vary.
const elements=new Map(ids.map(id=>[id,{hidden:false,disabled:false,value:'',innerHTML:'',max:'24',dataset:{},classList:{toggle(){}}}]));
const label={htmlFor:'batch-size'};let restored=0;
const environmentContext=vm.createContext({state:{environment:{}},$:(id)=>elements.get(id),
  show:(id,visible)=>{elements.get(id).hidden=!visible;},renderAdapters(){},renderThreadValue(){},
  restoreInputs(){restored++;},tr:s=>s,escapeHtml:s=>String(s),document:{querySelector:()=>label}});
const envFunction=app.slice(app.indexOf('function renderEnvironment('),app.indexOf('function renderAdapters('));
vm.runInContext(envFunction,environmentContext);
for(const [edition,enabled] of [['directml',false],['cuda',true],['directml',false]]){
  environmentContext.renderEnvironment({edition,cuda_enabled:enabled,directml:{adapters:[]}});
  assert.equal(elements.get('cuda-amp-row').hidden,!enabled);
  assert.equal(elements.get('cuda-batch-size').disabled,!enabled);
  assert.equal(elements.get('batch-size').disabled,enabled);
  assert.equal(elements.get('cuda-device-option').hidden,!enabled);
  assert.equal(label.htmlFor,enabled?'cuda-batch-size':'batch-size');
}
assert.equal(restored,3);
console.log('Shared frontend CUDA/DirectML control switching passed.');
