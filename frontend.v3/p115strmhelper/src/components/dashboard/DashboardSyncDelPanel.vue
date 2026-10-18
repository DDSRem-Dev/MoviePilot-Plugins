<template>
  <div class="dashboard-widget dashboard-widget--sync-del">
    <v-card
      :flat="!config?.attrs?.border"
      class="strm-dash-card sync-del-dash-card fill-height d-flex flex-column dashboard-grid-fill"
    >
      <v-card-item v-if="config?.attrs?.title || config?.attrs?.subtitle" class="strm-dash-card__head pb-2">
        <v-card-title class="d-flex flex-wrap align-center gap-2 ps-0">
          <v-icon icon="mdi-delete-sweep" color="warning" size="small" />
          <span>{{ config?.attrs?.title || "同步删除历史" }}</span>
          <v-chip v-if="syncDelInitialLoaded" size="small" color="warning" variant="tonal">
            {{ syncDelHistoryTotal }} 条
          </v-chip>
        </v-card-title>
        <v-card-subtitle v-if="config?.attrs?.subtitle">{{ config.attrs.subtitle }}</v-card-subtitle>
        <template v-slot:append>
          <div class="d-flex align-center flex-shrink-0">
            <v-btn
              v-if="syncDelHistoryTotal > 0"
              size="small"
              variant="text"
              color="error"
              class="mr-1 dashboard-grid-no-drag"
              prepend-icon="mdi-delete-sweep"
              :loading="deletingAllSyncDel"
              @click="confirmDeleteAllSyncDel"
            >
              清空
            </v-btn>
            <v-btn icon size="small" variant="text" class="dashboard-grid-no-drag" :loading="syncDelHistoryLoading" @click="loadSyncDelHistory">
              <v-icon>mdi-refresh</v-icon>
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <v-card-text class="flex-grow-1 pa-3 pt-0 d-flex flex-column sync-del-dash-card__body">
        <v-alert
          v-if="syncDelBannerMessage"
          :type="syncDelBannerType"
          variant="tonal"
          density="comfortable"
          class="mb-3"
          closable
          @click:close="syncDelBannerMessage = ''"
        >
          {{ syncDelBannerMessage }}
        </v-alert>

        <div v-if="syncDelHistoryLoading && !syncDelInitialLoaded" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="40" />
        </div>

        <div v-else-if="syncDelLoadError" class="text-error text-body-2 d-flex align-center">
          <v-icon size="small" color="error" class="mr-1">mdi-alert-circle-outline</v-icon>
          {{ syncDelLoadError }}
        </div>

        <template v-else-if="syncDelInitialLoaded">
          <v-skeleton-loader v-if="syncDelHistoryLoading" type="list-item-avatar-three-line@3" class="bg-transparent" />

          <div v-else-if="syncDelHistory.length === 0" class="text-center py-10">
            <v-icon icon="mdi-information-outline" size="56" color="grey" class="mb-3 opacity-40" />
            <div class="text-body-1 text-medium-emphasis">暂无删除历史</div>
            <div class="text-caption text-medium-emphasis mt-1">媒体同步删除任务完成后将在此记录</div>
          </div>

          <div v-else class="sync-del-list flex-grow-1">
            <v-list class="bg-transparent pa-0">
              <template v-for="(item, index) in syncDelHistory" :key="item.unique || index">
                <v-list-item class="px-0 py-2">
                  <template v-slot:prepend>
                    <v-avatar size="48" rounded class="mr-3">
                      <v-img v-if="item.image" :src="item.image" :alt="item.title" cover />
                      <v-icon v-else icon="mdi-movie" />
                    </v-avatar>
                  </template>
                  <v-list-item-title class="text-body-1 font-weight-medium">{{ item.title }}</v-list-item-title>
                  <v-list-item-subtitle class="text-caption">
                    <div class="d-flex flex-wrap align-center gap-1 mt-1">
                      <v-chip size="small" variant="tonal" color="primary">{{ item.type }}</v-chip>
                      <span v-if="item.year" class="text-medium-emphasis">· {{ item.year }}</span>
                      <span v-if="item.season" class="text-medium-emphasis">
                        · S{{ String(item.season).padStart(2, "0") }}
                      </span>
                      <span v-if="item.episode" class="text-medium-emphasis">
                        · E{{ String(item.episode).padStart(2, "0") }}
                      </span>
                    </div>
                    <div v-if="item.path" class="text-medium-emphasis mt-1 sync-del-path">{{ item.path }}</div>
                    <div class="text-medium-emphasis mt-1">{{ item.del_time }}</div>
                  </v-list-item-subtitle>
                  <template v-slot:append>
                    <v-btn
                      icon
                      size="small"
                      variant="text"
                      class="dashboard-grid-no-drag"
                      color="error"
                      :loading="deletingSyncDelId === item.unique"
                      :disabled="!item.unique"
                      @click="confirmDeleteSyncDel(item)"
                    >
                      <v-icon>mdi-delete</v-icon>
                    </v-btn>
                  </template>
                </v-list-item>
                <v-divider v-if="index < syncDelHistory.length - 1" class="my-0" />
              </template>
            </v-list>
          </div>

          <div
            v-if="syncDelHistoryTotal > 0 && !syncDelHistoryLoading"
            class="d-flex flex-wrap align-center justify-space-between mt-2 gap-2"
          >
            <div class="text-caption text-medium-emphasis">
              {{ syncDelPageRangeText }}
            </div>
            <v-pagination
              v-model="syncDelHistoryPage"
              :length="syncDelPaginationLength"
              :total-visible="7"
              density="comfortable"
              class="dashboard-grid-no-drag"
              @update:model-value="loadSyncDelHistory"
            />
          </div>
        </template>
      </v-card-text>

      <v-divider v-if="allowRefresh" />
      <v-card-actions v-if="allowRefresh" class="px-3 py-2 refresh-actions">
        <span class="text-caption text-disabled">{{ lastRefreshedTimeDisplaySyncDel }}</span>
        <v-spacer />
        <v-btn icon variant="text" size="small" class="dashboard-grid-no-drag" :loading="syncDelHistoryLoading" @click="loadSyncDelHistory">
          <v-icon size="small">mdi-refresh</v-icon>
        </v-btn>
      </v-card-actions>
    </v-card>

    <v-dialog v-model="deleteSyncDelConfirm.show" max-width="420" persistent>
      <v-card>
        <v-card-title class="text-h6 d-flex align-center">
          <v-icon icon="mdi-alert-circle-outline" color="error" class="mr-2" />
          删除记录
        </v-card-title>
        <v-card-text>确定删除这条同步删除历史吗？</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="grey" variant="text" class="dashboard-grid-no-drag" :disabled="deletingSyncDelId" @click="deleteSyncDelConfirm.show = false">
            取消
          </v-btn>
          <v-btn color="error" variant="text" class="dashboard-grid-no-drag" :loading="deletingSyncDelId" @click="handleConfirmDeleteSyncDel">
            删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteAllSyncDelConfirm" max-width="450" persistent>
      <v-card>
        <v-card-title class="text-h6 d-flex align-center">
          <v-icon icon="mdi-alert-circle-outline" color="error" class="mr-2" />
          清空历史
        </v-card-title>
        <v-card-text>
          <div class="mb-2">确定清空全部 <strong>{{ syncDelHistoryTotal }}</strong> 条同步删除历史吗？</div>
          <v-alert type="error" variant="tonal" density="compact" class="mt-2" icon="mdi-alert">
            <div class="text-caption">此操作不可恢复</div>
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="grey" variant="text" class="dashboard-grid-no-drag" :disabled="deletingAllSyncDel" @click="deleteAllSyncDelConfirm = false">
            取消
          </v-btn>
          <v-btn color="error" variant="text" class="dashboard-grid-no-drag" :loading="deletingAllSyncDel" @click="handleConfirmDeleteAllSyncDel">
            确认清空
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
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

