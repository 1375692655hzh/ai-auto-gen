// 一键制作流水线：story 校验 -> 审核门禁 -> TTS 补齐(保留供应商) -> 测时长 -> 生成 active-story -> 渲染 -> QA 自检(轻量)
// 用法:
//   node scripts/build.mjs <projectId>            正式制作（要求 status=reviewed）
//   node scripts/build.mjs <projectId> --force    跳过审核门禁
//   node scripts/build.mjs <projectId> --estimate 仅按字数估时长出片（无语音预览用）
//   node scripts/build.mjs <projectId> --no-render 只生成 active-story（配 remotion studio 预览）
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync, statSync, copyFileSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { validateStory } from "./story-validate.mjs";
import { TEMPLATE_IDS } from "./template-ids.mjs";
import { synthOnce, writeSidecar, sidecarPath, matchesSidecar, hashNarration, loadEnv, FFPROBE } from "./tts-engines.mjs";

import { captionTimeline, toSrt } from "../shared/captions.mjs";

loadEnv();

const args = process.argv.slice(2);
const projectId = args.find((a) => !a.startsWith("--"));
if (!projectId || !/^[a-zA-Z0-9_-]+$/.test(projectId)) {
	console.error("用法: node scripts/build.mjs <projectId> [--force] [--estimate] [--no-render] [--keyframes] [--sample=秒]");
	process.exit(1);
}
const FORCE = args.includes("--force");
const ESTIMATE = args.includes("--estimate");
const NO_RENDER = args.includes("--no-render");
const KEYFRAMES = args.includes("--keyframes");
const sampleArg = args.find((a) => a.startsWith("--sample="));
const sampleSeconds = sampleArg ? Number(sampleArg.slice("--sample=".length)) : 0;
const SAMPLE = Number.isFinite(sampleSeconds) && sampleSeconds > 0;

const projDir = path.join("videos", projectId);
const projFile = path.join(projDir, "project.json");
const storyFile = path.join(projDir, "story.json");
for (const f of [projFile, storyFile]) {
	if (!existsSync(f)) {
		console.error(`找不到 ${f} —— 项目不存在？可用 scripts/new-article.mjs 创建。`);
		process.exit(1);
	}
}
const project = JSON.parse(readFileSync(projFile, "utf-8"));
const story = JSON.parse(readFileSync(storyFile, "utf-8"));
const compositionId = "Story";

/* ---- story.json 结构校验（TTS/渲染之前的前置门禁） ---- */
{
	const { errors, warnings } = validateStory(story);
	for (const w of warnings) console.warn(`⚠ ${w}`);
	if (errors.length > 0) {
		for (const e of errors) console.error(`✗ ${e}`);
		console.error(`\nstory.json 校验未通过（${errors.length} 错误）。修好后重跑。`);
		process.exit(1);
	}
	console.log(`✓ story.json 校验通过（${story.scenes.length} 场景${warnings.length ? `，${warnings.length} 警告` : ""}）`);
}

/* ---- 审核门禁 ---- */
if (project.status !== "reviewed" && !FORCE && !ESTIMATE) {
	console.error(
		`✋ 项目状态为 "${project.status}"，未通过人工审核，拒绝制作。\n` +
			`   审核 = 编辑 videos/${projectId}/story.json 的 narration 文本，\n` +
			`   然后把 project.json 的 status 改为 "reviewed"。\n` +
			`   （强制制作加 --force，无声预览加 --estimate）`,
	);
	process.exit(1);
}

const meta = story.meta;
const fps = meta.fps ?? 30;
const TRIM_SILENCE = meta.trimSilence ?? true;      // P1: TTS 头尾静默裁剪总闸(出问题置 false 一键回滚)
const pad = meta.padSeconds ?? 0.25;   // 2026-09-13 节奏收紧(MoA四岗评审): 幕间停顿 ~1.9s→~1.0s
const LEAD_S = meta.leadSeconds ?? 0.4;   // 音频前置静默: 语音开始时画面动画已展开(0.35 会贴着慢弹簧入场"空画面说话", 取 0.45)
// 最短场景兜底(模板感知): versus/stacked/vpoints 最晚入场元素 ~4.7s, 保 5.0; 其余 4.0
const SLOW_TEMPLATES = new Set(["versus", "stacked", "vpoints"]);
const minSceneS = (tpl) => (SLOW_TEMPLATES.has(tpl) ? 5.0 : 4.0);
const audioDir = path.join(projDir, "audio");
mkdirSync(audioDir, { recursive: true });

