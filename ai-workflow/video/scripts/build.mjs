// 一键制作流水线：story 校验 -> 审核门禁 -> TTS 补齐(含降级链) -> 测时长 -> 生成 active-story -> 渲染 -> QA 自检(轻量)
// 用法:
//   node scripts/build.mjs <projectId>            正式制作（要求 status=reviewed）
//   node scripts/build.mjs <projectId> --force    跳过审核门禁
//   node scripts/build.mjs <projectId> --estimate 仅按字数估时长出片（无语音预览用）
//   node scripts/build.mjs <projectId> --no-render 只生成 active-story（配 remotion studio 预览）
import msedgeTtsPkg from "msedge-tts";
const { MsEdgeTTS, OUTPUT_FORMAT } = msedgeTtsPkg;
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { validateStory } from "./story-validate.mjs";
import { TEMPLATE_IDS } from "./template-ids.mjs";

const COMPOSITOR_PKG = {
	win32: ["compositor-win32-x64-msvc", "ffprobe.exe"],
	darwin: ["compositor-darwin-arm64-x64", "ffprobe"],
	linux: ["compositor-linux-x64-gnu", "ffprobe"],
}[process.platform] || ["compositor-win32-x64-msvc", "ffprobe.exe"];
const FFPROBE = path.join("node_modules", "@remotion", COMPOSITOR_PKG[0], COMPOSITOR_PKG[1]);

/** 读取 .env（KEY=VALUE，等号后原样），不覆盖已有环境变量 */
const loadEnv = () => {
	if (!existsSync(".env")) return;
	for (const line of readFileSync(".env", "utf-8").split(/\r?\n/)) {
		const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
		if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
	}
};
loadEnv();

