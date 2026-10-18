<template>
  <v-dialog v-model="manualTransferDialog.show" max-width="500" persistent>
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-play-circle" class="mr-2" color="primary" size="small" />
        <span>手动整理确认</span>
      </v-card-title>

      <v-card-text class="px-3 py-3">
        <div v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
          <div class="text-body-2 mb-3">确定要手动整理以下目录吗？</div>
          <v-alert type="info" variant="tonal" density="compact" icon="mdi-information">
            <div class="text-body-2">
              <strong>路径：</strong>{{ manualTransferDialog.path }}
            </div>
          </v-alert>
        </div>

        <div v-else-if="manualTransferDialog.loading" class="d-flex flex-column align-center py-3">
          <v-progress-circular indeterminate color="primary" size="48" class="mb-3"></v-progress-circular>
          <div class="text-body-2 text-grey">正在启动整理任务...</div>
        </div>

        <div v-else-if="manualTransferDialog.result">
          <v-alert :type="manualTransferDialog.result.type" variant="tonal" density="compact"
            :icon="manualTransferDialog.result.type === 'success' ? 'mdi-check-circle' : 'mdi-alert-circle'">
            <div class="text-subtitle-2 mb-1">
              {{ manualTransferDialog.result.title }}
            </div>
            <div class="text-body-2">{{ manualTransferDialog.result.message }}</div>
          </v-alert>
        </div>
      </v-card-text>

      <v-card-actions class="px-3 py-2">
        <v-spacer></v-spacer>
        <template v-if="!manualTransferDialog.loading && !manualTransferDialog.result">
          <v-btn color="grey" variant="text" @click="$emit('close')" size="small">
            取消
          </v-btn>
          <v-btn color="primary" variant="text" @click="$emit('confirm')" size="small">
            确认执行
          </v-btn>
        </template>
        <template v-else>
          <v-btn color="primary" variant="text" @click="$emit('close')" size="small">
            关闭
          </v-btn>
        </template>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  manualTransferDialog: { type: Object, required: true },
});

defineEmits(['confirm', 'close']);
</script>
