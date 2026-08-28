// 一键制作流水线：审核校验 -> TTS 补齐 -> 测时长 -> 生成 active-story -> 渲染
// 用法:
//   node scripts/build.mjs <projectId>            正式制作（要求 status=reviewed）
//   node scripts/build.mjs <projectId> --force    跳过审核门禁
//   node scripts/build.mjs <projectId> --estimate 仅按字数估时长出片（无语音预览用）
//   node scripts/build.mjs <projectId> --no-render 只生成 active-story（配 remotion studio 预览）
import msedgeTtsPkg from "msedge-tts";
const { MsEdgeTTS, OUTPUT_FORMAT } = msedgeTtsPkg;
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const COMPOSITOR_PKG = {
	win32: ["compositor-win32-x64-msvc", "ffprobe.exe"],
	darwin: ["compositor-darwin-arm64-x64", "ffprobe"],
	linux: ["compositor-linux-x64-gnu", "ffprobe"],
}[process.platform] || ["compositor-win32-x64-msvc", "ffprobe.exe"];
const FFPROBE = path.join("node_modules", "@remotion", COMPOSITOR_PKG[0], COMPOSITOR_PKG[1]);
const COMPOSITION_ID = "Story";

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
const audioDir = path.join(projDir, "audio");
mkdirSync(audioDir, { recursive: true });

/* ---- TTS：补齐缺失音频 ---- */

/** 引擎一：Edge TTS（免费，voice 如 zh-CN-YunxiNeural） */
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
		: { engine: "edge", voice: story.meta.voice ?? "zh-CN-YunxiNeural" };

async function synth(text, outFile) {
	for (let attempt = 1; attempt <= 8; attempt++) {
		try {
			if (ttsConf.engine === "dashscope") {
				await synthDashscope(text, ttsConf.voice, outFile);
			} else {
				await synthEdge(text, ttsConf.voice, outFile);
			}
			return true;
		} catch (e) {
			console.error(`  TTS 重试 ${attempt}/8: ${e.message}`);
			await new Promise((r) => setTimeout(r, 2500 * attempt));
		}
	}
	return false;
}

if (!ESTIMATE) {
	console.log(`TTS 引擎: ${ttsConf.engine} · 音色 ${ttsConf.voice}`);
	let synthesized = 0;
	for (const s of story.scenes) {
		const outFile = path.join(audioDir, `${s.id}.mp3`);
		if (!existsSync(outFile)) {
			process.stdout.write(`合成语音: ${s.id} ... `);
			if (await synth(s.narration, outFile)) {
				console.log("ok");
				synthesized++;
			} else {
				console.error(`\n语音合成失败: ${s.id}（网络问题可重跑，已有音频会跳过）`);
				process.exit(1);
			}
		}
	}
	if (synthesized === 0) console.log("语音已全部存在，跳过 TTS");
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
	if (ESTIMATE) {
		dur = Math.max(4, s.narration.length / 4.2);
	} else {
		const file = path.join(audioDir, `${s.id}.mp3`);
		dur = probeDuration(file);
		audio = `audio/${s.id}.mp3`;
	}
	const f = Math.ceil((dur + pad) * fps);
	frames.push({
		id: s.id,
		template: s.template,
		audio,
		caption: s.caption ?? s.narration,
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
	caption: string;
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
	["remotion", "render", COMPOSITION_ID, outFile, "--public-dir", projDir],
	{ stdio: "inherit", shell: true },
);
console.log(`\n✅ 完成，耗时 ${((Date.now() - t0) / 1000 / 60).toFixed(1)} 分钟`);

/* ---- 封面: 渲染开场标题帧(约0.7s处, 动画已稳定) 作为当期封面 ---- */
const coverFile = path.join(projDir, "out", "cover.png");
try {
	execFileSync(
		"npx",
		["remotion", "still", COMPOSITION_ID, coverFile, "--frame=20", "--public-dir", projDir],
		{ stdio: "inherit", shell: true },
	);
	console.log(`🖼 封面已生成 -> ${coverFile}(与视频开场同款视觉)`);
} catch (e) {
	console.error(`封面生成失败(不影响视频): ${e.message}`);
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
