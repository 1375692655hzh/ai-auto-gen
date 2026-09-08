// 用法: node scripts/tts-scenes.mjs <job.json 绝对路径>
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { synthOnce, hashNarration, loadEnv, FFPROBE } from "./tts-engines.mjs";

loadEnv();

async function main() {
	const jobFile = process.argv[2];
	if (!jobFile || !path.isAbsolute(jobFile))
		throw new Error("用法: node scripts/tts-scenes.mjs <job.json 绝对路径>");
	const job = JSON.parse(readFileSync(jobFile, "utf-8"));
	if (!Array.isArray(job.scenes) || !["edge", "dashscope"].includes(job.provider) ||
		typeof job.voice !== "string" || !job.voice.trim() ||
		typeof job.out_dir !== "string" || !job.out_dir.trim())
		throw new Error("job 必须包含 scenes、out_dir、provider(edge|dashscope) 和 voice");
	const ids = new Set();
	for (const s of job.scenes) {
		if (!s || typeof s.id !== "string" || !/^[a-z0-9][a-z0-9-]*$/.test(s.id) ||
			ids.has(s.id) || typeof s.narration !== "string")
			throw new Error("场景必须包含唯一的 kebab-case id 和字符串 narration");
		ids.add(s.id);
	}
	const outDir = job.out_dir;
	mkdirSync(outDir, { recursive: true });
	const manifestPath = path.join(outDir, "manifest.json");
	const resultPath = path.join(outDir, "_result.json");
	const manifest = existsSync(manifestPath)
		? JSON.parse(readFileSync(manifestPath, "utf-8")) : {};
	// 失败时不留下上一轮的成功结果；只为成功合成的音频提交缓存哈希。
	rmSync(resultPath, { force: true });
	const saveManifest = () => writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
	async function synthAll(engine, voice) {
		const made = [];
		for (const s of job.scenes) {
			const outFile = path.join(outDir, `${s.id}.mp3`);
			const hash = hashNarration(s.narration);
			if (existsSync(outFile) && manifest[s.id] === hash) continue;
			rmSync(outFile, { force: true });
			delete manifest[s.id];
			saveManifest();
			process.stdout.write(`合成语音: ${s.id} ... `);
			if (await synthOnce(engine, voice, s.narration, outFile)) {
				console.log("ok");
				manifest[s.id] = hash;
				saveManifest();
				made.push(outFile);
			} else {
				rmSync(outFile, { force: true });
				return { ok: false, made, failedId: s.id };
			}
		}
		return { ok: true, made };
	}
	let r = await synthAll(job.provider, job.voice);
	if (!r.ok && job.provider === "dashscope") {
		console.warn(`\n⚠ ${r.failedId} 合成失败，DashScope 不可用 → 自动降级 Edge TTS，整批重跑保持音色一致`);
		for (const f of r.made) {
			rmSync(f);
			delete manifest[path.basename(f, ".mp3")];
		}
		saveManifest();
		r = await synthAll("edge", "zh-CN-XiaoxiaoNeural");
	}
	if (!r.ok) throw new Error(`语音合成失败: ${r.failedId}（网络问题可重跑，已有音频会跳过）`);
	saveManifest();
	const result = { items: {} };
	for (const s of job.scenes) {
		const file = `${s.id}.mp3`;
		const duration = Number(execFileSync(FFPROBE, [
			"-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
			path.join(outDir, file),
		]).toString().trim());
		if (!Number.isFinite(duration) || duration <= 0)
			throw new Error(`音频时长无效: ${s.id}`);
		result.items[s.id] = { file, hash: hashNarration(s.narration), duration_s: duration };
	}
	writeFileSync(resultPath, JSON.stringify(result));
	console.log(`RESULT ${JSON.stringify(result)}`);
	process.exit(0);
}

main().catch((error) => {
	console.error(error.message);
	process.exit(1);
});
