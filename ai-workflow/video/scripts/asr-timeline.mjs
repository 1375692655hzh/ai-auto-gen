// ASR 全轨钉词薄封装(视频制作·音频路线, 2026-09-15): 已知文本(mimo 转写+人工校对)
// + 整条上传音频 → 句级时间轴。
// 短轨(≤150s)直接走 align.mjs 的 ensurePhraseTimeline(whisper token 时钟+缓存);
// 长轨(2026-09-17 P1 分段对齐)改为: 静音中点切段(段长目标 110s/上限 140s, 段界天然在
// 停顿处) → 每段 whisper 转写 → token 时间戳平移段偏移拼回全轨流, 并丢弃落在静音区间内
// 的 token(静音里没有语音, 落进去的必为段内幻觉残片) → 与 align.mjs 同款成本比例映射
// 出句级 phrases。
// 动机: 13 分钟整轨喂 whisper 幻觉严重(token/旁白比 3.60 出闸), ≤2min 段内幻觉概率
// 骤降(build 期逐幕 8-25s 对齐零幻觉实证); 分段后全轨时间轴由估算变精确, 切幕回到窄窗。
// job: {audio_file, narration, scene_id?, result_file}
//   → result: {ok, phrases[], audioDuration, matchRate, cacheHit, segments?, error?}
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { FFPROBE } from "./tts-engines.mjs";
import { N } from "./normalize-text.mjs";
import {
	ensurePhraseTimeline,
	phraseTimelineMeta,
	splitPhrases,
	tokenCost,
	findToken,
	interpolateMissing,
	makeMonotonic,
	hash16,
	transcribeAudio,
} from "./align.mjs";

const SEG_THRESHOLD = 150; // ≤150s 走整轨原路(短音频已实证)
const TARGET_SEG = 110, MIN_SEG = 35, MAX_SEG = 140;
const SEG_SCHEMA = 1;
const SILENCE_DB = -40, SILENCE_MIN_D = 0.35; // 与 workbench _speech_regions 同口径

const FFMPEG_BASE = FFPROBE.replace(/ffprobe(\.exe)?$/i, "ffmpeg$1");
function resolveFfmpeg() {
	// 系统完整版优先(compositor 精简版缺滤镜前科, 与 cut-audio.mjs 同策略)
	const where = spawnSync("where", ["ffmpeg"], { encoding: "utf8", shell: true });
	const sys = (where.stdout ?? "").split(/\r?\n/)[0]?.trim();
	return where.status === 0 && sys && existsSync(sys) ? sys : FFMPEG_BASE;
}
const probeDuration = (file) =>
	Number(spawnSync(FFPROBE, ["-v", "error", "-show_entries", "format=duration",
		"-of", "csv=p=0", file], { encoding: "utf8" }).stdout?.trim()) || 0;

/** silencedetect 静音区间 [[start,end]…]; 探测不可用返回 null(切段退化为硬切) */
function detectSilences(ff, file) {
	const det = spawnSync(ff, ["-hide_banner", "-i", file,
		"-af", `silencedetect=noise=${SILENCE_DB}dB:d=${SILENCE_MIN_D}`, "-f", "null", "-"],
		{ encoding: "utf8" });
	const log = `${det.stdout ?? ""}\n${det.stderr ?? ""}`;
	if (det.error || !/silence_/.test(log)) return null;
	const starts = [...log.matchAll(/silence_start:\s*([\d.]+)/g)].map((m) => Number(m[1]));
	const ends = [...log.matchAll(/silence_end:\s*([\d.]+)/g)].map((m) => Number(m[1]));
	if (starts.length > ends.length) ends.push(probeDuration(file));
	return starts.slice(0, ends.length).map((s, i) => [s, ends[i]]);
}

/** 段规划: 贪心, 每个下界取与 (cursor+MIN_SEG, cursor+MAX_SEG) 相交静音里最接近
 * cursor+TARGET 的中点; 无静音可用则硬切在锚点; 尾段吃剩余(≤MAX_SEG)。 */
