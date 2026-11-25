<template>
  <v-dialog v-model="dirDialog.show" max-width="680" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet p115-sheet--workspace">
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <v-icon
            :icon="dirDialog.isLocal ? 'mdi-folder-search-outline' : 'mdi-cloud-search-outline'"
            :color="dirDialog.isLocal ? 'primary' : 'secondary'"
            size="20"
          />
          <span>{{ dirDialog.isLocal ? '选择本地目录' : '选择 115 网盘目录' }}</span>
          <span class="p115-badge" :class="dirDialog.isLocal ? 'p115-badge--blue' : 'p115-badge--pink'">
            {{ dirDialog.isLocal ? 'Local' : '115 Cloud' }}
          </span>
        </div>

        <div class="p115-dir-head-tools">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            :title="editPathMode ? '切换为面包屑导航' : '手动输入或粘贴完整路径'"
            @click="editPathMode = !editPathMode"
          >
            <v-icon size="14" :icon="editPathMode ? 'mdi-apple-finder' : 'mdi-form-textbox'" />
            <span>{{ editPathMode ? '面包屑' : '输入路径' }}</span>
          </button>
          <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" aria-label="关闭" @click="$emit('close')">
            <v-icon size="18" icon="mdi-close" />
          </button>
        </div>
      </div>

      <div class="p115-sheet-body">
        <!-- Finder Breadcrumbs OR Direct Path Input -->
        <div v-if="editPathMode" class="p115-dir-path-input">
          <v-text-field
            v-model="dirDialog.currentPath"
            label="当前目录完整路径（按回车跳转）"
            variant="outlined"
            density="compact"
            hide-details
            @keyup.enter="$emit('load-dir')"
          >
            <template #append-inner>
              <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="$emit('load-dir')">
                跳转
              </button>
            </template>
          </v-text-field>
        </div>

        <div v-else class="p115-crumb-bar">
          <button
            type="button"
            class="p115-crumb"
            :class="{ 'p115-crumb--active': breadcrumbs.length === 0 }"
            @click="jumpToCrumb(rootToken)"
          >
            <v-icon size="14" :icon="dirDialog.isLocal ? 'mdi-harddisk' : 'mdi-cloud-outline'" />
            <span>{{ rootToken }}</span>
          </button>

          <template v-for="(crumb, idx) in breadcrumbs" :key="crumb.fullPath">
            <span class="p115-crumb-sep">›</span>
            <button
              type="button"
              class="p115-crumb"
              :class="{ 'p115-crumb--active': idx === breadcrumbs.length - 1 }"
              @click="jumpToCrumb(crumb.fullPath)"
            >
              {{ crumb.label }}
            </button>
          </template>
        </div>

        <!-- Instant Client-side Folder Filter -->
        <div class="p115-dir-filter">
          <v-icon size="16" icon="mdi-magnify" class="p115-dir-filter-icon" />
          <input
            v-model="filterQuery"
            type="text"
            class="p115-dir-filter-input"
            placeholder="在当前目录下筛选文件夹..."
          />
          <button
            v-if="filterQuery"
            type="button"
            class="p115-dir-filter-clear"
            aria-label="清空筛选"
            @click="filterQuery = ''"
          >
            <v-icon size="14" icon="mdi-close-circle" />
          </button>
        </div>

        <!-- Loading State -->
        <div v-if="dirDialog.loading" class="p115-dir-loading">
          <v-progress-circular indeterminate color="primary" size="32" />
          <span>正在读取目录列表...</span>
        </div>

        <!-- Finder Folder List -->
        <div v-else class="p115-finder-box">
          <button
            v-if="canGoUp"
            type="button"
            class="p115-finder-row p115-finder-row--up"
            @click="handleNavigateUp"
          >
            <span class="p115-finder-row-left">
              <span class="p115-folder-badge p115-folder-badge--up">
                <v-icon size="16" icon="mdi-arrow-up" />
              </span>
              <span class="p115-finder-name">返回上级目录</span>
            </span>
            <span class="p115-mono p115-finder-hint">..</span>
          </button>

          <button
            v-for="(item, index) in filteredItems"
            :key="item.path || index"
            type="button"
            class="p115-finder-row"
            :disabled="!item.is_dir"
            @click="handleSelectDir(item)"
          >
            <span class="p115-finder-row-left">
              <span class="p115-folder-badge" :class="dirDialog.isLocal ? '' : 'p115-folder-badge--cloud'">
                <v-icon size="16" :icon="item.is_dir ? 'mdi-folder' : 'mdi-file-outline'" />
              </span>
              <span class="p115-finder-name">{{ item.name }}</span>
            </span>
            <v-icon size="16" icon="mdi-chevron-right" class="p115-finder-chevron" />
          </button>

          <div v-if="!filteredItems.length" class="p115-finder-empty">
            <v-icon size="28" icon="mdi-folder-open-outline" class="mb-1 opacity-50" />
            <div>{{ filterQuery ? '没有匹配筛选条件的子目录' : '当前目录没有子文件夹或访问受限' }}</div>
          </div>
        </div>

        <div
          v-if="disableRoot && dirDialog.currentPath === '/' && !dirDialog.isLocal"
          class="p115-callout p115-callout--warn mt-3"
        >
          <v-icon size="18" color="warning" icon="mdi-alert-circle-outline" />
          <span>115离线下载不支持选择根目录，请选择或进入一个子目录。</span>
        </div>

        <div v-if="dirDialog.error" class="p115-callout p115-callout--error mt-3">
          <v-icon size="18" color="error" icon="mdi-close-circle-outline" />
          <span>{{ dirDialog.error }}</span>
        </div>
      </div>

      <div class="p115-sheet-footer">
        <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">
          取消
        </button>

        <div class="p115-dir-footer-right">
          <span class="p115-dir-selected-preview p115-mono" :title="dirDialog.currentPath">
            {{ dirDialog.currentPath || '/' }}
          </span>
          <button
            type="button"
            class="p115-btn p115-btn--primary"
            :disabled="
              !dirDialog.currentPath ||
              dirDialog.loading ||
              (disableRoot && dirDialog.currentPath === '/' && !dirDialog.isLocal)
            "
            @click="$emit('confirm')"
          >
            <v-icon size="16" icon="mdi-check" />
            <span>选择当前目录</span>
          </button>
        </div>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const props = defineProps({
  dirDialog: { type: Object, required: true },
  disableRoot: { type: Boolean, default: false },
});

