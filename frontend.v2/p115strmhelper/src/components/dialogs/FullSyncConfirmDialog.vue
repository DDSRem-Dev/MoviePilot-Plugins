<template>
  <v-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" max-width="500" persistent>
    <v-card>
      <v-card-title class="text-h6 d-flex align-center">
        <v-icon icon="mdi-alert-circle-outline" color="warning" class="mr-2"></v-icon>
        确认操作
      </v-card-title>
      <v-card-text>
        <div class="mb-2">您确定要立即执行全量同步吗？</div>
        <v-alert v-if="hasMediaServerRefresh" type="warning" variant="tonal" density="compact"
          class="mt-2" icon="mdi-alert">
          <div class="text-body-2 mb-1"><strong>重要警告</strong></div>
          <div class="text-caption">
            全量同步完成后将自动刷新整个媒体库，此操作会扫描所有媒体文件，可能导致媒体服务器负载增加。请确保您已了解此风险并自行承担相应责任。
          </div>
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="$emit('update:modelValue', false)" :disabled="loading">
          取消
        </v-btn>
        <v-btn color="warning" variant="text" @click="$emit('confirm')" :loading="loading">
          确认执行
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, required: true },
  loading: { type: Boolean, default: false },
  hasMediaServerRefresh: { type: Boolean, default: false },
});

defineEmits(['update:modelValue', 'confirm']);
</script>
