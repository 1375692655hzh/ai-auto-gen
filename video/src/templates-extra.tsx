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
import { Backdrop, colorOf, COLORS, FadeUp, Kicker, Panel, Rich, RichTitle, SceneShell } from "./ui";
import { ComparePanel } from "./templates-core";

/* ---------------- rows：证据行列表 ---------------- */

export const RowsTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as RowsData;
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
									<div style={{ fontSize: 34, textAlign: "right", lineHeight: 1.5 }}>
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