const args = process.argv.slice(2);
const projectId = args.find((a) => !a.startsWith("--"));
if (!projectId) {
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
const compositionId = story.meta?.format === "vertical" ? "VerticalShort" : "Story";

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

/* ---- TTS：补齐缺失音频 ---- */

/** 引擎一：Edge TTS（免费，voice 如 zh-CN-XiaoxiaoNeural） */
async function synthEdge(text, voice, outFile) {
	const tts = new MsEdgeTTS();
	await tts.setMetadata(voice, OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3);
	const { audioStream } = tts.toStream(text);
	const chunks = [];
	await new Promise((resolve, reject) => {
		audioStream.on("data", (c) => chunks.push(c));
		audioStream.on("end", resolve);
		audioStream.on("error", reject);
	});
	writeFileSync(outFile, Buffer.concat(chunks));
}

/** 引擎二：阿里云 DashScope Qwen TTS（原生 SpeechSynthesizer 接口） */
async function synthDashscope(text, voice, outFile) {
	const key = process.env.DASHSCOPE_API_KEY;
	if (!key) throw new Error("缺少 DASHSCOPE_API_KEY（写入引擎根目录 .env）");
	const base = process.env.DASHSCOPE_BASE_URL ?? "https://dashscope.aliyuncs.com/compatible-mode/v1";
	const endpoint = `${new URL(base).origin}/api/v1/services/audio/tts/SpeechSynthesizer`;
	const res = await fetch(endpoint, {
		method: "POST",
		headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
		body: JSON.stringify({
			model: "qwen-audio-3.0-tts-plus",
			input: { text, voice, format: "mp3", sample_rate: 24000 },
		}),
	});
	if (!res.ok) {
		throw new Error(`dashscope HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
	}
	const json = await res.json();
	const url = json?.output?.audio?.url?.replace("http://", "https://");
	if (!url) throw new Error(`dashscope 未返回音频: ${JSON.stringify(json).slice(0, 200)}`);
	const audio = await fetch(url);
	if (!audio.ok) throw new Error(`音频下载失败 HTTP ${audio.status}`);
	writeFileSync(outFile, Buffer.from(await audio.arrayBuffer()));
}

/** 按项目配置分发引擎（story.json meta.tts，缺省用 edge + meta.voice） */
const ttsConf =
	story.meta.tts && story.meta.tts.provider === "dashscope"
		? { engine: "dashscope", voice: story.meta.tts.voice ?? "longanlufeng" }
		: { engine: "edge", voice: story.meta.voice ?? "zh-CN-XiaoxiaoNeural" };

async function synthOnce(engine, voice, text, outFile) {
	for (let attempt = 1; attempt <= 8; attempt++) {
		try {
			if (engine === "dashscope") {
				await synthDashscope(text, voice, outFile);
			} else {
				await synthEdge(text, voice, outFile);
			}
			return true;
		} catch (e) {
			console.error(`  TTS 重试 ${attempt}/8: ${e.message}`);
			await new Promise((r) => setTimeout(r, 2500 * attempt));
		}
	}
	return false;
}

/** 用指定引擎补齐全部缺失音频；返回 {ok, made[], failedId} */
async function synthAll(engine, voice) {
	const made = [];
	for (const s of story.scenes) {
		if (s.silent) continue;                  // 静默场景无旁白，不需要音频
		const outFile = path.join(audioDir, `${s.id}.mp3`);
		if (existsSync(outFile)) continue;
		process.stdout.write(`合成语音: ${s.id} ... `);
		if (await synthOnce(engine, voice, s.narration, outFile)) {
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
		const hash = createHash("sha1").update(s.narration).digest("hex").slice(0, 10);
		const outFile = path.join(audioDir, `${s.id}.mp3`);
		if (existsSync(outFile) && manifest[s.id] !== hash) {
			rmSync(outFile);
			console.log(`文本已改, 旧音频失效: ${s.id}`);
		}
		manifest[s.id] = hash;
	}
	writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
	let r = await synthAll(ttsConf.engine, ttsConf.voice);
	// 降级链：dashscope 失败/缺 key → 删掉本次已合成音频，整批改用 edge 重跑（保音色一致）
	if (!r.ok && ttsConf.engine === "dashscope") {
		console.warn(`\n⚠ ${r.failedId} 合成失败，DashScope 不可用 → 自动降级 Edge TTS，整批重跑保持音色一致`);
		for (const f of r.made) rmSync(f);
		r = await synthAll("edge", story.meta.voice ?? "zh-CN-XiaoxiaoNeural");
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
	const f = Math.ceil((dur + (silent ? 0 : pad + LEAD_S)) * fps);
	frames.push({
		id: s.id,
		template: s.template,
		audio,
		caption: s.caption ?? null,
		cues: s.captions ?? null,          // 同步字幕轨(帧级起止)
		leadFrames: silent ? 0 : Math.round(LEAD_S * fps),
		audioDuration: Number(dur.toFixed(3)),
		durationInFrames: f,
	});
	totalFrames += f;
}

/* ---- 生成 src/active-story.ts ---- */
const active = {
	meta: { fps, width: meta.width ?? 1920, height: meta.height ?? 1080, voice: meta.voice },
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
	leadFrames?: number;
	audioDuration: number;
	durationInFrames: number;
}
export const ACTIVE: { meta: { fps: number; width: number; height: number; voice: string }; story: Story; frames: ActiveFrame[]; totalFrames: number } = ${JSON.stringify(active, null, "\t")};
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

/* ---- 封面: 渲染开场标题帧(约0.7s处, 动画已稳定) 作为当期封面 ---- */
const coverFile = path.join(projDir, "out", "cover.png");
try {
	execFileSync(
		"npx",
		["remotion", "still", compositionId, coverFile, "--frame=20", "--public-dir", projDir],
		{ stdio: "inherit", shell: true },
	);
	console.log(`🖼 封面已生成 -> ${coverFile}(与视频开场同款视觉)`);
} catch (e) {
	console.error(`封面生成失败(不影响视频): ${e.message}`);
}

/* ---- QA 自检（轻量版）: 结果只进日志与 out/verify.json，不新增项目状态 ----
 * 状态三态不变（draft/reviewed/built）；QA 有错时仅拒绝置 built 并以退出码 1 报告。 */
{
	console.log("\nQA 自检:");
	const qa = { file: path.relative(projDir, outFile), composition: compositionId,
		mode: ESTIMATE ? "estimate" : "build", checks: [], warnings: [], errors: [],
		builtAt: new Date().toISOString() };
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
