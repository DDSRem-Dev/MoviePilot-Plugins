<template>
  <v-dialog v-model="configGeneratorDialog.show" max-width="780" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-code-tags" color="primary" size="20" />
          <span>生成 Emby 反代 302 配置</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body">
        <div class="mb-3">
          <AppleSegmentedControl v-model="configGeneratorDialog.configType" :items="typeOptions" block />
        </div>

        <div class="p115-callout p115-callout--info mb-4">
          <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-1 flex-shrink-0" />
          <div v-if="configGeneratorDialog.configType === 'emby2alist'">
            <div class="font-weight-bold mb-1">emby2Alist 使用说明</div>
            <div>1. 此配置用于 emby2Alist 系列软件的 <code class="p115-mono">mediaPathMapping</code> 规则</div>
            <div>2. 将下方生成的配置复制到 emby2Alist 的配置文件数组中</div>
            <div>3. 自动匹配 STRM 中的挂载路径前缀并替换为插件 302 重定向地址（保留后续路径）</div>
          </div>
          <div v-else>
            <div class="font-weight-bold mb-1">Emby 302 反向代理插件使用说明</div>
            <div>1. 此配置用于 Emby 302 反向代理插件的「顶置路径规则」</div>
            <div>2. 将生成的配置复制到顶置路径规则中（每行一条：<code class="p115-mono">路径前缀 =&gt; 目标 URL</code>）</div>
            <div>3. 路径匹配前缀时会先替换为目标 URL 再执行 302 跳转</div>
          </div>
        </div>

        <v-row dense class="mb-2">
          <v-col cols="12" md="6">
            <v-text-field
              v-model="configGeneratorDialog.mountDir"
              label="媒体服务器网盘挂载目录"
              hint="对应配置中的 fuse_strm_mount_dir，例如：/emby/115"
              persistent-hint
              density="compact"
              variant="outlined"
              placeholder="/emby/115"
            />
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field
              v-model="configGeneratorDialog.moviepilotAddress"
              label="MoviePilot 地址"
              hint="对应配置中的 moviepilot_address"
              persistent-hint
              density="compact"
              variant="outlined"
              placeholder="http://localhost:3000"
            />
          </v-col>
        </v-row>

        <div class="mt-3">
          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-caption font-weight-bold">生成的配置代码</span>
            <span class="p115-badge p115-badge--blue">只读预览</span>
          </div>

          <div v-if="configGeneratorDialog.loading" class="d-flex flex-column align-center py-6">
            <v-progress-circular indeterminate color="primary" size="34" class="mb-2" />
            <div class="text-caption">正在生成配置...</div>
          </div>

          <v-textarea
            v-else
            v-model="configGeneratorDialog.generatedConfig"
            :hint="
              configGeneratorDialog.configType === 'emby_reverse_proxy'
                ? '复制此配置到 Emby 302 反向代理插件的顶置路径规则中'
                : '复制此配置到 emby2Alist 的 mediaPathMapping 数组中'
            "
            persistent-hint
            rows="7"
            variant="outlined"
            density="compact"
            readonly
            class="p115-mono"
          />
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">关闭</button>
        <div class="d-flex align-center gap-2">
          <button
            type="button"
            class="p115-btn p115-btn--tonal"
            :disabled="configGeneratorDialog.loading"
            @click="$emit('regenerate')"
          >
            <v-icon size="16" icon="mdi-refresh" />
            <span>重新生成</span>
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--primary"
            :disabled="configGeneratorDialog.loading || !configGeneratorDialog.generatedConfig"
            @click="$emit('copy')"
          >
            <v-icon size="16" icon="mdi-content-copy" />
            <span>复制配置</span>
          </button>
        </div>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

defineProps({
  configGeneratorDialog: { type: Object, required: true },
});

defineEmits(['close', 'copy', 'regenerate']);

const { dialogContentClass } = useThemeAdapter();

const typeOptions = [
  { label: 'emby2Alist 规则', value: 'emby2alist' },
  { label: 'Emby 302 反代顶置规则', value: 'emby_reverse_proxy' },
];
</script>
