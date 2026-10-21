import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {CenterStatistics} from '../centerstage/static/statistics.js';
const fixture=JSON.parse(fs.readFileSync(new URL('./data/statistics.json',import.meta.url),'utf8'));
const build=(annotations=fixture.annotations)=>{const stats=new CenterStatistics(fixture.labels,annotations);stats.append(fixture.frames);return stats;};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
test('media clock, partial intervals, gaps, equal-name double C and rewind',()=>{
  const stats=build(),end=stats.at(11),at4=stats.at(4);
  assert.equal(end.rows[0].name,'Sample A');close(end.rows[0].seconds,5.5);assert.equal(end.rows[0].track_count,3);
  close(end.unknown,2);close(end.covered,10);close(end.rows.reduce((s,r)=>s+r.equivalent_seconds,0)+end.unknown,end.covered);
  close(at4.rows[0].seconds,3);assert.equal(at4.rows[0].track_count,1);assert.equal(at4.rows.length,2);
  assert.deepEqual(stats.at(4),at4);assert.deepEqual(stats.at(11),end);
  assert.equal(stats.at(0).rows.length,0);assert.equal(stats.at(5).rows.some(r=>r.name==='Sample B'),false);
  assert.equal(stats.segmentAt(9.5),null);assert.equal(stats.segmentAt(5.5).names[0],'Sample A');
});
test('incremental streaming agrees with full load and late annotations rebuild cleanly',()=>{
  const streamed=new CenterStatistics(fixture.labels,fixture.annotations);
  for(const f of fixture.frames)streamed.append([f]);
  assert.deepEqual(streamed.at(11),build().at(11));
  const anonymous=new CenterStatistics();anonymous.append(fixture.frames);
  assert.equal(anonymous.at(11).rows.filter(r=>r.named).length,0);
  assert.ok(anonymous.at(11).rows.length>0);
  assert.equal(build().identity('b',3.5).name,'轨迹片段 002');assert.equal(build().identity('b',4).name,'Sample A');
  assert.equal(anonymous.identity('b',8).name,'轨迹片段 002');
  assert.throws(()=>streamed.append(fixture.frames),/重叠/);
});
test('same known name from multiple tracks is counted only once at each moment',()=>{
  const stats=build();close(stats.at(5).rows[0].seconds-stats.at(4).rows[0].seconds,1);
  close(stats.at(5).rows[0].equivalent_seconds-stats.at(4).rows[0].equivalent_seconds,1);
});
test('legacy popularity-based names cannot become verified labels or named totals',()=>{
  const stats=new CenterStatistics({a:{name:'Guessed',evidence:'auto_identified',confidence:.99}});
  stats.append([{t:0,end:2,centers:['a'],people:[{id:'a'}]}]);
  assert.equal(stats.label('a',1),undefined);
  assert.equal(stats.identity('a',1).named,false);
  assert.equal(stats.at(2).rows[0].name,'轨迹片段 001');
  close(stats.at(2).unbound,2);
});
test('fragmentation never creates member rows; two unnamed centers count one video interval',()=>{
  const stats=new CenterStatistics();
  for(let i=0;i<20;i++)stats.append([{t:i/10,end:(i+1)/10,shot:i,centers:[`left-${i}`,`right-${i}`],people:[]}]);
  assert.equal(stats.at(2).rows.length,40);
  assert.equal(stats.membersAt(2).rows.length,0);
  close(stats.membersAt(2).unbound,2);
  close(stats.membersAt(.35).unbound,.35);
  assert.equal(stats.membersAt(0).rows.length,0);
});
test('member view keeps only supported names without changing their time or scope',()=>{
  const stats=build();
  for(const t of [0,1,4,4.5,5,7,11,3]){
    const full=stats.at(t),members=stats.membersAt(t);
    assert.deepEqual(members,{...full,rows:full.rows.filter(row=>row.named)});
    assert.ok(members.rows.every(row=>row.key.startsWith('name:')));
  }
});