function planSegments(duration, silences) {
	const bounds = [];
	let cursor = 0;
	while (duration - cursor > MAX_SEG) {
		const anchor = cursor + TARGET_SEG;
		let best = null;
		if (silences) {
			for (const [s, e] of silences) {
				const lo = Math.max(s, cursor + MIN_SEG), hi = Math.min(e, cursor + MAX_SEG);
				if (hi <= lo) continue;
				const mid = (lo + hi) / 2;
				if (!best || Math.abs(mid - anchor) < Math.abs(best - anchor)) best = mid;
			}
		}
		const cut = best ?? anchor;
		bounds.push(cut);
		cursor = cut;
	}
	const starts = [0, ...bounds];
	return starts.map((s, i) => ({ start: s, end: i + 1 < starts.length ? starts[i + 1] : duration }));
}

/** 长轨分段对齐主链: 成功填 out.phrases/audioDuration/matchRate/segments 并写缓存, 失败抛错。 */
async function pinSegmented(job, ff, out, dir, ctx) {
	const fullWav = path.join(dir, `${job.scene_id || "asr-full"}.seg.tmp.wav`);
	try {
		// 1) 整轨 16k 单声道 wav(whisper 输入格式, 一次转换所有段共用)
		const conv = spawnSync(ff, ["-hide_banner", "-loglevel", "error", "-y", "-i", job.audio_file,
			"-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", fullWav], { encoding: "utf8" });
		const duration = probeDuration(fullWav);
		if (conv.status !== 0 || !(duration > 1)) {
			throw new Error(`音频转 wav 失败: ${(conv.stderr || "").trim().slice(0, 120)}`);
		}

		// 2) 静音图 + 段规划
		const silences = detectSilences(ff, fullWav);
		const segments = planSegments(duration, silences);
		const inSilence = (sec) => {
			if (!silences) return false;
			for (const [s, e] of silences) {
				if (sec < s) return false;
				if (sec <= e) return true;
			}
			return false;
		};

		// 3) 逐段转写: token 平移段偏移拼回全轨坐标, 落在静音区间内的丢弃
		const tokens = [];
		for (let i = 0; i < segments.length; i++) {
			const seg = segments[i];
			const segWav = path.join(dir, `${job.scene_id || "asr-full"}.seg${i}.tmp.wav`);
			try {
				spawnSync(ff, ["-hide_banner", "-loglevel", "error", "-y",
					"-ss", seg.start.toFixed(3), "-t", (seg.end - seg.start).toFixed(3),
					"-i", fullWav, "-c:a", "pcm_s16le", segWav], { encoding: "utf8" });
				const result = await transcribeAudio(segWav);
				for (const token of result.transcription) {
					if (tokenCost(token.text) === 0) continue;
					const from = Number(token.offsets.from) + seg.start * 1000;
					const to = Math.max(from + 1, Number(token.offsets.to) + seg.start * 1000);
					if (inSilence((from + to) / 2000)) continue;
					tokens.push({ text: token.text, from, to });
				}
			} finally {
				rmSync(segWav, { force: true });
			}
		}
		if (tokens.length === 0) throw new Error("分段转写无有效 token");

		// 4) 与 align.mjs 同款: 成本累积 → 幻觉闸门 → 比例映射句级 phrases
		let cumulativeCost = 0;
		const costed = tokens.map((token) => {
			const entry = { ...token, costStart: cumulativeCost, costEnd: cumulativeCost + tokenCost(token.text) };
			cumulativeCost = entry.costEnd;
			return entry;
		});
		const normalizedNarration = N(job.narration);
		const narrationLength = [...normalizedNarration].length;
		const ratio = narrationLength > 0 ? cumulativeCost / narrationLength : 0;
		const phraseTexts = splitPhrases(job.narration);
		const totalPhraseLength = phraseTexts.reduce((sum, text) => sum + [...N(text)].length, 0);
		if (narrationLength === 0 || totalPhraseLength === 0 || ratio < ctx.minRate || ratio > 1.6) {
			throw new Error(`align_failed token/旁白比 ${ratio.toFixed(2)}`);
		}
		let cursor = 0;
		let matchedCharacters = 0;
		const phrases = phraseTexts.map((text, id) => {
			const normalized = N(text);
			const startIndex = normalizedNarration.indexOf(normalized, cursor);
			if (!normalized || startIndex < 0) return { id, text, startSec: null, endSec: null };
			const endIndex = startIndex + [...normalized].length - 1;
			const startToken = findToken(costed, startIndex * cumulativeCost / narrationLength);
			const endToken = findToken(costed, endIndex * cumulativeCost / narrationLength);
			cursor = endIndex + 1;
			matchedCharacters += [...normalized].length;
			const startSec = startToken.from / 1000;
			const endSec = Math.max(endToken.to / 1000, startSec + 0.08);
			return { id, text, startSec, endSec };
		});
		const matchRate = matchedCharacters / totalPhraseLength;
		if (matchRate < ctx.minRate) throw new Error(`align_failed 匹配率 ${matchRate.toFixed(2)}`);

		interpolateMissing(phrases, duration);
		makeMonotonic(phrases, duration);
		out.phrases = phrases.map((p) => ({ id: p.id, text: p.text,
			start: Number(p.startSec.toFixed(3)), end: Number(p.endSec.toFixed(3)) }));
		out.audioDuration = Number(duration.toFixed(3));
		out.matchRate = Number(matchRate.toFixed(3));
		out.segments = segments.length;
		writeFileSync(ctx.cacheFile, JSON.stringify({
			segSchema: SEG_SCHEMA, targetSeg: TARGET_SEG,
			audioHash: ctx.audioHash, narrationHash: ctx.narrationHash,
			audioDuration: out.audioDuration, matchRate: out.matchRate,
			segments: out.segments, phrases: out.phrases,
		}) + "\n");
	} finally {
		rmSync(fullWav, { force: true });
	}
}

