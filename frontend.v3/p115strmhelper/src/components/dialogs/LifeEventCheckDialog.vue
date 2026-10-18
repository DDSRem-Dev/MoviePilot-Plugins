<template>
  <v-dialog v-model="lifeEventCheckDialog.show" max-width="1000" scrollable persistent>
    <v-card>
      <v-card-title class="d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-bug-check" class="mr-2" color="primary" size="small" />
        <span>115生活事件故障检查</span>
      </v-card-title>
      <v-card-text class="px-3 py-3">
        <div class="mb-3">
          <div class="text-caption text-grey mb-1">拉取指定时间内的全部数据（可选）</div>
          <div class="life-event-check-start-time-wrapper">
            <input v-model="lifeEventCheckDialog.startTime" type="datetime-local"
              class="life-event-check-datetime-input" aria-label="开始时间" />
            <v-btn v-if="lifeEventCheckDialog.startTime" icon size="x-small" variant="text"
              class="life-event-check-clear-btn" aria-label="清除时间" @click="lifeEventCheckDialog.startTime = ''">
              <v-icon icon="mdi-close" size="small" />
            </v-btn>
          </div>
          <div class="text-caption text-grey mt-1">填写后点击检查，将额外拉取从该时间起的全部生活事件并显示数量</div>
        </div>
        <v-alert v-if="lifeEventCheckDialog.error" type="error" density="compact" class="mb-3" variant="tonal"
          closable>
          {{ lifeEventCheckDialog.error }}
        </v-alert>
        <div v-if="lifeEventCheckDialog.loading" class="d-flex flex-column align-center py-3">
          <v-progress-circular indeterminate color="primary" size="48" class="mb-3"></v-progress-circular>
          <div class="text-body-2 text-grey">正在检查...</div>
        </div>
        <div v-else-if="lifeEventCheckDialog.result">
          <v-alert :type="lifeEventCheckDialog.result.data?.success ? 'success' : 'warning'" density="compact"
            class="mb-3" variant="tonal">
            <div class="text-subtitle-2 mb-1">
              <v-icon :icon="lifeEventCheckDialog.result.data?.success ? 'mdi-check-circle' : 'mdi-alert-circle'"
                class="mr-1" size="small"></v-icon>
              {{ lifeEventCheckDialog.result.msg }}
            </div>
            <div v-if="lifeEventCheckDialog.result.data?.error_messages?.length" class="mt-2">
              <div class="text-caption mb-1"><strong>发现的问题：</strong></div>
              <div v-for="(msg, idx) in lifeEventCheckDialog.result.data.error_messages" :key="idx"
                class="text-caption d-flex align-start mb-1">
                <v-icon icon="mdi-alert" size="x-small" class="mr-1 mt-1" color="warning"></v-icon>
                <span>{{ msg }}</span>
              </div>
            </div>
          </v-alert>

          <div class="mb-3">
            <div class="d-flex align-center mb-2">
              <v-icon icon="mdi-information" size="small" class="mr-2" color="info"></v-icon>
              <strong class="text-body-2">检查结果摘要</strong>
              <v-spacer></v-spacer>
              <v-btn size="small" variant="outlined" prepend-icon="mdi-content-copy" @click="$emit('copy-debug')">
                复制调试信息
              </v-btn>
            </div>
            <v-card variant="outlined" class="pa-3">
              <v-row dense>
                <v-col cols="12" md="6">
                  <div class="d-flex align-center mb-2">
                    <v-icon
                      :icon="lifeEventCheckDialog.result.data?.summary?.plugin_enabled ? 'mdi-check-circle' : 'mdi-close-circle'"
                      :color="lifeEventCheckDialog.result.data?.summary?.plugin_enabled ? 'success' : 'error'"
                      size="small" class="mr-2"></v-icon>
                    <span class="text-caption">插件启用:
                      <strong>{{ lifeEventCheckDialog.result.data?.summary?.plugin_enabled ? '是' : '否' }}</strong>
                    </span>
                  </div>
                </v-col>
                <v-col cols="12" md="6">
                  <div class="d-flex align-center mb-2">
                    <v-icon
                      :icon="lifeEventCheckDialog.result.data?.summary?.client_initialized ? 'mdi-check-circle' : 'mdi-close-circle'"
                      :color="lifeEventCheckDialog.result.data?.summary?.client_initialized ? 'success' : 'error'"
                      size="small" class="mr-2"></v-icon>
                    <span class="text-caption">客户端初始化:
                      <strong>{{ lifeEventCheckDialog.result.data?.summary?.client_initialized ? '是' : '否' }}</strong>
                    </span>
                  </div>
                </v-col>
                <v-col cols="12" md="6">
                  <div class="d-flex align-center mb-2">
                    <v-icon
                      :icon="lifeEventCheckDialog.result.data?.summary?.monitorlife_initialized ? 'mdi-check-circle' : 'mdi-close-circle'"
                      :color="lifeEventCheckDialog.result.data?.summary?.monitorlife_initialized ? 'success' : 'error'"
                      size="small" class="mr-2"></v-icon>
                    <span class="text-caption">MonitorLife初始化:
                      <strong>{{ lifeEventCheckDialog.result.data?.summary?.monitorlife_initialized ? '是' : '否'
                      }}</strong>
                    </span>
                  </div>
                </v-col>
                <v-col cols="12" md="6">
                  <div class="d-flex align-center mb-2">
                    <v-icon
                      :icon="lifeEventCheckDialog.result.data?.summary?.thread_running ? 'mdi-check-circle' : 'mdi-close-circle'"
                      :color="lifeEventCheckDialog.result.data?.summary?.thread_running ? 'success' : 'error'"
                      size="small" class="mr-2"></v-icon>
                    <span class="text-caption">线程运行:
                      <strong>{{ lifeEventCheckDialog.result.data?.summary?.thread_running ? '是' : '否' }}</strong>
                    </span>
                  </div>
                </v-col>
                <v-col cols="12">
                  <div class="d-flex align-center mb-2">
                    <v-icon
                      :icon="lifeEventCheckDialog.result.data?.summary?.config_valid ? 'mdi-check-circle' : 'mdi-close-circle'"
                      :color="lifeEventCheckDialog.result.data?.summary?.config_valid ? 'success' : 'error'"
                      size="small" class="mr-2"></v-icon>
                    <span class="text-caption">配置有效:
                      <strong>{{ lifeEventCheckDialog.result.data?.summary?.config_valid ? '是' : '否' }}</strong>
                    </span>
                  </div>
                </v-col>
              </v-row>
            </v-card>
          </div>

          <div>
            <div class="d-flex align-center mb-2">
              <v-icon icon="mdi-code-tags" size="small" class="mr-2" color="primary"></v-icon>
              <strong class="text-body-2">详细调试信息</strong>
            </div>
            <v-textarea :model-value="lifeEventCheckDialog.result.data?.debug_info || ''" readonly variant="outlined"
              rows="15" auto-grow class="text-caption font-monospace debug-info-textarea"
              style="font-size: 0.75rem; line-height: 1.6; white-space: pre-wrap;" hint="此信息可用于开发者诊断问题，请复制给开发者"
              persistent-hint></v-textarea>
          </div>
        </div>
      </v-card-text>
      <v-divider></v-divider>
      <v-card-actions class="px-3 py-2">
        <v-btn color="grey" variant="text" @click="$emit('close')" size="small" prepend-icon="mdi-close">关闭</v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="$emit('check')" :disabled="lifeEventCheckDialog.loading"
          size="small" prepend-icon="mdi-refresh">
          重新检查
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  lifeEventCheckDialog: { type: Object, required: true },
});

defineEmits(['check', 'close', 'copy-debug']);
</script>

<style scoped>
.life-event-check-start-time-wrapper {
  display: flex;
  align-items: center;
  gap: 4px;
}

.life-event-check-datetime-input {
  border: 1px solid rgba(0, 0, 0, 0.23);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 0.875rem;
  color: inherit;
  background: transparent;
  outline: none;
  cursor: pointer;
}

.life-event-check-datetime-input:focus {
  border-color: rgb(var(--v-theme-primary));
  box-shadow: 0 0 0 1px rgb(var(--v-theme-primary));
}
</style>
