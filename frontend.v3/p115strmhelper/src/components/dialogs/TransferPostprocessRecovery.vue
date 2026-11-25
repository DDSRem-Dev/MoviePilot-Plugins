<template>
  <div class="p115-recovery-trigger">
    <div class="p115-recovery-info">
      <div class="p115-recovery-title">
        <v-icon size="16" color="primary" icon="mdi-file-restore-outline" />
        <span>整理后处理恢复核验</span>
      </div>
      <div class="p115-recovery-desc">查询未完成或已停止的整理事件，核验云端与本地目标后续做 STRM 后处理</div>
    </div>
    <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="open = true">
      <v-icon size="15" icon="mdi-history" />
      <span>打开恢复面板</span>
    </button>
  </div>

  <v-dialog v-model="open" max-width="780" :persistent="busy" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-file-restore-outline" color="primary" size="20" />
          <span>整理后处理恢复</span>
        </div>
        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon"
          :disabled="busy"
          aria-label="关闭"
          @click="open = false"
        >
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body">
        <p class="text-caption mb-3 opacity-80">
          选择一条记录查看详情并核验重试。未完成任务可继续执行；已停止任务会核验是否符合旧版大小误判的恢复条件。
        </p>

        <div class="d-flex align-center justify-space-between flex-wrap gap-2 mb-3">
          <AppleSegmentedControl v-model="filter" :items="filters" @change="loadList(1)" />
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            :disabled="busy"
            @click="loadList(page)"
          >
            <v-icon size="15" icon="mdi-refresh" />
            <span>刷新列表</span>
          </button>
        </div>

        <v-progress-linear v-if="operation === 'list'" indeterminate color="primary" class="mb-3" rounded />

        <div v-if="listError" class="p115-callout p115-callout--error mb-3" role="status">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ listError }}，请刷新列表重试</span>
        </div>

        <div v-else-if="!records.length && operation !== 'list'" class="p115-recovery-empty" role="status">
          当前筛选下没有后处理记录
        </div>

        <div v-if="records.length" class="p115-recovery-list mb-3" aria-label="后处理记录">
          <button
            v-for="item in records"
            :key="item.key"
            type="button"
            class="p115-recovery-row"
            :class="{ 'p115-recovery-row--selected': eventKey === item.key }"
            :disabled="busy"
            :aria-pressed="eventKey === item.key"
            @click="selectRecord(item)"
          >
            <span class="d-flex align-center gap-2 mb-1">
              <span class="p115-badge" :class="statusFor(item.state).badgeClass">
                {{ statusFor(item.state).label }}
              </span>
              <span class="p115-recovery-filename" :title="fileName(item)">{{ fileName(item) }}</span>
            </span>
            <span class="p115-recovery-path p115-mono">{{ item.cloud_path || item.local_path || '未记录路径' }}</span>
            <span v-if="item.reason || item.state === 'superseded'" class="p115-recovery-reason">
              {{ item.reason || '旧记录未保存停止原因' }}
            </span>
          </button>
        </div>

        <div class="d-flex align-center justify-space-between gap-2 mb-3">
          <span class="text-caption opacity-75 p115-tabular">共 {{ total }} 条 · 第 {{ page }} / {{ pageCount }} 页</span>
          <div class="d-flex gap-1">
            <button
              type="button"
              class="p115-btn p115-btn--subtle p115-btn--sm"
              :disabled="busy || page <= 1"
              @click="loadList(page - 1)"
            >
              上一页
            </button>
            <button
              type="button"
              class="p115-btn p115-btn--subtle p115-btn--sm"
              :disabled="busy || page >= pageCount"
              @click="loadList(page + 1)"
            >
              下一页
            </button>
          </div>
        </div>

        <div v-if="feedback" class="p115-callout mb-3" :class="`p115-callout--${feedback.type === 'success' ? 'success' : feedback.type === 'error' ? 'error' : 'warn'}`" role="status">
          <span>{{ feedback.text }}</span>
        </div>

        <div v-if="operation === 'retry'" class="p115-callout p115-callout--info mb-3" role="status">
          <v-progress-circular indeterminate size="16" width="2" color="primary" />
          <span>正在核验并执行后处理，请等待结果...</span>
        </div>

        <AppleBentoCard v-if="record" title="选中记录详情" icon="mdi-text-box-search-outline">
          <template #badge>
            <span class="p115-badge" :class="status.badgeClass">{{ status.label }}</span>
          </template>
          <template #actions>
            <button
              type="button"
              class="p115-btn p115-btn--tonal p115-btn--sm"
              :disabled="busy"
              @click="query"
            >
              刷新状态
            </button>
          </template>

          <dl class="p115-recovery-dl">
            <dt>网盘目标</dt>
            <dd class="p115-mono">{{ record.cloud_path || '未记录' }}</dd>
            <dt>本地 STRM</dt>
            <dd class="p115-mono">{{ record.local_path || '未记录' }}</dd>
            <dt>记录大小</dt>
            <dd class="p115-tabular">{{ sizeLabel }}</dd>
            <template v-if="record.state === 'superseded' || record.reason">
              <dt>停止原因</dt>
              <dd>{{ record.reason || '旧记录未保存停止原因' }}</dd>
            </template>
          </dl>

          <p v-if="record.state === 'superseded'" class="text-caption opacity-75 mt-3 mb-0">
            旧记录的大小可能经过舍入。重试时将核验云端文件、本地 STRM 和事件归属，符合条件才会继续。
          </p>
          <p v-if="record.state === 'done'" class="text-caption mt-3 mb-0">后处理已完成，无需重试。</p>
        </AppleBentoCard>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" :disabled="busy" @click="open = false">关闭</button>
        <button
          type="button"
          class="p115-btn p115-btn--primary"
          :disabled="!canRetry"
          @click="retry"
        >
          <v-progress-circular v-if="operation === 'retry'" indeterminate size="14" width="2" />
          <v-icon v-else size="16" icon="mdi-play-circle-outline" />
          <span>核验并重试</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, inject, ref, watch } from 'vue';
