// Isolated CLI builds use a temporary cwd. Never touch a user project or active-story.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync, readFileSync, copyFileSync, rmSync, readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync, spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const video=fileURLToPath(new URL('..',import.meta.url));
const build=path.join(video,'scripts/build.mjs');
const compositor='node_modules/@remotion/compositor-win32-x64-msvc';
const sha=s=>createHash('sha1').update(s).digest('hex').slice(0,10);
function fixture(run){
 const root=mkdtempSync(path.join(tmpdir(),'aag-build-test-'));
 try {
  const project=path.join(root,'videos','demo');
  mkdirSync(path.join(project,'audio'),{recursive:true});mkdirSync(path.join(root,'src'));
  const source={meta:{title:'Fixture',format:'16:9',fps:30,voice:'selected',tts:{provider:'custom',base_url:'https://invalid.local',model:'no-network'},width:1920,height:1080},scenes:[{id:'b1',template:'hand-drawn',narration:'第一句字幕。第二句字幕。',data:{}}]};
  writeFileSync(path.join(project,'story.json'),JSON.stringify(source));
  writeFileSync(path.join(project,'project.json'),JSON.stringify({status:'reviewed',settings:{require_selected_audio:true}}));
  const audio=path.join(project,'audio/b1.mp3');
  const invoke=()=>spawnSync(process.execPath,[build,'demo','--no-render'],{cwd:root,encoding:'utf8',timeout:20000});
  run({root,project,source,audio,invoke});
 } finally {rmSync(root,{recursive:true,force:true});}
}
test('selected missing audio blocks instead of synthesizing or downgrading',()=>fixture(({invoke})=>{
 const result=invoke();assert.notEqual(result.status,0);assert.match(result.stderr,/已选语音缺失/);
}));
test('stale audio is preserved byte for byte',()=>fixture(({audio,project,invoke})=>{
 const bytes=Buffer.from('preserve this selected audio');writeFileSync(audio,bytes);
 writeFileSync(path.join(project,'audio/manifest.json'),JSON.stringify({b1:'stale'}));
 const result=invoke();assert.notEqual(result.status,0);assert.match(result.stderr,/语音已过期/);assert.deepEqual(readFileSync(audio),bytes);
}));
test('actual mp3 duration, selected custom audio, fps and SRT on isolated CLI',()=>fixture(({root,project,source,audio,invoke})=>{
 mkdirSync(path.join(root,compositor),{recursive:true});
 for(const name of readdirSync(path.join(video,compositor)).filter(n=>n.endsWith('.dll') || n==='ffprobe.exe')) copyFileSync(path.join(video,compositor,name),path.join(root,compositor,name));
 execFileSync(path.join(video,compositor,'ffmpeg.exe'),['-v','error','-f','lavfi','-i','sine=frequency=440:duration=3','-c:a','libmp3lame',audio]);
 const original=readFileSync(audio);
 writeFileSync(path.join(project,'audio/manifest.json'),JSON.stringify({b1:sha(source.scenes[0].narration)}));
 for(const fps of [30,60]) {
  source.meta.fps=fps;writeFileSync(path.join(project,'story.json'),JSON.stringify(source));
  const result=invoke();assert.equal(result.status,0,result.stderr);assert.match(result.stdout,/跳过 TTS/);
  const {frames}=JSON.parse(readFileSync(path.join(project,'out/timeline.json')));
  assert.equal(frames.length,1);assert.equal(frames[0].audio,'audio/b1.mp3');
  assert.ok(Math.abs(frames[0].audioDuration-3)<.1);assert.equal(frames[0].leadFrames,Math.round(fps*.45));
  assert.equal(frames[0].alignmentMethod,'approximate-text-weight');
  assert.match(readFileSync(path.join(project,'out/subtitles.srt'),'utf8'),/00:00:00,4\d\d/);
  assert.deepEqual(readFileSync(audio),original);
 }
}));
