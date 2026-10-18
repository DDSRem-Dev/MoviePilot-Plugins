<template>
  <div class="dashboard-widget dashboard-widget--strm">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card fill-height d-flex flex-column dashboard-grid-fill">
      <v-card-item v-if="config?.attrs?.title || config?.attrs?.subtitle" class="strm-dash-card__head pb-2">
        <v-card-title class="d-flex flex-wrap align-center gap-2 ps-0">
          <v-icon icon="mdi-sync" color="primary" size="small" />
          <span>{{ config?.attrs?.title || "STRM 同步执行记录" }}</span>
          <v-chip v-if="initialDataLoaded" size="small" color="primary" variant="tonal">
            {{ strmHistoryTotal }} 条
          </v-chip>
        </v-card-title>
        <v-card-subtitle v-if="config?.attrs?.subtitle">{{ config.attrs.subtitle }}</v-card-subtitle>
        <template v-slot:append>
          <div class="d-flex align-center flex-shrink-0">
            <v-btn
              v-if="strmHistoryTotal > 0"
              size="small"
              variant="text"
              color="error"
              class="mr-1 dashboard-grid-no-drag"
              prepend-icon="mdi-delete-sweep"
              :loading="deletingAllStrm"
              @click="confirmDeleteAllStrm"
            >
              清空
            </v-btn>
            <v-btn icon size="small" variant="text" class="dashboard-grid-no-drag" :loading="strmHistoryLoading" @click="loadStrmHistory">
              <v-icon>mdi-refresh</v-icon>
            </v-btn>
          </div>
        </template>
      </v-card-item>

      <v-card-text class="flex-grow-1 pa-3 pt-0 d-flex flex-column strm-dash-card__body">
        <v-alert
          v-if="strmBannerMessage"
          :type="strmBannerType"
          variant="tonal"
          density="comfortable"
          class="mb-3"
          closable
          @click:close="strmBannerMessage = ''"
        >
          {{ strmBannerMessage }}
        </v-alert>

        <div v-if="strmHistoryLoading && !initialDataLoaded" class="text-center py-8">
          <v-progress-circular indeterminate color="primary" size="40" />
        </div>

        <div v-else-if="strmLoadError" class="text-error text-body-2 d-flex align-center">
          <v-icon size="small" color="error" class="mr-1">mdi-alert-circle-outline</v-icon>
          {{ strmLoadError }}
        </div>

        <template v-else-if="initialDataLoaded">
          <div class="strm-filter-row d-flex flex-wrap align-center gap-2 mb-3">
            <v-select
              v-model="strmKindSelected"
              :items="strmKindSelectItems"
              item-title="title"
              item-value="value"
              label="任务类型"
              density="compact"
              hide-details
              clearable
              variant="outlined"
              class="strm-kind-field dashboard-grid-no-drag"
              @update:model-value="applyStrmFilter"
            />
          </div>

          <v-skeleton-loader v-if="strmHistoryLoading" type="card, card, card" class="bg-transparent" />

          <div v-else-if="strmHistoryItems.length === 0" class="text-center py-10 strm-dash-empty">
            <v-icon icon="mdi-playlist-remove" size="56" color="grey" class="mb-3 opacity-40" />
            <div class="text-body-1 text-medium-emphasis">暂无执行记录</div>
            <div class="text-caption text-medium-emphasis mt-1">完成一次全量、增量或分享同步后将在此展示</div>
          </div>

          <div v-else class="strm-dash-list flex-grow-1">
            <v-card
              v-for="(row, idx) in strmHistoryItems"
              :key="row.unique || idx"
              variant="outlined"
              class="strm-dash-item strm-history-item mb-3"
              :class="{ 'strm-dash-item--fail strm-history-item--fail': !row.success }"
            >
              <v-card-item class="pb-2">
                <div class="flex-grow-1 min-w-0">
                  <div class="d-flex flex-wrap align-center gap-2 mb-2">
                    <v-chip size="small" color="primary" variant="flat">{{ kindLabel(row.kind) }}</v-chip>
                    <v-chip size="small" :color="row.success ? 'success' : 'error'" variant="tonal">
                      {{ row.success ? "成功" : "失败" }}
                    </v-chip>
                  </div>
                  <div class="text-h6 font-weight-medium text-high-emphasis">
                    {{ row.finished_at }}
                  </div>
                  <div class="text-body-2 text-medium-emphasis mt-2">
                    耗时 <strong class="text-high-emphasis">{{ formatNum(row.elapsed_sec) }}</strong> 秒 · 扫描
                    <strong class="text-high-emphasis">{{ row.total_iterated }}</strong> 项
                    <template v-if="row.kind === 'increment'">
                      · API <strong class="text-high-emphasis">{{ row.api_requests }}</strong> 次
                    </template>
                  </div>
                </div>
                <template v-slot:append>
                  <v-btn
                    icon
                    size="small"
                    variant="text"
                    class="dashboard-grid-no-drag"
                    color="error"
                    :loading="deletingStrmId === row.unique"
                    :disabled="!row.unique"
                    @click="confirmDeleteStrm(row)"
                  >
                    <v-icon size="small">mdi-delete-outline</v-icon>
                  </v-btn>
                </template>
              </v-card-item>
              <v-card-text class="pt-0">
                <div class="text-caption text-medium-emphasis strm-section-label mb-2">生成统计</div>
                <div class="d-flex flex-wrap gap-1 mb-1">
                  <v-chip
                    v-for="s in parseStatsEntries(row.stats, row.kind)"
                    :key="s.key"
                    size="small"
                    :color="statChipColor(s)"
                    variant="tonal"
                  >
                    {{ s.label }} {{ formatStatValue(s.value) }}
                  </v-chip>
                </div>
                <div v-if="parseExtraEntries(row.extra).length" class="mt-3">
                  <div class="text-caption text-medium-emphasis strm-section-label mb-2">补充信息</div>
                  <div v-for="(ex, ei) in parseExtraEntries(row.extra)" :key="ei" class="text-body-2 strm-extra-line">
                    <span class="text-medium-emphasis">{{ ex.label }}</span>
                    <a
                      v-if="ex.href"
                      :href="ex.href"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="text-primary ms-1 dashboard-grid-no-drag"
                      >{{ ex.display }}</a
                    >
                    <span v-else class="ms-1 text-high-emphasis" :title="ex.full">{{ ex.display }}</span>
                  </div>
                </div>
                <v-alert
                  v-if="!row.success && row.error"
                  type="error"
                  variant="tonal"
                  density="compact"
                  class="mt-3"
                  border="start"
                >
                  {{ row.error }}
                </v-alert>
              </v-card-text>
            </v-card>
          </div>

          <div
            v-if="strmHistoryTotal > 0 && !strmHistoryLoading"
            class="d-flex flex-wrap align-center justify-space-between mt-2 gap-2"
          >
            <div class="text-caption text-medium-emphasis">
              {{ strmPageRangeText }}
            </div>
            <v-pagination
              v-model="strmHistoryPage"
              :length="strmPaginationLength"
              :total-visible="7"
              density="comfortable"
              class="dashboard-grid-no-drag"
              @update:model-value="loadStrmHistory"
            />
          </div>
        </template>
      </v-card-text>

      <v-divider v-if="allowRefresh" />
      <v-card-actions v-if="allowRefresh" class="px-3 py-2 refresh-actions">
        <span class="text-caption text-disabled">{{ lastRefreshedTimeDisplay }}</span>
        <v-spacer />
        <v-btn icon variant="text" size="small" class="dashboard-grid-no-drag" :loading="strmHistoryLoading" @click="loadStrmHistory">
          <v-icon size="small">mdi-refresh</v-icon>
        </v-btn>
      </v-card-actions>
    </v-card>

    <v-dialog v-model="deleteStrmConfirm.show" max-width="420" persistent>
      <v-card>
        <v-card-title class="text-h6 d-flex align-center">
          <v-icon icon="mdi-alert-circle-outline" color="error" class="mr-2" />
          删除记录
        </v-card-title>
        <v-card-text>确定删除这条 STRM 执行历史吗？</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="grey" variant="text" class="dashboard-grid-no-drag" :disabled="deletingStrmId" @click="deleteStrmConfirm.show = false">
            取消
          </v-btn>
          <v-btn color="error" variant="text" class="dashboard-grid-no-drag" :loading="deletingStrmId" @click="handleConfirmDeleteStrm">
            删除
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteAllStrmConfirm" max-width="450" persistent>
      <v-card>
        <v-card-title class="text-h6 d-flex align-center">
          <v-icon icon="mdi-alert-circle-outline" color="error" class="mr-2" />
          清空历史
        </v-card-title>
        <v-card-text>
          <div class="mb-2">确定清空全部 <strong>{{ strmHistoryTotal }}</strong> 条 STRM 执行历史吗？</div>
          <v-alert type="error" variant="tonal" density="compact" class="mt-2" icon="mdi-alert">
            <div class="text-caption">此操作不可恢复</div>
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="grey" variant="text" class="dashboard-grid-no-drag" :disabled="deletingAllStrm" @click="deleteAllStrmConfirm = false">
            取消
          </v-btn>
          <v-btn color="error" variant="text" class="dashboard-grid-no-drag" :loading="deletingAllStrm" @click="handleConfirmDeleteAllStrm">
            确认清空
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from "vue";
import {
  KIND_LABELS,
  kindLabel,
  parseStatsEntries,
  parseExtraEntries,
  statChipColor,
  formatStatValue,
  formatNum,
} from "../../utils/strmHistoryDisplay.js";
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

