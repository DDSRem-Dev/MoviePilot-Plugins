<template>
  <div class="dashboard-widget dashboard-widget--status">
    <v-card
      :flat="!config?.attrs?.border"
      :loading="loading"
      class="status-dash-card dashboard-grid-fill fill-height d-flex flex-column"
    >
      <v-card-item v-if="config?.attrs?.title || config?.attrs?.subtitle" class="pb-2">
        <v-card-title>{{ config?.attrs?.title || "115网盘STRM助手" }}</v-card-title>
        <v-card-subtitle v-if="config?.attrs?.subtitle">{{ config.attrs.subtitle }}</v-card-subtitle>
      </v-card-item>

      <v-card-text class="flex-grow-1 pa-3 pt-0">
        <div v-if="loading && !initialDataLoaded" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="40" />
        </div>

        <div v-else-if="error" class="text-error text-body-2 d-flex align-center">
          <v-icon size="small" color="error" class="mr-1">mdi-alert-circle-outline</v-icon>
          {{ error }}
        </div>

        <v-row v-else-if="initialDataLoaded" class="status-dash-row" align="stretch">
          <v-col cols="12" md="6" class="d-flex flex-column mb-3 mb-md-0">
            <v-card class="status-inner-card w-100 d-flex flex-column flex-grow-1" variant="outlined">
              <v-card-item class="py-2">
                <v-card-title class="text-subtitle-1 d-flex align-center">
                  <v-icon icon="mdi-information" class="mr-2" size="small" />
                  系统状态
                </v-card-title>
              </v-card-item>
              <v-divider />
              <v-card-text class="pa-0 flex-grow-1">
                <v-list class="bg-transparent pa-0">
                  <v-list-item class="px-4 py-1" style="min-height: 40px">
                    <template v-slot:prepend>
                      <v-icon :color="status.enabled ? 'success' : 'grey'" icon="mdi-power" size="small" />
                    </template>
                    <v-list-item-title class="text-body-2">插件状态</v-list-item-title>
                    <template v-slot:append>
                      <v-chip :color="status.enabled ? 'success' : 'grey'" size="small" variant="tonal">
                        {{ status.enabled ? "已启用" : "已禁用" }}
                      </v-chip>
                    </template>
                  </v-list-item>
                  <v-divider class="my-0" />
                  <v-list-item class="px-4 py-1" style="min-height: 40px">
                    <template v-slot:prepend>
                      <v-icon
                        :color="status.has_client && initialConfig?.cookies ? 'success' : 'error'"
                        icon="mdi-account-check"
                        size="small"
                      />
                    </template>
                    <v-list-item-title class="text-body-2">115客户端状态</v-list-item-title>
                    <template v-slot:append>
                      <v-chip
                        :color="status.has_client && initialConfig?.cookies ? 'success' : 'error'"
                        size="small"
                        variant="tonal"
                      >
                        {{ status.has_client && initialConfig?.cookies ? "已连接" : "未连接" }}
                      </v-chip>
                    </template>
                  </v-list-item>
                  <v-divider class="my-0" />
                  <v-list-item class="px-4 py-1" style="min-height: 40px">
                    <template v-slot:prepend>
                      <v-icon :color="status.running ? 'warning' : 'success'" icon="mdi-play-circle" size="small" />
                    </template>
                    <v-list-item-title class="text-body-2">任务状态</v-list-item-title>
                    <template v-slot:append>
                      <v-chip :color="status.running ? 'warning' : 'success'" size="small" variant="tonal">
                        {{ status.running ? "运行中" : "空闲" }}
                      </v-chip>
                    </template>
                  </v-list-item>
                </v-list>
              </v-card-text>
            </v-card>
          </v-col>

          <v-col cols="12" md="6" class="d-flex flex-column">
            <v-card class="status-inner-card w-100 d-flex flex-column flex-grow-1" variant="outlined">
              <v-card-item class="py-2">
                <v-card-title class="text-subtitle-1 d-flex align-center">
                  <v-icon icon="mdi-account-box" class="mr-2" size="small" />
                  115账户信息
                </v-card-title>
              </v-card-item>
              <v-divider />
              <v-card-text class="pa-0 flex-grow-1">
                <v-skeleton-loader
                  v-if="userInfo.loading || storageInfo.loading"
                  type="list-item-avatar-three-line, list-item-three-line"
                />
                <div v-else>
                  <v-alert
                    v-if="userInfo.error || storageInfo.error"
                    type="warning"
                    variant="tonal"
                    density="comfortable"
                    class="ma-4"
                  >
                    {{ userInfo.error || storageInfo.error }}
                  </v-alert>
                  <v-list v-else class="bg-transparent pa-0">
                    <v-list-item class="px-4 py-2">
                      <template v-slot:prepend>
                        <v-avatar size="36" class="mr-2">
                          <v-img v-if="userInfo.avatar" :src="userInfo.avatar" :alt="userInfo.name" />
                          <v-icon v-else icon="mdi-account-circle" />
                        </v-avatar>
                      </template>
                      <v-list-item-title class="text-body-1 font-weight-medium">
                        {{ userInfo.name || "未知用户" }}
                      </v-list-item-title>
                    </v-list-item>
                    <v-divider class="my-0" />
                    <v-list-item class="px-4 py-2">
                      <template v-slot:prepend>
                        <v-icon
                          :color="userInfo.is_vip ? 'amber-darken-2' : 'grey'"
                          icon="mdi-shield-crown"
                          size="small"
                        />
                      </template>
                      <v-list-item-title class="text-body-2">VIP状态</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="userInfo.is_vip ? 'success' : 'grey'" size="small" variant="tonal">
                          {{
                            userInfo.is_vip
                              ? userInfo.is_forever_vip
                                ? "永久VIP"
                                : `VIP (至 ${userInfo.vip_expire_date || "N/A"})`
                              : "非VIP"
                          }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0" />
                    <v-list-item class="px-4 py-3">
                      <v-list-item-title class="text-body-2 mb-1">存储空间</v-list-item-title>
                      <v-list-item-subtitle v-if="storageInfo.used && storageInfo.total" class="text-caption">
                        已用 {{ storageInfo.used }} / 总共 {{ storageInfo.total }} (剩余 {{ storageInfo.remaining }})
                      </v-list-item-subtitle>
                      <v-progress-linear
                        v-if="storageInfo.used && storageInfo.total"
                        :model-value="calculateStoragePercentage(storageInfo.used, storageInfo.total)"
                        color="primary"
                        height="8"
                        rounded
                        class="mt-2"
                      />
                      <v-list-item-subtitle v-else class="text-caption text-medium-emphasis">
                        存储信息不可用
                      </v-list-item-subtitle>
                    </v-list-item>
                  </v-list>
                </div>
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>
      </v-card-text>

      <v-divider v-if="allowRefresh" />
      <v-card-actions v-if="allowRefresh" class="px-3 py-2 refresh-actions">
        <span class="text-caption text-disabled">{{ lastRefreshedTimeDisplay }}</span>
        <v-spacer />
        <v-btn class="dashboard-grid-no-drag" icon variant="text" size="small" @click="fetchStatusData" :loading="loading">
          <v-icon size="small">mdi-refresh</v-icon>
        </v-btn>
      </v-card-actions>
    </v-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from "vue";
import { P115_STRM_HELPER_PLUGIN_ID } from "../../utils/pluginId.js";

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
  if (!lastRefreshedTimestamp.value) return "";
  const date = new Date(lastRefreshedTimestamp.value);
  return `更新于: ${date.getHours().toString().padStart(2, "0")}:${date
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}`;
});

