// 视频装配层：读取 src/active-story.ts（由 scripts/build.mjs 生成）
// 场景时长由音频时长驱动，字幕与音轨按场景挂载
import React from "react";
import { AbsoluteFill, Audio, Freeze, Sequence, staticFile } from "remotion";
import { ACTIVE, ActiveFrame } from "./active-story";
import type { SceneProps } from "./story-types";
import { BarsTpl, CardsTpl, CompareTpl, EventTpl, TitleTpl } from "./templates-core";
import {
	ChecklistTpl,
	ConclusionTpl,
	RowsTpl,
	StackedTpl,
	VersusTpl,
} from "./templates-extra";
import { VPointsTpl, VStatTpl, VTitleTpl } from "./templates-vertical";
import { ClipTpl } from "./templates-media";
import PaperBoardTpl from "./templates-paper";
import { COLORS } from "./ui";

import {VoxFastCutTpl, HandDrawnTpl} from "./templates-follow";

const TEMPLATES: Record<string, React.FC<SceneProps>> = {
	title: TitleTpl,
	event: EventTpl,
	bars: BarsTpl,
	compare: CompareTpl,
	cards: CardsTpl,
	rows: RowsTpl,
	stacked: StackedTpl,
	versus: VersusTpl,
	checklist: ChecklistTpl,
	conclusion: ConclusionTpl,
	vtitle: VTitleTpl,
	vstat: VStatTpl,
	vpoints: VPointsTpl,
	"paper-board": PaperBoardTpl,
	clip: ClipTpl,
	"vox-fast-cut": VoxFastCutTpl,
	"hand-drawn": HandDrawnTpl,
};

const StageScaler: React.FC<{ children: React.ReactNode }> = ({ children }) => {
	const meta = ACTIVE.meta;
	// 仅 9:16 使用竖版设计基座；1:1 和 4:5 使用横版基座上下留边。
	const isVertical = meta.height > meta.width && meta.width * 16 === meta.height * 9;
	const baseW = isVertical ? 1080 : 1920;
	const baseH = isVertical ? 1920 : 1080;
	const s = Math.min(meta.width / baseW, meta.height / baseH);
	return (
		<AbsoluteFill style={{
			transform: `scale(${s})`,
			transformOrigin: "top left",
			left: (meta.width - baseW * s) / 2,
			top: (meta.height - baseH * s) / 2,
			width: baseW,
			height: baseH,
		}}>
			{children}
		</AbsoluteFill>
	);
};

export const Video: React.FC = () => {
	let acc = 0;
	const seqs: { frame: ActiveFrame; from: number; index: number }[] = ACTIVE.frames.map(
		(f, index) => {
			const from = acc;
			acc += f.durationInFrames;
			return { frame: f, from, index };
		},
	);
	return (
		<>
			<AbsoluteFill style={{ backgroundColor: COLORS.bgDeep }} />
			{seqs.map(({ frame, from, index }) => {
				const Comp = TEMPLATES[frame.template];
				if (!Comp) {
					throw new Error(`未知模板: ${frame.template}（场景 ${frame.id}）`);
				}
				return (
					<Sequence key={frame.id} from={from} durationInFrames={frame.durationInFrames} name={frame.id}>
						{frame.audio ? (
							<Sequence from={frame.leadFrames ?? 0}>
								<Audio src={staticFile(frame.audio)} />
							</Sequence>
						) : null}
						<StageScaler>
							<Freeze frame={(frame.visualDurationInFrames ?? frame.durationInFrames) - 1}
								active={(f) => f >= (frame.visualDurationInFrames ?? frame.durationInFrames)}>
							<Comp
								scene={ACTIVE.story.scenes[index]}
								duration={frame.durationInFrames}
								caption={frame.cues ?? frame.caption}
							/>
							</Freeze>
						</StageScaler>
					</Sequence>
				);
			})}
		</>
	);
};
