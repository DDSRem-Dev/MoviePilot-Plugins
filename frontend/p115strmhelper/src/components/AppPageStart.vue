<template>
  <v-container fluid class="app-start pa-2 pa-sm-4">
    <div class="d-flex align-center flex-wrap gap-2 mb-2 mb-sm-3">
      <v-icon icon="mdi-view-dashboard-outline" color="primary" :size="isMobile ? 22 : 26" />
      <span :class="['font-weight-medium', 'text-high-emphasis', isMobile ? 'text-subtitle-1' : 'text-h6']">
        115 助手仪表盘
      </span>
    </div>

    <!-- 分享 STRM 清理（对齐媒体整理：单卡 + 顶栏 + 表格区） -->
    <v-card class="app-start-card mb-4" variant="flat" rounded="0">
      <v-card-item class="py-3">
        <v-card-title class="text-subtitle-1 pa-0 font-weight-medium">
          <v-row align="center" class="ma-n1" no-gutters>
            <v-col cols="12" lg="7" class="pa-1">
              <div class="d-flex align-center flex-wrap gap-2">
                <v-icon icon="mdi-broom" color="primary" size="22" />
                <span class="text-high-emphasis">无效分享 STRM 清理</span>
                <v-chip v-if="deleteMode === 'immediate'" size="small" variant="tonal" color="info" label>
                  立即删除
                </v-chip>
                <v-chip v-else size="small" variant="tonal" color="warning" label>待确认</v-chip>
              </div>
            </v-col>
            <v-col cols="12" lg="5" class="pa-1 d-flex align-center justify-lg-end gap-2 flex-wrap">
              <v-btn-group variant="outlined" divided rounded density="comfortable"
                class="app-start-top-actions">
                <v-btn prepend-icon="mdi-refresh" :loading="refreshing" @click="refreshAll">
                  刷新
                </v-btn>
                <v-btn prepend-icon="mdi-play" color="primary" :loading="scanLoading" :disabled="!canScan"
                  @click="runScan">
                  立即扫描
                </v-btn>
              </v-btn-group>
            </v-col>
          </v-row>
        </v-card-title>
      </v-card-item>

      <v-divider />

      <div v-if="deleteMode === 'immediate'" class="pa-4">
        <v-alert v-if="lastSummary" type="info" variant="tonal" density="comfortable" class="text-body-2">
          <div class="mb-1">
            上次扫描：无效 <strong>{{ lastSummary.invalid_strm_count ?? 0 }}</strong> 条 · 已删
            <strong>{{ lastSummary.deleted_count ?? 0 }}</strong> 条
          </div>
          <div v-if="lastSummary.message" class="text-caption text-medium-emphasis">{{ lastSummary.message }}</div>
        </v-alert>
        <div v-else class="text-body-2 text-medium-emphasis">暂无扫描摘要，可在插件全页分享同步中配置清理目录并保存后执行「立即扫描」</div>
      </div>

      <div v-else class="pending-cleanup-plugin-ui">
        <div v-if="pendingLoading" class="pa-4">
          <v-skeleton-loader class="ma-2" type="table" />
        </div>
        <div v-else-if="!pendingBatch" class="text-body-2 text-medium-emphasis py-8 text-center px-4">
          暂无待确认批次，可点击「立即扫描」生成
        </div>
        <template v-else>
          <div
            class="px-4 pt-3 pb-2 d-flex flex-column flex-sm-row flex-wrap align-stretch align-sm-center justify-space-between gap-3">
            <div class="text-body-2 min-w-0">
              待删 <strong>{{ pendingPaths.total }}</strong> 条 STRM
              <span class="text-caption text-medium-emphasis d-block mt-1">
                批次 <code class="text-caption">{{ pendingBatch.request_id }}</code>
                · {{ formatTs(pendingBatch.created_at) }}
              </span>
            </div>
            <div class="d-flex flex-wrap gap-2 flex-shrink-0 app-start-batch-actions">
              <v-btn color="error" variant="flat" size="small" prepend-icon="mdi-delete-forever"
                :loading="execId === pendingBatch.request_id" :disabled="!!cancelId"
                class="flex-grow-1 flex-sm-grow-0"
                @click="executeBatch(pendingBatch.request_id)">
                确认删除
              </v-btn>
              <v-btn variant="outlined" size="small" prepend-icon="mdi-close"
                :loading="cancelId === pendingBatch.request_id" :disabled="!!execId"
                class="flex-grow-1 flex-sm-grow-0"
                @click="cancelBatch(pendingBatch.request_id)">
                取消
              </v-btn>
            </div>
          </div>
          <v-data-table :headers="batchPathsHeaders" :items="pendingPathsTableItems" :loading="pendingPaths.loading"
            item-value="rowKey" density="compact" hover hide-default-footer fixed-header class="app-start-data-table"
            :height="pendingPathsTableHeight">
            <template #item.path="{ item }">
              <span class="text-body-2 text-break">{{ item.path }}</span>
            </template>
            <template #no-data>
              <div class="text-body-2 text-medium-emphasis py-8 text-center">
                {{ pendingPaths.loading ? '' : '暂无路径或批次已失效，请刷新' }}
              </div>
            </template>
            <template #loading>
              <v-skeleton-loader class="ma-4" type="table" />
            </template>
          </v-data-table>
          <template v-if="!pendingPaths.loading && pendingPaths.total > 0">
            <v-divider />
            <div
              class="app-start-page-footer d-flex flex-column flex-md-row align-stretch align-md-center justify-space-between gap-2 gap-md-3 px-2 px-md-3 py-2">
              <div class="d-flex align-center justify-center justify-md-start gap-2 app-start-page-footer__select">
                <v-select v-model="pendingPaths.limit" :items="missingPageSizes" item-title="title" item-value="value"
                  density="compact" variant="plain" hide-details class="missing-per-page"
                  @update:model-value="onPendingPathsLimitChange" />
              </div>
              <div
                class="text-caption text-medium-emphasis text-center text-md-center flex-grow-1 order-3 order-md-2 px-1 app-start-page-footer__tip">
                {{ pendingPathsPageTip }}
              </div>
              <div class="app-start-pagination-scroll order-2 order-md-3 w-100 w-md-auto">
                <v-pagination v-model="pendingPaths.page" :length="pendingPathsTotalPages"
                  :total-visible="paginationTotalVisible" :show-first-last-page="paginationShowFirstLast"
                  first-aria-label="第一页" last-aria-label="最后一页" prev-aria-label="上一页" next-aria-label="下一页"
                  :density="paginationDensity" size="small" @update:model-value="loadPendingPathsPage" />
              </div>
            </div>
          </template>
        </template>
      </div>
    </v-card>

    <!-- 无效分享 STRM 关联媒体缺失 -->
    <v-card class="app-start-card" variant="flat" rounded="0">
      <v-card-item class="py-3">
        <v-card-title class="text-subtitle-1 pa-0 font-weight-medium">
          <v-row align="center" class="ma-n1" no-gutters>
            <v-col cols="12" md="8" class="pa-1">
              <div class="d-flex align-center gap-2">
                <v-icon icon="mdi-database-off-outline" color="primary" size="22" />
                <span class="text-high-emphasis">无效分享 STRM 关联媒体缺失</span>
              </div>
            </v-col>
            <v-col cols="12" md="4" class="pa-1 d-flex justify-md-end">
              <v-btn v-if="missingTotal > 0" size="small" variant="tonal" color="error" prepend-icon="mdi-delete-sweep"
                :loading="clearAllLoading" :block="isMobile" @click="clearAllMissing">
                清空全部
              </v-btn>
            </v-col>
          </v-row>
        </v-card-title>
      </v-card-item>

      <v-divider />

      <div v-if="isMobile" class="missing-mobile-list">
        <template v-if="missingLoading">
          <v-skeleton-loader class="ma-4" type="list-item-three-line" />
        </template>
        <template v-else-if="missingItems.length === 0">
          <div class="text-body-2 text-medium-emphasis py-8 text-center">暂无记录</div>
        </template>
        <template v-else>
          <div
            v-for="item in missingItems"
            :key="item.uid"
            class="missing-mobile-card"
          >
            <div class="missing-mobile-card__head">
              <div class="missing-mobile-card__title">
                <div class="text-body-2 font-weight-medium text-break">
                  {{ item.title || '—' }}
                  <span v-if="item.year != null && item.year !== ''" class="text-medium-emphasis">
                    ({{ item.year }})
                  </span>
                </div>
                <div class="text-caption text-medium-emphasis mt-1">
                  <span v-if="item.type">{{ item.type }}</span>
                  <template v-if="item.seasons != null && item.seasons !== ''">
                    <span class="mx-1">·</span>{{ item.seasons }}
                  </template>
                  <template v-if="item.episodes != null && item.episodes !== ''">
                    <span class="mx-1">·</span>{{ item.episodes }}
                  </template>
                </div>
              </div>
              <v-btn icon size="small" variant="text" color="error"
                :loading="deletingUid === item.uid" @click="deleteOneMissing(item.uid)">
                <v-icon size="small">mdi-delete-outline</v-icon>
              </v-btn>
            </div>
            <div class="missing-mobile-card__body text-caption">
              <div class="strm-path-cell text-break">
                <span class="text-medium-emphasis">STRM：</span>{{ item.strm_path || '—' }}
              </div>
              <div class="missing-mobile-card__kv">
                <span><span class="text-medium-emphasis">分享码：</span>{{ item.share_code || '—' }}</span>
                <span><span class="text-medium-emphasis">接收码：</span>{{ item.receive_code || '—' }}</span>
              </div>
              <div v-if="hasAnyExternalId(item)" class="missing-mobile-card__ids">
                <span v-if="hasNativeMediaId(item)">{{ nativeMediaIdLabel(item) }}</span>
                <span v-if="item.tmdbid != null && item.tmdbid !== ''">TMDB: {{ item.tmdbid }}</span>
                <span v-if="item.tvdbid != null && item.tvdbid !== ''">TVDB: {{ item.tvdbid }}</span>
                <span v-if="item.imdbid != null && item.imdbid !== ''">IMDB: {{ item.imdbid }}</span>
                <span v-if="item.doubanid != null && item.doubanid !== ''">豆瓣: {{ item.doubanid }}</span>
              </div>
              <div v-if="item.id != null && item.id !== ''" class="text-medium-emphasis">
                整理记录 #{{ item.id }}
              </div>
            </div>
          </div>
        </template>
      </div>
      <div v-else class="missing-media-scroll">
        <v-data-table :headers="missingHeaders" :items="missingItems" :loading="missingLoading" item-value="uid"
          density="compact" hover hide-default-footer fixed-header class="app-start-data-table missing-media-table"
          :height="missingTableHeight">
          <template #item.share_code="{ item }">
            <span class="text-caption font-weight-medium text-break d-block">{{ item.share_code || '—' }}</span>
          </template>
          <template #item.receive_code="{ item }">
            <span class="text-caption text-medium-emphasis text-break d-block">{{ item.receive_code || '—' }}</span>
          </template>
          <template #item.strm_path="{ item }">
            <span class="strm-path-cell text-caption text-break d-block">{{ item.strm_path }}</span>
          </template>
          <template #item.type="{ item }">
            <span class="text-caption">{{ item.type || '—' }}</span>
          </template>
          <template #item.title="{ item }">
            <span class="text-caption text-break d-block">{{ item.title || '—' }}</span>
          </template>
          <template #item.year="{ item }">
            <span class="text-caption">{{ item.year != null && item.year !== '' ? item.year : '—' }}</span>
          </template>
          <template #item.season_ep="{ item }">
            <div class="text-caption">
              <template v-if="item.seasons != null && item.seasons !== ''">
                <div>{{ item.seasons }}</div>
              </template>
              <template v-if="item.episodes != null && item.episodes !== ''">
                <div class="text-medium-emphasis">{{ item.episodes }}</div>
              </template>
              <span v-if="seasonEpEmpty(item)">—</span>
            </div>
          </template>
          <template #item.external_ids="{ item }">
            <div class="text-caption missing-id-stack">
              <div v-if="hasNativeMediaId(item)">{{ nativeMediaIdLabel(item) }}</div>
              <div v-if="item.tmdbid != null && item.tmdbid !== ''">TMDB: {{ item.tmdbid }}</div>
              <div v-if="item.tvdbid != null && item.tvdbid !== ''">TVDB: {{ item.tvdbid }}</div>
              <div v-if="item.imdbid != null && item.imdbid !== ''">IMDB: {{ item.imdbid }}</div>
              <div v-if="item.doubanid != null && item.doubanid !== ''">豆瓣: {{ item.doubanid }}</div>
              <span v-if="!hasAnyExternalId(item)">—</span>
            </div>
          </template>
          <template #item.history_id="{ item }">
            <span class="text-caption">{{ item.id != null && item.id !== '' ? item.id : '—' }}</span>
          </template>
          <template #item.actions="{ item }">
            <v-btn icon size="small" variant="text" color="error" :loading="deletingUid === item.uid"
              @click="deleteOneMissing(item.uid)">
              <v-icon size="small">mdi-delete-outline</v-icon>
            </v-btn>
          </template>
          <template #no-data>
            <div class="text-body-2 text-medium-emphasis py-8 text-center">暂无记录</div>
          </template>
          <template #loading>
            <v-skeleton-loader class="ma-4" type="table" />
          </template>
        </v-data-table>
      </div>

      <template v-if="!missingLoading && missingTotal > 0">
        <v-divider />
        <div
          class="app-start-page-footer d-flex flex-column flex-md-row align-stretch align-md-center justify-space-between gap-2 gap-md-3 px-2 px-md-3 py-2">
          <div class="d-flex align-center justify-center justify-md-start gap-2 app-start-page-footer__select">
            <v-select v-model="missingLimit" :items="missingPageSizes" item-title="title" item-value="value"
              density="compact" variant="plain" hide-details class="missing-per-page"
              @update:model-value="onMissingLimitChange" />
          </div>
          <div
            class="text-caption text-medium-emphasis text-center text-md-center flex-grow-1 order-3 order-md-2 px-1 app-start-page-footer__tip">
            {{ missingPageTip }}
          </div>
          <div class="app-start-pagination-scroll order-2 order-md-3 w-100 w-md-auto">
            <v-pagination v-model="missingPage" :length="missingTotalPages" :total-visible="paginationTotalVisible"
              :show-first-last-page="paginationShowFirstLast" first-aria-label="第一页" last-aria-label="最后一页"
              prev-aria-label="上一页" next-aria-label="下一页" :density="paginationDensity" size="small"
              @update:model-value="loadMissing" />
          </div>
        </div>
      </template>
    </v-card>

    <Teleport to="body">
      <div
        class="Vue-Toastification__container bottom-right app-page-start-toast-host"
        aria-live="polite"
      >
        <Transition name="Vue-Toastification__bounce">
          <div
            v-if="toast.visible"
            :class="['Vue-Toastification__toast', toastVariantClass, 'bottom-right']"
          >
            <svg
              v-if="toast.variant === 'success'"
              class="Vue-Toastification__icon"
              aria-hidden="true"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 512 512"
            >
              <path
                fill="currentColor"
                d="M504 256c0 136.967-111.033 248-248 248S8 392.967 8 256 119.033 8 256 8s248 111.033 248 248zM227.314 387.314l184-184c6.248-6.248 6.248-16.379 0-22.627l-22.627-22.627c-6.248-6.249-16.379-6.249-22.628 0L216 308.118l-70.059-70.059c-6.248-6.248-16.379-6.248-22.628 0l-22.627 22.627c-6.248 6.248-6.248 16.379 0 22.627l104 104c6.249 6.249 16.379 6.249 22.628.001z"
              />
            </svg>
            <svg
              v-else-if="toast.variant === 'error'"
              class="Vue-Toastification__icon"
              aria-hidden="true"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 576 512"
            >
              <path
                fill="currentColor"
                d="M569.517 440.013C587.975 472.007 564.806 512 527.94 512H48.054c-36.937 0-59.999-40.055-41.577-71.987L246.423 23.985c18.467-32.009 64.72-31.951 83.154 0l239.94 416.028zM288 354c-25.405 0-46 20.595-46 46s20.595 46 46 46 46-20.595 46-46-20.595-46-46-46zm-43.673-165.346l7.418 136c.347 6.364 5.609 11.346 11.982 11.346h48.546c6.373 0 11.635-4.982 11.982-11.346l7.418-136c.375-6.874-5.098-12.654-11.982-12.654h-63.383c-6.884 0-12.356 5.78-11.981 12.654z"
              />
            </svg>
            <svg
              v-else-if="toast.variant === 'warning'"
              class="Vue-Toastification__icon"
              aria-hidden="true"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 512 512"
            >
              <path
                fill="currentColor"
                d="M504 256c0 136.997-111.043 248-248 248S8 392.997 8 256C8 119.083 119.043 8 256 8s248 111.083 248 248zm-248 50c-25.405 0-46 20.595-46 46s20.595 46 46 46 46-20.595 46-46-20.595-46-46-46zm-43.673-165.346l7.418 136c.347 6.364 5.609 11.346 11.982 11.346h48.546c6.373 0 11.635-4.982 11.982-11.346l7.418-136c.375-6.874-5.098-12.654-11.982-12.654h-63.383c-6.884 0-12.356 5.78-11.981 12.654z"
              />
            </svg>
            <svg
              v-else
              class="Vue-Toastification__icon"
              aria-hidden="true"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 512 512"
            >
              <path
                fill="currentColor"
                d="M256 8C119.043 8 8 119.083 8 256c0 136.997 111.043 248 248 248s248-111.003 248-248C504 119.083 392.957 8 256 8zm0 110c23.196 0 42 18.804 42 42s-18.804 42-42 42-42-18.804-42-42 18.804-42 42-42zm56 254c0 6.627-5.373 12-12 12h-88c-6.627 0-12-5.373-12-12v-24c0-6.627 5.373-12 12-12h12v-64h-12c-6.627 0-12-5.373-12-12v-24c0-6.627 5.373-12 12-12h64c6.627 0 12 5.373 12 12v100h12c6.627 0 12 5.373 12 12v24z"
              />
            </svg>
            <div role="alert" class="Vue-Toastification__toast-body">{{ toast.text }}</div>
            <button
              type="button"
              class="Vue-Toastification__close-button"
              aria-label="关闭"
              @click="dismissToast"
            >
              &times;
            </button>
          </div>
        </Transition>
      </div>
    </Teleport>
  </v-container>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue';
