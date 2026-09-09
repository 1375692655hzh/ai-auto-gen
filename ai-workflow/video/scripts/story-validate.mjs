// story.json 渲染前校验器（移植自 ai-video，按本仓库能力裁剪扩展）
// 导出 validateStory(story) -> { errors: string[], warnings: string[] }
// 纪律：本仓库已有字段（captions/compact/summary/stat/tags/entrances/silent/durationS 等）
//       与不认识的 meta/scene 字段一律【警告】不报错——渲染由模板侧兜底，这里只拦硬伤。
// 硬伤（errors）：模板不在 Video.tsx 注册集合、9:16 与其他画幅混用模板、scenes 为空、
//                narration 为空、meta.fps/width/height 非正数、缺 data。
// 画幅支持 16:9/9:16/1:1/4:5；旧别名、未知标注与尺寸不匹配只警告，渲染以 meta 尺寸为准。
import { TEMPLATE_IDS, VERTICAL_TEMPLATES } from "./template-ids.mjs";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { realpathSync } from "node:fs";

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;
const DIMS = { "16:9": [1920, 1080], "9:16": [1080, 1920], "1:1": [1080, 1080], "4:5": [1080, 1350] };
const ALIASES = { horizontal: "16:9", vertical: "9:16" };

const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);

/** 场景级已知字段（超出者警告但放行） */
const KNOWN_SCENE_KEYS = new Set([
	"id", "template", "narration", "caption", "captions", "data",
	"silent", "durationS",
]);

