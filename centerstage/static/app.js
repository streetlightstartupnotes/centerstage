import {CenterStatistics} from './statistics.js?v=lang-20261021';
import {frameIndexAt,canInterpolate,playbackWindow,timelineColors,timelineRects,identityColor} from './playback.js?v=lang-20261021';
import {t,trServer,setLanguage,onLanguage} from './i18n.js?v=icon-20261021';
const $ = id => document.getElementById(id);
const video = $('video'), canvas = $('overlay'), ctx = canvas.getContext('2d');
let job = null, frames = [], cursor = 0, selectedFile = null, wantedPlay = false, holding = false;
let generation = 0, currentFrame = null, labelTrack = null, uploadStarted = 0, firstPlayback = false;
let pollTimer, toastTimer, lastPanel = 0, renderBoxes = [], modelReady = false, waitAll = false;
let playPending=0,playAttempt=0;
let presentedTime=null;
let uploading=false;
let previewing=false;
let statistics=new CenterStatistics(),identityRevision='',showAllRanks=false,timelineDirty=true,timelineCache=document.createElement('canvas');
let panelSignature='',rankingSignature='';
const terminal = new Set(['complete','failed','cancelled','interrupted']);
const stateNames = () => ({queued:t('statusQueued'),analyzing:t('statusAnalyzing'),complete:t('statusComplete'),cancelled:t('statusCancelled'),interrupted:t('statusInterrupted'),failed:t('statusFailed')});
const peopleCount = n => n===1?t('onePerson'):n===2?t('twoPeople'):t('nPeople',{n});
const esc = str => String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = t => `${String(Math.floor(Math.max(0,t)/60)).padStart(2,'0')}:${String(Math.floor(Math.max(0,t)%60)).padStart(2,'0')}`;
const labelAt = (id,t=video.currentTime) => statistics.label(id,t);
const personName = (id,t=video.currentTime) => {const identity=statistics.identity(id,t);return identity.named?identity.name:'';};
const segmentNames = segment => [...new Set(segment.names.filter((name,i)=>segment.keys[i].startsWith('name:')))].join(' / ');
function syncStatistics(batch=null){
  const links=$('appearance-mode').checked?(job.appearance_links||{}):{};
  const revision=JSON.stringify([job.labels||{},job.annotations||[],links]);
  if(batch===null||revision!==identityRevision){statistics=new CenterStatistics(job.labels||{},job.annotations||[],links);statistics.append(frames);identityRevision=revision;}
  else {if(!batch.length)return;statistics.append(batch);}
  timelineDirty=true;rankingSignature='';panelSignature='';
}
function displayTime(){return !video.ended&&presentedTime!==null?presentedTime:video.currentTime;}
function rankingTime(){return $('ranking-scope').value==='analyzed'?confirmed():displayTime();}
function seekTo(t){if(!job)return;previewing=true;presentedTime=null;currentFrame=null;video.currentTime=Math.max(0,Math.min(job.video.duration,t));draw(video.currentTime);panels(video.currentTime);gate();}
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,5000); }
async function api(path, options={}) {
  const response=await fetch(path,options);
  if(response.status===204) return null;
  if(!response.ok) { const body=await response.json().catch(()=>({})); throw new Error(typeof body.detail==='string'?body.detail:t('requestFailed',{status:response.status})); }
  return response.json();
}
function message(title, detail='', actionable=false) {
  $('stage-message').hidden=false; $('stage-message-title').textContent=title; $('stage-message-detail').textContent=detail;
  $('resume').hidden=!actionable; $('stage-message').querySelector('.spinner').hidden=actionable || terminal.has(job?.status);
}
function stageReady() { $('stage-message').hidden=true; }
async function health() {
  try {
    const data=await api('/api/health');modelReady=data.model_status==='ready';
    $('engine-status').classList.toggle('ready',modelReady);
    $('engine-status').querySelector('span').textContent=modelReady?t('engineReady'):trServer(data.message);
    $('start').disabled=!modelReady||uploading;
    if(data.model_status==='failed') $('import-error').textContent=data.error || trServer(data.message);
  } catch { modelReady=false; $('engine-status').classList.remove('ready'); $('engine-status').querySelector('span').textContent=t('serverDown'); }
  setTimeout(health,2500);
}
function showTitle(){
  const el=$('video-title');
  if(document.activeElement===el) return;
  el.textContent=job?(job.title||job.filename):t('newJobTitle');
  el.contentEditable=job?'true':'false';
  el.setAttribute('aria-label', job?t('titleEditable'):t('titleLabel'));
}
let titleBefore='';
$('video-title').addEventListener('focus',()=>{titleBefore=$('video-title').textContent;});
$('video-title').addEventListener('keydown',event=>{
  if(event.key==='Enter'){event.preventDefault();event.currentTarget.blur();}
  if(event.key==='Escape'){event.preventDefault();event.currentTarget.textContent=titleBefore;event.currentTarget.blur();}
});
$('video-title').addEventListener('paste',event=>{
  event.preventDefault();
  const text=(event.clipboardData?.getData('text')||'').replace(/\s+/g,' ').trim();
  if(text) document.execCommand('insertText',false,text);
});
$('video-title').addEventListener('blur',()=>{saveTitle();});
async function saveTitle(){
  if(!job) return;
  const next=$('video-title').textContent.replace(/\s+/g,' ').trim();
  if(!next || next===(job.title||job.filename)){showTitle();return;}
  try{
    const saved=await api(`/api/jobs/${job.id}/title`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:next})});
    job.title=saved.title;
    showTitle();
    history();
  }catch(error){showTitle();toast(error.message);}
}
async function history() {
  try {
    const {jobs}=await api('/api/jobs');$('history-count').textContent=jobs.length;
    $('history').innerHTML=jobs.length?jobs.map(j=>`<div class="history-item ${j.id===job?.id?'selected':''}"><button class="history-open" data-job="${j.id}"><strong>${esc(j.title||j.filename)}</strong><small>${stateNames()[j.status]||t('waiting')} · ${time(j.video.duration)}</small></button><button class="history-delete" data-delete="${j.id}" data-title="${esc(j.title||j.filename)}">${esc(t('delete'))}</button></div>`).join(''):`<p class="muted tiny">${esc(t('noHistory'))}</p>`;
    $('history').querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>loadJob(b.dataset.job));
    $('history').querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{$('delete-copy').textContent=t('deleteConfirm',{title:b.dataset.title});$('delete-form').dataset.id=b.dataset.delete;$('delete-dialog').showModal();});
  } catch {}
}
function clearJob(){
  generation++;clearTimeout(pollTimer);video.pause();wantedPlay=false;holding=false;firstPlayback=false;
  job=null;frames=[];currentFrame=null;renderBoxes=[];presentedTime=null;previewing=false;
  video.removeAttribute('src');video.load();
  $('empty').hidden=false;$('stage-message').hidden=true;showTitle();
  $('video-meta').textContent=t('metaEmpty');
  $('seek').disabled=true;$('play').disabled=true;$('export-json').disabled=$('export-csv').disabled=true;$('edit-roster').disabled=true;
  $('current-person').innerHTML=`<h2>—</h2><p>${esc(t('importToSee'))}</p>`;
  $('ranking').className='ranking-empty';$('ranking').textContent=t('noResults');
  $('analysis-status').textContent=t('waitingImport');$('analysis-metrics').textContent='';
  $('name-status').textContent=t('namesUnconfirmed');$('current-state').textContent=t('waitingFrame');
  const locationURL=new URL(location.href);locationURL.searchParams.delete('job');window.history.replaceState(null,'',locationURL);
}
$('delete-form').onsubmit=async e=>{
  e.preventDefault();
  const id=$('delete-form').dataset.id;if(!id)return;
  try{
    await api(`/api/jobs/${id}`,{method:'DELETE'});
    $('delete-dialog').close();
    if(localStorage.getItem('centerstage:last')===id) localStorage.removeItem('centerstage:last');
    if(job?.id===id) clearJob();
    toast(t('deleted'));
    history();
  }catch(error){toast(error.message);}
};
function selectFile(file) {
  if(!file)return;
  if(file.size>2*1024**3){toast(t('fileTooBig'));return;}
  selectedFile=file;$('selected-file').textContent=`${file.name} · ${(file.size/1024**2).toFixed(1)} MB`;
  $('import-error').textContent='';$('start').disabled=!modelReady;
  $('start').textContent=modelReady?t('startAnalysis'):t('waitModel');$('import-dialog').showModal();
}
$('file').onchange=()=>selectFile($('file').files[0]);
for(const id of ['choose-file','upload-top']) $(id).onclick=()=>{$('file').value='';$('file').click();};
$('new-task').onclick=()=>{ $('file').value='';$('file').click(); };
$('stage').ondragover=e=>{e.preventDefault();$('stage').classList.add('dragging');};
$('stage').ondragleave=()=>$('stage').classList.remove('dragging');
$('stage').ondrop=e=>{e.preventDefault();$('stage').classList.remove('dragging');selectFile(e.dataTransfer.files[0]);};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('about').onclick=()=>$('about-dialog').showModal();
$('import-form').onsubmit=async e=>{
  e.preventDefault();if(!selectedFile || !modelReady || uploading)return;
  uploading=true;
  const form=new FormData();form.append('file',selectedFile);form.append('source_url',$('source').value.trim());
  form.append('group_id',$('group').value);
  form.append('mode',new FormData(e.target).get('mode'));form.append('analysis_fps',$('fps').value);form.append('tracker',$('tracker').value);
  $('start').disabled=true;uploadStarted=performance.now();
  try {
    const result=await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();xhr.open('POST','/api/jobs');xhr.responseType='json';xhr.timeout=600000;
      xhr.upload.onprogress=e=>{if(e.lengthComputable)$('start').textContent=t('importing',{n:Math.round(e.loaded/e.total*100)});};
      xhr.onerror=()=>reject(new Error(t('uploadBroken')));
      xhr.ontimeout=()=>reject(new Error(t('uploadTimeout')));
      xhr.onload=()=>xhr.status===201?resolve(xhr.response):reject(new Error(typeof xhr.response?.detail==='string'?xhr.response.detail:t('cannotImport')));
      xhr.send(form);
    });
    $('import-dialog').close();await loadJob(result.id,true);history();
  }catch(error){$('import-error').textContent=error.message;}
  finally{uploading=false;$('start').disabled=!modelReady;$('start').textContent=t('startAnalysis');}
};
async function loadJob(id, autoplay=false) {
  if(!autoplay)uploadStarted=0;
  const serial=++generation;clearTimeout(pollTimer);video.pause();wantedPlay=autoplay;holding=false;firstPlayback=false;waitAll=false;playPending=0;
  job=null;frames=[];currentFrame=null;renderBoxes=[];presentedTime=null;previewing=false;
  $('current-person').innerHTML=`<h2>—</h2><p>${esc(t('reading'))}</p>`;$('ranking').textContent=t('reading');
  const loaded=await api(`/api/jobs/${id}`).catch(e=>{toast(e.message);return null;});
  if(!loaded || serial!==generation)return;
  job=loaded;frames=[];cursor=0;currentFrame=null;showAllRanks=false;syncStatistics();localStorage.setItem('centerstage:last',id);const locationURL=new URL(location.href);locationURL.searchParams.set('job',id);window.history.replaceState(null,'',locationURL);
  video.dataset.bufferPauses='0';delete video.dataset.firstPlaySeconds;
  video.src=`/api/jobs/${id}/video`;video.load();$('empty').hidden=true;
  showTitle();$('video-meta').textContent=`${job.video.width} × ${job.video.height} · ${Math.round(job.video.fps)} FPS`;
  $('seek').max=job.video.duration;$('seek').value=0;$('seek').disabled=false;$('play').disabled=false;
  $('export-json').disabled=$('export-csv').disabled=false;
  $('edit-roster').disabled=false;
  message(t('reading'));history();await poll(serial);
}
async function poll(serial) {
  if(!job || serial!==generation)return;
  let delay=500;
  try {
    const data=await api(`/api/jobs/${job.id}/frames?after=${cursor}`);
    if(serial!==generation)return;
    const previousStatus=job.status;
    frames.push(...data.frames);cursor=data.next;job=data.job;syncStatistics(data.frames);
    if(previousStatus!==job.status)history();
    delay=data.total>cursor?10:terminal.has(job.status)?2000:400;
    updateStatus();gate();
  }catch(error){if(serial===generation){$('analysis-status').textContent=t('reconnecting');delay=2000;}}
  if(serial===generation)pollTimer=setTimeout(()=>poll(serial),delay);
}
function confirmed() { return frames.length?frames[frames.length-1].end:0; }
function updateStatus() {
  const names=job.name_status;
  $('name-status').textContent=names?[trServer(names.message),trServer(names.note)].filter(Boolean).join(' '):t('namesNotConfirmed');
  $('analyzed-bar').style.width=`${Math.min(100,confirmed()/job.video.duration*100)}%`;
  $('analysis-status').textContent=trServer(job.message);
  $('analysis-metrics').textContent=t('analyzed',{done:time(job.confirmed_until),total:time(job.video.duration)})+(job.speed?t('speed',{speed:job.speed.toFixed(2)}):'');
  $('cancel').hidden=terminal.has(job.status);
  $('wait-all').hidden=terminal.has(job.status)||waitAll||job.mode==='complete'||!(job.speed<1 && job.elapsed>10);
  $('analysis-dot').style.background=job.status==='failed'?'#f0a58d':'var(--green)';
  if(job.source_task==='pending') $('source-status').textContent=t('waitAgentRoster');
  else if(job.roster?.length) $('source-status').innerHTML=`${esc(t('rosterVerified',{n:job.roster.length}))}<a class="source-link" href="${esc(job.roster[0].source)}" target="_blank" rel="noopener noreferrer">${esc(t('viewSource'))}</a><br>`;
  else $('source-status').textContent='';
  $('source-status').append(document.createTextNode(job.annotation_pending?t('annotationPending'):job.annotation_status==='unresolved'?t('annotationUnresolved',{note:job.annotation_note||t('keepUnknown')}):job.annotation_status==='complete'?t('annotationComplete'):job.annotation_status==='partial'?t('annotationPartial'):t('tracksPreparing')));
  $('roster-title').textContent=t('memberTime');
  $('appearance-control').hidden=!Object.keys(job.appearance_links||{}).length;
  $('roster-hint').textContent=t('rosterHint');
  $('roster-summary').textContent=t('rosterLine',{group:job.group||t('sourceWord'),n:job.roster?.length||0});
  $('roster-list').textContent=(job.roster||[]).map(m=>m.name).join(' · ')||t('noRoster');
  $('roster-options').innerHTML=(job.roster||[]).map(m=>`<option value="${esc(m.name)}"></option>`).join('');
}
function gate() {
  if(!job)return;
  if(!frames.length && job.frame_count>0){message(t('reading'));return;}
  const now=video.currentTime || 0;
  const {available,complete:isDone,atEnd,stopped,ready,enoughStart}=playbackWindow(job,frames,cursor,now,firstPlayback);
  if(atEnd){holding=false;stageReady();return;}
  if(job.status==='failed' && !frames.length) {video.pause();wantedPlay=false;message(t('analysisFailed'),trServer(job.message));return;}
  if((job.mode==='complete' || waitAll) && !isDone && !terminal.has(job.status)) {
    if(!video.paused)video.pause();holding=true;message(t('fullAnalysis'),t('fullProgress',{n:Math.floor(job.confirmed_until/job.video.duration*100)}));return;
  }
  if(!ready || (!firstPlayback && !enoughStart)) {
    if(!video.paused)video.pause();holding=true;
    const endedEarly=terminal.has(job.status) && available<job.video.duration;
    message(endedEarly?t('noResultHere'):now>1?t('preparingNext'):t('preparingFirst'),endedEarly?t('dragBack'):t('readyNote',{time:time(available)}));
    return;
  }
  if(video.error) {message(t('codecTitle'),t('codecDetail'));return;}
  if(wantedPlay) {
    if(holding && !stopped && available-now<1.2 && firstPlayback)return;
    holding=false;stageReady();
    if(video.paused && video.readyState>=2 && !playPending) {
      const serial=generation,attempt=++playAttempt;playPending=attempt;
      video.play().then(()=>{
      if(serial!==generation)return;
      if(!wantedPlay){video.pause();return;}
      if(!firstPlayback && uploadStarted)video.dataset.firstPlaySeconds=((performance.now()-uploadStarted)/1000).toFixed(3);
      if(!firstPlayback && uploadStarted){toast(t('firstReadyToast',{n:(performance.now()-uploadStarted)/1000|0}));}
      firstPlayback=true;
    }).catch(()=>{if(serial===generation && wantedPlay){wantedPlay=false;message(t('readyTitle'),t('clickPlay'),true);}}).finally(()=>{if(playPending===attempt)playPending=0;});
    }
  }else if(!firstPlayback && !previewing) {holding=false;message(t('readyTitle'),t('readyToWatch'),true);}
  else {holding=false;stageReady();}
}
function togglePlay(){
  if(!job)return;
  if(wantedPlay){wantedPlay=false;video.pause();}
  else {wantedPlay=true;if(video.ended)video.currentTime=0;gate();}
}
$('play').onclick=togglePlay;$('resume').onclick=()=>{wantedPlay=true;gate();};
function paintTransport(){
  const playing=!video.paused&&!video.ended;
  $('play').classList.toggle('is-playing',playing);
  $('play').setAttribute('aria-label',t(playing?'pauseVideo':'playVideo'));
  $('mute').classList.toggle('is-muted',video.muted);
  $('mute').setAttribute('aria-pressed',video.muted?'true':'false');
  $('mute').setAttribute('aria-label',t(video.muted?'unmute':'mute'));
}
$('mute').onclick=()=>{video.muted=!video.muted;paintTransport();};
$('rate').onchange=()=>{video.playbackRate=Number($('rate').value);};
$('seek').oninput=()=>seekTo(Number($('seek').value));
$('fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else $('stage').requestFullscreen?.();};
video.onplay=()=>paintTransport();
video.onpause=()=>{paintTransport();if(wantedPlay && holding && firstPlayback && !terminal.has(job?.status))video.dataset.bufferPauses=String(Number(video.dataset.bufferPauses||0)+1);};
video.onended=()=>{wantedPlay=false;draw(video.currentTime);panels(video.currentTime);};video.onloadeddata=gate;video.onerror=gate;
video.onseeking=()=>{presentedTime=null;currentFrame=null;draw(video.currentTime);panels(video.currentTime);};
video.onseeked=()=>{presentedTime??=video.currentTime;draw(presentedTime);panels(presentedTime);gate();};
$('cancel').onclick=async()=>{try{job=await api(`/api/jobs/${job.id}/cancel`,{method:'POST'});updateStatus();}catch(e){toast(e.message);}};
$('wait-all').onclick=()=>{waitAll=true;wantedPlay=true;updateStatus();gate();toast(t('switchedWait'));};
for(const format of ['json','csv']) $('export-'+format).onclick=()=>{if(job)window.location.href=`/api/jobs/${job.id}/export?format=${format}${format==='csv'?'&view=members&until='+rankingTime():''}&appearance=${$('appearance-mode').checked}`;};
$('appearance-mode').onchange=()=>{syncStatistics();draw(video.currentTime);panels(video.currentTime);};
$('ranking-scope').onchange=()=>{rankingSignature='';panels(video.currentTime);};
$('ranking-more').onclick=()=>{showAllRanks=!showAllRanks;rankingSignature='';panels(video.currentTime);};
function jumpCenter(direction){const t=video.currentTime,eligible=statistics.segments.filter(s=>s.keys.length&&(direction<0?s.start<t-.15:s.start>t+.05));const target=direction<0?eligible.at(-1):eligible[0];if(target)seekTo(target.start+.001);}
$('previous-center').onclick=()=>jumpCenter(-1);$('next-center').onclick=()=>jumpCenter(1);
function personBox(person){
  const used=new Set([0,1,2,3,4,5,6,11,12]);
  const pts=(person.pose||[]).filter((point,index)=>used.has(index)&&point[2]>=0.45);
  if(pts.length<3) return person.box;
  const xs=pts.map(point=>point[0]),ys=pts.map(point=>point[1]);
  const x0=Math.min(...xs),y0=Math.min(...ys),x1=Math.max(...xs),y1=Math.max(...ys);
  const padX=Math.max(0.015,(x1-x0)*0.45),padY=Math.max(0.02,(y1-y0)*0.22);
  return [Math.max(0,x0-padX),Math.max(0,y0-padY*1.6),Math.min(1,x1+padX),Math.min(1,y1+padY)];
}
function draw(t) {
  const width=canvas.clientWidth,height=canvas.clientHeight,dpr=window.devicePixelRatio || 1;
  if(canvas.width!==Math.round(width*dpr) || canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);renderBoxes=[];
  currentFrame=null;
  if(!job || !video.videoWidth || video.seeking)return;
  const index=frameIndexAt(frames,t),frame=index>=0?frames[index]:null;
  currentFrame=frame;
  canvas.dataset.mediaTime=String(t);canvas.dataset.frameStart=frame?String(frame.t):'';
  if(!currentFrame)return;
  const scale=Math.min(width/video.videoWidth,height/video.videoHeight),vw=video.videoWidth*scale,vh=video.videoHeight*scale,ox=(width-vw)/2,oy=(height-vh)/2;
  const next=frames[index+1];
  const weight=canInterpolate(frame,next)?Math.max(0,Math.min(1,(t-frame.t)/(next.t-frame.t))):0;
  const other=new Map((next?.people||[]).map(p=>[p.id,p]));
  for(const p of frame.people){
    const following=other.get(p.id),currentBox=personBox(p),nextBox=following?personBox(following):null,box=nextBox && weight?currentBox.map((x,i)=>x+(nextBox[i]-x)*weight):currentBox;
    const x=ox+box[0]*vw,y=oy+box[1]*vh,w=(box[2]-box[0])*vw,h=(box[3]-box[1])*vh;
    const center=frame.centers.includes(p.id),identity=statistics.identity(p.id,t),c=center?(identity.named?identityColor(identity.key):timelineColors.unnamed):'#f1f1e9';
    if(!center && !labelAt(p.id,t))continue;
    renderBoxes.push({id:p.id,x,y,w,h});
    ctx.strokeStyle=c;ctx.globalAlpha=center?1:.5;ctx.lineWidth=center?2:1;
    ctx.strokeRect(x,y,w,h);
    if(center){const n=12;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(x,y+n);ctx.lineTo(x,y);ctx.lineTo(x+n,y);ctx.moveTo(x+w-n,y+h);ctx.lineTo(x+w,y+h);ctx.lineTo(x+w,y+h-n);ctx.stroke();}
    ctx.globalAlpha=1;const shown=personName(p.id,t);if(!shown)continue;ctx.font='11px -apple-system, sans-serif';const text=shown;const tw=Math.min(ctx.measureText(text).width+16,vw-5);
    const tx=Math.min(Math.max(ox,x),ox+vw-tw),ty=Math.max(oy,y-25);
    ctx.fillStyle=center?'#b73824ed':'#222222de';ctx.fillRect(tx,ty,tw,22);ctx.fillStyle='#ffffff';ctx.fillText(text,tx+8,ty+15,tw-12);
  }
}
function panels(media) {
  if(!job)return;
  const frame=currentFrame,centers=[...new Map((frame?.centers||[]).map(id=>[labelAt(id,media)?statistics.identity(id,media).key:'track:'+id,id])).values()],stats=statistics.membersAt(rankingTime()),currentStats=statistics.membersAt(media);
  const rowsByKey=new Map(currentStats.rows.map(r=>[r.key,r]));
  const named=centers.filter(id=>labelAt(id,media)).map(id=>personName(id,media));
  const countText=centers.length?peopleCount(centers.length):'';
  $('current-state').textContent=video.ended?t('playbackEnded'):countText?`${countText}${named.length?' · '+named.join(' / '):''}`:frame?t('undecided'):t('waitingFrame');
  $('current-person').classList.toggle('has-person',!!centers.length);
  const signature=JSON.stringify([centers,centers.map(id=>personName(id,media)),video.ended,!!frame,t('currentCenter')]);
  if(signature!==panelSignature){
    panelSignature=signature;
    $('current-person').innerHTML=centers.length?centers.map(id=>{const name=personName(id,media);return `<div class="current-card"><canvas width="90" height="110" data-portrait="${esc(id)}" aria-label="${esc(t('portraitAria'))}"></canvas><div><h2>${esc(name||'—')}</h2><p>${name?esc(t('currentCenter')):esc(t('noCredit'))}</p>${name?`<strong data-current-total="${esc(id)}">0.0 s</strong><small>${esc(t('totalCenter'))}</small>`:''}</div></div>`;}).join(''):`<h2>—</h2><p>${esc(video.ended?t('endedHint'):frame?t('notEnough'):t('waitingVideo'))}</p>`;
  }
  $('current-person').querySelectorAll('[data-current-total]').forEach(el=>{el.textContent=(rowsByKey.get(statistics.identity(el.dataset.currentTotal,media).key)?.seconds||0).toFixed(1)+' s';});
  const activeKeys=new Set(centers.map(id=>statistics.identity(id,media).key));
  const displayed=showAllRanks?stats.rows:stats.rows.slice(0,10),max=Math.max(1,...stats.rows.map(r=>r.seconds));
  // Keep buttons mounted while seconds advance, so a click cannot move to a different target.
  const rankSignature=JSON.stringify([displayed.map(r=>[r.key,r.name]),stats.unbound>0]);
  if(rankSignature!==rankingSignature){
    rankingSignature=rankSignature;
    $('ranking').className=displayed.length?'':'ranking-empty';
    $('ranking').innerHTML=displayed.length?displayed.map((r,i)=>`<div class="rank-row ${activeKeys.has(r.key)?'active':''}" data-key="${esc(r.key)}"><div class="rank-label"><span class="rank-number">${String(i+1).padStart(2,'0')}</span><button class="rank-name" data-first="${r.first}" title="${esc(t('replayFirst'))}">${esc(r.name)}</button><span class="rank-value"></span></div><div class="rank-bar"><i></i></div></div>`).join(''):stats.unbound>0?esc(t('rankingUnbound')):esc(t('rankingNone'));
    $('ranking').querySelectorAll('[data-first]').forEach(b=>b.onclick=()=>seekTo(Number(b.dataset.first)+.001));
  }
  $('ranking').querySelectorAll('.rank-row').forEach((el,i)=>{el.classList.toggle('active',activeKeys.has(displayed[i].key));el.querySelector('.rank-value').textContent=displayed[i].seconds.toFixed(1)+' s';el.querySelector('.rank-bar i').style.width=`${displayed[i].seconds/max*100}%`;});
  $('ranking-more').hidden=stats.rows.length<=10;$('ranking-more').textContent=showAllRanks?t('collapseRanks'):t('expandRanks',{n:stats.rows.length});
  $('ranking-cutoff').textContent=time(stats.until);$('unknown-time').textContent=t('unknownTime',{n:statistics.at(confirmed()).unknown.toFixed(1)});$('unnamed-time').textContent=stats.unbound.toFixed(1)+' s';
  const visible=frame?.people||[];$('member-count').textContent=t('boxCount',{n:visible.length});
  const memberSignature=JSON.stringify(visible.map(p=>[p.id,personName(p.id,media)]));
  if($('members').dataset.signature!==memberSignature){
    $('members').dataset.signature=memberSignature;
    $('members').innerHTML=visible.length?`<div class="member-list">${visible.map(p=>`<button class="member-chip ${labelAt(p.id,media)?'confirmed':''}" data-person="${esc(p.id)}">${esc(personName(p.id,media))}</button>`).join('')}</div>`:`<p class="muted">${esc(t('noPeople'))}</p>`;
    $('members').querySelectorAll('[data-person]').forEach(b=>b.onclick=()=>editLabel(b.dataset.person));
  }
  const recent=statistics.segments.filter(s=>s.keys.length&&s.start<=media).slice(-6).reverse();
  const changeSignature=JSON.stringify(recent.map(s=>[s.start,s.names]));
  if($('center-changes').dataset.signature!==changeSignature){
    $('center-changes').dataset.signature=changeSignature;
    $('center-changes').innerHTML=recent.length?recent.map(s=>`<button class="change-chip" data-start="${s.start}"><time>${time(s.start)}</time><span>${esc(segmentNames(s))}</span><small></small></button>`).join(''):`<p class="muted">${esc(t('noCentersYet'))}</p>`;
    $('center-changes').querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>seekTo(Number(b.dataset.start)+.001));
  }
  $('center-changes').querySelectorAll('.change-chip').forEach((el,i)=>{el.classList.toggle('active',media>=recent[i].start&&media<recent[i].end);el.querySelector('small').textContent=(Math.min(media,recent[i].end)-recent[i].start).toFixed(1)+' s';});
  $('previous-center').disabled=!statistics.segments.some(s=>s.keys.length&&s.start<media-.15);
  $('next-center').disabled=!statistics.segments.some(s=>s.keys.length&&s.start>media+.05);
  const caption=(job.captions||[]).findLast(c=>c.t<=media&&c.end>media);
  $('caption-name').textContent=caption?.names?.join(' / ')||'—';$('caption-note').textContent=caption?t('captionSampled'):t('captionEmpty');
  drawTimeline(media);
  const legend=new Map();
  for(const s of statistics.segments) s.keys.forEach((key,i)=>{if(key.startsWith('name:'))legend.set(key,s.names[i]);});
  const legendHtml=[...legend].map(([key,name])=>`<span><i style="background:${identityColor(key)}"></i>${esc(name)}</span>`).join('')+`<span><i class="legend-unnamed"></i>${esc(t('legendUnnamed'))}</span><span><i class="legend-unknown"></i>${esc(t('legendUnknown'))}</span><span><i class="legend-pending"></i>${esc(t('legendPending'))}</span>`;
  if($('timeline-legend').dataset.signature!==legendHtml){$('timeline-legend').dataset.signature=legendHtml;$('timeline-legend').innerHTML=legendHtml;}
}
function portraits(){
  if(!currentFrame||video.readyState<2||video.seeking)return;
  $('current-person').querySelectorAll('[data-portrait]').forEach(c=>{const p=currentFrame.people.find(p=>p.id===c.dataset.portrait);if(!p)return;const [x1,y1,x2,y2]=p.box,context=c.getContext('2d'),w=(x2-x1)*video.videoWidth,h=(y2-y1)*video.videoHeight;if(w<=0||h<=0)return;const scale=Math.min(c.width/w,c.height/h);context.fillStyle='#e8e8e3';context.fillRect(0,0,c.width,c.height);context.drawImage(video,x1*video.videoWidth,y1*video.videoHeight,w,h,(c.width-w*scale)/2,(c.height-h*scale)/2,w*scale,h*scale);});
}
function drawTimeline(t){
  const c=$('center-timeline'),context=c.getContext('2d'),dpr=window.devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;
  if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);}
  context.setTransform(dpr,0,0,dpr,0,0);context.fillStyle=timelineColors.pending;context.fillRect(0,0,w,h);
  if(timelineCache.width!==c.width||timelineCache.height!==c.height){timelineCache.width=c.width;timelineCache.height=c.height;timelineDirty=true;}
  if(timelineDirty){
    const cached=timelineCache.getContext('2d');cached.setTransform(dpr,0,0,dpr,0,0);cached.clearRect(0,0,w,h);
    for(const r of timelineRects(statistics.segments,job.video.duration,w)){cached.fillStyle=r.color;cached.fillRect(r.x,r.y*h,r.width,r.height*h);}
    timelineDirty=false;
  }
  context.drawImage(timelineCache,0,0,w,h);
  context.fillStyle='#20201c';context.fillRect(Math.max(0,Math.min(w-2,t/job.video.duration*w-1)),0,2,h);
  $('timeline-end').textContent=time(job.video.duration);
}
$('center-timeline').onclick=e=>{if(!job)return;const r=e.currentTarget.getBoundingClientRect();seekTo((e.clientX-r.left)/r.width*job.video.duration);};
$('center-timeline').onmousemove=e=>{
  if(!job)return;
  const r=e.currentTarget.getBoundingClientRect(),at=Math.max(0,Math.min(job.video.duration,(e.clientX-r.left)/r.width*job.video.duration)),s=statistics.segmentAt(at);
  const precise=value=>`${time(value)}.${Math.floor(value%1*10)}`;
  const names=s?segmentNames(s):'';$('timeline-detail').textContent=s?t('timelineSpan',{range:`${precise(s.start)} – ${precise(s.end)}`,who:s.keys.length?peopleCount(s.keys.length):t('undecided'),names:names?' · '+names:''}):t('noAnalysisYet',{time:precise(at)});
};
$('center-timeline').onmouseleave=()=>{$('timeline-detail').textContent=t('timelineHelp');};
function editLabel(id){
  if(!job)return;wantedPlay=false;video.pause();labelTrack=id;
  $('track-label').textContent=t('trackBound',{time:time(video.currentTime)});
  $('person-name').value=labelAt(id)?.name||'';
  $('roster-choices').innerHTML=(job.roster||[]).map(m=>`<button type="button" data-choice="${esc(m.name)}">${esc(m.name)}</button>`).join('');
  $('roster-choices').querySelectorAll('button').forEach(b=>b.onclick=()=>{$('person-name').value=b.dataset.choice;$('roster-choices').querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===b));});
  const preview=$('person-preview'),context=preview.getContext('2d'),person=currentFrame?.people.find(p=>p.id===id);context.fillStyle='#e6e6de';context.fillRect(0,0,preview.width,preview.height);
  if(person&&video.readyState>=2){const [a,b,c,d]=person.box,x=a*video.videoWidth,y=b*video.videoHeight,w=(c-a)*video.videoWidth,h=(d-b)*video.videoHeight,scale=Math.min(preview.width/w,preview.height/h);context.drawImage(video,x,y,w,h,(preview.width-w*scale)/2,(preview.height-h*scale)/2,w*scale,h*scale);}
  $('label-dialog').showModal();$('person-name').focus();
}
$('edit-roster').onclick=()=>{if(!job)return;$('roster-names').value=(job.roster||[]).map(m=>m.name).join('\n');$('roster-source').value=job.roster?.[0]?.source||job.source_url||'';$('roster-error').textContent='';$('roster-dialog').showModal();};
$('roster-form').onsubmit=async e=>{e.preventDefault();try{const names=[...new Set($('roster-names').value.split(/\n/).map(n=>n.trim()).filter(Boolean))];job=await api(`/api/jobs/${job.id}/roster`,{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({members:names.map(name=>({name,source:$('roster-source').value.trim()}))})});$('roster-dialog').close();updateStatus();panels(video.currentTime);}catch(e){$('roster-error').textContent=e.message;}};
canvas.onclick=e=>{const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const hit=[...renderBoxes].reverse().find(b=>x>=b.x&&x<=b.x+b.w&&y>=b.y&&y<=b.y+b.h);if(hit)editLabel(hit.id);};
$('label-form').onsubmit=async e=>{e.preventDefault();try{job=await api(`/api/jobs/${job.id}/labels/${labelTrack}`,{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({name:$('person-name').value})});$('label-dialog').close();syncStatistics();panels(video.currentTime);draw(video.currentTime);toast(t('savedName'));}catch(e){toast(e.message);}};
function tick(now){
  if(job){gate();const t=displayTime()||0;$('seek').value=video.currentTime;$('time').innerHTML=`${time(t)} <em>/ ${time(job.video.duration)}</em>`;if(video.paused || !video.requestVideoFrameCallback)draw(t);if(now-lastPanel>100){panels(t);portraits();lastPanel=now;}}
  requestAnimationFrame(tick);
}
if(video.requestVideoFrameCallback){const onFrame=(_,metadata)=>{presentedTime=metadata.mediaTime;if(!video.seeking)draw(presentedTime);video.requestVideoFrameCallback(onFrame);};video.requestVideoFrameCallback(onFrame);}
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target.tagName)||document.querySelector('dialog[open]'))return;if(e.code==='Space'&&job){e.preventDefault();togglePlay();}if(e.key.toLowerCase()==='n')$('file').click();});
function refreshLanguage(){
  paintTransport();
  showTitle();
  if($('import-dialog').open && !uploading) $('start').textContent=modelReady?t('startAnalysis'):t('waitModel');
  if(!job){
    $('analysis-status').textContent=t('waitingImport');
    $('current-state').textContent=t('waitingFrame');
    $('name-status').textContent=t('namesUnconfirmed');
    $('timeline-detail').textContent=t('timelineHelp');
    $('member-count').textContent=t('zeroBoxes');
  }
  history();
  if(job){
    panelSignature='';rankingSignature='';
    delete $('members').dataset.signature;
    delete $('center-changes').dataset.signature;
    delete $('timeline-legend').dataset.signature;
    updateStatus();gate();panels(displayTime()||0);draw(displayTime()||0);
  }
}
document.querySelectorAll('.lang-switch [data-lang]').forEach(button=>button.onclick=()=>setLanguage(button.dataset.lang));
onLanguage(refreshLanguage);
setLanguage(document.documentElement.lang==='en'||localStorage.getItem('centerstage:lang')==='en'?'en':'zh');
await history();health();requestAnimationFrame(tick);
const previous=new URLSearchParams(location.search).get('job')||localStorage.getItem('centerstage:last');if(previous)loadJob(previous);