function calculateStoragePercentage(used, total) {
  if (!used || !total) return 0;
  const parseSize = (sizeStr) => {
    if (!sizeStr || typeof sizeStr !== "string") return 0;
    const value = parseFloat(sizeStr);
    if (Number.isNaN(value)) return 0;
    if (sizeStr.toUpperCase().includes("TB")) return value * 1024 * 1024;
    if (sizeStr.toUpperCase().includes("GB")) return value * 1024;
    if (sizeStr.toUpperCase().includes("MB")) return value;
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
      if (response.user_info) {
        Object.assign(userInfo, response.user_info);
      } else {
        userInfo.error = "未能获取有效的用户信息。";
      }
      if (response.storage_info) {
        Object.assign(storageInfo, response.storage_info);
      } else {
        storageInfo.error = "未能获取有效的存储空间信息。";
      }
    } else {
      const errMsg = response?.error_message || "获取用户和存储信息失败。";
      userInfo.error = errMsg;
      storageInfo.error = errMsg;
      if (errMsg.includes("Cookie") || errMsg.includes("未配置")) {
        status.has_client = false;
      }
    }
  } catch (err) {
    console.error("获取用户/存储状态失败:", err);
    const msg = `请求用户/存储状态时出错: ${err.message || "未知网络错误"}`;
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
        if (configData) {
          Object.assign(initialConfig, configData);
        }
      } catch (configErr) {
        console.error("获取配置失败:", configErr);
      }
      initialDataLoaded.value = true;
      if (status.has_client && initialConfig?.cookies) {
        await fetchUserStorageStatus();
      } else {
        userInfo.loading = false;
        storageInfo.loading = false;
        if (!initialConfig?.cookies) {
          userInfo.error = "请先配置115 Cookie。";
          storageInfo.error = "请先配置115 Cookie。";
        } else if (!status.has_client) {
          userInfo.error = "115客户端未连接或Cookie无效。";
          storageInfo.error = "115客户端未连接或Cookie无效。";
        }
      }
      lastRefreshedTimestamp.value = Date.now();
    } else {
      status.enabled = Boolean(initialConfig.enabled);
      status.has_client = Boolean(initialConfig.cookies && String(initialConfig.cookies).trim() !== "");
      status.running = false;
      initialDataLoaded.value = true;
      try {
        const configData = await props.api.get(`plugin/${pluginId}/get_config`);
        if (configData) {
          Object.assign(initialConfig, configData);
        }
      } catch (configErr) {
        console.error("获取配置失败:", configErr);
      }
      userInfo.loading = false;
      storageInfo.loading = false;
      throw new Error(result?.msg || "获取状态失败");
    }
  } catch (err) {
    error.value = `获取状态失败: ${err.message || "未知错误"}`;
    console.error("获取状态失败:", err);
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