export function validateStory(story) {
	const errors = [];
	const warnings = [];
	const err = (msg) => errors.push(msg);
	const warn = (msg) => warnings.push(msg);

	if (!isObj(story)) {
		return { errors: ["story 根必须是对象"], warnings };
	}
	const meta = story.meta;
	let aspect = "16:9";
	if (!isObj(meta)) {
		err("meta 缺失或不是对象");
	} else {
		for (const k of ["title", "voice"]) {
			if (typeof meta[k] !== "string" || !meta[k].trim()) {
				warn(`meta.${k} 建议为非空字符串（缺省时由引擎兜底）`);
			}
		}
		for (const k of ["fps", "width", "height"]) {
			if (meta[k] !== undefined && (typeof meta[k] !== "number" || meta[k] <= 0))
				err(`meta.${k} 必须是正数，收到 ${JSON.stringify(meta[k])}`);
		}
		const fmt = meta.format === undefined ? "16:9" : meta.format;
		aspect = typeof fmt === "string" && Object.hasOwn(ALIASES, fmt) ? ALIASES[fmt] : fmt;
		if (aspect !== fmt)
			warn(`旧画幅标注 ${fmt}，建议迁移为 ${aspect}`);
		else if (typeof aspect !== "string" || !Object.hasOwn(DIMS, aspect))
			warn(`未知画幅标注 ${JSON.stringify(fmt)}（放行，渲染以 meta.width/height 为准）`);
		if (meta.tts !== undefined) {
			if (!isObj(meta.tts)) err("meta.tts 必须是对象");
			else if (meta.tts.provider === "custom") {
				// 自定义 OpenAI 兼容供应商(如 mimo): 协议参数随 meta 透传, 密钥走环境变量
				if (!meta.tts.base_url || !meta.tts.model)
					err("meta.tts.provider=custom 时必须带 base_url 与 model");
			} else if (meta.tts.provider !== "edge" && meta.tts.provider !== "dashscope")
				err(`meta.tts.provider 只能是 edge|dashscope|custom，收到 ${JSON.stringify(meta.tts.provider)}`);
		}
		// format 只是标注，尺寸不匹配或缺省仅提示。
		if (typeof meta.width !== "number" || typeof meta.height !== "number") {
			warn("建议显式声明 meta.width / meta.height，渲染以这两个尺寸为准");
		} else if (typeof aspect === "string" && Object.hasOwn(DIMS, aspect)) {
			const [ew, eh] = DIMS[aspect];
			if (meta.width !== ew || meta.height !== eh) {
				warn(`meta 尺寸 ${meta.width}×${meta.height} 与 format=${aspect} 预期 ${ew}×${eh} 不匹配（渲染以 meta.width/height 为准）`);
			}
		}
		const knownMeta = new Set(["title", "voice", "tts", "fps", "width", "height",
			"padSeconds", "format", "theme", "layout"]);
		const unknownMeta = Object.keys(meta).filter((k) => !knownMeta.has(k));
		if (unknownMeta.length) warn(`meta 含未知字段（放行）: ${unknownMeta.join(", ")}`);
	}

	if (!Array.isArray(story.scenes) || story.scenes.length === 0) {
		err("scenes 必须是非空数组");
		return { errors, warnings };
	}

	const seenIds = new Set();
	story.scenes.forEach((s, i) => {
		const where = `scenes[${i}]`;
		if (!isObj(s)) return err(`${where} 不是对象`);
		if (typeof s.id !== "string" || !ID_RE.test(s.id))
			err(`${where}.id 必须是 kebab-case 字符串，收到 ${JSON.stringify(s.id)}`);
		else if (seenIds.has(s.id)) err(`${where}.id 重复：${s.id}`);
		else seenIds.add(s.id);
		if (!TEMPLATE_IDS.includes(s.template))
			err(`${where}.template 必须是 ${TEMPLATE_IDS.join("/")} 之一，收到 ${JSON.stringify(s.template)}`);
		if (aspect === "9:16" && !VERTICAL_TEMPLATES.includes(s.template))
			err(`${where}.template：9:16 竖版项目只允许 vtitle/vstat/vpoints 三个模板`);
		if (aspect !== "9:16" && VERTICAL_TEMPLATES.includes(s.template))
			err(`${where}.template：竖版模板只能用于 9:16 项目`);
		if (typeof s.narration !== "string" || !s.narration.trim())
			err(`${where}.narration 必须是非空字符串`);
		if (s.caption !== undefined && typeof s.caption !== "string")
			warn(`${where}.caption 建议是字符串（收到 ${typeof s.caption}，放行）`);
		if (s.data === undefined || !isObj(s.data)) {
			err(`${where}.data 缺失或不是对象（模板渲染会崩）`);
		} else {
            for (const key of ["src", "image"]) {
                const value = s.data[key];
                if (value != null && (typeof value !== "string" || !/^(materials|input\/collage)\/[a-zA-Z0-9_.-]+$/.test(value) || /(^|\/)\.\.?(\/|$)/.test(value)))
                    err(`${where} data.${key} 必须是项目内安全素材路径`);
            }
            if (["vox-fast-cut", "hand-drawn"].includes(s.template) && aspect !== "16:9") err(`${where} ${s.template} 仅支持 16:9`);
			if (s.template === "clip") {
				if (typeof s.data.src !== "string" || !s.data.src.trim())
					err(`${where}(${s.id}) clip.data.src 必须是非空字符串`);
				for (const k of ["start", "end", "zoom"]) {
					if (s.data[k] !== undefined && typeof s.data[k] !== "number")
						warn(`${where}(${s.id}) clip.data.${k} 建议为数字`);
				}
			}
			// 竖版三模板的最小可渲染字段（warning 级，防白屏不拦流程）
			if (s.template === "vtitle" && !Array.isArray(s.data.title))
				warn(`${where}(${s.id}) vtitle.data.title 建议为富文本数组`);
			if (s.template === "vstat" && (typeof s.data.value !== "string" || !s.data.value))
				warn(`${where}(${s.id}) vstat.data.value 建议为非空字符串`);
			if (s.template === "vpoints" &&
				(!Array.isArray(s.data.points) || s.data.points.length < 1))
				warn(`${where}(${s.id}) vpoints.data.points 建议为至少 1 条的数组`);
		}
		const unknown = Object.keys(s).filter((k) => !KNOWN_SCENE_KEYS.has(k));
		if (unknown.length) warn(`${where} 含未知字段（放行）: ${unknown.join(", ")}`);
	});

	// CTA 收尾场（warning 级；vox-collage 单风格主题以悬念收尾是特性，豁免）
	const last = story.scenes[story.scenes.length - 1];
	const singleStyle = story.meta?.theme === "vox-collage";
	if (isObj(last) && !singleStyle) {
		const ctaOk = aspect === "9:16"
			? last.template === "vpoints"
			: last.template === "conclusion";
		if (!ctaOk)
			warn(`最后一场(${last.id || "?"} ${last.template}) 不是 CTA 收尾版式` +
				(aspect === "9:16" ? "（建议 vpoints）" : "（建议 conclusion）"));
	}

	// 连续同版式提示（vox-collage 全场 paper-board 是主题特性，豁免）
	if (!singleStyle) {
		let run = 1;
		for (let i = 1; i < story.scenes.length; i++) {
			if (!isObj(story.scenes[i]) || !isObj(story.scenes[i - 1])) { run = 1; continue; }
			run = story.scenes[i].template === story.scenes[i - 1].template ? run + 1 : 1;
			if (run >= 4)
				warn(`scenes[${i}].id=${story.scenes[i].id}：连续 ${run} 场使用 ${story.scenes[i].template}，视觉单调`);
		}
	}

	return { errors, warnings };
}

/* ---- CLI 冒烟入口: node scripts/story-validate.mjs <story.json> ---- */
if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const file = process.argv[2];
	if (!file) {
		console.error("用法: node scripts/story-validate.mjs <story.json>");
		process.exit(2);
	}
	const target = JSON.parse(readFileSync(file, "utf-8"));
	const { errors, warnings } = validateStory(target);
	for (const w of warnings) console.warn(`⚠ ${w}`);
	if (errors.length > 0) {
		for (const e of errors) console.error(`✗ ${e}`);
		console.error(`校验未通过（${errors.length} 错误）`);
		process.exit(1);
	}
	console.log(`✓ 校验通过（${target.scenes.length} 场景，${warnings.length} 警告）`);
}
