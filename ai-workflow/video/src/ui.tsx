import React from "react";
import {
	AbsoluteFill,
	Easing,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import type { CaptionCue } from "./story-types";
import type { ColorKey, Rich as RichParts } from "./story-types";

export const COLORS = {
	bgDeep: "#070B16",
	text: "#F5F7FA",
	sub: "#9AA7BD",
	nvidia: "#76B900",
	red: "#FF5A5A",
	green: "#00C896",
	amber: "#FFB020",
	blue: "#4D9FFF",
	purple: "#9B7BFF",
	panel: "rgba(255,255,255,0.045)",
	panelStrong: "rgba(255,255,255,0.08)",
	border: "rgba(255,255,255,0.10)",
};

export const FONT =
	'"Microsoft YaHei", "PingFang SC", "Noto Sans SC", "Source Han Sans SC", sans-serif';

/** 颜色关键字 -> 主题色 */
export const colorOf = (k?: ColorKey): string => (k ? COLORS[k] ?? COLORS.text : COLORS.text);

/** 富文本渲染：[{t:"文字",c:"green",b:true}, ...] */
export const Rich: React.FC<{ parts: RichParts; style?: React.CSSProperties }> = ({ parts, style }) => (
	<span style={style}>
		{parts.map((p, i) =>
			p.br ? (
				<br key={i} />
			) : (
				<span
					key={i}
					style={{
						color: p.c ? colorOf(p.c) : undefined,
						fontWeight: p.b ? 800 : undefined,
					}}
				>
					{p.t}
				</span>
			),
		)}
	</span>
);

/** 富文本大标题 */
export const RichTitle: React.FC<{
	parts: RichParts;
	delay?: number;
	size?: number;
	marginTop?: number;
}> = ({ parts, delay = 6, size = 84, marginTop = 26 }) => (
	<FadeUp delay={delay}>
		<div
			style={{
				fontSize: size,
				fontWeight: 800,
				lineHeight: 1.18,
				marginTop,
				letterSpacing: "0.01em",
			}}
		>
			<Rich parts={parts} />
		</div>
	</FadeUp>
);

export const Backdrop: React.FC = () => {
	return (
		<AbsoluteFill style={{ backgroundColor: COLORS.bgDeep }}>
			<AbsoluteFill
				style={{
					background:
						"radial-gradient(1300px 750px at 28% 18%, rgba(118,185,0,0.10), transparent 62%), radial-gradient(1100px 650px at 82% 88%, rgba(77,159,255,0.10), transparent 62%)",
				}}
			/>
			<AbsoluteFill
				style={{
					opacity: 0.55,
					backgroundImage:
						"linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
					backgroundSize: "96px 96px",
				}}
			/>
			<AbsoluteFill
				style={{
					background:
						"radial-gradient(1500px 950px at 50% 50%, transparent 55%, rgba(0,0,0,0.55))",
				}}
			/>
		</AbsoluteFill>
	);
};

/** 场景外壳：入场淡入 + 出场淡出 + 底部字幕条 */
export const SceneShell: React.FC<{
	children: React.ReactNode;
	duration: number;
	caption?: string | CaptionCue[] | null;
	padding?: number;
}> = ({ children, duration, caption, padding = 90 }) => {
	const frame = useCurrentFrame();
	const captionText = Array.isArray(caption)
		? (caption.find((c) => frame >= c.start && frame < c.end) ?? caption[caption.length - 1])?.t ?? ""
		: caption;
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
				paddingTop: padding,
				paddingLeft: padding,
				paddingRight: padding,
				paddingBottom: captionText ? 200 : padding,
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
						bottom: 34,
						display: "flex",
						justifyContent: "center",
					}}
				>
					<div
						style={{
							maxWidth: 1560,
							backgroundColor: "rgba(7,11,22,0.85)",
							border: `2px solid ${COLORS.border}`,
							borderRadius: 18,
							padding: "16px 40px",
							fontSize: 34,
							lineHeight: 1.5,
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

/** 弹簧上浮入场 */
export const FadeUp: React.FC<{
	children: React.ReactNode;
	delay?: number;
	y?: number;
	style?: React.CSSProperties;
}> = ({ children, delay = 0, y = 30, style }) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const s = spring({
		frame: frame - delay,
		fps,
		config: { damping: 200, mass: 0.9 },
	});
	return (
		<div
			style={{
				...style,
				opacity: s,
				transform: `translateY(${(1 - s) * y}px)`,
			}}
		>
			{children}
		</div>
	);
};

/** 数字滚动 */
export const NumberTicker: React.FC<{
	value: number;
	decimals?: number;
	durationFrames?: number;
	delay?: number;
	prefix?: string;
	suffix?: string;
	style?: React.CSSProperties;
}> = ({
	value,
	decimals = 0,
	durationFrames = 40,
	delay = 0,
	prefix = "",
	suffix = "",
	style,
}) => {
	const frame = useCurrentFrame();
	const p = interpolate(frame, [delay, delay + durationFrames], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
		easing: Easing.out(Easing.cubic),
	});
	return (
		<span style={{ fontVariantNumeric: "tabular-nums", ...style }}>
			{prefix}
			{(value * p).toFixed(decimals)}
			{suffix}
		</span>
	);
};

/** 眉标 */
export const Kicker: React.FC<{
	text: string;
	color?: string;
	delay?: number;
}> = ({ text, color = COLORS.nvidia, delay = 0 }) => (
	<FadeUp delay={delay} y={14}>
		<div style={{ display: "flex", alignItems: "center", gap: 16 }}>
			<div style={{ width: 46, height: 6, backgroundColor: color, borderRadius: 3 }} />
			<span
				style={{
					fontSize: 30,
					fontWeight: 700,
					letterSpacing: "0.28em",
					color,
				}}
			>
				{text}
			</span>
		</div>
	</FadeUp>
);

/** 药丸标签 */
export const Chip: React.FC<{
	children: React.ReactNode;
	color?: string;
	style?: React.CSSProperties;
}> = ({ children, color = COLORS.text, style }) => (
	<span
		style={{
			padding: "12px 26px",
			borderRadius: 999,
			border: `2px solid ${color}55`,
			backgroundColor: `${color}14`,
			fontSize: 30,
			fontWeight: 600,
			color,
			whiteSpace: "nowrap",
			...style,
		}}
	>
		{children}
	</span>
);

/** 面板 */
export const Panel: React.FC<{
	children: React.ReactNode;
	accent?: string;
	style?: React.CSSProperties;
}> = ({ children, accent, style }) => (
	<div
		style={{
			backgroundColor: COLORS.panel,
			border: `2px solid ${COLORS.border}`,
			borderRadius: 24,
			padding: 36,
			position: "relative",
			overflow: "hidden",
			...(accent
				? {
						borderLeft: `6px solid ${accent}`,
					}
				: {}),
			...style,
		}}
	>
		{children}
	</div>
);

/** 大标题 */
export const Headline: React.FC<{
	children: React.ReactNode;
	delay?: number;
	size?: number;
}> = ({ children, delay = 6, size = 84 }) => (
	<FadeUp delay={delay}>
		<div
			style={{
				fontSize: size,
				fontWeight: 800,
				lineHeight: 1.18,
				marginTop: 26,
				letterSpacing: "0.01em",
			}}
		>
			{children}
		</div>
	</FadeUp>
);
