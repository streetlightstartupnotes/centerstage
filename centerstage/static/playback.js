// A sample owns [t, end). Never borrow a result across a gap or a seek.
export function frameIndexAt(frames, t) {
  let lo=0, hi=frames.length-1, index=-1;
  while(lo<=hi){const m=(lo+hi)>>1;if(frames[m].t<=t){index=m;lo=m+1;}else hi=m-1;}
  return index>=0 && t<frames[index].end ? index : -1;
}

export function canInterpolate(frame, next) {
  return !!next && next.shot===frame.shot && next.t>frame.t && Math.abs(frame.end-next.t)<1e-6;
}

export function playbackWindow(job, frames, cursor, t, firstPlayback) {
  const available=frames.at(-1)?.end||0;
  const terminal=['complete','cancelled','failed','interrupted'].includes(job.status);
  const stopped=terminal && cursor>=job.frame_count;
  const complete=job.status==='complete' && stopped && available>=job.video.duration-1e-5;
  // Chromium can expose the rounded duration before dispatching `ended`.
  // Pausing at this point suppresses `ended` and leaves the player buffering.
  const atEnd=complete && t>=job.video.duration-1e-6;
  const ready=atEnd || (frameIndexAt(frames,t)>=0 && (stopped || available>=Math.min(job.video.duration,t+.12)));
  return {available,stopped,complete,atEnd,ready,
    enoughStart:firstPlayback || available>=Math.min(3,job.video.duration) || (stopped&&available>0)};
}

export const timelineColors={unknown:'#c9c8bd',pending:'#f2f1ed',unnamed:'#e7e2d8'};
export const identityPalette=['#bd684f','#3d6b8c','#c4a15a','#6d8f62','#8d5a78','#d07a45','#4f7d78','#a34b3c','#5c6e9a','#7a6a4f'];
export const timelineStateNames={single:'1 人',dual:'2 人',multiple:'多个 C 位',unknown:'未明确判定'};

export function identityColor(key){
  const text=String(key||'');
  let hash=2166136261;
  for(let i=0;i<text.length;i++) hash=Math.imul(hash^text.charCodeAt(i),16777619);
  return identityPalette[(hash>>>0)%identityPalette.length];
}

// Each person is one horizontal color zone. Two centers split the bar vertically.
export function timelineRects(segments,duration,width){
  if(!(duration>0&&width>0))return [];
  return segments.filter(s=>s.end>s.start&&s.start<duration).flatMap(s=>{
    const x=Math.max(0,s.start)/duration*width;
    const span=(Math.min(duration,s.end)-Math.max(0,s.start))/duration*width;
    const end=Math.min(duration,s.end);
    if(!s.keys.length) return [{x,y:0,width:span,height:1,color:timelineColors.unknown,state:s.state,start:s.start,end,key:''}];
    return s.keys.map((key,index)=>({
      x,y:index/s.keys.length,width:span,height:1/s.keys.length,
      color:String(key).startsWith('name:')?identityColor(key):timelineColors.unnamed,state:s.state,start:s.start,end,key}));
  });
}