/* ---- 素材同步：本期仅原样拷贝，不转码 ---- */
function syncMaterials() {
	const srcDir = path.join(projDir, "input", "materials");
	const dstDir = path.join(projDir, "materials");
	if (!existsSync(srcDir)) return;
	mkdirSync(dstDir, { recursive: true });
	for (const name of readdirSync(srcDir)) {
		const src = path.join(srcDir, name);
		if (!statSync(src).isFile()) continue;
		const dst = path.join(dstDir, name);
		if (existsSync(dst) && statSync(dst).mtimeMs >= statSync(src).mtimeMs) continue;
		process.stdout.write(`素材规范化: input/materials/${name} -> materials/${name} ... `);
		copyFileSync(src, dst);
		console.log("ok（直接拷贝）");
	}
}
syncMaterials();

/* ---- 素材存在性硬检查 ---- */
{
	const missing = [];
	for (const s of story.scenes) {
        for (const key of ["src", "image"]) {
            const rel = s.data?.[key];
            if (!rel) continue;
            const file = path.resolve(projDir, rel);
            if (!existsSync(file)) missing.push(`场景 ${s.id}: ${rel}`);
            else {
                const resolved = realpathSync(file).toLowerCase();
                const root = realpathSync(projDir).toLowerCase();
                if (resolved !== root && !resolved.startsWith(root + path.sep)) missing.push(`场景 ${s.id}: 素材越界 ${rel}`);
            }
        }
	}
	if (missing.length > 0) {
		for (const m of missing) console.error(`✗ 素材缺失: ${m}`);
		process.exit(1);
	}
}

/* ---- TTS：补齐缺失音频 ---- */

/** 按项目配置分发引擎（story.json meta.tts：dashscope/custom 走 meta 配置，缺省 edge + meta.voice） */
const ttsConf = (() => {
	const tts = story.meta.tts;
    if (tts?.provider === "volc") return {engine: "volc", voice: tts.voice, customCfg: {api_key: process.env.VOLC_TTS_API_KEY ?? ""}};
	if (tts && tts.provider === "dashscope")
		return { engine: "dashscope", voice: tts.voice ?? "longanlufeng", customCfg: undefined };
	if (tts && tts.provider === "custom")
		return {
			engine: "custom",
			voice: tts.voice ?? "",
			customCfg: {
				base_url: tts.base_url ?? "", model: tts.model ?? "",
				style: tts.style ?? "", format: tts.format ?? "",
				api_key: process.env.CUSTOM_TTS_API_KEY ?? "",   // 密钥经 CLI 注入环境, 不落 story.json
			},
		};
	return { engine: "edge", voice: story.meta.voice ?? "zh-CN-XiaoxiaoNeural", customCfg: undefined };
})();

/** 用指定引擎补齐全部缺失音频；返回 {ok, made[], failedId} */
async function synthAll(engine, voice, customCfg) {
	const made = [];
	for (const s of story.scenes) {
		if (s.silent) continue;                  // 静默场景无旁白，不需要音频
		const outFile = path.join(audioDir, `${s.id}.mp3`);
		if (existsSync(outFile)) {
            if (!existsSync(sidecarPath(outFile)) || matchesSidecar(outFile, engine, voice, s.narration)) continue;
            if (project.settings?.require_selected_audio) throw new Error(`已选语音供应商/音色不匹配: ${s.id}，请重新选择语音 take`);
            rmSync(outFile, {force: true});
        }
		if (project.settings?.require_selected_audio) throw new Error(`已选语音缺失: ${s.id}，请重新选择语音 take`);
		process.stdout.write(`合成语音: ${s.id} ... `);
		if (await synthOnce(engine, voice, s.narration, outFile, customCfg)) {
			writeSidecar(outFile, engine, voice, s.narration);
			console.log("ok");
			made.push(outFile);
		} else {
			return { ok: false, made, failedId: s.id };
		}
	}
	return { ok: true, made };
}

if (!ESTIMATE) {
	console.log(`TTS 引擎: ${ttsConf.engine} · 音色 ${ttsConf.voice}`);
	// 音频缓存清单: {sceneId: narration哈希}, 文本变了只重合成变的场景
	const manifestPath = path.join(audioDir, "manifest.json");
	const manifest = existsSync(manifestPath)
		? JSON.parse(readFileSync(manifestPath, "utf-8"))
		: {};
	for (const s of story.scenes) {
		// 音频缓存按 narration 内容哈希失效: 改稿后复用旧音频会音画错位
		const hash = hashNarration(s.narration);
		const outFile = path.join(audioDir, `${s.id}.mp3`);
		if (existsSync(outFile) && !existsSync(sidecarPath(outFile)) && manifest[s.id] !== hash) {
			throw new Error(`语音已过期或缺少匹配哈希: ${s.id}，请在语音阶段重新选择/生成；保留原音频`);
		}
		manifest[s.id] = hash;
	}
	writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
	let r = await synthAll(ttsConf.engine, ttsConf.voice, ttsConf.customCfg);
	if (!r.ok && ["dashscope", "volc"].includes(ttsConf.engine) && !project.settings?.require_selected_audio) {
        console.warn(`${ttsConf.engine} 不可用，清理本批音频，整批降级 Edge`);
        for (const s of story.scenes) {
            if (s.silent) continue;
            for (const suffix of [".mp3", ".tts.json", ".cues.json", ".alignment.json"])
                rmSync(path.join(audioDir, s.id + suffix), {force: true});
        }
        r = await synthAll("edge", "zh-CN-XiaoxiaoNeural");
    }
    if (!r.ok) {
		console.error(`\n语音合成失败: ${r.failedId}（网络问题可重跑，已有音频会跳过）`);
		process.exit(1);
	}
	if (r.made.length === 0) console.log("语音已全部存在，跳过 TTS");
}

