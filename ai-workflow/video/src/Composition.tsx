import { Composition } from "remotion";
import { ACTIVE } from "./active-story";
import { Video } from "./Video";
import { CoverMaker } from "./Cover";
import type { CoverSpec } from "./Cover";

export const MyComposition = () => {
	return (
		<>
			<Composition
				id="Story"
				component={Video}
				durationInFrames={ACTIVE.totalFrames}
				fps={ACTIVE.meta.fps}
				width={ACTIVE.meta.width}
				height={ACTIVE.meta.height}
			/>
			<Composition
				id="CoverMaker"
				component={CoverMaker}
				durationInFrames={1}
				fps={30}
				width={1920}
				height={1080}
				defaultProps={{} as CoverSpec}
				calculateMetadata={({ props }) => {
					const spec = (props ?? {}) as CoverSpec;
					return {
						width: Number(spec.width) > 0 ? Number(spec.width) : 1920,
						height: Number(spec.height) > 0 ? Number(spec.height) : 1080,
						durationInFrames: 1,
					};
				}}
			/>
		</>
	);
};
