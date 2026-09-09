import { captionAt, splitCaption, visualShots } from "../shared/captions.mjs";
// 场景模板库（四）：横版纸拼贴档案（VOX 风格）—— paper-board
// 父 beat 不拆场景、不重合成语音。同一张拼贴图按 3–6 秒 visualShots 轮换安全构图
// （object-position 裁切，不伪称图内元素分层）。纸条/红章随 shot 切换。
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
	/** 各 shot 轮换的档案标签（原文 on_screen，缺省回退 label） */
	labels?: string[];
}

/** 安全构图：避开四角极端，只做整图裁切，不拆图层。 */
const CROPS = [
	{pos: "24% 30%", scale: 1.22},
	{pos: "76% 36%", scale: 1.18},
	{pos: "50% 70%", scale: 1.16},
	{pos: "42% 22%", scale: 1.24},
];

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
	const cues = Array.isArray(caption) ? caption : [];
	const shots = visualShots(cues, duration, fps);
	const index = Math.max(0, shots.findIndex((s) => frame >= s.start && frame < s.end));
	const shot = shots[index] || {start: 0, end: duration, label: ""};
	const local = frame - shot.start;
	const crop = CROPS[index % CROPS.length];

	const pin = spring({ frame: local, fps, config: { damping: 12, stiffness: 110 }, durationInFrames: 18 });
	const labelIn = interpolate(local, [6, 20], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
	const stampIn = spring({ frame: local - 14, fps, config: { damping: 9, stiffness: 160 }, durationInFrames: 12 });
	const sway = Math.sin((shot.start + local) / 46) * 0.35;
	const ken = interpolate(local, [0, Math.max(1, shot.end - shot.start)], [1.05, 1.0]);

	const captionText = captionAt(caption, frame, duration, fps);
	const fade = interpolate(frame, [0, 10, duration - 10, duration], [0, 1, 1, 0], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
	});
	const labels = (data.labels && data.labels.length ? data.labels : [data.label || ""]).filter(Boolean);
	const shotLine = splitCaption(shot.label)[0] || "";
	const label = String(labels[index % Math.max(1, labels.length)] || shotLine.replace(/\n/g, "")).slice(0, 12);
	const stamp = (data.stamp || "").slice(0, 6);

	return (
		<AbsoluteFill style={{ background: PAPER_BG, opacity: fade, fontFamily: FONT, overflow: "hidden" }}>
			<div style={{position: "absolute", top: 36, left: 70, fontSize: 24, letterSpacing: 4, color: "#6a5c48"}}>
				档案 · {String(index + 1).padStart(2, "0")}/{String(shots.length).padStart(2, "0")}
			</div>
			{/* 拼贴主图：整图裁切轮换，不拆图层 */}
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
							overflow: "hidden",
						}}
					>
						<Img
							src={staticFile(data.image)}
							style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: crop.pos, transform: `scale(${crop.scale})`, transformOrigin: crop.pos }}
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
						<span style={{whiteSpace: "pre-wrap"}}>{captionText}</span>
					</div>
				</div>
			) : null}
		</AbsoluteFill>
	);
};

export default PaperBoardTpl;