import { useDisplay } from 'vuetify';
import { P115_STRM_HELPER_PLUGIN_ID } from '../utils/pluginId.js';
import '../styles/moviepilot-toast.css';

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true,
  },
  pluginId: {
    type: String,
    default: P115_STRM_HELPER_PLUGIN_ID,
  },
});

const display = useDisplay();

/** 窄屏少显页码按钮；xs 仅 5 个槽位，sm/md 以下7，md+ 与桌面一致 */
const paginationTotalVisible = computed(() => {
  if (display.mdAndUp.value) return 11;
  if (display.smAndUp.value) return 7;
  return 5;
});

const paginationShowFirstLast = computed(() => display.smAndUp.value);

const paginationDensity = computed(() => (display.xs.value ? 'compact' : 'comfortable'));

const isMobile = computed(() => display.xs.value);

const refreshing = ref(false);

const toast = reactive({
  visible: false,
  text: '',
  variant: 'success',
});

let toastHideTimer = null;

const toastVariantClass = computed(() => {
  const map = {
    success: 'Vue-Toastification__toast--success',
    error: 'Vue-Toastification__toast--error',
    warning: 'Vue-Toastification__toast--warning',
    info: 'Vue-Toastification__toast--info',
  };
  return map[toast.variant] || map.success;
});

