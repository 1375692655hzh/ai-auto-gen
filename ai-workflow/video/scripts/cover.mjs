// 封面出图：读 <proj>/cover.json → remotion still CoverMaker out/cover.png
// 用法: node scripts/cover.mjs <projectId>
// cover.json 由 workbench 服务端写入（素材已拷贝进项目 cover_assets/，密钥零涉及）。
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const projectId = process.argv[2];
if (!projectId || !/^[a-zA-Z0-9_-]+$/.test(projectId)) {
	console.error("用法: node scripts/cover.mjs <projectId>");
	process.exit(1);
}
const projDir = path.join("videos", projectId);
const specFile = path.join(projDir, "cover.json");
if (!existsSync(specFile)) {
	console.error(`找不到 ${specFile} —— 先在工作台提交封面表单`);
	process.exit(1);
}
for (const key of ["bg", "person"]) {
	const rel = JSON.parse(readFileSync(specFile, "utf-8"))[key];
	if (rel && !existsSync(path.join(projDir, rel))) {
		console.error(`素材缺失: ${rel}`);
		process.exit(1);
	}
}
const outFile = path.join(projDir, "out", "cover.png");
mkdirSync(path.dirname(outFile), { recursive: true });
console.log("渲染封面 -> " + outFile);
// Windows 下行内 JSON --props 转义会炸（Remotion 官方提示），传文件路径替代
execFileSync(
	"npx",
	["remotion", "still", "CoverMaker", outFile, "--public-dir", projDir, `--props=${path.resolve(specFile)}`],
	{ stdio: "inherit", shell: true },
);
if (!existsSync(outFile)) {
	console.error("封面文件未生成");
	process.exit(1);
}
console.log("cover ok -> " + outFile);
