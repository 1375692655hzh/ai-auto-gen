import { captionAt } from "../shared/captions.mjs";
// 场景模板库（三）：竖版 Shorts（1080×1920）—— vtitle / vstat / vpoints
// 移植自 ai-video 同名文件；本仓库 SceneProps 无 phrases/reveal 渐进揭示链路，
// 入场节奏一律回退模板固定 delay。Data 接口在本文件内声明（story-types 契约不动）。
import React from "react";
import {
	AbsoluteFill,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import type { CaptionCue, Rich as RichParts, SceneProps } from "./story-types";
import {
	Backdrop,
	COLORS,
	FadeUp,
	FONT,
	NumberTicker,
	Panel,
	Rich,
} from "./ui";

/* ---- 各竖版模板的 data 结构（本文件私有，运行时镜像） ---- */

/** vtitle：竖版开场大字标题 */
export interface VTitleData {
	title: RichParts;
	sub?: RichParts;
}

/** vstat：单数据大卡（数字 ticker + 标签 + 可选来源行） */
export interface VStatData {
	/** 可 ticker 的数字串：纯数字（可含千分位逗号与小数点），允许一个 %/亿/万 后缀 */
	value: string;
	label: RichParts;
	source?: string;
}

/** vpoints：2-4 条要点快切 */
export interface VPointsData {
	points: { text: RichParts }[];
	kicker?: RichParts;
}

/** 竖版安全区外壳：上下留出 Shorts 界面遮挡区；字幕条兼容 string 与帧级 cues */
const VShell: React.FC<{
	children: React.ReactNode;
	duration: number;
	caption?: string | CaptionCue[] | null;
}> = ({ children, duration, caption }) => {
	const frame = useCurrentFrame();
	const captionText = captionAt(caption, frame, duration, useVideoConfig().fps);
	const fade = interpolate(
		frame,
		[0, 10, duration - 10, duration],
		[0, 1, 1, 0],
		{ extrapolateLeft: "clamp", extrapolateRight: "clamp" },
	);
	return (
		<AbsoluteFill
			style={{
				opacity: fade,
				paddingTop: 210,
				paddingLeft: 70,
				paddingRight: 70,
				paddingBottom: 320,
				boxSizing: "border-box",
				fontFamily: FONT,
				color: COLORS.text,
			}}
		>
			{children}
			{captionText ? (
				<div
					style={{
						position: "absolute",
						left: 0,
						right: 0,
						bottom: 56,
						maxHeight: 240,
						overflow: "hidden",
						display: "flex",
						justifyContent: "center",
					}}
				>
					<div
						style={{
							maxWidth: 940,
							backgroundColor: "rgba(7,11,22,0.85)",
                            color: "#f5f5f5",
							border: `2px solid ${COLORS.border}`,
							borderRadius: 18,
							padding: "16px 40px",
							fontSize: 30,
							lineHeight: 1.5,
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

/* ---------------- vtitle：竖版开场大字 ---------------- */

export const VTitleTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as VTitleData;
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const lineGrow = spring({ frame: frame - 20, fps, config: { damping: 200 } });
	return (
		<VShell duration={duration} caption={caption}>
			<Backdrop />
			<div
				style={{
					height: "100%",
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
					flexDirection: "column",
					gap: 36,
				}}
			>
				<FadeUp delay={6}>
					<div
						style={{
							fontSize: 108,
							fontWeight: 800,
							textAlign: "center",
							lineHeight: 1.25,
						}}
					>
						<Rich parts={d.title} />
					</div>
				</FadeUp>
				<div
					style={{
						width: 320 * lineGrow,
						height: 6,
						backgroundColor: COLORS.nvidia,
						borderRadius: 3,
					}}
				/>
				{d.sub ? (
					<FadeUp delay={30}>
						<div
							style={{
								fontSize: 42,
								color: COLORS.sub,
								textAlign: "center",
								lineHeight: 1.5,
							}}
						>
							<Rich parts={d.sub} />
						</div>
					</FadeUp>
				) : null}
			</div>
		</VShell>
	);
};

/* ---------------- vstat：单数据大卡 ---------------- */

const VSTAT_RE = /^(-?)(\d[\d,]*)(?:\.(\d+))?(%|亿|万)?$/;

export const VStatTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as VStatData;
	const match = (d.value ?? "").match(VSTAT_RE);
	const fontSize = d.value.length <= 4 ? 190 : d.value.length <= 6 ? 150 : 116;
	const delay = 8; // 本仓库无 phrases 对齐链路，固定入场
	const numericValue = match
		? Number(`${match[1]}${match[2].replace(/,/g, "")}.${match[3] ?? "0"}`)
		: 0;
	return (
		<VShell duration={duration} caption={caption}>
			<Backdrop />
			<div
				style={{
					height: "100%",
					display: "flex",
					alignItems: "center",
					justifyContent: "center",
					flexDirection: "column",
					textAlign: "center",
				}}
			>
				<FadeUp delay={delay} y={20}>
					<div
						style={{
							fontSize,
							fontWeight: 800,
							color: COLORS.nvidia,
							fontVariantNumeric: "tabular-nums",
							lineHeight: 1.1,
						}}
					>
						{match ? (
							<NumberTicker
								value={numericValue}
								decimals={match[3]?.length ?? 0}
								durationFrames={50}
								delay={delay}
								suffix={match[4] ?? ""}
							/>
						) : (
							d.value
						)}
					</div>
					<div style={{ fontSize: 46, marginTop: 24, lineHeight: 1.5 }}>
						<Rich parts={d.label} />
					</div>
					{d.source ? (
						<div style={{ fontSize: 26, color: COLORS.sub, marginTop: 16 }}>
							{d.source}
						</div>
					) : null}
				</FadeUp>
			</div>
		</VShell>
	);
};

/* ---------------- vpoints：要点快切 ---------------- */

export const VPointsTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as VPointsData;
	return (
		<VShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
				{d.kicker ? (
					<FadeUp delay={6} y={14}>
						<div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1.4 }}>
							<Rich parts={d.kicker} />
						</div>
					</FadeUp>
				) : null}
				<div
					style={{
						flex: 1,
						display: "flex",
						flexDirection: "column",
						justifyContent: "center",
						gap: 22,
					}}
				>
					{(d.points ?? []).map((point, i) => (
						<FadeUp key={i} delay={20 + i * 40}>
							<Panel style={{ padding: "28px 34px" }}>
								<div style={{ fontSize: 42, lineHeight: 1.5 }}>
									<Rich parts={point.text} />
								</div>
							</Panel>
						</FadeUp>
					))}
				</div>
			</div>
		</VShell>
	);
};
