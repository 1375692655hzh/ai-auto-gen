import { Composition } from "remotion";
import { ACTIVE } from "./active-story";
import { Video } from "./Video";

export const MyComposition = () => {
	return (
		<Composition
			id="Story"
			component={Video}
			durationInFrames={ACTIVE.totalFrames}
			fps={ACTIVE.meta.fps}
			width={ACTIVE.meta.width}
			height={ACTIVE.meta.height}
		/>
	);
};
