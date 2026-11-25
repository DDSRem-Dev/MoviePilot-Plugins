<template>
  <div class="dashboard-widget dashboard-widget--status">
    <v-card
      :flat="!config?.attrs?.border"
      :loading="loading"
      class="status-dash-card dashboard-grid-fill"
    >
      <!-- Unified Apple Widget Header -->
      <div v-if="config?.attrs?.title || config?.attrs?.subtitle" class="p115-dash-header">
        <div class="p115-dash-header-left">
          <div class="p115-dash-icon">
            <v-icon icon="mdi-cloud-check-outline" size="18" />
          </div>
          <div class="p115-dash-titles">
            <div class="p115-dash-title-row">
              <span>{{ config?.attrs?.title || "运行状态与 115 账户" }}</span>
              <span
                v-if="initialDataLoaded"
                class="p115-badge"
                :class="status.enabled ? 'p115-badge--green' : 'p115-badge--neutral'"
              >
                <span class="p115-badge-dot" />
                {{ status.enabled ? "运行正常" : "插件未启用" }}
              </span>
            </div>
            <div v-if="config?.attrs?.subtitle" class="p115-dash-subtitle">
              {{ config.attrs.subtitle }}
            </div>
          </div>
        </div>

        <div v-if="!allowRefresh" class="p115-dash-header-right">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--icon dashboard-grid-no-drag"
            :disabled="loading"
            title="刷新状态"
            @click="fetchStatusData"
          >
            <v-progress-circular v-if="loading" indeterminate size="13" width="2" />
            <v-icon v-else size="16" icon="mdi-refresh" />
          </button>
        </div>
      </div>

      <!-- Widget Body -->
      <div class="p115-dash-body p115-dash-body--auto">
        <div v-if="loading && !initialDataLoaded" class="d-flex align-center justify-center flex-grow-1" style="min-height: 196px">
          <v-progress-circular indeterminate color="primary" size="34" />
        </div>

        <div v-else-if="error" class="p115-callout p115-callout--error">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ error }}</span>
        </div>

        <v-row v-else-if="initialDataLoaded" dense align="stretch" class="flex-grow-0">
          <!-- Left: System Status -->
          <v-col cols="12" md="5" class="d-flex mb-2 mb-md-0">
            <div class="p115-dash-subcard">
              <div class="p115-dash-subcard-head">
                <div class="d-flex align-center gap-2">
                  <v-icon icon="mdi-pulse" color="primary" size="16" />
                  <span>系统状态</span>
                </div>
              </div>
              <div class="p115-inset-list flex-grow-1 justify-center">
                <div class="p115-inset-row">
                  <div class="d-flex align-center gap-2">
                    <v-icon :color="status.enabled ? 'success' : 'grey'" icon="mdi-power" size="17" />
                    <span class="text-body-2">插件状态</span>
                  </div>
                  <span class="p115-badge" :class="status.enabled ? 'p115-badge--green' : 'p115-badge--neutral'">
                    <span class="p115-badge-dot" />
                    {{ status.enabled ? "已启用" : "已禁用" }}
                  </span>
                </div>

                <div class="p115-inset-row">
                  <div class="d-flex align-center gap-2">
                    <v-icon
                      :color="status.has_client && initialConfig?.cookies ? 'success' : 'error'"
                      icon="mdi-account-check-outline"
                      size="17"
                    />
                    <span class="text-body-2">115客户端状态</span>
                  </div>
                  <span
                    class="p115-badge"
                    :class="status.has_client && initialConfig?.cookies ? 'p115-badge--blue' : 'p115-badge--red'"
                  >
                    <span class="p115-badge-dot" />
                    {{ status.has_client && initialConfig?.cookies ? "已连接" : "未连接" }}
                  </span>
                </div>

                <div class="p115-inset-row">
                  <div class="d-flex align-center gap-2">
                    <v-icon :color="status.running ? 'warning' : 'success'" icon="mdi-play-circle-outline" size="17" />
                    <span class="text-body-2">任务状态</span>
                  </div>
                  <span class="p115-badge" :class="status.running ? 'p115-badge--amber' : 'p115-badge--green'">
                    <span class="p115-badge-dot" />
                    {{ status.running ? "运行中" : "空闲" }}
                  </span>
                </div>
              </div>
            </div>
          </v-col>

          <!-- Right: 115 Account & Cloud Storage -->
          <v-col cols="12" md="7" class="d-flex">
            <div class="p115-dash-subcard">
              <div class="p115-dash-subcard-head">
                <div class="d-flex align-center gap-2">
                  <v-icon icon="mdi-account-circle-outline" color="primary" size="16" />
                  <span>115账户信息</span>
                </div>
                <span
                  v-if="!userInfo.loading && !userInfo.error && userInfo.is_vip !== null"
                  class="p115-badge"
                  :class="userInfo.is_vip ? 'p115-badge--pink' : 'p115-badge--neutral'"
                >
                  <v-icon size="12" icon="mdi-crown" />
                  {{
                    userInfo.is_vip
                      ? userInfo.is_forever_vip
                        ? "永久VIP"
                        : `VIP (至 ${userInfo.vip_expire_date || "N/A"})`
                      : "非VIP"
                  }}
                </span>
              </div>

              <div class="pa-4 flex-grow-1 d-flex flex-column justify-space-between gap-3">
                <v-skeleton-loader
                  v-if="userInfo.loading || storageInfo.loading"
                  type="list-item-avatar-two-line, list-item-two-line"
                  class="bg-transparent"
                />
                <div v-else-if="userInfo.error || storageInfo.error" class="p115-callout p115-callout--warn">
                  <v-icon size="16" color="warning" icon="mdi-alert-outline" />
                  <span>{{ userInfo.error || storageInfo.error }}</span>
                </div>
                <template v-else>
                  <div class="d-flex align-center gap-3">
                    <div
                      style="
                        padding: 2px;
                        border-radius: 50%;
                        background: linear-gradient(135deg, #5bcffa 0%, #f5abb9 100%);
                        display: inline-flex;
                      "
                    >
                      <v-avatar size="44">
                        <v-img v-if="userInfo.avatar" :src="userInfo.avatar" :alt="userInfo.name" />
                        <v-icon v-else icon="mdi-account-circle" size="34" color="primary" />
                      </v-avatar>
                    </div>
                    <div class="min-w-0">
                      <div class="text-subtitle-1 font-weight-bold text-truncate" style="line-height: 1.25">
                        {{ userInfo.name || "未知用户" }}
                      </div>
                      <div class="text-caption opacity-70 mt-1">
                        {{
                          userInfo.is_vip
                            ? userInfo.is_forever_vip
                              ? "尊享永久 VIP 云端存储特权"
                              : `VIP 有效期至 ${userInfo.vip_expire_date || "N/A"}`
                            : "115 网盘在线账户"
                        }}
                      </div>
                    </div>
                  </div>

                  <div>
                    <div class="d-flex align-baseline justify-space-between flex-wrap gap-2 mb-2">
                      <span class="text-caption font-weight-bold">
                        存储空间
                        <span v-if="storageInfo.used && storageInfo.total" class="opacity-70 p115-tabular ml-1">
                          ({{ calculateStoragePercentage(storageInfo.used, storageInfo.total).toFixed(1) }}%)
                        </span>
                      </span>
                      <span v-if="storageInfo.used && storageInfo.total" class="text-caption p115-tabular">
                        已用 <strong>{{ storageInfo.used }}</strong> / {{ storageInfo.total }}
                        <span class="opacity-70">(剩余 {{ storageInfo.remaining }})</span>
                      </span>
                      <span v-else class="text-caption opacity-60">存储信息不可用</span>
                    </div>
                    <div v-if="storageInfo.used && storageInfo.total" class="p115-progress-track">
                      <div
                        class="p115-progress-fill"
                        :style="{ width: `${calculateStoragePercentage(storageInfo.used, storageInfo.total)}%` }"
                      />
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </v-col>
        </v-row>
      </div>

      <!-- Refresh Footer -->
      <div v-if="allowRefresh" class="p115-dash-footer">
        <span class="text-caption opacity-65 p115-tabular">{{ lastRefreshedTimeDisplay }}</span>
        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon dashboard-grid-no-drag"
          :disabled="loading"
          title="刷新状态"
          @click="fetchStatusData"
        >
          <v-progress-circular v-if="loading" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-refresh" />
        </button>
      </div>
    </v-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import { P115_STRM_HELPER_PLUGIN_ID } from '../../utils/pluginId.js';

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true,
  },
  config: {
    type: Object,
    default: () => ({ attrs: {} }),
  },
  allowRefresh: {
    type: Boolean,
    default: false,
  },
  refreshInterval: {
    type: Number,
    default: 0,
  },
});

