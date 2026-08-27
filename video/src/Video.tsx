// 视频装配层：读取 src/active-story.ts（由 scripts/build.mjs 生成）
// 场景时长由音频时长驱动，字幕与音轨按场景挂载
import React from "react";
import { Audio, Sequence, staticFile } from "remotion";
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
			{seqs.map(({ frame, from, index }) => {
				const Comp = TEMPLATES[frame.template];
				if (!Comp) {
					throw new Error(`未知模板: ${frame.template}（场景 ${frame.id}）`);
				}
				return (
					<Sequence key={frame.id} from={from} durationInFrames={frame.durationInFrames} name={frame.id}>
						{frame.audio ? <Audio src={staticFile(frame.audio)} /> : null}
						<Comp
							scene={ACTIVE.story.scenes[index]}
							duration={frame.durationInFrames}
							caption={frame.caption}
						/>
					</Sequence>
				);
			})}
		</>
	);
};
