<template>
  <v-dialog v-model="manualTransferDialog.show" max-width="480" persistent :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-folder-play-outline" color="primary" size="20" />
          <span>手动整理确认</span>
        </div>
      </div>

      <div class="p115-sheet-body">
        <div v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
          <div class="text-body-2 mb-3">确定要手动整理以下 115 网盘目录吗？</div>
          <div class="p115-callout p115-callout--info">
            <v-icon size="18" color="primary" icon="mdi-cloud-outline" />
            <div>
              <div class="text-caption opacity-70">目标网盘路径</div>
              <div class="p115-mono font-weight-medium">{{ manualTransferDialog.path }}</div>
            </div>
          </div>
        </div>

        <div v-else-if="manualTransferDialog.loading" class="d-flex flex-column align-center py-5">
          <v-progress-circular indeterminate color="primary" size="40" class="mb-3" />
          <div class="text-body-2">正在启动整理任务...</div>
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

      <div class="p115-sheet-footer">
        <template v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
          <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">取消</button>
          <button type="button" class="p115-btn p115-btn--primary" @click="$emit('confirm')">
            <v-icon size="16" icon="mdi-play" />
            <span>确认执行</span>
          </button>
        </template>
        <template v-else>
          <div />
          <button
            type="button"
            class="p115-btn p115-btn--primary"
            :disabled="manualTransferDialog.loading"
            @click="$emit('close')"
          >
            关闭
          </button>
        </template>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

defineProps({
  manualTransferDialog: { type: Object, required: true },
});

defineEmits(['confirm', 'close']);

const { dialogContentClass } = useThemeAdapter();
</script>
