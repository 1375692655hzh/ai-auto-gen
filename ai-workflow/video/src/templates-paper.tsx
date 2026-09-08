// 场景模板库（四）：横版纸拼贴档案（VOX 风格）—— paper-board
// 每 scene 一张 AI 生成的纸拼贴海报（seedream, 1920×1920, 存 videos/<id>/input/collage/），
// 模板负责：拼贴图"钉入"入场 → 打字机纸条/红章依次钉上 → 微动（呼吸摆动 + Ken Burns）。
// Data 接口在本文件内声明（story-types 契约不动）；图缺失时回退纯纸板+打字机大字。
import React from "react";
import {
	AbsoluteFill,
	Img,
	interpolate,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import type { SceneProps } from "./story-types";
import { FONT } from "./ui";

/* ---- paper-board 的 data 结构（本文件私有，运行时镜像） ---- */
export interface PaperBoardData {
	/** 拼贴图相对项目目录路径(staticFile 解析)：input/collage/<scene>.jpeg；缺失则纯纸板回退 */
	image?: string | null;
	/** 打字机纸条文本(档案标签：地点/日期/人名，≤10 字) */
	label?: string;
	/** 红色橡皮印章文本(≤6 字，可缺省) */
	stamp?: string;
	/** 无图回退时的打字机大字(通常=scene.title) */
	fallback_title?: string;
}

/* ---- 档案纸板底色(生成图自带背景, 但无图回退/留边时露出) ---- */
const PAPER_BG = "linear-gradient(160deg, #ece1c6 0%, #e2d4b2 55%, #d8c9a4 100%)";

const Tape: React.FC<{ style: React.CSSProperties; delay: number }> = ({ style, delay }) => {
	const frame = useCurrentFrame();
	const opacity = interpolate(frame, [delay, delay + 12], [0, 0.75], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	return (
		<div
			style={{
				position: "absolute",
				width: 190,
				height: 56,
				background: "rgba(222,210,170,0.55)",
				borderLeft: "2px dashed rgba(160,140,90,0.35)",
				borderRight: "2px dashed rgba(160,140,90,0.35)",
				boxShadow: "0 2px 6px rgba(60,40,10,0.18)",
				opacity,
				...style,
			}}
		/>
	);
};

/** 黄铜图钉(径向渐变小圆) */
const Pin: React.FC<{ style: React.CSSProperties }> = ({ style }) => (
	<div
		style={{
			position: "absolute",
			width: 26,
			height: 26,
			borderRadius: "50%",
			background: "radial-gradient(circle at 35% 30%, #f0c060 0%, #b5762a 55%, #6e4212 100%)",
			boxShadow: "0 3px 6px rgba(60,40,10,0.45)",
			...style,
		}}
	/>
);

const PaperBoardTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const data = (scene.data ?? {}) as PaperBoardData;

	// 入场: 图 spring 钉入(0-24), 纸条(22-38), 红章(38-52); 之后整体微摆
	const pin = spring({ frame, fps, config: { damping: 12, stiffness: 110 }, durationInFrames: 24 });
	const labelIn = interpolate(frame, [22, 38], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
	const stampIn = spring({ frame: frame - 38, fps, config: { damping: 9, stiffness: 160 }, durationInFrames: 14 });
	const sway = Math.sin(frame / 46) * 0.35;               // 微摆(度)
	const ken = interpolate(frame, [0, duration], [1.07, 1.0]); // Ken Burns 缓推

	const captionText = Array.isArray(caption)
		? (caption.find((c) => frame >= c.start && frame < c.end) ?? caption[caption.length - 1])?.t ?? ""
		: caption;
	const fade = interpolate(frame, [0, 10, duration - 10, duration], [0, 1, 1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const label = (data.label || "").slice(0, 12);
	const stamp = (data.stamp || "").slice(0, 6);

	return (
		<AbsoluteFill style={{ background: PAPER_BG, opacity: fade, fontFamily: FONT, overflow: "hidden" }}>
			{/* 拼贴主图(带纸白边, 轻微右倾, spring 钉入 + 微摆 + Ken Burns) */}
			{data.image ? (
				<AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
					<div
						style={{
							width: "72%",
							height: "86%",
							transform: `rotate(${-1.6 + sway}deg) scale(${pin * ken})`,
							transformOrigin: "50% 42%",
							background: "#fdfbf5",
							padding: 16,
							boxShadow: "0 18px 46px rgba(70,50,15,0.38)",
							position: "relative",
						}}
					>
						<Img
							src={staticFile(data.image)}
							style={{ width: "100%", height: "100%", objectFit: "cover" }}
						/>
						<Tape style={{ top: -24, left: 60, transform: "rotate(-8deg)" }} delay={10} />
						<Tape style={{ bottom: -22, right: 48, transform: "rotate(7deg)" }} delay={16} />
					</div>
				</AbsoluteFill>
			) : (
				/* 无图回退: 纸板 + 打字机大字 */
				<AbsoluteFill style={{ alignItems: "center", justifyContent: "center", padding: 120 }}>
					<div
						style={{
							fontFamily: '"Courier New", monospace',
							fontSize: 92,
							fontWeight: 700,
							color: "#3a3226",
							textAlign: "center",
							letterSpacing: 4,
							transform: `rotate(${sway / 2}deg)`,
							maxWidth: "84%",
						}}
					>
						{data.fallback_title || ""}
					</div>
				</AbsoluteFill>
			)}

			{/* 打字机纸条(档案标签): 左下, 纸白底 + 等宽字 + 黄铜钉 */}
			{label ? (
				<div
					style={{
						position: "absolute",
						left: 96,
						bottom: 150,
						transform: `rotate(-2.4deg) translateY(${(1 - labelIn) * 40}px)`,
						opacity: labelIn,
						background: "#f7f2e3",
						padding: "14px 42px",
						boxShadow: "0 8px 20px rgba(70,50,15,0.3)",
						borderTop: "2px solid rgba(160,140,90,0.4)",
					}}
				>
					<div style={{ position: "relative" }}>
						<span
							style={{
								fontFamily: '"Courier New", monospace',
								fontSize: 46,
								fontWeight: 700,
								letterSpacing: 8,
								color: "#33302a",
								textTransform: "uppercase",
							}}
						>
							{label}
						</span>
						<Pin style={{ top: -13, left: -13 }} />
						<Pin style={{ bottom: -13, right: -13 }} />
					</div>
				</div>
			) : null}

			{/* 红色橡皮印章: 右上, 盖章式 spring */}
			{stamp ? (
				<div
					style={{
						position: "absolute",
						right: 130,
						top: 120,
						transform: `rotate(9deg) scale(${stampIn > 0 ? 1.6 - 0.6 * stampIn : 1.6})`,
						opacity: stampIn * 0.88,
						border: "6px solid #c2372c",
						borderRadius: "50%",
						width: 210,
						height: 210,
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
					}}
				>
					<span
						style={{
							fontFamily: '"Courier New", monospace',
							fontSize: 56,
							fontWeight: 800,
							color: "#c2372c",
							letterSpacing: 4,
						}}
					>
						{stamp}
					</span>
				</div>
			) : null}

			{/* 字幕条(沿用暗底白字, 纸档案风格下保证可读) */}
			{captionText ? (
				<div
					style={{
						position: "absolute",
						left: 0,
						right: 0,
						bottom: 44,
						display: "flex",
						justifyContent: "center",
					}}
				>
					<div
						style={{
							maxWidth: 1240,
							backgroundColor: "rgba(30,24,14,0.86)",
							borderRadius: 14,
							padding: "14px 38px",
							fontSize: 32,
							lineHeight: 1.5,
							color: "#f5efdf",
							textAlign: "center",
						}}
					>
						{captionText}
					</div>
				</div>
			) : null}
		</AbsoluteFill>
	);
};

export default PaperBoardTpl;
