<template>
  <div
    class="p115-page-host p115-scope"
    :data-p115-theme="themeMode"
    :data-p115-transparent="isTransparent ? 'true' : 'false'"
  >
    <div class="p115-window">
      <div class="p115-aurora" />

      <!-- Top Vibrancy Window Header -->
      <header class="p115-window-header">
        <div class="p115-header-brand">
          <div class="p115-squircle-icon">
            <v-icon icon="mdi-cog-outline" size="21" />
          </div>
          <div class="p115-header-titles">
            <div class="p115-header-title">
              <span>115网盘STRM助手配置</span>
              <span v-if="isDirty" class="p115-badge p115-badge--amber">
                <span class="p115-badge-dot" />
                有未保存修改
              </span>
              <span v-else-if="!loading" class="p115-badge p115-badge--blue">
                <span class="p115-badge-dot" />
                已同步
              </span>
            </div>
            <div class="p115-header-subtitle">
              支持 ⌘K 快速检索全部配置项 · ⌘S 一键保存 · 自动保护未保存变更
            </div>
          </div>
        </div>

        <div class="d-flex align-center gap-2 flex-shrink-0">
          <button
            v-if="isDirty"
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            title="放弃当前修改并恢复至上次加载状态"
            @click="resetToLoadedSnapshot"
          >
            <v-icon size="15" icon="mdi-restore" />
            <span class="d-none d-sm-inline">还原更改</span>
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            @click="handleBackClick"
          >
            <v-icon size="15" icon="mdi-arrow-left" />
            <span>返回总览</span>
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--ghost p115-btn--icon p115-btn--sm"
            aria-label="关闭窗口"
            title="关闭窗口"
            @click="handleCloseClick"
          >
            <v-icon size="17" icon="mdi-close" />
          </button>
        </div>
      </header>

      <!-- Main Split Shell (macOS Sequoia Sidebar on Desktop / Sticky Bar on Mobile) -->
      <div class="p115-config-shell">
        <!-- Left Sidebar (Desktop >= 960px) & Top Search/Nav (Mobile < 960px) -->
        <aside class="p115-config-sidebar">
          <div class="p115-search-wrap">
            <v-icon size="16" icon="mdi-magnify" class="p115-search-icon" />
            <input
              ref="searchInputRef"
              v-model="searchQuery"
              type="text"
              class="p115-search-input"
              placeholder="搜索功能、路径或配置 (⌘K)"
              @keydown.esc="searchQuery = ''"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="p115-search-clear"
              aria-label="清空搜索"
              @click="searchQuery = ''"
            >
              <v-icon size="14" icon="mdi-close-circle" />
            </button>
          </div>

          <!-- Instant Search Results Overlay Panel -->
          <div v-if="searchQuery.trim()" class="p115-search-results">
            <div v-if="searchResults.length === 0" class="p115-search-empty">
              未找到与“{{ searchQuery }}”匹配的配置分区
            </div>
            <button
              v-for="item in searchResults"
              :key="item.id"
              type="button"
              class="p115-search-hit"
              @click="handleSelectSearchResult(item)"
            >
              <div class="d-flex align-center gap-1.5 mb-0.5">
                <span class="p115-badge p115-badge--blue">{{ item.categoryLabel }}</span>
                <span v-if="item.subLabel" class="text-caption font-weight-bold">{{ item.subLabel }}</span>
              </div>
              <div class="p115-search-hit-title">{{ item.title }}</div>
            </button>
          </div>

          <!-- Desktop Category Rail -->
          <nav class="p115-sidebar-nav">
            <button
              v-for="cat in categoryItems"
              :key="cat.value"
              type="button"
              class="p115-nav-item"
              :class="{ 'p115-nav-item--active': mainCategory === cat.value }"
              @click="mainCategory = cat.value"
            >
              <span class="p115-nav-icon-box" :class="`p115-nav-icon-box--${cat.tone}`">
                <v-icon size="16" :icon="cat.icon" />
              </span>
              <span class="p115-nav-label">{{ cat.label }}</span>
              <span v-if="cat.badge" class="p115-nav-badge p115-tabular">{{ cat.badge }}</span>
            </button>
          </nav>

          <!-- Mobile Horizontal Category Segmented Bar -->
          <div class="p115-mobile-catbar">
            <AppleSegmentedControl v-model="mainCategory" :items="categoryItems" />
          </div>
        </aside>

        <!-- Right Scrollable Settings Stage -->
        <main ref="contentPaneRef" class="p115-config-stage">
          <!-- Floating Message Banner -->
          <div
            v-if="message.text"
            class="p115-callout mb-4"
            :class="`p115-callout--${message.type === 'success' ? 'success' : message.type === 'error' ? 'error' : message.type === 'warning' ? 'warn' : 'info'}`"
          >
            <v-icon
              size="18"
              :color="message.type"
              :icon="message.type === 'success' ? 'mdi-check-circle-outline' : 'mdi-information-outline'"
              class="mt-0.5 flex-shrink-0"
            />
            <span class="flex-grow-1">{{ message.text }}</span>
            <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" @click="message.text = ''">
              <v-icon size="16" icon="mdi-close" />
            </button>
          </div>

          <v-skeleton-loader v-if="loading" type="article, actions" class="bg-transparent" />

          <div v-else class="p115-stage-inner">
            <BasicConfigSection v-if="mainCategory === 'category-basic'" />
            <StrmSyncSection v-else-if="mainCategory === 'category-strm'" />
            <PanManagementSection v-else-if="mainCategory === 'category-pan'" />
            <OtherFeaturesSection v-else-if="mainCategory === 'category-other'" />
            <SystemConfigSection v-else-if="mainCategory === 'category-system'" />
          </div>
        </main>
      </div>

      <!-- Bottom Frosted Action Dock -->
      <footer class="p115-window-footer p115-config-footer">
        <button type="button" class="p115-btn p115-btn--pink" @click="openDonateDialog">
          <v-icon size="16" icon="mdi-gift-outline" />
          <span>捐赠 / 授权</span>
        </button>

        <div class="p115-config-actions">
          <button
            type="button"
            class="p115-btn p115-btn--tonal"
            :disabled="syncLoading"
            @click="fullSyncConfirmDialog = true"
          >
            <v-progress-circular v-if="syncLoading" indeterminate size="14" width="2" />
            <v-icon v-else size="16" icon="mdi-sync" />
            <span>全量同步</span>
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--primary"
            :disabled="saveLoading"
            @click="saveConfig"
          >
            <v-progress-circular v-if="saveLoading" indeterminate size="14" width="2" />
            <v-icon v-else size="16" icon="mdi-content-save-outline" />
            <span>保存配置</span>
          </button>
        </div>
      </footer>
    </div>

    <!-- Unsaved Changes Protection Sheet -->
    <v-dialog v-model="unsavedDialog" max-width="460" :content-class="dialogContentClass">
      <v-card class="p115-sheet" elevation="0">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon size="19" color="warning" icon="mdi-content-save-alert-outline" />
            <span>存在未保存的配置修改</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <p class="ma-0 text-body-2">
            您对当前插件配置进行了更改但尚未保存。直接返回将丢失本次编辑内容，是否先保存配置？
          </p>
        </div>
        <div class="p115-sheet-footer">
          <button type="button" class="p115-btn p115-btn--danger p115-btn--sm" @click="discardAndLeave">
            放弃更改并返回
          </button>
          <div class="d-flex align-center gap-2">
            <button type="button" class="p115-btn p115-btn--subtle p115-btn--sm" @click="unsavedDialog = false">
              继续编辑
            </button>
            <button type="button" class="p115-btn p115-btn--primary p115-btn--sm" @click="saveAndLeave">
              保存并返回
            </button>
          </div>
        </div>
      </v-card>
    </v-dialog>

    <!-- 全量同步确认对话框 -->
    <FullSyncConfirmDialog
      v-model="fullSyncConfirmDialog"
      :loading="syncLoading"
      :has-media-server-refresh="config.full_sync_media_server_refresh_enabled"
      @confirm="handleConfirmFullSync"
    />

    <!-- 目录选择器对话框 -->
    <DirSelectorDialog
      :dir-dialog="dirDialog"
      @load-dir="loadDirContent"
      @navigate-up="navigateToParentDir"
      @select-dir="selectDir"
      @confirm="confirmDirSelection"
      @close="closeDirDialog"
    />

    <!-- 手动整理确认对话框 -->
    <ManualTransferDialog
      :manual-transfer-dialog="manualTransferDialog"
      @confirm="confirmManualTransfer"
      @close="closeManualTransferDialog"
    />

    <!-- 115网盘扫码登录对话框 -->
    <QrCodeDialog
      :qr-dialog="qrDialog"
      :client-types="clientTypes"
      @refresh="refreshQrCode"
      @close="closeQrDialog"
    />

    <!-- 阿里云盘扫码登录对话框 -->
    <AliQrCodeDialog
      :ali-qr-dialog="aliQrDialog"
      @refresh="refreshAliQrCode"
      @close="closeAliQrCodeDialog"
    />

    <!-- 捐赠/授权对话框 -->
    <DonateDialog
      :donate-dialog="donateDialog"
      :format-authorization-expiration="formatAuthorizationExpiration"
      @close="closeDonateDialog"
    />

    <!-- Emby 反代 302 配置生成对话框 -->
    <ConfigGeneratorDialog
      :config-generator-dialog="configGeneratorDialog"
      @close="closeConfigGeneratorDialog"
      @copy="copyGeneratedConfig"
      @regenerate="generateConfig"
    />

    <!-- 生活事件故障检查对话框 -->
    <LifeEventCheckDialog
      :life-event-check-dialog="lifeEventCheckDialog"
      @check="checkLifeEventStatus"
      @close="closeLifeEventCheckDialog"
      @copy-debug="copyDebugInfo"
    />

    <!-- 频道配置导入对话框 -->
    <ImportChannelDialog
      :import-dialog="importDialog"
      @close="closeImportDialog"
      @confirm="handleConfirmImport"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, provide, nextTick } from 'vue';
