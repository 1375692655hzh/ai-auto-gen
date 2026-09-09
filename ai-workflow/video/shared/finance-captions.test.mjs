import test from 'node:test';
import assert from 'node:assert/strict';
import {captionTimeline, toSrt} from './captions.mjs';

const track = {origin:'provider-alignment', unit:'seconds', cues:[
  {t:'收入',start:.1,end:.5}, {t:'增长',start:.5,end:.8}, {t:'12.5%',start:.8,end:1.4},
  {t:'仍需',start:2,end:2.4}, {t:'观察',start:2.4,end:2.9},
]};
for (const fps of [30,60]) test(`Edge words preserve exact sentence bounds at ${fps} fps`,()=>{
  const result = captionTimeline({text:'收入增长12.5%。仍需观察！', duration:4, fps, lead:.7, providerTrack:track});
  assert.equal(result.method,'provider-alignment');
  assert.deepEqual(result.cues,[{t:'收入增长12.5%。',start:Math.round(.8*fps),end:Math.round(2.1*fps)},
    {t:'仍需观察！',start:Math.round(2.7*fps),end:Math.round(3.6*fps)}]);
  assert.match(toSrt([{cues:result.cues,durationInFrames:5.5*fps}],fps),/00:00:00,800 --> 00:00:02,100/);
});
test('bad sidecar falls back honestly without using stale alignment',()=>{
  for (const bad of [{}, {...track,unit:'ticks'}, {...track,cues:[]},
    {...track,cues:[{t:'旧文本',start:0,end:1}]},
    {...track,cues:track.cues.map((c,i)=>i===1?{...c,start:.2}:c)},
    {...track,cues:track.cues.map((c,i)=>i===4?{...c,end:8}:c)}]) {
    const r=captionTimeline({text:'收入增长12.5%。仍需观察！',duration:4,fps:30,providerTrack:bad});
    assert.equal(r.method,'approximate-text-weight'); assert.ok(r.warning);
  }
});
test('long provider sentence splits only at actual word boundaries',()=>{
  const words=Array.from({length:40},(_,i)=>({t:'增长',start:i*.2,end:(i+1)*.2}));
  const r=captionTimeline({text:'增长'.repeat(40)+'。',duration:9,fps:30,providerTrack:{...track,cues:words}});
  assert.equal(r.method,'provider-alignment'); assert.ok(r.cues.length>1);
  for(const c of r.cues) {
    assert.ok(words.some(w=>Math.round(w.start*30)===c.start));
    assert.ok(words.some(w=>Math.round(w.end*30)===c.end));
  }
});
test('fallback stays sentence-first and labels estimates',()=>{
  const r=captionTimeline({text:'短句！这是第二句，包含句内停顿。收入12.5亿元？',duration:9,fps:30});
  assert.equal(r.method,'approximate-text-weight');
  assert.equal(r.cues[0].t,'短句！');
  assert.equal(r.cues.map(c=>c.t).join('').replace(/\s/gu,''),'短句！这是第二句，包含句内停顿。收入12.5亿元？');
  assert.equal(r.cues.at(-1).end,270);
  assert.ok(r.cues.every((c,i)=>c.end>c.start && (!i || c.start===r.cues[i-1].end)));
});
