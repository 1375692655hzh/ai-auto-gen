const NON_REPEATABLE_REJECTION_PATTERN = /(?:审核[^，。；]*(?:未通过|不通过|拒绝)|未通过|被拒绝|驳回|不符合发文规定|与平台已有内容高度相似|内容高度相似|含有?广告信息|广告软文|营销软文|敏感词|不适宜发布|违规内容)/;

/** 只识别内容本身导致的持久失败；登录、额度、网络和平台暂时错误仍允许重试。 */
export function isNonRepeatableRejection(value) {
  return NON_REPEATABLE_REJECTION_PATTERN.test(String(value || '').replace(/\s+/g, ''));
}

/**
 * 后端对发布失败给出唯一、结构化的重试结论。前端只消费该结论，不再自行解析文案。
 */
export function classifyPublishRetry({ status = '', stage = '', healthStatus = '', detail = '' } = {}) {
  if (healthStatus === 'restricted') {
    return { retryDisposition: 'blocked', blockKind: 'restricted' };
  }
  if (
    healthStatus === 'rejected'
    || ((status === 'failed' || stage === 'rejected') && isNonRepeatableRejection(detail))
  ) {
    return { retryDisposition: 'blocked', blockKind: 'rejected' };
  }
  return { retryDisposition: 'allowed', blockKind: '' };
}

/** 返回会阻止同一文章继续投放到同平台的长期状态。 */
export function publicationPublishBlock(publication) {
  if (!publication?.platform) return null;
  const detail = [
    publication.platformDetail,
    publication.platformStatus,
    publication.rawStatus,
    publication.error,
  ].map(value => String(value || '').trim()).find(Boolean) || '';
  const policy = classifyPublishRetry({
    status: publication.status,
    healthStatus: publication.healthStatus,
    detail: [
      publication.platformStatus,
      publication.platformDetail,
      publication.rawStatus,
      publication.error,
    ].join(' '),
  });
  if (policy.blockKind === 'restricted') {
    return {
      kind: 'restricted',
      reason: detail || '该文章在此平台展示受限',
    };
  }
  if (policy.blockKind === 'rejected') {
    return {
      kind: 'rejected',
      reason: detail || '该文章未通过平台内容审核',
    };
  }
  return null;
}