import '../styles/apple-theme.css';
import { P115_STRM_HELPER_PLUGIN_ID } from '../utils/pluginId.js';
import { consumeConfigJump } from '../utils/navigationBridge.js';
import { useThemeAdapter } from './composables/useThemeAdapter.js';
import { useConfigSearch } from './composables/useConfigSearch.js';
import { usePathManagement } from './composables/usePathManagement.js';
import { useQrCode } from './composables/useQrCode.js';
import { useDirSelector } from './composables/useDirSelector.js';
import { useSizeFormatter } from './composables/useSizeFormatter.js';
import AppleSegmentedControl from './ui/AppleSegmentedControl.vue';
import QrCodeDialog from './dialogs/QrCodeDialog.vue';
import AliQrCodeDialog from './dialogs/AliQrCodeDialog.vue';
import DirSelectorDialog from './dialogs/DirSelectorDialog.vue';
import DonateDialog from './dialogs/DonateDialog.vue';
import ConfigGeneratorDialog from './dialogs/ConfigGeneratorDialog.vue';
import LifeEventCheckDialog from './dialogs/LifeEventCheckDialog.vue';
import ManualTransferDialog from './dialogs/ManualTransferDialog.vue';
import FullSyncConfirmDialog from './dialogs/FullSyncConfirmDialog.vue';
import ImportChannelDialog from './dialogs/ImportChannelDialog.vue';
import BasicConfigSection from './sections/BasicConfigSection.vue';
import StrmSyncSection from './sections/StrmSyncSection.vue';
import PanManagementSection from './sections/PanManagementSection.vue';
import OtherFeaturesSection from './sections/OtherFeaturesSection.vue';
import SystemConfigSection from './sections/SystemConfigSection.vue';

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true,
  },
  initialConfig: {
    type: Object,
    default: () => ({}),
  },
});

const emit = defineEmits(['save', 'close', 'switch']);

const PLUGIN_ID = P115_STRM_HELPER_PLUGIN_ID;
const { isTransparent, themeMode, dialogContentClass } = useThemeAdapter();
const { searchQuery, searchResults } = useConfigSearch();

const searchInputRef = ref(null);
const contentPaneRef = ref(null);
const unsavedDialog = ref(false);

const loading = ref(true);
const saveLoading = ref(false);
const syncLoading = ref(false);
const clearIdPathCacheLoading = ref(false);
const clearP115ClientCacheLoading = ref(false);
const clearIncrementSkipCacheLoading = ref(false);
const clearR302CacheLoading = ref(false);

const mainCategory = ref('category-basic');
const activeSubTabs = reactive({
  strm: 'tab-transfer',
  pan: 'tab-pan-transfer',
  other: 'tab-sync-del',
  system: 'tab-cache-config',
});

const mediaservers = ref([]);
const embyMediaservers = computed(() => mediaservers.value.filter((server) => server.type === 'emby'));
const isCookieVisible = ref(false);
const isAliTokenVisible = ref(false);
const isTransferModuleEnhancementLocked = ref(true);