const showSnack = (text, color = 'success', timeout) => {
  const ms = timeout ?? (color === 'error' ? 5000 : 3200);
  toast.text = text;
  toast.variant = color;
  if (toastHideTimer) {
    clearTimeout(toastHideTimer);
    toastHideTimer = null;
  }
  toast.visible = true;
  toastHideTimer = setTimeout(() => {
    toast.visible = false;
    toastHideTimer = null;
  }, ms);
};

const dismissToast = () => {
  if (toastHideTimer) {
    clearTimeout(toastHideTimer);
    toastHideTimer = null;
  }
  toast.visible = false;
};

onBeforeUnmount(() => {
  dismissToast();
});

const initialConfig = reactive({});
const deleteMode = computed(() =>
  (initialConfig.share_strm_cleanup_config && initialConfig.share_strm_cleanup_config.delete_mode) || 'plugin_ui',
);

const canScan = computed(
  () =>
    !!(initialConfig.enabled && initialConfig.cookies && String(initialConfig.cookies).trim()),
);

const pendingLoading = ref(true);
const shareBatches = ref([]);
const lastSummary = ref(null);

const pendingBatch = computed(() =>
  shareBatches.value.length > 0 ? shareBatches.value[0] : null,
);

const missingLoading = ref(true);
const missingItems = ref([]);
const missingTotal = ref(0);
const missingPage = ref(1);
const missingLimit = ref(25);

