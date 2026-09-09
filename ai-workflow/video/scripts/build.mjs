// 一键制作流水线：story 校验 -> 审核门禁 -> TTS 补齐(保留供应商) -> 测时长 -> 生成 active-story -> 渲染 -> QA 自检(轻量)
// 用法:
//   node scripts/build.mjs <projectId>            正式制作（要求 status=reviewed）
//   node scripts/build.mjs <projectId> --force    跳过审核门禁
//   node scripts/build.mjs <projectId> --estimate 仅按字数估时长出片（无语音预览用）
//   node scripts/build.mjs <projectId> --no-render 只生成 active-story（配 remotion studio 预览）
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync, statSync, copyFileSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { validateStory } from "./story-validate.mjs";
import { TEMPLATE_IDS } from "./template-ids.mjs";
import { synthOnce, hashNarration, loadEnv, FFPROBE } from "./tts-engines.mjs";

import { captionTimeline, toSrt } from "../shared/captions.mjs";

loadEnv();

const args = process.argv.slice(2);
const projectId = args.find((a) => !a.startsWith("--"));
if (!projectId || !/^[a-zA-Z0-9_-]+$/.test(projectId)) {
	console.error("用法: node scripts/build.mjs <projectId> [--force] [--estimate] [--no-render]");
	process.exit(1);
}
const FORCE = args.includes("--force");
const ESTIMATE = args.includes("--estimate");
const NO_RENDER = args.includes("--no-render");

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
const pad = meta.padSeconds ?? 0.8;
const LEAD_S = 0.7;                    // 音频前置静默: 语音开始时画面动画已展开
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
		if (existsSync(outFile)) continue;
		if (project.settings?.require_selected_audio) throw new Error(`已选语音缺失: ${s.id}，请重新选择语音 take`);
		process.stdout.write(`合成语音: ${s.id} ... `);
		if (await synthOnce(engine, voice, s.narration, outFile, customCfg)) {
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
		if (existsSync(outFile) && manifest[s.id] !== hash) {
			throw new Error(`语音已过期或缺少匹配哈希: ${s.id}，请在语音阶段重新选择/生成；保留原音频`);
		}
		manifest[s.id] = hash;
	}
	writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
	let r = await synthAll(ttsConf.engine, ttsConf.voice, ttsConf.customCfg);
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

const frames = [];
let totalFrames = 0;
for (const s of story.scenes) {
	let dur;
	let audio = null;
	if (s.silent) {                      // 静默场景: 固定时长(公告每页5s)
		dur = s.durationS ?? 5;
	} else if (ESTIMATE) {
		dur = Math.max(4, s.narration.length / 4.2);
	} else {
		const file = path.join(audioDir, `${s.id}.mp3`);
		dur = probeDuration(file);
		audio = `audio/${s.id}.mp3`;
	}
	const silent = Boolean(s.silent);
	const visualFrames = Math.ceil((dur + (silent ? 0 : pad + LEAD_S)) * fps);
	const f = Math.max(Math.ceil(5.5 * fps), visualFrames);
	const alignmentFile = path.join(audioDir, `${s.id}.alignment.json`);
	const cuesFile = path.join(audioDir, `${s.id}.cues.json`);
	let providerTrack;
	if (!ESTIMATE && existsSync(cuesFile)) {
		try {
			providerTrack = JSON.parse(readFileSync(cuesFile, "utf-8"));
			if (providerTrack.narrationHash && providerTrack.narrationHash !== hashNarration(s.narration)) providerTrack = {};
		} catch { providerTrack = {}; }
	}
	const subtitles = silent ? {cues: [], method: "silent"} : captionTimeline({
		text: s.narration, duration: dur, fps, lead: LEAD_S, cues: s.captions,
		providerTrack,
		alignment: !providerTrack && !ESTIMATE && existsSync(alignmentFile) ? JSON.parse(readFileSync(alignmentFile, "utf-8")) : undefined,
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

/* ---- 渲染 ---- */
if (NO_RENDER) {
	console.log("\n--no-render：已生成 active-story，可用以下命令预览：");
	console.log(`  npx remotion studio --public-dir ${projDir}`);
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

/* ---- QA 自检（轻量版）: 结果只进日志与 out/verify.json，不新增项目状态 ----
 * 状态三态不变（draft/reviewed/built）；QA 有错时仅拒绝置 built 并以退出码 1 报告。 */
{
	console.log("\nQA 自检:");
	const qa = { file: path.relative(projDir, outFile), composition: compositionId,
		mode: ESTIMATE ? "estimate" : "build", durationS: totalFrames / fps,
		checks: [], warnings: frames.filter((f) => f.alignmentWarning).map((f) => `${f.id}: ${f.alignmentWarning}`), errors: stillErrors, stills,
		builtAt: new Date().toISOString() };
	qa.checks.push(`最短场景 ${Math.min(...frames.map((f) => f.durationInFrames / fps)).toFixed(2)} 秒（≥5.5 兜底）`);
	qa.checks.push(`场景首帧 ${stills}/${frames.length}（out/keyframes）`);
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
	for (const c of qa.checks) console.log(`  ✓ ${c}`);
	for (const w of qa.warnings) console.warn(`  ⚠ ${w}`);
	writeFileSync(path.join(projDir, "out", "verify.json"), JSON.stringify(qa, null, "\t"));
	console.log(`  QA 报告 -> ${path.join(projDir, "out", "verify.json")}`);
	if (qa.errors.length > 0) {
		for (const e of qa.errors) console.error(`  ✗ ${e}`);
		process.exit(1);
	}
}

/* ---- 更新项目状态（预览模式不改状态） ---- */
if (ESTIMATE) {
	console.log("预览模式：项目状态保持不变（正式出片需 status=reviewed）");
	process.exit(0);
}
project.status = "built";
project.builtAt = new Date().toISOString().slice(0, 10);
project.output = `out/final.mp4 (${(totalFrames / fps / 60).toFixed(2)} min)`;
writeFileSync(projFile, JSON.stringify(project, null, "\t"));
console.log(`项目状态 -> built`);