const config = reactive({
  language: 'zh_CN',
  enabled: false,
  notify: false,
  strm_url_format: 'pickcode',
  link_redirect_mode: 'cookie',
  cookies: '',
  aliyundrive_token: '',
  password: '',
  moviepilot_address: '',
  user_rmt_mediaext: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v',
  user_download_mediaext: 'srt,ssa,ass',
  transfer_monitor_enabled: false,
  transfer_monitor_scrape_metadata_enabled: false,
  transfer_monitor_scrape_metadata_exclude_paths: '',
  transfer_monitor_paths: '',
  transfer_mp_mediaserver_paths: '',
  transfer_monitor_media_server_refresh_enabled: false,
  transfer_monitor_media_server_refresh_delay: 0,
  transfer_monitor_emby_mediainfo_enabled: false,
  transfer_monitor_clouddrive2_enabled: false,
  transfer_monitor_remove_stale_strm: false,
  transfer_monitor_remove_stale_strm_dir: false,
  transfer_monitor_remove_stale_strm_file: false,
  transfer_monitor_mediaservers: [],
  timing_full_sync_strm: false,
  full_sync_overwrite_mode: 'never',
  full_sync_remove_unless_strm: false,
  full_sync_remove_unless_dir: false,
  full_sync_remove_unless_file: false,
  full_sync_media_server_refresh_enabled: false,
  full_sync_media_server_refresh_delay: 0,
  full_sync_mediaservers: [],
  full_sync_auto_download_mediainfo_enabled: false,
  full_sync_strm_log: true,
  full_sync_batch_num: 5000,
  full_sync_process_num: 128,
  cron_full_sync_strm: '0 */7 * * *',
  full_sync_strm_paths: '',
  full_sync_iter_function: 'iter_files_with_path_skim',
  full_sync_min_file_size: 0,
  full_sync_process_rust: false,
  full_sync_remove_unless_max_threshold: 10,
  full_sync_remove_unless_stable_threshold: 5,
  full_sync_cleanup_confirm_mode: 'none',
  increment_sync_strm_enabled: false,
  increment_sync_auto_download_mediainfo_enabled: false,
  increment_sync_cron: '0 * * * *',
  increment_sync_strm_paths: '',
  increment_sync_mp_mediaserver_paths: '',
  increment_sync_scrape_metadata_enabled: false,
  increment_sync_scrape_metadata_exclude_paths: '',
  increment_sync_media_server_refresh_enabled: false,
  increment_sync_media_server_refresh_delay: 0,
  increment_sync_mediaservers: [],
  increment_sync_emby_mediainfo_enabled: false,
  increment_sync_min_file_size: 0,
  increment_sync_second_level_dir_scan: false,
  increment_sync_itertree_timeout_seconds: 0,
  increment_sync_remove_unless_strm: false,
  increment_sync_remove_unless_dir: false,
  increment_sync_remove_unless_file: false,
  increment_sync_remove_unless_max_threshold: 10,
  increment_sync_remove_unless_stable_threshold: 5,
  monitor_life_enabled: false,
  monitor_life_auto_download_mediainfo_enabled: false,
  monitor_life_paths: '',
  monitor_life_mp_mediaserver_paths: '',
  monitor_life_media_server_refresh_enabled: false,
  monitor_life_media_server_refresh_delay: 0,
  monitor_life_mediaservers: [],
  monitor_life_emby_mediainfo_enabled: false,
  monitor_life_event_modes: [],
  monitor_life_scrape_metadata_enabled: false,
  monitor_life_scrape_metadata_exclude_paths: '',
  monitor_life_remove_mp_history: false,
  monitor_life_remove_mp_source: false,
  monitor_life_move_out_media_remove_local_strm: false,
  monitor_life_move_media_keep_old_strm: true,
  monitor_life_move_media_create_new_strm: true,
  monitor_life_move_media_mode: 'recreate',
  monitor_life_move_media_to_transfer_remove_local_strm: false,
  monitor_life_move_media_local_move_related_files: true,
  monitor_life_rename_auto_related_files: true,
  monitor_life_min_file_size: 0,
  monitor_life_transfer_stall_timeout_minutes: 60,
  share_strm_config: [],
  share_strm_mediaservers: [],
  share_strm_media_server_refresh_delay: 0,
  share_strm_mp_mediaserver_paths: '',
  share_interactive_gen_strm_config: {
    min_file_size: null,
    auto_download_mediainfo: false,
    local_path: '',
    moviepilot_transfer: false,
    iter_function: 'iter_share_files_with_path',
    speed_mode: 3,
  },
  share_strm_cleanup_config: {
    cleanup_paths: [],
    timing_share_strm_cleanup: false,
    cron_share_strm_cleanup: '0 */12 * * *',
    delete_mode: 'plugin_ui',
    remove_related_mediainfo: true,
    remove_empty_parent_dirs: true,
    remove_stale_transfer_history: false,
    record_missing_media_from_history: true,
  },
  api_strm_config: [],
  api_strm_mediaservers: [],
  api_strm_mp_mediaserver_paths: '',
  api_strm_scrape_metadata_enabled: false,
  api_strm_media_server_refresh_enabled: false,
  api_strm_media_server_refresh_delay: 0,
  clear_recyclebin_enabled: false,
  clear_receive_path_enabled: false,
  cron_clear: '0 */7 * * *',
  pan_transfer_enabled: false,
  pan_transfer_clouddrive2_config: { enabled: false, prefix: '' },
  pan_transfer_paths: '',
  pan_transfer_unrecognized_path: '',
  share_recieve_paths: [],
  offline_download_paths: [],
  offline_retry_enabled: false,
  offline_retry_max_attempts: 3,
  offline_retry_interval_hours: 24,
  fuse_enabled: false,
  fuse_mountpoint: '',
  fuse_readdir_ttl: 60,
  fuse_uid: null,
  fuse_gid: null,
  fuse_strm_takeover_enabled: false,
  fuse_strm_mount_dir: '',
  fuse_strm_takeover_rules: [],
  directory_upload_enabled: false,
  directory_upload_mode: 'compatibility',
  directory_upload_uploadext: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v',
  directory_upload_copyext: 'srt,ssa,ass',
  directory_upload_skip_bdmv_stream: true,
  directory_upload_rescan_enabled: true,
  directory_upload_rescan_interval: 10,
  directory_upload_rescan_max_submit: 300,
  directory_upload_path: [],
  directory_upload_clouddrive2_config: { enabled: false, prefix: '' },
  tg_search_channels: [],
  hdhive_search_enabled: false,
  hdhive_checkin_username: '',
  hdhive_checkin_password: '',
  hdhive_checkin_daily_enabled: false,
  hdhive_checkin_gamble_enabled: false,
  hdhive_checkin_time_range: '06:00-09:00',
  p115_checkin_enabled: false,
  p115_checkin_time_range: '06:00-09:00',
  share_strm_overwrite_check_enabled: false,
  auto_delete_inferior_source_enabled: false,
  transfer_intercept_exists_enabled: false,
  strm_backup_enabled: false,
  strm_backup_items: [],
  same_playback: false,
  error_info_upload: false,
  upload_module_enhancement: false,
  upload_module_skip_slow_upload: false,
  upload_module_notify: true,
  upload_module_wait_time: 300,
  upload_module_wait_timeout: 3600,
  upload_module_skip_upload_wait_size: 0,
  upload_module_force_upload_wait_size: 0,
  upload_module_skip_slow_upload_size: 0,
  upload_module_recheck_secupload: false,
  upload_module_recheck_secupload_interval: 300,
  upload_open_result_notify: false,
  upload_share_info: true,
  upload_offline_info: true,
  transfer_module_enhancement: false,
  pan_transfer_takeover: false,
  pan_transfer_linked_subtitle_audio: true,
  rename_dict_supplement_enabled: false,
  rename_dict_supplement_overwrite_mode: 'fill_missing',
  native_emby_mediainfo_enabled: false,
  sidebar_nav_keys: ['start'],
  strm_url_template_enabled: false,
  strm_url_template: '',
  strm_url_template_custom: '',
  strm_filename_template_enabled: false,
  strm_filename_template: '',
  strm_filename_template_custom: '',
  strm_generate_blacklist: [],
  mediainfo_download_whitelist: [],
  mediainfo_download_blacklist: [],
  share_audit_queue_enabled: true,
  share_audit_max_wait_seconds: 21600,
  share_audit_retry_interval_seconds: 1800,
  strm_url_encode: false,
  storage_module: 'u115',
  sync_del_enabled: false,
  sync_del_notify: true,
  sync_del_source: false,
  sync_del_p115_library_path: '',
  sync_del_p115_force_delete_files: false,
  sync_del_remove_versions: false,
  sync_del_mediaservers: [],
  timeout_enabled: true,
  timeout_default_connect: 30,
  timeout_default_pool: 15,
  timeout_default_read: 60,
  timeout_default_write: 60,
  timeout_slow_connect: 30,
  timeout_slow_pool: 15,
  timeout_slow_read: 300,
  timeout_slow_write: 300,
});

const categoryItems = computed(() => {
  const strmActive = [
    config.transfer_monitor_enabled,
    config.timing_full_sync_strm,
    config.increment_sync_strm_enabled,
    config.monitor_life_enabled,
  ].filter(Boolean).length;
  const panActive = [
    config.pan_transfer_enabled,
    config.fuse_enabled,
    config.directory_upload_enabled,
  ].filter(Boolean).length;
  const otherActive = [
    config.sync_del_enabled,
    config.hdhive_search_enabled,
    config.clear_recyclebin_enabled || config.clear_receive_path_enabled,
    config.same_playback,
    config.hdhive_checkin_daily_enabled || config.hdhive_checkin_gamble_enabled,
    config.p115_checkin_enabled,
    config.strm_backup_enabled,
  ].filter(Boolean).length;

  return [
    {
      value: 'category-basic',
      label: '基础设置',
      icon: 'mdi-tune-vertical',
      tone: 'blue',
      badge: config.enabled ? '开' : '关',
    },
    {
      value: 'category-strm',
      label: 'STRM同步',
      icon: 'mdi-file-link-outline',
      tone: 'blue',
      badge: strmActive || '',
    },
    {
      value: 'category-pan',
      label: '网盘管理',
      icon: 'mdi-cloud-outline',
      tone: 'pink',
      badge: panActive || '',
    },
    {
      value: 'category-other',
      label: '其他功能',
      icon: 'mdi-puzzle-outline',
      tone: 'amber',
      badge: otherActive || '',
    },
    {
      value: 'category-system',
      label: '系统配置',
      icon: 'mdi-cog-outline',
      tone: 'green',
      badge: '',
    },
  ];
});

const message = reactive({
  text: '',
  type: 'info',
});

