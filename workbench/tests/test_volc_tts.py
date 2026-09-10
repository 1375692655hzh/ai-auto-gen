"""Offline Volc protocol and configuration regression checks."""
import importlib.util
import asyncio
import json
from pathlib import Path
import struct
import sys
import unittest
import tempfile
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, vmake

SCRIPT = Path(__file__).resolve().parents[2] / "ai-workflow/video/scripts/volc-tts.py"
spec = importlib.util.spec_from_file_location("volc_tts", SCRIPT)
volc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(volc)


class VolcTests(unittest.TestCase):
    def test_frame_layout(self):
        for event in (1, 2, 50, 51, 52, 100, 102, 150, 152, 153, 200):
            expected = b"\x11\x14\x10\x00" + struct.pack(">i", event)
            if event not in (1, 2, 50, 51, 52):
                expected += struct.pack(">I", 3) + b"sid"
            self.assertEqual(volc.frame(event, "sid", b"{}"), expected + struct.pack(">I", 2) + b"{}")

    def test_audio_and_error_frames(self):
        frame = bytearray(volc.frame(352, "sid", b"audio"))
        frame[1] = 0xB4
        self.assertEqual(volc.parse(frame), (11, 4, 352, 0, b"audio"))
        error = b"\x11\xf0\x10\x00" + struct.pack(">II", 123, 3) + b"bad"
        self.assertEqual(volc.parse(error), (15, 0, 0, 123, b"bad"))

    def test_settings_and_story_preserve_volc_without_secrets(self):
        provider = config._tts_provider({}, {"id": "volc", "engine": "volc", "api_key": "test-only"})
        self.assertEqual(provider["engine"], "volc")
        meta = vmake._build_meta({}, {"tts_provider": "volc"}, "16:9", 30, "default", "default")
        self.assertEqual(meta["tts"], {"provider": "volc", "voice": "zh_male_liufei_uranus_bigtts"})
        self.assertNotIn("api_key", meta["tts"])

    def test_handshake_sends_three_frames_without_waiting_for_session_started(self):
        sent = []

        class Socket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send(self, data):
                sent.append(volc.parse(data))

            async def recv(self):
                if len(sent) == 1:
                    return volc.frame(50, "", b"{}")
                self_check.assertEqual([f[2] for f in sent], [1, 100, 200, 102])
                if not getattr(self, "audio_sent", False):
                    self.audio_sent = True
                    data = bytearray(volc.frame(352, "sid", b"fake-audio"))
                    data[1] = 0xB4
                    return data
                return volc.frame(152, "sid", b"{}")

        self_check = self
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "test.mp3"
            with patch.dict(sys.modules, {"websockets": SimpleNamespace(connect=lambda *a, **kw: Socket())}), \
                    patch.multiple(volc, KEY="test-only", TEXT="test narration", VOICE="test voice", OUT=str(out)):
                asyncio.run(volc.main())
            self.assertEqual(out.read_bytes(), b"fake-audio")
            self.assertFalse(out.with_name("test.mp3.tmp").exists())
        start = json.loads(sent[1][4])
        task = json.loads(sent[2][4])
        self.assertNotIn("tts_request", start)
        self.assertNotIn("text", start["req_params"])
        self.assertEqual(start["req_params"]["speaker"], "test voice")
        self.assertEqual(task, {"req_params": {"text": "test narration"}})
