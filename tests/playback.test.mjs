import {test} from 'node:test';
import assert from 'node:assert/strict';
import {frameIndexAt,canInterpolate,playbackWindow,timelineRects,timelineColors,identityColor} from '../centerstage/static/playback.js';
import {CenterStatistics} from '../centerstage/static/statistics.js';

test('exact half-open frame ownership at cuts, gaps and end',()=>{
  const frames=[{t:0,end:1,shot:0},{t:1,end:2,shot:1},{t:3,end:4,shot:1}];
  for(const [t,index] of [[0,0],[.999999,0],[1,1],[2,-1],[2.9999,-1],[3,2],[4,-1]])assert.equal(frameIndexAt(frames,t),index);
  assert.equal(canInterpolate(frames[0],frames[1]),false);
  assert.equal(canInterpolate(frames[1],frames[2]),false);
  assert.equal(canInterpolate(frames[0],{t:1,end:2,shot:0}),true);
});

test('cancelled short prefixes play without waiting for nonexistent buffer',()=>{
  const frames=[{t:0,end:.5}],job={status:'cancelled',frame_count:1,video:{duration:10}};
  const state=playbackWindow(job,frames,1,.45,false);
  assert.ok(state.ready&&state.enoughStart&&state.stopped);
  assert.equal(state.complete,false);
  assert.equal(playbackWindow(job,frames,1,.5,true).ready,false);
});

test('complete metadata cannot make missing frame batches or gaps playable',()=>{
  const job={status:'complete',frame_count:4,video:{duration:4}};
  assert.equal(playbackWindow(job,[{t:0,end:1}],1,.95,true).ready,false);
  const frames=[{t:0,end:1},{t:2,end:4}];
  assert.equal(playbackWindow({...job,frame_count:2},frames,2,1.5,true).ready,false);
});

test('rounded EOF never pauses playback before the browser ended event',()=>{
  const duration=223.56666666666666;
  const job={status:'complete',frame_count:1,video:{duration}};
  const result=playbackWindow(job,[{t:0,end:duration}],1,223.566667,true);
  assert.ok(result.complete&&result.atEnd&&result.ready);
  assert.equal(frameIndexAt([{t:0,end:duration}],223.566667),-1);
  assert.equal(playbackWindow({...job,status:'cancelled'},[{t:0,end:duration}],1,223.566667,true).atEnd,false);
});

test('timeline width conserves sampled media time without minimum-pixel inflation',()=>{
  const stats=new CenterStatistics();
  for(let i=0;i<1000;i++)stats.append([{t:i/10,end:(i+1)/10,shot:i,people:[],centers:i%2?['a']:[]}]);
  const rects=timelineRects(stats.segments,200,100);
  assert.ok(Math.abs(rects.reduce((sum,r)=>sum+r.width,0)-50)<1e-8);
  assert.equal(rects[0].color,timelineColors.unknown);
  assert.equal(rects[1].color,timelineColors.unnamed);
  assert.equal(rects[1].height,1);
  assert.equal(rects.at(-1).x+rects.at(-1).width,50);
});

test('two centers split one interval into two color bands without inventing time',()=>{
  const stats=new CenterStatistics();
  stats.append([{t:0,end:2,shot:0,people:[],centers:['a','b']}]);
  const rects=timelineRects(stats.segments,2,100);
  assert.equal(rects.length,2);
  assert.equal(rects[0].x,0);
  assert.equal(rects[0].width,100);
  assert.equal(rects[1].width,100);
  assert.equal(rects[0].y,0);
  assert.equal(rects[1].y,.5);
  assert.equal(rects[0].height,.5);
  assert.equal(rects[0].color,timelineColors.unnamed);
  assert.equal(rects[1].color,timelineColors.unnamed);
});

test('member color and the playback name are the same person',()=>{
  const stats=new CenterStatistics({},[{track_id:'a',start:0,end:2,name:'OA',evidence:'explicit_person_annotation'}]);
  stats.append([{t:0,end:1,shot:0,people:[],centers:['a']},{t:1,end:2,shot:0,people:[],centers:['b']}]);
  const rects=timelineRects(stats.segments,2,100);
  assert.equal(stats.identity('a',.5).name,'OA');
  assert.equal(rects[0].color,identityColor('name:oa'));
  assert.equal(rects[0].key,'name:oa');
  assert.equal(rects[1].color,timelineColors.unnamed);
  assert.equal(rects[1].key,'track:b');
});

test('same garment links cannot erase a double-center interval or a track transition',()=>{
  const links={a:{group_id:'g0001'},b:{group_id:'g0001'}};
  const stats=new CenterStatistics({},[],links);
  stats.append([{t:0,end:1,shot:0,people:[],centers:['a']},{t:1,end:2,shot:0,people:[],centers:['b']},{t:2,end:3,shot:0,people:[],centers:['a','b']}]);
  assert.equal(stats.segments.length,3);
  assert.equal(stats.segmentAt(1).tracks[0],'b');
  assert.equal(stats.segmentAt(2).state,'dual');
  assert.equal(stats.segmentAt(3),null);
  assert.equal(stats.at(3).unbound,3);
});

test('unsupported persisted annotations never create a named timeline',()=>{
  const stats=new CenterStatistics({},[{track_id:'a',start:0,end:1,name:'Guess',evidence:'auto_identified'}]);
  stats.append([{t:0,end:1,people:[],centers:['a']}]);
  assert.equal(stats.membersAt(1).rows.length,0);
  assert.equal(stats.label('a',.5),undefined);
});
