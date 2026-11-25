<template>
  <div class="p115-composer">
    <!-- Dual Path Mapping Mode (Local <-> Remote, optional structured CD2 prefix row & enabled toggle) -->
    <template v-if="mode === 'dual'">
      <div
        v-for="(pair, index) in items"
        :key="`${keyPrefix}-${index}`"
        class="p115-composer-card"
      >
        <!-- Unified 4-Column Symmetric Grid: Local | Arrow | Remote | Actions -->
        <div class="p115-composer-dual" :class="{ 'p115-composer-dual--with-cd2': showCd2Prefix }">
          <div class="p115-composer-input-wrap">
            <v-text-field
              v-model="pair.local"
              :label="localLabel"
              :placeholder="localPlaceholder"
              density="compact"
              variant="outlined"
              hide-details
              :readonly="readonlyInputs"
            >
              <template #prepend-inner>
                <v-icon size="16" color="primary" :icon="localIcon" />
              </template>
              <template v-if="allowLocalBrowse" #append-inner>
                <button
                  type="button"
                  class="p115-inline-browse"
                  :title="`浏览${localLabel}`"
                  @click="$emit('browse-local', index)"
                >
                  <v-icon size="16" icon="mdi-folder-open-outline" />
                </button>
              </template>
            </v-text-field>
          </div>

          <div class="p115-composer-arrow" aria-hidden="true">
            <v-icon size="18" icon="mdi-swap-horizontal" />
          </div>

          <div class="p115-composer-input-wrap">
            <v-text-field
              v-model="pair.remote"
              :label="remoteLabel"
              :placeholder="remotePlaceholder"
              density="compact"
              variant="outlined"
              hide-details
              :readonly="readonlyInputs"
            >
              <template #prepend-inner>
                <v-icon size="16" color="secondary" :icon="remoteIcon" />
              </template>
              <template v-if="allowRemoteBrowse" #append-inner>
                <button
                  type="button"
                  class="p115-inline-browse"
                  :title="`浏览${remoteLabel}`"
                  @click="$emit('browse-remote', index)"
                >
                  <v-icon size="16" icon="mdi-cloud-search-outline" />
                </button>
              </template>
            </v-text-field>
          </div>

          <!-- Row 2 (when CloudDrive2 Prefix Enabled): Shares exact columns 1..3 -->
          <template v-if="showCd2Prefix">
            <div class="p115-composer-cd2-divider" aria-hidden="true" />

            <div class="p115-composer-input-wrap">
              <v-text-field
                v-model="pair.cd2Prefix"
                label="CD2 挂载前缀 (可选)"
                placeholder="例如：/115open（非 CD2 路径留空）"
                density="compact"
                variant="outlined"
                hide-details
              >
                <template #prepend-inner>
                  <v-icon size="16" color="primary" icon="mdi-link-variant" />
                </template>
              </v-text-field>
            </div>

            <div class="p115-composer-arrow p115-composer-arrow--sub" aria-hidden="true">
              <v-icon size="16" icon="mdi-arrow-right" />
            </div>

            <div class="p115-cd2-preview">
              <span class="p115-cd2-preview-label">拼接网盘路径</span>
              <span class="p115-cd2-preview-val p115-mono" :title="buildEffectiveRemote(pair)">
                {{ buildEffectiveRemote(pair) }}
              </span>
            </div>
          </template>

          <div class="p115-composer-actions">
            <v-tooltip
              v-if="showEnabledToggle"
              :text="pair.enabled !== false ? '参与全量同步，点击关闭' : '不参与全量同步，点击开启'"
              location="top"
            >
              <template #activator="{ props: tipProps }">
                <button
                  v-bind="tipProps"
                  type="button"
                  class="p115-btn p115-btn--icon"
                  :class="pair.enabled !== false ? 'p115-btn--tonal' : 'p115-btn--subtle'"
                  @click="pair.enabled = pair.enabled === false"
                >
                  <v-icon size="16" :icon="pair.enabled !== false ? 'mdi-sync' : 'mdi-sync-off'" />
                </button>
              </template>
            </v-tooltip>

            <button
              type="button"
              class="p115-btn p115-btn--icon p115-btn--danger"
              title="移除此映射行"
              @click="$emit('remove', index)"
            >
              <v-icon size="16" icon="mdi-trash-can-outline" />
            </button>
          </div>
        </div>

        <div
          v-if="(pair.local && !pair.remote) || (!pair.local && pair.remote)"
          class="p115-composer-inline-warn"
        >
          <v-icon size="14" icon="mdi-alert-circle-outline" />
          <span>请补全成对映射目录，单侧留空将不会生效</span>
        </div>
      </div>
    </template>

    <!-- Single Path List Mode -->
    <template v-else-if="mode === 'single'">
      <div
        v-for="(item, index) in items"
        :key="`${keyPrefix}-${index}`"
        class="p115-composer-card p115-composer-single"
      >
        <div class="p115-composer-input-wrap">
          <v-text-field
            v-model="item.path"
            :label="singleLabel"
            :placeholder="singlePlaceholder"
            density="compact"
            variant="outlined"
            hide-details
            :readonly="readonlyInputs"
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" :icon="singleIcon" />
            </template>
            <template v-if="allowSingleBrowse" #append-inner>
              <button
                type="button"
                class="p115-inline-browse"
                :title="`浏览${singleLabel}`"
                @click="$emit('browse-single', index)"
              >
                <v-icon size="16" icon="mdi-folder-open-outline" />
              </button>
            </template>
          </v-text-field>
        </div>

        <div class="p115-composer-actions">
          <slot name="row-action" :item="item" :index="index" />
          <button
            type="button"
            class="p115-btn p115-btn--icon p115-btn--danger"
            :disabled="disableSingleRemoveWhenEmpty && !item.path"
            title="移除此路径"
            @click="$emit('remove', index)"
          >
            <v-icon size="16" icon="mdi-trash-can-outline" />
          </button>
        </div>
      </div>
    </template>

    <!-- Triple Path Mapping Mode (Mediaserver <-> MoviePilot <-> 115 Cloud) -->
    <template v-else-if="mode === 'triple'">
      <div
        v-for="(item, index) in items"
        :key="`${keyPrefix}-${index}`"
        class="p115-composer-card"
      >
        <div class="p115-composer-triple">
          <v-text-field
            v-model="item.mediaserver"
            label="媒体服务器 STRM 路径"
            placeholder="例如：/media/strm"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" icon="mdi-television-play" />
            </template>
          </v-text-field>

          <v-text-field
            v-model="item.moviepilot"
            label="MoviePilot 路径"
            placeholder="例如：/mnt/strm"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" icon="mdi-folder-home-outline" />
            </template>
            <template #append-inner>
              <button
                type="button"
                class="p115-inline-browse"
                title="浏览 MoviePilot 本地路径"
                @click="$emit('browse-triple', { index, side: 'local', field: 'moviepilot' })"
              >
                <v-icon size="16" icon="mdi-folder-open-outline" />
              </button>
            </template>
          </v-text-field>

          <v-text-field
            v-model="item.p115"
            label="115网盘媒体库路径"
            placeholder="例如：/影视"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="secondary" icon="mdi-cloud-outline" />
            </template>
            <template #append-inner>
              <button
                type="button"
                class="p115-inline-browse"
                title="浏览 115 网盘路径"
                @click="$emit('browse-triple', { index, side: 'remote', field: 'p115' })"
              >
                <v-icon size="16" icon="mdi-cloud-search-outline" />
              </button>
            </template>
          </v-text-field>

          <button
            type="button"
            class="p115-btn p115-btn--icon p115-btn--danger"
            title="移除此三端映射"
            @click="$emit('remove', index)"
          >
            <v-icon size="16" icon="mdi-trash-can-outline" />
          </button>
        </div>
      </div>
    </template>

    <div>
      <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="$emit('add')">
        <v-icon size="15" icon="mdi-plus" />
        <span>{{ addLabel }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  mode: {
    type: String,
    default: 'dual',
  },
  items: {
    type: Array,
    required: true,
  },
  keyPrefix: {
    type: String,
    default: 'path',
  },
  localLabel: {
    type: String,
    default: '本地 STRM 目录',
  },
  localPlaceholder: {
    type: String,
    default: '/mnt/strm/...',
  },
  localIcon: {
    type: String,
    default: 'mdi-folder-outline',
  },
  remoteLabel: {
    type: String,
    default: '网盘媒体库目录',
  },
  remotePlaceholder: {
    type: String,
    default: '/影视/...',
  },
  remoteIcon: {
    type: String,
    default: 'mdi-cloud-outline',
  },
  singleLabel: {
    type: String,
    default: '目录路径',
  },
  singlePlaceholder: {
    type: String,
    default: '请选择或输入路径',
  },
  singleIcon: {
    type: String,
    default: 'mdi-folder-outline',
  },
  allowLocalBrowse: {
    type: Boolean,
    default: true,
  },
  allowRemoteBrowse: {
    type: Boolean,
    default: true,
  },
  allowSingleBrowse: {
    type: Boolean,
    default: true,
  },
  readonlyInputs: {
    type: Boolean,
    default: false,
  },
  disableSingleRemoveWhenEmpty: {
    type: Boolean,
    default: false,
  },
  showCd2Prefix: {
    type: Boolean,
    default: false,
  },
  showEnabledToggle: {
    type: Boolean,
    default: false,
  },
  addLabel: {
    type: String,
    default: '添加路径映射',
  },
});