const pathMgmt = usePathManagement(config);
const {
  transferPaths,
  transferMpPaths,
  fullSyncPaths,
  incrementSyncPaths,
  incrementSyncMPPaths,
  monitorLifePaths,
  monitorLifeMpPaths,
  apiStrmPaths,
  apiStrmMPPaths,
  panTransferPaths,
  shareReceivePaths,
  offlineDownloadPaths,
  transferExcludePaths,
  incrementSyncExcludePaths,
  monitorLifeExcludePaths,
  directoryUploadPaths,
  syncDelLibraryPaths,
  fuseStrmTakeoverRules,
  generatePathsConfig,
  addPath,
  removePath,
  addPanTransferPath,
  removePanTransferPath,
  addShareReceivePath,
  removeShareReceivePath,
  addOfflineDownloadPath,
  removeOfflineDownloadPath,
} = pathMgmt;

const qrMgmt = useQrCode(props.api, config, message, PLUGIN_ID);
const {
  qrDialog,
  aliQrDialog,
  clientTypes,
  openQrCodeDialog,
  refreshQrCode,
  closeQrDialog,
  openAliQrCodeDialog,
  refreshAliQrCode,
  closeAliQrCodeDialog,
} = qrMgmt;

const dirMgmt = useDirSelector(props.api, config, message, PLUGIN_ID, pathMgmt);
const {
  dirDialog,
  openDirSelector,
  loadDirContent,
  selectDir,
  navigateToParentDir,
  confirmDirSelection,
  closeDirDialog,
  openExcludeDirSelector,
  removeExcludePathEntry,
} = dirMgmt;

const skipUploadWaitSizeFormattedRef = ref('');
const forceUploadWaitSizeFormattedRef = ref('');
const skipSlowUploadSizeFormattedRef = ref('');
const fullSyncMinFileSizeFormattedRef = ref('');
const incrementSyncMinFileSizeFormattedRef = ref('');
const monitorLifeMinFileSizeFormattedRef = ref('');

const { parseSize, formatBytes } = useSizeFormatter();

const fullSyncConfirmDialog = ref(false);
const machineId = ref('');
const tgChannels = ref([{ name: '', id: '' }]);

const addTgChannel = () => {
  tgChannels.value.push({ name: '', id: '' });
};

const removeTgChannel = (index) => {
  tgChannels.value.splice(index, 1);
  if (tgChannels.value.length === 0) {
    tgChannels.value.push({ name: '', id: '' });
  }
};

const importDialog = reactive({
  show: false,
  jsonText: '',
  error: '',
});

const donateDialog = reactive({
  show: false,
  loading: false,
  error: null,
  donateInfo: null,
  activeTab: 'wechat',
  authorizationStatus: null,
});

const lifeEventCheckDialog = reactive({
  show: false,
  loading: false,
  error: null,
  result: null,
  startTime: '',
});

const configGeneratorDialog = reactive({
  show: false,
  loading: false,
  configType: 'emby2alist',
  mountDir: '',
  moviepilotAddress: '',
  generatedConfig: '',
});

const manualTransferDialog = reactive({
  show: false,
  loading: false,
  path: '',
  result: null,
});

// Snapshot & Dirty Tracking
const rawLoadedData = ref(null);
const baselineSnapshot = ref('');

const buildSnapshot = () =>
  JSON.stringify({
    config,
    transferPaths: transferPaths.value,
    transferMpPaths: transferMpPaths.value,
    fullSyncPaths: fullSyncPaths.value,
    incrementSyncPaths: incrementSyncPaths.value,
    incrementSyncMPPaths: incrementSyncMPPaths.value,
    monitorLifePaths: monitorLifePaths.value,
    monitorLifeMpPaths: monitorLifeMpPaths.value,
    apiStrmPaths: apiStrmPaths.value,
    apiStrmMPPaths: apiStrmMPPaths.value,
    panTransferPaths: panTransferPaths.value,
    shareReceivePaths: shareReceivePaths.value,
    offlineDownloadPaths: offlineDownloadPaths.value,
    directoryUploadPaths: directoryUploadPaths.value,
    syncDelLibraryPaths: syncDelLibraryPaths.value,
    fuseStrmTakeoverRules: fuseStrmTakeoverRules.value,
    tgChannels: tgChannels.value,
    sizes: [
      skipUploadWaitSizeFormattedRef.value,
      forceUploadWaitSizeFormattedRef.value,
      skipSlowUploadSizeFormattedRef.value,
      fullSyncMinFileSizeFormattedRef.value,
      incrementSyncMinFileSizeFormattedRef.value,
      monitorLifeMinFileSizeFormattedRef.value,
    ],
  });

const isDirty = computed(() => {
  if (loading.value || !baselineSnapshot.value) return false;
  return buildSnapshot() !== baselineSnapshot.value;
});

const applyLoadedData = (data) => {
  if (!data) return;
  Object.assign(config, JSON.parse(JSON.stringify(data)));
  directoryUploadPaths.value =
    Array.isArray(config.directory_upload_path) && config.directory_upload_path.length > 0
      ? config.directory_upload_path.map((p) => ({
          src: p.src ?? '',
          dest_remote: p.dest_remote ?? '',
          dest_local: p.dest_local ?? '',
          dest_strm: p.dest_strm ?? '',
          delete: !!p.delete,
        }))
      : [{ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }];

  let parsedChannels = [];
  if (config.tg_search_channels) {
    if (Array.isArray(config.tg_search_channels)) {
      parsedChannels = config.tg_search_channels;
    } else if (typeof config.tg_search_channels === 'string') {
      try {
        parsedChannels = JSON.parse(config.tg_search_channels);
      } catch (e) {
        console.error('解析旧的TG频道配置字符串失败:', e);
        parsedChannels = [];
      }
    }
  }
  tgChannels.value =
    Array.isArray(parsedChannels) && parsedChannels.length > 0
      ? parsedChannels.map((c) => ({ ...c }))
      : [{ name: '', id: '' }];

  if (data.mediaservers) {
    mediaservers.value = data.mediaservers;
  }

  if (Array.isArray(config.fuse_strm_takeover_rules) && config.fuse_strm_takeover_rules.length > 0) {
    fuseStrmTakeoverRules.value = config.fuse_strm_takeover_rules.map((rule) => {
      const extensions = Array.isArray(rule.extensions) ? rule.extensions : [];
      const names = Array.isArray(rule.names) ? rule.names : [];
      const paths = Array.isArray(rule.paths) ? rule.paths : [];
      return {
        extensions: extensions.join('\n'),
        names: names.join('\n'),
        paths: paths.join('\n'),
        _use_extensions: extensions.length > 0,
        _use_names: names.length > 0,
        _use_paths: paths.length > 0,
      };
    });
  } else {
    fuseStrmTakeoverRules.value = [
      { extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false },
    ];
  }

  if (config.sync_del_mediaservers === null || config.sync_del_mediaservers === undefined) {
    config.sync_del_mediaservers = [];
  }

  skipUploadWaitSizeFormattedRef.value =
    config.upload_module_skip_upload_wait_size > 0 ? formatBytes(config.upload_module_skip_upload_wait_size) : '';
  forceUploadWaitSizeFormattedRef.value =
    config.upload_module_force_upload_wait_size > 0 ? formatBytes(config.upload_module_force_upload_wait_size) : '';
  skipSlowUploadSizeFormattedRef.value =
    config.upload_module_skip_slow_upload_size > 0 ? formatBytes(config.upload_module_skip_slow_upload_size) : '';
  fullSyncMinFileSizeFormattedRef.value =
    config.full_sync_min_file_size > 0 ? formatBytes(config.full_sync_min_file_size) : '';
  incrementSyncMinFileSizeFormattedRef.value =
    config.increment_sync_min_file_size > 0 ? formatBytes(config.increment_sync_min_file_size) : '';
  monitorLifeMinFileSizeFormattedRef.value =
    config.monitor_life_min_file_size > 0 ? formatBytes(config.monitor_life_min_file_size) : '';
};

const resetToLoadedSnapshot = async () => {
  if (!rawLoadedData.value) return;
  applyLoadedData(rawLoadedData.value);
  await nextTick();
  baselineSnapshot.value = buildSnapshot();
  message.text = '已还原至上次加载的配置状态';
  message.type = 'info';
  setTimeout(() => {
    if (message.type === 'info') message.text = '';
  }, 2500);
};