/* ---- 测时长 / 估算时长 ---- */
function probeDuration(file) {
	const out = execFileSync(FFPROBE, [
		"-v",
		"error",
		"-show_entries",
		"format=duration",
		"-of",
		"csv=p=0",
		file,
	]).toString();
	return Number(out.trim());
}

/* ---- P1(2026-09-13 MoA四岗方案): TTS 头尾静默裁剪 ----
   副本落 audio/trim/<id>.mp3, 原件/manifest/对轴 sidecar 一律不动(红线);
   silencedetect 阈值 -42dB, 头留 50ms/尾留 80ms 保护边防切到爆破音起振;
   -ss/-t 流拷贝零重编码; ffmpeg 缺滤镜或探测/裁剪失败 → 返回 null 降级用原件
   (降级模式照抄电平检测: 系统完整版 ffmpeg 优先, compositor 兜底)。
   副本旁写 <id>.mp3.trim.json 缓存(源 mtime+size 命中即复用), 幂等可重跑。 */
let TRIM_FFMPEG;
function resolveTrimFfmpeg() {
	if (TRIM_FFMPEG) return TRIM_FFMPEG;
	const where = spawnSync("where", ["ffmpeg"], { encoding: "utf8", shell: true });
	const sys = (where.stdout ?? "").split(/\r?\n/)[0]?.trim();
	TRIM_FFMPEG = where.status === 0 && sys && existsSync(sys) ? sys
		: FFPROBE.replace(/ffprobe(\.exe)?$/, "ffmpeg$1");
	return TRIM_FFMPEG;
}
function trimSilence(file, dur) {
	if (!(dur > 0.6)) return null;                       // 极短音频不裁
	const st = existsSync(file) ? statSync(file) : null;
	if (!st) return null;
	const cacheFile = `${file}.trim.json`;
	const out = path.join(path.dirname(file), "trim", path.basename(file));
	try {
		const cached = JSON.parse(readFileSync(cacheFile, "utf8"));
		if (cached.mtimeMs === st.mtimeMs && cached.size === st.size && existsSync(out))
			return { audio: `audio/trim/${path.basename(file)}`, duration: cached.duration, head: cached.head };
	} catch { /* 无缓存走探测 */ }
	const ff = resolveTrimFfmpeg();
	const r = spawnSync(ff, ["-hide_banner", "-i", file,
		"-af", "silencedetect=noise=-42dB:d=0.08", "-f", "null", "-"], { encoding: "utf8" });
	const log = `${r.stdout ?? ""}
${r.stderr ?? ""}`;
	if (r.error || !/silence_/.test(log)) return null;   // 无滤镜/无输出 → 降级原件
	const starts = [...log.matchAll(/silence_start: ([\d.]+)/g)].map((m) => +m[1]);
	const ends = [...log.matchAll(/silence_end: ([\d.]+)/g)].map((m) => +m[1]);
	let head = 0, tail = 0;
	if (starts.length && ends.length && starts[0] <= 0.05) head = ends[0] ?? 0;
	if (starts.length > ends.length) {                    // 尾段静默直到 EOF(无 silence_end)
		const lastStart = starts[starts.length - 1];
		if (lastStart >= (ends[ends.length - 1] ?? 0)) tail = dur - lastStart;
	}
	const headCut = Math.max(0, head - 0.05);
	const tailCut = Math.max(0, tail - 0.08);
	if (headCut + tailCut < 0.05) return null;            // 可裁量太小, 跳过
	mkdirSync(path.dirname(out), { recursive: true });
	const cutLen = Math.max(0.1, dur - tailCut - headCut);
	const c = spawnSync(ff, ["-hide_banner", "-loglevel", "error", "-y",
		"-ss", headCut.toFixed(3), "-t", cutLen.toFixed(3), "-i", file, "-c", "copy", out], { encoding: "utf8" });
	if (c.status !== 0 || !existsSync(out)) return null;
	const duration = probeDuration(out);
	if (!(duration > 0.5) || duration >= dur) { try { rmSync(out); } catch {} return null; }
	writeFileSync(cacheFile, JSON.stringify({ mtimeMs: st.mtimeMs, size: st.size, head: headCut, duration }));
	return { audio: `audio/trim/${path.basename(file)}`, duration, head: headCut };
}
// 对轴轨(Edge cues.json / whisper alignment.json)按裁头量平移并钳位到裁后时长——
// cue 一对, SRT/字幕/快切镜头吸附(visualShots)全链路自动对齐; 整条落裁剪区的行丢弃。
function shiftAudioTrack(track, head, newDur) {
	if (!track || !(head > 0)) return track;
	const rows = Array.isArray(track.cues) ? track.cues : Array.isArray(track.segments) ? track.segments : null;
	if (!rows) return track;
	const shifted = [];
	for (const c of rows) {
		const start = Math.max(0, (c.start ?? 0) - head);
		const end = Math.min(newDur, (c.end ?? 0) - head);
		if (end <= start) continue;
		shifted.push({ ...c, start: Number(start.toFixed(3)), end: Number(end.toFixed(3)) });
	}
	if (!shifted.length) return null;
	const next = { ...track };
	if (Array.isArray(track.cues)) next.cues = shifted; else next.segments = shifted;
	return next;
}