import { useTransferPostprocess } from '../composables/useTransferPostprocess.js';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleBentoCard from '../ui/AppleBentoCard.vue';

const { dialogContentClass } = useThemeAdapter();

const open = ref(false);
const {
  eventKey, record, feedback, operation, busy, canRetry, query, retry,
  records, filter, page, total, pageCount, listError, loadList, selectRecord,
} = useTransferPostprocess(inject('api'), inject('PLUGIN_ID'));

const filters = [
  { label: '未完成', value: 'unfinished' },
  { label: '待处理', value: 'pending' },
  { label: '已停止', value: 'superseded' },
  { label: '已完成', value: 'done' },
  { label: '全部', value: 'all' },
];

watch(open, (visible) => {
  if (visible) loadList(1);
});

const statusFor = (state) => ({
  pending: { label: '待处理', badgeClass: 'p115-badge--blue' },
  done: { label: '已完成', badgeClass: 'p115-badge--green' },
  superseded: { label: '已停止', badgeClass: 'p115-badge--amber' },
}[state] || { label: '未知状态', badgeClass: 'p115-badge--neutral' });

const status = computed(() => statusFor(record.value?.state));
const fileName = (item) => (item.cloud_path || item.local_path || '').split('/').filter(Boolean).pop() || '未记录文件名';
const sizeLabel = computed(() => (record.value?.size == null ? '未记录' : `${record.value.size} 字节`));
</script>

<style scoped>
.p115-recovery-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 15px;
  border-radius: 13px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
  flex-wrap: wrap;
}

.p115-recovery-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 600;
}

.p115-recovery-desc {
  font-size: 0.75rem;
  color: var(--p115-text-secondary);
  margin-top: 2px;
}

.p115-recovery-empty {
  padding: 28px 12px;
  text-align: center;
  font-size: 0.82rem;
  color: var(--p115-text-secondary);
}

.p115-recovery-list {
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--p115-border-hairline);
  border-radius: 12px;
  background: var(--p115-bg-card);
  padding: 4px;
}

.p115-recovery-row {
  display: block;
  width: 100%;
  padding: 10px 12px;
  border: none;
  border-radius: 9px;
  background: transparent;
  text-align: left;
  color: inherit;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.p115-recovery-row:hover {
  background: var(--p115-bg-hover);
}

.p115-recovery-row--selected {
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.16), rgba(245, 171, 185, 0.12));
}

.p115-recovery-filename {
  font-size: 0.84rem;
  font-weight: 560;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.p115-recovery-path {
  display: block;
  font-size: 0.75rem;
  color: var(--p115-text-secondary);
  overflow-wrap: anywhere;
}

.p115-recovery-reason {
  display: block;
  font-size: 0.74rem;
  color: var(--p115-amber-ink);
  margin-top: 3px;
}

.p115-recovery-dl {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: 8px 12px;
  font-size: 0.8rem;
}

.p115-recovery-dl dt {
  color: var(--p115-text-tertiary);
  font-weight: 560;
}

.p115-recovery-dl dd {
  margin: 0;
  overflow-wrap: anywhere;
}
</style>
