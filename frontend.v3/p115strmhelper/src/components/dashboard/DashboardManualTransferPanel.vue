<template>
  <div class="dashboard-widget dashboard-widget--transfer-mini">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card dashboard-grid-fill">
      <!-- Unified Apple Widget Header -->
      <div v-if="config?.attrs?.title || config?.attrs?.subtitle" class="p115-dash-header">
        <div class="p115-dash-header-left">
          <div class="p115-dash-icon">
            <v-icon icon="mdi-folder-cog-outline" size="18" />
          </div>
          <div class="p115-dash-titles">
            <div class="p115-dash-title-row">
              <span>{{ config?.attrs?.title || "手动网盘整理" }}</span>
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
            :disabled="transferConfigLoading"
            title="刷新配置"
            @click="loadTransferConfig"
          >
            <v-progress-circular v-if="transferConfigLoading" indeterminate size="13" width="2" />
            <v-icon v-else size="16" icon="mdi-refresh" />
          </button>
        </div>
      </div>

      <!-- Widget Body -->
      <div class="p115-dash-body p115-dash-body--auto justify-center">
        <div v-if="transferConfigLoading && !transferConfigLoaded" class="text-center py-4">
          <v-progress-circular indeterminate color="primary" size="30" />
        </div>
        <template v-else-if="transferConfigLoaded">
          <div v-if="!panTransferEnabled" class="p115-callout p115-callout--warn">
            <v-icon size="16" color="warning" icon="mdi-alert-outline" />
            <span>请先在插件设置中开启「网盘整理」</span>
          </div>
          <div v-else-if="panTransferSelectItems.length === 0" class="p115-callout p115-callout--info">
            <v-icon size="16" color="primary" icon="mdi-information-outline" />
            <span>请先在插件设置中配置「网盘整理目录」</span>
          </div>
          <div v-else class="d-flex flex-column gap-3">
            <v-select
              v-model="selectedManualPath"
              :items="panTransferSelectItems"
              item-title="title"
              item-value="value"
              label="选择待整理目录"
              density="compact"
              hide-details
              variant="outlined"
              class="dashboard-grid-no-drag"
            />
            <button
              type="button"
              class="p115-btn p115-btn--primary w-100 dashboard-grid-no-drag"
              :disabled="!selectedManualPath"
              @click="openManualTransferDialog"
            >
              <v-icon size="16" icon="mdi-play-circle-outline" />
              <span>执行整理</span>
            </button>
          </div>
        </template>
      </div>

      <!-- Refresh Footer -->
      <div v-if="allowRefresh" class="p115-dash-footer">
        <span class="text-caption opacity-65 p115-tabular">{{ lastRefreshedTimeDisplayTransfer }}</span>
        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon dashboard-grid-no-drag"
          :disabled="transferConfigLoading"
          title="刷新配置"
          @click="loadTransferConfig"
        >
          <v-progress-circular v-if="transferConfigLoading" indeterminate size="13" width="2" />
          <v-icon v-else size="15" icon="mdi-refresh" />
        </button>
      </div>
    </v-card>

    <v-dialog v-model="manualTransferDialog.show" max-width="480" persistent :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="primary" icon="mdi-play-circle-outline" />
            <span>手动整理确认</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
            <div class="text-body-2 mb-3">确定要手动整理以下目录吗？</div>
            <div class="p115-callout p115-callout--info">
              <v-icon size="16" color="primary" icon="mdi-folder-network-outline" />
              <div><strong>路径：</strong><span class="p115-mono">{{ manualTransferDialog.path }}</span></div>
            </div>
          </div>
          <div v-else-if="manualTransferDialog.loading" class="d-flex flex-column align-center py-4">
            <v-progress-circular indeterminate color="primary" size="42" class="mb-3" />
            <div class="text-body-2 opacity-75">正在启动整理任务...</div>
          </div>
          <div v-else-if="manualTransferDialog.result">
            <div
              class="p115-callout"
              :class="manualTransferDialog.result.type === 'success' ? 'p115-callout--success' : 'p115-callout--error'"
            >
              <v-icon
                size="18"
                :color="manualTransferDialog.result.type === 'success' ? 'success' : 'error'"
                :icon="manualTransferDialog.result.type === 'success' ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'"
              />
              <div>
                <div class="font-weight-bold mb-1">{{ manualTransferDialog.result.title }}</div>
                <div>{{ manualTransferDialog.result.message }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="p115-sheet-footer justify-end">
          <template v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
            <button
              type="button"
              class="p115-btn p115-btn--subtle p115-btn--sm dashboard-grid-no-drag"
              @click="closeManualTransferDialog"
            >
              取消
            </button>
            <button
              type="button"
              class="p115-btn p115-btn--primary p115-btn--sm dashboard-grid-no-drag"
              @click="confirmManualTransfer"
            >
              确认执行
            </button>
          </template>
          <button
            v-else
            type="button"
            class="p115-btn p115-btn--primary p115-btn--sm dashboard-grid-no-drag"
            @click="closeManualTransferDialog"
          >
            关闭
          </button>
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue';
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
});

