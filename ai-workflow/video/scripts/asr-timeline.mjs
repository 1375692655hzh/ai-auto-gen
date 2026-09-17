// ASR 全轨钉词薄封装(视频制作·音频路线, 2026-09-15): 已知文本(mimo 转写+人工校对)
// + 整条上传音频 → 句级时间轴。复用 align.mjs 的 ensurePhraseTimeline(whisper token
// 时钟 + audioHash/narrationHash 缓存), 不重复造对齐轮子。
// job: {audio_file, narration, scene_id?, result_file} → result: {ok, phrases[], audioDuration, matchRate, cacheHit, error?}
import { readFileSync, writeFileSync } from "node:fs";
import { ensurePhraseTimeline, phraseTimelineMeta } from "./align.mjs";

const [jobFile] = process.argv.slice(2);
const job = JSON.parse(readFileSync(jobFile, "utf8"));
const out = { ok: false, phrases: [], audioDuration: 0, matchRate: null, cacheHit: false, error: "" };
try {
	const timeline = await ensurePhraseTimeline(
		{ id: job.scene_id || "asr-full", narration: job.narration }, job.audio_file, 30);
	if (timeline) {
		const meta = phraseTimelineMeta(timeline) || {};
		out.ok = true;
		out.phrases = timeline.phrases.map((p) => ({ id: p.id, text: p.text, start: p.startSec, end: p.endSec }));
		out.audioDuration = timeline.audioDuration;
		out.matchRate = typeof meta.matchRate === "number" ? Number(meta.matchRate.toFixed(3)) : null;
		out.cacheHit = !!meta.cacheHit;
	} else {
		out.error = "align_failed";
	}
} catch (e) {
	out.error = String(e && e.message ? e.message : e).slice(0, 200);
}
writeFileSync(job.result_file, JSON.stringify(out) + "\n");
console.log(out.ok
	? `ASR 钉词完成: ${out.phrases.length} 句 / ${out.audioDuration}s${out.cacheHit ? " (缓存)" : ""}`
	: `ASR 钉词失败: ${out.error}`);
