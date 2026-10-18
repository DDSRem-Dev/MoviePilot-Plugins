<template>
  <div class="dashboard-widget dashboard-widget--transfer-mini">
    <v-card :flat="!config?.attrs?.border" class="strm-dash-card transfer-mini-card dashboard-grid-fill h-100 d-flex flex-column">
      <v-card-item v-if="config?.attrs?.title || config?.attrs?.subtitle" class="pb-2">
        <v-card-title class="d-flex flex-wrap align-center gap-2 ps-0 text-subtitle-1">
          <v-icon icon="mdi-folder-cog" color="primary" size="small" />
          {{ config?.attrs?.title || "手动网盘整理" }}
        </v-card-title>
        <v-card-subtitle v-if="config?.attrs?.subtitle">{{ config.attrs.subtitle }}</v-card-subtitle>
        <template v-slot:append>
          <v-btn class="dashboard-grid-no-drag" icon size="small" variant="text" :loading="transferConfigLoading" @click="loadTransferConfig">
            <v-icon>mdi-refresh</v-icon>
          </v-btn>
        </template>
      </v-card-item>

      <v-card-text class="pa-3 pt-0 transfer-mini-card__body flex-grow-1 d-flex flex-column">
        <div v-if="transferConfigLoading && !transferConfigLoaded" class="text-center py-6">
          <v-progress-circular indeterminate color="primary" size="36" />
        </div>
        <template v-else-if="transferConfigLoaded">
          <v-alert v-if="!panTransferEnabled" type="warning" variant="tonal" density="compact" class="mb-3">
            请先在插件设置中开启「网盘整理」
          </v-alert>
          <v-alert v-else-if="panTransferSelectItems.length === 0" type="info" variant="tonal" density="compact"
            class="mb-3">
            请先在插件设置中配置「网盘整理目录」
          </v-alert>
          <template v-else>
            <v-select v-model="selectedManualPath" :items="panTransferSelectItems" item-title="title" item-value="value"
              label="整理目录" density="compact" hide-details variant="outlined" class="mb-3 dashboard-grid-no-drag" />
            <v-btn class="dashboard-grid-no-drag" block color="primary" variant="tonal" prepend-icon="mdi-play-circle" :disabled="!selectedManualPath"
              @click="openManualTransferDialog">
              执行整理
            </v-btn>
          </template>
        </template>
      </v-card-text>

      <v-divider v-if="allowRefresh" />
      <v-card-actions v-if="allowRefresh" class="px-3 py-2 refresh-actions">
        <span class="text-caption text-disabled">{{ lastRefreshedTimeDisplayTransfer }}</span>
        <v-spacer />
        <v-btn class="dashboard-grid-no-drag" icon variant="text" size="small" :loading="transferConfigLoading" @click="loadTransferConfig">
          <v-icon size="small">mdi-refresh</v-icon>
        </v-btn>
      </v-card-actions>
    </v-card>

    <v-dialog v-model="manualTransferDialog.show" max-width="500" persistent>
      <v-card>
        <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2">
          <v-icon icon="mdi-play-circle" class="mr-2" color="primary" size="small" />
          手动整理确认
        </v-card-title>
        <v-card-text class="px-3 py-3">
          <div v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
            <div class="text-body-2 mb-3">确定要手动整理以下目录吗？</div>
            <v-alert type="info" variant="tonal" density="compact" icon="mdi-information">
              <div class="text-body-2"><strong>路径：</strong>{{ manualTransferDialog.path }}</div>
            </v-alert>
          </div>
          <div v-else-if="manualTransferDialog.loading" class="d-flex flex-column align-center py-3">
            <v-progress-circular indeterminate color="primary" size="48" class="mb-3" />
            <div class="text-body-2 text-medium-emphasis">正在启动整理任务...</div>
          </div>
          <div v-else-if="manualTransferDialog.result">
            <v-alert :type="manualTransferDialog.result.type" variant="tonal" density="compact"
              :icon="manualTransferDialog.result.type === 'success' ? 'mdi-check-circle' : 'mdi-alert-circle'">
              <div class="text-subtitle-2 mb-1">{{ manualTransferDialog.result.title }}</div>
              <div class="text-body-2">{{ manualTransferDialog.result.message }}</div>
            </v-alert>
          </div>
        </v-card-text>
        <v-card-actions class="px-3 py-2">
          <v-spacer />
          <template v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
            <v-btn class="dashboard-grid-no-drag" color="grey" variant="text" size="small" @click="closeManualTransferDialog">取消</v-btn>
            <v-btn class="dashboard-grid-no-drag" color="primary" variant="text" size="small" @click="confirmManualTransfer">确认执行</v-btn>
          </template>
          <v-btn v-else class="dashboard-grid-no-drag" color="primary" variant="text" size="small" @click="closeManualTransferDialog">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from "vue";
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
});

const transferConfigLoading = ref(false);
const transferConfigLoaded = ref(false);
const panTransferEnabled = ref(false);
const panTransferPathsList = ref([]);
const selectedManualPath = ref("");
const lastRefreshedTimestampTransfer = ref(null);
const manualTransferDialog = reactive({
  show: false,
  loading: false,
  path: "",
  result: null,
});

const panTransferSelectItems = computed(() =>
  panTransferPathsList.value
    .map((p) => (p.path ? String(p.path).trim() : ""))
    .filter(Boolean)
    .map((path) => ({ title: path, value: path })),
);

const lastRefreshedTimeDisplayTransfer = computed(() => {
  if (!lastRefreshedTimestampTransfer.value) return "";
  const date = new Date(lastRefreshedTimestampTransfer.value);
  return `更新于: ${date.getHours().toString().padStart(2, "0")}:${date
    .getMinutes()
    .toString()
    .padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}`;
});

function parsePanTransferPaths(raw) {
  if (!raw || typeof raw !== "string") return [];
  return raw
    .split("\n")
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
      panTransferPathsList.value = parsePanTransferPaths(data.pan_transfer_paths || "");
      const vals = panTransferSelectItems.value.map((x) => x.value);
      if (vals.length > 0) {
        if (!selectedManualPath.value || !vals.includes(selectedManualPath.value)) {
          selectedManualPath.value = vals[0];
        }
      } else {
        selectedManualPath.value = "";
      }
    }
    transferConfigLoaded.value = true;
    lastRefreshedTimestampTransfer.value = Date.now();
  } catch (err) {
    console.error("获取整理配置失败:", err);
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
  manualTransferDialog.path = "";
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
        type: "success",
        title: "整理任务已启动",
        message:
          result.msg || "整理任务已在后台启动，正在执行中。您可以在日志中查看详细进度。",
      };
    } else {
      manualTransferDialog.result = {
        type: "error",
        title: "启动失败",
        message: result.msg || "启动整理任务失败，请检查配置和网络连接。",
      };
    }
  } catch (error) {
    manualTransferDialog.result = {
      type: "error",
      title: "启动失败",
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
