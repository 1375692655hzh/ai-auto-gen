"""Offline mixed sample. Copies archived narration; draws clearly marked demo art.
Run: python scripts/demo_mixed_video.py [--render]
No image/TTS API calls. Source assets are never modified.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'workbench'))
from server.vmake import script_to_story
from PIL import Image, ImageDraw, ImageFont


def main():
    video = ROOT / 'ai-workflow/video'
    project = video / 'videos/demo-mixed-0909'
    marker = project / 'demo-origin.json'
    if project.exists() and not marker.exists():
        raise RuntimeError('Refusing to overwrite an unowned project')
    project.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'generator': 'scripts/demo_mixed_video.py', 'note': 'Archived narration; program-drawn demo art, not current market reporting.'}), encoding='utf-8')
    materials = project / 'input/materials'
    audio_dir = project / 'audio'
    materials.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(exist_ok=True)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 44)
    img = Image.new('RGB', (1600, 1000), '#e9dec6')
    draw = ImageDraw.Draw(img)
    for box in [(90,130,740,830),(840,200,1500,740)]:
        draw.rectangle(box, fill='#fffaf0', outline='#38332e', width=5)
    draw.text((130,180), '程序绘制 · 演示素材', fill='#b3352c', font=font)
    draw.text((130,290), '完整图片 / 安全构图', fill='#38332e', font=font)
    draw.text((130,390), '独立文字卡 / 快切', fill='#38332e', font=font)
    draw.ellipse((940,290,1340,690), fill='#a5ada4', outline='#38332e', width=9)
    draw.line((910,680,1370,270), fill='#b3352c', width=12)
    draw.text((90,910), '历史音频仅用于渲染验收 · 非实时财经内容', fill='#38332e', font=font)
    img.save(materials / 'demo.png')
    ffmpeg = video / 'node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe'
    subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-loop', '1', '-i', str(materials/'demo.png'), '-t', '8', '-vf', 'scale=1280:720', '-r','30','-pix_fmt','yuv420p',str(materials/'demo.mp4')], check=True)
    selections = [('wb0905205634','b1'), ('wb0905205634','b2'), ('wb0907230359','b2-s1'), ('wb0907230359','b4-s4')]
    methods = ['vox-fast-cut','hand-drawn','upload_image','upload_video']
    beats, overrides, manifest, origins = [], [], {}, []
    for i, ((pid, sid), method) in enumerate(zip(selections, methods),1):
        source = video / 'videos' / pid
        story = json.loads((source/'story.json').read_text(encoding='utf-8'))
        scene = next(s for s in story['scenes'] if s['id']==sid)
        bid, text = f'b{i}', scene['narration']
        audio = source/'audio'/f'{sid}.mp3'
        before = hashlib.sha256(audio.read_bytes()).hexdigest()
        shutil.copy2(audio,audio_dir/f'{bid}.mp3')
        assert before == hashlib.sha256(audio.read_bytes()).hexdigest()
        origins.append({'beat':bid,'source':str(audio),'sha256':before})
        manifest[bid] = hashlib.sha1(text.encode()).hexdigest()[:10]
        beats.append({'id':bid,'role':'setup','narration':text,'on_screen':['历史音频 · 渲染演示'], 'visual_hint':'演示图形'})
        overrides.append({'beat_id':bid,'method':method,**({'file':'demo.mp4' if method=='upload_video' else 'demo.png'} if method!='hand-drawn' else {}), 'kenburns':'none', 'credit':'程序绘制演示素材；历史音频'})
    settings = {'aspect':'16:9','fps':30,'theme':'vox-collage','enrich':'plain','beat_overrides':overrides,'materials_dir':str(materials),'require_selected_audio':True,'image_budget':0}
    story, _ = script_to_story({'title':'混合渲染验收 · 历史音频', 'beats':beats},settings)
    for name,value in [('story.json',story),('project.json',{'id':project.name,'status':'reviewed','title':'隔离混合演示','settings':settings}),('audio/manifest.json',manifest),('demo-origin.json',{'generator':'scripts/demo_mixed_video.py','audio':origins,'visuals':'program-drawn demo assets'})]:
        (project/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    if '--render' in sys.argv or '--workbench' in sys.argv:
        workbench_build(project, beats, overrides, manifest)
    print(project)


def workbench_build(project, beats, overrides, manifest):
    """Drive the real workbench CLI (jobs + make + selected takes). Restores jobs after."""
    from server import config, vstudio
    if vstudio.job_running("build"):
        raise RuntimeError("workbench build job is running; not stealing the slot")
    jobs_file = config.DATA_DIR / "video_jobs.json"
    backup = jobs_file.read_bytes() if jobs_file.is_file() else None
    make_id = None
    try:
        text = "".join(b["narration"] for b in beats)
        row = vstudio.make_upsert({"title": "【验收】混合渲染演示", "narration": {"text": text, "style_id": "vox-doc"}})
        make_id = row["id"]
        row, err = vstudio.lock_narration(make_id)
        if err:
            raise RuntimeError(err)
        script = {"schema": "wb-video-script/v1", "title": "混合渲染验收 · 历史音频", "format": "horizontal",
                  "beats": beats, "word_count": len(text)}
        vstudio.make_upsert({"id": make_id, "script": script})
        row, err = vstudio.lock_script(make_id)
        if err:
            raise RuntimeError(err)
        voice_key = "demo"
        voice_dir = vstudio.voice_root() / make_id / voice_key
        voice_dir.mkdir(parents=True, exist_ok=True)
        items = {}
        for beat in beats:
            src = project / "audio" / f"{beat['id']}.mp3"
            dest = voice_dir / f"{beat['id']}.mp3"
            dest.write_bytes(src.read_bytes())
            items[beat["id"]] = {"file": f"{beat['id']}.mp3", "hash": manifest[beat["id"]]}
        row = vstudio.make_get(make_id)
        row["voice"] = {"profile_id": "", "voice": "archived-take", "voice_key": voice_key, "items": items}
        vstudio._make_save(row)
        png = (project / "input/materials/demo.png").read_bytes()
        mp4 = (project / "input/materials/demo.mp4").read_bytes()
        a1, _ = vstudio.asset_add(make_id, "b1", "demo.png", png)
        a3, _ = vstudio.asset_add(make_id, "b3", "demo.png", png)
        a4, _ = vstudio.asset_add(make_id, "b4", "demo.mp4", mp4)
        mapped = []
        for o in overrides:
            item = dict(o)
            if o["beat_id"] == "b1":
                item["asset_id"] = a1["asset_id"]
            elif o["beat_id"] == "b3":
                item["asset_id"] = a3["asset_id"]
            elif o["beat_id"] == "b4":
                item["asset_id"] = a4["asset_id"]
            mapped.append(item)
        vstudio.make_upsert({"id": make_id, "video": {
            "mode": "edit", "aspect": "16:9", "fps": 30, "theme": "vox-collage", "layout": "auto",
            "enrich": "plain", "generation_method": "inherit", "image_budget": 0,
            "beat_overrides": mapped}})
        vstudio.begin_job("build", {"make_id": make_id, "project_id": project.name, "mode": "build"})
        subprocess.run([sys.executable, str(ROOT / "cli.py"), "workbench", "build-video", "--json"],
                       cwd=ROOT, check=True)
    finally:
        if make_id:
            try:
                vstudio.make_del(make_id)
            except Exception:
                pass
            try:
                shutil.rmtree(vstudio.voice_root() / make_id, ignore_errors=True)
                shutil.rmtree(vstudio.assets_root() / make_id, ignore_errors=True)
            except Exception:
                pass
        if backup is not None:
            jobs_file.write_bytes(backup)


def verify():
    video = ROOT / 'ai-workflow/video'
    project = video / 'videos/demo-mixed-0909'
    out = project / 'out'
    ffmpeg = video / 'node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe'
    ffprobe = ffmpeg.with_name('ffprobe.exe')
    probe = json.loads(subprocess.check_output([str(ffprobe), '-v','error','-show_streams','-show_format','-of','json',str(out/'final.mp4')]))
    stream = next(s for s in probe['streams'] if s['codec_type']=='video')
    assert (stream['width'],stream['height'],stream['r_frame_rate']) == (1920,1080,'30/1')
    assert any(s['codec_type']=='audio' for s in probe['streams'])
    timeline = json.loads((out/'timeline.json').read_text())
    fps = timeline['fps']
    duration = sum(f['durationInFrames'] for f in timeline['frames']) / fps
    assert abs(float(probe['format']['duration'])-duration) < .15
    origins = json.loads((project/'demo-origin.json').read_text())['audio']
    for row in origins:
        for file in [Path(row['source']), project/'audio'/f"{row['beat']}.mp3"]:
            assert hashlib.sha256(file.read_bytes()).hexdigest() == row['sha256'], file
    for scene, frame in zip(json.loads((project/'story.json').read_text(encoding='utf-8'))['scenes'],timeline['frames']):
        assert ''.join(''.join(c['t'].split()) for c in frame['cues']) == ''.join(scene['narration'].split())
        assert frame['cues'][0]['start'] >= frame['leadFrames']
        assert frame['cues'][-1]['end'] <= frame['durationInFrames']
    keys = out / 'keyframes'
    keys.mkdir(exist_ok=True)
    times = [('vox-first', 2), ('vox-second', 5.6), ('vox-third', 8.5)]
    hand_start = timeline['frames'][0]['durationInFrames']/fps
    times += [('hand-early',hand_start+.9),('hand-middle',hand_start+3.3),('hand-late',hand_start+7.8)]
    image_start = sum(f['durationInFrames'] for f in timeline['frames'][:2])/fps
    video_start = sum(f['durationInFrames'] for f in timeline['frames'][:3])/fps
    times += [('upload-image',image_start+1.5),('upload-video',video_start+1.5),('lead-empty',.3),('tail-empty',duration-.3)]
    for name,seconds in times:
        subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(seconds),'-i',str(out/'final.mp4'),'-frames:v','1',str(keys/f'{name}.png')],check=True)
    (out/'probe.json').write_text(json.dumps(probe,indent=2),encoding='utf-8')
    (out/'keyframes.json').write_text(json.dumps(dict(times),indent=2),encoding='utf-8')
    print(json.dumps({'width':stream['width'],'height':stream['height'],'fps':stream['r_frame_rate'],'duration':probe['format']['duration'],'audio':[s['codec_name'] for s in probe['streams'] if s['codec_type']=='audio'],'cue_count':sum(len(f['cues']) for f in timeline['frames']),'keyframes':len(times),'source_audio_hashes':'4/4 unchanged'},ensure_ascii=False))


if __name__ == '__main__':
    verify() if '--verify' in sys.argv else main()
