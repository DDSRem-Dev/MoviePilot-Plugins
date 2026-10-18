<template>
  <v-dialog v-model="importDialog.show" max-width="600" persistent>
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon icon="mdi-import" class="mr-2" color="primary" size="small" />
        <span>一键导入频道配置</span>
      </v-card-title>
      <v-card-text class="py-4">
        <v-alert v-if="importDialog.error" type="error" density="compact" class="mb-3" variant="tonal" closable>
          {{ importDialog.error }}
        </v-alert>
        <p class="text-caption mb-2 text-grey-darken-1">
          请在此处粘贴JSON格式的频道列表。格式应为：<br>
          <code>[{"name":"名称1", "id":"id1"}, {"name":"名称2", "id":"id2"}]</code>
        </p>
        <v-textarea v-model="importDialog.jsonText" label="频道配置JSON" variant="outlined" rows="8" auto-grow
          hide-details="auto" placeholder='[{"name":"Lsp115","id":"Lsp115"}]'></v-textarea>
      </v-card-text>
      <v-divider></v-divider>
      <v-card-actions class="px-3 py-2">
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="$emit('close')" size="small">
          取消
        </v-btn>
        <v-btn color="primary" variant="text" @click="$emit('confirm')" size="small">
          确认导入
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  importDialog: { type: Object, required: true },
});

defineEmits(['close', 'confirm']);
</script>
