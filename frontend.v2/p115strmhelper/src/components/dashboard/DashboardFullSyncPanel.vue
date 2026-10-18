<template>
  <div class="dashboard-widget dashboard-widget--full-sync-mini">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card full-sync-mini-card dashboard-grid-fill h-100 d-flex flex-column">
      <v-card-item v-if="config?.attrs?.title || config?.attrs?.subtitle" class="strm-dash-card__head pb-2">
        <v-card-title class="d-flex flex-wrap align-center gap-2 ps-0 text-subtitle-1">
          <v-icon icon="mdi-sync" color="primary" size="small" />
          {{ config?.attrs?.title || "全量同步" }}
        </v-card-title>
        <v-card-subtitle v-if="config?.attrs?.subtitle">{{ config.attrs.subtitle }}</v-card-subtitle>
        <template v-slot:append>
          <v-btn v-if="!allowRefresh" class="dashboard-grid-no-drag" icon size="small" variant="text" :loading="configLoading" @click="loadConfig">
            <v-icon>mdi-refresh</v-icon>
          </v-btn>
        </template>
      </v-card-item>

      <v-card-text class="pa-3 pt-0 full-sync-mini-card__body flex-grow-1 d-flex flex-column">
        <div v-if="configLoading && !configLoaded" class="text-center py-6">
          <v-progress-circular indeterminate color="primary" size="36" />
        </div>
        <template v-else-if="configLoaded">
          <v-alert v-if="!pluginEnabled" type="warning" variant="tonal" density="compact" class="mb-2">
            请先在插件设置中启用插件
          </v-alert>
          <v-alert v-else-if="!hasCookies" type="warning" variant="tonal" density="compact" class="mb-2">
            请先在插件设置中配置 115 Cookie
          </v-alert>
          <template v-else>
            <div class="d-flex flex-column gap-3 full-sync-mini-card__primary">
              <v-btn class="dashboard-grid-no-drag" block color="primary" variant="tonal" prepend-icon="mdi-sync" :disabled="!canTriggerFullSync"
                @click="fullSyncConfirmOpen = true">
                全量同步
              </v-btn>
              <v-btn class="dashboard-grid-no-drag" block color="primary" variant="outlined" prepend-icon="mdi-database-sync"
                :disabled="!canTriggerFullSyncDb" @click="fullSyncDbConfirmOpen = true">
                全量同步数据库
              </v-btn>
            </div>
            <div v-if="!canTriggerFullSync && canTriggerFullSyncDb" class="text-caption text-medium-emphasis mt-3">
              全量同步需先在配置中填写全量同步路径（每行一条且含 #）
            </div>

            <template v-if="showStrmCleanupPending">
              <div class="full-sync-mini-card__cleanup mt-4 rounded-lg pa-3">
                <div class="d-flex align-center justify-space-between gap-2 mb-2">
                  <div class="d-flex align-center gap-2 text-body-2 font-weight-medium min-w-0 text-high-emphasis">
                    <v-icon icon="mdi-delete-alert" color="primary" size="small" class="flex-shrink-0" />
                    <span class="text-truncate">待确认清理失效 STRM</span>
                  </div>
                  <v-btn size="small" variant="text" density="compact" class="flex-shrink-0 dashboard-grid-no-drag" prepend-icon="mdi-refresh"
                    :loading="pendingLoading" @click="loadPendingBatches">
                    刷新
                  </v-btn>
                </div>
                <div v-if="pendingLoading" class="text-center py-3">
                  <v-progress-circular indeterminate color="primary" size="24" />
                </div>
                <v-alert v-else-if="!pendingBatches.length" type="info" variant="tonal" density="compact"
                  class="text-caption mb-0">
                  暂无待确认批次；全量同步产生待删列表后将显示在此
                </v-alert>
                <div v-else class="d-flex flex-column gap-2">
                  <v-card v-for="b in pendingBatches" :key="b.request_id" variant="outlined" density="compact">
                    <v-card-text class="py-2 px-3">
                      <div class="text-caption font-weight-medium">批次 {{ b.request_id }}</div>
                      <div class="text-caption text-medium-emphasis">共 {{ b.path_count }} 个文件</div>
                      <div v-if="b.path_preview?.length" class="text-caption text-disabled text-truncate mt-1"
                        :title="formatPreview(b.path_preview)">
                        {{ formatPreview(b.path_preview) }}
                      </div>
                      <div class="d-flex gap-2 mt-2">
                        <v-btn class="dashboard-grid-no-drag" size="small" color="error" variant="tonal"
                          :loading="pendingAction === `${b.request_id}:exec`" :disabled="!!pendingAction"
                          @click="executePendingCleanup(b.request_id)">
                          确认删除
                        </v-btn>
                        <v-btn class="dashboard-grid-no-drag" size="small" variant="text" :loading="pendingAction === `${b.request_id}:cancel`"
                          :disabled="!!pendingAction" @click="cancelPendingCleanup(b.request_id)">
                          取消
                        </v-btn>
                      </div>
                    </v-card-text>
                  </v-card>
                </div>
              </div>
            </template>
          </template>
        </template>
      </v-card-text>

      <v-divider v-if="allowRefresh" />
      <v-card-actions v-if="allowRefresh" class="px-3 py-2 refresh-actions">
        <span class="text-caption text-disabled">{{ lastRefreshedDisplay }}</span>
        <v-spacer />
        <v-btn class="dashboard-grid-no-drag" icon variant="text" size="small" :loading="configLoading" @click="loadConfig">
          <v-icon size="small">mdi-refresh</v-icon>
        </v-btn>
      </v-card-actions>
    </v-card>

    <FullSyncConfirmDialog v-model="fullSyncConfirmOpen" :loading="syncLoading"
      :has-media-server-refresh="Boolean(fullSyncMediaServerRefresh)" @confirm="onConfirmFullSync" />

    <v-dialog v-model="fullSyncDbConfirmOpen" max-width="450" persistent>
      <v-card>
        <v-card-title class="text-h6 d-flex align-center">
          <v-icon icon="mdi-alert-circle-outline" color="primary" class="mr-2" />
          确认操作
        </v-card-title>
        <v-card-text>
          您确定要立即执行全量同步数据库吗？该操作会覆盖原有数据库数据
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn class="dashboard-grid-no-drag" color="grey" variant="text" :disabled="syncDbLoading" @click="fullSyncDbConfirmOpen = false">
            取消
          </v-btn>
          <v-btn class="dashboard-grid-no-drag" color="primary" variant="text" :loading="syncDbLoading" @click="onConfirmFullSyncDb">
            确认执行
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="3200">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from "vue";
import { P115_STRM_HELPER_PLUGIN_ID } from "../../utils/pluginId.js";
import FullSyncConfirmDialog from "../dialogs/FullSyncConfirmDialog.vue";

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
});

