<template>
  <div class="dashboard-widget dashboard-widget--full-sync-mini">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card dashboard-grid-fill">
      <!-- Unified Apple Widget Header -->
      <div v-if="config?.attrs?.title || config?.attrs?.subtitle" class="p115-dash-header">
        <div class="p115-dash-header-left">
          <div class="p115-dash-icon">
            <v-icon icon="mdi-sync" size="18" />
          </div>
          <div class="p115-dash-titles">
            <div class="p115-dash-title-row">
              <span>{{ config?.attrs?.title || "全量同步" }}</span>
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
            :disabled="configLoading"
            title="刷新配置"
            @click="loadConfig"
          >
            <v-progress-circular v-if="configLoading" indeterminate size="13" width="2" />
            <v-icon v-else size="16" icon="mdi-refresh" />
          </button>
        </div>
      </div>

      <!-- Widget Body -->
      <div class="p115-dash-body p115-dash-body--auto justify-center">
        <div v-if="configLoading && !configLoaded" class="text-center py-4">
          <v-progress-circular indeterminate color="primary" size="30" />
        </div>
        <template v-else-if="configLoaded">
          <div v-if="!pluginEnabled" class="p115-callout p115-callout--warn">
            <v-icon size="16" color="warning" icon="mdi-alert-outline" />
            <span>请先在插件设置中启用插件</span>
          </div>
          <div v-else-if="!hasCookies" class="p115-callout p115-callout--warn">
            <v-icon size="16" color="warning" icon="mdi-key-alert-outline" />
            <span>请先在插件设置中配置 115 Cookie</span>
          </div>
          <template v-else>
            <div class="d-flex flex-column gap-2">
              <button
                type="button"
                class="p115-btn p115-btn--primary w-100 dashboard-grid-no-drag"
                :disabled="!canTriggerFullSync"
                @click="fullSyncConfirmOpen = true"
              >
                <v-icon size="16" icon="mdi-sync" />
                <span>全量同步</span>
              </button>
              <button
                type="button"
                class="p115-btn p115-btn--tonal w-100 dashboard-grid-no-drag"
                :disabled="!canTriggerFullSyncDb"
                @click="fullSyncDbConfirmOpen = true"
              >
                <v-icon size="16" icon="mdi-database-sync-outline" />
                <span>全量同步数据库</span>
              </button>
            </div>
            <div v-if="!canTriggerFullSync && canTriggerFullSyncDb" class="text-caption opacity-70 mt-2">
              全量同步需先在配置中填写全量同步路径（每行一条且含 #）
            </div>

            <template v-if="showStrmCleanupPending">
              <div class="p115-dash-row-card mt-3">
                <div class="d-flex align-center justify-space-between gap-2 mb-2">
                  <div class="d-flex align-center gap-2 text-body-2 font-weight-bold min-w-0">
                    <v-icon icon="mdi-delete-alert-outline" color="warning" size="17" class="flex-shrink-0" />
                    <span class="text-truncate">待确认清理失效 STRM</span>
                  </div>
                  <button
                    type="button"
                    class="p115-btn p115-btn--ghost p115-btn--sm dashboard-grid-no-drag flex-shrink-0"
                    :disabled="pendingLoading"
                    @click="loadPendingBatches"
                  >
                    <v-icon size="14" icon="mdi-refresh" />
                    <span>刷新</span>
                  </button>
                </div>

                <div v-if="pendingLoading" class="text-center py-3">
                  <v-progress-circular indeterminate color="primary" size="22" />
                </div>
                <div v-else-if="!pendingBatches.length" class="text-caption opacity-75">
                  暂无待确认批次；全量同步产生待删列表后将显示在此
                </div>
                <div v-else class="d-flex flex-column gap-2">
                  <div
                    v-for="b in pendingBatches"
                    :key="b.request_id"
                    class="p115-dash-row-card"
                    style="background: var(--p115-bg-card)"
                  >
                    <div class="text-caption font-weight-bold p115-mono">批次 {{ b.request_id }}</div>
                    <div class="text-caption opacity-75 p115-tabular">共 {{ b.path_count }} 个文件</div>
                    <div
                      v-if="b.path_preview?.length"
                      class="text-caption opacity-65 text-truncate mt-1 p115-mono"
                      :title="formatPreview(b.path_preview)"
                    >
                      {{ formatPreview(b.path_preview) }}
                    </div>
                    <div class="d-flex gap-2 mt-2">
                      <button
                        type="button"
                        class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
                        :disabled="!!pendingAction"
                        @click="executePendingCleanup(b.request_id)"
                      >
                        确认删除
                      </button>
                      <button
                        type="button"
                        class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
                        :disabled="!!pendingAction"
                        @click="cancelPendingCleanup(b.request_id)"
                      >
                        取消
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </template>
        </template>
      </div>

      <!-- Refresh Footer -->
      <div v-if="allowRefresh" class="p115-dash-footer">
        <span class="text-caption opacity-65 p115-tabular">{{ lastRefreshedDisplay }}</span>
        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon dashboard-grid-no-drag"
          :disabled="configLoading"
          title="刷新配置"
          @click="loadConfig"
        >
          <v-progress-circular v-if="configLoading" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-refresh" />
        </button>
      </div>
    </v-card>

    <FullSyncConfirmDialog
      v-model="fullSyncConfirmOpen"
      :loading="syncLoading"
      :has-media-server-refresh="Boolean(fullSyncMediaServerRefresh)"
      @confirm="onConfirmFullSync"
    />

    <v-dialog v-model="fullSyncDbConfirmOpen" max-width="450" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="primary" icon="mdi-database-sync-outline" />
            <span>确认全量同步数据库</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          您确定要立即执行全量同步数据库吗？该操作会覆盖原有数据库数据。
        </div>
        <div class="p115-sheet-footer justify-end">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
            :disabled="syncDbLoading"
            @click="fullSyncDbConfirmOpen = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--primary p115-btn--sm dashboard-grid-no-drag"
            :disabled="syncDbLoading"
            @click="onConfirmFullSyncDb"
          >
            <v-progress-circular v-if="syncDbLoading" indeterminate size="13" width="2" />
            <span>确认执行</span>
          </button>
        </div>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" timeout="3200">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue';