const missingPageSizes = [
  { title: '15', value: 15 },
  { title: '25', value: 25 },
  { title: '50', value: 50 },
  { title: '100', value: 100 },
];

const missingHeaders = [
  { title: '分享码', key: 'share_code', sortable: false, minWidth: '96px' },
  { title: '接收码', key: 'receive_code', sortable: false, minWidth: '96px' },
  { title: 'STRM 路径', key: 'strm_path', sortable: false, minWidth: '200px' },
  { title: '类型', key: 'type', sortable: false, width: '88px' },
  { title: '标题', key: 'title', sortable: false, minWidth: '140px' },
  { title: '年份', key: 'year', sortable: false, width: '64px' },
  { title: '季 / 集', key: 'season_ep', sortable: false, minWidth: '88px' },
  { title: '外部 ID', key: 'external_ids', sortable: false, minWidth: '112px' },
  { title: '整理记录', key: 'history_id', sortable: false, width: '80px' },
  { title: '', key: 'actions', sortable: false, align: 'end', width: '52px' },
];

const batchPathsHeaders = [
  { title: 'STRM 路径', key: 'path', sortable: false, minWidth: '320px' },
];

const pendingPaths = reactive({
  requestId: '',
  page: 1,
  limit: 25,
  paths: [],
  total: 0,
  loading: false,
});