const syncDelHistory = ref([]);
const syncDelHistoryLoading = ref(false);
const syncDelHistoryTotal = ref(0);
const syncDelHistoryPage = ref(1);
const syncDelHistoryLimit = ref(20);
const syncDelInitialLoaded = ref(false);
const syncDelLoadError = ref(null);
const syncDelBannerMessage = ref("");
const syncDelBannerType = ref("info");
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
  if (syncDelHistoryTotal.value <= 0) return "";
  const start = (syncDelHistoryPage.value - 1) * syncDelHistoryLimit.value + 1;
  const end = Math.min(syncDelHistoryPage.value * syncDelHistoryLimit.value, syncDelHistoryTotal.value);
  return `第 ${start} – ${end} 条，共 ${syncDelHistoryTotal.value} 条`;
});

const lastRefreshedTimeDisplaySyncDel = computed(() => {
  if (!lastRefreshedTimestampSyncDel.value) return "";
  const date = new Date(lastRefreshedTimestampSyncDel.value);
  return `更新于: ${date.getHours().toString().padStart(2, "0")}:${date
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}`;
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
      throw new Error(response?.msg || "获取同步删除历史失败");
    }
  } catch (err) {
    console.error("加载同步删除历史失败:", err);
    syncDelLoadError.value = err.message || "获取数据失败";
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
      syncDelBannerMessage.value = response.msg || "删除成功";
      syncDelBannerType.value = "success";
      if (syncDelHistory.value.length === 1 && syncDelHistoryPage.value > 1) {
        syncDelHistoryPage.value--;
      }
      await loadSyncDelHistory();
    } else {
      syncDelBannerMessage.value = response?.msg || "删除失败";
      syncDelBannerType.value = "error";
    }
  } catch (err) {
    console.error("删除同步删除历史失败:", err);
    syncDelBannerMessage.value = `删除失败: ${err.message || "未知错误"}`;
    syncDelBannerType.value = "error";
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
      syncDelBannerMessage.value = response.msg || "已清空";
      syncDelBannerType.value = "success";
      syncDelHistoryPage.value = 1;
      await loadSyncDelHistory();
    } else {
      syncDelBannerMessage.value = response?.msg || "清空失败";
      syncDelBannerType.value = "error";
    }
  } catch (err) {
    console.error("清空同步删除历史失败:", err);
    syncDelBannerMessage.value = `清空失败: ${err.message || "未知错误"}`;
    syncDelBannerType.value = "error";
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