import { P115_STRM_HELPER_PLUGIN_ID } from '../../utils/pluginId.js';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';
import FullSyncConfirmDialog from '../dialogs/FullSyncConfirmDialog.vue';

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

const { dialogContentClass } = useThemeAdapter();

const configLoading = ref(false);
const configLoaded = ref(false);
const lastRefreshedAt = ref(null);

const pluginEnabled = ref(false);
const hasCookies = ref(false);
const fullSyncStrmPaths = ref('');
const fullSyncMediaServerRefresh = ref(false);
const fullSyncRemoveUnlessStrm = ref(false);
const fullSyncCleanupConfirmMode = ref('none');

const pendingBatches = ref([]);
const pendingLoading = ref(false);
const pendingAction = ref('');

const fullSyncConfirmOpen = ref(false);
const fullSyncDbConfirmOpen = ref(false);
const syncLoading = ref(false);
const syncDbLoading = ref(false);

const snackbar = reactive({ show: false, text: '', color: 'success' });

function fullSyncPathsCount(raw) {
  if (!raw || typeof raw !== 'string') return 0;
  try {
    return raw.split('\n').filter((line) => line.trim() && line.includes('#')).length;
  } catch {
    return 0;
  }
}

const canTriggerFullSyncDb = computed(() => pluginEnabled.value && hasCookies.value);

const canTriggerFullSync = computed(
  () => canTriggerFullSyncDb.value && fullSyncPathsCount(fullSyncStrmPaths.value) > 0,
);

const showStrmCleanupPending = computed(() => {
  const mode = String(fullSyncCleanupConfirmMode.value || 'none')
    .trim()
    .toLowerCase()
    .replace(/-/g, '_');
  return pluginEnabled.value && hasCookies.value && fullSyncRemoveUnlessStrm.value && mode !== 'none';
});

