export interface Cue {t: string; start: number; end: number}
export interface CaptionTimeline {
	cues: Cue[];
	method: string;
}
export function captionAt(caption: string | Cue[] | null | undefined, frame: number, duration: number, fps: number): string;
export function splitCaption(text: string, width?: number): string[];
export function captionTimeline(args: {
	text: string;
	duration: number;
	fps: number;
	lead?: number;
	alignment?: {unit: string; origin: string; segments: {t: string; start: number; end: number}[]};
	cues?: Cue[];
}): CaptionTimeline;
export function toSrt(frames: {cues?: Cue[]; durationInFrames: number}[], fps: number): string;
export function visualShots(cues: Cue[], duration: number, fps: number): {start: number; end: number; label: string}[];
