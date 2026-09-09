import test from 'node:test';
import assert from 'node:assert/strict';
import {captionTimeline, captionAt, splitCaption, toSrt, visualShots} from './captions.mjs';
import {validateStory} from '../scripts/story-validate.mjs';
import {TEMPLATE_IDS} from '../scripts/template-ids.mjs';
const compact = s => s.replace(/\s/g,'');
for (const [name,text] of Object.entries({
  chinese: '市场发生变化，利息支出同比增加百分之十五。接下来观察资金流向，保持耐心。',
  english: 'Revenue reached 12.5 billion USD. NVIDIA and SpaceX remain distinct names; wait for the next update!',
  long: '一段没有句号的中文长句需要安全切分同时完整保留原始文字'.repeat(6),
  numbers: '2026年收入12.5亿元，增长35%，延迟20ms。价格为1,234.56美元。',
  punctuation: '“真的？”是的！\n短句；接下来：观察，不要猜。',
})) {
  test(`coverage and two lines: ${name}`, () => {
    const chunks=splitCaption(text);
    assert.equal(compact(chunks.join('')),compact(text));
    assert.ok(chunks.every(c=>c.split('\n').length<=2));
    const {cues,method}=captionTimeline({text,duration:45,fps:30,lead:.7});
    assert.equal(method,'approximate-text-weight');
    assert.equal(cues[0].start,21); assert.equal(cues.at(-1).end,1371);
    assert.ok(cues.every((c,i)=>c.end>c.start && (!i || c.start===cues[i-1].end)));
    assert.equal(compact(cues.map(c=>c.t).join('')),compact(text));
  });
}
test('word / decimal / unit boundaries',()=>{
 const text='收入为12.5亿元，NVIDIA SpaceX增长35%，响应20ms。';
 const parts=splitCaption(text,8).join('|');
 for (const word of ['12.5亿元','NVIDIA','SpaceX','35%','20ms']) assert.ok(parts.includes(word),parts);
});
test('gap, lead and tail show no stale caption in any fps',()=>{
 for(const fps of [30,60]) {
  const cues=[{t:'甲',start:fps,end:2*fps},{t:'乙',start:3*fps,end:4*fps}];
  for(const t of [0,.7,2,2.5,4,5]) assert.equal(captionAt(cues,t*fps,6*fps,fps),'');
  assert.equal(captionAt(cues,1.5*fps,6*fps,fps),'甲');
 }
});
test('30 / 60 fps timing agreement within one frame',()=>{
 const text='数字12.5亿元。 English words remain intact! '+ '请保持字幕完整。'.repeat(8);
 const a=captionTimeline({text,duration:23.47,fps:30,lead:.7}).cues;
 const b=captionTimeline({text,duration:23.47,fps:60,lead:.7}).cues;
 assert.equal(a.length,b.length);
 a.forEach((c,i)=>{assert.ok(Math.abs(c.start/30-b[i].start/60)<=1/30);assert.ok(Math.abs(c.end/30-b[i].end/60)<=1/30);});
});
test('provider audio-relative timestamps take precedence and preserve gaps',()=>{
 const alignment={unit:'seconds',origin:'audio',segments:[{t:'你好。',start:.1,end:1},{t:'世界。',start:2,end:3}]};
 const result=captionTimeline({text:'你好。世界。',duration:4,fps:30,lead:.7,alignment,cues:[{t:'bad',start:0,end:1}]});
 assert.equal(result.method,'provider-alignment');
 assert.deepEqual(result.cues,[{t:'你好。',start:24,end:51},{t:'世界。',start:81,end:111}]);
 assert.equal(captionAt(result.cues,65,150,30),'');
});
test('invalid / stale / overlapping alignment rejected',()=>{
 for(const segments of [[{t:'错',start:0,end:1}],[{t:'甲',start:1,end:9}],[{t:'甲',start:1,end:2},{t:'乙',start:1.5,end:3}]]) {
  assert.throws(()=>captionTimeline({text:'甲乙',duration:4,fps:30,lead:.7,alignment:{unit:'seconds',origin:'audio',segments}}));
 }
});
test('supplied scene frame cues have no double lead',()=>{
 const cues=[{t:'甲。',start:30,end:90}];
 assert.deepEqual(captionTimeline({text:'甲。',duration:4,fps:30,lead:.7,cues}).cues,cues);
});
test('SRT matches rendered frames including scene offsets',()=>{
 const frames=[{cues:[{t:'甲',start:21,end:60}],durationInFrames:90},{cues:[{t:'乙',start:21,end:60}],durationInFrames:90}];
 assert.equal(toSrt(frames,30),'1\n00:00:00,700 --> 00:00:02,000\n甲\n\n2\n00:00:03,700 --> 00:00:05,000\n乙\n');
});
test('shots merge short cues / split long cues independently',()=>{
 for(const cues of [[{t:'long',start:21,end:600}],Array.from({length:30},(_,i)=>({t:'短',start:i*20,end:(i+1)*20}))]){
  const shots=visualShots(cues,630,30);
  assert.ok(shots.length>=4 && shots.length<=6);
  assert.equal(shots[0].start,0);assert.equal(shots.at(-1).end,630);
  assert.ok(shots.every((s,i)=>s.end-s.start>=90 && s.end-s.start<=180 && (!i || s.start===shots[i-1].end)));
 }
});
test('new template registry, illegal material path and aspect',()=>{
 for(const template of ['hand-drawn','vox-fast-cut']) {
  assert.ok(TEMPLATE_IDS.includes(template));
  const story={meta:{format:'16:9'},scenes:[{id:'b1',template,narration:'原文',data:{}}]};
  assert.equal(validateStory(story).errors.length,0);
  for(const image of ['../secret.png','C:/x.png','materials/../../x.png','https://example.com/x.png']){
   story.scenes[0].data={image};assert.ok(validateStory(story).errors.length>0);
  }
  story.scenes[0].data={};story.meta.format='9:16';assert.ok(validateStory(story).errors.length>0);
 }
});
test('long narration never becomes a single on-screen caption',()=>{
 const text='市场发生变化，利息支出同比增加百分之十五。接下来观察资金流向，保持耐心。';
 const {cues,method}=captionTimeline({text,duration:20,fps:30,lead:.7});
 assert.equal(method,'approximate-text-weight');
 assert.ok(cues.length>=2);
 assert.ok(cues.every(c=>compact(c.t)!==compact(text)));
 assert.ok(cues.every(c=>c.t.split('\n').length<=2));
});
test('overlong token is force-split without dropping characters',()=>{
 const text='一段没有句号的中文长句需要安全切分同时完整保留原始文字'.repeat(4);
 const chunks=splitCaption(text,16);
 assert.equal(compact(chunks.join('')),compact(text));
 assert.ok(chunks.length>=3);
 assert.ok(chunks.every(c=>c.split('\n').length<=2));
});
test('short leftover shot merges instead of leaving a sub-3s tail',()=>{
 const fps=30, duration=7*fps;
 const shots=visualShots([{t:'long',start:21,end:duration-10}],duration,fps);
 assert.equal(shots.at(-1).end,duration);
 assert.ok(shots.every(s=>s.end-s.start>=3*fps || shots.length===1));
});