/* ---- 引擎无关对轴（whisper.cpp）：无线界引擎(volc/dashscope/custom)的场景补齐 alignment，
 * 字幕与手绘跟随用真实音频时间而不是纯文本权重估算。对齐失败/缺失一律回退估算，不阻断制作。
 * 本机组件不存在时整段跳过（隔离测试环境没有 whisper 二进制，且那里必须保持估算口径）。
 * 注意：本段位于 "/* ---- 测时长" 标记之后 —— tts-volc.test.mjs 按标记切片 vm 执行 TTS 块，勿移回。 ---- */
const whisperReady = ["main.exe", "main"].some((name) =>
	existsSync(path.join("node_modules", ".cache", "whisper-cpp", name)));
if (!ESTIMATE && whisperReady) {
	const { ensurePhraseTimeline } = await import("./align.mjs");
	for (const s of story.scenes) {
		if (s.silent) continue;
		if (existsSync(path.join(audioDir, `${s.id}.cues.json`))) continue;   // Edge 词界轨已存在，优先且更准
		const alignmentFile = path.join(audioDir, `${s.id}.alignment.json`);
		let fresh = false;
		if (existsSync(alignmentFile)) {
			try {
				const saved = JSON.parse(readFileSync(alignmentFile, "utf-8"));
				fresh = saved?.narrationHash === hashNarration(s.narration)
					&& Array.isArray(saved?.segments) && saved.segments.length > 0;
			} catch { fresh = false; }
		}
		if (fresh) continue;
		try {
			const timeline = await ensurePhraseTimeline(s, path.join(audioDir, `${s.id}.mp3`), fps);
			if (timeline) {
				writeFileSync(alignmentFile, JSON.stringify({
					v: 1, unit: "seconds", origin: "audio", source: "whisper", model: timeline.model,
					narrationHash: hashNarration(s.narration),
					segments: timeline.phrases.map((p) => ({ t: p.text, start: p.startSec, end: p.endSec })),
				}, null, 2));
				console.log(`✓ 对轴完成 ${s.id}: ${timeline.phrases.length} 条短语（whisper/${timeline.model}）`);
			} else {
				console.warn(`⚠ 对轴匹配率过低 ${s.id}，字幕回退文本估算`);
			}
		} catch (error) {
			console.warn(`⚠ 对轴失败 ${s.id}: ${String(error?.message ?? error).slice(0, 120)}，字幕回退文本估算`);
		}
	}
} else if (!ESTIMATE && !whisperReady) {
	console.log("对轴：未检测到 whisper.cpp 本地组件，无线界引擎场景字幕按文本估算");
}