defineEmits(['add', 'remove', 'browse-local', 'browse-remote', 'browse-single', 'browse-triple']);

const buildEffectiveRemote = (pair) => {
  const prefix = String(pair?.cd2Prefix || '').trim().replace(/\/+$/, '');
  const remote = String(pair?.remote || '').trim();
  if (!prefix && !remote) return '待填写网盘目录';
  if (!prefix) return remote || '/';
  const cleanRemote = remote.replace(/^\/+/, '').replace(/\/+$/, '');
  return cleanRemote ? `${prefix}/${cleanRemote}` : prefix;
};
</script>

<style scoped>
.p115-composer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.p115-composer-card {
  padding: 12px 14px;
  border-radius: 13px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
  transition: border-color 0.2s ease;
  min-width: 0;
  max-width: 100%;
}

.p115-composer-card:hover {
  border-color: var(--p115-border-accent);
}

.p115-composer-dual {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 26px minmax(0, 1fr) auto;
  align-items: center;
  column-gap: 10px;
  row-gap: 10px;
}

.p115-composer-dual .p115-composer-actions {
  grid-column: 4;
  grid-row: 1;
}

.p115-composer-dual--with-cd2 .p115-composer-actions {
  grid-column: 4;
  grid-row: 1 / span 3;
  align-self: center;
}

