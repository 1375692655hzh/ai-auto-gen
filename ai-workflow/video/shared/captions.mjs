// Pure caption helpers shared by build.mjs (Node) and Remotion templates.
// Times are scene-local frames. Without a provider alignment track, cue
// start/end are approximate-text-weight — not word-level timestamps.
const compact = (text) => text.replace(/\s/gu, "");
const weight = (text) => [...text].reduce((n, c) => n + (/\s/u.test(c) ? 0.15 : /[，。！？；,.!?;]/u.test(c) ? 0.65 : /[\x00-\x7f]/u.test(c) ? 0.5 : 1), 0);
const UNIT = /^(?:[%％]|亿|万|元|美元|亿元|万元|公里|kg|ms|GB|bps)$/u;

function tokenize(text) {
	const tokens = [];
	const push = (seg) => {
		const last = tokens.at(-1) || "";
		if (tokens.length && /^[.,]\d/u.test(seg) && /\d$/u.test(last)) tokens[tokens.length - 1] += seg;
		else if (tokens.length && UNIT.test(seg) && /[\d亿万%％]$/u.test(last)) tokens[tokens.length - 1] += seg;
		else tokens.push(seg);
	};
	if (typeof Intl !== "undefined" && Intl.Segmenter) {
		for (const {segment} of new Intl.Segmenter("zh", {granularity: "word"}).segment(text)) push(segment);
	} else {
		for (const ch of text) push(ch);
	}
	return tokens;
}

function breakToken(token, width) {
	if (weight(token) <= width) return [token];
	const out = [];
	let cur = "";
	for (const ch of token) {
		if (cur && weight(cur + ch) > width && !/[\d.,%％]/u.test(ch)) {
			out.push(cur);
			cur = "";
		}
		cur += ch;
	}
	if (cur) out.push(cur);
	return out;
}

export function splitCaption(text, width = 16) {
	if (!text) return [];
	const lines = [];
	let line = "";
	for (const token of tokenize(text).flatMap((t) => breakToken(t, width))) {
		if (line && weight(line + token) > width && !/^[，。！？；,.!?;：:、）】]$/u.test(token)) {
			lines.push(line);
			line = "";
		}
		line += token;
		if (/[。！？；!?;]$/u.test(token) || (/[，,：:]$/u.test(token) && weight(line) >= 6) || token === ".") {
			lines.push(line);
			line = "";
		}
	}
	if (line) lines.push(line);
	const chunks = [];
	for (let i = 0; i < lines.length; i++) {
		let chunk = lines[i];
		const next = lines[i + 1];
		if (next && !/[，,。！？；!?;：:]\s*$/u.test(chunk) && weight(chunk) < 12 && weight(next) <= 18 && weight(chunk) + weight(next) <= 30) {
			chunk += "\n" + next;
			i++;
		} else if (!/[，,。！？；!?;：:]\s*$/u.test(chunk) && next && weight(chunk + next) <= 24) {
			chunk += "\n" + next;
			i++;
		}
		chunks.push(chunk);
	}
	return chunks;
}

function allocate(text, start, end) {
	const parts = splitCaption(text);
	const total = parts.reduce((n, p) => n + weight(p), 0);
	if (end - start < parts.length) throw new Error("字幕时间不足：短字幕数量超过可用帧");
	let sum = 0, cursor = start;
	return parts.map((t, i) => {
		sum += weight(t);
		const stop = i === parts.length - 1 ? end : Math.min(end - (parts.length - i - 1), Math.max(cursor + 1, Math.round(start + (end - start) * sum / total)));
		const cue = {t, start: cursor, end: stop};
		cursor = stop;
		return cue;
	});
}

function approximateSentences(text, start, end) {
	// Sentence-first allocation gives full stops their own pause weight; timing
	// inside each sentence remains a character-weight estimate, never alignment.
	const sentences = text.match(/[^。！？!?]*[。！？!?]+|[^。！？!?]+$/gu) || [];
	const sizes = sentences.map((s) => splitCaption(s).length);
	const required = sizes.reduce((a, b) => a + b, 0);
	if (end - start < required) throw new Error("字幕时间不足：短字幕数量超过可用帧");
	const weights = sentences.map((s) => weight(s) + (/[。！？!?]$/u.test(s) ? 1.5 : 0));
	const total = weights.reduce((a, b) => a + b, 0);
	let cursor = start, used = 0, sum = 0;
	return sentences.flatMap((s, i) => {
		used += sizes[i]; sum += weights[i];
		const stop = i === sentences.length - 1 ? end : start + used + Math.round((end - start - required) * sum / total);
		const cues = allocate(s, cursor, stop);
		cursor = stop;
		return cues;
	});
}