const frames = [];
let totalFrames = 0;
for (const s of story.scenes) {
	let dur;
	let audio = null;
	let trimHead = 0;
	if (s.silent) {                      // 静默场景: 固定时长(公告每页5s)
		dur = s.durationS ?? 5;
	} else if (ESTIMATE) {
		dur = Math.max(4, s.narration.length / 4.2);
	} else {
		const file = path.join(audioDir, `${s.id}.mp3`);
		dur = probeDuration(file);
		audio = `audio/${s.id}.mp3`;
		if (TRIM_SILENCE) {                              // P1: 头尾静默裁剪(副本), 原件不动
			const trimmed = trimSilence(file, dur);
			if (trimmed) { audio = trimmed.audio; dur = trimmed.duration; trimHead = trimmed.head; }
		}
	}
	const silent = Boolean(s.silent);
	const visualFrames = Math.ceil((dur + (silent ? 0 : pad + LEAD_S)) * fps);
	const f = Math.max(Math.ceil(minSceneS(s.template) * fps), visualFrames);
	const alignmentFile = path.join(audioDir, `${s.id}.alignment.json`);
	const cuesFile = path.join(audioDir, `${s.id}.cues.json`);
	let providerTrack;
	if (!ESTIMATE && existsSync(cuesFile)) {
		try {
			providerTrack = JSON.parse(readFileSync(cuesFile, "utf-8"));
			if (providerTrack.narrationHash && providerTrack.narrationHash !== hashNarration(s.narration)) providerTrack = {};
		} catch { providerTrack = {}; }
	}
	let alignmentTrack;
	if (!providerTrack && !ESTIMATE && existsSync(alignmentFile)) {
		try {
			const saved = JSON.parse(readFileSync(alignmentFile, "utf-8"));
			if (saved?.narrationHash === hashNarration(s.narration)
				&& Array.isArray(saved?.segments) && saved.segments.length > 0)
				alignmentTrack = saved;
		} catch { /* 损坏或哈希不符的对齐轨按缺失处理，走文本估算 */ }
	}
	if (trimHead > 0) {                                 // P1: 对轴轨随裁头平移+钳位(防末 cue 越界回退估算)
		providerTrack = shiftAudioTrack(providerTrack, trimHead, dur) || undefined;
		alignmentTrack = shiftAudioTrack(alignmentTrack, trimHead, dur) || undefined;
	}
	const subtitles = silent ? {cues: [], method: "silent"} : captionTimeline({
		text: s.narration, duration: dur, fps, lead: LEAD_S, cues: s.captions,
		providerTrack,
		alignment: alignmentTrack,
	});
	frames.push({
		id: s.id,
		template: s.template,
		audio,
		caption: s.caption ?? null,
		cues: subtitles.cues,
		alignmentMethod: subtitles.method,          // 同步字幕轨(帧级起止)
		alignmentWarning: subtitles.warning,
		visualDurationInFrames: visualFrames,
		leadFrames: silent ? 0 : Math.round(LEAD_S * fps),
		audioDuration: Number(dur.toFixed(3)),
		trimHead: Number(trimHead.toFixed(3)) || undefined,
		durationInFrames: f,
	});
	totalFrames += f;
}

mkdirSync(path.join(projDir, "out"), {recursive: true});
writeFileSync(path.join(projDir, "out", "subtitles.srt"), toSrt(frames, fps));
writeFileSync(path.join(projDir, "out", "timeline.json"), JSON.stringify({fps, frames}, null, 2));

/* ---- 生成 src/active-story.ts ---- */
const active = {
	meta: { fps, width: meta.width ?? 1920, height: meta.height ?? 1080, voice: meta.voice,
		theme: meta.theme, layout: meta.layout },
	story,
	frames,
	totalFrames,
};
const ts = `// 由 scripts/build.mjs 自动生成，勿手改
import type { Story } from "./story-types";
export interface ActiveFrame {
	id: string;
	template: string;
	audio: string | null;
	caption: string | null;
	cues?: { t: string; start: number; end: number }[] | null;
	alignmentMethod?: string;
	visualDurationInFrames?: number;
	leadFrames?: number;
	audioDuration: number;
	durationInFrames: number;
}
type ActiveStory = { meta: { fps: number; width: number; height: number; voice: string; theme?: string; layout?: string }; story: Story; frames: ActiveFrame[]; totalFrames: number };
export const ACTIVE = ${JSON.stringify(active, null, "	")} as unknown as ActiveStory;
`;
writeFileSync(path.join("src", "active-story.ts"), ts);

console.log(
	`\n时间轴: ${frames.length} 个场景，共 ${(totalFrames / fps / 60).toFixed(2)} 分钟` +
		(ESTIMATE ? "（估算模式，无音轨）" : ""),
);
for (const f of frames) {
	console.log(`  ${f.id.padEnd(10)} ${f.audioDuration.toFixed(1)}s -> ${f.durationInFrames}f`);
}

/* ---- 渲染前预检（delivery promise）：语速区间 + 静态版式驻留风险 ---- */
{
	const issues = [];
	for (const f of frames) {
		const s = story.scenes.find((x) => x.id === f.id);
		if (!s || s.silent) continue;
		if (!ESTIMATE) {
			const rate = s.narration.length / f.audioDuration;
			if (rate < 2.2 || rate > 5.5)
				issues.push(`语速 ${rate.toFixed(1)} 字/秒（${f.id}，正常区间 2.2–5.5，考虑增删旁白）`);
		}
		const durS = f.durationInFrames / fps;
		if (durS > 22 && ["title", "vtitle", "cards", "checklist", "conclusion"].includes(s.template))
			issues.push(`幻灯片风险：${f.id} 静态版式驻留 ${durS.toFixed(0)}s（建议拆段或换信息更密版式）`);
	}
	for (const i of issues) console.log(`⚠ 预检 ${i}`);
	if (issues.length === 0) console.log("预检：无风险提示");
}

