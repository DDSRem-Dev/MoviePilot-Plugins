<template>
  <v-dialog
    :model-value="modelValue"
    max-width="480"
    persistent
    :content-class="dialogContentClass"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-sync-alert" color="warning" size="20" />
          <span>确认执行全量同步</span>
        </div>
      </div>

      <div class="p115-sheet-body">
        <p class="text-body-2 mb-3">您确定要立即启动全量 STRM 同步任务吗？任务将在后台队列执行。</p>

        <div v-if="hasMediaServerRefresh" class="p115-callout p115-callout--warn">
          <v-icon icon="mdi-alert-outline" color="warning" size="18" class="mt-1 flex-shrink-0" />
          <div>
            <div class="font-weight-bold mb-1">重要警告：已开启全量刷新媒体库</div>
            <div>
              全量同步完成后将自动刷新整个媒体库，此操作会扫描所有媒体文件，可能导致媒体服务器负载增加。请确保您已了解此风险并自行承担相应责任。
            </div>
          </div>
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button
          type="button"
          class="p115-btn p115-btn--subtle"
          :disabled="loading"
          @click="$emit('update:modelValue', false)"
        >
          取消
        </button>
        <button
          type="button"
          class="p115-btn p115-btn--primary"
          :disabled="loading"
          @click="$emit('confirm')"
        >
          <v-progress-circular v-if="loading" indeterminate size="14" width="2" />
          <v-icon v-else size="16" icon="mdi-play" />
          <span>确认执行</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

defineProps({
  modelValue: { type: Boolean, required: true },
  loading: { type: Boolean, default: false },
  hasMediaServerRefresh: { type: Boolean, default: false },
});

defineEmits(['update:modelValue', 'confirm']);

const { dialogContentClass } = useThemeAdapter();
</script>
