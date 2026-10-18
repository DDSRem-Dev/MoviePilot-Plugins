import { onMounted, onUnmounted, reactive } from 'vue';

const HDHIVE_ORIGIN = 'https://re0.me';
const OAUTH_TIMEOUT_MS = 120000;
const POPUP_FEATURES = 'width=520,height=720';

/**
 * HDHive OAuth（postMessage 单路径）
 * @param {object} api - MoviePilot API
 * @param {object} message - 全局消息 reactive
 * @param {string} pluginId - 插件 ID
 */
export function useHdhiveOAuth(api, message, pluginId) {
  const oauth = reactive({
    loading: false,
    pending: false,
    status: null,
    redirectUri: '',
    expectedState: '',
  });

  let popup = null;
  let timeoutId = null;

  const clearOAuthTimer = () => {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  };

  const closePopup = () => {
    if (popup && !popup.closed) {
      try {
        popup.close();
      } catch {
        /* ignore */
      }
    }
    popup = null;
  };

  const parseMessagePayload = (raw) => {
    if (!raw) return null;
    let data = raw;
    if (typeof data === 'string') {
      try {
        data = JSON.parse(data);
      } catch {
        try {
          const u = new URL(data);
          const code = u.searchParams.get('code');
          const state = u.searchParams.get('state');
          if (code && state) return { code, state };
        } catch {
          return null;
        }
        return null;
      }
    }

    // 常见结构：{code,state} / {authorization_code,state} / {data:{code,state}} / {response:{code,state}}
    const pick = (obj) => {
      if (!obj) return null;
      const code = obj.code || obj.authorization_code;
      const state = obj.state;
      if (code && state) return { code, state };
      return null;
    };

    const direct = pick(data);
    if (direct) return direct;
    const nested = pick(data.data) || pick(data.response) || pick(data.payload);
    if (nested) return nested;

    return null;
  };

  const fetchStatus = async () => {
    try {
      const resp = await api.get(`plugin/${pluginId}/hdhive/oauth/status`);
      if (resp?.code === 0) {
        oauth.status = resp.data || null;
      }
    } catch (e) {
      console.warn('HDHive OAuth status failed', e);
    }
  };

  const completeOAuth = async ({ code, state }) => {
    if (!oauth.redirectUri) {
      message.text = '缺少 redirect_uri，请重新发起授权';
      message.type = 'error';
      return;
    }
    if (oauth.expectedState && state !== oauth.expectedState) {
      message.text = 'OAuth state 校验失败，请重试';
      message.type = 'error';
      return;
    }
    oauth.loading = true;
    try {
      const resp = await api.post(`plugin/${pluginId}/hdhive/oauth/complete`, {
        code,
        state,
        redirect_uri: oauth.redirectUri,
      });
      if (resp?.code === 0) {
        message.text = resp.msg || 'HDHive 授权成功';
        message.type = 'success';
        await fetchStatus();
      } else {
        message.text = resp?.msg || 'HDHive 授权失败';
        message.type = 'error';
      }
    } catch (e) {
      message.text = `HDHive 授权失败: ${e.message}`;
      message.type = 'error';
    } finally {
      oauth.loading = false;
      oauth.pending = false;
      clearOAuthTimer();
      closePopup();
    }
  };

  const onOAuthMessage = (event) => {
    // RE0 的 postmessage 可能来自 re0.me，也可能来自 redirect_uri 所在域名（broker callback 页）
    const redirectOrigin = oauth.redirectUri ? new URL(oauth.redirectUri).origin : '';
    if (event.origin !== HDHIVE_ORIGIN && event.origin !== redirectOrigin) return;
    if (!oauth.pending) return;
    const parsed = parseMessagePayload(event.data);
    if (!parsed) return;
    completeOAuth(parsed);
  };

  const startOAuth = async () => {
    if (oauth.pending) return;
    oauth.loading = true;
    try {
      const resp = await api.get(`plugin/${pluginId}/hdhive/oauth/start`);
      if (resp?.code !== 0 || !resp.data?.authorize_url) {
        message.text = resp?.msg || '无法获取授权地址';
        message.type = 'error';
        return;
      }
      oauth.redirectUri = resp.data.redirect_uri || '';
      oauth.expectedState = resp.data.state || '';
      popup = window.open(resp.data.authorize_url, 'hdhive_oauth', POPUP_FEATURES);
      if (!popup || popup.closed) {
        message.text = '无法打开授权窗口，请允许浏览器弹窗后重试';
        message.type = 'warning';
        return;
      }
      oauth.pending = true;
      message.text = '请在弹出窗口中完成 HDHive 授权…';
      message.type = 'info';
      clearOAuthTimer();
      timeoutId = setTimeout(() => {
        if (oauth.pending) {
          oauth.pending = false;
          closePopup();
          message.text = '授权超时，请重试';
          message.type = 'warning';
        }
      }, OAUTH_TIMEOUT_MS);
    } catch (e) {
      message.text = `启动授权失败: ${e.message}`;
      message.type = 'error';
    } finally {
      oauth.loading = false;
    }
  };

  const revokeOAuth = async () => {
    oauth.loading = true;
    try {
      const resp = await api.post(`plugin/${pluginId}/hdhive/oauth/revoke`, {});
      if (resp?.code === 0) {
        message.text = resp.msg || '已解除 OAuth';
        message.type = 'success';
        await fetchStatus();
      } else {
        message.text = resp?.msg || '解除授权失败';
        message.type = 'error';
      }
    } catch (e) {
      message.text = `解除授权失败: ${e.message}`;
      message.type = 'error';
    } finally {
      oauth.loading = false;
    }
  };

  onMounted(() => {
    window.addEventListener('message', onOAuthMessage);
    fetchStatus();
  });

  onUnmounted(() => {
    window.removeEventListener('message', onOAuthMessage);
    clearOAuthTimer();
    closePopup();
  });

  const authModeLabel = () => {
    const mode = oauth.status?.auth_mode;
    if (mode === 'oauth') return '已 OAuth 授权';
    return '未授权';
  };

  return {
    oauth,
    startOAuth,
    revokeOAuth,
    fetchStatus,
    authModeLabel,
  };
}
