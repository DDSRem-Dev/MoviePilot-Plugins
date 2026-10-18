<template>
  <div class="mb-4">
    <v-btn variant="tonal" color="primary" prepend-icon="mdi-file-restore-outline" @click="open = true">
      整理后处理恢复
    </v-btn>
    <div class="text-caption text-medium-emphasis mt-2">查询未完成或已停止的整理事件，核验目标后续做 STRM 后处理。</div>
  </div>

  <v-dialog v-model="open" max-width="800" :persistent="busy" scrollable>
    <v-card>
      <v-card-title class="text-h6 pa-4">整理后处理恢复</v-card-title>
      <v-divider />
      <v-card-text class="pa-4">
        <p class="text-body-2 mb-4">
          选择一条记录查看详情并核验重试。未完成任务可继续执行；已停止任务会核验是否符合旧版大小误判的恢复条件。
        </p>
        <div class="d-flex align-center ga-3 mb-3">
          <v-select v-model="filter" label="事件状态" :items="filters" variant="outlined" density="compact"
            hide-details :disabled="busy" @update:model-value="loadList(1)" />
          <v-btn variant="tonal" color="primary" :disabled="busy" :loading="operation === 'list'"
            @click="loadList(page)">刷新列表</v-btn>
        </div>
        <v-progress-linear v-if="operation === 'list'" indeterminate color="primary" class="mb-3" />
        <v-alert v-if="listError" type="error" variant="tonal" density="compact" class="mb-3" role="status">
          {{ listError }}，请刷新列表重试
        </v-alert>
        <p v-else-if="!records.length && operation !== 'list'" class="text-body-2 my-4" role="status">
          当前筛选下没有后处理记录
        </p>
        <div v-if="records.length" class="recovery-list mb-3" aria-label="后处理记录">
          <button v-for="item in records" :key="item.key" type="button" class="recovery-row"
            :class="{ 'recovery-row-selected': eventKey === item.key }" :disabled="busy"
            :aria-pressed="eventKey === item.key" @click="selectRecord(item)">
            <span class="d-flex align-center ga-2 mb-1">
              <v-chip :color="statusFor(item.state).color" size="x-small" variant="tonal" class="flex-shrink-0">
                {{ statusFor(item.state).label }}
              </v-chip>
              <span class="text-body-2 font-weight-medium recovery-filename" :title="fileName(item)">{{ fileName(item) }}</span>
            </span>
            <span class="text-caption recovery-path">{{ item.cloud_path || item.local_path || '未记录路径' }}</span>
            <span v-if="item.reason || item.state === 'superseded'"
              class="d-block text-caption text-medium-emphasis recovery-text mt-1">
              {{ item.reason || '旧记录未保存停止原因' }}
            </span>
          </button>
        </div>
        <div class="d-flex align-center justify-space-between ga-2 mb-4">
          <span class="text-caption text-medium-emphasis">共 {{ total }} 条 · 第 {{ page }} / {{ pageCount }} 页</span>
          <div class="d-flex">
            <v-btn size="small" variant="text" :disabled="busy || page <= 1" @click="loadList(page - 1)">上一页</v-btn>
            <v-btn size="small" variant="text" :disabled="busy || page >= pageCount" @click="loadList(page + 1)">下一页</v-btn>
          </div>
        </div>
        <div v-if="eventKey" class="d-flex align-center justify-space-between mb-3">
          <span class="text-subtitle-2">选中记录详情</span>
          <v-btn size="small" variant="text" color="primary" :disabled="busy"
            :loading="operation === 'query'" @click="query">刷新状态</v-btn>
        </div>

        <v-alert v-if="feedback" :type="feedback.type" variant="tonal" density="compact"
          class="mb-4 recovery-text" role="status">{{ feedback.text }}</v-alert>
        <v-alert v-if="operation === 'retry'" type="info" variant="tonal" density="compact"
          class="mb-4" role="status">正在核验并执行后处理，请等待结果。</v-alert>

        <div v-if="record" aria-live="polite">
          <div class="d-flex align-center mb-4">
            <span class="text-body-2 mr-3">事件状态</span>
            <v-chip :color="status.color" size="small" variant="tonal">{{ status.label }}</v-chip>
          </div>
          <dl class="recovery-details text-body-2">
            <dt>网盘目标</dt><dd>{{ record.cloud_path || '未记录' }}</dd>
            <dt>本地 STRM</dt><dd>{{ record.local_path || '未记录' }}</dd>
            <dt>记录大小</dt><dd>{{ sizeLabel }}</dd>
            <template v-if="record.state === 'superseded' || record.reason">
              <dt>停止原因</dt><dd>{{ record.reason || '旧记录未保存停止原因' }}</dd>
            </template>
          </dl>
          <p v-if="record.state === 'superseded'" class="text-caption text-medium-emphasis mt-3">
            旧记录的大小可能经过舍入。重试时将核验云端文件、本地 STRM 和事件归属，符合条件才会继续。
          </p>
          <p v-if="record.state === 'done'" class="text-body-2 mt-3">后处理已完成，无需重试。</p>
        </div>
      </v-card-text>
      <v-divider />
      <v-card-actions class="pa-4">
        <v-btn variant="text" :disabled="busy" @click="open = false">关闭</v-btn>
        <v-spacer />
        <v-btn color="primary" variant="tonal" :disabled="!canRetry" :loading="operation === 'retry'"
          @click="retry">核验并重试</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, inject, ref, watch } from 'vue';
import { useTransferPostprocess } from '../composables/useTransferPostprocess';

const open = ref(false);
const { eventKey, record, feedback, operation, busy, canRetry, query, retry,
  records, filter, page, total, pageCount, listError, loadList, selectRecord }
  = useTransferPostprocess(inject('api'), inject('PLUGIN_ID'));
const filters = [
  { title: '未完成', value: 'unfinished' },
  { title: '待处理', value: 'pending' },
  { title: '已停止', value: 'superseded' },
  { title: '已完成', value: 'done' },
  { title: '全部', value: 'all' },
];
watch(open, (visible) => { if (visible) loadList(1); });
const statusFor = (state) => ({
  pending: { label: '待处理', color: 'info' },
  done: { label: '已完成', color: 'success' },
  superseded: { label: '已停止', color: 'warning' },
}[state] || { label: '未知状态', color: 'grey' });
const status = computed(() => statusFor(record.value?.state));
const fileName = (item) => (item.cloud_path || item.local_path || '').split('/').filter(Boolean).pop() || '未记录文件名';
const sizeLabel = computed(() => record.value?.size == null
  ? '未记录' : `${record.value.size} 字节`);
</script>

<style scoped>
.recovery-list {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  border-radius: 6px;
}
.recovery-row {
  display: block;
  width: 100%;
  padding: 12px;
  text-align: left;
  color: inherit;
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.12);
}
.recovery-row:last-child { border-bottom: 0; }
.recovery-row:hover,
.recovery-row-selected { background: rgba(var(--v-theme-primary), 0.08); }
.recovery-row:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; }
.recovery-row:disabled { cursor: wait; }
.recovery-filename {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.recovery-path {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.recovery-details dt {
  color: rgb(var(--v-theme-on-surface), 0.65);
  margin-top: 12px;
  margin-bottom: 4px;
}
.recovery-details dd {
  margin: 0;
  white-space: pre-wrap;
}
.recovery-details dd,
.recovery-text {
  overflow-wrap: anywhere;
}
</style>
