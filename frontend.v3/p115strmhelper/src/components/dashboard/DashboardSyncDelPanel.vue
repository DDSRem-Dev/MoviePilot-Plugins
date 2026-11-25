<template>
  <div class="dashboard-widget dashboard-widget--sync-del">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card dashboard-grid-fill">
      <!-- Unified Apple Widget Header -->
      <div v-if="config?.attrs?.title || config?.attrs?.subtitle" class="p115-dash-header">
        <div class="p115-dash-header-left">
          <div class="p115-dash-icon">
            <v-icon icon="mdi-delete-sweep-outline" size="18" />
          </div>
          <div class="p115-dash-titles">
            <div class="p115-dash-title-row">
              <span>{{ config?.attrs?.title || "同步删除历史" }}</span>
              <span v-if="syncDelInitialLoaded" class="p115-badge p115-badge--pink p115-tabular">
                {{ syncDelHistoryTotal }} 条
              </span>
            </div>
            <div v-if="config?.attrs?.subtitle" class="p115-dash-subtitle">
              {{ config.attrs.subtitle }}
            </div>
          </div>
        </div>

        <div class="p115-dash-header-right">
          <button
            v-if="syncDelHistoryTotal > 0"
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
            :disabled="deletingAllSyncDel"
            @click="confirmDeleteAllSyncDel"
          >
            <v-progress-circular v-if="deletingAllSyncDel" indeterminate size="12" width="2" />
            <v-icon v-else size="14" icon="mdi-delete-sweep-outline" />
            <span>清空</span>
          </button>

          <button
            v-if="!allowRefresh"
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--icon dashboard-grid-no-drag"
            :disabled="syncDelHistoryLoading"
            title="刷新历史"
            @click="loadSyncDelHistory"
          >
            <v-progress-circular v-if="syncDelHistoryLoading" indeterminate size="13" width="2" />
            <v-icon v-else size="16" icon="mdi-refresh" />
          </button>
        </div>
      </div>

      <!-- Widget Body -->
      <div class="p115-dash-body">
        <div
          v-if="syncDelBannerMessage"
          class="p115-callout mb-3 dashboard-grid-no-drag"
          :class="syncDelBannerType === 'error' ? 'p115-callout--error' : 'p115-callout--success'"
        >
          <span class="flex-grow-1">{{ syncDelBannerMessage }}</span>
          <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" @click="syncDelBannerMessage = ''">
            <v-icon size="15" icon="mdi-close" />
          </button>
        </div>

        <div v-if="syncDelHistoryLoading && !syncDelInitialLoaded" class="d-flex align-center justify-center flex-grow-1" style="min-height: 296px">
          <v-progress-circular indeterminate color="primary" size="34" />
        </div>

        <div v-else-if="syncDelLoadError" class="p115-callout p115-callout--error">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ syncDelLoadError }}</span>
        </div>

        <template v-else-if="syncDelInitialLoaded">
          <v-skeleton-loader
            v-if="syncDelHistoryLoading"
            type="list-item-avatar-three-line@3"
            class="bg-transparent"
          />

          <div
            v-else-if="syncDelHistory.length === 0"
            class="d-flex flex-column align-center justify-center flex-grow-1 py-8 text-center"
          >
            <v-icon icon="mdi-information-outline" size="48" class="mb-2 opacity-40" />
            <div class="text-body-2 font-weight-medium opacity-75">暂无删除历史</div>
            <div class="text-caption opacity-60 mt-1">媒体同步删除任务完成后将在此记录</div>
          </div>

          <div v-else class="p115-dash-scroll">
            <div
              v-for="(item, index) in syncDelHistory"
              :key="item.unique || index"
              class="p115-dash-row-card d-flex align-center gap-3"
            >
              <v-avatar size="48" rounded="lg" class="flex-shrink-0">
                <v-img v-if="item.image" :src="item.image" :alt="item.title" cover />
                <v-icon v-else icon="mdi-movie-open-outline" color="primary" />
              </v-avatar>

              <div class="min-w-0 flex-grow-1">
                <div class="d-flex align-center flex-wrap gap-2">
                  <span class="text-body-2 font-weight-bold text-truncate">{{ item.title }}</span>
                  <span class="p115-badge p115-badge--blue">{{ item.type }}</span>
                  <span v-if="item.year" class="text-caption opacity-75 p115-tabular">{{ item.year }}</span>
                  <span v-if="item.season" class="text-caption opacity-75 p115-tabular">
                    S{{ String(item.season).padStart(2, "0") }}
                  </span>
                  <span v-if="item.episode" class="text-caption opacity-75 p115-tabular">
                    E{{ String(item.episode).padStart(2, "0") }}
                  </span>
                </div>
                <div v-if="item.path" class="text-caption opacity-75 mt-1 p115-mono sync-del-path">
                  {{ item.path }}
                </div>
                <div class="text-caption opacity-60 mt-1 p115-tabular">{{ item.del_time }}</div>
              </div>

              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger dashboard-grid-no-drag flex-shrink-0"
                :disabled="!item.unique || deletingSyncDelId === item.unique"
                title="删除此记录"
                @click="confirmDeleteSyncDel(item)"
              >
                <v-progress-circular v-if="deletingSyncDelId === item.unique" indeterminate size="13" width="2" />
                <v-icon v-else size="15" icon="mdi-trash-can-outline" />
              </button>
            </div>
          </div>

          <div v-if="syncDelHistoryTotal > 0 && !syncDelHistoryLoading" class="p115-dash-pagebar">
            <div class="text-caption opacity-70 p115-tabular">{{ syncDelPageRangeText }}</div>
            <v-pagination
              v-model="syncDelHistoryPage"
              :length="syncDelPaginationLength"
              :total-visible="5"
              density="compact"
              size="small"
              class="dashboard-grid-no-drag"
              @update:model-value="loadSyncDelHistory"
            />
          </div>
        </template>
      </div>

      <!-- Refresh Footer -->
      <div v-if="allowRefresh" class="p115-dash-footer">
        <span class="text-caption opacity-65 p115-tabular">{{ lastRefreshedTimeDisplaySyncDel }}</span>
        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon dashboard-grid-no-drag"
          :disabled="syncDelHistoryLoading"
          title="刷新历史"
          @click="loadSyncDelHistory"
        >
          <v-progress-circular v-if="syncDelHistoryLoading" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-refresh" />
        </button>
      </div>
    </v-card>

    <v-dialog v-model="deleteSyncDelConfirm.show" max-width="420" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="error" icon="mdi-alert-circle-outline" />
            <span>删除记录</span>
          </div>
        </div>
        <div class="p115-sheet-body">确定删除这条同步删除历史吗？</div>
        <div class="p115-sheet-footer justify-end">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
            :disabled="Boolean(deletingSyncDelId)"
            @click="deleteSyncDelConfirm.show = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
            :disabled="Boolean(deletingSyncDelId)"
            @click="handleConfirmDeleteSyncDel"
          >
            删除
          </button>
        </div>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteAllSyncDelConfirm" max-width="440" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="error" icon="mdi-delete-sweep-outline" />
            <span>清空历史</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div class="mb-2">确定清空全部 <strong class="p115-tabular">{{ syncDelHistoryTotal }}</strong> 条同步删除历史吗？</div>
          <div class="p115-callout p115-callout--error">
            <v-icon size="16" color="error" icon="mdi-alert-outline" />
            <span>此操作不可恢复</span>
          </div>
        </div>
        <div class="p115-sheet-footer justify-end">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
            :disabled="deletingAllSyncDel"
            @click="deleteAllSyncDelConfirm = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
            :disabled="deletingAllSyncDel"
            @click="handleConfirmDeleteAllSyncDel"
          >
            确认清空
          </button>
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import { P115_STRM_HELPER_PLUGIN_ID } from '../../utils/pluginId.js';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

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

