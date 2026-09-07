// 模板注册表的单一事实源（与 src/Video.tsx TEMPLATES 键集人工保持一致；
// .tsx 无法被 node 侧直接 import，故此处以常量镜像，Video.tsx 改注册时必须同步本文件）
export const TEMPLATE_IDS = [
	"title",
	"event",
	"bars",
	"compare",
	"cards",
	"rows",
	"stacked",
	"versus",
	"checklist",
	"conclusion",
	"vtitle",
	"vstat",
	"vpoints",
];

export const VERTICAL_TEMPLATES = ["vtitle", "vstat", "vpoints"];
