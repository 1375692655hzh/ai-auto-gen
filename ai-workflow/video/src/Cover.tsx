// 封面制作 Composition：背景图 + 人物形象 + 标题 → 单帧封面。
// 移植参考仓 E:\ai-video 的 cover.html 设计（人物照右侧 + 左侧压暗渐变 + 大标题 + 琥珀高亮），
// 用 Remotion still 出图（确定性强、零新增依赖）。props 经 --props JSON 注入（cover.json）。
import { AbsoluteFill, Img, staticFile } from "remotion";
import React from "react";

export interface CoverSpec {
	bg?: string;          // 项目目录相对路径（staticFile 解析）
	person?: string;
	title?: string;       // 支持 \n 分行；**文字** 走琥珀渐变高亮
	kicker?: string;      // 顶部小字（如「年底 AI 主线 · 投资逻辑」）
	sub?: string;         // 底部副标题
	width?: number;
	height?: number;
	accent?: string;      // 强调色，默认琥珀
}

type Segment = { text: string; hl: boolean };

const parseLine = (line: string): Segment[] =>
	line
		.split("**")
		.map((text, i) => ({ text, hl: i % 2 === 1 }))
		.filter((seg) => seg.text.length > 0);

export const CoverMaker: React.FC<CoverSpec> = (spec) => {
	const width = spec.width ?? 1920;
	const height = spec.height ?? 1080;
	const vertical = height > width;
	const accent = spec.accent ?? "#FFB020";
	const s = width / 1920;                 // 版式按横版 1920 基准等比缩放
	const lines = String(spec.title ?? "").split("\n").filter((l) => l.trim().length > 0);
	const padX = Math.round(100 * s);
	const titleSize = Math.round((vertical ? 96 : 124) * s);

	return (
		<AbsoluteFill style={{ backgroundColor: "#070B16", fontFamily: '"Microsoft YaHei","PingFang SC",sans-serif' }}>
			{spec.bg ? (
				<Img src={staticFile(spec.bg)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
			) : null}
			{/* 人物形象：右侧站立，底部微留边，与背景自然叠加 */}
			{spec.person ? (
				<Img
					src={staticFile(spec.person)}
					style={{
						position: "absolute",
						right: Math.round(60 * s),
						bottom: 0,
						height: "94%",
						objectFit: "contain",
						filter: "drop-shadow(0 12px 40px rgba(0,0,0,0.55))",
					}}
				/>
			) : null}
			{/* 左侧压暗渐变保证标题可读（参考仓 scrim 设计） */}
			<div
				style={{
					position: "absolute",
					inset: 0,
					background: vertical
						? "linear-gradient(0deg, rgba(7,11,22,0.96) 0%, rgba(7,11,22,0.80) 38%, rgba(7,11,22,0.30) 62%, rgba(7,11,22,0) 80%)"
						: "linear-gradient(90deg, rgba(7,11,22,0.94) 0%, rgba(7,11,22,0.82) 30%, rgba(7,11,22,0.35) 55%, rgba(7,11,22,0) 75%), linear-gradient(0deg, rgba(7,11,22,0.55) 0%, rgba(7,11,22,0) 30%)",
				}}
			/>
			<div
				style={{
					position: "absolute",
					left: padX,
					right: padX,
					...(vertical ? { bottom: Math.round(90 * s) } : { top: "50%", transform: "translateY(-50%)" }),
				}}
			>
				{spec.kicker ? (
					<div style={{ display: "flex", alignItems: "center", gap: Math.round(18 * s), color: accent, fontSize: Math.round(38 * s), fontWeight: 700, letterSpacing: 6 * s, marginBottom: Math.round(40 * s) }}>
						<span style={{ width: Math.round(60 * s), height: Math.round(7 * s), background: accent, borderRadius: 3 }} />
						{spec.kicker}
					</div>
				) : null}
				<div style={{ color: "#F5F7FA", fontSize: titleSize, fontWeight: 900, lineHeight: 1.18, textShadow: "0 6px 30px rgba(0,0,0,0.8)" }}>
					{lines.map((line, i) => (
						<div key={i}>
							{parseLine(line).map((seg, j) =>
								seg.hl ? (
									<span
										key={j}
										style={{
											background: `linear-gradient(180deg, #FFD34D 0%, ${accent} 55%, #E08A00 100%)`,
											WebkitBackgroundClip: "text",
											backgroundClip: "text",
											color: "transparent",
											textShadow: "none",
											filter: `drop-shadow(0 0 26px ${accent}73) drop-shadow(0 6px 24px rgba(0,0,0,0.8))`,
										}}
									>
										{seg.text}
									</span>
								) : (
									<span key={j}>{seg.text}</span>
								),
							)}
						</div>
					))}
				</div>
				{spec.sub ? (
					<div style={{ marginTop: Math.round(48 * s), display: "flex", alignItems: "center", gap: Math.round(22 * s), color: "#9AA7BD", fontSize: Math.round(42 * s), fontWeight: 600, letterSpacing: 3 * s }}>
						<span>{spec.sub}</span>
						<span style={{ width: Math.round(10 * s), height: Math.round(10 * s), borderRadius: "50%", background: accent }} />
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};
