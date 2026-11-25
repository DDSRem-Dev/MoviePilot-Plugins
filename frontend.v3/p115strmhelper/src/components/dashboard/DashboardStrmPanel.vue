<template>
  <div class="dashboard-widget dashboard-widget--strm">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card dashboard-grid-fill">
      <!-- Unified Apple Widget Header with Inline Filter -->
      <div v-if="config?.attrs?.title || config?.attrs?.subtitle" class="p115-dash-header">
        <div class="p115-dash-header-left">
          <div class="p115-dash-icon">
            <v-icon icon="mdi-file-sync-outline" size="18" />
          </div>
          <div class="p115-dash-titles">
            <div class="p115-dash-title-row">
              <span>{{ config?.attrs?.title || "STRM 同步执行记录" }}</span>
              <span v-if="initialDataLoaded" class="p115-badge p115-badge--blue p115-tabular">
                {{ strmHistoryTotal }} 条
              </span>
            </div>
            <div v-if="config?.attrs?.subtitle" class="p115-dash-subtitle">
              {{ config.attrs.subtitle }}
            </div>
          </div>
        </div>

        <div class="p115-dash-header-right">
          <div v-if="initialDataLoaded" class="p115-dash-filter-select dashboard-grid-no-drag">
            <v-select
              v-model="strmKindSelected"
              :items="strmKindSelectItems"
              item-title="title"
              item-value="value"
              placeholder="全部类型"
              density="compact"
              hide-details
              variant="outlined"
              @update:model-value="applyStrmFilter"
            />
          </div>

          <button
            v-if="strmHistoryTotal > 0"
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
            :disabled="deletingAllStrm"
            @click="confirmDeleteAllStrm"
          >
            <v-progress-circular v-if="deletingAllStrm" indeterminate size="12" width="2" />
            <v-icon v-else size="14" icon="mdi-delete-sweep-outline" />
            <span>清空</span>
          </button>

          <button
            v-if="!allowRefresh"
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--icon dashboard-grid-no-drag"
            :disabled="strmHistoryLoading"
            title="刷新记录"
            @click="loadStrmHistory"
          >
            <v-progress-circular v-if="strmHistoryLoading" indeterminate size="13" width="2" />
            <v-icon v-else size="16" icon="mdi-refresh" />
          </button>
        </div>
      </div>

      <!-- Widget Body -->
      <div class="p115-dash-body">
        <div
          v-if="strmBannerMessage"
          class="p115-callout mb-3 dashboard-grid-no-drag"
          :class="strmBannerType === 'error' ? 'p115-callout--error' : 'p115-callout--success'"
        >
          <span class="flex-grow-1">{{ strmBannerMessage }}</span>
          <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" @click="strmBannerMessage = ''">
            <v-icon size="15" icon="mdi-close" />
          </button>
        </div>

        <div v-if="strmHistoryLoading && !initialDataLoaded" class="d-flex align-center justify-center flex-grow-1" style="min-height: 320px">
          <v-progress-circular indeterminate color="primary" size="34" />
        </div>

        <div v-else-if="strmLoadError" class="p115-callout p115-callout--error">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ strmLoadError }}</span>
        </div>

        <template v-else-if="initialDataLoaded">
          <v-skeleton-loader v-if="strmHistoryLoading" type="card, card" class="bg-transparent" />

          <div
            v-else-if="strmHistoryItems.length === 0"
            class="d-flex flex-column align-center justify-center flex-grow-1 py-8 text-center"
          >
            <v-icon icon="mdi-playlist-remove" size="48" class="mb-2 opacity-40" />
            <div class="text-body-2 font-weight-medium opacity-75">暂无执行记录</div>
            <div class="text-caption opacity-60 mt-1">完成一次全量、增量或分享同步后将在此展示</div>
          </div>

          <div v-else class="p115-dash-scroll">
            <div
              v-for="(row, idx) in strmHistoryItems"
              :key="row.unique || idx"
              class="p115-dash-row-card"
              :class="row.success ? 'p115-dash-row-card--accent' : 'p115-dash-row-card--fail'"
            >
              <!-- Compact Single-Row Header: Badges + Timestamp + Metrics + Delete -->
              <div class="d-flex align-center justify-space-between gap-2 flex-wrap mb-2">
                <div class="d-flex align-center flex-wrap gap-2 min-w-0">
                  <span class="p115-badge p115-badge--blue">{{ kindLabel(row.kind) }}</span>
                  <span class="p115-badge" :class="row.success ? 'p115-badge--green' : 'p115-badge--red'">
                    <span class="p115-badge-dot" />
                    {{ row.success ? "成功" : "失败" }}
                  </span>
                  <span class="text-body-2 font-weight-bold p115-tabular">{{ row.finished_at }}</span>
                  <span class="text-caption opacity-75 p115-tabular">
                    耗时 <strong>{{ formatNum(row.elapsed_sec) }}</strong> 秒 · 扫描
                    <strong>{{ row.total_iterated }}</strong> 项
                    <template v-if="row.kind === 'increment'">
                      · API <strong>{{ row.api_requests }}</strong> 次
                    </template>
                  </span>
                </div>

                <button
                  type="button"
                  class="p115-btn p115-btn--icon p115-btn--danger dashboard-grid-no-drag"
                  :disabled="!row.unique || deletingStrmId === row.unique"
                  title="删除此记录"
                  @click="confirmDeleteStrm(row)"
                >
                  <v-progress-circular v-if="deletingStrmId === row.unique" indeterminate size="13" width="2" />
                  <v-icon v-else size="15" icon="mdi-trash-can-outline" />
                </button>
              </div>

              <!-- Generation Statistics Pills -->
              <div class="p115-stat-pills">
                <span
                  v-for="s in parseStatsEntries(row.stats, row.kind)"
                  :key="s.key"
                  class="p115-stat-pill"
                  :class="resolveStatPillClass(s)"
                >
                  <span>{{ s.label }}</span>
                  <strong>{{ formatStatValue(s.value) }}</strong>
                </span>
              </div>

              <!-- Extra Metadata -->
              <div v-if="parseExtraEntries(row.extra).length" class="mt-2 pt-2" style="border-top: 1px dashed var(--p115-border-hairline)">
                <div v-for="(ex, ei) in parseExtraEntries(row.extra)" :key="ei" class="text-caption strm-extra-line">
                  <span class="opacity-70">{{ ex.label }}</span>
                  <a
                    v-if="ex.href"
                    :href="ex.href"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-primary ms-1 dashboard-grid-no-drag"
                  >
                    {{ ex.display }}
                  </a>
                  <span v-else class="ms-1 p115-mono" :title="ex.full">{{ ex.display }}</span>
                </div>
              </div>

              <!-- Failure Error Callout -->
              <div v-if="!row.success && row.error" class="p115-callout p115-callout--error mt-2">
                <v-icon size="15" color="error" icon="mdi-alert-outline" />
                <span>{{ row.error }}</span>
              </div>
            </div>
          </div>

          <div v-if="strmHistoryTotal > 0 && !strmHistoryLoading" class="p115-dash-pagebar">
            <div class="text-caption opacity-70 p115-tabular">{{ strmPageRangeText }}</div>
            <v-pagination
              v-model="strmHistoryPage"
              :length="strmPaginationLength"
              :total-visible="5"
              density="compact"
              size="small"
              class="dashboard-grid-no-drag"
              @update:model-value="loadStrmHistory"
            />
          </div>
        </template>
      </div>

      <!-- Refresh Footer -->
      <div v-if="allowRefresh" class="p115-dash-footer">
        <span class="text-caption opacity-65 p115-tabular">{{ lastRefreshedTimeDisplay }}</span>
        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon dashboard-grid-no-drag"
          :disabled="strmHistoryLoading"
          title="刷新记录"
          @click="loadStrmHistory"
        >
          <v-progress-circular v-if="strmHistoryLoading" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-refresh" />
        </button>
      </div>
    </v-card>

    <v-dialog v-model="deleteStrmConfirm.show" max-width="420" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="error" icon="mdi-alert-circle-outline" />
            <span>删除记录</span>
          </div>
        </div>
        <div class="p115-sheet-body">确定删除这条 STRM 执行历史吗？</div>
        <div class="p115-sheet-footer justify-end">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
            :disabled="Boolean(deletingStrmId)"
            @click="deleteStrmConfirm.show = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
            :disabled="Boolean(deletingStrmId)"
            @click="handleConfirmDeleteStrm"
          >
            删除
          </button>
        </div>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteAllStrmConfirm" max-width="440" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="error" icon="mdi-delete-sweep-outline" />
            <span>清空历史</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div class="mb-2">确定清空全部 <strong class="p115-tabular">{{ strmHistoryTotal }}</strong> 条 STRM 执行历史吗？</div>
          <div class="p115-callout p115-callout--error">
            <v-icon size="16" color="error" icon="mdi-alert-outline" />
            <span>此操作不可恢复</span>
          </div>
        </div>
        <div class="p115-sheet-footer justify-end">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
            :disabled="deletingAllStrm"
            @click="deleteAllStrmConfirm = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm dashboard-grid-no-drag"
            :disabled="deletingAllStrm"
            @click="handleConfirmDeleteAllStrm"
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
import {
  KIND_LABELS,
  kindLabel,
  parseStatsEntries,
  parseExtraEntries,
  statChipColor,
  formatStatValue,
  formatNum,
} from '../../utils/strmHistoryDisplay.js';
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