const configLoading = ref(false);
const configLoaded = ref(false);
const lastRefreshedAt = ref(null);

const pluginEnabled = ref(false);
const hasCookies = ref(false);
const fullSyncStrmPaths = ref("");
const fullSyncMediaServerRefresh = ref(false);
const fullSyncRemoveUnlessStrm = ref(false);
const fullSyncCleanupConfirmMode = ref("none");

const pendingBatches = ref([]);
const pendingLoading = ref(false);
const pendingAction = ref("");

const fullSyncConfirmOpen = ref(false);
const fullSyncDbConfirmOpen = ref(false);
const syncLoading = ref(false);
const syncDbLoading = ref(false);

const snackbar = reactive({ show: false, text: "", color: "success" });

function fullSyncPathsCount(raw) {
  if (!raw || typeof raw !== "string") return 0;
  try {
    return raw.split("\n").filter((line) => line.trim() && line.includes("#")).length;
  } catch {
    return 0;
  }
}

const canTriggerFullSyncDb = computed(
  () => pluginEnabled.value && hasCookies.value,
);

const canTriggerFullSync = computed(
  () => canTriggerFullSyncDb.value && fullSyncPathsCount(fullSyncStrmPaths.value) > 0,
);

const showStrmCleanupPending = computed(() => {
  const mode = String(fullSyncCleanupConfirmMode.value || "none")
    .trim()
    .toLowerCase()
    .replace(/-/g, "_");
  return (
    pluginEnabled.value &&
    hasCookies.value &&
    fullSyncRemoveUnlessStrm.value &&
    mode !== "none"
  );
});

const lastRefreshedDisplay = computed(() => {
  if (!lastRefreshedAt.value) return "";
  const date = new Date(lastRefreshedAt.value);
  return `更新于: ${date.getHours().toString().padStart(2, "0")}:${date
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}`;
});