const { dialogContentClass } = useThemeAdapter();

const syncDelHistory = ref([]);
const syncDelHistoryLoading = ref(false);
const syncDelHistoryTotal = ref(0);
const syncDelHistoryPage = ref(1);
const syncDelHistoryLimit = ref(20);
const syncDelInitialLoaded = ref(false);
const syncDelLoadError = ref(null);
const syncDelBannerMessage = ref('');
const syncDelBannerType = ref('info');
const deletingSyncDelId = ref(null);
const deletingAllSyncDel = ref(false);
const deleteSyncDelConfirm = reactive({ show: false, item: null });
const deleteAllSyncDelConfirm = ref(false);
const lastRefreshedTimestampSyncDel = ref(null);

let refreshTimer = null;

const syncDelPaginationLength = computed(() => {
  if (syncDelHistoryTotal.value <= 0 || syncDelHistoryLimit.value <= 0) return 0;
  return Math.ceil(syncDelHistoryTotal.value / syncDelHistoryLimit.value);
});

const syncDelPageRangeText = computed(() => {
  if (syncDelHistoryTotal.value <= 0) return '';
  const start = (syncDelHistoryPage.value - 1) * syncDelHistoryLimit.value + 1;
  const end = Math.min(syncDelHistoryPage.value * syncDelHistoryLimit.value, syncDelHistoryTotal.value);
  return `第 ${start} – ${end} 条，共 ${syncDelHistoryTotal.value} 条`;
});

