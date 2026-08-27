// 新建视频项目脚手架
// 用法: node scripts/new-article.mjs <projectId> [文章文件路径]
import { existsSync, mkdirSync, copyFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const [, , projectId, articleSrc] = process.argv;
if (!projectId) {
	console.error("用法: node scripts/new-article.mjs <projectId> [文章文件路径]");
	console.error('示例: node scripts/new-article.mjs my-topic "D:\\articles\\my.md"');
	process.exit(1);
}

const projDir = path.join("videos", projectId);
if (existsSync(projDir)) {
	console.error(`已存在: ${projDir}`);
	process.exit(1);
}
for (const d of ["input", "script", "audio", "out"]) {
	mkdirSync(path.join(projDir, d), { recursive: true });
}

if (articleSrc && existsSync(articleSrc)) {
	copyFileSync(articleSrc, path.join(projDir, "input", "article" + path.extname(articleSrc)));
}

writeFileSync(
	path.join(projDir, "project.json"),
	JSON.stringify(
		{
			id: projectId,
			title: projectId,
			status: "draft",
			created: new Date().toISOString().slice(0, 10),
			note: "draft=待审核；reviewed=审核通过可制作；built=已出片。审核=改 story.json 的 narration 后把 status 改为 reviewed。",
		},
		null,
		"\t",
	),
);

writeFileSync(
	path.join(projDir, "story.json"),
	JSON.stringify(
		{
			meta: {
				title: projectId,
				voice: "zh-CN-YunxiNeural",
				fps: 30,
				width: 1920,
				height: 1080,
				padSeconds: 0.8,
			},
			scenes: [
				{
					id: "title",
					template: "title",
					narration: "（把文章交给 agent，由 agent 撰写各场景 narration 与画面数据；或手工编辑本文件）",
					data: {
						kicker: "新视频",
						titlePre: "",
						titlePost: " 标题",
						subtitle1: [{ t: "副标题第一行" }],
						subtitle2: [{ t: "副标题第二行" }],
					},
				},
			],
		},
		null,
		"\t",
	),
);

console.log(`已创建项目: ${projDir}`);
console.log(`下一步: 把文章放入 ${projDir}/input/，交给 agent 生成演讲稿与分镜（story.json），`);
console.log(`人工审核 narration 后把 project.json 的 status 改为 "reviewed"，然后:`);
console.log(`  node scripts/build.mjs ${projectId}`);