const [jobFile] = process.argv.slice(2);
const job = JSON.parse(readFileSync(jobFile, "utf8"));
const out = { ok: false, phrases: [], audioDuration: 0, matchRate: null, cacheHit: false, error: "" };
const writeResult = () => writeFileSync(job.result_file, JSON.stringify(out) + "\n");

try {
	const duration = probeDuration(job.audio_file);
	if (!(duration > 0.3)) throw new Error(`无法读取音频时长: ${duration}`);

	if (duration <= SEG_THRESHOLD) {
		// 短轨: 原整轨路径(缓存/闸门口径与 0915 版完全一致)
		const timeline = await ensurePhraseTimeline(
			{ id: job.scene_id || "asr-full", narration: job.narration }, job.audio_file, 30);
		if (timeline) {
			const meta = phraseTimelineMeta(timeline) || {};
			out.ok = true;
			out.phrases = timeline.phrases.map((p) => ({ id: p.id, text: p.text, start: p.startSec, end: p.endSec }));
			out.audioDuration = timeline.audioDuration;
			out.matchRate = typeof meta.matchRate === "number" ? Number(meta.matchRate.toFixed(3)) : null;
			out.cacheHit = !!meta.cacheHit;
			out.segments = 1;
		} else {
			out.error = "align_failed";
		}
	} else {
		// 长轨: 分段对齐(缓存键 = 音频哈希+文稿哈希+段参数)
		const dir = path.dirname(path.resolve(job.audio_file));
		const cacheFile = path.join(dir, `${job.scene_id || "asr-full"}.seg.json`);
		const ctx = {
			audioHash: hash16(readFileSync(job.audio_file)),
			narrationHash: hash16(job.narration ?? ""),
			minRate: Number.isFinite(Number(process.env.ALIGN_MIN_RATE)) ? Number(process.env.ALIGN_MIN_RATE) : 0.6,
			cacheFile,
		};
		try {
			const cached = JSON.parse(readFileSync(cacheFile, "utf8"));
			if (cached.audioHash === ctx.audioHash && cached.narrationHash === ctx.narrationHash
				&& cached.segSchema === SEG_SCHEMA && cached.targetSeg === TARGET_SEG) {
				out.ok = true;
				out.phrases = cached.phrases;
				out.audioDuration = cached.audioDuration;
				out.matchRate = cached.matchRate;
				out.cacheHit = true;
				out.segments = cached.segments;
			}
		} catch { /* 无缓存/损坏 → 重建 */ }
		if (!out.ok) {
			await pinSegmented(job, resolveFfmpeg(), out, dir, ctx);
			out.ok = true;
		}
	}
} catch (e) {
	out.ok = false;
	out.error = String(e && e.message ? e.message : e).slice(0, 200);
}
writeResult();
console.log(out.ok
	? `ASR 钉词完成: ${out.phrases.length} 句 / ${out.audioDuration}s / ${out.segments ?? 1} 段${out.cacheHit ? " (缓存)" : ""}`
	: `ASR 钉词失败: ${out.error}`);
