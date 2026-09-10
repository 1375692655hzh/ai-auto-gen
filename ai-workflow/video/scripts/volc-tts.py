# 火山引擎豆包语音合成大模型 2.0 · WebSocket 双向流式合成（自包含，供 build.mjs 调用）
# 用法: py -3.12 scripts/volc-tts.py <text> <voice> <out.mp3>
# 鉴权: 环境变量 VOLC_TTS_API_KEY（新版控制台 API Key，X-Api-Key 单头）
# 依赖: py -3.12 -m pip install websockets
# 失败约定: 一切失败以 "VOLC_EMPTY:" 前缀打印并 exit 1（build 据此快速降级，不重试）
import asyncio
import json
import os
import struct
import sys
import uuid

KEY = os.environ.get("VOLC_TTS_API_KEY", "")
RESOURCE = "seed-tts-2.0"
TEXT = sys.argv[1] if len(sys.argv) > 1 else ""
VOICE = sys.argv[2] if len(sys.argv) > 2 else "zh_male_liufei_uranus_bigtts"
OUT = sys.argv[3] if len(sys.argv) > 3 else "volc-tts-out.mp3"

CONN_EVENTS = {1, 2, 50, 51, 52}


def frame(event: int, session_id: str, payload: bytes) -> bytes:
    head = bytes([0x11, 0x14, 0x10, 0x00])  # v1 · size4 · FullClientRequest|WithEvent · JSON|none
    out = head + struct.pack(">i", event)
    if event not in CONN_EVENTS:
        sid = session_id.encode("utf-8")
        out += struct.pack(">I", len(sid)) + sid
    out += struct.pack(">I", len(payload)) + payload
    return out


def parse(data: bytes):
    header_size = (data[0] & 0x0F) * 4
    mtype = data[1] >> 4
    flags = data[1] & 0x0F
    off = header_size
    event = 0
    err = 0
    if mtype == 15:
        err = struct.unpack(">I", data[off : off + 4])[0]
        off += 4
    elif mtype in (1, 2, 9, 11, 12) and flags in (1, 3):
        off += 4
    if flags == 4:
        event = struct.unpack(">i", data[off : off + 4])[0]
        off += 4
        if event not in CONN_EVENTS:
            slen = struct.unpack(">I", data[off : off + 4])[0]
            off += 4
            if slen:
                off += slen
    plen = struct.unpack(">I", data[off : off + 4])[0]
    off += 4
    return mtype, flags, event, err, data[off : off + plen]


def fail(msg: str):
    print(msg.replace(KEY, "[redacted]") if KEY else msg)
    sys.exit(1)


async def main():
    import websockets

    if not KEY:
        fail("VOLC_EMPTY: 缺少 VOLC_TTS_API_KEY（写入引擎根目录 .env）")
    if not TEXT or not OUT:
        fail("VOLC_EMPTY: 参数不足（text / out 必填）")
    url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    headers = {"X-Api-Key": KEY, "X-Api-Resource-Id": RESOURCE}
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        await ws.send(frame(1, "", b"{}"))
        print("  -> StartConnection", file=sys.stderr)
        first = parse((await asyncio.wait_for(ws.recv(), timeout=45)))
        if first[2] != 50:
            fail(f"VOLC_EMPTY: 首帧非 ConnectionStarted（event={first[2]}）: {first[4][:200].decode('utf-8', 'ignore')}")
        audio = bytearray()
        session = str(uuid.uuid4())
        cfg = json.dumps({
            "user": {"uid": "ai-auto-gen"},
            "req_params": {
                "speaker": VOICE,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }).encode("utf-8")
        task = json.dumps({"req_params": {"text": TEXT}}).encode("utf-8")
        await ws.send(frame(100, session, cfg))
        print("  -> StartSession", file=sys.stderr)
        await ws.send(frame(200, session, task))
        print("  -> TaskRequest", file=sys.stderr)
        await ws.send(frame(102, session, b"{}"))
        print("  -> FinishSession", file=sys.stderr)
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=45)
            if isinstance(raw, str):
                continue
            mtype, _flags, event, err, payload = parse(raw)
            print(f"  <- type={mtype} flags={_flags} event={event} payload={len(payload)}", file=sys.stderr)
            if mtype == 15:
                fail(f"VOLC_EMPTY: volc code {err}: {payload[:300].decode('utf-8', 'ignore')}")
            if event in (51, 153):
                fail(f"VOLC_EMPTY: volc failed event {event}: {payload[:300].decode('utf-8', 'ignore')}")
            if mtype == 11 and payload:
                audio += payload
            if event in (152, 52):
                break
        if not audio:
            fail("VOLC_EMPTY: 火山返回空音频（控制台核对服务开通/额度/Key 关联服务）")
        from pathlib import Path
        target = Path(OUT)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_bytes(audio)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"OK {len(audio)} bytes")


if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=120))
    except Exception as exc:
        reason = "WS session timeout" if isinstance(exc, TimeoutError) else str(exc)
        fail(f"VOLC_EMPTY: {type(exc).__name__}: {reason}")