const applyJumpTarget = (target) => {
  if (!target) return;
  if (target.category) {
    mainCategory.value = target.category;
  }
  if (target.subTab) {
    if (target.category === 'category-strm') activeSubTabs.strm = target.subTab;
    else if (target.category === 'category-pan') activeSubTabs.pan = target.subTab;
    else if (target.category === 'category-other') activeSubTabs.other = target.subTab;
    else if (target.category === 'category-system') activeSubTabs.system = target.subTab;
  }
  if (contentPaneRef.value) {
    contentPaneRef.value.scrollTo({ top: 0, behavior: 'smooth' });
  }
};

const handleSelectSearchResult = (item) => {
  applyJumpTarget({ category: item.category, subTab: item.subTab });
  searchQuery.value = '';
};

const pendingExitEvent = ref('switch');

const handleBackClick = () => {
  if (isDirty.value) {
    pendingExitEvent.value = 'switch';
    unsavedDialog.value = true;
    return;
  }
  emit('switch');
};

const handleCloseClick = () => {
  if (isDirty.value) {
    pendingExitEvent.value = 'close';
    unsavedDialog.value = true;
    return;
  }
  emit('close');
};

const discardAndLeave = () => {
  unsavedDialog.value = false;
  emit(pendingExitEvent.value);
};

const saveAndLeave = async () => {
  unsavedDialog.value = false;
  await saveConfig();
  emit(pendingExitEvent.value);
};

const manualTransfer = (index) => {
  if (index < 0 || index >= panTransferPaths.value.length) {
    message.text = '路径项不存在';
    message.type = 'error';
    return;
  }
  const pathItem = panTransferPaths.value[index];
  const path = pathItem?.path;
  if (!path || typeof path !== 'string' || !path.trim()) {
    message.text = '请先配置网盘路径';
    message.type = 'warning';
    return;
  }
  Object.assign(manualTransferDialog, {
    path: path.trim(),
    loading: false,
    result: null,
    show: true,
  });
};

const confirmManualTransfer = async () => {
  if (!manualTransferDialog.path) return;
  manualTransferDialog.loading = true;
  manualTransferDialog.result = null;
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/manual_transfer`, {
      path: manualTransferDialog.path,
    });
    if (result.code === 0) {
      manualTransferDialog.result = {
        type: 'success',
        title: '整理任务已启动',
        message: '整理任务已在后台启动，正在执行中。您可以在日志中查看详细进度。',
      };
    } else {
      manualTransferDialog.result = {
        type: 'error',
        title: '启动失败',
        message: result.msg || '启动整理任务失败，请检查配置和网络连接。',
      };
    }
  } catch (error) {
    manualTransferDialog.result = {
      type: 'error',
      title: '启动失败',
      message: `启动整理任务时发生错误：${error.message || error}`,
    };
  } finally {
    manualTransferDialog.loading = false;
  }
};

const closeManualTransferDialog = () => {
  Object.assign(manualTransferDialog, {
    show: false,
    path: '',
    loading: false,
    result: null,
  });
};

const checkTransferModuleEnhancement = async () => {
  try {
    const result = await props.api.get(`plugin/${PLUGIN_ID}/check_feature?name=transfer_module_enhancement`);
    if (result && result.enabled === true) {
      isTransferModuleEnhancementLocked.value = false;
    } else {
      isTransferModuleEnhancementLocked.value = true;
      config.transfer_module_enhancement = false;
    }
  } catch (err) {
    isTransferModuleEnhancementLocked.value = true;
    config.transfer_module_enhancement = false;
    console.error('检查 "整理模块增强" 功能授权失败:', err);
  }
};

const loadConfig = async () => {
  try {
    loading.value = true;
    const data = await props.api.get(`plugin/${PLUGIN_ID}/get_config`);
    if (data) {
      rawLoadedData.value = JSON.parse(JSON.stringify(data));
      applyLoadedData(data);
    }
  } catch (err) {
    console.error('加载配置失败:', err);
    message.text = `加载配置失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    loading.value = false;
    await nextTick();
    baselineSnapshot.value = buildSnapshot();
  }
};

const saveConfig = async () => {
  saveLoading.value = true;
  message.text = '';
  message.type = 'info';
  try {
    for (const [key, label, maximum] of [
      ['offline_retry_max_attempts', '离线重试次数', 100],
      ['offline_retry_interval_hours', '离线重试间隔（小时）', 8760],
    ]) {
      const value = Number(config[key]);
      if (!Number.isInteger(value) || value < 1 || value > maximum) {
        throw new Error(`${label}必须是 1～${maximum} 的整数`);
      }
      config[key] = value;
    }
    config.moviepilot_address = config.moviepilot_address?.trim() || null;
    config.upload_module_skip_upload_wait_size = parseSize(skipUploadWaitSizeFormattedRef.value) || 0;
    config.upload_module_force_upload_wait_size = parseSize(forceUploadWaitSizeFormattedRef.value) || 0;
    config.upload_module_skip_slow_upload_size = parseSize(skipSlowUploadSizeFormattedRef.value) || 0;
    config.full_sync_min_file_size = parseSize(fullSyncMinFileSizeFormattedRef.value) || 0;
    config.increment_sync_min_file_size = parseSize(incrementSyncMinFileSizeFormattedRef.value) || 0;
    config.monitor_life_min_file_size = parseSize(monitorLifeMinFileSizeFormattedRef.value) || 0;

    config.transfer_monitor_paths = generatePathsConfig(transferPaths.value, 'transfer');
    config.transfer_mp_mediaserver_paths = generatePathsConfig(transferMpPaths.value, 'mp');
    config.full_sync_strm_paths = generatePathsConfig(fullSyncPaths.value, 'fullSync');
    config.increment_sync_strm_paths = generatePathsConfig(incrementSyncPaths.value, 'incrementSync');
    config.increment_sync_mp_mediaserver_paths = generatePathsConfig(incrementSyncMPPaths.value, 'increment-mp');
    config.monitor_life_paths = generatePathsConfig(monitorLifePaths.value, 'monitorLife');
    config.monitor_life_mp_mediaserver_paths = generatePathsConfig(monitorLifeMpPaths.value, 'monitorLifeMp');

    config.api_strm_config = apiStrmPaths.value
      .filter((p) => p.local?.trim() && p.remote?.trim())
      .map((p) => ({ local_path: p.local.trim(), pan_path: p.remote.trim() }));
    config.api_strm_mp_mediaserver_paths = generatePathsConfig(apiStrmMPPaths.value, 'apiStrm-mp');

    config.sync_del_p115_library_path = syncDelLibraryPaths.value
      .filter((p) => p.mediaserver?.trim() || p.moviepilot?.trim() || p.p115?.trim())
      .map((p) => `${p.mediaserver || ''}#${p.moviepilot || ''}#${p.p115 || ''}`)
      .join('\n');

    const payload = JSON.parse(JSON.stringify(config));
    if (Array.isArray(payload.sync_del_mediaservers) && payload.sync_del_mediaservers.length === 0) {
      payload.sync_del_mediaservers = null;
    }

    config.pan_transfer_paths = generatePathsConfig(panTransferPaths.value, 'panTransfer');
    config.share_recieve_paths = shareReceivePaths.value.filter((p) => p.path?.trim()).map((p) => p.path);
    config.offline_download_paths = offlineDownloadPaths.value.filter((p) => p.path?.trim()).map((p) => p.path);
    config.directory_upload_path = directoryUploadPaths.value.filter(
      (p) => p.src?.trim() || p.dest_remote?.trim() || p.dest_local?.trim() || p.dest_strm?.trim(),
    );

    const validChannels = tgChannels.value.filter(
      (c) => c.name && c.name.trim() !== '' && c.id && c.id.trim() !== '',
    );
    config.tg_search_channels = validChannels;

    config.fuse_strm_takeover_rules = fuseStrmTakeoverRules.value
      .map((rule) => {
        const extensions =
          typeof rule.extensions === 'string'
            ? rule.extensions
                .split('\n')
                .map((ext) => ext.trim())
                .filter(Boolean)
            : rule.extensions || [];
        const names =
          typeof rule.names === 'string'
            ? rule.names
                .split('\n')
                .map((name) => name.trim())
                .filter(Boolean)
            : rule.names || [];
        const paths =
          typeof rule.paths === 'string'
            ? rule.paths
                .split('\n')
                .map((path) => path.trim())
                .filter(Boolean)
            : rule.paths || [];
        return { extensions, names, paths };
      })
      .filter((rule) => rule.extensions.length > 0 || rule.names.length > 0 || rule.paths.length > 0);

    const finalPayload = JSON.parse(JSON.stringify(config));
    if (Array.isArray(finalPayload.sync_del_mediaservers) && finalPayload.sync_del_mediaservers.length === 0) {
      finalPayload.sync_del_mediaservers = null;
    }

    emit('save', finalPayload);
    rawLoadedData.value = JSON.parse(JSON.stringify(config));
    await nextTick();
    baselineSnapshot.value = buildSnapshot();

    message.text = '配置已发送保存请求，请稍候...';
    message.type = 'info';
  } catch (err) {
    console.error('发送保存事件时出错:', err);
    message.text = `发送保存请求时出错: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    saveLoading.value = false;
    setTimeout(() => {
      if (message.type === 'info' || message.type === 'error') {
        message.text = '';
      }
    }, 5000);
  }
};

const getMachineId = async () => {
  machineId.value = '正在获取...';
  try {
    const result = await props.api.get(`plugin/${PLUGIN_ID}/get_machine_id`);
    if (result && result.machine_id) {
      machineId.value = result.machine_id;
      message.text = '设备ID获取成功！';
      message.type = 'success';
    } else {
      throw new Error(result?.msg || '未能获取设备ID');
    }
  } catch (err) {
    machineId.value = '获取失败，请重试';
    message.text = `获取设备ID失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  }
  setTimeout(() => {
    if (message.type === 'success' || message.type === 'info') {
      message.text = '';
    }
  }, 3000);
};