/* ---- 渲染 ---- */
if (NO_RENDER) {
	console.log("\n--no-render：已生成 active-story，可用以下命令预览：");
	console.log(`  npx remotion studio --public-dir ${projDir}`);
	process.exit(0);
}

/* ---- 渲前关键帧预览：逐场景 renderStill 出 start/mid/60% 三位置静帧，不改项目状态 ---- */
if (KEYFRAMES) {
	const [{ bundle }, { enableTailwind }, { renderStill, selectComposition }, { tmpdir }] =
		await Promise.all([
			import("@remotion/bundler"),
			import("@remotion/tailwind-v4"),
			import("@remotion/renderer"),
			import("node:os"),
		]);
	const outDir = path.join(projDir, "out", "keyframes");
	mkdirSync(outDir, { recursive: true });
	// 清掉上一轮预览，防旧图残留误导审片
	for (const entry of readdirSync(outDir, { withFileTypes: true })) {
		if (entry.isFile() && (entry.name.endsWith(".png") || entry.name === "README.txt")) {
			rmSync(path.join(outDir, entry.name), { force: true });
		}
	}
	console.log(`\n开始生成关键帧 -> ${outDir}`);
	const serveUrl = await bundle({
		entryPoint: path.resolve("src/index.ts"),
		webpackOverride: (c) => enableTailwind(c),
		publicDir: path.resolve(projDir),
	});
	const outputs = [];
	try {
		const composition = await selectComposition({ serveUrl, id: compositionId });
		let from = 0;
		let sequence = 1;
		for (let i = 0; i < frames.length; i++) {
			const f = frames[i];
			const positions = [
				{ label: "start", frame: from + Math.round(0.8 * fps), description: "场景开始后0.8秒" },
			];
			if (f.durationInFrames / fps > 15) {
				positions.push({ label: "mid", frame: from + Math.round(0.5 * f.durationInFrames), description: "中段" });
			}
			positions.push({ label: "60", frame: from + Math.round(0.6 * f.durationInFrames), description: "时长60%处" });
			for (const position of positions) {
				const filename = `${String(sequence).padStart(2, "0")}-${f.id}-${position.label}.png`;
				const output = path.join(outDir, filename);
				await renderStill({
					composition,
					serveUrl,
					frame: position.frame,
					output,
					imageFormat: "png",
					overwrite: true,
					inputProps: {},
				});
				outputs.push(`${filename} → 场景 ${f.id}（第 ${i + 1}/共 ${frames.length} 场，模板 ${f.template}）的 ${position.description}`);
				sequence++;
			}
			from += f.durationInFrames;
		}
		writeFileSync(path.join(outDir, "README.txt"),
			["每个文件对应哪个场景的哪一段：", ...outputs, "确认无误后跑正式 build：node scripts/build.mjs " + projectId].join("\n") + "\n");
	} finally {
		const tempRoot = path.resolve(tmpdir());
		const resolvedServeUrl = path.resolve(serveUrl);
		const relativeToTemp = path.relative(tempRoot, resolvedServeUrl);
		if (relativeToTemp && !relativeToTemp.startsWith("..") && !path.isAbsolute(relativeToTemp)) {
			rmSync(resolvedServeUrl, { recursive: true, force: true });
		}
	}
	console.log("\n✓ 关键帧生成完成（预览模式，项目状态不变）：");
	for (const item of outputs) console.log(`  ${item}`);
	process.exit(0);
}

/* ---- 带音样片预览：只渲开头 N 秒，不改项目状态 ---- */
if (SAMPLE) {
	const sampleOut = path.join(projDir, "out", "sample.mp4");
	mkdirSync(path.dirname(sampleOut), { recursive: true });
	const endFrame = Math.min(Math.round(fps * sampleSeconds), totalFrames - 1);
	console.log(`\n开始渲染 ${sampleSeconds} 秒样片（推荐 15-25 秒）-> ${sampleOut}`);
	const t0 = Date.now();
	execFileSync(
		"npx",
		["remotion", "render", compositionId, sampleOut, "--public-dir", projDir, `--frames=0-${endFrame}`],
		{ stdio: "inherit", shell: true },
	);
	console.log(`\n✓ 样片渲染完成，实际 ${probeDuration(sampleOut).toFixed(1)}s，耗时 ${((Date.now() - t0) / 1000 / 60).toFixed(1)} 分钟（预览模式，项目状态不变）`);
	process.exit(0);
}