const lastRefreshedTimeDisplaySyncDel = computed(() => {
  if (!lastRefreshedTimestampSyncDel.value) return '';
  const date = new Date(lastRefreshedTimestampSyncDel.value);
  return `更新于: ${date.getHours().toString().padStart(2, '0')}:${date
    .getMinutes()
    .toString()
    .padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
});

async function loadSyncDelHistory() {
  syncDelHistoryLoading.value = true;
  syncDelLoadError.value = null;
  try {
    const response = await props.api.get(
      `plugin/${P115_STRM_HELPER_PLUGIN_ID}/get_sync_del_history?page=${syncDelHistoryPage.value}&limit=${syncDelHistoryLimit.value}`,
    );
    if (response && response.code === 0 && response.data) {
      if (response.data.items && Array.isArray(response.data.items)) {
        syncDelHistory.value = response.data.items;
        syncDelHistoryTotal.value = response.data.total || 0;
      } else if (Array.isArray(response.data)) {
        syncDelHistory.value = response.data;
        syncDelHistoryTotal.value = response.data.length;
      } else {
        syncDelHistory.value = [];
        syncDelHistoryTotal.value = 0;
      }
      syncDelInitialLoaded.value = true;
      lastRefreshedTimestampSyncDel.value = Date.now();
    } else {
      syncDelHistory.value = [];
      syncDelHistoryTotal.value = 0;
      syncDelInitialLoaded.value = true;
      throw new Error(response?.msg || '获取同步删除历史失败');
    }
  } catch (err) {
    syncDelLoadError.value = err.message || '获取数据失败';
    syncDelHistory.value = [];
    syncDelHistoryTotal.value = 0;
    syncDelInitialLoaded.value = true;
  } finally {
    syncDelHistoryLoading.value = false;
  }
}

function confirmDeleteSyncDel(item) {
  if (!item?.unique) return;
  deleteSyncDelConfirm.item = item;
  deleteSyncDelConfirm.show = true;
}

async function handleConfirmDeleteSyncDel() {
  const unique = deleteSyncDelConfirm.item?.unique;
  if (!unique) return;
  deleteSyncDelConfirm.show = false;
  deletingSyncDelId.value = unique;
  try {
    const response = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/delete_sync_del_history`, {
      key: unique,
    });
    if (response && response.code === 0) {
      syncDelBannerMessage.value = response.msg || '删除成功';
      syncDelBannerType.value = 'success';
      if (syncDelHistory.value.length === 1 && syncDelHistoryPage.value > 1) {
        syncDelHistoryPage.value--;
      }
      await loadSyncDelHistory();
    } else {
      syncDelBannerMessage.value = response?.msg || '删除失败';
      syncDelBannerType.value = 'error';
    }
  } catch (err) {
    syncDelBannerMessage.value = `删除失败: ${err.message || '未知错误'}`;
    syncDelBannerType.value = 'error';
  } finally {
    deletingSyncDelId.value = null;
    deleteSyncDelConfirm.item = null;
  }
}

function confirmDeleteAllSyncDel() {
  if (syncDelHistoryTotal.value === 0) return;
  deleteAllSyncDelConfirm.value = true;
}

async function handleConfirmDeleteAllSyncDel() {
  deleteAllSyncDelConfirm.value = false;
  deletingAllSyncDel.value = true;
  try {
    const response = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/delete_all_sync_del_history`);
    if (response && response.code === 0) {
      syncDelBannerMessage.value = response.msg || '已清空';
      syncDelBannerType.value = 'success';
      syncDelHistoryPage.value = 1;
      await loadSyncDelHistory();
    } else {
      syncDelBannerMessage.value = response?.msg || '清空失败';
      syncDelBannerType.value = 'error';
    }
  } catch (err) {
    syncDelBannerMessage.value = `清空失败: ${err.message || '未知错误'}`;
    syncDelBannerType.value = 'error';
  } finally {
    deletingAllSyncDel.value = false;
  }
}

onMounted(() => {
  loadSyncDelHistory();
  if (props.refreshInterval > 0) {
    refreshTimer = setInterval(loadSyncDelHistory, props.refreshInterval * 1000);
  }
});

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
});
</script>