const emit = defineEmits(['load-dir', 'navigate-up', 'select-dir', 'confirm', 'close']);

const { dialogContentClass } = useThemeAdapter();

const filterQuery = ref('');
const editPathMode = ref(false);

watch(
  () => props.dirDialog.currentPath,
  () => {
    filterQuery.value = '';
  },
);

const canGoUp = computed(() => {
  const p = props.dirDialog.currentPath;
  return p && p !== '/' && p !== 'C:\\' && p !== 'C:/';
});

const rootToken = computed(() => {
  const p = String(props.dirDialog.currentPath || '/').replace(/\\/g, '/');
  const winMatch = p.match(/^([a-zA-Z]:)\/?/);
  return winMatch ? `${winMatch[1]}/` : '/';
});

const breadcrumbs = computed(() => {
  const raw = String(props.dirDialog.currentPath || '/').replace(/\\/g, '/');
  const isWin = /^[a-zA-Z]:/.test(raw);
  const stripped = isWin ? raw.replace(/^[a-zA-Z]:\/?/, '') : raw.replace(/^\/+/, '');
  const parts = stripped.split('/').filter(Boolean);
  let acc = isWin ? rootToken.value.replace(/\/$/, '') : '';
  return parts.map((seg) => {
    acc = `${acc}/${seg}`;
    return {
      label: seg,
      fullPath: acc,
    };
  });
});

const filteredItems = computed(() => {
  const items = Array.isArray(props.dirDialog.items) ? props.dirDialog.items : [];
  const q = filterQuery.value.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => String(item.name || '').toLowerCase().includes(q));
});