const missingTableHeight = computed(() => {
  if (display.xs.value) return missingItems.value.length > 8 ? 420 : 300;
  return missingItems.value.length > 12 ? 520 : 360;
});

const missingTotalPages = computed(() =>
  Math.max(1, Math.ceil(missingTotal.value / missingLimit.value)),
);

const missingPageTip = computed(() => {
  const t = missingTotal.value;
  if (t <= 0) return '共 0 条';
  const per = missingLimit.value;
  const page = missingPage.value;
  const from = (page - 1) * per + 1;
  const to = Math.min(page * per, t);
  return `第 ${from}–${to} 条，共 ${t} 条`;
});

const pendingPathsPageTip = computed(() => {
  const t = pendingPaths.total;
  const per = pendingPaths.limit;
  const page = pendingPaths.page;
  if (t <= 0) return '共 0 条';
  const from = (page - 1) * per + 1;
  const to = Math.min(page * per, t);
  return `第 ${from}–${to} 条，共 ${t} 条`;
});

const pendingPathsTotalPages = computed(() =>
  Math.max(1, Math.ceil(pendingPaths.total / pendingPaths.limit)),
);

const pendingPathsTableItems = computed(() =>
  pendingPaths.paths.map((path, i) => ({
    rowKey: `${pendingPaths.page}-${i}`,
    path,
  })),
);