async function loadConfig() {
  configLoading.value = true;
  try {
    const data = await props.api.get(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/get_config`);
    if (data) {
      pluginEnabled.value = Boolean(data.enabled);
      hasCookies.value = Boolean(data.cookies && String(data.cookies).trim() !== "");
      fullSyncStrmPaths.value = data.full_sync_strm_paths || "";
      fullSyncMediaServerRefresh.value = Boolean(data.full_sync_media_server_refresh_enabled);
      fullSyncRemoveUnlessStrm.value = Boolean(data.full_sync_remove_unless_strm);
      fullSyncCleanupConfirmMode.value = data.full_sync_cleanup_confirm_mode || "none";
    }
    configLoaded.value = true;
    lastRefreshedAt.value = Date.now();
    if (showStrmCleanupPending.value) {
      await loadPendingBatches();
    } else {
      pendingBatches.value = [];
    }
  } catch (err) {
    console.error("仪表盘获取配置失败:", err);
    configLoaded.value = true;
    snackbar.text = "获取配置失败";
    snackbar.color = "error";
    snackbar.show = true;
  } finally {
    configLoading.value = false;
  }
}

function showSnackbar(text, color = "success") {
  snackbar.text = text;
  snackbar.color = color;
  snackbar.show = true;
}

function formatPreview(paths) {
  if (!Array.isArray(paths) || !paths.length) return "";
  return paths.slice(0, 3).join(" · ");
}

async function loadPendingBatches() {
  if (!showStrmCleanupPending.value) {
    pendingBatches.value = [];
    return;
  }
  pendingLoading.value = true;
  try {
    const result = await props.api.get(
      `plugin/${P115_STRM_HELPER_PLUGIN_ID}/strm_cleanup_pending`,
    );
    if (result && result.code === 0 && result.data && Array.isArray(result.data.batches)) {
      pendingBatches.value = result.data.batches;
    } else {
      pendingBatches.value = [];
    }
  } catch (err) {
    console.error("获取待确认 STRM 清理失败:", err);
    pendingBatches.value = [];
  } finally {
    pendingLoading.value = false;
  }
}

async function executePendingCleanup(requestId) {
  if (!requestId) return;
  pendingAction.value = `${requestId}:exec`;
  try {
    const result = await props.api.post(
      `plugin/${P115_STRM_HELPER_PLUGIN_ID}/strm_cleanup_execute`,
      { request_id: requestId },
    );
    if (result && result.code === 0) {
      showSnackbar(result.msg || "已执行清理", "success");
      await loadPendingBatches();
    } else {
      showSnackbar(result?.msg || "执行失败", "error");
    }
  } catch (err) {
    console.error(err);
    showSnackbar(`执行失败: ${err.message || err}`, "error");
  } finally {
    pendingAction.value = "";
  }
}

async function cancelPendingCleanup(requestId) {
  if (!requestId) return;
  pendingAction.value = `${requestId}:cancel`;
  try {
    const result = await props.api.post(
      `plugin/${P115_STRM_HELPER_PLUGIN_ID}/strm_cleanup_cancel`,
      { request_id: requestId },
    );
    if (result && result.code === 0) {
      showSnackbar(result.msg || "已取消", "success");
      await loadPendingBatches();
    } else {
      showSnackbar(result?.msg || "取消失败", "error");
    }
  } catch (err) {
    console.error(err);
    showSnackbar(`取消失败: ${err.message || err}`, "error");
  } finally {
    pendingAction.value = "";
  }
}

async function onConfirmFullSync() {
  fullSyncConfirmOpen.value = false;
  if (!canTriggerFullSync.value) {
    showSnackbar("条件不满足，请检查插件状态与全量同步路径", "warning");
    return;
  }
  syncLoading.value = true;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/full_sync`);
    if (result && result.code === 0) {
      showSnackbar(result.msg || "全量同步任务已启动", "success");
      if (showStrmCleanupPending.value) {
        setTimeout(() => loadPendingBatches(), 4000);
      }
    } else {
      showSnackbar(result?.msg || "启动全量同步失败", "error");
    }
  } catch (err) {
    console.error(err);
    showSnackbar(`启动失败: ${err.message || err}`, "error");
  } finally {
    syncLoading.value = false;
  }
}

async function onConfirmFullSyncDb() {
  fullSyncDbConfirmOpen.value = false;
  if (!canTriggerFullSyncDb.value) {
    showSnackbar("请先启用插件并配置 Cookie", "warning");
    return;
  }
  syncDbLoading.value = true;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/full_sync_db`);
    if (result && result.code === 0) {
      showSnackbar(result.msg || "全量同步数据库任务已启动", "success");
    } else {
      showSnackbar(result?.msg || "启动失败", "error");
    }
  } catch (err) {
    console.error(err);
    showSnackbar(`启动失败: ${err.message || err}`, "error");
  } finally {
    syncDbLoading.value = false;
  }
}

onMounted(() => {
  loadConfig();
});
</script>

<style scoped>
/*
 * 待确认区：不用 bg-surface-variant（部分主题下会呈深灰/近黑，与主仪表盘浅色卡冲突）
 * 与 dashboard-panels 里 status-inner-card / 透明主题浅色块一致
 */
.full-sync-mini-card__cleanup {
  background: rgba(var(--v-theme-primary), 0.06);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  box-shadow: inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.04);
}

.v-theme--dark .full-sync-mini-card__cleanup,
[data-theme="dark"] .full-sync-mini-card__cleanup {
  background: rgba(var(--v-theme-on-surface), 0.06);
  border-color: rgba(var(--v-theme-on-surface), 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

html[data-theme="transparent"] .full-sync-mini-card__cleanup {
  background-color: rgba(var(--v-theme-surface), var(--transparent-opacity-light, 0.2)) !important;
  backdrop-filter: blur(var(--transparent-blur-light, 6px));
  -webkit-backdrop-filter: blur(var(--transparent-blur-light, 6px));
  border: 1px solid rgba(var(--v-theme-on-surface), 0.1) !important;
  box-shadow: inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.04);
}
</style>
