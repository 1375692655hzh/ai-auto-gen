/**
 * 脱敏包使用内存保存登录态，避免绑定原工程的数据库。
 * 生产接入时可将这两个函数替换为自己的加密凭证库实现。
 */
const accountStates = new Map();

export function setStorageState(accountId, storageState) {
  if (accountId == null || accountId === '') throw new TypeError('accountId 不能为空');
  if (!storageState || typeof storageState !== 'object') throw new TypeError('storageState 必须是对象');
  accountStates.set(String(accountId), structuredClone(storageState));
}

export function getStorageState(accountId) {
  const value = accountStates.get(String(accountId));
  return value ? structuredClone(value) : null;
}

export function refreshStorageState(accountId, storageState) {
  setStorageState(accountId, storageState);
}

export function clearStorageState(accountId) {
  accountStates.delete(String(accountId));
}
