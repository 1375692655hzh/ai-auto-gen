"""Offline generation capability, cache, and selected take regression."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, vmake, vstudio


class GenerationTests(unittest.TestCase):
    def script(self):
        return {"title":"测试", "beats":[{"id":f"b{i}", "role":"setup", "narration":"完整旁白，数字12.5亿元。继续观察。", "on_screen":["原始标签"]} for i in range(1,7)]}

    def test_mixed_overrides_win_over_global_vox(self):
        script = self.script()
        original = copy.deepcopy(script)
        methods = ['template','vox-fast-cut','hand-drawn','upload_image','upload_video','ai_image']
        overrides = [{"beat_id":f"b{i}","method":method, "file":"asset.mp4" if method=='upload_video' else "asset.png"} if method.startswith('upload_') else {"beat_id":f"b{i}","method":method} for i,method in enumerate(methods,1)]
        story,_ = vmake.script_to_story(script, {"theme":"vox-collage", "beat_overrides":overrides})
        self.assertEqual([s['template'] for s in story['scenes']], ['event','vox-fast-cut','hand-drawn','clip','clip','paper-board'])
        self.assertEqual(script, original)
        for beat,scene in zip(script['beats'],story['scenes']):
            self.assertEqual((beat['id'],beat['narration']), (scene['id'],scene['narration']))
            self.assertEqual(vstudio.voice_hash(beat['narration']),vstudio.voice_hash(scene['narration']))

    def test_default_and_inherit(self):
        story,_=vmake.script_to_story(self.script(), {'generation_method':'hand-drawn','beat_overrides':[{'beat_id':'b1','method':'template'},{'beat_id':'b2','method':'inherit'}]})
        self.assertEqual(story['scenes'][0]['template'],'event')
        self.assertTrue(all(s['template']=='hand-drawn' for s in story['scenes'][1:]))

    def test_vox_collage_method_keeps_parent_audio_identity(self):
        story,_=vmake.script_to_story(self.script(), {'generation_method':'vox-collage','beat_overrides':[{'beat_id':'b2','method':'vox-fast-cut'}]})
        self.assertEqual(story['scenes'][0]['template'],'paper-board')
        self.assertEqual(story['scenes'][1]['template'],'vox-fast-cut')
        self.assertEqual([s['id'] for s in story['scenes']],[b['id'] for b in self.script()['beats']])
        self.assertEqual([s['narration'] for s in story['scenes']],[b['narration'] for b in self.script()['beats']])

    def test_presets_registry_and_invalid_method(self):
        with patch.object(config,'load', return_value=copy.deepcopy(config.DEFAULTS)):
            self.assertEqual(vstudio.build_presets()['generation_methods'],vmake.GENERATION_METHODS)
        with self.assertRaisesRegex(ValueError,'不支持画幅'):
            vmake.script_to_story(self.script(), {'beat_overrides':[{'beat_id':'b1','method':'unknown'}]})

    def test_dashscope_without_local_key_never_switches_to_edge(self):
        with patch.object(vmake,'dashscope_key_ok',return_value=False):
            story,_=vmake.script_to_story(self.script(),{'tts_provider':'dashscope','voice':'longanlufeng'})
        self.assertEqual(story['meta']['tts']['provider'],'dashscope')

    def test_cached_images_across_projects_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def generate(prompt,dest):
                dest.write_bytes(b'offline image fixture '+prompt.encode())
            with patch.object(vmake,'VIDEOS_DIR',root/'projects'), patch.object(config,'DATA_DIR',root/'data'), patch.object(vstudio,'_gen_collage_image',side_effect=generate) as gen:
                script=self.script()
                story,_=vmake.script_to_story(script,{'theme':'vox-collage'})
                vstudio._fill_collage_images('one',story,[],1)
                self.assertEqual(gen.call_count,1) # Six identical prompts share one image.
                vstudio._fill_collage_images('two',story,[],0)
                self.assertEqual(gen.call_count,1)
                self.assertEqual(len(list((root/'projects/two/input/collage').glob('*.jpeg'))),6)
                changed=copy.deepcopy(story)
                changed['scenes'][0]['data']['image_prompt']='different'
                with self.assertRaisesRegex(ValueError,'预算不足'):
                    vstudio._fill_collage_images('three',changed,[],0)
                before = (root/'projects/one/input/collage/b1.jpeg').read_bytes()
                with self.assertRaisesRegex(ValueError,'预算不足'):
                    vstudio._fill_collage_images('one',changed,[],0)
                self.assertEqual((root/'projects/one/input/collage/b1.jpeg').read_bytes(), before)
                gen.side_effect=RuntimeError('offline fixture failure')
                with self.assertRaisesRegex(RuntimeError,'已完成缓存保留'):
                    vstudio._fill_collage_images('three',changed,[],1)
                self.assertEqual(len(list((root/'data/image_cache').glob('*.jpeg'))),1)
                gen.side_effect=generate
                vstudio._fill_collage_images('three',changed,[],1)
                self.assertEqual(gen.call_count,3)
                self.assertEqual(len(list((root/'data/image_cache').glob('*.jpeg'))),2)

    def test_handdraw_skips_llm_and_rejects_material(self):
        with patch.object(vmake, '_llm_compose_scenes', side_effect=AssertionError('no external API')):
            story, _ = vmake.script_to_story(self.script(), {'generation_method':'hand-drawn','enrich':'llm'})
        self.assertTrue(all(s['template']=='hand-drawn' for s in story['scenes']))
        with self.assertRaisesRegex(ValueError,'不接受外部素材'):
            vmake.script_to_story(self.script(), {'beat_overrides':[{'beat_id':'b1','method':'hand-drawn','file':'../bad.png'}]})

    def test_cache_path_escape_rejected_without_api(self):
        story,_=vmake.script_to_story(self.script(),{'theme':'vox-collage'})
        story['scenes'][0]['data']['image']='../../outside.jpeg'
        with tempfile.TemporaryDirectory() as tmp, patch.object(vmake,'VIDEOS_DIR',Path(tmp)), patch.object(vstudio,'_gen_collage_image') as gen:
            with self.assertRaisesRegex(ValueError,'越界'):
                vstudio._fill_collage_images('one',story,[],6)
            gen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