const outFile = path.join(projDir, "out", ESTIMATE ? "preview-silent.mp4" : "final.mp4");
mkdirSync(path.dirname(outFile), { recursive: true });
console.log(`\n开始渲染 -> ${outFile}`);
const t0 = Date.now();
execFileSync(
	"npx",
	["remotion", "render", compositionId, outFile, "--public-dir", projDir],
	{ stdio: "inherit", shell: true },
);
console.log(`\n✅ 完成，耗时 ${((Date.now() - t0) / 1000 / 60).toFixed(1)} 分钟`);

/* ---- 封面: 渲染开场标题帧（0.7 秒处动画已稳定，随 fps 缩放）作为当期封面 ---- */
const coverFile = path.join(projDir, "out", "cover.png");
try {
	execFileSync(
		"npx",
		["remotion", "still", compositionId, coverFile, `--frame=${Math.round(0.7 * fps)}`, "--public-dir", projDir],
		{ stdio: "inherit", shell: true },
	);
	console.log(`🖼 封面已生成 -> ${coverFile}(与视频开场同款视觉)`);
} catch (e) {
	console.error(`封面生成失败(不影响视频): ${e.message}`);
}

// Decode each scene's exact first frame from the final render; this reuses the
// rendered pixels and avoids rebundling a concurrently changing active-story.
const keyframeDir = path.join(projDir, "out", "keyframes");
mkdirSync(keyframeDir, {recursive: true});
const stillErrors = [];
let stills = 0, firstFrame = 0;
const ffmpeg = FFPROBE.replace(/ffprobe(\.exe)?$/, "ffmpeg$1");
for (const frame of frames) {
	try {
		execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", "-i", outFile,
			"-vf", `trim=start_frame=${firstFrame}:end_frame=${firstFrame + 1}`, "-frames:v", "1", "-update", "1",
			path.join(keyframeDir, `${frame.id}.png`)], {stdio: "pipe"});
		if (!existsSync(path.join(keyframeDir, `${frame.id}.png`))) throw new Error("静帧文件未生成");
		stills++;
	} catch (error) { stillErrors.push(`首帧抽查失败 ${frame.id}: ${error.message}`); }
	firstFrame += frame.durationInFrames;
}

/* ---- QA 自检: 结果进日志与 out/verify.json；有错置 qa_failed 并以退出码 1 报告，
 * 有警告置 built 但 qaStatus=built_with_warnings。对齐参考仓 QA 口径：
 * 分辨率 / 成片时长(±1.5s) / 音轨存在 / 音频电平(近静音判错、削波判警)。 */
