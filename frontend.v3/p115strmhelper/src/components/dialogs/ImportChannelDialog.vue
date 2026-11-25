<template>
  <v-dialog v-model="importDialog.show" max-width="580" persistent :content-class="dialogContentClass">
    <v-card flat class="p115-sheet">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon icon="mdi-code-json" color="primary" size="20" />
          <span>一键导入 Telegram 频道配置</span>
        </div>
        <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <div class="p115-sheet-body">
        <div v-if="importDialog.error" class="p115-callout p115-callout--error mb-3">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
          <span>{{ importDialog.error }}</span>
        </div>

        <div class="p115-callout p115-callout--info mb-3">
          <v-icon size="18" color="primary" icon="mdi-information-outline" />
          <div>
            <div>请粘贴 JSON 数组格式的频道列表，示例结构：</div>
            <code class="p115-mono d-block mt-1">[{"name":"名称1", "id":"id1"}, {"name":"名称2", "id":"id2"}]</code>
          </div>
        </div>

        <v-textarea
          v-model="importDialog.jsonText"
          label="频道配置 JSON"
          variant="outlined"
          rows="7"
          auto-grow
          hide-details="auto"
          class="p115-mono"
          placeholder='[{"name":"Lsp115","id":"Lsp115"}]'
        />
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">取消</button>
        <button type="button" class="p115-btn p115-btn--primary" @click="$emit('confirm')">
          <v-icon size="16" icon="mdi-check" />
          <span>确认导入</span>
        </button>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

defineProps({
  importDialog: { type: Object, required: true },
});

defineEmits(['close', 'confirm']);

const { dialogContentClass } = useThemeAdapter();
</script>
