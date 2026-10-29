'use strict';
const $ = id => document.getElementById(id);
const tr = (source,params) => I18n.t(source,params);
const message = value => I18n.message(value);
const icons = {
  keyboard:'<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h1m4 0h1m4 0h1M6 13h1m4 0h1m4 0h1M7 16h10"/>',
  scan:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/><rect x="8" y="8" width="8" height="8" rx="2"/>',
  layers:'<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  history:'<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7m2-4v5l3 2"/>',
  sliders:'<path d="M4 4v5m0 4v7M12 4v10m0 4v2m8-16v2m0 4v10M1 9h6m2 9h6m2-12h6"/>',
  folder:'<path d="M3 7V5h6l2 2h10v13H3V7Z"/>',
  play:'<path d="m8 4 12 8-12 8V4Z"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  crop:'<path d="M7 3v14h14M3 7h14v14"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
  timeline:'<path d="M3 7h18M3 17h18M7 4v6m10 4v6"/>',
  stop:'<rect x="5" y="5" width="14" height="14" rx="2"/>',
  box:'<path d="m12 3 9 5v9l-9 5-9-5V8l9-5Zm-9 5 9 5 9-5m-9 5v9M7 5.8l10 5.5"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  save:'<path d="M4 3h13l4 4v14H3V3h1Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
  chart:'<path d="M3 3v18h18M6 15l5-5 4 3 6-8"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  refresh:'<path d="M3 10a9 9 0 0 1 15-6l3 3m0-5v5h-5M21 14a9 9 0 0 1-15 6l-3-3m0 5v-5h5"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.box}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
