<template>
  <v-dialog v-model="lifeEventCheckDialog.show" max-width="860" persistent :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-stethoscope" color="primary" size="20" />
          <span>115 生活事件故障检查</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body">
        <!-- Time Range Pull Control -->
        <AppleBentoCard title="拉取指定时间内的全部数据（可选）" icon="mdi-clock-outline" class="mb-4">
          <div class="d-flex align-center flex-wrap gap-2">
            <input
              v-model="lifeEventCheckDialog.startTime"
              type="datetime-local"
              class="p115-datetime-input p115-tabular"
              aria-label="开始时间"
            />
            <button
              v-if="lifeEventCheckDialog.startTime"
              type="button"
              class="p115-btn p115-btn--subtle p115-btn--sm"
              @click="lifeEventCheckDialog.startTime = ''"
            >
              清除时间
            </button>
          </div>
          <div class="text-caption mt-2 opacity-75">
            填写后点击「重新检查」，将额外拉取从该时间起的全部生活事件并统计数量
          </div>
        </AppleBentoCard>

        <div v-if="lifeEventCheckDialog.error" class="p115-callout p115-callout--error mb-3">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ lifeEventCheckDialog.error }}</span>
        </div>

        <div v-if="lifeEventCheckDialog.loading" class="d-flex flex-column align-center py-8">
          <v-progress-circular indeterminate color="primary" size="42" class="mb-3" />
          <div class="text-body-2">正在诊断生活事件线程与拉取链路...</div>
        </div>

        <template v-else-if="lifeEventCheckDialog.result">
          <div
            class="p115-callout mb-4"
            :class="lifeEventCheckDialog.result.data?.success ? 'p115-callout--success' : 'p115-callout--warn'"
          >
            <v-icon
              size="18"
              :color="lifeEventCheckDialog.result.data?.success ? 'success' : 'warning'"
              :icon="lifeEventCheckDialog.result.data?.success ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline'"
              class="mt-1 flex-shrink-0"
            />
            <div class="w-100">
              <div class="font-weight-bold">{{ lifeEventCheckDialog.result.msg }}</div>
              <div v-if="lifeEventCheckDialog.result.data?.error_messages?.length" class="mt-2">
                <div class="font-weight-medium mb-1">发现的问题：</div>
                <div
                  v-for="(msg, idx) in lifeEventCheckDialog.result.data.error_messages"
                  :key="idx"
                  class="d-flex align-start gap-1 mb-1"
                >
                  <span>•</span>
                  <span>{{ msg }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 5-Point Summary Matrix -->
          <AppleBentoCard title="检查结果摘要" icon="mdi-clipboard-check-outline" class="mb-4">
            <template #actions>
              <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="$emit('copy-debug')">
                <v-icon size="14" icon="mdi-content-copy" />
                <span>复制调试信息</span>
              </button>
            </template>

            <div class="p115-diag-grid">
              <div v-for="item in summaryChecks" :key="item.label" class="p115-diag-item">
                <span>{{ item.label }}</span>
                <span class="p115-badge" :class="item.ok ? 'p115-badge--green' : 'p115-badge--red'">
                  <span class="p115-badge-dot" />
                  {{ item.ok ? '正常' : '异常' }}
                </span>
              </div>
            </div>
          </AppleBentoCard>

          <div>
            <div class="text-caption font-weight-bold mb-2">详细调试日志（可复制给开发者排查）</div>
            <v-textarea
              :model-value="lifeEventCheckDialog.result.data?.debug_info || ''"
              readonly
              variant="outlined"
              rows="12"
              auto-grow
              class="p115-mono text-caption"
              hide-details
            />
          </div>
        </template>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">关闭</button>
        <button
          type="button"
          class="p115-btn p115-btn--primary"
          :disabled="lifeEventCheckDialog.loading"
          @click="$emit('check')"
        >
          <v-icon size="16" icon="mdi-refresh" />
          <span>重新检查</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed } from 'vue';
import AppleBentoCard from '../ui/AppleBentoCard.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const props = defineProps({
  lifeEventCheckDialog: { type: Object, required: true },
});

defineEmits(['check', 'close', 'copy-debug']);

const { dialogContentClass } = useThemeAdapter();

const summaryChecks = computed(() => {
  const s = props.lifeEventCheckDialog.result?.data?.summary || {};
  return [
    { label: '插件启用', ok: Boolean(s.plugin_enabled) },
    { label: '客户端初始化', ok: Boolean(s.client_initialized) },
    { label: 'MonitorLife 初始化', ok: Boolean(s.monitorlife_initialized) },
    { label: '监控线程运行', ok: Boolean(s.thread_running) },
    { label: '配置有效性', ok: Boolean(s.config_valid) },
  ];
});
</script>

<style scoped>
.p115-datetime-input {
  padding: 7px 12px;
  border-radius: 10px;
  border: 1px solid var(--p115-border-hairline);
  background: var(--p115-bg-inset);
  color: var(--p115-text-primary);
  font-family: var(--p115-font-sans);
  font-size: 0.84rem;
  outline: none;
}

.p115-datetime-input:focus {
  border-color: var(--p115-blue);
  box-shadow: 0 0 0 3px rgba(91, 207, 250, 0.22);
}

.p115-diag-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}

.p115-diag-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
  font-size: 0.8rem;
  font-weight: 540;
}
</style>
