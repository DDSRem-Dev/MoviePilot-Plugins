const STORAGE_KEY = 'p115strmhelper_v3_nav_jump';

let pendingJump = null;

/**
 * 在从 Page 切换到 Config 前写入深链定位目标
 * 同时写入内存与 sessionStorage，兼容宿主销毁重建组件树场景
 */
export function requestConfigJump(target) {
  if (!target || typeof target !== 'object') return;
  const payload = {
    category: target.category || 'category-basic',
    subTab: target.subTab || '',
    highlightId: target.highlightId || '',
    ts: Date.now(),
  };
  pendingJump = payload;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    /* ignore storage quota errors */
  }
}

/**
 * Config 挂载时消费一次跳转意图（15 秒内有效）
 */
export function consumeConfigJump() {
  let payload = pendingJump;
  pendingJump = null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      sessionStorage.removeItem(STORAGE_KEY);
      if (!payload) payload = JSON.parse(raw);
    }
  } catch {
    /* ignore */
  }
  if (!payload || Date.now() - (payload.ts || 0) > 15000) {
    return null;
  }
  return payload;
}
