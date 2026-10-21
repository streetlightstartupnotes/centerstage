// Media-time accounting: each interval contributes once, regardless of playback.
class Series {
  constructor(){this.spans=[];this.total=0;}
  add(start,end,weight=1){if(end<=start)return;this.spans.push({start,end,weight,before:this.total});this.total+=(end-start)*weight;}
  at(t){let lo=0,hi=this.spans.length-1,index=-1;while(lo<=hi){const m=(lo+hi)>>1;if(this.spans[m].start<t){index=m;lo=m+1;}else hi=m-1;}if(index<0)return 0;const s=this.spans[index];return s.before+Math.max(0,Math.min(t,s.end)-s.start)*s.weight;}
}
export class CenterStatistics {
  constructor(labels={},annotations=[],appearanceLinks={}){
    this.appearanceLinks=appearanceLinks;
    this.labels=labels;this.annotations=new Map();this.tracks=new Map();this.rows=new Map();this.unknown=new Series();this.unnamed=new Series();this.covered=new Series();this.segments=[];this.end=0;
    for(const a of annotations){if(a.evidence!=='explicit_person_annotation'||!a.name?.trim())continue;if(!this.annotations.has(a.track_id))this.annotations.set(a.track_id,[]);this.annotations.get(a.track_id).push(a);}
  }
  label(id,t){const manual=this.labels[id];return manual?.evidence==='user_confirmed'&&manual.name?.trim()?manual:(this.annotations.get(id)||[]).find(a=>a.start<=t&&t<a.end);}
  track(id){if(!this.tracks.has(id))this.tracks.set(id,{id,name:`轨迹片段 ${String(this.tracks.size+1).padStart(3,'0')}`});return this.tracks.get(id);}
  identity(id,t,allowGroup=true){const name=this.label(id,t)?.name?.trim(),group=allowGroup&&this.appearanceLinks[id]?.group_id;if(name)return {key:'name:'+name.toLowerCase(),name,named:true};if(group)return {key:'garment:'+group,name:'外观组 '+String(Number(group.slice(1))).padStart(3,'0'),named:false,association:'garment_similarity'};return {key:'track:'+id,name:this.track(id).name,named:false};}
  append(frames){
    for(const f of frames){
      if(!Number.isFinite(f.t)||!Number.isFinite(f.end)||f.t<0||f.end<=f.t)throw new Error('无效的分析区间');
      if(f.t<this.end-1e-6)throw new Error('分析区间重叠');
      for(const p of f.people||[])this.track(p.id);
      for(const id of f.centers)this.track(id);
      this.covered.add(f.t,f.end);this.end=f.end;
      const edges=[...new Set([f.t,f.end,...f.centers.flatMap(id=>(this.annotations.get(id)||[]).flatMap(a=>[a.start,a.end])).filter(v=>v>=f.t&&v<=f.end)])].sort((a,b)=>a-b);
      for(let i=0;i<edges.length-1;i++){
        const start=edges[i],end=edges[i+1],ids=new Map();
        for(const id of new Set(f.centers)){const group=this.appearanceLinks[id]?.group_id,allowGroup=!group||[...new Set(f.centers)].filter(other=>this.appearanceLinks[other]?.group_id===group).length===1;const identity=this.identity(id,(start+end)/2,allowGroup);if(!ids.has(identity.key))ids.set(identity.key,{...identity,tracks:[]});ids.get(identity.key).tracks.push(id);}
        if(!ids.size)this.unknown.add(start,end);
        if([...ids.values()].some(r=>!r.named))this.unnamed.add(start,end);
        for(const entry of ids.values()){
          if(!this.rows.has(entry.key))this.rows.set(entry.key,{...entry,tracks:new Map(),seconds:new Series(),equivalent:new Series(),first:start});
          const r=this.rows.get(entry.key);entry.tracks.forEach(id=>{if(!r.tracks.has(id))r.tracks.set(id,start);});r.seconds.add(start,end);r.equivalent.add(start,end,1/ids.size);
        }
        const keys=[...ids.keys()].sort(),last=this.segments.at(-1),tracks=[...new Set(f.centers)].sort();
        const state=ids.size===0?'unknown':ids.size===1?'single':ids.size===2?'dual':'multiple';
        if(last&&last.shot===f.shot&&Math.abs(last.end-start)<1e-6&&JSON.stringify(last.keys)===JSON.stringify(keys)&&JSON.stringify(last.tracks)===JSON.stringify(tracks))last.end=end;
        else this.segments.push({start,end,shot:f.shot,keys,tracks,state,names:keys.map(k=>ids.get(k).name)});
      }
    }
  }
  at(t){
    t=Math.max(0,Math.min(t,this.end));
    const rows=[...this.rows.values()].filter(r=>r.first<t).map(r=>({key:r.key,name:r.name,named:r.named,seconds:r.seconds.at(t),equivalent_seconds:r.equivalent.at(t),track_count:[...r.tracks.values()].filter(first=>first<t).length,first:r.first,...(r.association?{association:r.association}:{})}));
    rows.sort((a,b)=>b.seconds-a.seconds||a.first-b.first||a.key.localeCompare(b.key));
    return {until:t,rows,unknown:this.unknown.at(t),unbound:this.unnamed.at(t),covered:this.covered.at(t)};
  }
  membersAt(t){const stats=this.at(t);return {...stats,rows:stats.rows.filter(r=>r.named)};}
  segmentAt(t){let lo=0,hi=this.segments.length-1,index=-1;while(lo<=hi){const m=(lo+hi)>>1;if(this.segments[m].start<=t){index=m;lo=m+1;}else hi=m-1;}return index>=0&&t<this.segments[index].end?this.segments[index]:null;}
}
