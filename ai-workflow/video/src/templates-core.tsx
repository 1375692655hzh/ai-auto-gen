// 场景模板库（一）：标题 / 事件 / 跌幅柱状图 / 双栏对比 / 特征卡片
import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type {
	BarsData,
	CardsData,
	CompareData,
	EventData,
	PanelSpec,
	SceneProps,
	TitleData,
} from "./story-types";
import {
	Backdrop,
	Chip,
	colorOf,
	COLORS,
	FadeUp,
	Kicker,
	NumberTicker,
	Panel,
	Rich,
	RichTitle,
	SceneShell,
} from "./ui";

/* ---------------- title：开场标题 ---------------- */

export const TitleTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as TitleData;
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const lineGrow = spring({ frame: frame - 20, fps, config: { damping: 200 } });
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<AbsoluteFill
				style={{
					alignItems: "center",
					justifyContent: "center",
					flexDirection: "column",
					gap: 36,
				}}
			>
				<Kicker text={d.kicker ?? ""} color={colorOf(d.kickerColor)} delay={4} />
				<FadeUp delay={10}>
					<div style={{ fontSize: 110, fontWeight: 800, textAlign: "center", lineHeight: 1.2 }}>
						{d.titlePre}
						{d.ticker !== undefined ? (
							<NumberTicker
								value={d.ticker}
								decimals={d.tickerDecimals ?? 0}
								delay={14}
								durationFrames={50}
							/>
						) : null}
						{d.titlePost}
					</div>
				</FadeUp>
				<div
					style={{
						width: 240 * lineGrow,
						height: 6,
						backgroundColor: COLORS.nvidia,
						borderRadius: 3,
					}}
				/>
				<FadeUp delay={34}>
					<div style={{ fontSize: 44, color: COLORS.sub, textAlign: "center", lineHeight: 1.6 }}>
						<Rich parts={d.subtitle1 ?? []} />
						<br />
						<Rich parts={d.subtitle2 ?? []} />
					</div>
				</FadeUp>
			</AbsoluteFill>
		</SceneShell>
	);
};

/* ---------------- event：事件陈述（机构+数字+面板+引言） ---------------- */

