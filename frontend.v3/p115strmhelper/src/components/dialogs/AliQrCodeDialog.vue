<template>
  <v-dialog v-model="aliQrDialog.show" max-width="430" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-qrcode" color="primary" size="20" />
          <span>阿里云盘扫码登录</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body p115-ali-qr-body">
        <div v-if="aliQrDialog.error" class="p115-callout p115-callout--error mb-3 w-100 text-left">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ aliQrDialog.error }}</span>
        </div>

        <div v-if="aliQrDialog.loading" class="p115-ali-qr-state">
          <v-progress-circular indeterminate color="primary" size="38" />
          <span>正在获取二维码...</span>
        </div>

        <div v-else-if="aliQrDialog.qrcode" class="p115-ali-qr-showcase">
          <div class="p115-bezel p115-ali-frame">
            <div class="p115-bezel-core p115-ali-frame-core">
              <img :src="aliQrDialog.qrcode" width="212" height="212" alt="阿里云盘二维码" class="p115-ali-img" />
            </div>
          </div>
          <div class="p115-badge p115-badge--pink mt-3">
            <span class="p115-badge-dot" />
            <span>{{ aliQrDialog.status }}</span>
          </div>
          <div class="p115-ali-tips">请使用阿里云盘 App 扫描二维码授权登录</div>
        </div>

        <div v-else class="p115-ali-qr-state">
          <v-icon icon="mdi-qrcode-off" size="52" class="opacity-40" />
          <div class="font-weight-medium">二维码获取失败</div>
          <div class="p115-ali-tips">请点击下方「刷新」按钮重试</div>
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">
          关闭
        </button>
        <button
          type="button"
          class="p115-btn p115-btn--primary"
          :disabled="aliQrDialog.loading"
          @click="$emit('refresh')"
        >
          <v-icon size="16" icon="mdi-refresh" />
          <span>刷新</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

defineProps({
  aliQrDialog: { type: Object, required: true },
});

defineEmits(['refresh', 'close']);

const { dialogContentClass } = useThemeAdapter();
</script>

<style scoped>
.p115-ali-qr-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.p115-ali-qr-showcase {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.p115-ali-frame {
  padding: 6px;
  border-radius: 22px;
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.25), rgba(245, 171, 185, 0.25));
}

.p115-ali-frame-core {
  padding: 12px;
  border-radius: 16px;
  background: #ffffff !important;
}

.p115-ali-img {
  display: block;
  border-radius: 8px;
}

.p115-ali-tips {
  font-size: 0.78rem;
  color: var(--p115-text-secondary);
  margin-top: 6px;
}

.p115-ali-qr-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 12px;
  font-size: 0.85rem;
  color: var(--p115-text-secondary);
}
</style>
