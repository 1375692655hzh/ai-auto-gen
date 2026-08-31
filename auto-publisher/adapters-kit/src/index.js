export { getAdapter, listPlatforms } from './adapters/registry.js';
export {
  BaseAdapter, NeedLoginError, PublishRejectedError, PublishResultUnknownError, ConfirmCancelledError,
} from './adapters/base.js';
export { setStorageState, getStorageState, refreshStorageState, clearStorageState } from './runtime/storage.js';
export { withAccountContext, withHeadlessAccountContext, closeAll } from './browser/manager.js';
export { checkArticleForPlatform, hasBlockingIssue } from './domain/platformConstraints.js';
