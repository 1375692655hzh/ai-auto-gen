// 场景模板库（二）：证据行 / 归因堆叠面板 / 多空对照 / 验证清单 / 结论
import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import type {
	ChecklistData,
	ConclusionData,
	RowsData,
	SceneProps,
	StackedData,
	VersusData,
} from "./story-types";
import { Backdrop, Chip, colorOf, COLORS, FadeUp, Kicker, Panel, Rich, RichTitle, SceneShell } from "./ui";
import { ComparePanel } from "./templates-core";

/* ---------------- rows：证据行列表 ---------------- */

export const RowsTpl: React.FC<SceneProps> = (props) => {
	const d = props.scene.data as unknown as RowsData & { compact?: boolean };
	if (d.summary) return <EnrichedRowsTpl {...props} />;   // 丰富详情六区
	if (d.compact) {
		// 公告页：全静态无逐条动画(每页仅5s)。
		// 内容容器必须 position:relative+zIndex:1 —— Backdrop 是 absolute 层,
		// CSS 绘制顺序上定位元素晚于流内内容绘制,无 transform 的裸 div 会被整层盖住。
		const { duration, caption } = props;
		const ROW_H = 88, GAP = 16;
		return (
			<SceneShell duration={duration} caption={caption}>
				<Backdrop />
				<div
					style={{
						position: "relative",
						zIndex: 1,
						display: "flex",
						flexDirection: "column",
						height: "100%",
					}}
				>
					<div style={{ fontSize: 26, fontWeight: 700, letterSpacing: 6, color: COLORS.sub }}>
						{d.kicker}
					</div>
					<div style={{ fontSize: 54, fontWeight: 800, lineHeight: 1.25, marginTop: 14 }}>
						<Rich parts={d.headline} />
					</div>
					<div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: GAP }}>
						{d.rows.map((r, i) => (
							<div
								key={i}
								style={{
									display: "flex",
									gap: 22,
									alignItems: "flex-start",
									height: ROW_H,
									overflow: "hidden",
								}}
							>
								<span
									style={{
										fontSize: 26,
										fontWeight: 700,
										color: COLORS.sub,
										width: 52,
										flexShrink: 0,
										textAlign: "right",
										marginTop: 8,
										fontVariantNumeric: "tabular-nums",
									}}
								>
									<Rich parts={r.label} />
								</span>
								<div
									style={{
										flex: 1,
										fontSize: 30,
										lineHeight: 1.47,
										color: COLORS.text,
										textAlign: "left",
										display: "-webkit-box",
										WebkitLineClamp: 2,
										WebkitBoxOrient: "vertical",
										overflow: "hidden",
									}}
								>
									<Rich parts={r.body} />
								</div>
							</div>
						))}
					</div>
				</div>
			</SceneShell>
		);
	}
	const { duration, caption } = props;
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 30 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				<div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: 8 }}>
					{d.rows.map((r, i) => (
						<FadeUp key={i} delay={26 + i * 30}>
							<Panel accent={colorOf(r.accent)}>
								<div
									style={{
										display: "flex",
										alignItems: "center",
										justifyContent: "space-between",
										gap: 30,
										padding: "20px 36px",
									}}
								>
									<div style={{ fontSize: 36, fontWeight: 700, whiteSpace: "nowrap" }}>
										<Rich parts={r.label} />
									</div>
									<div style={{ fontSize: 34, textAlign: "left", flex: 1, lineHeight: 1.5 }}>
										<Rich parts={r.body} />
									</div>
								</div>
							</Panel>
						</FadeUp>
					))}
				</div>
				{d.footnote ? (
					<FadeUp delay={160}>
						<div style={{ fontSize: 34, color: COLORS.sub, textAlign: "center", lineHeight: 1.6 }}>
							<Rich parts={d.footnote} />
						</div>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};

/* ---------------- stacked：归因堆叠面板（问题转变 + N 块面板） ---------------- */

export const StackedTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as StackedData;
	const footDelay = Math.max(300, duration - 110);
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 28 }}>
				<Kicker text={d.kicker ?? ""} color={colorOf(d.kickerColor ?? "red")} delay={2} />
				<RichTitle parts={d.headline} delay={8} size={d.headlineSize ?? 84} />
				{d.transform ? (
					<FadeUp delay={20}>
						<div style={{ display: "flex", alignItems: "center", gap: 26, fontSize: 38 }}>
							<Rich parts={d.transform.from} />
							<span style={{ color: COLORS.nvidia, fontWeight: 800, fontSize: 46 }}>→</span>
							<Rich parts={d.transform.to} />
						</div>
					</FadeUp>
				) : null}
				<div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 22, justifyContent: "center" }}>
					{d.panels.map((p, i) => (
						<FadeUp key={i} delay={90 + i * 165}>
							<Panel accent={colorOf(p.accent)}>
								<div style={{ display: "flex", gap: 40, alignItems: "center" }}>
									<div
										style={{
											fontSize: 34,
											fontWeight: 800,
											color: colorOf(p.accent),
											whiteSpace: "nowrap",
										}}
									>
										<Rich parts={p.title} />
									</div>
									<div style={{ fontSize: 33, lineHeight: 1.7 }}>
										<Rich parts={p.body} />
									</div>
								</div>
							</Panel>
						</FadeUp>
					))}
				</div>
				{d.footnote ? (
					<FadeUp delay={footDelay}>
						<div style={{ fontSize: 32, color: COLORS.sub, textAlign: "center" }}>
							<Rich parts={d.footnote} />
						</div>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};

/* ---------------- versus：多空对照 ---------------- */

export const VersusTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as VersusData;
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 30 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				<div style={{ flex: 1, display: "flex", gap: 36 }}>
					<ComparePanel panel={{ ...d.bull, title: d.bull.title }} delay={24} />
					<ComparePanel panel={{ ...d.bear, title: d.bear.title }} delay={110} />
				</div>
				{d.footnote ? (
					<FadeUp delay={230}>
						<div style={{ fontSize: 33, color: COLORS.sub, textAlign: "center" }}>
							<Rich parts={d.footnote} />
						</div>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};

/* ---------------- checklist：验证清单 ---------------- */

export const ChecklistTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as ChecklistData;
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 34 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} />
				<div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: 20 }}>
					{d.items.map((c, i) => (
						<FadeUp key={c.tag} delay={24 + i * 16}>
							<Panel>
								<div style={{ display: "flex", alignItems: "center", gap: 34 }}>
									<div
										style={{
											fontSize: 34,
											fontWeight: 800,
											color: COLORS.nvidia,
											minWidth: 130,
											textAlign: "center",
											padding: "10px 0",
											borderRadius: 14,
											backgroundColor: `${COLORS.nvidia}18`,
											border: `2px solid ${COLORS.nvidia}44`,
										}}
									>
										{c.tag}
									</div>
									<div style={{ fontSize: 35, lineHeight: 1.55 }}>
										<Rich parts={c.body} />
									</div>
								</div>
							</Panel>
						</FadeUp>
					))}
				</div>
			</div>
		</SceneShell>
	);
};