const initialDataLoaded = ref(false);
const lastRefreshedTimestamp = ref(null);

const strmKindSelected = ref('');
const strmKindApplied = ref('');
const strmHistoryPage = ref(1);
const strmHistoryLimit = ref(20);
const strmHistoryItems = ref([]);
const strmHistoryTotal = ref(0);
const strmHistoryLoading = ref(false);
const strmLoadError = ref(null);
const strmBannerMessage = ref('');
const strmBannerType = ref('info');
const deletingStrmId = ref(null);
const deletingAllStrm = ref(false);
const deleteStrmConfirm = reactive({ show: false, row: null });
const deleteAllStrmConfirm = ref(false);

const strmKindSelectItems = [
  { title: '全部类型', value: '' },
  ...Object.entries(KIND_LABELS).map(([value, title]) => ({ title, value })),
];

let refreshTimer = null;

function resolveStatPillClass(s) {
  const c = statChipColor(s);
  const numVal = Number(s?.value);
  if (c === 'error') return numVal > 0 ? 'p115-stat-pill--red' : 'p115-stat-pill--muted';
  if (c === 'warning') return numVal > 0 ? 'p115-stat-pill--amber' : 'p115-stat-pill--muted';
  if (c === 'success') return numVal > 0 ? 'p115-stat-pill--green' : 'p115-stat-pill--muted';
  if (Number.isFinite(numVal) && numVal === 0) return 'p115-stat-pill--muted';
  return 'p115-stat-pill--blue';
}

