<template>
  <v-dialog v-model="configGeneratorDialog.show" max-width="900" scrollable>
    <v-card>
      <v-card-title class="d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-code-tags" class="mr-2" color="primary" size="small" />
        <span>生成 Emby 反代 302 配置</span>
      </v-card-title>
      <v-card-text class="pa-4">
        <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
          <div class="text-body-2 mb-1"><strong>使用说明：</strong></div>
          <div class="text-caption" v-if="configGeneratorDialog.configType === 'emby2alist'">
            <div class="mb-1">1. 此配置用于 emby2Alist 系列软件的 <code>mediaPathMapping</code> 规则</div>
            <div class="mb-1">2. 将生成的配置复制到 emby2Alist 的配置文件中</div>
            <div>3. 配置会自动匹配 strm 文件中的 <code>/emby/115</code> 路径并替换为插件重定向地址</div>
          </div>
          <div class="text-caption" v-else>
            <div class="mb-1">1. 此配置用于 Emby 302 反向代理插件的「顶置路径规则」</div>
            <div class="mb-1">2. 将生成的配置复制到 Emby 302 反向代理插件的顶置路径规则中（每行一条：路径前缀 => 目标 URL）</div>
            <div>3. 路径匹配前缀时会先替换为目标 URL 再 302 跳转</div>
          </div>
        </v-alert>

        <v-row>
          <v-col cols="12">
            <v-radio-group v-model="configGeneratorDialog.configType" label="配置类型" density="compact" hide-details
              class="mb-2">
              <v-radio label="emby2Alist mediaPathMapping" value="emby2alist"></v-radio>
              <v-radio label="Emby 302 反向代理 顶置路径规则" value="emby_reverse_proxy"></v-radio>
            </v-radio-group>
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12">
            <v-text-field v-model="configGeneratorDialog.mountDir" label="媒体服务器网盘挂载目录"
              hint="对应配置中的 fuse_strm_mount_dir，例如：/emby/115" persistent-hint density="compact" variant="outlined"
              placeholder="/emby/115"></v-text-field>
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12">
            <v-text-field v-model="configGeneratorDialog.moviepilotAddress" label="MoviePilot 地址"
              hint="对应配置中的 moviepilot_address" persistent-hint density="compact" variant="outlined"
              placeholder="http://localhost:3000"></v-text-field>
          </v-col>
        </v-row>

        <v-divider class="my-4"></v-divider>

        <div class="mb-2">
          <div class="text-body-2 mb-2"><strong>生成的配置：</strong></div>
          <div v-if="configGeneratorDialog.loading" class="d-flex flex-column align-center py-4">
            <v-progress-circular indeterminate color="primary" class="mb-3"></v-progress-circular>
            <div class="text-body-2 text-grey">正在生成配置...</div>
          </div>
          <v-textarea v-else v-model="configGeneratorDialog.generatedConfig" label="配置代码"
            :hint="configGeneratorDialog.configType === 'emby_reverse_proxy' ? '复制此配置到 Emby 302 反向代理插件的顶置路径规则中' : '复制此配置到 emby2Alist 的 mediaPathMapping 数组中'"
            persistent-hint rows="8" variant="outlined" density="compact" readonly class="font-monospace"
            style="font-family: 'Courier New', monospace;"></v-textarea>
        </div>

        <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
          <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
          <div class="text-caption" v-if="configGeneratorDialog.configType === 'emby2alist'">
            <div>• 规则：将 <code>/emby/115</code> 替换为插件重定向地址（保留后续路径）</div>
          </div>
          <div class="text-caption" v-else>
            <div>• 规则：路径前缀 => 目标 URL，匹配前缀时先替换再 302</div>
          </div>
        </v-alert>
      </v-card-text>
      <v-divider></v-divider>
      <v-card-actions class="px-3 py-2">
        <v-btn color="grey" variant="text" @click="$emit('close')" size="small" prepend-icon="mdi-close">关闭</v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="$emit('copy')" size="small"
          prepend-icon="mdi-content-copy"
          :disabled="configGeneratorDialog.loading || !configGeneratorDialog.generatedConfig">
          复制配置
        </v-btn>
        <v-btn color="primary" variant="text" @click="$emit('regenerate')" size="small" prepend-icon="mdi-refresh"
          :disabled="configGeneratorDialog.loading" :loading="configGeneratorDialog.loading">
          重新生成
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  configGeneratorDialog: { type: Object, required: true },
});

defineEmits(['close', 'copy', 'regenerate']);
</script>
