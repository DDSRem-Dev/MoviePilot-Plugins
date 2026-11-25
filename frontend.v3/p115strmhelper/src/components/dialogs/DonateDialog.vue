<template>
  <v-dialog v-model="donateDialog.show" max-width="560" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-gift-outline" color="secondary" size="20" />
          <span>支持作者 / 授权状态</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body">
        <div class="p115-callout p115-callout--success mb-3">
          <v-icon size="18" color="success" icon="mdi-heart-outline" />
          <span>无论是否捐赠，插件功能均可正常使用。捐赠为自愿支持行为。</span>
        </div>

        <div v-if="donateDialog.error" class="p115-callout p115-callout--error mb-3">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ donateDialog.error }}</span>
        </div>

        <div v-if="donateDialog.loading" class="d-flex flex-column align-center py-6">
          <v-progress-circular indeterminate color="primary" size="38" class="mb-3" />
          <div class="text-body-2">正在加载捐赠与授权信息...</div>
        </div>

        <template v-else-if="donateDialog.donateInfo">
          <!-- Authorization Status Bento Card -->
          <AppleBentoCard title="当前设备授权状态" icon="mdi-shield-check-outline" class="mb-4">
            <div v-if="!donateDialog.authorizationStatus" class="text-caption opacity-70">
              暂无授权信息
            </div>
            <div v-else class="p115-auth-grid">
              <div class="p115-auth-cell">
                <span class="p115-auth-label">授权状态</span>
                <span
                  class="p115-badge"
                  :class="donateDialog.authorizationStatus.is_authorized ? 'p115-badge--green' : 'p115-badge--amber'"
                >
                  <span class="p115-badge-dot" />
                  {{ donateDialog.authorizationStatus.is_authorized ? '已授权' : '未授权' }}
                </span>
              </div>

              <div v-if="donateDialog.authorizationStatus.is_authorized" class="p115-auth-cell">
                <span class="p115-auth-label">授权类型</span>
                <span
                  class="p115-badge"
                  :class="donateDialog.authorizationStatus.is_permanent ? 'p115-badge--pink' : 'p115-badge--blue'"
                >
                  {{ donateDialog.authorizationStatus.is_permanent ? '永久授权' : '临时授权' }}
                </span>
              </div>

              <div
                v-if="
                  donateDialog.authorizationStatus.is_authorized &&
                  !donateDialog.authorizationStatus.is_permanent &&
                  donateDialog.authorizationStatus.authorization_expiration
                "
                class="p115-auth-cell"
              >
                <span class="p115-auth-label">过期时间</span>
                <span class="p115-tabular text-caption font-weight-medium">
                  {{ formatAuthorizationExpiration(donateDialog.authorizationStatus.authorization_expiration) }}
                </span>
              </div>
            </div>
          </AppleBentoCard>

          <div class="p115-callout p115-callout--info mb-4">
            <v-icon size="18" color="primary" icon="mdi-send-circle-outline" />
            <div>
              捐赠后可前往
              <a
                :href="`https://${donateDialog.donateInfo.telegram_bot}`"
                target="_blank"
                rel="noopener noreferrer"
                class="p115-link"
              >
                Telegram Bot
              </a>
              发送 <code class="p115-mono">{{ donateDialog.donateInfo.donate_command }}</code> 提交捐赠证明
            </div>
          </div>

          <div v-if="payItems.length > 0" class="d-flex flex-column align-center">
            <AppleSegmentedControl v-model="donateDialog.activeTab" :items="payItems" class="mb-4" />

            <template v-if="donateDialog.activeTab === 'wechat' && donateDialog.donateInfo.wechat?.enabled">
              <div class="p115-bezel p115-donate-qr">
                <div class="p115-bezel-core p115-donate-qr-core">
                  <img
                    v-if="donateDialog.donateInfo.wechat.qrcode"
                    :src="donateDialog.donateInfo.wechat.qrcode"
                    width="240"
                    height="240"
                    alt="微信赞赏码"
                  />
                  <div v-else class="pa-8 text-center text-caption">二维码未配置</div>
                </div>
              </div>
              <div class="text-caption mt-2 opacity-75">使用微信扫描上方二维码进行支持</div>
            </template>

            <template v-if="donateDialog.activeTab === 'alipay' && donateDialog.donateInfo.alipay?.enabled">
              <div class="p115-bezel p115-donate-qr">
                <div class="p115-bezel-core p115-donate-qr-core">
                  <img
                    v-if="donateDialog.donateInfo.alipay.qrcode"
                    :src="donateDialog.donateInfo.alipay.qrcode"
                    width="240"
                    height="240"
                    alt="支付宝收款码"
                  />
                  <div v-else class="pa-8 text-center text-caption">二维码未配置</div>
                </div>
              </div>
              <div class="text-caption mt-2 opacity-75">使用支付宝扫描上方二维码进行支持</div>

              <div v-if="donateDialog.donateInfo.alipay?.redpack_enabled" class="p115-callout p115-callout--pink mt-3 w-100">
                <v-icon size="18" color="secondary" icon="mdi-wallet-giftcard" />
                <span>同样支持支付宝口令红包：生成红包口令后直接私聊发送给 Telegram 机器人即可</span>
              </div>
            </template>
          </div>
        </template>

        <div v-else class="d-flex flex-column align-center py-6 opacity-70">
          <v-icon icon="mdi-gift-off-outline" size="48" class="mb-2" />
          <div class="text-body-2">捐赠信息暂未配置，请联系作者获取</div>
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">关闭</button>
        <a
          class="p115-btn p115-btn--primary"
          :href="`https://${donateDialog.donateInfo?.telegram_bot || 't.me/dds_oof_bot'}`"
          target="_blank"
          rel="noopener noreferrer"
        >
          <v-icon size="16" icon="mdi-send" />
          <span>前往 Telegram Bot</span>
        </a>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed } from 'vue';
import AppleBentoCard from '../ui/AppleBentoCard.vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const props = defineProps({
  donateDialog: { type: Object, required: true },
  formatAuthorizationExpiration: { type: Function, required: true },
});

defineEmits(['close']);

const { dialogContentClass } = useThemeAdapter();

const payItems = computed(() => {
  const list = [];
  if (props.donateDialog.donateInfo?.wechat?.enabled) {
    list.push({ label: '微信支持', value: 'wechat', icon: 'mdi-wechat' });
  }
  if (props.donateDialog.donateInfo?.alipay?.enabled) {
    list.push({ label: '支付宝支持', value: 'alipay', icon: 'mdi-wallet-outline' });
  }
  return list;
});
</script>

<style scoped>
.p115-auth-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
}

.p115-auth-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
}

.p115-auth-label {
  font-size: 0.72rem;
  color: var(--p115-text-tertiary);
}

.p115-donate-qr {
  padding: 6px;
  border-radius: 22px;
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.25), rgba(245, 171, 185, 0.25));
}

.p115-donate-qr-core {
  padding: 12px;
  border-radius: 16px;
  background: #ffffff !important;
}

.p115-donate-qr-core img {
  display: block;
  border-radius: 8px;
}

.p115-link {
  color: var(--p115-blue-ink);
  font-weight: 600;
  text-decoration: underline;
}
</style>
