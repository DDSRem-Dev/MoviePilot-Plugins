<template>
  <v-dialog v-model="donateDialog.show" max-width="600">
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-gift" class="mr-2" color="primary" size="small" />
        <span>支持作者 / 获取授权</span>
      </v-card-title>

      <v-card-text class="py-4">
        <v-alert type="success" variant="tonal" density="compact" class="mb-3" icon="mdi-information-outline">
          <span class="text-body-2">无论是否捐赠，插件功能均可正常使用。捐赠为自愿支持行为。</span>
        </v-alert>
        <v-alert v-if="donateDialog.error" type="error" density="compact" class="mb-3" variant="tonal" closable>
          {{ donateDialog.error }}
        </v-alert>

        <div v-if="donateDialog.loading" class="d-flex flex-column align-center py-3">
          <v-progress-circular indeterminate color="primary" class="mb-3"></v-progress-circular>
          <div>正在加载捐赠信息...</div>
        </div>

        <div v-else-if="donateDialog.donateInfo">
          <!-- 授权状态 -->
          <v-card variant="outlined" class="mb-4">
            <v-card-item>
              <v-card-title class="d-flex align-center">
                <v-icon icon="mdi-shield-check"
                  :color="donateDialog.authorizationStatus?.is_authorized ? 'success' : 'warning'"
                  class="mr-2"></v-icon>
                <span class="text-h6">授权状态</span>
              </v-card-title>
            </v-card-item>
            <v-card-text>
              <v-row v-if="!donateDialog.authorizationStatus">
                <v-col cols="12">
                  <div class="text-caption text-grey">暂无授权信息</div>
                </v-col>
              </v-row>
              <v-row v-else>
                <v-col cols="12" md="4">
                  <div class="d-flex flex-column">
                    <span class="text-caption text-grey-darken-1">授权状态</span>
                    <v-chip :color="donateDialog.authorizationStatus.is_authorized ? 'success' : 'warning'"
                      size="small" class="mt-1">
                      {{ donateDialog.authorizationStatus.is_authorized ? '已授权' : '未授权' }}
                    </v-chip>
                  </div>
                </v-col>
                <v-col cols="12" md="4" v-if="donateDialog.authorizationStatus.is_authorized">
                  <div class="d-flex flex-column">
                    <span class="text-caption text-grey-darken-1">授权类型</span>
                    <v-chip :color="donateDialog.authorizationStatus.is_permanent ? 'info' : 'default'" size="small"
                      class="mt-1">
                      {{ donateDialog.authorizationStatus.is_permanent ? '永久授权' : '临时授权' }}
                    </v-chip>
                  </div>
                </v-col>
                <v-col cols="12" md="4"
                  v-if="donateDialog.authorizationStatus.is_authorized && !donateDialog.authorizationStatus.is_permanent && donateDialog.authorizationStatus.authorization_expiration">
                  <div class="d-flex flex-column">
                    <span class="text-caption text-grey-darken-1">过期时间</span>
                    <span class="text-body-2 mt-1">{{
                      formatAuthorizationExpiration(donateDialog.authorizationStatus.authorization_expiration)
                    }}</span>
                  </div>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
            <div class="text-caption">
              捐赠后前往 <a :href="`https://${donateDialog.donateInfo.telegram_bot}`" target="_blank"
                style="color: inherit; text-decoration: underline;">Telegram Bot</a> 使用
              <code>{{ donateDialog.donateInfo.donate_command }}</code> 命令提交捐赠证明
            </div>
          </v-alert>

          <!-- 捐赠方式选择 -->
          <v-tabs v-model="donateDialog.activeTab" color="primary" class="mb-4">
            <v-tab v-if="donateDialog.donateInfo.wechat?.enabled" value="wechat">
              <v-icon start>mdi-wechat</v-icon>微信
            </v-tab>
            <v-tab v-if="donateDialog.donateInfo.alipay?.enabled" value="alipay">
              <v-icon start>mdi-wallet</v-icon>支付宝
            </v-tab>
          </v-tabs>

          <v-window v-model="donateDialog.activeTab" :touch="false">
            <!-- 微信捐赠 -->
            <v-window-item v-if="donateDialog.donateInfo.wechat?.enabled" value="wechat">
              <div class="d-flex flex-column align-center">
                <v-card flat class="border pa-2 mb-3">
                  <img v-if="donateDialog.donateInfo.wechat.qrcode" :src="donateDialog.donateInfo.wechat.qrcode"
                    width="280" height="280" alt="微信捐赠码" />
                  <div v-else class="d-flex flex-column align-center pa-8">
                    <v-icon icon="mdi-image-off" size="64" color="grey" class="mb-2"></v-icon>
                    <div class="text-caption text-grey">二维码未配置</div>
                  </div>
                </v-card>
                <div class="text-body-2 text-grey">使用微信扫描二维码进行捐赠</div>
              </div>
            </v-window-item>

            <!-- 支付宝捐赠 -->
            <v-window-item v-if="donateDialog.donateInfo.alipay?.enabled" value="alipay">
              <div class="d-flex flex-column align-center">
                <v-card flat class="border pa-2 mb-3">
                  <img v-if="donateDialog.donateInfo.alipay.qrcode" :src="donateDialog.donateInfo.alipay.qrcode"
                    width="280" height="280" alt="支付宝收款码" />
                  <div v-else class="d-flex flex-column align-center pa-8">
                    <v-icon icon="mdi-image-off" size="64" color="grey" class="mb-2"></v-icon>
                    <div class="text-caption text-grey">二维码未配置</div>
                  </div>
                </v-card>
                <div class="text-body-2 text-grey mb-2">使用支付宝扫描二维码进行捐赠</div>

                <!-- 支付宝红包口令方式 -->
                <div v-if="donateDialog.donateInfo.alipay?.redpack_enabled" class="w-100 mt-3">
                  <v-divider class="mb-3"></v-divider>
                  <v-alert type="info" variant="tonal" density="compact" icon="mdi-wallet-giftcard">
                    <div class="text-caption">
                      也可以使用支付宝红包口令，将口令发给机器人即可
                    </div>
                  </v-alert>
                </div>
              </div>
            </v-window-item>
          </v-window>
        </div>

        <div v-else class="d-flex flex-column align-center py-3">
          <v-icon icon="mdi-gift-off" size="64" color="grey" class="mb-3"></v-icon>
          <div class="text-subtitle-1">捐赠信息未配置</div>
          <div class="text-body-2 text-grey">请联系作者获取捐赠方式</div>
        </div>
      </v-card-text>

      <v-divider></v-divider>
      <v-card-actions class="px-3 py-2">
        <v-btn color="grey" variant="text" @click="$emit('close')" size="small" prepend-icon="mdi-close">
          关闭
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text"
          :href="`https://${donateDialog.donateInfo?.telegram_bot || 't.me/dds_oof_bot'}`" target="_blank"
          size="small" prepend-icon="mdi-telegram">
          前往 Telegram Bot
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  donateDialog: { type: Object, required: true },
  formatAuthorizationExpiration: { type: Function, required: true },
});

defineEmits(['close']);
</script>
