// 原音连续主轨(0917 用户裁决)回归: CONT 模式 --no-render 断言——
// frame.audio 恒 null / leadFrames 恒 0 / 总帧数=主轨时长量化 / 场景边界=绝对时间轴 / SRT 无 lead 偏移。
// 隔离 cwd, 不触真实项目与 src/active-story.ts。
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, readdirSync, copyFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync, spawnSync} from 'node:child_process';
const video=fileURLToPath(new URL('..',import.meta.url));
const build=path.join(video,'scripts/build.mjs');
const compositor='node_modules/@remotion/compositor-win32-x64-msvc';

function fixture(run){
 const root=mkdtempSync(path.join(tmpdir(),'aag-cont-test-'));
 try {
  const project=path.join(root,'videos','demo');
  mkdirSync(path.join(project,'audio'),{recursive:true});mkdirSync(path.join(root,'src'));
  // 真实 mp3 主轨(2.9s 正弦): probeDuration 走 compositor ffprobe
  mkdirSync(path.join(root,compositor),{recursive:true});
  for(const name of readdirSync(path.join(video,compositor)).filter(n=>n.endsWith('.dll')||n==='ffprobe.exe'||n==='ffmpeg.exe')) copyFileSync(path.join(video,compositor,name),path.join(root,compositor,name));
  const master=path.join(project,'audio/master.mp3');
  execFileSync(path.join(root,compositor,'ffmpeg.exe'),['-v','error','-f','lavfi','-i','sine=frequency=440:duration=2.9','-c:a','libmp3lame',master]);
  const story={meta:{title:'Continuous',format:'16:9',fps:30,voice:'original',width:1920,height:1080},
   scenes:[{id:'b1',template:'hand-drawn',narration:'第一句字幕。',data:{}},
           {id:'b2',template:'hand-drawn',narration:'第二句字幕。',data:{}}]};
  const settings={require_selected_audio:true,audioRoute:{mode:'original-continuous',master:'audio/master.mp3',
   timeline:'audio/master.timeline.json',duration_s:2.9,audio_hash:'x',delivery:'stream-copy'}};
  writeFileSync(path.join(project,'story.json'),JSON.stringify(story));
  writeFileSync(path.join(project,'project.json'),JSON.stringify({status:'reviewed',settings}));
  const timeline={schema:'wb-original-continuous-timeline/v1',audio_hash:'x',narration_hash:'y',
   duration_s:2.9,alignment:'whisper',beats:[
    {id:'b1',start_s:0,end_s:1.4,phrases:[{t:'第一句字幕。',start:0.4,end:1.2}]},
    {id:'b2',start_s:1.4,end_s:2.9,phrases:[{t:'第二句字幕。',start:1.6,end:2.4}]}]};
  writeFileSync(path.join(project,'audio/master.timeline.json'),JSON.stringify(timeline));
  const invoke=()=>spawnSync(process.execPath,[build,'demo','--no-render'],{cwd:root,encoding:'utf8',timeout:30000});
  run({root,project,story,master,timeline,invoke});
 } finally {rmSync(root,{recursive:true,force:true});}
}

test('CONT mode: silent visuals driven by absolute master timeline',()=>fixture(({project,master,invoke})=>{
 const result=invoke();
 assert.equal(result.status,0,result.stderr+result.stdout);
 const tl=JSON.parse(readFileSync(path.join(project,'out/timeline.json')));
 assert.equal(tl.frames.length,2);
 // 唯一音轨=主轨 remux, 场景永不挂音频
 for(const f of tl.frames){assert.equal(f.audio,null);assert.equal(f.leadFrames,0);assert.equal(f.trimHead,undefined);}
 // 总帧数 = ceil(主轨时长×fps), 边界=绝对秒→帧(b1: 0→42, b2: 42→88)
 const dur=Number(spawnSync(path.join('node_modules/@remotion/compositor-win32-x64-msvc','ffprobe.exe'),
  ['-v','error','-show_entries','format=duration','-of','csv=p=0',master],{cwd:process.cwd(),encoding:'utf8'}).stdout.trim());
 const expectedTotal=Math.ceil(dur*30);
 assert.equal(tl.frames[0].durationInFrames,42);
 assert.equal(tl.frames[0].durationInFrames+tl.frames[1].durationInFrames,tl.frames.reduce((a,f)=>a+f.durationInFrames,0));
 assert.equal(tl.frames.reduce((a,f)=>a+f.durationInFrames,0),expectedTotal);
 // 无逐幕音频依赖
 assert.ok(!existsSync(path.join(project,'audio/b1.mp3')));
 // SRT: 字幕走原音绝对时间(第一句 0.4s 起, 第二句 1.6s 起), 无 0.4s lead 偏移
 const srt=readFileSync(path.join(project,'out/subtitles.srt'),'utf8');
 assert.match(srt,/00:00:00,4\d\d --> 00:00:01,2\d\d/);
 assert.match(srt,/00:00:01,6\d\d --> 00:00:02,4\d\d/);
}));

test('CONT mode: master missing / schema wrong must fail fast',()=>fixture(({project,invoke})=>{
 const pj=JSON.parse(readFileSync(path.join(project,'project.json')));
 rmSync(path.join(project,'audio/master.mp3'));
 let r=invoke();assert.notEqual(r.status,0);assert.match(r.stderr,/主轨缺失/);
 writeFileSync(path.join(project,'audio/master.mp3'),Buffer.alloc(2048));
 const bad=JSON.parse(readFileSync(path.join(project,'audio/master.timeline.json')));
 bad.schema='wrong';
 writeFileSync(path.join(project,'audio/master.timeline.json'),JSON.stringify(bad));
 r=invoke();assert.notEqual(r.status,0);assert.match(r.stderr,/schema/);
 // 估帧数与场景数错位也必须拒
 const bad2=JSON.parse(readFileSync(path.join(project,'audio/master.timeline.json')));
 bad2.schema='wb-original-continuous-timeline/v1';bad2.beats=[bad2.beats[0]];
 writeFileSync(path.join(project,'audio/master.timeline.json'),JSON.stringify(bad2));
 r=invoke();assert.notEqual(r.status,0);assert.match(r.stderr,/幕数|时长/);
 assert.equal(pj.settings.audioRoute.mode,'original-continuous');
}));