const pendingPathsTableHeight = computed(() => {
  if (display.xs.value) return pendingPaths.paths.length > 8 ? 360 : 260;
  return pendingPaths.paths.length > 12 ? 420 : 320;
});

const scanLoading = ref(false);
const execId = ref(null);
const cancelId = ref(null);
const deletingUid = ref(null);
const clearAllLoading = ref(false);

const formatTs = (t) => {
  if (t == null) return '';
  const d = typeof t === 'number' ? new Date(t * 1000) : new Date(t);
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString();
};

const hasNativeMediaId = (item) =>
  Boolean(item.media_source && String(item.media_id ?? '').trim() && String(item.media_id).trim() !== '0');

const nativeMediaIdLabel = (item) => {
  const labels = {
    themoviedb: 'TMDB', douban: '豆瓣', tvdb: 'TVDB', imdb: 'IMDB',
    bangumi: 'Bangumi', anilist: 'AniList', musicbrainz: 'MusicBrainz',
  };
  return `${labels[item.media_source] || item.media_source}: ${item.media_id}`;
};

const hasAnyExternalId = (item) =>
  hasNativeMediaId(item) ||
  (item.tmdbid != null && item.tmdbid !== '') ||
  (item.tvdbid != null && item.tvdbid !== '') ||
  (item.imdbid != null && item.imdbid !== '') ||
  (item.doubanid != null && item.doubanid !== '');

const seasonEpEmpty = (item) =>
  (item.seasons == null || item.seasons === '') &&
  (item.episodes == null || item.episodes === '');

const loadConfig = async () => {
  try {
    const configData = await props.api.get(`plugin/${props.pluginId}/get_config`);
    if (configData && typeof configData === 'object') {
      Object.assign(initialConfig, configData);
    }
  } catch (e) {
    console.error(e);
  }
};

const loadPendingPathsPage = async ({ soft = false } = {}) => {
  if (!pendingPaths.requestId) return;
  if (!soft || pendingPaths.paths.length === 0) {
    pendingPaths.loading = true;
  }
  try {
    const qs = new URLSearchParams({
      request_id: pendingPaths.requestId,
      page: String(pendingPaths.page),
      limit: String(pendingPaths.limit),
    });
    const res = await props.api.get(
      `plugin/${props.pluginId}/share_strm_cleanup_batch_paths?${qs.toString()}`,
    );
    if (res && res.code === 0 && res.data) {
      pendingPaths.paths = Array.isArray(res.data.paths) ? res.data.paths : [];
      pendingPaths.total = Number(res.data.total) || 0;
    } else {
      pendingPaths.paths = [];
      if (res?.msg) {
        showSnack(res.msg, 'error');
      }
    }
  } catch (e) {
    pendingPaths.paths = [];
    showSnack(e.message || '加载路径失败', 'error');
  } finally {
    pendingPaths.loading = false;
  }
};