const formatAuthorizationExpiration = (utcTimeStr) => {
  if (!utcTimeStr) return '未知';
  try {
    const date = new Date(utcTimeStr);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return utcTimeStr;
  }
};

const openDonateDialog = async () => {
  donateDialog.show = true;
  donateDialog.loading = true;
  donateDialog.error = null;
  donateDialog.donateInfo = null;
  donateDialog.authorizationStatus = null;

  try {
    const [donateResult, authResult] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/get_donate_info`),
      props.api.get(`plugin/${PLUGIN_ID}/get_authorization_status`),
    ]);

    if (donateResult && donateResult.code === 0 && donateResult.data) {
      donateDialog.donateInfo = donateResult.data;
      if (donateResult.data.wechat?.enabled) {
        donateDialog.activeTab = 'wechat';
      } else if (donateResult.data.alipay?.enabled) {
        donateDialog.activeTab = 'alipay';
      }
    } else {
      throw new Error(donateResult?.msg || '获取捐赠信息失败');
    }

    if (authResult && authResult.code === 0 && authResult.data) {
      donateDialog.authorizationStatus = authResult.data;
    }
  } catch (err) {
    donateDialog.error = `加载捐赠信息失败: ${err.message || '未知错误'}`;
    console.error('获取捐赠信息失败:', err);
  } finally {
    donateDialog.loading = false;
  }
};

const closeDonateDialog = () => {
  donateDialog.show = false;
  donateDialog.error = null;
  donateDialog.donateInfo = null;
  donateDialog.authorizationStatus = null;
};

const handleConfirmFullSync = async () => {
  fullSyncConfirmDialog.value = false;
  await triggerFullSync();
};

const triggerFullSync = async () => {
  syncLoading.value = true;
  message.text = '';
  try {
    if (!config.enabled) throw new Error('插件未启用，请先启用插件');
    if (!config.cookies || config.cookies.trim() === '') throw new Error('请先设置115 Cookie');
    config.full_sync_strm_paths = generatePathsConfig(fullSyncPaths.value, 'fullSync');
    if (!config.full_sync_strm_paths) throw new Error('请先配置全量同步路径');

    const result = await props.api.post(`plugin/${PLUGIN_ID}/full_sync`);
    if (result && result.code === 0) {
      message.text = result.msg || '全量同步任务已启动';
      message.type = 'success';
    } else {
      throw new Error(result?.msg || '启动全量同步失败');
    }
  } catch (err) {
    message.text = `启动全量同步失败: ${err.message || '未知错误'}`;
    message.type = 'error';
    console.error('启动全量同步失败:', err);
  } finally {
    syncLoading.value = false;
  }
};

const clearIdPathCache = async () => {
  clearIdPathCacheLoading.value = true;
  message.text = '';
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/clear_id_path_cache`);
    if (result && result.code === 0) {
      message.text = result.msg || '文件路径ID缓存清理成功';
      message.type = 'success';
    } else {
      throw new Error(result?.msg || '文件路径ID缓存清理失败');
    }
  } catch (err) {
    message.text = `文件路径ID缓存清理失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    clearIdPathCacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') message.text = '';
    }, 3000);
  }
};

const clearP115ClientCache = async () => {
  clearP115ClientCacheLoading.value = true;
  message.text = '';
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/clear_p115client_cache`);
    if (result && result.code === 0) {
      message.text = result.msg || 'P115Client 缓存清理成功';
      message.type = 'success';
    } else {
      throw new Error(result?.msg || 'P115Client 缓存清理失败');
    }
  } catch (err) {
    message.text = `P115Client 缓存清理失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    clearP115ClientCacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') message.text = '';
    }, 3000);
  }
};

const clearIncrementSkipCache = async () => {
  clearIncrementSkipCacheLoading.value = true;
  message.text = '';
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/clear_increment_skip_cache`);
    if (result && result.code === 0) {
      message.text = result.msg || '增量同步跳过路径缓存清理成功';
      message.type = 'success';
    } else {
      throw new Error(result?.msg || '增量同步跳过路径缓存清理失败');
    }
  } catch (err) {
    message.text = `增量同步跳过路径缓存清理失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    clearIncrementSkipCacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') message.text = '';
    }, 3000);
  }
};

const clearR302Cache = async () => {
  clearR302CacheLoading.value = true;
  message.text = '';
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/clear_302_cache`);
    if (result && result.code === 0) {
      message.text = result.msg || '302跳转缓存清理成功';
      message.type = 'success';
    } else {
      throw new Error(result?.msg || '302跳转缓存清理失败');
    }
  } catch (err) {
    message.text = `302跳转缓存清理失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    clearR302CacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') message.text = '';
    }, 3000);
  }
};

const openImportDialog = () => {
  importDialog.jsonText = '';
  importDialog.error = '';
  importDialog.show = true;
};

const closeImportDialog = () => {
  importDialog.show = false;
};

const handleConfirmImport = () => {
  importDialog.error = '';
  if (!importDialog.jsonText || !importDialog.jsonText.trim()) {
    importDialog.error = '输入内容不能为空。';
    return;
  }
  try {
    const parsedData = JSON.parse(importDialog.jsonText);
    if (!Array.isArray(parsedData)) throw new Error('数据必须是一个数组。');
    const isValidStructure = parsedData.every(
      (item) => typeof item === 'object' && item !== null && 'name' in item && 'id' in item,
    );
    if (!isValidStructure) throw new Error("数组中的每个元素都必须是包含 'name' 和 'id' 键的对象。");
    tgChannels.value = parsedData.length > 0 ? parsedData : [{ name: '', id: '' }];
    message.text = '频道配置导入成功！';
    message.type = 'success';
    closeImportDialog();
  } catch (e) {
    importDialog.error = `导入失败: ${e.message}`;
  }
};

const copyCookieToClipboard = async () => {
  if (!config.cookies) {
    message.text = 'Cookie为空，无法复制。';
    message.type = 'warning';
    return;
  }
  try {
    await navigator.clipboard.writeText(config.cookies);
    message.text = 'Cookie已复制到剪贴板！';
    message.type = 'success';
  } catch {
    message.text = '复制Cookie失败。请检查浏览器权限或确保通过HTTPS访问，或尝试手动复制。';
    message.type = 'error';
  }
  setTimeout(() => {
    if (['success', 'warning', 'error'].includes(message.type)) message.text = '';
  }, 3000);
};

const copyAliTokenToClipboard = async () => {
  if (!config.aliyundrive_token) {
    message.text = 'Token为空，无法复制。';
    message.type = 'warning';
    return;
  }
  try {
    await navigator.clipboard.writeText(config.aliyundrive_token);
    message.text = '阿里云盘Token已复制到剪贴板！';
    message.type = 'success';
  } catch {
    message.text = '复制Token失败。请检查浏览器权限或手动复制。';
    message.type = 'error';
  }
  setTimeout(() => {
    message.text = '';
  }, 3000);
};

const openConfigGeneratorDialog = async () => {
  configGeneratorDialog.show = true;
  configGeneratorDialog.configType = configGeneratorDialog.configType || 'emby2alist';
  configGeneratorDialog.mountDir = config.fuse_strm_mount_dir || '/emby/115';
  configGeneratorDialog.moviepilotAddress = config.moviepilot_address || window.location.origin || 'http://localhost:3000';
  configGeneratorDialog.generatedConfig = '';
  await generateConfig();
};

const closeConfigGeneratorDialog = () => {
  configGeneratorDialog.show = false;
};

const generateConfig = async () => {
  try {
    configGeneratorDialog.loading = true;
    const mountDir = configGeneratorDialog.mountDir || '/emby/115';
    const moviepilotAddress =
      configGeneratorDialog.moviepilotAddress || window.location.origin || 'http://localhost:3000';
    const configType = configGeneratorDialog.configType || 'emby2alist';
    const response = await props.api.get(
      `plugin/${PLUGIN_ID}/generate_emby2alist_config?mount_dir=${encodeURIComponent(mountDir)}&moviepilot_address=${encodeURIComponent(moviepilotAddress)}&config_type=${encodeURIComponent(configType)}`,
    );

    if (response && response.code === 0 && response.data) {
      configGeneratorDialog.generatedConfig = response.data.generated_config || '';
      if (response.data.mount_dir) configGeneratorDialog.mountDir = response.data.mount_dir;
      if (response.data.moviepilot_address) configGeneratorDialog.moviepilotAddress = response.data.moviepilot_address;
      message.text = '配置生成成功！';
      message.type = 'success';
      setTimeout(() => {
        if (message.type === 'success') message.text = '';
      }, 3000);
    } else {
      message.text = response?.msg || '生成配置失败';
      message.type = 'error';
      setTimeout(() => {
        if (message.type === 'error') message.text = '';
      }, 3000);
    }
  } catch (err) {
    message.text = `生成配置失败: ${err.message || '未知错误'}`;
    message.type = 'error';
    setTimeout(() => {
      if (message.type === 'error') message.text = '';
    }, 3000);
  } finally {
    configGeneratorDialog.loading = false;
  }
};

watch(
  () => configGeneratorDialog.configType,
  (newVal, oldVal) => {
    if (!configGeneratorDialog.show || oldVal === undefined || newVal === oldVal) return;
    generateConfig();
  },
);

const copyGeneratedConfig = async () => {
  try {
    await navigator.clipboard.writeText(configGeneratorDialog.generatedConfig);
    message.text = '配置已复制到剪贴板！';
    message.type = 'success';
    setTimeout(() => {
      if (message.type === 'success') message.text = '';
    }, 3000);
  } catch {
    message.text = '复制失败，请手动复制';
    message.type = 'error';
    setTimeout(() => {
      if (message.type === 'error') message.text = '';
    }, 3000);
  }
};

const checkLifeEventStatus = async () => {
  lifeEventCheckDialog.show = true;
  lifeEventCheckDialog.loading = true;
  lifeEventCheckDialog.error = null;
  lifeEventCheckDialog.result = null;

  const body = {};
  const startTimeStr = (lifeEventCheckDialog.startTime || '').trim();
  if (startTimeStr) {
    const startDate = new Date(startTimeStr);
    if (!Number.isNaN(startDate.getTime())) {
      body.start_time = Math.floor(startDate.getTime() / 1000);
    }
  }

  try {
    const response = await props.api.post(
      `plugin/${PLUGIN_ID}/check_life_event_status`,
      Object.keys(body).length ? body : undefined,
    );
    if (response.code === 0) {
      lifeEventCheckDialog.result = response;
    } else {
      lifeEventCheckDialog.error = response.msg || '检查失败';
    }
  } catch (error) {
    lifeEventCheckDialog.error = error.message || '检查时发生错误';
  } finally {
    lifeEventCheckDialog.loading = false;
  }
};

const closeLifeEventCheckDialog = () => {
  lifeEventCheckDialog.show = false;
  lifeEventCheckDialog.error = null;
  lifeEventCheckDialog.result = null;
};

const copyDebugInfo = async () => {
  if (lifeEventCheckDialog.result?.data?.debug_info) {
    try {
      await navigator.clipboard.writeText(lifeEventCheckDialog.result.data.debug_info);
      message.text = '调试信息已复制到剪贴板';
      message.type = 'success';
    } catch {
      message.text = '复制失败，请手动选择文本复制';
      message.type = 'error';
    }
  }
};

const setMoviePilotAddressToCurrentOrigin = () => {
  if (typeof window !== 'undefined' && window.location?.origin) {
    config.moviepilot_address = window.location.origin;
    message.text = 'MoviePilot地址已设置为当前站点地址！';
    message.type = 'success';
  } else {
    message.text = '无法获取当前站点地址。';
    message.type = 'error';
  }
  setTimeout(() => {
    if (message.type === 'success' || message.type === 'error') message.text = '';
  }, 3000);
};

const handleKeydown = (e) => {
  const isMod = e.metaKey || e.ctrlKey;
  if (!isMod) return;
  if (e.key.toLowerCase() === 'k') {
    e.preventDefault();
    searchInputRef.value?.focus();
    searchInputRef.value?.select();
  } else if (e.key.toLowerCase() === 's') {
    e.preventDefault();
    if (!saveLoading.value && !loading.value) {
      saveConfig();
    }
  }
};

onMounted(async () => {
  const jump = consumeConfigJump();
  if (jump) {
    applyJumpTarget(jump);
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('keydown', handleKeydown);
  }
  await loadConfig();
  await checkTransferModuleEnhancement();
});

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', handleKeydown);
  }
});

watch(mainCategory, () => {
  if (contentPaneRef.value) {
    contentPaneRef.value.scrollTo({ top: 0, behavior: 'smooth' });
  }
});

// Provide Context to All Child Sections
provide('config', config);
provide('message', message);
provide('api', props.api);
provide('PLUGIN_ID', PLUGIN_ID);
provide('mediaservers', mediaservers);
provide('embyMediaservers', embyMediaservers);
provide('activeSubTabs', activeSubTabs);

// Path refs
provide('transferPaths', transferPaths);
provide('transferMpPaths', transferMpPaths);
provide('fullSyncPaths', fullSyncPaths);
provide('incrementSyncPaths', incrementSyncPaths);
provide('incrementSyncMPPaths', incrementSyncMPPaths);
provide('monitorLifePaths', monitorLifePaths);
provide('monitorLifeMpPaths', monitorLifeMpPaths);
provide('apiStrmPaths', apiStrmPaths);
provide('apiStrmMPPaths', apiStrmMPPaths);
provide('panTransferPaths', panTransferPaths);
provide('shareReceivePaths', shareReceivePaths);
provide('offlineDownloadPaths', offlineDownloadPaths);
provide('transferExcludePaths', transferExcludePaths);
provide('incrementSyncExcludePaths', incrementSyncExcludePaths);
provide('monitorLifeExcludePaths', monitorLifeExcludePaths);
provide('directoryUploadPaths', directoryUploadPaths);
provide('syncDelLibraryPaths', syncDelLibraryPaths);
provide('fuseStrmTakeoverRules', fuseStrmTakeoverRules);

// Path actions
provide('addPath', addPath);
provide('removePath', removePath);
provide('addPanTransferPath', addPanTransferPath);
provide('removePanTransferPath', removePanTransferPath);
provide('addShareReceivePath', addShareReceivePath);
provide('removeShareReceivePath', removeShareReceivePath);
provide('addOfflineDownloadPath', addOfflineDownloadPath);
provide('removeOfflineDownloadPath', removeOfflineDownloadPath);
provide('generatePathsConfig', generatePathsConfig);

// Dir selector
provide('openDirSelector', openDirSelector);
provide('openExcludeDirSelector', openExcludeDirSelector);
provide('removeExcludePathEntry', removeExcludePathEntry);

// Size
provide('parseSize', parseSize);
provide('formatBytes', formatBytes);
provide('skipUploadWaitSizeFormattedRef', skipUploadWaitSizeFormattedRef);
provide('forceUploadWaitSizeFormattedRef', forceUploadWaitSizeFormattedRef);
provide('skipSlowUploadSizeFormattedRef', skipSlowUploadSizeFormattedRef);
provide('fullSyncMinFileSizeFormattedRef', fullSyncMinFileSizeFormattedRef);
provide('incrementSyncMinFileSizeFormattedRef', incrementSyncMinFileSizeFormattedRef);
provide('monitorLifeMinFileSizeFormattedRef', monitorLifeMinFileSizeFormattedRef);

// Loading states
provide('syncLoading', syncLoading);
provide('clearIdPathCacheLoading', clearIdPathCacheLoading);
provide('clearP115ClientCacheLoading', clearP115ClientCacheLoading);
provide('clearIncrementSkipCacheLoading', clearIncrementSkipCacheLoading);
provide('clearR302CacheLoading', clearR302CacheLoading);

// UI states & Credential helpers
provide('isTransferModuleEnhancementLocked', isTransferModuleEnhancementLocked);
provide('isCookieVisible', isCookieVisible);
provide('isAliTokenVisible', isAliTokenVisible);
provide('openQrCodeDialog', openQrCodeDialog);
provide('openAliQrCodeDialog', openAliQrCodeDialog);
provide('copyCookieToClipboard', copyCookieToClipboard);
provide('copyAliTokenToClipboard', copyAliTokenToClipboard);
provide('setMoviePilotAddressToCurrentOrigin', setMoviePilotAddressToCurrentOrigin);

// Actions
provide('triggerFullSync', triggerFullSync);
provide('clearIdPathCache', clearIdPathCache);
provide('clearP115ClientCache', clearP115ClientCache);
provide('clearIncrementSkipCache', clearIncrementSkipCache);
provide('clearR302Cache', clearR302Cache);
provide('checkLifeEventStatus', checkLifeEventStatus);
provide('openConfigGeneratorDialog', openConfigGeneratorDialog);
provide('manualTransfer', manualTransfer);
provide('openDonateDialog', openDonateDialog);
provide('getMachineId', getMachineId);
provide('formatAuthorizationExpiration', formatAuthorizationExpiration);
provide('copyDebugInfo', copyDebugInfo);

// Dialog states
provide('fullSyncConfirmDialog', fullSyncConfirmDialog);
provide('lifeEventCheckDialog', lifeEventCheckDialog);
provide('tgChannels', tgChannels);
provide('addTgChannel', addTgChannel);
provide('removeTgChannel', removeTgChannel);
provide('openImportDialog', openImportDialog);
provide('machineId', machineId);
</script>

<style scoped>
.p115-config-shell {
  position: relative;
  z-index: 2;
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  overflow: hidden;
}

/* macOS Sequoia Vibrancy Sidebar */
.p115-config-sidebar {
  position: relative;
  background: var(--p115-bg-sidebar);
  border-right: 1px solid var(--p115-border-hairline);
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
}

.p115-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
  border-radius: 10px;
  padding: 0 8px 0 10px;
  height: 35px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.p115-search-wrap:focus-within {
  border-color: var(--p115-blue);
  box-shadow: 0 0 0 3px rgba(91, 207, 250, 0.2);
}

.p115-search-icon {
  color: var(--p115-text-tertiary);
  margin-right: 6px;
  flex-shrink: 0;
}

.p115-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--p115-text-primary);
  font-family: var(--p115-font-sans);
  font-size: 0.8rem;
}

.p115-search-input::placeholder {
  color: var(--p115-text-tertiary);
}

.p115-search-clear {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--p115-text-tertiary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  padding: 2px;
}

.p115-search-results {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 290px;
  overflow-y: auto;
  padding: 6px;
  border-radius: 12px;
  background: var(--p115-bg-card);
  border: 1px solid var(--p115-border-accent);
  box-shadow: var(--p115-shadow-card);
}

.p115-search-empty {
  font-size: 0.76rem;
  color: var(--p115-text-secondary);
  padding: 8px;
  text-align: center;
}

.p115-search-hit {
  appearance: none;
  text-align: left;
  border: 1px solid transparent;
  border-radius: 9px;
  background: var(--p115-bg-inset);
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.p115-search-hit:hover {
  border-color: var(--p115-border-accent);
  background: var(--p115-bg-hover);
}

.p115-search-hit-title {
  font-size: 0.76rem;
  color: var(--p115-text-secondary);
  line-height: 1.35;
}

/* Desktop Sidebar Navigation Items */
.p115-sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.p115-nav-item {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 11px;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  color: var(--p115-text-secondary);
  font-family: var(--p115-font-sans);
  font-size: 0.86rem;
  font-weight: 540;
  text-align: left;
  transition:
    background-color 0.18s ease,
    color 0.18s ease,
    transform 0.1s var(--p115-press);
}

.p115-nav-item:hover:not(.p115-nav-item--active) {
  background: var(--p115-bg-hover);
  color: var(--p115-text-primary);
}

.p115-nav-item:active {
  transform: scale(0.98);
}

.p115-nav-item--active {
  background: var(--p115-bg-seg-pill);
  color: var(--p115-text-primary);
  font-weight: 640;
  box-shadow: var(--p115-shadow-pill);
  border-color: var(--p115-border-hairline);
}

.p115-nav-icon-box {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  flex-shrink: 0;
}

.p115-nav-icon-box--blue {
  background: linear-gradient(135deg, #5bcffa 0%, #2eb8f0 100%);
}

.p115-nav-icon-box--pink {
  background: linear-gradient(135deg, #f5abb9 0%, #ec849c 100%);
}

.p115-nav-icon-box--amber {
  background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
}

.p115-nav-icon-box--green {
  background: linear-gradient(135deg, #34c759 0%, #22c55e 100%);
}

.p115-nav-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.p115-nav-badge {
  font-size: 0.7rem;
  font-weight: 620;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(91, 207, 250, 0.16);
  color: var(--p115-blue-ink);
}

.p115-mobile-catbar {
  display: none;
}

/* Right Content Stage */
.p115-config-stage {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  transform: translateZ(0);
  padding: 18px 22px 28px;
}

.p115-stage-inner {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.p115-config-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

/* Tablet & Mobile Responsive Layout (< 960px) */
@media (max-width: 960px) {
  .p115-config-shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }

  .p115-config-sidebar {
    min-width: 0;
    max-width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--p115-border-hairline);
    padding: 8px 10px;
    gap: 8px;
    overflow: hidden;
  }

  .p115-sidebar-nav {
    display: none;
  }

  .p115-mobile-catbar {
    display: block;
    width: 100%;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }

  .p115-config-stage {
    min-width: 0;
    max-width: 100%;
    padding: 12px 10px 20px;
  }
}

@media (max-width: 599px) {
  .p115-config-footer {
    flex-wrap: nowrap;
    gap: 6px;
  }

  .p115-config-footer > .p115-btn,
  .p115-config-actions > .p115-btn {
    padding: 7px 9px;
    font-size: 0.76rem;
  }

  .p115-config-actions {
    flex-wrap: nowrap;
    gap: 6px;
  }
}
</style>