// Match provider words to the narration while restoring punctuation omitted by Edge.
// Whole provider words are grouped; no estimated subdivision is labelled precise.
function providerCaptions(track, text, duration, fps, start) {
	if (track?.origin !== "provider-alignment" || track.unit !== "seconds" || !Array.isArray(track.cues) || !track.cues.length) return null;
	const chars = [...text], positions = [], normalized = [];
	const clean = (s) => [...s.normalize("NFKC").toLowerCase()].filter((c) => /[\p{L}\p{N}]/u.test(c)).join("");
	chars.forEach((c, i) => { for (const n of clean(c)) { normalized.push(n); positions.push(i); } });
	let cursor = 0, previous = 0;
	const words = [];
	for (const c of track.cues) {
		if (typeof c.t !== "string" || !Number.isFinite(c.start) || !Number.isFinite(c.end) ||
			c.start < previous || c.end <= c.start || c.end > duration + 0.001) return null;
		const word = clean(c.t);
		if (!word || normalized.slice(cursor, cursor + word.length).join("") !== word) return null;
		words.push({...c, charStart: positions[cursor]});
		cursor += word.length;
		previous = c.end;
	}
	if (cursor !== normalized.length) return null;
	const grouped = [];
	for (let i = 0; i < words.length; i++) {
		const word = words[i];
		const t = chars.slice(i === 0 ? 0 : word.charStart, words[i + 1]?.charStart ?? chars.length).join("");
		const begin = start + Math.round(word.start * fps), end = start + Math.round(word.end * fps);
		if (end <= begin) return null;
		const last = grouped.at(-1);
		if (last && weight(last.t + t) <= 30 && !/[。！？；!?;，,：:]\s*$/u.test(last.t)) {
			last.t += t;
			last.end = end;
		} else grouped.push({t, start: begin, end});
	}
	return grouped;
}

export function captionTimeline({text, duration, fps, lead = 0, alignment, cues, providerTrack}) {
	const start = Math.round(lead * fps), end = start + Math.round(duration * fps);
	if (!(duration > 0) || ![30, 60].includes(fps)) throw new Error("字幕时长或 fps 无效");
	if (providerTrack) {
		const precise = providerCaptions(providerTrack, text, duration, fps, start);
		if (precise) return {cues: precise, method: "provider-alignment"};
		// An unusable sidecar must not turn estimated timestamps into claimed alignment.
		return {cues: approximateSentences(text, start, end), method: "approximate-text-weight", warning: "词界轨无效或与旁白不匹配，已回退估算字幕"};
	}
	let input, method = "approximate-text-weight";
	if (alignment) {
		if (alignment.unit !== "seconds" || alignment.origin !== "audio" || !Array.isArray(alignment.segments)) throw new Error("对齐轨必须为 audio-relative seconds segments");
		input = alignment.segments.map((c) => ({t: c.t, start: start + Math.round(c.start * fps), end: start + Math.round(c.end * fps)}));
		method = alignment.source === "whisper" ? "whisper-alignment" : "provider-alignment";
	} else if (Array.isArray(cues) && cues.length) {
		input = cues;
		method = "supplied-scene-frames";
	}
	if (!input) return {cues: approximateSentences(text, start, end), method};
	let previous = start;
	for (const c of input) {
		if (typeof c.t !== "string" || !Number.isInteger(c.start) || !Number.isInteger(c.end) || c.start < previous || c.end <= c.start || c.end > end) throw new Error("对齐字幕越界、重叠或时间无效");
		previous = c.end;
	}
	if (compact(input.map((c) => c.t).join("")) !== compact(text)) throw new Error("对齐字幕与当前旁白不一致，请重新选择匹配的对齐轨");
	const grouped = [];
	for (const c of input) {
		const last = grouped.at(-1);
		if (last && c.start - last.end <= fps * 0.12 && weight(last.t + c.t) <= 30 && !/[。！？；!?;]$/u.test(last.t)) {
			last.t += c.t;
			last.end = c.end;
		} else grouped.push({...c});
	}
	const result = grouped.flatMap((c) => allocate(c.t, c.start, c.end));
	return {cues: result, method: grouped.some((c) => splitCaption(c.t).length > 1) ? method + "+approximate-subdivision" : method};
}

export function captionAt(caption, frame, duration, fps) {
	const cues = typeof caption === "string" ? captionTimeline({text: caption, duration: duration / fps, fps}).cues : caption;
	return cues?.find((c) => frame >= c.start && frame < c.end)?.t ?? "";
}

export function toSrt(frames, fps) {
	const stamp = (f) => {
		let n = Math.round(f / fps * 1000);
		const ms = n % 1000;
		n = Math.floor(n / 1000);
		const s = n % 60;
		n = Math.floor(n / 60);
		return `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
	};
	let offset = 0, count = 0;
	const blocks = [];
	for (const f of frames) {
		for (const c of f.cues || []) blocks.push(`${++count}\n${stamp(offset + c.start)} --> ${stamp(offset + c.end)}\n${c.t}\n`);
		offset += f.durationInFrames;
	}
	return blocks.join("\n");
}

export function visualShots(cues, duration, fps) {
	// 3–6 second visual shots, independent of subtitle count. Snap to nearby cue
	// boundaries; leftover shorter than 3s merges into the previous shot.
	const min = 3 * fps, max = 6 * fps, target = 4.5 * fps;
	const shots = [];
	let start = 0;
	while (start < duration) {
		const remaining = duration - start;
		let end = duration;
		if (remaining > max) {
			const lo = start + min, hi = start + max;
			const candidates = (cues || []).map((c) => c.start).filter((t) => t >= lo && t <= hi && duration - t >= min);
			end = candidates.sort((a, b) => Math.abs(a - start - target) - Math.abs(b - start - target))[0]
				?? Math.min(start + target, duration - min);
			end = Math.round(end);
			if (duration - end < min) end = duration;
		}
		shots.push({start, end, label: ""});
		start = end;
	}
	for (const shot of shots) {
		shot.label = (cues || []).filter((c) => c.start < shot.end && c.end > shot.start).map((c) => c.t).join("");
	}
	return shots;
}