const lastRefreshedDisplay = computed(() => {
  if (!lastRefreshedAt.value) return '';
  const date = new Date(lastRefreshedAt.value);
  return `更新于: ${date.getHours().toString().padStart(2, '0')}:${date
    .getMinutes()
    .toString()
    .padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
});

async function loadConfig() {
  configLoading.value = true;
  try {
    const data = await props.api.get(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/get_config`);
    if (data) {
      pluginEnabled.value = Boolean(data.enabled);
      hasCookies.value = Boolean(data.cookies && String(data.cookies).trim() !== '');
      fullSyncStrmPaths.value = data.full_sync_strm_paths || '';
      fullSyncMediaServerRefresh.value = Boolean(data.full_sync_media_server_refresh_enabled);
      fullSyncRemoveUnlessStrm.value = Boolean(data.full_sync_remove_unless_strm);
      fullSyncCleanupConfirmMode.value = data.full_sync_cleanup_confirm_mode || 'none';
    }
    configLoaded.value = true;
    lastRefreshedAt.value = Date.now();
    if (showStrmCleanupPending.value) {
      await loadPendingBatches();
    } else {
      pendingBatches.value = [];
    }
  } catch {
    configLoaded.value = true;
    snackbar.text = '获取配置失败';
    snackbar.color = 'error';
    snackbar.show = true;
  } finally {
    configLoading.value = false;
  }
}

function showSnackbar(text, color = 'success') {
  snackbar.text = text;
  snackbar.color = color;
  snackbar.show = true;
}

function formatPreview(paths) {
  if (!Array.isArray(paths) || !paths.length) return '';
  return paths.slice(0, 3).join(' · ');
}

async function loadPendingBatches() {
  if (!showStrmCleanupPending.value) {
    pendingBatches.value = [];
    return;
  }
  pendingLoading.value = true;
  try {
    const result = await props.api.get(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/strm_cleanup_pending`);
    if (result && result.code === 0 && result.data && Array.isArray(result.data.batches)) {
      pendingBatches.value = result.data.batches;
    } else {
      pendingBatches.value = [];
    }
  } catch {
    pendingBatches.value = [];
  } finally {
    pendingLoading.value = false;
  }
}

async function executePendingCleanup(requestId) {
  if (!requestId) return;
  pendingAction.value = `${requestId}:exec`;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/strm_cleanup_execute`, {
      request_id: requestId,
    });
    if (result && result.code === 0) {
      showSnackbar(result.msg || '已执行清理', 'success');
      await loadPendingBatches();
    } else {
      showSnackbar(result?.msg || '执行失败', 'error');
    }
  } catch (err) {
    showSnackbar(`执行失败: ${err.message || err}`, 'error');
  } finally {
    pendingAction.value = '';
  }
}

async function cancelPendingCleanup(requestId) {
  if (!requestId) return;
  pendingAction.value = `${requestId}:cancel`;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/strm_cleanup_cancel`, {
      request_id: requestId,
    });
    if (result && result.code === 0) {
      showSnackbar(result.msg || '已取消', 'success');
      await loadPendingBatches();
    } else {
      showSnackbar(result?.msg || '取消失败', 'error');
    }
  } catch (err) {
    showSnackbar(`取消失败: ${err.message || err}`, 'error');
  } finally {
    pendingAction.value = '';
  }
}

async function onConfirmFullSync() {
  fullSyncConfirmOpen.value = false;
  if (!canTriggerFullSync.value) {
    showSnackbar('条件不满足，请检查插件状态与全量同步路径', 'warning');
    return;
  }
  syncLoading.value = true;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/full_sync`);
    if (result && result.code === 0) {
      showSnackbar(result.msg || '全量同步任务已启动', 'success');
      if (showStrmCleanupPending.value) {
        setTimeout(() => loadPendingBatches(), 4000);
      }
    } else {
      showSnackbar(result?.msg || '启动全量同步失败', 'error');
    }
  } catch (err) {
    showSnackbar(`启动失败: ${err.message || err}`, 'error');
  } finally {
    syncLoading.value = false;
  }
}

async function onConfirmFullSyncDb() {
  fullSyncDbConfirmOpen.value = false;
  if (!canTriggerFullSyncDb.value) {
    showSnackbar('请先启用插件并配置 Cookie', 'warning');
    return;
  }
  syncDbLoading.value = true;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/full_sync_db`);
    if (result && result.code === 0) {
      showSnackbar(result.msg || '全量同步数据库任务已启动', 'success');
    } else {
      showSnackbar(result?.msg || '启动失败', 'error');
    }
  } catch (err) {
    showSnackbar(`启动失败: ${err.message || err}`, 'error');
  } finally {
    syncDbLoading.value = false;
  }
}

onMounted(() => {
  loadConfig();
});
</script>