.p115-composer-cd2-divider {
  grid-column: 1 / span 3;
  border-top: 1px dashed var(--p115-border-hairline);
}

.p115-cd2-preview {
  min-width: 0;
  min-height: 40px;
  padding: 6px 12px;
  border-radius: 10px;
  background: var(--p115-bg-card);
  border: 1px solid var(--p115-border-hairline);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.p115-cd2-preview-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--p115-text-tertiary);
  white-space: nowrap;
  flex-shrink: 0;
}

.p115-cd2-preview-val {
  font-size: 0.79rem;
  color: var(--p115-blue-ink);
  font-weight: 560;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.p115-composer-single {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.p115-composer-triple {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
  align-items: center;
  gap: 8px;
}

.p115-composer-input-wrap {
  min-width: 0;
  width: 100%;
}

.p115-composer-arrow {
  color: var(--p115-blue-ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  opacity: 0.75;
}

.p115-composer-arrow--sub {
  opacity: 0.55;
}

.p115-composer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.p115-inline-browse {
  appearance: none;
  border: none;
  background: rgba(91, 207, 250, 0.14);
  color: var(--p115-blue-ink);
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.15s ease, transform 0.1s var(--p115-press);
}

.p115-inline-browse:hover {
  background: rgba(91, 207, 250, 0.25);
}

.p115-inline-browse:active {
  transform: scale(0.92);
}

.p115-composer-inline-warn {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.73rem;
  color: var(--p115-amber-ink);
}

@media (max-width: 860px) {
  .p115-composer-triple {
    grid-template-columns: minmax(0, 1fr);
  }

  .p115-composer-triple > button {
    justify-self: end;
  }
}

@media (max-width: 768px) {
  .p115-composer-dual {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .p115-composer-dual .p115-composer-actions,
  .p115-composer-dual--with-cd2 .p115-composer-actions {
    grid-column: 1;
    grid-row: auto;
    justify-content: flex-end;
  }

  .p115-composer-cd2-divider {
    grid-column: 1;
    margin-block: 2px;
  }

  .p115-composer-arrow {
    transform: rotate(90deg);
    justify-self: center;
    height: 16px;
  }

  .p115-composer-actions {
    justify-content: flex-end;
  }
}
</style>
