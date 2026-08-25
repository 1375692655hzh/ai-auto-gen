/**
 * 各平台的内容硬约束 —— 提交前预检、发布前门禁与前端提示共用这一份声明。
 *
 * 之前这些数字散在三处：头条标题范围在 adapters/toutiao/api.js，值得买的
 * 字数图片门槛写死在 adapters/zdm/index.js 的 console.warn 里，网易的要求
 * 只记在 README。分散的后果是前端无法在提交前预检，只能等任务跑到 adapter
 * 里才失败。集中到这里后三方读同一份数据。
 *
 * severity 决定发现问题后怎么处理：
 *   error   —— 平台必定拒绝，预检直接拦住，不创建任务；
 *   warning —— 平台会收下但很可能审核驳回，提示后允许用户坚持发布。
 */

/** 未声明约束的平台按这份默认值处理（即不做限制）。 */
const DEFAULT_CONSTRAINTS = Object.freeze({
  titleMin: null,
  titleMax: null,
  titleSeverity: 'error',
  minBodyChars: null,
  minImages: null,
  contentSeverity: 'warning',
  /** true 表示未明确上传封面时平台会拒绝提交。 */
  coverRequired: false,
  /** 先审后发的平台提交后拿不到即时链接，状态会停在「审核中」等补链。 */
  reviewBeforePublish: false,
});

export const PLATFORM_CONSTRAINTS = Object.freeze({
  sohu: {
    ...DEFAULT_CONSTRAINTS,
  },
  toutiao: {
    ...DEFAULT_CONSTRAINTS,
    // 平台编辑器硬校验，超限直接被接口拒绝，系统不做静默截断。
    titleMin: 2,
    titleMax: 30,
    titleSeverity: 'error',
  },
  wangyi: {
    ...DEFAULT_CONSTRAINTS,
    // 网易号标题要求 5~64 字，超出范围时平台会拒绝提交。
    titleMin: 5,
    titleMax: 64,
    titleSeverity: 'error',
    coverRequired: true,
  },
  zdm: {
    ...DEFAULT_CONSTRAINTS,
    // 运营规则按 30 字上限执行；即使接口偶尔接受更长标题，也不继续提交。
    titleMax: 30,
    titleSeverity: 'error',
    // 原创门槛：不达标平台仍会收下，但审核大概率驳回，所以是 warning 而非 error。
    minBodyChars: 800,
    minImages: 5,
    contentSeverity: 'warning',
    coverRequired: true,
    reviewBeforePublish: true,
  },
});

export function getPlatformConstraints(platformId) {
  return PLATFORM_CONSTRAINTS[String(platformId || '').trim()] || DEFAULT_CONSTRAINTS;
}

/** 按 Unicode 码点数标题长度：中文与 emoji 都按 1 字计，与平台口径一致。 */
export function titleLength(title) {
  return [...String(title == null ? '' : title).trim()].length;
}

function issue({ field, severity, code, message }) {
  return { field, severity, code, message };
}

/**
 * 标题预检。标题在上游内容源表里就有，不需要读正文文档，所以这项是零成本的，
 * 前端在分发弹窗里可以直接算。
 */
export function checkPlatformTitle(title, platformId, platformName = platformId) {
  const constraints = getPlatformConstraints(platformId);
  const length = titleLength(title);
  if (length === 0) {
    return issue({
      field: 'title',
      severity: 'error',
      code: 'TITLE_EMPTY',
      message: '文章标题为空，无法发布',
    });
  }
  const { titleMin, titleMax, titleSeverity } = constraints;
  if (titleMax != null && length > titleMax) {
    return issue({
      field: 'title',
      severity: titleSeverity,
      code: 'TITLE_TOO_LONG',
      message: `${platformName}标题最多 ${titleMax} 字，当前 ${length} 字`,
    });
  }
  if (titleMin != null && length < titleMin) {
    return issue({
      field: 'title',
      severity: titleSeverity,
      code: 'TITLE_TOO_SHORT',
      message: titleMax != null
        ? `${platformName}标题需 ${titleMin}~${titleMax} 字，当前 ${length} 字`
        : `${platformName}标题至少 ${titleMin} 字，当前 ${length} 字`,
    });
  }
  return null;
}

/**
 * 正文预检。字数与图片数要读上游内容源文档才知道，调用方拿不到时传 null 跳过，
 * 不要用 0 代替 —— 0 会被当成「真的没有图片」而误报。
 */
export function checkPlatformContent({ bodyChars, imageCount } = {}, platformId, platformName = platformId) {
  const { minBodyChars, minImages, contentSeverity } = getPlatformConstraints(platformId);
  const issues = [];
  if (minBodyChars != null && Number.isFinite(bodyChars) && bodyChars < minBodyChars) {
    issues.push(issue({
      field: 'body',
      severity: contentSeverity,
      code: 'BODY_TOO_SHORT',
      message: `${platformName}要求正文不少于 ${minBodyChars} 字，当前 ${bodyChars} 字`,
    }));
  }
  if (minImages != null && Number.isFinite(imageCount) && imageCount < minImages) {
    issues.push(issue({
      field: 'images',
      severity: contentSeverity,
      code: 'TOO_FEW_IMAGES',
      message: `${platformName}要求配图不少于 ${minImages} 张，当前 ${imageCount} 张`,
    }));
  }
  return issues;
}

/**
 * 封面预检。调用方不知道封面状态时传 null/undefined 跳过；明确传 false 时，
 * 对声明为封面必填的平台返回阻断问题。
 */
export function checkPlatformCover(coverAvailable, platformId, platformName = platformId) {
  const { coverRequired } = getPlatformConstraints(platformId);
  if (!coverRequired || coverAvailable == null || coverAvailable) return null;
  return issue({
    field: 'cover',
    severity: 'error',
    code: 'COVER_REQUIRED',
    message: `${platformName}要求必须填写封面`,
  });
}

/** 标题 + 正文的完整预检；正文指标缺失时只检标题。 */
export function checkArticleForPlatform(article = {}, platformId, platformName = platformId) {
  const issues = [];
  const titleIssue = checkPlatformTitle(article.title, platformId, platformName);
  if (titleIssue) issues.push(titleIssue);
  issues.push(...checkPlatformContent(article, platformId, platformName));
  const coverIssue = checkPlatformCover(article.coverAvailable, platformId, platformName);
  if (coverIssue) issues.push(coverIssue);
  return issues;
}

export function hasBlockingIssue(issues) {
  return (Array.isArray(issues) ? issues : []).some(item => item?.severity === 'error');
}

/** 供 listPlatforms() 下发给前端；只暴露前端预检真正会用到的字段。 */
export function publicPlatformConstraints(platformId) {
  const {
    titleMin, titleMax, minBodyChars, minImages, coverRequired, reviewBeforePublish,
  } = getPlatformConstraints(platformId);
  return { titleMin, titleMax, minBodyChars, minImages, coverRequired, reviewBeforePublish };
}