/* ---------------- conclusion：结论 ---------------- */

export const ConclusionTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as ConclusionData;
	const frame = useCurrentFrame();
	const tagStart = Math.max(280, duration - 230);
	const taglineIn = interpolate(frame, [tagStart, tagStart + 40], [0, 1], {
		extrapolateLeft: "clamp",
		extrapolateRight: "clamp",
		easing: Easing.out(Easing.cubic),
	});
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 30 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", gap: 26 }}>
					{d.statements.map((s, i) => (
						<FadeUp key={s.who} delay={20 + i * 22}>
							<Panel accent={colorOf(s.color)}>
								<div style={{ fontSize: 36, lineHeight: 1.6 }}>
									<span style={{ color: colorOf(s.color), fontWeight: 800, marginRight: 22 }}>{s.who}</span>
									<Rich parts={s.body} />
								</div>
							</Panel>
						</FadeUp>
					))}
				</div>
				<div
					style={{
						textAlign: "center",
						opacity: taglineIn,
						transform: `scale(${0.92 + taglineIn * 0.08})`,
						paddingBottom: 20,
					}}
				>
					<div style={{ fontSize: 64, fontWeight: 800, lineHeight: 1.4 }}>
						<Rich parts={d.tagline} />
					</div>
					{d.sub ? (
						<div style={{ fontSize: 34, color: COLORS.sub, marginTop: 18 }}>
							<Rich parts={d.sub} />
						</div>
					) : null}
				</div>
			</div>
		</SceneShell>
	);
};

/* ---------------- enriched rows：概括+数字卡+标签分行+板块chips(早报视频) ---------------- */

export const EnrichedRowsTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as RowsData;
	const ent = d.entrances ?? {};
	const at = (k: string, i: number) => ent[k] ?? 2 + i * 3;
	const tags = d.tags ?? [];
	return (
		<SceneShell duration={duration} caption={caption}>
			<Backdrop />
			<div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 26 }}>
				<Kicker text={d.kicker ?? ""} delay={2} />
				<RichTitle parts={d.headline} delay={8} size={66} marginTop={14} />
				{d.summary ? (
					<FadeUp delay={at("summary", 0)}>
						<div style={{ fontSize: 36, lineHeight: 1.55, color: COLORS.text, textAlign: "left" }}>
							<Rich parts={d.summary} />
						</div>
					</FadeUp>
				) : null}
				{d.stat ? (
					<FadeUp delay={at("stat", 1)}>
						<div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
							<span style={{ fontSize: 96, fontWeight: 800, color: COLORS.nvidia, fontVariantNumeric: "tabular-nums" }}>
								{d.stat.value}
							</span>
							{d.stat.unit ? <span style={{ fontSize: 44, fontWeight: 700, color: COLORS.nvidia }}>{d.stat.unit}</span> : null}
							{d.stat.label ? <span style={{ fontSize: 26, color: COLORS.sub }}>{d.stat.label}</span> : null}
						</div>
					</FadeUp>
				) : null}
				<div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
					{d.rows.map((r, i) => (
						<FadeUp key={i} delay={at(`row${i}`, 2 + i)}>
							<div style={{ display: "flex", alignItems: "flex-start", gap: 18 }}>
								<span
									style={{
										fontSize: 28, fontWeight: 700, color: colorOf(r.accent),
										backgroundColor: `${colorOf(r.accent)}18`, borderRadius: 8,
										padding: "6px 16px", whiteSpace: "nowrap", marginTop: 4,
									}}
								>
									<Rich parts={r.label} />
								</span>
								<div style={{ fontSize: 32, lineHeight: 1.55, color: COLORS.text, textAlign: "left", flex: 1 }}>
									<Rich parts={r.body} />
								</div>
							</div>
						</FadeUp>
					))}
				</div>
				{tags.length ? (
					<FadeUp delay={at("tags", d.rows.length + 2)}>
						<div style={{ display: "flex", gap: 18, marginTop: "auto", paddingBottom: 8 }}>
							{tags.map((t) => (
								<Chip key={t} color={COLORS.sub} style={{ fontSize: 26, padding: "10px 22px" }}>{t}</Chip>
							))}
						</div>
					</FadeUp>
				) : null}
			</div>
		</SceneShell>
	);
};
