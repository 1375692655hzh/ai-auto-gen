// 原声切幕器(视频制作·音频路线, 2026-09-15 三岗复合定案):
// 上传音频按分镜时间窗切成逐幕 mp3 —— 产物与 TTS take 同构(裸 mp3, manifest 由
// Python 拷贝链写, 不写 .tts.json sidecar), 另写逐幕 .alignment.json(whisper 轨,
// 10 位 narrationHash=hashNarration 与 build.mjs 同口径, 未裁剪坐标) + cuts.json。
// 切点策略: 每个边界先在 ±window 找 ≥80ms 静音中点(-42dB/80ms 与 build.mjs trimSilence
// 同口径) → 扩窗 ±expand → 仍无 → 硬切兜底(10ms afade 防爆音不啃词头 + libmp3lame)。
// 静音窗路径 -c copy 零重编码; wav 源必须重编码(mp3 目标)。
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { FFPROBE, hashNarration } from "./tts-engines.mjs";

const FFMPEG_BASE = FFPROBE.replace(/ffprobe(\.exe)?$/i, "ffmpeg$1");
function resolveFfmpeg() {
	// 系统完整版优先(compositor 精简版缺滤镜前科, 与 build.mjs resolveTrimFfmpeg 同策略)
	const where = spawnSync("where", ["ffmpeg"], { encoding: "utf8", shell: true });
	const sys = (where.stdout ?? "").split(/\r?\n/)[0]?.trim();
	return where.status === 0 && sys && existsSync(sys) ? sys : FFMPEG_BASE;
}
const probeDuration = (file) =>
	Number(spawnSync(FFPROBE, ["-v", "error", "-show_entries", "format=duration",
		"-of", "csv=p=0", file], { encoding: "utf8" }).stdout?.trim()) || 0;

const [planFile] = process.argv.slice(2);
const plan = JSON.parse(readFileSync(planFile, "utf8"));
const result = { ok: false, items: {}, cuts: [], silences: null, error: "" };
const writeResult = () => writeFileSync(plan.result_file, JSON.stringify(result) + "\n");

const ff = resolveFfmpeg();
const sourceDuration = probeDuration(plan.source);
if (!(sourceDuration > 0.3)) {
	result.error = `无法读取源音频时长: ${plan.source}`;
	writeResult();
	console.error(result.error);
	process.exit(1);
}

// 1) 全轨静音图(一次探测, 所有边界共用)
const det = spawnSync(ff, ["-hide_banner", "-i", plan.source,
	"-af", "silencedetect=noise=-42dB:d=0.08", "-f", "null", "-"], { encoding: "utf8" });
const log = `${det.stdout ?? ""}\n${det.stderr ?? ""}`;
if (!det.error && /silence_/.test(log)) {
	result.silences = [...log.matchAll(/silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)/g)]
		.map((m) => [Number(m[1]), Number(m[2])]);
}

const W = plan.window ?? 0.3, X = plan.expand ?? 0.6, FADE = (plan.fade_ms ?? 10) / 1000;
const silenceMid = (t, win) => {          // t±win 内找静音段与窗相交部分的中点, 取最近者
	if (!result.silences) return null;
	let best = null;
	for (const [s, e] of result.silences) {
		if (e < t - win || s > t + win) continue;
		const mid = (Math.max(s, t - win) + Math.min(e, t + win)) / 2;
		if (!best || Math.abs(mid - t) < Math.abs(best - t)) best = mid;
	}
	return best;
};

// 2) 边界序列: 首幕起点 + 相邻幕中点; 逐级找静音, 兜底硬切
const scenes = plan.cuts;
const bounds = [scenes[0].start];
for (let i = 1; i < scenes.length; i++)
	bounds.push((scenes[i - 1].end + scenes[i].start) / 2);
