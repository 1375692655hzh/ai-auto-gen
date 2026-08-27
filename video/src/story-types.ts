// story.json 的数据结构定义：一篇文章 = 一份 story.json，与版式代码解耦

/** 颜色关键字（映射到引擎主题色板） */
export type ColorKey =
	| "text"
	| "sub"
	| "nvidia"
	| "red"
	| "green"
	| "amber"
	| "blue"
	| "purple";

/** 富文本片段：t=文字 c=颜色 b=加粗 br=换行 */
export interface Segment {
	t?: string;
	c?: ColorKey;
	b?: boolean;
	br?: boolean;
}
export type Rich = Segment[];

/** 数字滚动块 */
export interface StatSpec {
	prefix?: string;
	value: number;
	decimals?: number;
	suffix?: string;
	label?: Rich;
}

/** 对比面板（compare 模板的左右栏） */
export interface PanelSpec {
	accent?: ColorKey;
	grow?: number;
	title?: Rich;
	sub?: Rich;
	items?: Rich[];
	chips?: string[];
	chipColor?: ColorKey;
	stat?: StatSpec;
	lines?: Rich[];
	footer?: Rich;
}

/* ---- 各模板的 data 结构 ---- */

export interface TitleData {
	kicker?: string;
	kickerColor?: ColorKey;
	titlePre?: string;
	ticker?: number;
	tickerDecimals?: number;
	titlePost?: string;
	subtitle1?: Rich;
	subtitle2?: Rich;
}

export interface EventData {
	kicker?: string;
	headline: Rich;
	chips?: string[];
	chipColor?: ColorKey;
	stat?: StatSpec;
	panel?: PanelSpec;
	quote?: { accent?: ColorKey; source?: string; text: Rich };
}

export interface BarsData {
	kicker?: string;
	kickerColor?: ColorKey;
	headline: Rich;
	bars: { name: string; pct: number; tag?: string }[];
	footnote?: Rich;
}

export interface CompareData {
	kicker?: string;
	headline: Rich;
	left: PanelSpec;
	right: PanelSpec;
	arrow?: boolean;
	bottom?: { accent?: ColorKey; body: Rich };
}

export interface CardsData {
	kicker?: string;
	headline: Rich;
	cards: { icon?: string; title: string }[];
	question?: Rich;
}

export interface RowsData {
	kicker?: string;
	headline: Rich;
	rows: { accent?: ColorKey; label: Rich; body: Rich }[];
	footnote?: Rich;
}

export interface StackedData {
	kicker?: string;
	kickerColor?: ColorKey;
	headline: Rich;
	headlineSize?: number;
	transform?: { from: Rich; to: Rich };
	panels: { accent?: ColorKey; title: Rich; body: Rich }[];
	footnote?: Rich;
}

export interface VersusData {
	kicker?: string;
	headline: Rich;
	bull: PanelSpec;
	bear: PanelSpec;
	footnote?: Rich;
}

export interface ChecklistData {
	kicker?: string;
	headline: Rich;
	items: { tag: string; body: Rich }[];
}

export interface ConclusionData {
	kicker?: string;
	statements: { who: string; color?: ColorKey; body: Rich }[];
	tagline: Rich;
	sub?: Rich;
}

/** 单个场景：模板名 + 旁白（TTS 文本）+ 字幕 + 版式数据 */
export interface StoryScene {
	id: string;
	template: string;
	narration: string;
	caption?: string;
	data: Record<string, unknown>;
}

/** TTS 引擎配置（缺省 = edge + meta.voice） */
export interface TtsConfig {
	provider: "edge" | "dashscope";
	/** dashscope 音色：longanlufeng（男）/ longanlingxin（女）；edge 音色用 meta.voice */
	voice?: string;
}

export interface StoryMeta {
	title: string;
	voice: string;
	tts?: TtsConfig;
	fps: number;
	width: number;
	height: number;
	padSeconds?: number;
}

export interface Story {
	meta: StoryMeta;
	scenes: StoryScene[];
}

/** 所有场景模板组件的统一 props */
export interface SceneProps {
	scene: StoryScene;
	duration: number;
	caption: string;
}
