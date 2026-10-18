<template>
  <v-dialog v-model="qrDialog.show" max-width="450">
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-qrcode" class="mr-2" color="primary" size="small" />
        <span>115网盘扫码登录</span>
      </v-card-title>

      <v-card-text class="text-center py-4">
        <v-alert v-if="qrDialog.error" type="error" density="compact" class="mb-3 mx-3" variant="tonal" closable>
          {{ qrDialog.error }}
        </v-alert>

        <div v-if="qrDialog.loading" class="d-flex flex-column align-center py-3">
          <v-progress-circular indeterminate color="primary" class="mb-3"></v-progress-circular>
          <div>正在获取二维码...</div>
        </div>

        <div v-else-if="qrDialog.qrcode" class="d-flex flex-column align-center">
          <div class="mb-2 font-weight-medium">请选择扫码方式</div>
          <v-chip-group v-model="qrDialog.clientType" class="mb-3" mandatory selected-class="primary">
            <v-chip v-for="type in clientTypes" :key="type.value" :value="type.value" variant="outlined"
              color="primary" size="small">
              {{ type.label }}
            </v-chip>
          </v-chip-group>
          <div class="d-flex flex-column align-center mb-3">
            <v-card flat class="border pa-2 mb-2">
              <img :src="qrDialog.qrcode" width="220" height="220" />
            </v-card>
            <div class="text-body-2 text-grey mb-1">{{ qrDialog.tips }}</div>
            <div class="text-subtitle-2 font-weight-medium text-primary">{{ qrDialog.status }}</div>
          </div>
          <v-btn color="primary" variant="tonal" @click="$emit('refresh')" size="small" class="mb-2">
            <v-icon left size="small" class="mr-1">mdi-refresh</v-icon>刷新二维码
          </v-btn>
        </div>

        <div v-else class="d-flex flex-column align-center py-3">
          <v-icon icon="mdi-qrcode-off" size="64" color="grey" class="mb-3"></v-icon>
          <div class="text-subtitle-1">二维码获取失败</div>
          <div class="text-body-2 text-grey">请点击刷新按钮重试</div>
          <div class="text-caption mt-2 text-grey">
            <v-icon icon="mdi-alert-circle" size="small" class="mr-1 text-warning"></v-icon>
            如果多次获取失败，请检查网络连接
          </div>
        </div>
      </v-card-text>
      <v-divider></v-divider>
      <v-card-actions class="px-3 py-2">
        <v-btn color="grey" variant="text" @click="$emit('close')" size="small" prepend-icon="mdi-close">关闭</v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="$emit('refresh')" :disabled="qrDialog.loading" size="small"
          prepend-icon="mdi-refresh">
          刷新二维码
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  qrDialog: { type: Object, required: true },
  clientTypes: { type: Array, required: true },
});

defineEmits(['refresh', 'close']);
</script>