const keyNames = 'QWERTYUASDFGHJZXCVBNM'.split('');
keyNames.forEach(key => {
  const el = document.createElement('button'); el.type='button'; el.className = 'key'; el.id = `key-${key}`; el.textContent = key; $('keyboard').append(el); el.addEventListener('click',()=>toggleKey(key));
  const option = document.createElement('option'); option.value = key; option.textContent = tr("Key {key}",{key}); $('region-select').append(option);
});
const state = {token:'',settings:{},environment:{},active:null,current:null,video:null,videoPath:'',page:'inference',connected:false,polling:false};
const elapsedClock = new ElapsedClock();
function renderElapsed() { $('metric-time').textContent = elapsedClock.id ? duration(Math.floor(elapsedClock.value())) : '—'; }
setInterval(renderElapsed, 250);
const pageLabels = {inference:"Inference",history:"History",settings:"Settings",simulator:"Simulator",converter:"Score conversion",scores:"Score manager"};
const statuses = {running:"Running",stopping:"Stopping",completed:"Completed",cancelled:"Stopped",failed:"Failed",interrupted:"Interrupted"};
const deletedJobIds=new Set();
let toastTimer, pendingStart=false;
let scores=[], uploadedScore=null, scoresDirectory=null;
function show(el,visible=true) { (typeof el==='string'?$(el):el).classList.toggle('hidden',!visible); }
function toast(message,error=false) { $('toast').textContent=I18n.message(message); $('toast').classList.toggle('error',error); show('toast'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>show('toast',false),error?6500:3500); }
function escapeHtml(value) { return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function basename(path) { return String(path||'').split(/[\\/]/).pop(); }
function duration(value) { if(value==null||!Number.isFinite(value)) return '—'; const seconds=Math.max(0,Math.round(value)); return seconds<60?tr("{seconds} s",{seconds}):seconds<3600?tr("{minutes} m {seconds} s",{minutes:Math.floor(seconds/60),seconds:seconds%60}):tr("{hours} h {minutes} m",{hours:Math.floor(seconds/3600),minutes:Math.floor(seconds%3600/60)}); }
function timecode(value) { const sec=Math.max(0,Number(value)||0); return `${String(Math.floor(sec/60)).padStart(2,'0')}:${(sec%60).toFixed(2).padStart(5,'0')}`; }
async function api(path,data) {
  const options = data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-KeyPressDetection-Token':state.token},body:JSON.stringify(data)};
  let response;
  try { response=await fetch(path,options); } catch { throw new Error(tr("Cannot connect to the server. Check the CMD window.")); }
  let result;
  try { result=await response.json(); } catch { throw new Error(tr("The server returned an unexpected response. Run start.cmd again and retry.")); }
  if(!response.ok) throw new Error(message(result.error)||tr("Operation failed"));
  return result;
}
function page(name,refreshScores=true) {
  if(!pageLabels[name]) name='inference';
  state.page=name;
  document.querySelectorAll('.page').forEach(el=>show(el,el.id===`page-${name}`));
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===name));
  $('breadcrumb').textContent=tr(pageLabels[name]);
  if(location.hash!==`#${name}`) history.replaceState(null,'',`#${name}`);
  if(name==='history') loadHistory();
  if(name==='scores') { if(!libraryInitialized){$('library-directory').value=$('output-dir').value;libraryInitialized=true;} loadLibrary(); }
  if(name==='simulator'&&refreshScores) {if(scoresDirectory===null)$('score-directory').value=$('output-dir').value; loadScores();}
  if(name==='converter') { if(!convertInitialized) { $('convert-directory').value=$('output-dir').value; convertInitialized=true; } loadConvertScores(); }
}
document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',()=>page(el.dataset.page)));
window.addEventListener('hashchange',()=>page(location.hash.slice(1)));
$('threshold').addEventListener('input',()=> $('threshold-value').textContent=Number($('threshold').value).toFixed(2));
const savedInputs=['video-path','output-dir','batch-size','cuda-batch-size','stride','infer-min-size'];
function remember() { try { localStorage.setItem(`key-press-detection-${state.environment.edition||'source'}-inputs`,JSON.stringify(Object.fromEntries(savedInputs.map(id=>[id,$(id).value])))); } catch {} }
function restoreInputs() { try { const saved=JSON.parse(localStorage.getItem(`key-press-detection-${state.environment.edition||'source'}-inputs`)||'{}'); for(const id of savedInputs) if(saved[id]!==undefined) $(id).value=saved[id]; } catch {} }
savedInputs.forEach(id=>$(id).addEventListener('change',remember));
function applySettings(settings) {
  state.settings=settings;
  $('default-model').value=settings.model_path;
  $('model-name').textContent=basename(settings.model_path);
  $('device-select').value=settings.device;
  $('infer-amp').checked=settings.amp??true; $('tf32').checked=settings.tf32??false;
  $('directml-precision').value=settings.directml_precision||'fp32';
  renderAdapters();
  $('threshold').value=settings.threshold;
  $('threshold-value').textContent=Number(settings.threshold).toFixed(2);
  $('debounce-ms').value=settings.debounce_ms??50; $('cpu-threads').value=Math.min(settings.cpu_threads??0,Number($('cpu-threads').max)); renderThreadValue(); renderKeyControls();
}
function renderEnvironment(env) {
  const editionChanged=state.environment.edition!==env.edition;
  state.environment=env;
  const cuda=!!env.cuda_enabled;
  show('cuda-amp-row',cuda); show('cuda-tf32-row',cuda);
  show('cuda-batch-size',cuda); show('batch-size',!cuda);
  $('cuda-batch-size').disabled=!cuda; $('batch-size').disabled=cuda;
  $('cuda-device-option').hidden=!cuda; $('cuda-device-option').disabled=!cuda;
  document.querySelector('label[for="batch-size"],label[for="cuda-batch-size"]').htmlFor=cuda?'cuda-batch-size':'batch-size';
  if(editionChanged)restoreInputs();
  renderAdapters();
  $('cpu-threads').max=env.cpu_logical_count||24; renderThreadValue();
  $('hardware-label').textContent=env.loading?tr("Detecting device…"):env.error?tr("Environment error"):env.device;
  $('hardware-dot').classList.toggle('offline',!!env.error);
  const rows=[[tr("Compute device"),env.device||tr("Detecting")],[tr("VRAM"),env.vram_gb?`${env.vram_gb} GB`:'—'],[tr("Video decoder"),env.av?`PyAV ${env.av}`:'—'],['Python',env.python||'—'],[tr("Portable runtime"),env.portable?tr("Enabled"):env.loading?tr("Detecting"):tr("Disabled")]];
  if(env.cuda_enabled)rows.push(['PyTorch',env.torch||'—'],[tr("CUDA runtime"),env.cuda_version||'—']);
  rows.push(['ONNX Runtime / DirectML',env.directml?.version||'—'],[tr("DirectML adapter"),(env.directml?.adapters||[]).map(a=>a.name).join(', ')||tr("No compatible GPU detected")]);
  $('environment-list').innerHTML=rows.map(([k,v])=>`<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join('')+(env.error?`<div><dt>${tr("Error")}</dt><dd>${escapeHtml(env.error)}</dd></div>`:'');
}
function renderAdapters() {
  const el=$('directml-adapter');
  const selected=el.dataset.dirty==='true'?Number(el.value):(state.settings.directml_adapter??-1);
  const entries=[{id:-1,name:tr("Auto select")}].concat(state.environment.directml?.adapters||[]);
  if(selected>=0&&!entries.some(a=>a.id===selected))entries.push({id:selected,name:`${selected} · ${tr("No compatible GPU detected")}`});
  el.replaceChildren(...entries.map(a=>{const option=document.createElement('option');option.value=a.id;option.textContent=a.name;return option;}));
  el.value=String(selected);
  el.disabled=!['auto','directml'].includes($('device-select').value);
  $('directml-precision').disabled=el.disabled;
}
$('directml-adapter').addEventListener('change',()=>{$('directml-adapter').dataset.dirty='true';});
$('device-select').addEventListener('change',renderAdapters);
function setConnected(ok) {
  state.connected=ok; if(!ok)elapsedClock.pause(); show('connection-banner',!ok); $('connection-dot').classList.toggle('offline',!ok);
  $('connection-label').textContent=ok?tr("Connected"):tr("Disconnected"); updateControls();
}
function updateControls() {
  ['start-inference'].forEach(id=>$(id).disabled=!!state.active||!state.connected||!!state.environment.error||state.environment.loading||pendingStart);
  show('active-task',!!state.active);
  $('active-task-label').textContent=tr("Inference running");
}
async function loadVideo() {
  const path=$('video-path').value.trim(); if(!path) return toast(tr("Select a video file first."),true);
  const button=$('load-video'); button.disabled=true; $('video-meta').textContent=tr("Decoding first frame…");
  try {
    const info=await api('/api/video',{path}); state.video=info; state.videoPath=path;
    show('empty-preview',false); show('video-preview'); show('preview-caption'); $('video-preview').src=info.preview;delete $('video-preview').dataset.previewKey;
    renderVideoMeta();
    $('preview-caption-text').textContent=tr("First frame");
    remember();
  } catch(error) { state.video=null; state.videoPath=''; $('video-meta').textContent=tr("Failed to load video"); toast(error.message,true); }
  finally {button.disabled=false;}
}
$('load-video').addEventListener('click',loadVideo);
$('video-path').addEventListener('change',()=> { state.video=null; state.videoPath=''; });
document.querySelectorAll('[data-pick]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;
  try { const result=await api('/api/pick',{kind:button.dataset.kind,language:I18n.language}); if(result.path) {$(button.dataset.pick).value=result.path; remember(); if(button.dataset.pick==='video-path') await loadVideo(); if(button.dataset.pick==='score-directory')await loadScores(); if(button.dataset.pick==='convert-directory')await loadConvertScores(); if(button.dataset.pick==='library-directory')await loadLibrary();} }
  catch(error) {toast(error.message,true);} finally {button.disabled=false;}
}));
async function startJob(kind,config) {
  if(state.active||pendingStart) return;
  pendingStart=true; updateControls();
  try {
    const job=await api('/api/jobs',{kind,...config}); state.active=job.id; state.current=job; elapsedClock.sync(job);if(!state.connected)elapsedClock.pause();
    if(kind==='inference') keyNames.forEach(k=>$(`key-${k}`).classList.remove('pressed'));
    renderJob(job); remember(); toast(tr("Inference started"));
  } catch(error) {toast(error.message,true);} finally {pendingStart=false; updateControls();}
}
$('inference-form').addEventListener('submit',event=>{
  event.preventDefault();
  startJob('inference',{...state.settings,video_path:$('video-path').value,output_dir:$('output-dir').value,
    threshold:Number($('threshold').value),batch_size:Number($(state.environment.cuda_enabled?'cuda-batch-size':'batch-size').value),stride:Number($('stride').value),min_size:Number($('infer-min-size').value),amp:$('infer-amp').checked,debounce_ms:Number($('debounce-ms').value)});
});
['stop-inference'].forEach(id=>$(id).addEventListener('click',async()=>{
  if(!state.current) return;
  try {renderJob(await api('/api/stop',{id:state.current.id})); toast(tr("Stop requested. Waiting for the current batch."));}
  catch(error) {toast(error.message,true);}
}));
$('active-task').addEventListener('click',async()=>{
  if(state.active) {state.current=await api(`/api/jobs/${state.active}`); page(state.current.kind); renderJob(state.current);}
});
function renderProgress(prefix,job) {
  const percent=job.progress==null?null:Math.max(0,Math.min(100,job.progress*100));
  const running=['running','stopping'].includes(job.status);
  $(`${prefix}-progress`).style.width=`${percent??0}%`;
  $(`${prefix}-progress`).parentElement.classList.toggle('indeterminate',percent===null&&running);
  $(`${prefix}-progress-label`).textContent=percent===null?tr("Frame count unknown"):`${percent.toFixed(1)}%`;
  $(`${prefix}-stage`).textContent=message(job.stage);
  show(`${prefix}-error`,!!job.error); $(`${prefix}-error`).textContent=message(job.error);
  const log=$(`${prefix}-logs`); const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<50;
  log.innerHTML=(job.logs||[]).map(row=>`<div><time>${escapeHtml(row.time)}</time>${escapeHtml(row.message)}</div>`).join('');
  if(atBottom) log.scrollTop=log.scrollHeight;
  show(`${prefix}-log-panel`);
}
function renderArtifacts(container,job) {
  const expanded=container.querySelector('details')?.open||false;
  container.replaceChildren();
  if(job.kind==='inference'&&['running','stopping'].includes(job.status))return;
  const artifacts=job.artifacts||[];
  const link=artifact=>{
    const a=document.createElement('a'); a.className='secondary'; a.href=`/api/jobs/${encodeURIComponent(job.id)}/files/${encodeURIComponent(artifact.name)}`;
    a.innerHTML=icon('download'); a.append(document.createTextNode(job.kind==='inference'&&artifact.name.endsWith('.txt')?tr("Download TXT"):message(artifact.label)));
    a.download=artifact.name; a.title=artifact.name; return a;
  };
  if(job.kind==='inference') {
    const txt=artifacts.find(a=>a.name.endsWith('.txt'));
    if(txt) {
      const button=document.createElement('button'); button.className='primary'; button.type='button'; button.innerHTML=icon('keyboard'); button.append(tr("Load in simulator"));
      button.onclick=async()=>{
        uploadedScore=null; $('score-directory').value=job.config.output_dir; scoresDirectory=job.config.output_dir;
        page('simulator',false); await loadScores();
        const file=scores.find(f=>f.name===txt.name&&f.path.replaceAll('\\','/')===`${job.output_dir}/${txt.name}`.replaceAll('\\','/'));
        if(file)$('score-select').value=file.path;
        else {uploadedScore={path:`${job.output_dir}/${txt.name}`,name:txt.name}; $('score-select').value=''; $('score-file').textContent=txt.name;}
      };
      container.append(button);
    }
    const others=artifacts.filter(a=>a!==txt);
    if(others.length) {
      const details=document.createElement('details'); details.className='other-downloads'; details.open=expanded;
      const summary=document.createElement('summary'); summary.textContent=tr("Other files"); summary.insertAdjacentHTML('beforeend',icon('chevron')); details.append(summary);
      const group=document.createElement('div'); others.forEach(a=>group.append(link(a))); details.append(group); container.append(details);
    }
  } else artifacts.forEach(a=>container.append(link(a)));
  if(job.artifacts?.length) {
    const button=document.createElement('button'); button.className='secondary'; button.type='button'; button.innerHTML=icon('folder'); button.append(tr("Open folder")); button.onclick=()=>api('/api/open-output',{id:job.id}).catch(e=>toast(e.message,true)); container.append(button);
  }

}
function renderJob(job) {
  if(job.kind!=='inference'||deletedJobIds.has(job.id))return;
  state.current=job; elapsedClock.sync(job);if(!state.connected)elapsedClock.pause();
  const running=['running','stopping'].includes(job.status);
  if(running) state.active=job.id;
  else if(state.active===job.id) state.active=null;
  const m=job.metrics||{};
  if(job.kind==='inference') {
    show('inference-job'); renderProgress('infer',job); show('stop-inference',running); $('stop-inference').disabled=job.status==='stopping';
    $('inference-device').textContent=m.device?`${m.device.toUpperCase()} · ${m.device_name||''} · ${m.precision||''} · batch ${m.batch_size||1}`:'';
    $('metric-frames').textContent=m.processed_frames?.toLocaleString()??'—'; $('metric-fps').textContent=m.fps??'—'; $('metric-events').textContent=m.key_events??'—'; renderElapsed(); $('infer-eta').textContent=running?(m.eta!=null?tr("ETA {time}",{time:duration(m.eta)}):tr("Preparing")):tr(statuses[job.status]||job.status);
    renderKeyControls(m.pressed||[]);
    $('keyboard-footnote').textContent=m.video_time!=null?tr("Video time {time} · Last processed frame",{time:timecode(m.video_time)}):tr("Waiting for detections");
    if(job.has_preview) {show('empty-preview',false); show('video-preview'); show('preview-caption'); const previewKey=`${job.id}:${job.preview_version??m.processed_frames??'saved'}`; if($('video-preview').dataset.previewKey!==previewKey){$('video-preview').src=`/api/jobs/${encodeURIComponent(job.id)}/preview?v=${encodeURIComponent(previewKey)}`;$('video-preview').dataset.previewKey=previewKey;} $('preview-caption-text').textContent=tr("Video frame · {time}",{time:timecode(m.video_time)});}
    renderVideoMeta();
    const events=job.events||[]; show('events-empty',!events.length); show('events-table',!!events.length);
    $('events-body').innerHTML=[...events].reverse().map(e=>`<tr><td>${timecode(e.time)}</td><td>${e.keys.map(k=>`<span class="event-key">${escapeHtml(k)}</span>`).join('')}</td></tr>`).join('');
    renderArtifacts($('infer-artifacts'),job);
  }
  updateControls();
}
async function loadHistory() {
  try {
    const jobs=await api('/api/jobs'); $('history-count').textContent=jobs.length; const list=$('history-list'); list.replaceChildren();
    if(!jobs.length) {list.innerHTML=`<div class="history-empty">${tr("No jobs")}</div>`;return;}
    for(const job of jobs) {
      const row=document.createElement('div'); row.className='history-row';
      row.innerHTML=`<div class="history-icon">${icon('scan')}</div><div class="history-info"><strong title="${escapeHtml(job.video||'')}">${escapeHtml(job.video||tr("Inference"))}</strong><p>${escapeHtml(job.created_at.replace('T',' '))} · ${duration(job.elapsed)}</p></div><span class="status-tag ${escapeHtml(job.status)}">${escapeHtml(tr(statuses[job.status]||job.status)||job.status)}</span>`;
      const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=tr("View results");button.onclick=async()=>{try {const detail=await api(`/api/jobs/${job.id}`);page(detail.kind);renderJob(detail);}catch(error){toast(error.message,true);}};row.append(button);list.append(row);
    }
  } catch(error) {toast(error.message,true);}
}
$('refresh-history').addEventListener('click',loadHistory);
$('settings-form').addEventListener('submit',async event=>{
  event.preventDefault();
  try {const saved=await api('/api/settings',{model_path:$('default-model').value.trim(),device:$('device-select').value,directml_adapter:Number($('directml-adapter').value),directml_precision:$('directml-precision').value,tf32:$('tf32').checked,cpu_threads:Number($('cpu-threads').value)});$('directml-adapter').dataset.dirty='false';applySettings(saved);toast(tr("Settings saved. Applied to the next job."));}
  catch(error){toast(error.message,true);}
});
let keySaveChain=Promise.resolve(),keyRevision=0;
function renderThreadValue(){ const n=Number($('cpu-threads').value);$('cpu-threads-value').textContent=n?String(n):tr("Auto ({count})",{count:state.environment.cpu_logical_count||$('cpu-threads').max}); }
$('cpu-threads').addEventListener('input',renderThreadValue);
$('video-preview').addEventListener('load',()=>{const img=$('video-preview');if(img.naturalWidth&&img.naturalHeight){$('preview-stage').style.aspectRatio=`${img.naturalWidth} / ${img.naturalHeight}`;$('preview-stage').style.minHeight='0';}});
function renderKeyControls(pressed=state.current?.metrics?.pressed||[]){
  const disabled=state.settings.disabled_keys||[];
  for(const key of keyNames){const el=$(`key-${key}`),off=disabled.includes(key);el.classList.toggle('disabled-key',off);el.classList.toggle('pressed',!off&&pressed.includes(key));el.setAttribute('aria-pressed',String(!off));el.title=tr(off?"Enable {key}":"Disable {key}",{key});}
}
function toggleKey(key){
  const previous=[...(state.settings.disabled_keys||[])];
  const disabled=previous.includes(key)?previous.filter(k=>k!==key):[...previous,key];
  state.settings.disabled_keys=disabled;renderKeyControls();const revision=++keyRevision;
  keySaveChain=keySaveChain.then(async()=>{try{await api('/api/settings',{disabled_keys:disabled});}catch(error){if(revision===keyRevision){state.settings.disabled_keys=previous;renderKeyControls();}toast(error.message,true);}});
}
let editing=null,regionImage=null,dragStart=null;
function regionLocked(){return $('region-select').value!=='roi'&&(editing.disabled_keys||[]).includes($('region-select').value);}
function expandROI(){if($('region-select').value!=='roi')editing.roi=RegionGeometry.union(editing.roi,currentRect());}

function currentRect(){return $('region-select').value==='roi'?editing.roi:editing.regions[$('region-select').value];}
function replaceRect(rect){if($('region-select').value==='roi') editing.roi=rect; else editing.regions[$('region-select').value]=rect;}
function syncRectInputs(){currentRect().forEach((v,i)=>{const el=$(['region-x1','region-y1','region-x2','region-y2'][i]);el.value=Math.round(v);el.disabled=regionLocked();});}
function drawRegions(){
  if(!editing||!regionImage)return;const canvas=$('region-canvas'),ctx=canvas.getContext('2d');const[w,h]=editing.reference_size;canvas.width=w;canvas.height=h;ctx.drawImage(regionImage,0,0,w,h);
  const chosen=$('region-select').value;const draw=(rect,label,selected)=>{const off=(editing.disabled_keys||[]).includes(label);ctx.setLineDash(off?[8,6]:[]);ctx.strokeStyle=off?'#777777':selected?'#ffb17d':label==='roi'?'#f2df9d':'#9bbea4';ctx.lineWidth=selected?5:2;ctx.strokeRect(rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1]);ctx.font=`${Math.max(14,w/80)}px "Segoe UI",sans-serif`;ctx.fillStyle=ctx.strokeStyle;ctx.fillText(label==='roi'?'ROI':label,rect[0]+5,rect[1]+Math.max(19,w/70));};
  draw(editing.roi,'roi',chosen==='roi');for(const[key,rect]of Object.entries(editing.regions))draw(rect,key,chosen===key);
}
async function openRegionEditor(move=false){
  if(!state.video||state.videoPath!==$('video-path').value.trim())await loadVideo();if(!state.video)return;
  const cfg=structuredClone(state.settings); const sx=state.video.width/cfg.reference_size[0],sy=state.video.height/cfg.reference_size[1];const scale=r=>r.map((v,i)=>Math.round(v*(i%2?sy:sx)));
  editing={disabled_keys:[...(cfg.disabled_keys||[])],reference_size:[state.video.width,state.video.height],roi:scale(cfg.roi),regions:Object.fromEntries(Object.entries(cfg.regions).map(([k,r])=>[k,scale(r)]))};
  for(const k of keyNames)$('region-select').querySelector(`option[value="${k}"]`).disabled=editing.disabled_keys.includes(k);
  if(move){$('region-mode').value='move';$('region-select').value=keyNames.find(k=>!editing.disabled_keys.includes(k))||'roi';}
  if(regionLocked())$('region-select').value='roi';
  regionImage=new Image();regionImage.onload=()=>{drawRegions();syncRectInputs();};regionImage.src=state.video.preview;
  $('region-resolution').textContent=`${editing.reference_size.join(' × ')} px`; $('region-dialog').showModal();
}
$('edit-regions').addEventListener('click',()=>openRegionEditor());
$('move-regions').addEventListener('click',()=>openRegionEditor(true));
$('close-regions').addEventListener('click',()=>$('region-dialog').close());
$('region-select').addEventListener('change',()=>{syncRectInputs();drawRegions();});
function pointerPoint(event){const rect=$('region-canvas').getBoundingClientRect();return [Math.max(0,Math.min(editing.reference_size[0],Math.round((event.clientX-rect.left)/rect.width*editing.reference_size[0]))),Math.max(0,Math.min(editing.reference_size[1],Math.round((event.clientY-rect.top)/rect.height*editing.reference_size[1])))];}
$('region-canvas').addEventListener('pointerdown',event=>{
  if(!editing||event.button!==0)return;const point=pointerPoint(event);
  if($('region-mode').value==='move'){
    const hit=RegionGeometry.hit(editing.regions,editing.disabled_keys||[],point,$('region-select').value);
    if(hit)$('region-select').value=hit;
    else if($('region-select').value!=='roi'||!RegionGeometry.contains(editing.roi,point))return;
  }
  if(regionLocked())return;
  dragStart={point,rect:[...currentRect()]};$('region-canvas').setPointerCapture(event.pointerId);syncRectInputs();drawRegions();
});
$('region-canvas').addEventListener('pointermove',event=>{
  if(!dragStart)return;const end=pointerPoint(event),start=dragStart.point;
  replaceRect($('region-mode').value==='move'?RegionGeometry.move(dragStart.rect,end[0]-start[0],end[1]-start[1],...editing.reference_size):[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])]);drawRegions();syncRectInputs();
});
['pointerup','pointercancel'].forEach(name=>$('region-canvas').addEventListener(name,()=>{if(!dragStart)return;const r=currentRect();if(name==='pointercancel'||r[2]<=r[0]||r[3]<=r[1])replaceRect(dragStart.rect);else expandROI();dragStart=null;syncRectInputs();drawRegions();}));
$('region-mode').addEventListener('change',()=>{dragStart=null;});
['region-x1','region-y1','region-x2','region-y2'].forEach(id=>$(id).addEventListener('change',()=>{if(regionLocked())return;const r=['region-x1','region-y1','region-x2','region-y2'].map(id=>Number($(id).value));if(r.every(Number.isFinite)&&r[0]>=0&&r[1]>=0&&r[2]>r[0]&&r[3]>r[1]&&r[2]<=editing.reference_size[0]&&r[3]<=editing.reference_size[1]){replaceRect(r);expandROI();}syncRectInputs();drawRegions();}));
$('reset-regions').addEventListener('click',()=>{
  const raw={Q:[398,608,519,736],W:[564,609,687,736],E:[737,610,854,735],R:[902,611,1021,736],T:[1073,614,1189,738],Y:[1235,612,1357,740],U:[1402,615,1524,739],A:[398,750,520,872],S:[568,751,687,875],D:[736,747,858,867],F:[900,753,1022,870],G:[1073,752,1185,871],H:[1236,751,1358,872],J:[1400,751,1520,870],Z:[397,883,519,1002],X:[569,885,686,1006],C:[734,880,857,1003],V:[901,882,1019,1005],B:[1073,882,1193,1008],N:[1236,881,1358,1009],M:[1400,880,1522,1008]};
  const scale=r=>r.map((v,i)=>Math.round(v*editing.reference_size[i%2]/[1920,1080][i%2]));editing.roi=scale([350,550,1550,1020]);editing.regions=Object.fromEntries(Object.entries(raw).map(([k,r])=>[k,scale(r)]));syncRectInputs();drawRegions();
});
$('save-regions').addEventListener('click',async()=>{try{const {disabled_keys,...layout}=editing;applySettings(await api('/api/settings',layout));$('region-dialog').close();toast(tr("Regions saved"));}catch(error){toast(error.message,true);}});
async function poll(){
  if(state.polling)return;state.polling=true;
  try {
    const status=await api('/api/status');
    if(!state.connected){const boot=await api('/api/bootstrap');state.token=boot.token;applySettings(boot.settings);}
    renderEnvironment(status.environment);setConnected(true);
    const before=state.active;state.active=status.active;
    if(state.current&&(['running','stopping'].includes(state.current.status)||state.current.id===before)){
      const currentId=state.current.id;let job;
      try{job=await api(`/api/jobs/${currentId}`);}catch(error){if(deletedJobIds.has(currentId))return;throw error;}
      if(deletedJobIds.has(currentId))return;renderJob(job);
      if(!['running','stopping'].includes(job.status)&&before) {toast(job.status==='completed'?tr("Job completed. Results saved."):job.error||tr("Job stopped"),job.status==='failed');loadHistory();}
    }else if(state.active&&!state.current){renderJob(await api(`/api/jobs/${state.active}`));}
    updateControls();
  }catch{setConnected(false);}finally{state.polling=false;setTimeout(poll,state.connected?1100:3000);}
}
async function init(){
  try{const data=await api('/api/bootstrap');state.token=data.token;applySettings(data.settings);renderEnvironment(data.environment);state.active=data.active;setConnected(true);restoreInputs(); page(location.hash.slice(1)||'inference');if(data.active){const job=await api(`/api/jobs/${data.active}`);page(job.kind);renderJob(job);}loadHistory();}
  catch(error){setConnected(false);toast(error.message,true);}finally{poll();}
}

function renderVideoMeta() {
  const info=state.video;
  const jobVideo=state.current?.has_preview?basename(state.current.config?.video_path):'';
  $('video-meta').textContent=info?`${info.width} × ${info.height} / ${info.fps.toFixed(2)} fps${info.duration?' / '+duration(info.duration):''}`:jobVideo||tr("Not loaded");
}
function renderLanguageToggle() {
  $('language-toggle').textContent=window.LANGUAGE_NAMES[I18n.language==='zh'?'en':'zh'];
  $('language-toggle').setAttribute('aria-label',I18n.language==='zh'?'Switch to English':tr('Switch to Chinese'));
}
function renderScores() {
  const select=$('score-select'), previous=select.value; select.replaceChildren();
  const empty=document.createElement('option'); empty.value=''; empty.textContent=tr(scores.length?"Select TXT":"No TXT files in this directory"); select.append(empty);
  for(const file of scores){const option=document.createElement('option'); option.value=file.path; option.textContent=file.relative; select.append(option);}
  if(scores.some(file=>file.path===previous))select.value=previous;
  else if(!uploadedScore&&scores.length)select.value=scores[0].path;
  $('score-file').textContent=uploadedScore?.name||'';
}
async function loadScores() {
  $('refresh-scores').disabled=true;
  const directory=$('score-directory').value.trim()||$('output-dir').value;
  try {const result=await api('/api/simulator/files',{directory}); scores=result.files; scoresDirectory=directory; renderScores();}
  catch(error){toast(error.message,true);}finally{$('refresh-scores').disabled=false;}
}
$('refresh-scores').addEventListener('click',loadScores);
$('score-directory').addEventListener('change',loadScores);
$('score-select').addEventListener('change',()=>{uploadedScore=null; $('score-file').textContent=''; $('score-upload').value=''; show('simulator-result',false);});
$('score-upload').addEventListener('change',async()=>{
  const file=$('score-upload').files[0]; if(!file)return;
  if(!file.name.toLowerCase().endsWith('.txt')||file.size>8*1024*1024){$('score-upload').value='';return toast(tr("Select a TXT file no larger than 8 MiB."),true);}
  $('launch-simulator').disabled=true;
  try {
    const content=await new Promise((resolve,reject)=>{const reader=new FileReader(); reader.onload=()=>resolve(reader.result.split(',')[1]); reader.onerror=()=>reject(new Error('Cannot read TXT.')); reader.readAsDataURL(file);});
    uploadedScore=await api('/api/simulator/upload',{name:file.name,content}); $('score-select').value=''; $('score-file').textContent=uploadedScore.name; show('simulator-result',false);
  }catch(error){toast(error.message,true);}finally{$('launch-simulator').disabled=false; $('score-upload').value='';}
});
$('launch-simulator').addEventListener('click',async()=>{
  const button=$('launch-simulator'); button.disabled=true;
  $('simulator-result').textContent=tr("Confirm administrator access in the Windows prompt."); show('simulator-result');
  try {
    await api('/api/simulator/launch',{directory:$('score-directory').value,score:uploadedScore?.path||$('score-select').value||null,language:I18n.language});
    $('simulator-result').textContent=tr('Simulator opened.');
  }catch(error){$('simulator-result').textContent=message(error.message);}finally{button.disabled=false;}
});


let convertInitialized=false,convertFiles=[],convertUpload=null,convertedName='score_formatted.txt',convertRevision=0;
function invalidateConversion(){ convertRevision++;$('download-converted').disabled=true;$('converted-text').value='';$('convert-stats').textContent=''; }
function renderConvertScores(){
  const select=$('convert-select'),previous=select.value;select.replaceChildren();
  const empty=document.createElement('option');empty.value='';empty.textContent=tr(convertFiles.length?"Select TXT":"No TXT files in this directory");select.append(empty);
  for(const file of convertFiles){const option=document.createElement('option');option.value=file.path;option.textContent=file.relative;select.append(option);}
  if(convertFiles.some(f=>f.path===previous))select.value=previous;else if(!convertUpload&&convertFiles.length)select.value=convertFiles[0].path;
}
async function loadConvertScores(){
  $('refresh-convert').disabled=true;
  try{const result=await api('/api/simulator/files',{directory:$('convert-directory').value});convertFiles=result.files;renderConvertScores();}
  catch(error){toast(error.message,true);}finally{$('refresh-convert').disabled=false;}
}
$('refresh-convert').addEventListener('click',loadConvertScores);
$('convert-directory').addEventListener('change',()=>{invalidateConversion();loadConvertScores();});
$('convert-select').addEventListener('change',()=>{convertUpload=null;$('convert-file').textContent='';$('convert-upload').value='';invalidateConversion();});
$('convert-upload').addEventListener('change',()=>{
  const file=$('convert-upload').files[0];if(!file)return;
  if(file.size>8*1024*1024||!file.name.toLowerCase().endsWith('.txt')){toast(tr("Select a TXT file no larger than 8 MiB."),true);$('convert-upload').value='';return;}
  convertUpload=file;$('convert-file').textContent=file.name;$('convert-select').value='';invalidateConversion();
});
['convert-format','convert-bpm','convert-beats','convert-denominator','convert-start','convert-line'].forEach(id=>$(id).addEventListener('input',invalidateConversion));
$('convert-score').addEventListener('click',async()=>{
  const file=convertUpload,path=$('convert-select').value;
  if(!file&&!path)return toast(tr("Select TXT"),true);
  $('convert-score').disabled=true;invalidateConversion();const revision=convertRevision;
  try{
    const data={format:$('convert-format').value,bpm:Number($('convert-bpm').value),beats:Number($('convert-beats').value),denominator:Number($('convert-denominator').value),start:Number($('convert-start').value),bars_per_line:Number($('convert-line').value),debounce_ms:Number($('debounce-ms').value)};
    if(file){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));data.content=btoa(binary);data.name=file.name;}else data.path=path;
    const result=await api('/api/score/convert',data);if(revision!==convertRevision)return;$('converted-text').value=result.text;convertedName=result.name;$('download-converted').disabled=false;
    $('convert-stats').textContent=tr("{events} events · {bars} bars",{events:result.events,bars:result.bars});
  }catch(error){toast(error.message,true);}finally{$('convert-score').disabled=false;}
});
$('download-converted').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([$('converted-text').value],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=convertedName;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

function clearCurrentJob() {
  state.current=null;elapsedClock.reset();renderElapsed();
  ['inference-job','infer-log-panel','events-table','video-preview','preview-caption'].forEach(id=>show(id,false));
  show('empty-preview');show('events-empty');
  $('events-body').replaceChildren();$('infer-artifacts').replaceChildren();$('infer-logs').replaceChildren();
  $('inference-device').textContent='';$('keyboard-footnote').textContent='';renderVideoMeta();
  $('video-preview').removeAttribute('src');delete $('video-preview').dataset.previewKey;
  renderKeyControls();updateControls();
}

let libraryInitialized=false,libraryFiles=[],libraryDirectory='',libraryRevision=0,libraryBusy=false;
const librarySelection=new Map();
function visibleLibraryFiles() {
  const query=$('library-search').value.trim().toLocaleLowerCase();
  return libraryFiles.filter(file=>`${file.name} ${file.relative}`.toLocaleLowerCase().includes(query));
}
function renderLibrary() {
  const files=visibleLibraryFiles(),container=$('library-files');container.replaceChildren();
  for(const file of files){
    const row=document.createElement('label');row.className='library-row';
    const check=document.createElement('input');check.type='checkbox';check.checked=librarySelection.has(file.path);check.disabled=libraryBusy;
    check.setAttribute('aria-label',tr("Select {name}",{name:file.name}));
    check.addEventListener('change',()=>{if(check.checked)librarySelection.set(file.path,file);else librarySelection.delete(file.path);updateLibrarySelection();});
    const info=document.createElement('span');info.className='library-info';
    const name=document.createElement('strong');name.textContent=file.name;
    const path=document.createElement('small');path.textContent=file.relative;
    info.append(name,path);
    const meta=document.createElement('span');meta.className='library-meta';
    const date=document.createElement('time');date.dateTime=new Date(file.modified*1000).toISOString();date.textContent=new Date(file.modified*1000).toLocaleString(I18n.language==='zh'?'zh-CN':'en-US');
    const size=document.createElement('small');size.textContent=file.bytes<1024?`${file.bytes} B`:`${(file.bytes/1024).toFixed(1)} KiB`;meta.append(date,size);
    row.append(check,info,meta);container.append(row);
  }
  if(!files.length){const empty=document.createElement('p');empty.className='history-empty';empty.textContent=tr(libraryBusy?"Loading…":'No matching output folders');container.append(empty);}
  updateLibrarySelection();
}
function updateLibrarySelection() {
  const files=visibleLibraryFiles(),selected=files.filter(file=>librarySelection.has(file.path)).length;
  $('library-all').checked=files.length>0&&selected===files.length;
  $('library-all').indeterminate=selected>0&&selected<files.length;
  $('library-all').disabled=libraryBusy||!files.length;
  $('library-count').textContent=tr('{total} folders · {selected} selected',{total:libraryFiles.length,selected:librarySelection.size});
  $('library-delete').disabled=libraryBusy||!librarySelection.size;
  $('library-directory').disabled=libraryBusy;
  document.querySelector('[data-pick="library-directory"]').disabled=libraryBusy;
  $('library-output').disabled=libraryBusy;$('library-uploads').disabled=libraryBusy;
}
async function loadLibrary() {
  if(libraryBusy)return;
  const revision=++libraryRevision;libraryBusy=true;librarySelection.clear();libraryFiles=[];renderLibrary();
  $('library-refresh').disabled=true;
  try{
    const result=await api('/api/scores/list',{directory:$('library-directory').value.trim()||$('output-dir').value});
    if(revision===libraryRevision){libraryDirectory=result.directory;libraryFiles=result.files;}
  }catch(error){toast(error.message,true);}
  finally{if(revision===libraryRevision){libraryBusy=false;$('library-refresh').disabled=false;renderLibrary();}}
}
$('library-refresh').addEventListener('click',loadLibrary);
$('library-directory').addEventListener('change',loadLibrary);
$('library-search').addEventListener('input',renderLibrary);
$('library-output').addEventListener('click',()=>{if(!libraryBusy){$('library-directory').value=$('output-dir').value;loadLibrary();}});
$('library-uploads').addEventListener('click',()=>{if(!libraryBusy){$('library-directory').value='scores';loadLibrary();}});
$('library-all').addEventListener('change',()=>{for(const file of visibleLibraryFiles()){if($('library-all').checked)librarySelection.set(file.path,file);else librarySelection.delete(file.path);}renderLibrary();});
$('library-delete').addEventListener('click',async()=>{
  const selected=[...librarySelection.values()];
  if(libraryBusy||!selected.length||!window.confirm(tr('Delete {count} selected folders and all their contents? This cannot be undone.',{count:selected.length})))return;
  libraryBusy=true;renderLibrary();
  try{
    const result=await api('/api/scores/delete',{directory:libraryDirectory,files:selected.map(({path,version})=>({path,version}))});
    const normalize=path=>path.replace(/\\/g,'/').toLowerCase().replace(/\/$/,'');
    const deleted=result.deleted.map(normalize);
    const removed=path=>deleted.some(folder=>normalize(path)===folder||normalize(path).startsWith(folder+'/'));
    scores=scores.filter(file=>!removed(file.path));convertFiles=convertFiles.filter(file=>!removed(file.path));
    if(uploadedScore&&removed(uploadedScore.path))uploadedScore=null;
    renderScores();renderConvertScores();invalidateConversion();
    for(const id of result.removed_jobs||[])deletedJobIds.add(id);
    if(state.current&&deletedJobIds.has(state.current.id))clearCurrentJob();
    await loadHistory();
    toast(tr(result.errors.length?'Deleted {count} folders; some folders could not be deleted':'Deleted {count} folders',{count:result.deleted.length}),!!result.errors.length);
  }catch(error){toast(error.message,true);}
  finally{libraryBusy=false;await loadLibrary();}
});

I18n.bind();
renderLanguageToggle();
renderVideoMeta();
$('preview-caption-text').textContent=tr("First frame");
$('language-toggle').addEventListener('click',()=>I18n.set(I18n.language==='zh'?'en':'zh'));
document.addEventListener('languagechange',()=>{
  renderLanguageToggle(); renderLibrary(); renderScores(); renderConvertScores(); renderThreadValue(); renderKeyControls();
  $('simulator-result').textContent=message($('simulator-result').textContent);
  $('breadcrumb').textContent=tr(pageLabels[state.page]);
  renderEnvironment(state.environment); setConnected(state.connected); renderVideoMeta();
  for(const key of keyNames)$('region-select').querySelector(`option[value="${key}"]`).textContent=tr("Key {key}",{key});
  $('preview-caption-text').textContent=tr("First frame");
  if(state.current)renderJob(state.current);
  if(state.connected)loadHistory(); show('toast',false);
});
init();
