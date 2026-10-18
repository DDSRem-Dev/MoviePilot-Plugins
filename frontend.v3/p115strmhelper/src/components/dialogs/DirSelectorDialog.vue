<template>
  <v-dialog v-model="dirDialog.show" max-width="800">
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-lighten-5">
        <v-icon :icon="dirDialog.isLocal ? 'mdi-folder-search' : 'mdi-folder-network'" class="mr-2" color="primary" />
        <span>{{ dirDialog.isLocal ? '选择本地目录' : '选择网盘目录' }}</span>
      </v-card-title>

      <v-card-text class="px-3 py-2">
        <div v-if="dirDialog.loading" class="d-flex justify-center my-3">
          <v-progress-circular indeterminate color="primary"></v-progress-circular>
        </div>

        <div v-else>
          <!-- 当前路径显示 -->
          <v-text-field v-model="dirDialog.currentPath" label="当前路径" variant="outlined" density="compact" class="mb-2"
            @keyup.enter="$emit('load-dir')"></v-text-field>

          <!-- 文件列表 -->
          <v-list class="border rounded" max-height="300px" overflow-y="auto">
            <v-list-item
              v-if="dirDialog.currentPath !== '/' && dirDialog.currentPath !== 'C:\\' && dirDialog.currentPath !== 'C:/'"
              @click="$emit('navigate-up')" class="py-1">
              <template v-slot:prepend>
                <v-icon icon="mdi-arrow-up" size="small" class="mr-2" color="grey" />
              </template>
              <v-list-item-title class="text-body-2">上级目录</v-list-item-title>
              <v-list-item-subtitle>..</v-list-item-subtitle>
            </v-list-item>

            <v-list-item v-for="(item, index) in dirDialog.items" :key="index" @click="$emit('select-dir', item)"
              :disabled="!item.is_dir" class="py-1">
              <template v-slot:prepend>
                <v-icon :icon="item.is_dir ? 'mdi-folder' : 'mdi-file'" size="small" class="mr-2"
                  :color="item.is_dir ? 'amber-darken-2' : 'blue'" />
              </template>
              <v-list-item-title class="text-body-2">{{ item.name }}</v-list-item-title>
            </v-list-item>

            <v-list-item v-if="!dirDialog.items.length" class="py-2 text-center">
              <v-list-item-title class="text-body-2 text-grey">该目录为空或访问受限</v-list-item-title>
            </v-list-item>
          </v-list>
        </div>

        <v-alert v-if="disableRoot && dirDialog.currentPath === '/' && !dirDialog.isLocal" type="warning"
          density="compact" class="mt-2 text-caption" variant="tonal" icon="mdi-alert-circle-outline">
          115离线下载不支持选择根目录，请选择或进入一个子目录。
        </v-alert>

        <v-alert v-if="dirDialog.error" type="error" density="compact" class="mt-2 text-caption" variant="tonal">
          {{ dirDialog.error }}
        </v-alert>
      </v-card-text>

      <v-card-actions class="px-3 py-2">
        <v-spacer></v-spacer>
        <v-btn color="primary" @click="$emit('confirm')"
          :disabled="!dirDialog.currentPath || dirDialog.loading || (disableRoot && dirDialog.currentPath === '/' && !dirDialog.isLocal)"
          variant="text" size="small">
          选择当前目录
        </v-btn>
        <v-btn color="grey" @click="$emit('close')" variant="text" size="small">
          取消
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
defineProps({
  dirDialog: { type: Object, required: true },
  disableRoot: { type: Boolean, default: false },
});

defineEmits(['load-dir', 'navigate-up', 'select-dir', 'confirm', 'close']);
</script>