const { dialogContentClass } = useThemeAdapter();

const transferConfigLoading = ref(false);
const transferConfigLoaded = ref(false);
const panTransferEnabled = ref(false);
const panTransferPathsList = ref([]);
const selectedManualPath = ref('');
const lastRefreshedTimestampTransfer = ref(null);
const manualTransferDialog = reactive({
  show: false,
  loading: false,
  path: '',
  result: null,
});

const panTransferSelectItems = computed(() =>
  panTransferPathsList.value
    .map((p) => (p.path ? String(p.path).trim() : ''))
    .filter(Boolean)
    .map((path) => ({ title: path, value: path })),
);

const lastRefreshedTimeDisplayTransfer = computed(() => {
  if (!lastRefreshedTimestampTransfer.value) return '';
  const date = new Date(lastRefreshedTimestampTransfer.value);
  return `更新于: ${date.getHours().toString().padStart(2, '0')}:${date
    .getMinutes()
    .toString()
    .padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
});

function parsePanTransferPaths(raw) {
  if (!raw || typeof raw !== 'string') return [];
  return raw
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((path) => ({ path }));
}

async function loadTransferConfig() {
  transferConfigLoading.value = true;
  try {
    const data = await props.api.get(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/get_config`);
    if (data) {
      panTransferEnabled.value = Boolean(data.pan_transfer_enabled);
      panTransferPathsList.value = parsePanTransferPaths(data.pan_transfer_paths || '');
      const vals = panTransferSelectItems.value.map((x) => x.value);
      if (vals.length > 0) {
        if (!selectedManualPath.value || !vals.includes(selectedManualPath.value)) {
          selectedManualPath.value = vals[0];
        }
      } else {
        selectedManualPath.value = '';
      }
    }
    transferConfigLoaded.value = true;
    lastRefreshedTimestampTransfer.value = Date.now();
  } catch {
    transferConfigLoaded.value = true;
  } finally {
    transferConfigLoading.value = false;
  }
}

function openManualTransferDialog() {
  const path = selectedManualPath.value?.trim();
  if (!path) return;
  manualTransferDialog.path = path;
  manualTransferDialog.loading = false;
  manualTransferDialog.result = null;
  manualTransferDialog.show = true;
}

function closeManualTransferDialog() {
  manualTransferDialog.show = false;
  manualTransferDialog.path = '';
  manualTransferDialog.loading = false;
  manualTransferDialog.result = null;
}

async function confirmManualTransfer() {
  if (!manualTransferDialog.path) return;
  manualTransferDialog.loading = true;
  manualTransferDialog.result = null;
  try {
    const result = await props.api.post(`plugin/${P115_STRM_HELPER_PLUGIN_ID}/manual_transfer`, {
      path: manualTransferDialog.path,
    });
    if (result.code === 0) {
      manualTransferDialog.result = {
        type: 'success',
        title: '整理任务已启动',
        message: result.msg || '整理任务已在后台启动，正在执行中。您可以在日志中查看详细进度。',
      };
    } else {
      manualTransferDialog.result = {
        type: 'error',
        title: '启动失败',
        message: result.msg || '启动整理任务失败，请检查配置和网络连接。',
      };
    }
  } catch (error) {
    manualTransferDialog.result = {
      type: 'error',
      title: '启动失败',
      message: `启动整理任务时发生错误：${error.message || error}`,
    };
  } finally {
    manualTransferDialog.loading = false;
  }
}

onMounted(() => {
  loadTransferConfig();
});
</script>