const jumpToCrumb = (targetPath) => {
  if (props.dirDialog.loading) return;
  props.dirDialog.currentPath = targetPath;
  emit('load-dir');
};

const handleNavigateUp = () => {
  filterQuery.value = '';
  emit('navigate-up');
};

const handleSelectDir = (item) => {
  filterQuery.value = '';
  emit('select-dir', item);
};
</script>

<style scoped>
.p115-dir-head-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.p115-dir-path-input {
  margin-bottom: 10px;
}

.p115-crumb-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border-radius: 11px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 10px;
  scrollbar-width: none;
}

.p115-crumb-bar::-webkit-scrollbar {
  display: none;
}

.p115-crumb {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--p115-text-secondary);
  font-family: var(--p115-font-mono);
  font-size: 0.77rem;
  padding: 4px 8px;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.p115-crumb:hover {
  background: var(--p115-bg-hover);
  color: var(--p115-text-primary);
}

.p115-crumb--active {
  background: rgba(91, 207, 250, 0.18);
  color: var(--p115-blue-ink);
  font-weight: 620;
}

.p115-crumb-sep {
  color: var(--p115-text-tertiary);
  font-size: 0.8rem;
}

.p115-dir-filter {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}

.p115-dir-filter-icon {
  position: absolute;
  left: 11px;
  color: var(--p115-text-tertiary);
  pointer-events: none;
}

.p115-dir-filter-input {
  width: 100%;
  padding: 8px 32px 8px 34px;
  border-radius: 10px;
  border: 1px solid var(--p115-border-hairline);
  background: var(--p115-bg-card);
  color: var(--p115-text-primary);
  font-family: var(--p115-font-sans);
  font-size: 0.82rem;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.p115-dir-filter-input:focus {
  border-color: var(--p115-blue);
  box-shadow: 0 0 0 3px rgba(91, 207, 250, 0.2);
}

.p115-dir-filter-clear {
  position: absolute;
  right: 8px;
  appearance: none;
  border: none;
  background: transparent;
  color: var(--p115-text-tertiary);
  cursor: pointer;
  display: flex;
}

.p115-dir-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 36px 16px;
  font-size: 0.82rem;
  color: var(--p115-text-secondary);
}

.p115-finder-box {
  border-radius: 13px;
  background: var(--p115-bg-card);
  border: 1px solid var(--p115-border-hairline);
  max-height: 300px;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 5px;
}

.p115-finder-row {
  width: 100%;
  appearance: none;
  border: none;
  background: transparent;
  color: var(--p115-text-primary);
  padding: 8px 10px;
  min-height: 40px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
  text-align: left;
  transition: background-color 0.14s ease, transform 0.1s var(--p115-press);
}

.p115-finder-row:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.12) 0%, rgba(245, 171, 185, 0.09) 100%);
}

.p115-finder-row:active:not(:disabled) {
  transform: scale(0.99);
}

.p115-finder-row-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.p115-folder-badge {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(91, 207, 250, 0.16);
  color: var(--p115-blue-ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.p115-folder-badge--cloud {
  background: rgba(245, 171, 185, 0.2);
  color: var(--p115-pink-ink);
}

.p115-folder-badge--up {
  background: var(--p115-bg-seg-track);
  color: var(--p115-text-secondary);
}

.p115-finder-name {
  font-size: 0.84rem;
  font-weight: 520;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.p115-finder-hint,
.p115-finder-chevron {
  color: var(--p115-text-tertiary);
  font-size: 0.75rem;
  flex-shrink: 0;
}

.p115-finder-empty {
  padding: 28px 12px;
  text-align: center;
  font-size: 0.8rem;
  color: var(--p115-text-secondary);
}

.p115-dir-footer-right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.p115-dir-selected-preview {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
  color: var(--p115-text-secondary);
}

@media (max-width: 599px) {
  .p115-dir-selected-preview {
    display: none;
  }

  .p115-dir-filter-input {
    font-size: 16px;
  }
}
</style>