const loadPending = async ({ soft = false } = {}) => {
  if (!soft || shareBatches.value.length === 0) {
    pendingLoading.value = true;
  }
  try {
    const res = await props.api.get(`plugin/${props.pluginId}/share_strm_cleanup_pending`);
    if (res && res.code === 0 && res.data && Array.isArray(res.data.batches)) {
      shareBatches.value = res.data.batches;
    } else {
      shareBatches.value = [];
    }
    if (shareBatches.value.length > 0) {
      const b = shareBatches.value[0];
      const prevId = pendingPaths.requestId;
      pendingPaths.requestId = b.request_id;
      if (prevId !== b.request_id) {
        pendingPaths.page = 1;
      }
      pendingPaths.limit = pendingPaths.limit || 25;
      await loadPendingPathsPage({ soft });
    } else {
      pendingPaths.requestId = '';
      pendingPaths.paths = [];
      pendingPaths.total = 0;
      pendingPaths.loading = false;
    }
  } catch (e) {
    console.error(e);
    shareBatches.value = [];
    pendingPaths.requestId = '';
    pendingPaths.paths = [];
    pendingPaths.total = 0;
    pendingPaths.loading = false;
  } finally {
    pendingLoading.value = false;
  }
};

const loadSummary = async () => {
  try {
    const res = await props.api.get(`plugin/${props.pluginId}/share_strm_cleanup_last_summary`);
    if (res && res.code === 0 && res.data) {
      lastSummary.value = res.data.summary || null;
    } else {
      lastSummary.value = null;
    }
  } catch (e) {
    lastSummary.value = null;
  }
};

const onPendingPathsLimitChange = () => {
  pendingPaths.page = 1;
  loadPendingPathsPage();
};

const loadMissing = async ({ soft = false } = {}) => {
  if (!soft || missingItems.value.length === 0) {
    missingLoading.value = true;
  }
  try {
    const qs = new URLSearchParams({
      page: String(missingPage.value),
      limit: String(missingLimit.value),
    });
    const res = await props.api.get(
      `plugin/${props.pluginId}/share_strm_missing_media_list?${qs.toString()}`,
    );
    if (res && res.code === 0 && res.data) {
      missingItems.value = Array.isArray(res.data.items) ? res.data.items : [];
      missingTotal.value = res.data.total || 0;
    } else {
      missingItems.value = [];
      missingTotal.value = 0;
    }
  } catch (e) {
    missingItems.value = [];
    missingTotal.value = 0;
  } finally {
    missingLoading.value = false;
  }
};

const onMissingLimitChange = () => {
  missingPage.value = 1;
  loadMissing();
};

const refreshAll = async () => {
  refreshing.value = true;
  try {
    await loadConfig();
    await Promise.all([
      loadPending({ soft: true }),
      loadSummary(),
      loadMissing({ soft: true }),
    ]);
    showSnack('已刷新', 'success');
  } catch (e) {
    showSnack(e.message || '刷新失败', 'error');
  } finally {
    refreshing.value = false;
  }
};

const runScan = async () => {
  scanLoading.value = true;
  try {
    const res = await props.api.post(`plugin/${props.pluginId}/share_strm_cleanup_scan`);
    if (res && res.code === 0) {
      showSnack(res.msg || '扫描已启动', 'success');
      setTimeout(() => {
        loadSummary();
        loadPending();
      }, 1500);
    } else {
      throw new Error(res?.msg || '启动失败');
    }
  } catch (e) {
    showSnack(e.message || '启动扫描失败', 'error');
  } finally {
    scanLoading.value = false;
  }
};

const executeBatch = async (requestId) => {
  execId.value = requestId;
  try {
    const res = await props.api.post(`plugin/${props.pluginId}/share_strm_cleanup_execute`, {
      request_id: requestId,
    });
    if (res && res.code === 0) {
      showSnack(res.msg || '已执行', 'success');
      await loadPending();
    } else {
      throw new Error(res?.msg || '执行失败');
    }
  } catch (e) {
    showSnack(e.message || '执行失败', 'error');
  } finally {
    execId.value = null;
  }
};

const cancelBatch = async (requestId) => {
  cancelId.value = requestId;
  try {
    const res = await props.api.post(`plugin/${props.pluginId}/share_strm_cleanup_cancel`, {
      request_id: requestId,
    });
    if (res && res.code === 0) {
      showSnack(res.msg || '已取消', 'success');
      await loadPending();
    } else {
      throw new Error(res?.msg || '取消失败');
    }
  } catch (e) {
    showSnack(e.message || '取消失败', 'error');
  } finally {
    cancelId.value = null;
  }
};

