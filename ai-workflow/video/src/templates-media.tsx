// 外部视频/图片 B-roll 场景
import React from "react";
import {
	AbsoluteFill,
	Img,
	interpolate,
	OffthreadVideo,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from "remotion";
import type { ColorKey, Rich as RichParts, SceneProps } from "./story-types";
import { COLORS, colorOf, FadeUp, Kicker, Panel, Rich, RichTitle, SceneShell } from "./ui";

type Rich = RichParts;

export interface ClipData {
	/** 素材路径，相对项目目录，如 materials/xxx.mp4（由构建管线从 input/materials 规范化而来） */
	src: string;
	/** 素材类型，缺省按扩展名推断 */
	kind?: "video" | "image";
	/** 图片运镜（视频素材忽略）：in=推近 out=拉远 left/right=横摇 none=静止 */
	kenburns?: "in" | "out" | "left" | "right" | "none";
	/** 压暗遮罩：bottom=底部渐变（默认） full=整体压暗 none=无遮罩 */
	scrim?: "bottom" | "full" | "none";
	/** 视频截取起点（秒），缺省从头播 */
	trimFrom?: number;
	/** 视频截取终点（秒），缺省播到场景结束 */
	trimTo?: number;
	/** 素材内起始秒，缺省回退 trimFrom，再缺省从头播 */
	start?: number;
	/** 素材内结束秒，缺省回退 trimTo，再缺省播到场景结束 */
	end?: number;
	/** 中心放大倍数，范围 1-3，缺省 1（不放大） */
	zoom?: number;
	kicker?: string;
	kickerColor?: ColorKey;
	headline?: Rich;
	/** 左下角要点列表（可选） */
	points?: Rich[];
	/** 来源角标（建议填写，版权习惯） */
	credit?: string;
}

const VIDEO_EXT = /\.(mp4|mov|webm|mkv|avi|m4v)$/i;

/* ---------------- clip：外部素材 B-roll ---------------- */

/** 图片运镜变换（视频素材自带运动，不叠加） */
const kenBurns = (
	kind: NonNullable<ClipData["kenburns"]>,
	frame: number,
	duration: number,
): string => {
	const t = interpolate(frame, [0, duration], [0, 1]);
	switch (kind) {
		case "in":
			return `scale(${1 + t * 0.12})`;
		case "out":
			return `scale(${1.12 - t * 0.12})`;
		case "left":
			return `scale(1.12) translateX(${(1 - t * 2) * 40}px)`;
		case "right":
			return `scale(1.12) translateX(${(t * 2 - 1) * 40}px)`;
		default:
			return "none";
	}
};

export const ClipTpl: React.FC<SceneProps> = ({ scene, duration, caption }) => {
	const d = scene.data as unknown as ClipData;
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	const isVideo = (d.kind ?? (VIDEO_EXT.test(d.src) ? "video" : "image")) === "video";
	const scrim = d.scrim ?? "bottom";
	const videoStart = d.start ?? d.trimFrom;
	const videoEnd = d.end ?? d.trimTo;
	const zoom = d.zoom ?? 1;
	return (
		<SceneShell duration={duration} caption={caption} padding={0}>
			<AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
				{isVideo ? (
					<OffthreadVideo
						src={staticFile(d.src)}
						muted
						startFrom={Math.round((videoStart ?? 0) * fps)}
						endAt={videoEnd !== undefined ? Math.round(videoEnd * fps) : undefined}
						style={{
							width: "100%",
							height: "100%",
							objectFit: "cover",
							transform: zoom !== 1 ? `scale(${zoom})` : undefined,
							transformOrigin: "center",
						}}
					/>
				) : (
					<Img
						src={staticFile(d.src)}
						style={{
							width: "100%",
							height: "100%",
							objectFit: "cover",
							transform: `${zoom !== 1 ? `scale(${zoom}) ` : ""}${kenBurns(d.kenburns ?? "in", frame, duration)}`,
						}}
					/>
				)}
				{scrim === "bottom" ? (
					<>
						<AbsoluteFill
							style={{
								background:
									"linear-gradient(to top, rgba(4,6,12,0.88) 0%, rgba(4,6,12,0.35) 38%, transparent 65%)",
							}}
						/>
						<AbsoluteFill
							style={{
								background:
									"linear-gradient(to bottom, rgba(4,6,12,0.55) 0%, transparent 30%)",
							}}
						/>
					</>
				) : scrim === "full" ? (
					<AbsoluteFill style={{ backgroundColor: "rgba(4,6,12,0.55)" }} />
				) : null}
			</AbsoluteFill>
			{d.kicker || d.headline ? (
				<div style={{ position: "absolute", left: 90, top: 84, right: 400 }}>
					{d.kicker ? <Kicker text={d.kicker} color={colorOf(d.kickerColor)} delay={4} /> : null}
					{d.headline ? <RichTitle parts={d.headline} delay={10} size={60} marginTop={20} /> : null}
				</div>
			) : null}
			{d.points?.length ? (
				<div style={{ position: "absolute", left: 90, bottom: caption ? 220 : 90, maxWidth: 900 }}>
					<Panel accent={colorOf(d.kickerColor ?? "nvidia")} style={{ padding: "26px 34px" }}>
						{d.points.map((p, i) => (
							<FadeUp key={i} delay={30 + i * 16} y={14}>
								<div style={{ fontSize: 33, lineHeight: 1.55, marginTop: i === 0 ? 0 : 10 }}>
									<Rich parts={p} />
								</div>
							</FadeUp>
						))}
					</Panel>
				</div>
			) : null}
			{d.credit ? (
				<div
					style={{
						position: "absolute",
						right: 40,
						bottom: caption ? 176 : 30,
						fontSize: 22,
						color: COLORS.sub,
						backgroundColor: "rgba(7,11,22,0.7)",
						borderRadius: 10,
						padding: "6px 14px",
					}}
				>
					{d.credit}
				</div>
			) : null}
		</SceneShell>
	);
};