const strmPaginationLength = computed(() => {
  if (strmHistoryTotal.value <= 0 || strmHistoryLimit.value <= 0) return 0;
  return Math.ceil(strmHistoryTotal.value / strmHistoryLimit.value);
});

const strmPageRangeText = computed(() => {
  if (strmHistoryTotal.value <= 0) return '';
  const start = (strmHistoryPage.value - 1) * strmHistoryLimit.value + 1;
  const end = Math.min(strmHistoryPage.value * strmHistoryLimit.value, strmHistoryTotal.value);
  return `第 ${start} – ${end} 条，共 ${strmHistoryTotal.value} 条`;
});

const lastRefreshedTimeDisplay = computed(() => {
  if (!lastRefreshedTimestamp.value) return '';
  const date = new Date(lastRefreshedTimestamp.value);
  return `更新于: ${date.getHours().toString().padStart(2, '0')}:${date
    .getMinutes()
    .toString()
    .padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
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
    if (k) qs.set('kind', k);
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
      throw new Error(result?.msg || '获取执行记录失败');
    }
  } catch (err) {
    strmLoadError.value = err.message || '获取数据失败';
    initialDataLoaded.value = true;
  } finally {
    strmHistoryLoading.value = false;
  }
}

function applyStrmFilter() {
  const v = strmKindSelected.value;
  strmKindApplied.value = v != null && v !== '' ? String(v).trim() : '';
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
      strmBannerMessage.value = response.msg || '删除成功';
      strmBannerType.value = 'success';
      if (strmHistoryItems.value.length === 1 && strmHistoryPage.value > 1) {
        strmHistoryPage.value--;
      }
      await loadStrmHistory();
    } else {
      strmBannerMessage.value = response?.msg || '删除失败';
      strmBannerType.value = 'error';
    }
  } catch (err) {
    strmBannerMessage.value = `删除失败: ${err.message || '未知错误'}`;
    strmBannerType.value = 'error';
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
      strmBannerMessage.value = response.msg || '已清空';
      strmBannerType.value = 'success';
      strmHistoryPage.value = 1;
      await loadStrmHistory();
    } else {
      strmBannerMessage.value = response?.msg || '清空失败';
      strmBannerType.value = 'error';
    }
  } catch (err) {
    strmBannerMessage.value = `清空失败: ${err.message || '未知错误'}`;
    strmBannerType.value = 'error';
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
