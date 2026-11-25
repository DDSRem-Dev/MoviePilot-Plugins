<template>
  <v-container
    fluid
    class="p115-app-start p115-scope pa-2 pa-sm-4"
    :data-p115-theme="themeMode"
    :data-p115-transparent="isTransparent ? 'true' : 'false'"
  >
    <!-- Top Page Header -->
    <header class="p115-start-header mb-4">
      <div class="d-flex align-center gap-3 min-w-0">
        <div class="p115-squircle-icon">
          <v-icon icon="mdi-view-dashboard-outline" size="21" />
        </div>
        <div class="min-w-0">
          <div class="p115-header-title">
            <span>115 助手仪表盘</span>
            <span
              class="p115-badge"
              :class="deleteMode === 'immediate' ? 'p115-badge--blue' : 'p115-badge--amber'"
            >
              <span class="p115-badge-dot" />
              {{ deleteMode === 'immediate' ? '立即删除模式' : '界面待确认模式' }}
            </span>
          </div>
          <div class="p115-header-subtitle">
            无效分享 STRM 清理审查与关联缺失媒体追踪中心
          </div>
        </div>
      </div>

      <div class="p115-start-top-actions">
        <button
          type="button"
          class="p115-btn p115-btn--subtle p115-btn--sm"
          :disabled="refreshing"
          @click="refreshAll"
        >
          <v-progress-circular v-if="refreshing" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-refresh" />
          <span>刷新</span>
        </button>
        <button
          type="button"
          class="p115-btn p115-btn--primary p115-btn--sm"
          :disabled="!canScan || scanLoading"
          @click="runScan"
        >
          <v-progress-circular v-if="scanLoading" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-radar" />
          <span>立即扫描</span>
        </button>
      </div>
    </header>

    <!-- Card 1: 无效分享 STRM 清理 -->
    <AppleBentoCard title="无效分享 STRM 清理" icon="mdi-broom" class="mb-4" flush>
      <template #badge>
        <span
          class="p115-badge"
          :class="deleteMode === 'immediate' ? 'p115-badge--blue' : 'p115-badge--amber'"
        >
          {{ deleteMode === 'immediate' ? '立即删除' : '待确认' }}
        </span>
      </template>

      <div v-if="deleteMode === 'immediate'" class="pa-4">
        <div v-if="lastSummary" class="p115-callout p115-callout--info">
          <v-icon size="18" color="primary" icon="mdi-check-circle-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div class="p115-tabular">
              上次扫描：无效 <strong>{{ lastSummary.invalid_strm_count ?? 0 }}</strong> 条 · 已删
              <strong>{{ lastSummary.deleted_count ?? 0 }}</strong> 条
            </div>
            <div v-if="lastSummary.message" class="text-caption opacity-75 mt-0.5">{{ lastSummary.message }}</div>
          </div>
        </div>
        <div v-else class="text-body-2 opacity-70 py-2">
          暂无扫描摘要，可在插件全页分享同步中配置清理目录并保存后执行「立即扫描」
        </div>
      </div>

      <div v-else class="p115-pending-wrap">
        <div v-if="pendingLoading" class="pa-4">
          <v-skeleton-loader type="table-row@4" class="bg-transparent" />
        </div>
        <div v-else-if="!pendingBatch" class="text-body-2 opacity-70 py-8 text-center px-4">
          暂无待确认批次，可点击右上角「立即扫描」生成
        </div>
        <template v-else>
          <div class="px-4 py-3 d-flex flex-column flex-sm-row align-stretch align-sm-center justify-space-between gap-3">
            <div class="text-body-2 min-w-0">
              待删 <strong class="p115-tabular">{{ pendingPaths.total }}</strong> 条 STRM
              <span class="text-caption opacity-70 d-block mt-0.5 p115-tabular">
                批次 <code class="p115-mono">{{ pendingBatch.request_id }}</code> · {{ formatTs(pendingBatch.created_at) }}
              </span>
            </div>
            <div class="d-flex flex-wrap gap-2 flex-shrink-0">
              <button
                type="button"
                class="p115-btn p115-btn--danger p115-btn--sm"
                :disabled="!!cancelId || execId === pendingBatch.request_id"
                @click="executeBatch(pendingBatch.request_id)"
              >
                <v-progress-circular v-if="execId === pendingBatch.request_id" indeterminate size="13" width="2" />
                <v-icon v-else size="15" icon="mdi-delete-forever-outline" />
                <span>确认删除</span>
              </button>
              <button
                type="button"
                class="p115-btn p115-btn--subtle p115-btn--sm"
                :disabled="!!execId || cancelId === pendingBatch.request_id"
                @click="cancelBatch(pendingBatch.request_id)"
              >
                <v-progress-circular v-if="cancelId === pendingBatch.request_id" indeterminate size="13" width="2" />
                <v-icon v-else size="15" icon="mdi-close" />
                <span>取消</span>
              </button>
            </div>
          </div>

          <v-data-table
            :headers="batchPathsHeaders"
            :items="pendingPathsTableItems"
            :loading="pendingPaths.loading"
            item-value="rowKey"
            density="compact"
            hover
            hide-default-footer
            fixed-header
            class="bg-transparent"
            :height="pendingPathsTableHeight"
          >
            <template #item.path="{ item }">
              <span class="text-caption p115-mono text-break">{{ item.path }}</span>
            </template>
            <template #no-data>
              <div class="text-body-2 opacity-70 py-8 text-center">
                {{ pendingPaths.loading ? '' : '暂无路径或批次已失效，请刷新' }}
              </div>
            </template>
          </v-data-table>

          <div v-if="!pendingPaths.loading && pendingPaths.total > 0" class="p115-table-footer">
            <div class="p115-per-page-box">
              <v-select
                v-model="pendingPaths.limit"
                :items="missingPageSizes"
                item-title="title"
                item-value="value"
                density="compact"
                variant="outlined"
                hide-details
                @update:model-value="onPendingPathsLimitChange"
              />
            </div>
            <div class="text-caption opacity-70 p115-tabular text-center">
              {{ pendingPathsPageTip }}
            </div>
            <div class="p115-pagination-scroll">
              <v-pagination
                v-model="pendingPaths.page"
                :length="pendingPathsTotalPages"
                :total-visible="paginationTotalVisible"
                :show-first-last-page="paginationShowFirstLast"
                first-aria-label="第一页"
                last-aria-label="最后一页"
                prev-aria-label="上一页"
                next-aria-label="下一页"
                :density="paginationDensity"
                size="small"
                @update:model-value="loadPendingPathsPage"
              />
            </div>
          </div>
        </template>
      </div>
    </AppleBentoCard>

    <!-- Card 2: 无效分享 STRM 关联媒体缺失 -->
    <AppleBentoCard title="无效分享 STRM 关联媒体缺失" icon="mdi-database-off-outline" flush>
      <template #badge>
        <span v-if="!missingLoading" class="p115-badge p115-badge--pink p115-tabular">
          {{ missingTotal }} 条
        </span>
      </template>
      <template #action>
        <button
          v-if="missingTotal > 0"
          type="button"
          class="p115-btn p115-btn--danger p115-btn--sm"
          :disabled="clearAllLoading"
          @click="clearAllConfirmDialog = true"
        >
          <v-icon size="14" icon="mdi-delete-sweep-outline" />
          <span>清空全部</span>
        </button>
      </template>

      <!-- Mobile Card View -->
      <div v-if="isMobile" class="p115-mobile-list">
        <template v-if="missingLoading">
          <v-skeleton-loader class="ma-3 bg-transparent" type="list-item-three-line@3" />
        </template>
        <template v-else-if="missingItems.length === 0">
          <div class="text-body-2 opacity-70 py-8 text-center">暂无记录</div>
        </template>
        <template v-else>
          <div v-for="item in missingItems" :key="item.uid" class="p115-mobile-card">
            <div class="d-flex align-start justify-space-between gap-2">
              <div class="min-w-0 flex-grow-1">
                <div class="text-body-2 font-weight-bold text-break">
                  {{ item.title || '—' }}
                  <span v-if="item.year != null && item.year !== ''" class="opacity-70 p115-tabular">
                    ({{ item.year }})
                  </span>
                </div>
                <div class="d-flex flex-wrap align-center gap-1.5 mt-1">
                  <span v-if="item.type" class="p115-badge p115-badge--blue">{{ item.type }}</span>
                  <span v-if="item.seasons != null && item.seasons !== ''" class="text-caption opacity-75">
                    {{ item.seasons }}
                  </span>
                  <span v-if="item.episodes != null && item.episodes !== ''" class="text-caption opacity-75">
                    · {{ item.episodes }}
                  </span>
                </div>
              </div>
              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger flex-shrink-0"
                :disabled="deletingUid === item.uid"
                @click="deleteOneMissing(item.uid)"
              >
                <v-progress-circular v-if="deletingUid === item.uid" indeterminate size="13" width="2" />
                <v-icon v-else size="15" icon="mdi-trash-can-outline" />
              </button>
            </div>

            <div class="mt-2 d-flex flex-column gap-1 text-caption">
              <div class="p115-path-cell p115-mono">
                <span class="opacity-65">STRM：</span>{{ item.strm_path || '—' }}
              </div>
              <div class="d-flex flex-wrap gap-3 p115-mono">
                <span><span class="opacity-65">分享码：</span>{{ item.share_code || '—' }}</span>
                <span><span class="opacity-65">接收码：</span>{{ item.receive_code || '—' }}</span>
              </div>
              <div v-if="hasAnyExternalId(item)" class="d-flex flex-wrap gap-2 p115-tabular">
                <span v-if="hasNativeMediaId(item)" class="p115-badge p115-badge--neutral">{{ nativeMediaIdLabel(item) }}</span>
                <span v-if="item.tmdbid != null && item.tmdbid !== ''" class="p115-badge p115-badge--neutral">TMDB: {{ item.tmdbid }}</span>
                <span v-if="item.tvdbid != null && item.tvdbid !== ''" class="p115-badge p115-badge--neutral">TVDB: {{ item.tvdbid }}</span>
                <span v-if="item.imdbid != null && item.imdbid !== ''" class="p115-badge p115-badge--neutral">IMDB: {{ item.imdbid }}</span>
                <span v-if="item.doubanid != null && item.doubanid !== ''" class="p115-badge p115-badge--neutral">豆瓣: {{ item.doubanid }}</span>
              </div>
              <div v-if="item.id != null && item.id !== ''" class="opacity-65 p115-tabular">
                整理记录 #{{ item.id }}
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Desktop Table View -->
      <div v-else class="p115-missing-scroll">
        <v-data-table
          :headers="missingHeaders"
          :items="missingItems"
          :loading="missingLoading"
          item-value="uid"
          density="compact"
          hover
          hide-default-footer
          fixed-header
          class="p115-missing-table bg-transparent"
          :height="missingTableHeight"
        >
          <template #item.share_code="{ item }">
            <span class="text-caption font-weight-medium p115-mono text-break d-block">{{ item.share_code || '—' }}</span>
          </template>
          <template #item.receive_code="{ item }">
            <span class="text-caption opacity-75 p115-mono text-break d-block">{{ item.receive_code || '—' }}</span>
          </template>
          <template #item.strm_path="{ item }">
            <span class="p115-path-cell text-caption p115-mono text-break d-block">{{ item.strm_path }}</span>
          </template>
          <template #item.type="{ item }">
            <span v-if="item.type" class="p115-badge p115-badge--blue">{{ item.type }}</span>
            <span v-else class="text-caption">—</span>
          </template>
          <template #item.title="{ item }">
            <span class="text-caption font-weight-medium text-break d-block">{{ item.title || '—' }}</span>
          </template>
          <template #item.year="{ item }">
            <span class="text-caption p115-tabular">{{ item.year != null && item.year !== '' ? item.year : '—' }}</span>
          </template>
          <template #item.season_ep="{ item }">
            <div class="text-caption p115-tabular">
              <div v-if="item.seasons != null && item.seasons !== ''">{{ item.seasons }}</div>
              <div v-if="item.episodes != null && item.episodes !== ''" class="opacity-70">{{ item.episodes }}</div>
              <span v-if="seasonEpEmpty(item)">—</span>
            </div>
          </template>
          <template #item.external_ids="{ item }">
            <div class="text-caption p115-tabular p115-id-stack">
              <div v-if="hasNativeMediaId(item)">{{ nativeMediaIdLabel(item) }}</div>
              <div v-if="item.tmdbid != null && item.tmdbid !== ''">TMDB: {{ item.tmdbid }}</div>
              <div v-if="item.tvdbid != null && item.tvdbid !== ''">TVDB: {{ item.tvdbid }}</div>
              <div v-if="item.imdbid != null && item.imdbid !== ''">IMDB: {{ item.imdbid }}</div>
              <div v-if="item.doubanid != null && item.doubanid !== ''">豆瓣: {{ item.doubanid }}</div>
              <span v-if="!hasAnyExternalId(item)">—</span>
            </div>
          </template>
          <template #item.history_id="{ item }">
            <span class="text-caption p115-tabular">{{ item.id != null && item.id !== '' ? item.id : '—' }}</span>
          </template>
          <template #item.actions="{ item }">
            <button
              type="button"
              class="p115-btn p115-btn--icon p115-btn--danger"
              :disabled="deletingUid === item.uid"
              @click="deleteOneMissing(item.uid)"
            >
              <v-progress-circular v-if="deletingUid === item.uid" indeterminate size="13" width="2" />
              <v-icon v-else size="15" icon="mdi-trash-can-outline" />
            </button>
          </template>
          <template #no-data>
            <div class="text-body-2 opacity-70 py-8 text-center">暂无记录</div>
          </template>
        </v-data-table>
      </div>

      <div v-if="!missingLoading && missingTotal > 0" class="p115-table-footer">
        <div class="p115-per-page-box">
          <v-select
            v-model="missingLimit"
            :items="missingPageSizes"
            item-title="title"
            item-value="value"
            density="compact"
            variant="outlined"
            hide-details
            @update:model-value="onMissingLimitChange"
          />
        </div>
        <div class="text-caption opacity-70 p115-tabular text-center">
          {{ missingPageTip }}
        </div>
        <div class="p115-pagination-scroll">
          <v-pagination
            v-model="missingPage"
            :length="missingTotalPages"
            :total-visible="paginationTotalVisible"
            :show-first-last-page="paginationShowFirstLast"
            first-aria-label="第一页"
            last-aria-label="最后一页"
            prev-aria-label="上一页"
            next-aria-label="下一页"
            :density="paginationDensity"
            size="small"
            @update:model-value="loadMissing"
          />
        </div>
      </div>
    </AppleBentoCard>

    <!-- Non-blocking Apple Confirmation Sheet (Replaces native window.confirm) -->
    <v-dialog v-model="clearAllConfirmDialog" max-width="440" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="error" icon="mdi-delete-sweep-outline" />
            <span>清空缺失媒体记录</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div class="mb-2">
            确定清空全部 <strong class="p115-tabular">{{ missingTotal }}</strong> 条缺失媒体记录吗？
          </div>
          <div class="p115-callout p115-callout--error">
            <v-icon size="16" color="error" icon="mdi-alert-outline" />
            <span>清空后将无法找回历史缺失记录</span>
          </div>
        </div>
        <div class="p115-sheet-footer justify-end">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            :disabled="clearAllLoading"
            @click="clearAllConfirmDialog = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger p115-btn--sm"
            :disabled="clearAllLoading"
            @click="confirmClearAllMissing"
          >
            <v-progress-circular v-if="clearAllLoading" indeterminate size="13" width="2" />
            <span>确认清空</span>
          </button>
        </div>
      </v-card>
    </v-dialog>

    <!-- MoviePilot Host Toast Notification -->
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
import '../styles/apple-theme.css';
import '../styles/moviepilot-toast.css';
import { P115_STRM_HELPER_PLUGIN_ID } from '../utils/pluginId.js';
import { useThemeAdapter } from './composables/useThemeAdapter.js';
import AppleBentoCard from './ui/AppleBentoCard.vue';

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

