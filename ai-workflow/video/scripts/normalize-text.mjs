// 校验器与对齐脚本必须共用本模块，禁止各写一份。

export const SPLIT_PUNCTS = "，。；：？！、,.;:?!";

const TRADITIONAL_TO_SIMPLIFIED = {
	產: "产", 經: "经", 濟: "济", 國: "国", 內: "内", 億: "亿", 萬: "万", 點: "点",
	漲: "涨", 發: "发", 後: "后", 裡: "里", 裏: "里", 為: "为", 爲: "为", 與: "与", 從: "从",
	會: "会", 來: "来", 時: "时", 間: "间", 報: "报", 導: "导", 體: "体", 場: "场",
	壓: "压", 觀: "观", 們: "们", 這: "这", 說: "说", 請: "请", 應: "应", 當: "当",
	處: "处", 機: "机", 構: "构", 銀: "银", 資: "资", 價: "价", 買: "买", 賣: "卖",
	開: "开", 關: "关", 門: "门", 問: "问", 條: "条", 級: "级", 長: "长", 雙: "双",
	對: "对", 灣: "湾", 陸: "陆", 豐: "丰", 廠: "厂", 廣: "广", 寶: "宝", 頭: "头",
	幣: "币", 圓: "圆", 東: "东", 業: "业", 個: "个", 數: "数", 據: "据", 額: "额",
	達: "达", 還: "还", 過: "过", 將: "将", 實: "实", 現: "现", 動: "动", 務: "务",
	總: "总", 類: "类", 線: "线", 網: "网", 電: "电", 專: "专", 張: "张", 風: "风",
	險: "险", 增: "增", 減: "减", 強: "强", 弱: "弱", 預: "预", 計: "计", 較: "较",
	轉: "转", 換: "换", 結: "结", 啟: "启", 閉: "闭", 錢: "钱", 續: "续",
};

const DIGITS = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
const SMALL_UNITS = { 十: 10, 百: 100, 千: 1000 };
const LARGE_UNITS = { 万: 10000, 亿: 100000000 };
const CHINESE_NUMBER_RE = /[零〇一二两三四五六七八九十百千万亿点]+/g;
const PERCENT_MARKER = "\ue001";

const parseChineseInteger = (text) => {
	let total = 0;
	let section = 0;
	let digit = 0;
	for (const char of text) {
		if (Object.hasOwn(DIGITS, char)) {
			digit = DIGITS[char];
		} else if (Object.hasOwn(SMALL_UNITS, char)) {
			section += (digit || 1) * SMALL_UNITS[char];
			digit = 0;
		} else if (Object.hasOwn(LARGE_UNITS, char)) {
			section += digit;
			total += section * LARGE_UNITS[char];
			section = 0;
			digit = 0;
		}
	}
	return total + section + digit;
};

const parseChineseNumber = (text) => {
	const [integer, decimal] = text.split("点");
	const integerValue = /[十百千万亿]/u.test(integer)
		? parseChineseInteger(integer)
		: [...integer].map((char) => DIGITS[char]).join("");
	if (decimal === undefined) return String(integerValue);
	const decimalValue = [...decimal].map((char) => DIGITS[char]).join("");
	return `${integerValue}.${decimalValue}`;
};

const foldFullWidth = (text) => [...text].map((char) => {
	const code = char.codePointAt(0);
	if (code >= 0xff01 && code <= 0xff5e) return String.fromCodePoint(code - 0xfee0);
	if (code === 0x3000) return " ";
	return char;
}).join("");

/** 百分比统一输出为“百分之”+阿拉伯数字；仅保留数字内部的小数点。 */
export function N(input) {
	let text = String(input ?? "");
	text = [...text].map((char) => TRADITIONAL_TO_SIMPLIFIED[char] ?? char).join("");
	text = foldFullWidth(text);
	text = text.replace(/百分之([零〇一二两三四五六七八九十百千万亿点]+)/g, (_, value) =>
		`${PERCENT_MARKER}${parseChineseNumber(value)}`);
	text = text.replace(/百分之(?=\d)/g, PERCENT_MARKER);
	text = text.replace(/(\d+(?:\.\d+)?)(万|亿)/g, (_, value, unit) =>
		String(Number(value) * LARGE_UNITS[unit]));
	text = text.replace(CHINESE_NUMBER_RE, (value) =>
		/[零〇一二两三四五六七八九]/u.test(value) || value.startsWith("十") ? parseChineseNumber(value) : value);
	text = text.replace(/(\d+(?:\.\d+)?)%/g, `${PERCENT_MARKER}$1`);
	text = text.replaceAll(PERCENT_MARKER, "百分之");
	text = text.replace(/(?<=\d)\.(?=\d)/g, "\ue000");
	text = text.replace(/[^\p{L}\p{N}\ue000]/gu, "");
	return text.replaceAll("\ue000", ".");
}

export const normalizeText = N;
export default normalizeText;