const initialDataLoaded = ref(false);
const lastRefreshedTimestamp = ref(null);

const strmKindSelected = ref("");
const strmKindApplied = ref("");
const strmHistoryPage = ref(1);
const strmHistoryLimit = ref(20);
const strmHistoryItems = ref([]);
const strmHistoryTotal = ref(0);
const strmHistoryLoading = ref(false);
const strmLoadError = ref(null);
const strmBannerMessage = ref("");
const strmBannerType = ref("info");
const deletingStrmId = ref(null);
const deletingAllStrm = ref(false);
const deleteStrmConfirm = reactive({ show: false, row: null });
const deleteAllStrmConfirm = ref(false);

const strmKindSelectItems = [
  { title: "全部类型", value: "" },
  ...Object.entries(KIND_LABELS).map(([value, title]) => ({ title, value })),
];

let refreshTimer = null;

const strmPaginationLength = computed(() => {
  if (strmHistoryTotal.value <= 0 || strmHistoryLimit.value <= 0) return 0;
  return Math.ceil(strmHistoryTotal.value / strmHistoryLimit.value);
});

const strmPageRangeText = computed(() => {
  if (strmHistoryTotal.value <= 0) return "";
  const start = (strmHistoryPage.value - 1) * strmHistoryLimit.value + 1;
  const end = Math.min(strmHistoryPage.value * strmHistoryLimit.value, strmHistoryTotal.value);
  return `第 ${start} – ${end} 条，共 ${strmHistoryTotal.value} 条`;
});

