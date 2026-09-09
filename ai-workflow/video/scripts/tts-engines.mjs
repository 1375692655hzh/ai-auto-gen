import msedgeTtsPkg from "msedge-tts";
const { MsEdgeTTS, OUTPUT_FORMAT } = msedgeTtsPkg;
import { existsSync, readFileSync, writeFileSync, rmSync } from "node:fs";
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

export async function synthEdge(text, voice, outFile, {cuesFile = outFile.replace(/\.mp3$/i, ".cues.json")} = {}) {
	const tts = new MsEdgeTTS();
	try {
		await tts.setMetadata(voice, OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3,
			{wordBoundaryEnabled: Boolean(cuesFile), sentenceBoundaryEnabled: false});
		const {audioStream, metadataStream} = tts.toStream(text);
		const chunks = [], words = [];
		let metadataError = false;
		await new Promise((resolve, reject) => {
			const timeout = setTimeout(() => {
				audioStream.destroy();
				reject(new Error("Edge TTS stream timeout"));
			}, 120000);
			const finish = (error) => { clearTimeout(timeout); error ? reject(error) : resolve(); };
			metadataStream?.on("data", (chunk) => {
				try {
					for (const item of JSON.parse(chunk.toString()).Metadata || []) {
						if (item.Type !== "WordBoundary") continue;
						const d = item.Data;
						// Edge offsets and durations are 100 ns ticks relative to this audio.
						words.push({t: d.text.Text, start: d.Offset / 1e7, end: (d.Offset + d.Duration) / 1e7});
					}
				} catch { metadataError = true; }
			});
			metadataStream?.on("error", () => { metadataError = true; });
			audioStream.on("data", (c) => chunks.push(c));
			audioStream.once("error", finish);
			// msedge-tts 2.0.7 destroys metadataStream on audio close (no metadata end).
			audioStream.once("end", () => finish());
		});
		writeFileSync(outFile, Buffer.concat(chunks));
		if (cuesFile && words.length && !metadataError) {
			writeFileSync(cuesFile, JSON.stringify({origin: "provider-alignment", unit: "seconds",
				narrationHash: hashNarration(text), cues: words}, null, 2));
		} else if (cuesFile) {
			console.warn("Edge 未返回可用词界，字幕将标为 approximate-text-weight");
		}
	} finally {
		tts.close();
	}
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
	// MiniMax 协议: /t2a_v2(音频为 hex 编码; voice_setting.voice_id)
	if (base.includes("minimax")) {
		const r0 = await fetch(base + "/t2a_v2", {
			method: "POST", headers: auth,
			body: JSON.stringify({ model: cfg.model, text, stream: false,
				voice_setting: { voice_id: voice },
				audio_setting: { format: (cfg.format || "mp3"), sample_rate: 32000 } }),
		});
		if (!r0.ok) throw new Error(`MiniMax HTTP ${r0.status}: ${(await r0.text()).slice(0, 150)}`);
		const d0 = await r0.json();
		const br = d0.base_resp || {};
		if (br.status_code) throw new Error(`MiniMax ${br.status_code}: ${br.status_msg || ""}`);
		const hex = (d0.data || {}).audio || "";
		if (!hex) throw new Error("MiniMax 响应缺 data.audio");
		writeFileSync(outFile, Buffer.from(hex, "hex"));
		return;
	}
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
	// 官方契约: user 消息=语气风格指令, assistant 消息=要合成的文本(供应商可配默认风格)
	const style = cfg.style || "清晰自然的新闻播报语气, 语速适中, 情绪平稳专业";
	const r2 = await fetch(base + "/chat/completions", {
		method: "POST", headers: auth,
		body: JSON.stringify({ model: cfg.model, modalities: ["text", "audio"],
			audio: { voice, format: cfg.format || "mp3" },
			messages: [{ role: "user", content: style },
			           { role: "assistant", content: text }] }),
	});
	if (!r2.ok) throw new Error(`custom TTS(chat) HTTP ${r2.status}: ${(await r2.text()).slice(0, 150)}`);
	const d2 = await r2.json();
	const b64 = d2?.choices?.[0]?.message?.audio?.data || "";
	if (!b64) throw new Error("chat TTS 响应缺 audio.data");
	writeFileSync(outFile, Buffer.from(b64, "base64"));
}

export async function synthOnce(engine, voice, text, outFile, customCfg) {
	// Sidecars belong to this exact synthesis. Never reuse timestamps from a previous take/provider.
	for (const suffix of [".cues.json", ".alignment.json"])
		rmSync(outFile.replace(/\.mp3$/i, suffix), {force: true});
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
			// voiceLocale 报错 = 音色名不是合法 Edge 语音（须形如 zh-CN-XiaoxiaoNeural），
			// 重试无意义：给出可操作提示后立即失败
			if (engine === "edge" && /voiceLocale/i.test(e.message)) {
				console.error(`  TTS 失败: 音色"${voice}"不是有效的 Edge 语音名（应形如 zh-CN-XiaoxiaoNeural）。`
					+ `自定义供应商音色请先在制作页第三段生成语音稿（渲染时会直接复用），或到设置页改用标准音色名`);
				return false;
			}
			console.error(`  TTS 重试 ${attempt}/8: ${e.message}`);
			await new Promise((r) => setTimeout(r, 2500 * attempt));
		}
	}
	return false;
}

export const hashNarration = (text) => createHash("sha1").update(text).digest("hex").slice(0, 10);