const { isTransparent, themeMode, dialogContentClass } = useThemeAdapter();
const display = useDisplay();

const paginationTotalVisible = computed(() => {
  if (display.mdAndUp.value) return 11;
  if (display.smAndUp.value) return 7;
  return 5;
});

const paginationShowFirstLast = computed(() => display.smAndUp.value);
const paginationDensity = computed(() => (display.xs.value ? 'compact' : 'comfortable'));
const isMobile = computed(() => display.xs.value);

const refreshing = ref(false);
const clearAllConfirmDialog = ref(false);

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
const deleteMode = computed(
  () => (initialConfig.share_strm_cleanup_config && initialConfig.share_strm_cleanup_config.delete_mode) || 'plugin_ui',
);

const canScan = computed(
  () => !!(initialConfig.enabled && initialConfig.cookies && String(initialConfig.cookies).trim()),
);

const pendingLoading = ref(true);
const shareBatches = ref([]);
const lastSummary = ref(null);

const pendingBatch = computed(() => (shareBatches.value.length > 0 ? shareBatches.value[0] : null));

const missingLoading = ref(true);
const missingItems = ref([]);
const missingTotal = ref(0);
const missingPage = ref(1);
const missingLimit = ref(25);

const missingPageSizes = [
  { title: '15 / 页', value: 15 },
  { title: '25 / 页', value: 25 },
  { title: '50 / 页', value: 50 },
  { title: '100 / 页', value: 100 },
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

const batchPathsHeaders = [{ title: 'STRM 路径', key: 'path', sortable: false }];

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

const missingTotalPages = computed(() => Math.max(1, Math.ceil(missingTotal.value / missingLimit.value)));

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
    themoviedb: 'TMDB',
    douban: '豆瓣',
    tvdb: 'TVDB',
    imdb: 'IMDB',
    bangumi: 'Bangumi',
    anilist: 'AniList',
    musicbrainz: 'MusicBrainz',
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
  (item.seasons == null || item.seasons === '') && (item.episodes == null || item.episodes === '');

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
    const res = await props.api.get(`plugin/${props.pluginId}/share_strm_cleanup_batch_paths?${qs.toString()}`);
    if (res && res.code === 0 && res.data) {
      pendingPaths.paths = Array.isArray(res.data.paths) ? res.data.paths : [];
      pendingPaths.total = Number(res.data.total) || 0;
    } else {
      pendingPaths.paths = [];
      if (res?.msg) showSnack(res.msg, 'error');
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
      if (prevId !== b.request_id) pendingPaths.page = 1;
      pendingPaths.limit = pendingPaths.limit || 25;
      await loadPendingPathsPage({ soft });
    } else {
      pendingPaths.requestId = '';
      pendingPaths.paths = [];
      pendingPaths.total = 0;
      pendingPaths.loading = false;
    }
  } catch {
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
  } catch {
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
    const res = await props.api.get(`plugin/${props.pluginId}/share_strm_missing_media_list?${qs.toString()}`);
    if (res && res.code === 0 && res.data) {
      missingItems.value = Array.isArray(res.data.items) ? res.data.items : [];
      missingTotal.value = res.data.total || 0;
    } else {
      missingItems.value = [];
      missingTotal.value = 0;
    }
  } catch {
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
    await Promise.all([loadPending({ soft: true }), loadSummary(), loadMissing({ soft: true })]);
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

const confirmClearAllMissing = async () => {
  clearAllConfirmDialog.value = false;
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
.p115-app-start {
  max-inline-size: none;
  inline-size: 100%;
}

.p115-start-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 18px;
  border-radius: 18px;
  background: var(--p115-bg-window);
  backdrop-filter: blur(var(--p115-blur-chrome)) saturate(170%);
  -webkit-backdrop-filter: blur(var(--p115-blur-chrome)) saturate(170%);
  border: 1px solid var(--p115-border-hairline);
  box-shadow: var(--p115-shadow-card);
}

.p115-start-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.p115-pending-wrap {
  min-inline-size: 0;
}

.p115-path-cell {
  max-width: min(46rem, 70vw);
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.4;
}

.p115-missing-scroll {
  overflow-x: auto;
  max-inline-size: 100%;
}

.p115-missing-table {
  min-inline-size: 820px;
}

.p115-id-stack {
  line-height: 1.4;
}

.p115-table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 16px;
  border-top: 1px solid var(--p115-border-hairline);
  background: var(--p115-bg-floating);
}

.p115-per-page-box {
  inline-size: 128px;
  flex-shrink: 0;
}

.p115-pagination-scroll {
  min-inline-size: 0;
  max-inline-size: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  display: flex;
  justify-content: center;
}

/* Mobile Card Fallback */
.p115-mobile-list {
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.p115-mobile-card {
  padding: 12px 14px;
  border-radius: 13px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
}

@media (max-width: 600px) {
  .p115-start-header {
    padding: 12px 14px;
  }

  .p115-start-top-actions {
    width: 100%;
  }

  .p115-start-top-actions > button {
    flex: 1 1 0;
  }

  .p115-table-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .p115-per-page-box {
    inline-size: 100%;
  }
}
</style>