const loading = ref(false);
const error = ref(null);
const initialDataLoaded = ref(false);
const lastRefreshedTimestamp = ref(null);

const status = reactive({
  enabled: false,
  has_client: false,
  running: false,
});

const initialConfig = reactive({});

const userInfo = reactive({
  name: null,
  is_vip: null,
  is_forever_vip: null,
  vip_expire_date: null,
  avatar: null,
  error: null,
  loading: true,
});

const storageInfo = reactive({
  total: null,
  used: null,
  remaining: null,
  error: null,
  loading: true,
});

let refreshTimer = null;

const lastRefreshedTimeDisplay = computed(() => {
  if (!lastRefreshedTimestamp.value) return '';
  const date = new Date(lastRefreshedTimestamp.value);
  return `更新于: ${date.getHours().toString().padStart(2, '0')}:${date
    .getMinutes()
    .toString()
    .padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
});

function calculateStoragePercentage(used, total) {
  if (!used || !total) return 0;
  const parseSize = (sizeStr) => {
    if (!sizeStr || typeof sizeStr !== 'string') return 0;
    const value = parseFloat(sizeStr);
    if (Number.isNaN(value)) return 0;
    if (sizeStr.toUpperCase().includes('TB')) return value * 1024 * 1024;
    if (sizeStr.toUpperCase().includes('GB')) return value * 1024;
    if (sizeStr.toUpperCase().includes('MB')) return value;
    return value;
  };
  const usedValue = parseSize(used);
  const totalValue = parseSize(total);
  if (totalValue === 0) return 0;
  return Math.min(Math.max((usedValue / totalValue) * 100, 0), 100);
}

async function fetchUserStorageStatus() {
  userInfo.loading = true;
  userInfo.error = null;
  storageInfo.loading = true;
  storageInfo.error = null;
  try {
    const response = await props.api.get(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/user_storage_status`);
    if (response && response.success) {
      if (response.user_info) Object.assign(userInfo, response.user_info);
      else userInfo.error = '未能获取有效的用户信息。';
      if (response.storage_info) Object.assign(storageInfo, response.storage_info);
      else storageInfo.error = '未能获取有效的存储空间信息。';
    } else {
      const errMsg = response?.error_message || '获取用户和存储信息失败。';
      userInfo.error = errMsg;
      storageInfo.error = errMsg;
      if (errMsg.includes('Cookie') || errMsg.includes('未配置')) {
        status.has_client = false;
      }
    }
  } catch (err) {
    const msg = `请求用户/存储状态时出错: ${err.message || '未知网络错误'}`;
    userInfo.error = msg;
    storageInfo.error = msg;
  } finally {
    userInfo.loading = false;
    storageInfo.loading = false;
  }
}