const lastRefreshedTimeDisplay = computed(() => {
  if (!lastRefreshedTimestamp.value) return "";
  const date = new Date(lastRefreshedTimestamp.value);
  return `更新于: ${date.getHours().toString().padStart(2, "0")}:${date
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}`;
});

async function loadStrmHistory() {
  strmHistoryLoading.value = true;
  strmLoadError.value = null;
  try {
    const qs = new URLSearchParams({
      page: String(strmHistoryPage.value),
      limit: String(strmHistoryLimit.value),
    });
    const k = strmKindApplied.value?.trim();
    if (k) {
      qs.set("kind", k);
    }
    const result = await props.api.get(
      `plugin/${P115_STRM_HELPER_PLUGIN_ID}/get_strm_sync_history?${qs.toString()}`,
    );
    if (result && result.code === 0 && result.data) {
      strmHistoryItems.value = Array.isArray(result.data.items) ? result.data.items : [];
      strmHistoryTotal.value = result.data.total || 0;
      initialDataLoaded.value = true;
      lastRefreshedTimestamp.value = Date.now();
    } else {
      strmHistoryItems.value = [];
      strmHistoryTotal.value = 0;
      initialDataLoaded.value = true;
      throw new Error(result?.msg || "获取执行记录失败");
    }
  } catch (err) {
    console.error("获取 STRM 执行记录失败:", err);
    strmLoadError.value = err.message || "获取数据失败";
    initialDataLoaded.value = true;
  } finally {
    strmHistoryLoading.value = false;
  }
}

function applyStrmFilter() {
  const v = strmKindSelected.value;
  strmKindApplied.value = v != null && v !== "" ? String(v).trim() : "";
  strmHistoryPage.value = 1;
  loadStrmHistory();
}

function confirmDeleteStrm(row) {
  if (!row?.unique) return;
  deleteStrmConfirm.row = row;
  deleteStrmConfirm.show = true;
}

async function handleConfirmDeleteStrm() {
  const unique = deleteStrmConfirm.row?.unique;
  if (!unique) return;
  deleteStrmConfirm.show = false;
  deletingStrmId.value = unique;
  try {
    const response = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/delete_strm_sync_history`, {
      key: unique,
    });
    if (response && response.code === 0) {
      strmBannerMessage.value = response.msg || "删除成功";
      strmBannerType.value = "success";
      if (strmHistoryItems.value.length === 1 && strmHistoryPage.value > 1) {
        strmHistoryPage.value--;
      }
      await loadStrmHistory();
    } else {
      strmBannerMessage.value = response?.msg || "删除失败";
      strmBannerType.value = "error";
    }
  } catch (err) {
    console.error("删除 STRM 历史失败:", err);
    strmBannerMessage.value = `删除失败: ${err.message || "未知错误"}`;
    strmBannerType.value = "error";
  } finally {
    deletingStrmId.value = null;
    deleteStrmConfirm.row = null;
  }
}

function confirmDeleteAllStrm() {
  if (strmHistoryTotal.value === 0) return;
  deleteAllStrmConfirm.value = true;
}

async function handleConfirmDeleteAllStrm() {
  deleteAllStrmConfirm.value = false;
  deletingAllStrm.value = true;
  try {
    const response = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/delete_all_strm_sync_history`);
    if (response && response.code === 0) {
      strmBannerMessage.value = response.msg || "已清空";
      strmBannerType.value = "success";
      strmHistoryPage.value = 1;
      await loadStrmHistory();
    } else {
      strmBannerMessage.value = response?.msg || "清空失败";
      strmBannerType.value = "error";
    }
  } catch (err) {
    console.error("清空 STRM 历史失败:", err);
    strmBannerMessage.value = `清空失败: ${err.message || "未知错误"}`;
    strmBannerType.value = "error";
  } finally {
    deletingAllStrm.value = false;
  }
}

onMounted(() => {
  loadStrmHistory();
  if (props.refreshInterval > 0) {
    refreshTimer = setInterval(loadStrmHistory, props.refreshInterval * 1000);
  }
});

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
});
</script>