const deleteOneMissing = async (uid) => {
  deletingUid.value = uid;
  try {
    const res = await props.api.post(`plugin/${props.pluginId}/share_strm_missing_media_clear`, {
      uid,
      clear_all: false,
    });
    if (res && res.code === 0) {
      await loadMissing();
    } else {
      throw new Error(res?.msg || '删除失败');
    }
  } catch (e) {
    showSnack(e.message || '删除失败', 'error');
  } finally {
    deletingUid.value = null;
  }
};

const clearAllMissing = async () => {
  if (!confirm('确定清空全部缺失媒体记录？')) return;
  clearAllLoading.value = true;
  try {
    const res = await props.api.post(`plugin/${props.pluginId}/share_strm_missing_media_clear`, {
      clear_all: true,
    });
    if (res && res.code === 0) {
      missingPage.value = 1;
      await loadMissing();
      showSnack(res.msg || '已清空', 'success');
    } else {
      throw new Error(res?.msg || '清空失败');
    }
  } catch (e) {
    showSnack(e.message || '清空失败', 'error');
  } finally {
    clearAllLoading.value = false;
  }
};

onMounted(async () => {
  await loadConfig();
  await Promise.all([loadPending(), loadSummary(), loadMissing()]);
});
</script>

<style scoped>
.app-start {
  max-inline-size: none;
  inline-size: 100%;
}

.app-start-card {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  background: rgb(var(--v-theme-surface));
}

.strm-path-cell {
  max-width: min(48rem, 70vw);
  vertical-align: top;
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.35;
}

.missing-media-scroll {
  overflow-x: auto;
  max-inline-size: 100%;
}

.missing-media-table {
  min-inline-size: 800px;
}

.missing-id-stack {
  line-height: 1.35;
}

.pending-cleanup-plugin-ui {
  min-inline-size: 0;
}

.missing-per-page {
  flex: 0 1 auto;
  inline-size: 8.5rem;
  max-inline-size: 8.5rem;
  min-inline-size: 0;
}

.missing-per-page :deep(.v-field) {
  padding-inline-start: 4px;
}

/* 分页底栏：窄屏不挤出视口，分页可横向滑动 */
.app-start-page-footer {
  min-inline-size: 0;
  box-sizing: border-box;
}

.app-start-page-footer__tip {
  word-break: break-word;
  line-height: 1.35;
}

.app-start-pagination-scroll {
  min-inline-size: 0;
  max-inline-size: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  display: flex;
  justify-content: center;
  padding-block: 2px;
  box-sizing: border-box;
}

.app-start-pagination-scroll :deep(.v-pagination) {
  flex: 0 0 auto;
}

.app-start-pagination-scroll :deep(.v-pagination__list) {
  flex-wrap: nowrap;
}

@media (max-width: 959px) {
  .app-start-page-footer__select {
    inline-size: 100%;
    max-inline-size: 12rem;
    margin-inline: auto;
  }

  .app-start-page-footer__select .missing-per-page {
    flex: 1 1 auto;
    max-inline-size: none;
  }
}

/* 与媒体整理 history 页表格视觉对齐 */
.app-start-data-table :deep(.v-table__wrapper) {
  border-radius: 0;
}

.app-start-data-table :deep(.v-table th) {
  white-space: nowrap;
  font-weight: 600;
  font-size: 0.75rem;
}

.app-start-data-table :deep(.v-data-table__td) {
  vertical-align: top;
}

/* 手机端缺失媒体卡片列表 */
.missing-mobile-list {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.missing-mobile-card {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  border-radius: 6px;
  padding: 10px 12px;
  background: rgb(var(--v-theme-surface));
}

.missing-mobile-card__head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.missing-mobile-card__title {
  flex: 1 1 auto;
  min-inline-size: 0;
}

.missing-mobile-card__body {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  line-height: 1.45;
}

.missing-mobile-card__kv {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.missing-mobile-card__ids {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  color: rgb(var(--v-theme-on-surface));
}

/* 手机端顶部操作按钮组全宽 */
@media (max-width: 599px) {
  .app-start-top-actions {
    inline-size: 100%;
  }

  .app-start-top-actions :deep(.v-btn) {
    flex: 1 1 0;
  }

  .app-start-batch-actions {
    inline-size: 100%;
  }
}
</style>
