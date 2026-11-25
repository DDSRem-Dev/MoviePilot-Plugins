<template>
  <v-dialog v-model="qrDialog.show" max-width="460" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-qrcode-scan" color="primary" size="20" />
          <span>115网盘扫码登录</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body p115-qr-body">
        <div class="p115-qr-seg-wrap">
          <div class="p115-qr-caption">请选择扫码客户端渠道</div>
          <AppleSegmentedControl v-model="qrDialog.clientType" :items="clientItems" />
        </div>

        <div v-if="qrDialog.error" class="p115-callout p115-callout--error mb-3 w-100 text-left">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ qrDialog.error }}</span>
        </div>

        <div v-if="qrDialog.loading" class="p115-qr-state">
          <v-progress-circular indeterminate color="primary" size="38" />
          <span>正在获取二维码...</span>
        </div>

        <div v-else-if="qrDialog.qrcode" class="p115-qr-showcase">
          <div class="p115-bezel p115-qr-frame">
            <div class="p115-bezel-core p115-qr-frame-core">
              <img :src="qrDialog.qrcode" width="212" height="212" alt="115登录二维码" class="p115-qr-img" />
            </div>
          </div>

          <div class="p115-badge p115-badge--blue mt-3">
            <span class="p115-badge-dot" />
            <span>{{ qrDialog.status }}</span>
          </div>
          <div class="p115-qr-tips">{{ qrDialog.tips }}</div>
        </div>

        <div v-else class="p115-qr-state">
          <v-icon icon="mdi-qrcode-remove" size="52" class="opacity-40" />
          <div class="font-weight-medium">二维码获取失败</div>
          <div class="p115-qr-tips">请点击下方「刷新二维码」重试；若多次失败请检查网络连接</div>
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">
          关闭
        </button>
        <button
          type="button"
          class="p115-btn p115-btn--primary"
          :disabled="qrDialog.loading"
          @click="$emit('refresh')"
        >
          <v-icon size="16" icon="mdi-refresh" />
          <span>刷新二维码</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed } from 'vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const props = defineProps({
  qrDialog: { type: Object, required: true },
  clientTypes: { type: Array, required: true },
});

defineEmits(['refresh', 'close']);

const { dialogContentClass } = useThemeAdapter();

const clientItems = computed(() =>
  (props.clientTypes || []).map((t) => ({
    label: t.label,
    value: t.value,
  })),
);
</script>

<style scoped>
.p115-qr-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.p115-qr-seg-wrap {
  width: 100%;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.p115-qr-caption {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--p115-text-secondary);
}

.p115-qr-showcase {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.p115-qr-frame {
  padding: 6px;
  border-radius: 22px;
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.25), rgba(245, 171, 185, 0.25));
}

.p115-qr-frame-core {
  padding: 12px;
  border-radius: 16px;
  background: #ffffff !important;
  align-items: center;
  justify-content: center;
}

.p115-qr-img {
  display: block;
  border-radius: 8px;
}

.p115-qr-tips {
  font-size: 0.78rem;
  color: var(--p115-text-secondary);
  margin-top: 6px;
}

.p115-qr-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 12px;
  font-size: 0.85rem;
  color: var(--p115-text-secondary);
}
</style>
