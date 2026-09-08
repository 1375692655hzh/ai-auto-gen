import msedgeTtsPkg from "msedge-tts";
const { MsEdgeTTS, OUTPUT_FORMAT } = msedgeTtsPkg;
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";

const COMPOSITOR_PKG = {
	win32: ["compositor-win32-x64-msvc", "ffprobe.exe"],
	darwin: ["compositor-darwin-arm64-x64", "ffprobe"],
	linux: ["compositor-linux-x64-gnu", "ffprobe"],
}[process.platform] || ["compositor-win32-x64-msvc", "ffprobe.exe"];
export const FFPROBE = path.join("node_modules", "@remotion", COMPOSITOR_PKG[0], COMPOSITOR_PKG[1]);

/** 读取 .env（KEY=VALUE，等号后原样），不覆盖已有环境变量 */
export const loadEnv = () => {
	if (!existsSync(".env")) return;
	for (const line of readFileSync(".env", "utf-8").split(/\r?\n/)) {
		const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
		if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
	}
};

export async function synthEdge(text, voice, outFile) {
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

export async function synthDashscope(text, voice, outFile) {
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

export async function synthCustom(cfg, voice, text, outFile) {
	const base = String(cfg.base_url || "").replace(/\/+$/, "");
	if (!base || !cfg.model) throw new Error("custom 供应商缺 base_url/model");
	const auth = { "Content-Type": "application/json", Authorization: `Bearer ${cfg.api_key || ""}` };
	// 协议一: OpenAI /audio/speech
	const r1 = await fetch(base + "/audio/speech", {
		method: "POST", headers: auth,
		body: JSON.stringify({ model: cfg.model, voice, input: text, response_format: "mp3" }),
	});
	if (r1.ok) {
		const buf = Buffer.from(await r1.arrayBuffer());
		if (buf.length < 200) throw new Error(`custom TTS 返回内容过小(${buf.length}B), 疑似非音频`);
		writeFileSync(outFile, buf);
		return;
	}
	if (r1.status !== 404)
		throw new Error(`custom TTS HTTP ${r1.status}: ${(await r1.text()).slice(0, 150)}`);
	// 协议二: /chat/completions 音频模态(小米 mimo 等把 TTS 挂在 chat 端点的实现)
	const r2 = await fetch(base + "/chat/completions", {
		method: "POST", headers: auth,
		body: JSON.stringify({ model: cfg.model, modalities: ["text", "audio"],
			audio: { voice, format: "mp3" },
			messages: [{ role: "assistant", content: text }] }),
	});
	if (!r2.ok) throw new Error(`custom TTS(chat) HTTP ${r2.status}: ${(await r2.text()).slice(0, 150)}`);
	const d2 = await r2.json();
	const b64 = d2?.choices?.[0]?.message?.audio?.data || "";
	if (!b64) throw new Error("chat TTS 响应缺 audio.data");
	writeFileSync(outFile, Buffer.from(b64, "base64"));
}

export async function synthOnce(engine, voice, text, outFile, customCfg) {
	for (let attempt = 1; attempt <= 8; attempt++) {
		try {
			if (engine === "custom") {
				await synthCustom(customCfg || {}, voice, text, outFile);
			} else if (engine === "dashscope") {
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

export const hashNarration = (text) => createHash("sha1").update(text).digest("hex").slice(0, 10);