export const EventTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as EventData;
	const chipColor = d.chipColor ?? "blue";
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 30 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				{d.chips?.length ? (
					<FadeUp delay={16} y={16}>
						<div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 6 }}>
							{d.chips.map((name, i) => (
								<FadeUp key={name} delay={20 + i * 6} y={12}>
									<Chip color={colorOf(chipColor)}>{name}</Chip>
								</FadeUp>
							))}
						</div>
					</FadeUp>
				) : null}
				<div style={{ flex: 1, display: "flex", alignItems: "center", gap: 70 }}>
					{d.stat ? (
						<FadeUp delay={60}>
							<div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
								<span style={{ fontSize: 170, fontWeight: 800, color: COLORS.nvidia }}>
									{d.stat.prefix}
									<NumberTicker
										value={d.stat.value}
										decimals={d.stat.decimals ?? 0}
										delay={64}
										durationFrames={60}
									/>
								</span>
								<span style={{ fontSize: 56, fontWeight: 700 }}>{d.stat.suffix}</span>
							</div>
							{d.stat.label ? (
							<div style={{ fontSize: 34, color: COLORS.sub, marginTop: 4 }}>
									<Rich parts={d.stat.label} />
							</div>
							) : null}
						</FadeUp>
					) : null}
					{d.panel ? (
						<FadeUp delay={100} style={{ flex: 1 }}>
							<Panel accent={d.panel.accent ? colorOf(d.panel.accent) : undefined}>
								{d.panel.title ? (
									<div style={{ fontSize: 38, fontWeight: 700, color: colorOf(d.panel.accent ?? "nvidia") }}>
										<Rich parts={d.panel.title} />
									</div>
								) : null}
								{d.panel.items ? (
									<div style={{ fontSize: 36, lineHeight: 1.7, marginTop: 16 }}>
										{d.panel.items.map((line, i) => (
											<div key={i} style={{ marginTop: i === 0 ? 0 : 6 }}>
												<Rich parts={line} />
											</div>
										))}
									</div>
								) : null}
							</Panel>
						</FadeUp>
					) : null}
				</div>
				{d.quote ? (
					<FadeUp delay={150}>
						<Panel accent={colorOf(d.quote.accent ?? "amber")} style={{ padding: "26px 36px" }}>
							<span style={{ fontSize: 36, lineHeight: 1.6 }}>
								{d.quote.source ? (
									<span style={{ color: colorOf(d.quote.accent ?? "amber"), fontWeight: 700 }}>
										{d.quote.source}
									</span>
								) : null}
								<Rich parts={d.quote.text} />
							</span>
						</Panel>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};

/* ---------------- bars：跌幅柱状图 ---------------- */

interface BarData {
	name: string;
	pct: number;
	tag?: string;
}

export const BarsTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as BarsData;
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const maxLen = 430;
	const maxPct = Math.max(...d.bars.map((b) => b.pct), 1);
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
				<Kicker text={d.kicker ?? ""} color={colorOf(d.kickerColor ?? "red")} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				<div
					style={{
						flex: 1,
						display: "flex",
						alignItems: "flex-start",
						gap: 26,
						marginTop: 40,
						paddingTop: 60,
						borderTop: `3px solid ${COLORS.border}`,
					}}
				>
					{d.bars.map((b: BarData, i) => {
						const len = (b.pct / maxPct) * maxLen;
						const grow = spring({
							frame: frame - 40 - i * 5,
							fps,
							config: { damping: 200, mass: 1.1 },
						});
						const color = b.tag ? COLORS.amber : COLORS.red;
						return (
							<div
								key={b.name}
								style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}
							>
								<div
									style={{
										fontSize: 40,
										fontWeight: 800,
										color,
										fontVariantNumeric: "tabular-nums",
										opacity: grow,
									}}
								>
									-{(b.pct * grow).toFixed(1)}%
								</div>
								<div
									style={{
										width: "72%",
										height: len * grow,
										minHeight: 4,
										backgroundColor: color,
										borderRadius: "0 0 12px 12px",
										opacity: 0.92,
									}}
								/>
								<div style={{ fontSize: 30, marginTop: 18, fontWeight: 600 }}>{b.name}</div>
								{b.tag ? (
									<div style={{ fontSize: 22, color: COLORS.amber, marginTop: 4 }}>{b.tag}</div>
								) : null}
							</div>
						);
					})}
				</div>
				{d.footnote ? (
					<FadeUp delay={140}>
						<div style={{ fontSize: 34, color: COLORS.sub, textAlign: "center", paddingBottom: 8 }}>
							<Rich parts={d.footnote} />
						</div>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};

/* ---------------- compare：双栏对比面板 ---------------- */

export const ComparePanel: React.FC<{
	panel: PanelSpec;
	delay: number;
}> = ({ panel, delay }) => {
	const accent = colorOf(panel.accent);
	return (
		<FadeUp delay={delay} style={{ flex: panel.grow ?? 1 }}>
			<Panel accent={accent} style={{ height: "100%" }}>
				{panel.title ? (
					<div style={{ fontSize: 40, fontWeight: 800, color: accent, marginBottom: 24 }}>
						<Rich parts={panel.title} />
					</div>
				) : null}
				{panel.sub ? (
					<div style={{ fontSize: 32, color: COLORS.sub, marginBottom: 22 }}>
						<Rich parts={panel.sub} />
					</div>
				) : null}
				{panel.stat ? (
					<div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 18 }}>
						<span style={{ fontSize: 90, fontWeight: 800, color: COLORS.nvidia }}>
							{panel.stat.prefix}
							<NumberTicker
								value={panel.stat.value}
								decimals={panel.stat.decimals ?? 0}
								delay={delay + 6}
								durationFrames={50}
							/>
						</span>
						<span style={{ fontSize: 40, fontWeight: 700 }}>{panel.stat.suffix}</span>
					</div>
				) : null}
				{panel.chips ? (
					<div style={{ display: "flex", flexDirection: "column", gap: 18, alignItems: "flex-start" }}>
						{panel.chips.map((c) => (
							<Chip key={c} color={colorOf(panel.chipColor ?? "blue")}>
								{c}
							</Chip>
						))}
					</div>
				) : null}
				{panel.items
					? panel.items.map((line, i) => (
							<FadeUp key={i} delay={delay + 14 + i * 18}>
								<div style={{ fontSize: 35, lineHeight: 1.55, marginBottom: 16 }}>
									<Rich parts={line} />
								</div>
							</FadeUp>
						))
					: null}
				{panel.lines ? (
					<div style={{ fontSize: 36, lineHeight: 1.7 }}>
						{panel.lines.map((line, i) => (
							<div key={i} style={{ marginTop: i === 0 ? 0 : 10 }}>
								<Rich parts={line} />
							</div>
						))}
					</div>
				) : null}
				{panel.footer ? (
					<div style={{ fontSize: 33, marginTop: 22 }}>
						<Rich parts={panel.footer} />
					</div>
				) : null}
			</Panel>
		</FadeUp>
	);
};

export const CompareTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as CompareData;
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const arrow = spring({ frame: frame - 90, fps, config: { damping: 200 } });
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 34 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				<div style={{ flex: 1, display: "flex", alignItems: "stretch", gap: 24 }}>
					<ComparePanel panel={d.left} delay={26} />
					{d.arrow ? (
						<div
							style={{
								display: "flex",
								alignItems: "center",
								fontSize: 90,
								color: COLORS.nvidia,
								opacity: arrow,
								transform: `translateX(${(1 - arrow) * -40}px)`,
								fontWeight: 800,
							}}
						>
							→
						</div>
					) : null}
					<ComparePanel panel={d.right} delay={72} />
				</div>
				{d.bottom ? (
					<FadeUp delay={150}>
						<Panel accent={colorOf(d.bottom.accent ?? "amber")} style={{ padding: "24px 36px" }}>
							<span style={{ fontSize: 33, lineHeight: 1.65 }}>
								<Rich parts={d.bottom.body} />
							</span>
						</Panel>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};

/* ---------------- cards：特征卡片 ---------------- */

export const CardsTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as CardsData;
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 36 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				<div style={{ flex: 1, display: "flex", alignItems: "center", gap: 28 }}>
					{d.cards.map((f, i) => (
						<FadeUp key={f.title} delay={26 + i * 10} style={{ flex: 1 }}>
							<Panel
								accent={COLORS.nvidia}
								style={{
									height: 300,
									display: "flex",
									flexDirection: "column",
									alignItems: "center",
									justifyContent: "center",
									gap: 24,
								}}
							>
								<div style={{ fontSize: 72, color: COLORS.nvidia, fontWeight: 800 }}>{f.icon}</div>
								<div style={{ fontSize: 36, fontWeight: 700, textAlign: "center" }}>{f.title}</div>
							</Panel>
						</FadeUp>
					))}
				</div>
				{d.question ? (
					<FadeUp delay={110}>
						<div style={{ fontSize: 38, color: COLORS.sub, textAlign: "center" }}>
							<Rich parts={d.question} />
						</div>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};