async function fetchStatusData() {
  loading.value = true;
  error.value = null;
  try {
    const pluginId = P115_STRM_HELPER_PLUGIN_ID;
    const result = await props.api.get(`plugin/${pluginId}/get_status`);
    if (result && result.code === 0 && result.data) {
      status.enabled = Boolean(result.data.enabled);
      status.has_client = Boolean(result.data.has_client);
      status.running = Boolean(result.data.running);
      try {
        const configData = await props.api.get(`plugin/${pluginId}/get_config`);
        if (configData) Object.assign(initialConfig, configData);
      } catch (configErr) {
        console.error('获取配置失败:', configErr);
      }
      initialDataLoaded.value = true;
      if (status.has_client && initialConfig?.cookies) {
        await fetchUserStorageStatus();
      } else {
        userInfo.loading = false;
        storageInfo.loading = false;
        if (!initialConfig?.cookies) {
          userInfo.error = '请先配置115 Cookie。';
          storageInfo.error = '请先配置115 Cookie。';
        } else if (!status.has_client) {
          userInfo.error = '115客户端未连接或Cookie无效。';
          storageInfo.error = '115客户端未连接或Cookie无效。';
        }
      }
      lastRefreshedTimestamp.value = Date.now();
    } else {
      status.enabled = Boolean(initialConfig.enabled);
      status.has_client = Boolean(initialConfig.cookies && String(initialConfig.cookies).trim() !== '');
      status.running = false;
      initialDataLoaded.value = true;
      try {
        const configData = await props.api.get(`plugin/${pluginId}/get_config`);
        if (configData) Object.assign(initialConfig, configData);
      } catch (configErr) {
        console.error('获取配置失败:', configErr);
      }
      userInfo.loading = false;
      storageInfo.loading = false;
      throw new Error(result?.msg || '获取状态失败');
    }
  } catch (err) {
    error.value = `获取状态失败: ${err.message || '未知错误'}`;
    initialDataLoaded.value = true;
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  fetchStatusData();
  if (props.refreshInterval > 0) {
    refreshTimer = setInterval(fetchStatusData, props.refreshInterval * 1000);
  }
});

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
});
</script>