const points = bounds.map((t) => {
	let cut = silenceMid(t, W), mode = "silence";
	if (cut === null) cut = silenceMid(t, X);
	if (cut === null) { cut = t; mode = "hard"; }
	return { t, cut, mode };
});
// 单调钳位: 静音中点把两幕切重叠时强制拉开
for (let i = 1; i < points.length; i++)
	if (points[i].cut <= points[i - 1].cut) {
		points[i].cut = points[i - 1].cut + 0.05;
		points[i].mode = "hard";
	}

// 3) 逐幕落盘
for (let i = 0; i < scenes.length; i++) {
	const s = scenes[i];
	const from = points[i].cut;
	const to = i === scenes.length - 1 ? sourceDuration : points[i + 1].cut;
	const len = Math.max(0.2, to - from);
	const out = path.join(plan.out_dir, `${s.id}.mp3`);
	const needFade = points[i].mode === "hard"
		|| (i < scenes.length - 1 && points[i + 1].mode === "hard");
	const needReencode = plan.source_format === "wav" || needFade;
	const filters = [];
	if (needFade && points[i].mode === "hard") filters.push(`afade=t=in:st=0:d=${FADE}`);
	if (needFade && i < scenes.length - 1 && points[i + 1].mode === "hard")
		filters.push(`afade=t=out:st=${Math.max(0, len - FADE).toFixed(3)}:d=${FADE}`);
	const argv = needReencode
		? ["-hide_banner", "-loglevel", "error", "-y",
		   "-ss", from.toFixed(3), "-t", len.toFixed(3), "-i", plan.source,
		   ...(filters.length ? ["-af", filters.join(",")] : []),
		   "-c:a", "libmp3lame", "-q:a", "2", out]
		: ["-hide_banner", "-loglevel", "error", "-y",
		   "-ss", from.toFixed(3), "-t", len.toFixed(3), "-i", plan.source, "-c", "copy", out];
	const r = spawnSync(ff, argv, { encoding: "utf8" });
	const duration = probeDuration(out);
	if (r.status !== 0 || !existsSync(out) || !(duration > 0.1)) {
		result.error = `cut_failed ${s.id}: ${((r.stderr || r.stdout || "").trim().slice(-140))}`;
		writeResult();
		console.error(result.error);
		process.exit(1);
	}
	result.items[s.id] = { file: path.basename(out), duration: Number(duration.toFixed(3)),
		               cut_mode: needReencode ? (needFade ? "hard" : "reencode") : "silence" };
	result.cuts.push({ id: s.id, start: Number(from.toFixed(3)), end: Number(to.toFixed(3)),
		               duration: Number(duration.toFixed(3)), text: s.text,
		               cut_mode: result.items[s.id].cut_mode,
		               boundary_source: points[i].mode, fade_ms: needFade ? plan.fade_ms ?? 10 : 0 });
	// 逐幕 alignment.json: phrases 相对切点(未裁剪坐标, build 期 shiftAudioTrack 再平移);
	// narrationHash 用 hashNarration(与 build.mjs:300 比对同源), 时间戳钳在幕长内不越界
	if (Array.isArray(s.phrases) && s.phrases.length) {
		const segments = s.phrases
			.map((p) => ({ t: p.t, start: Number(Math.max(0, p.start - from).toFixed(3)),
				               end: Number(Math.min(duration, Math.max(0.08, p.end - from)).toFixed(3)) }))
			.filter((p) => p.start < duration);
		if (segments.length)
			writeFileSync(path.join(plan.out_dir, `${s.id}.alignment.json`), JSON.stringify({
				v: 1, unit: "seconds", origin: "audio", source: "whisper",
				narrationHash: hashNarration(s.narration), segments,
			}) + "\n");
	}
}
result.ok = true;
writeResult();
console.log(`切原声完成: ${scenes.length} 幕 (静音窗 ${result.cuts.filter((c) => c.cut_mode === "silence").length} / 硬切 ${result.cuts.filter((c) => c.cut_mode === "hard").length})`);
