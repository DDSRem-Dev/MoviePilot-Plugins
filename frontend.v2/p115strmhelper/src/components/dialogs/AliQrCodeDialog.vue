<template>
  <v-dialog v-model="aliQrDialog.show" max-width="450">
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-qrcode" class="mr-2" color="primary" size="small" />
        <span>阿里云盘扫码登录</span>
      </v-card-title>
      <v-card-text class="text-center py-4">
        <v-alert v-if="aliQrDialog.error" type="error" density="compact" class="mb-3 mx-3" variant="tonal" closable>
          {{ aliQrDialog.error }}
        </v-alert>
        <div v-if="aliQrDialog.loading" class="d-flex flex-column align-center py-3">
          <v-progress-circular indeterminate color="primary" class="mb-3"></v-progress-circular>
          <div>正在获取二维码...</div>
        </div>
        <div v-else-if="aliQrDialog.qrcode" class="d-flex flex-column align-center">
          <v-card flat class="border pa-2 mb-2">
            <img :src="aliQrDialog.qrcode" width="220" height="220" />
          </v-card>
          <div class="text-body-2 text-grey mb-1">请使用阿里云盘App扫描二维码</div>
          <div class="text-subtitle-2 font-weight-medium text-primary">{{ aliQrDialog.status }}</div>
        </div>
        <div v-else class="d-flex flex-column align-center py-3">
          <v-icon icon="mdi-qrcode-off" size="64" color="grey" class="mb-3"></v-icon>
          <div class="text-subtitle-1">二维码获取失败</div>
          <div class="text-body-2 text-grey">请点击刷新按钮重试</div>
        </div>
      </v-card-text>
      <v-divider></v-divider>
      <v-card-actions class="px-3 py-2">
        <v-btn color="grey" variant="text" @click="$emit('close')" size="small" prepend-icon="mdi-close">关闭</v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="$emit('refresh')" :disabled="aliQrDialog.loading" size="small"
          prepend-icon="mdi-refresh">
          刷新
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  aliQrDialog: { type: Object, required: true },
});

defineEmits(['refresh', 'close']);
</script>
