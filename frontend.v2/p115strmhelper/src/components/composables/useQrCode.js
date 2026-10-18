import { reactive, watch, onBeforeUnmount } from 'vue';

/**
 * 二维码登录 Composable
 * 管理 115网盘 和 阿里云盘 的扫码登录逻辑
 * @param {object|Function} api - MoviePilot API 对象
 * @param {object} config - 插件配置的 reactive 对象
 * @param {object} message - 消息提示的 reactive 对象
 * @param {string} PLUGIN_ID - 插件ID
 */
export function useQrCode(api, config, message, PLUGIN_ID) {
  // 二维码客户端类型选项
  const clientTypes = [
    { label: "支付宝", value: "alipaymini" },
    { label: "微信", value: "wechatmini" },
    { label: "安卓", value: "115android" },
    { label: "iOS", value: "115ios" },
    { label: "网页", value: "web" },
    { label: "PAD", value: "115ipad" },
    { label: "TV", value: "tv" }
  ];

  // 115网盘二维码登录对话框状态
  const qrDialog = reactive({
    show: false,
    loading: false,
    error: null,
    qrcode: '',
    uid: '',
    time: "",
    sign: "",
    tips: '请使用支付宝扫描二维码登录',
    status: '等待扫码',
    checkIntervalId: null,
    clientType: 'alipaymini'
  });

  // 阿里云盘二维码登录对话框状态
  const aliQrDialog = reactive({
    show: false,
    loading: false,
    error: null,
    qrcode: '',
    t: '',
    ck: '',
    status: '等待扫码',
    checkIntervalId: null,
  });

  // ============================================================
  // 115网盘二维码
  // ============================================================

  const clearQrCodeCheckInterval = () => {
    if (qrDialog.checkIntervalId) {
      clearInterval(qrDialog.checkIntervalId);
      qrDialog.checkIntervalId = null;
    }
  };

  const checkQrCodeStatus = async () => {
    if (!qrDialog.uid || !qrDialog.show || !qrDialog.time || !qrDialog.sign) return;
    try {
      const params = new URLSearchParams({
        uid: qrDialog.uid,
        time: qrDialog.time,
        sign: qrDialog.sign,
        client_type: qrDialog.clientType,
      });
      const response = await api.get(
        `plugin/${PLUGIN_ID}/check_qrcode?${params.toString()}`
      );
      if (response && response.code === 0 && response.data) {
        const data = response.data;
        if (data.status === 'waiting') qrDialog.status = '等待扫码';
        else if (data.status === 'scanned') qrDialog.status = '已扫码，请在设备上确认';
        else if (data.status === 'success') {
          if (data.cookie) {
            clearQrCodeCheckInterval();
            qrDialog.status = '登录成功！';
            config.cookies = data.cookie;
            message.text = '登录成功！Cookie已获取，请点击下方"保存配置"按钮保存。';
            message.type = 'success';
            setTimeout(() => { qrDialog.show = false; }, 3000);
          } else {
            qrDialog.status = '登录似乎成功，但未获取到Cookie';
            message.text = '登录成功但未获取到Cookie信息，请重试或检查账号。';
            message.type = 'warning';
            clearQrCodeCheckInterval();
          }
        }
      } else if (response) {
        if (qrDialog.status !== '登录成功，正在处理...') {
          clearQrCodeCheckInterval();
          qrDialog.error = response.msg || '二维码已失效，请刷新';
          qrDialog.status = '二维码已失效';
        }
      }
    } catch (err) {
      if (qrDialog.status !== '登录成功，正在处理...') console.error('检查二维码状态JS捕获异常:', err);
    }
  };

  const startQrCodeCheckInterval = () => {
    clearQrCodeCheckInterval();
    qrDialog.checkIntervalId = setInterval(checkQrCodeStatus, 3000);
  };

  const getQrCode = async () => {
    qrDialog.loading = true;
    qrDialog.error = null;
    qrDialog.qrcode = '';
    qrDialog.uid = '';
    qrDialog.time = '';
    qrDialog.sign = '';
    console.warn(`【115STRM助手 DEBUG】准备获取二维码，前端选择的 clientType: ${qrDialog.clientType}`);
    try {
      const params = new URLSearchParams({ client_type: qrDialog.clientType });
      const response = await api.get(
        `plugin/${PLUGIN_ID}/get_qrcode?${params.toString()}`
      );
      if (response && response.code === 0 && response.data) {
        qrDialog.uid = response.data.uid;
        qrDialog.time = response.data.time;
        qrDialog.sign = response.data.sign;
        qrDialog.qrcode = response.data.qrcode;
        qrDialog.tips = response.data.tips || '请扫描二维码登录';
        qrDialog.status = '等待扫码';
        if (response.data.client_type) qrDialog.clientType = response.data.client_type;
        startQrCodeCheckInterval();
      } else {
        qrDialog.error = response?.msg || '获取二维码失败';
        console.error("【115STRM助手 DEBUG】获取二维码API调用失败或返回错误码: ", response);
      }
    } catch (err) {
      qrDialog.error = `获取二维码出错: ${err.message || '未知错误'}`;
      console.error('【115STRM助手 DEBUG】获取二维码 JS 捕获异常:', err);
    } finally {
      qrDialog.loading = false;
    }
  };

  const refreshQrCode = () => {
    clearQrCodeCheckInterval();
    qrDialog.error = null;
    const matchedType = clientTypes.find(type => type.value === qrDialog.clientType);
    qrDialog.tips = matchedType ? `请使用${matchedType.label}扫描二维码登录` : '请扫描二维码登录';
    getQrCode();
  };

  const openQrCodeDialog = () => {
    qrDialog.show = true;
    qrDialog.loading = false;
    qrDialog.error = null;
    qrDialog.qrcode = '';
    qrDialog.uid = '';
    qrDialog.time = '';
    qrDialog.sign = '';
    if (!clientTypes.some(ct => ct.value === qrDialog.clientType)) qrDialog.clientType = 'alipaymini';
    const selectedClient = clientTypes.find(type => type.value === qrDialog.clientType);
    qrDialog.tips = selectedClient ? `请使用${selectedClient.label}扫描二维码登录` : '请使用支付宝扫描二维码登录';
    qrDialog.status = '等待扫码';
    getQrCode();
  };

  const closeQrDialog = () => {
    clearQrCodeCheckInterval();
    qrDialog.show = false;
  };

  // 切换客户端类型时刷新二维码
  watch(() => qrDialog.clientType, (newVal, oldVal) => {
    if (newVal !== oldVal && qrDialog.show) {
      console.log(`【115STRM助手 DEBUG】qrDialog.clientType 从 ${oldVal} 变为 ${newVal}，准备刷新二维码`);
      refreshQrCode();
    }
  });

  // ============================================================
  // 阿里云盘二维码
  // ============================================================

  const clearAliQrCodeCheckInterval = () => {
    if (aliQrDialog.checkIntervalId) {
      clearInterval(aliQrDialog.checkIntervalId);
      aliQrDialog.checkIntervalId = null;
    }
  };

  const checkAliQrCodeStatus = async () => {
    if (!aliQrDialog.t || !aliQrDialog.ck || !aliQrDialog.show) return;
    try {
      const response = await api.get(`plugin/${PLUGIN_ID}/check_aliyundrive_qrcode?t=${aliQrDialog.t}&ck=${encodeURIComponent(aliQrDialog.ck)}`);
      if (response && response.code === 0 && response.data) {
        if (response.data.status === 'success' && response.data.token) {
          clearAliQrCodeCheckInterval();
          aliQrDialog.status = '登录成功！';
          config.aliyundrive_token = response.data.token;
          message.text = '阿里云盘登录成功！Token已获取，请点击下方"保存配置"按钮。';
          message.type = 'success';
          setTimeout(() => { aliQrDialog.show = false; }, 2000);
        } else {
          aliQrDialog.status = response.data.msg || '等待扫码';
          if (response.data.status === 'expired' || response.data.status === 'invalid') {
            clearAliQrCodeCheckInterval();
            aliQrDialog.error = '二维码已失效，请刷新';
          }
        }
      } else if (response) {
        clearAliQrCodeCheckInterval();
        aliQrDialog.status = '二维码已失效';
        aliQrDialog.error = response.msg || '二维码检查失败，请刷新。';
      }
    } catch (err) {
      console.error('检查阿里云盘二维码状态出错:', err);
    }
  };

  const startAliQrCodeCheckInterval = () => {
    clearAliQrCodeCheckInterval();
    aliQrDialog.checkIntervalId = setInterval(checkAliQrCodeStatus, 2000);
  };

  const getAliQrCode = async () => {
    aliQrDialog.loading = true;
    aliQrDialog.error = null;
    aliQrDialog.qrcode = '';
    try {
      const response = await api.get(`plugin/${PLUGIN_ID}/get_aliyundrive_qrcode`);
      if (response && response.code === 0 && response.data) {
        aliQrDialog.qrcode = response.data.qrcode;
        aliQrDialog.t = response.data.t;
        aliQrDialog.ck = response.data.ck;
        aliQrDialog.status = '等待扫码';
        startAliQrCodeCheckInterval();
      } else {
        aliQrDialog.error = response?.msg || '获取阿里云盘二维码失败';
      }
    } catch (err) {
      aliQrDialog.error = `获取二维码出错: ${err.message || '未知错误'}`;
    } finally {
      aliQrDialog.loading = false;
    }
  };

  const refreshAliQrCode = () => {
    clearAliQrCodeCheckInterval();
    aliQrDialog.error = null;
    getAliQrCode();
  };

  const openAliQrCodeDialog = () => {
    aliQrDialog.show = true;
    aliQrDialog.loading = false;
    aliQrDialog.error = null;
    aliQrDialog.qrcode = '';
    aliQrDialog.t = '';
    aliQrDialog.ck = '';
    aliQrDialog.status = '等待扫码';
    getAliQrCode();
  };

  const closeAliQrCodeDialog = () => {
    clearAliQrCodeCheckInterval();
    aliQrDialog.show = false;
  };

  // 组件卸载时清理定时器
  onBeforeUnmount(() => {
    clearQrCodeCheckInterval();
    clearAliQrCodeCheckInterval();
  });

  return {
    qrDialog,
    aliQrDialog,
    clientTypes,
    openQrCodeDialog,
    refreshQrCode,
    closeQrDialog,
    clearQrCodeCheckInterval,
    openAliQrCodeDialog,
    refreshAliQrCode,
    closeAliQrCodeDialog,
    clearAliQrCodeCheckInterval,
  };
}