let qaStatus = "built";
{
	console.log("\nQA 自检:");
	const qa = { file: path.relative(projDir, outFile), composition: compositionId,
		mode: ESTIMATE ? "estimate" : "build", durationS: totalFrames / fps,
		checks: [], warnings: frames.filter((f) => f.alignmentWarning).map((f) => `${f.id}: ${f.alignmentWarning}`), errors: stillErrors, stills,
		builtAt: new Date().toISOString() };
	qa.checks.push(`最短场景 ${Math.min(...frames.map((f) => f.durationInFrames / fps)).toFixed(2)} 秒（模板感知兜底 ≥4.0，versus/stacked/vpoints ≥5.0）`);
	qa.checks.push(`场景首帧 ${stills}/${frames.length}（out/keyframes）`);
	const trimmedCount = frames.filter((f) => f.trimHead > 0).length;
	if (trimmedCount) qa.checks.push(`TTS 静默裁剪 ${trimmedCount}/${frames.length} 幕（audio/trim/ 副本，原件保留）`);
	qa.captionMethods = [...new Set(frames.map((f) => f.alignmentMethod))];
	if (!existsSync(outFile)) qa.errors.push(`产物缺失: ${outFile}`);
	else qa.checks.push(`产物存在（${(statSync(outFile).size / 1024 / 1024).toFixed(1)} MB）`);
	const badTpl = frames.filter((f) => !TEMPLATE_IDS.includes(f.template));
	if (badTpl.length === 0) qa.checks.push(`模板枚举合法（${frames.length} 场全部在注册表）`);
	else for (const f of badTpl) qa.errors.push(`未知模板: ${f.template}（场景 ${f.id}）`);
	if (frames.length === story.scenes.length) qa.checks.push(`场景数一致（${frames.length}）`);
	else qa.errors.push(`场景数不一致: 时间轴 ${frames.length} ≠ story ${story.scenes.length}`);
	if (ESTIMATE) {
		qa.checks.push("估算模式：无音轨，跳过音频齐全性检查");
	} else {
		const missing = (story.scenes ?? [])
			.filter((s) => !s.silent)
			.filter((s) => !existsSync(path.join(audioDir, `${s.id}.mp3`)));
		if (missing.length === 0) qa.checks.push("音频齐全（非静默场景均有 mp3）");
		else for (const s of missing) qa.errors.push(`缺音频: ${s.id}.mp3`);
	}
	if (existsSync(outFile)) {
		const expW = meta.width ?? 1920, expH = meta.height ?? 1080;
		try {
			const dims = execFileSync(FFPROBE, ["-v", "error", "-select_streams", "v:0",
				"-show_entries", "stream=width,height", "-of", "csv=p=0", outFile]).toString().trim();
			const [aw, ah] = dims.split(",").map(Number);
			if (aw === expW && ah === expH) qa.checks.push(`分辨率 ${aw}×${ah} ✓`);
			else qa.errors.push(`分辨率 ${dims} ≠ 预期 ${expW}×${expH}`);
		} catch (e) { qa.errors.push(`分辨率读取失败: ${String(e?.message ?? e).slice(0, 80)}`); }
		const actualDur = probeDuration(outFile);
		if (Math.abs(actualDur - totalFrames / fps) <= 1.5) qa.checks.push(`成片时长 ${actualDur.toFixed(1)}s ✓`);
		else qa.errors.push(`成片时长 ${actualDur.toFixed(1)}s ≠ 预期 ${(totalFrames / fps).toFixed(1)}s`);
		if (!ESTIMATE) {
			const hasAudio = execFileSync(FFPROBE, ["-v", "error", "-select_streams", "a",
				"-show_entries", "stream=codec_type", "-of", "csv=p=0", outFile]).toString().trim();
			if (hasAudio) qa.checks.push("音轨存在 ✓");
			else qa.errors.push("缺少音轨（旁白未混入？）");
			// 电平检测需要 volumedetect 滤镜：compositor 精简 ffmpeg 没有，优先用系统完整版。
			const whereFfmpeg = spawnSync("where", ["ffmpeg"], { encoding: "utf8", shell: true });
			const systemFfmpeg = (whereFfmpeg.stdout ?? "").split(/\r?\n/)[0]?.trim();
			const levelFfmpeg = whereFfmpeg.status === 0 && systemFfmpeg && existsSync(systemFfmpeg)
				? systemFfmpeg : ffmpeg;
			const vol = spawnSync(levelFfmpeg, ["-hide_banner", "-nostats", "-i", outFile,
				"-vn", "-af", "volumedetect", "-f", "null", "-"], { encoding: "utf8" });
			const volOut = `${vol.stdout ?? ""}\n${vol.stderr ?? ""}`;
			if (/No such filter: 'volumedetect'/.test(volOut)) {
				qa.checks.push("音频电平检测跳过（ffmpeg 无 volumedetect 滤镜）");
			} else {
				const meanVol = Number(volOut.match(/mean_volume:\s*(-?[\d.]+) dB/)?.[1]);
				const maxVol = Number(volOut.match(/max_volume:\s*(-?[\d.]+) dB/)?.[1]);
				if (Number.isFinite(meanVol)) {
					if (meanVol < -55) qa.errors.push(`音频近静音（mean ${meanVol}dB）`);
					else qa.checks.push(`音频电平 mean ${meanVol}dB ✓`);
				}
				if (Number.isFinite(maxVol) && maxVol > -0.5) qa.warnings.push(`疑似削波（max ${maxVol}dB）`);
			}
		}
	}
	qaStatus = qa.errors.length ? "qa_failed" : qa.warnings.length ? "built_with_warnings" : "built";
	qa.status = qaStatus;
	for (const c of qa.checks) console.log(`  ✓ ${c}`);
	for (const w of qa.warnings) console.warn(`  ⚠ ${w}`);
	writeFileSync(path.join(projDir, "out", "verify.json"), JSON.stringify(qa, null, "\t"));
	console.log(`  QA 报告 -> ${path.join(projDir, "out", "verify.json")}`);
	if (qa.errors.length > 0) {
		for (const e of qa.errors) console.error(`  ✗ ${e}`);
		if (!ESTIMATE) {
			project.status = "qa_failed";
			project.qaReport = "out/verify.json";
			writeFileSync(projFile, JSON.stringify(project, null, "\t"));
			console.error("  项目状态 -> qa_failed");
		}
		process.exit(1);
	}
}

/* ---- 更新项目状态（预览模式不改状态） ---- */
if (ESTIMATE) {
	console.log("预览模式：项目状态保持不变（正式出片需 status=reviewed）");
	process.exit(0);
}
project.status = "built";
project.qaStatus = qaStatus;
project.builtAt = new Date().toISOString().slice(0, 10);
project.output = `out/final.mp4 (${(totalFrames / fps / 60).toFixed(2)} min)`;
writeFileSync(projFile, JSON.stringify(project, null, "\t"));
console.log(`项目状态 -> built（qaStatus=${qaStatus}）`);
