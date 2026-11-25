<template>
  <v-dialog v-model="offlineDownloadDialog.show" max-width="800" persistent :content-class="dialogContentClass">
    <v-card flat class="p115-sheet p115-sheet--workspace">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-cloud-download-outline" color="primary" size="20" />
          <span>115 网盘离线下载</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body">
        <div class="mb-4">
          <AppleSegmentedControl v-model="offlineDownloadDialog.activeTab" :items="tabItems" block @change="onTabChange" />
        </div>

        <!-- Add Task View -->
        <div v-if="offlineDownloadDialog.activeTab === 'add'">
          <div v-if="offlineDownloadDialog.addError" class="p115-callout p115-callout--error mb-3">
            <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
            <span>{{ offlineDownloadDialog.addError }}</span>
          </div>

          <AppleSettingsGroup title="下载任务信息" padded>
            <v-textarea
              v-model="offlineDownloadDialog.links"
              label="下载链接"
              hint="每行一个链接，支持 http(s) / ftp / magnet / ed2k"
              persistent-hint
              variant="outlined"
              rows="5"
              clearable
              class="p115-mono mb-3"
            />

            <v-combobox
              v-model="offlineDownloadDialog.destPath"
              :items="offlineDownloadDialog.availablePathStrings"
              label="网盘保存路径 (可选)"
              hint="可选，留空默认使用网盘待整理目录。可从历史缓存或预设路径中选择，亦可手动输入"
              persistent-hint
              variant="outlined"
              density="compact"
              clearable
            >
              <template #prepend-inner>
                <v-icon icon="mdi-cloud-outline" size="18" color="secondary" />
              </template>
              <template #append-inner>
                <button
                  type="button"
                  class="p115-btn p115-btn--tonal p115-btn--sm"
                  @click.stop="$emit('browse-dest')"
                >
                  浏览网盘
                </button>
              </template>
              <template #item="{ props: itemProps, item }">
                <v-list-item v-bind="itemProps" :title="getPathLabel(item.raw)" />
              </template>
            </v-combobox>
          </AppleSettingsGroup>
        </div>

        <!-- Tasks List View -->
        <div v-else>
          <div v-if="offlineDownloadDialog.error" class="p115-callout p115-callout--error mb-3">
            <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
            <span>{{ offlineDownloadDialog.error }}</span>
          </div>

          <!-- Mobile Compact Cards (< 600px) -->
          <div v-if="isMobile" class="d-flex flex-column gap-2">
            <div v-if="offlineDownloadDialog.loading" class="py-6 text-center">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="!offlineDownloadDialog.tasks.length" class="py-6 text-center text-caption opacity-70">
              当前没有离线下载任务
            </div>
            <div
              v-for="(item, idx) in offlineDownloadDialog.tasks"
              :key="idx"
              class="p115-offline-mobile-card"
            >
              <div class="d-flex align-start justify-space-between gap-2 mb-2">
                <div class="text-body-2 font-weight-medium" style="word-break: break-all;">{{ item.name }}</div>
                <span class="p115-badge" :class="statusBadgeClass(item.status)">{{ item.status_text }}</span>
              </div>
              <div class="d-flex align-center justify-space-between text-caption opacity-75 mb-1 p115-tabular">
                <span>大小：{{ item.size_text }}</span>
                <span>{{ item.percent }}%</span>
              </div>
              <div class="p115-progress-track">
                <div class="p115-progress-fill" :style="{ width: `${Math.min(100, Math.max(0, item.percent || 0))}%` }" />
              </div>
            </div>
          </div>

          <!-- Desktop Server Data Table -->
          <div v-else style="overflow-x: auto;" @touchstart.stop @touchmove.stop @touchend.stop>
            <v-data-table-server
              :headers="offlineDownloadDialog.headers"
              :items="offlineDownloadDialog.tasks"
              :items-length="offlineDownloadDialog.totalTasks"
              :loading="offlineDownloadDialog.loading"
              :items-per-page="offlineDownloadDialog.itemsPerPage"
              density="compact"
              no-data-text="没有离线下载任务"
              loading-text="正在加载任务..."
              items-per-page-text="每页条目数"
              class="p115-tabular"
              @update:options="$emit('fetch-tasks', $event)"
            >
              <template #item.progress="{ item }">
                <div class="d-flex align-center gap-2">
                  <div class="p115-progress-track flex-grow-1">
                    <div
                      class="p115-progress-fill"
                      :style="{ width: `${Math.min(100, Math.max(0, item.percent || 0))}%` }"
                    />
                  </div>
                  <span class="text-caption font-weight-medium p115-tabular" style="min-width: 38px; text-align: right;">
                    {{ item.percent }}%
                  </span>
                </div>
              </template>
              <template #item.status_text="{ item }">
                <span class="p115-badge" :class="statusBadgeClass(item.status)">
                  {{ item.status_text }}
                </span>
              </template>
            </v-data-table-server>
          </div>
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">关闭</button>
        <button
          v-if="offlineDownloadDialog.activeTab === 'add'"
          type="button"
          class="p115-btn p115-btn--primary"
          :disabled="!offlineDownloadDialog.links || offlineDownloadDialog.adding"
          @click="$emit('add-task')"
        >
          <v-progress-circular v-if="offlineDownloadDialog.adding" indeterminate size="14" width="2" />
          <v-icon v-else size="16" icon="mdi-plus" />
          <span>添加离线任务</span>
        </button>
        <button
          v-else
          type="button"
          class="p115-btn p115-btn--tonal"
          :disabled="offlineDownloadDialog.loading"
          @click="$emit('fetch-tasks', { page: 1, itemsPerPage: offlineDownloadDialog.itemsPerPage })"
        >
          <v-icon size="16" icon="mdi-refresh" />
          <span>刷新列表</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed } from 'vue';
import { useDisplay } from 'vuetify';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const props = defineProps({
  offlineDownloadDialog: { type: Object, required: true },
  getPathLabel: { type: Function, required: true },
});

const emit = defineEmits(['close', 'add-task', 'fetch-tasks', 'browse-dest']);

const { dialogContentClass } = useThemeAdapter();
const display = useDisplay();
const isMobile = computed(() => display.xs.value);

const tabItems = [
  { label: '添加任务', value: 'add', icon: 'mdi-plus-circle-outline' },
  { label: '任务列表', value: 'tasks', icon: 'mdi-format-list-bulleted' },
];

const onTabChange = (val) => {
  if (val === 'tasks') {
    emit('fetch-tasks', { page: 1, itemsPerPage: props.offlineDownloadDialog.itemsPerPage });
  }
};

const statusBadgeClass = (status) => {
  switch (status) {
    case 0: return 'p115-badge--blue';
    case 1: return 'p115-badge--red';
    case 2: return 'p115-badge--green';
    case 3: return 'p115-badge--amber';
    default: return 'p115-badge--neutral';
  }
};
</script>

<style scoped>
.p115-offline-mobile-card {
  padding: 12px;
  border-radius: 12px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
}
</style>
