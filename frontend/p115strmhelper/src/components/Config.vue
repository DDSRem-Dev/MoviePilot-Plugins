<template>
  <div class="plugin-config">
    <v-card flat class="rounded border config-main-card" style="display: flex; flex-direction: column;">
      <!-- 标题区域 -->
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-1 bg-primary-lighten-5">
        <v-icon icon="mdi-cog" class="mr-2" color="primary" size="small" />
        <span>115网盘STRM助手配置</span>
      </v-card-title>

      <!-- 通知区域 -->
      <v-card-text class="px-3 py-2"
        style="flex-grow: 1; min-height: 0; overflow-y: auto; padding-bottom: 56px; -webkit-overflow-scrolling: touch;">
        <transition name="alert-fade" appear>
          <v-alert v-if="message.text" :type="message.type" density="compact" class="mb-2 text-caption" variant="tonal"
            closable>{{ message.text }}</v-alert>
        </transition>

        <transition name="content-fade" mode="out-in">
          <v-skeleton-loader v-if="loading" key="skeleton" type="article, actions"></v-skeleton-loader>

          <div v-else key="content" class="my-1">
            <!-- 基础设置 -->
            <v-expansion-panels v-model="basicConfigExpanded" variant="tonal" class="mb-3" multiple>
              <v-expansion-panel value="basic-config" class="rounded border config-card" eager>
                <v-expansion-panel-title class="text-subtitle-2 d-flex align-center px-3 py-2 bg-primary-lighten-5">
                  <v-icon icon="mdi-cog" class="mr-2" color="primary" size="small" />
                  <span>基础设置</span>
                </v-expansion-panel-title>
                <v-expansion-panel-text class="pa-3" eager>
                  <v-row>
                    <v-col cols="12" md="4">
                      <v-switch v-model="config.enabled" label="启用插件" color="success" density="compact"></v-switch>
                    </v-col>
                    <v-col cols="12" md="4">
                      <v-select v-model="config.strm_url_format" label="STRM文件URL格式" :items="[
                        { title: 'pickcode', value: 'pickcode' },
                        { title: 'pickcode + name', value: 'pickname' }
                      ]"
                        :hint="config.strm_url_template_enabled ? '已启用自定义模板时优先使用模板，模板渲染失败时将使用此设置作为后备方案' : '选择 STRM 文件的 URL 格式'"
                        persistent-hint chips closable-chips></v-select>
                    </v-col>
                    <v-col cols="12" md="4">
                      <v-select v-model="config.link_redirect_mode" label="直链获取模式" :items="[
                        { title: 'Cookie', value: 'cookie' },
                        { title: 'OpenAPI', value: 'open' }
                      ]" chips closable-chips></v-select>
                    </v-col>
                  </v-row>
                  <v-row>
                    <v-col cols="12" md="4">
                      <v-switch v-model="config.notify" label="发送通知" color="success" density="compact"></v-switch>
                    </v-col>
                    <v-col cols="12" md="8">
                      <v-select v-model="config.language" label="通知语言" :items="[
                        { title: '简体中文', value: 'zh_CN' },
                        { title: '繁中台湾', value: 'zh_TW' },
                        { title: '繁中港澳', value: 'zh_HK' },
                        { title: '柔情猫娘', value: 'zh_CN_catgirl' },
                        { title: '粤韵风华', value: 'zh_yue' },
                        { title: '咚咚搬砖', value: 'zh_CN_dong' }
                      ]" chips closable-chips></v-select>
                    </v-col>
                  </v-row>
                  <v-row>
                    <v-col cols="12" md="4">
                      <v-text-field v-model="config.cookies" label="115 Cookie" hint="点击图标切换显隐、复制或扫码" persistent-hint
                        density="compact" variant="outlined" hide-details="auto"
                        :type="isCookieVisible ? 'text' : 'password'">
                        <template v-slot:append-inner>
                          <v-icon :icon="isCookieVisible ? 'mdi-eye-off' : 'mdi-eye'"
                            @click="isCookieVisible = !isCookieVisible"
                            :aria-label="isCookieVisible ? '隐藏Cookie' : '显示Cookie'"
                            :title="isCookieVisible ? '隐藏Cookie' : '显示Cookie'" class="mr-1" size="small"></v-icon>
                          <v-icon icon="mdi-content-copy" @click="copyCookieToClipboard" :disabled="!config.cookies"
                            aria-label="复制Cookie" title="复制Cookie到剪贴板" size="small" class="mr-1"></v-icon>
                        </template>
                        <template v-slot:append>
                          <v-icon icon="mdi-qrcode-scan" @click="openQrCodeDialog"
                            :color="config.cookies ? 'success' : 'default'"
                            :aria-label="config.cookies ? '更新/更换Cookie (重新扫码)' : '扫码获取Cookie'"
                            :title="config.cookies ? '更新/更换Cookie (重新扫码)' : '扫码获取Cookie'"></v-icon>
                        </template>
                      </v-text-field>
                    </v-col>
                    <!-- 阿里云盘 Token 配置 -->
                    <v-col cols="12" md="4">
                      <v-text-field v-model="config.aliyundrive_token" label="阿里云盘 Token (可选)"
                        hint="非必填。点击图标切换显隐、复制或扫码获取" persistent-hint density="compact" variant="outlined"
                        hide-details="auto" :type="isAliTokenVisible ? 'text' : 'password'">
                        <template v-slot:append-inner>
                          <v-icon :icon="isAliTokenVisible ? 'mdi-eye-off' : 'mdi-eye'"
                            @click="isAliTokenVisible = !isAliTokenVisible"
                            :aria-label="isAliTokenVisible ? '隐藏Token' : '显示Token'"
                            :title="isAliTokenVisible ? '隐藏Token' : '显示Token'" class="mr-1" size="small"></v-icon>
                          <v-icon icon="mdi-content-copy" @click="copyAliTokenToClipboard"
                            :disabled="!config.aliyundrive_token" aria-label="复制Token" title="复制Token到剪贴板" size="small"
                            class="mr-1"></v-icon>
                        </template>
                        <template v-slot:append>
                          <v-icon icon="mdi-qrcode-scan" @click="openAliQrCodeDialog"
                            :color="config.aliyundrive_token ? 'success' : 'default'"
                            :aria-label="config.aliyundrive_token ? '更新/更换Token' : '扫码获取Token'"
                            :title="config.aliyundrive_token ? '更新/更换Token' : '扫码获取Token'"></v-icon>
                        </template>
                      </v-text-field>
                    </v-col>
                    <v-col cols="12" md="4">
                      <v-text-field v-model="config.moviepilot_address" label="STRM 文件内链接地址" hint="点右侧图标自动填充当前站点地址。"
                        persistent-hint density="compact" variant="outlined" hide-details="auto">
                        <template v-slot:append>
                          <v-icon icon="mdi-web" @click="setMoviePilotAddressToCurrentOrigin" aria-label="使用当前站点地址"
                            title="使用当前站点地址" color="info"></v-icon>
                        </template>
                      </v-text-field>
                    </v-col>
                  </v-row>
                  <v-row>
                    <v-col cols="12" md="6">
                      <v-text-field v-model="config.user_rmt_mediaext" label="可整理媒体文件扩展名" hint="支持的媒体文件扩展名，多个用逗号分隔"
                        persistent-hint density="compact" variant="outlined" hide-details="auto"></v-text-field>
                    </v-col>
                    <v-col cols="12" md="6">
                      <v-text-field v-model="config.user_download_mediaext" label="可下载媒体数据文件扩展名"
                        hint="下载的字幕等附属文件扩展名，多个用逗号分隔" persistent-hint density="compact" variant="outlined"
                        hide-details="auto"></v-text-field>
                    </v-col>
                  </v-row>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>

            <!-- 标签页 -->
            <v-card flat class="rounded mb-3 border config-card">
              <!-- 主分类标签 -->
              <v-tabs v-model="mainCategory" color="primary" class="main-category-tabs" grow>
                <v-tab value="category-strm" class="main-tab">
                  <v-icon size="small" start>mdi-file-link</v-icon>STRM同步
                </v-tab>
                <v-tab value="category-pan" class="main-tab">
                  <v-icon size="small" start>mdi-cloud</v-icon>网盘管理
                </v-tab>
                <v-tab value="category-other" class="main-tab">
                  <v-icon size="small" start>mdi-puzzle</v-icon>其他功能
                </v-tab>
                <v-tab value="category-system" class="main-tab">
                  <v-icon size="small" start>mdi-cog</v-icon>系统配置
                </v-tab>
              </v-tabs>
              <v-divider></v-divider>

              <!-- 主分类内容区域 -->
              <v-window v-model="mainCategory" :touch="false" class="tab-window">
                <!-- STRM同步分类 -->
                <v-window-item value="category-strm">
                  <StrmSyncSection />
                </v-window-item>

                <!-- 网盘管理分类 -->
                <v-window-item value="category-pan">
                  <PanManagementSection />
                </v-window-item>

                <!-- 其他功能分类 -->
                <v-window-item value="category-other">
                  <OtherFeaturesSection />
                </v-window-item>

                <!-- 系统配置分类 -->
                <v-window-item value="category-system">
                  <SystemConfigSection />
                </v-window-item>
              </v-window>
            </v-card>

            <!-- 操作按钮 -->

          </div>
        </transition>
      </v-card-text>
      <v-card-actions class="px-3 py-2 d-flex" style="flex-shrink: 0;">
        <v-btn color="warning" variant="text" @click="emit('switch')" size="small" prepend-icon="mdi-arrow-left">
          返回
        </v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="openDonateDialog" size="small" prepend-icon="mdi-gift">
          捐赠
        </v-btn>
        <v-btn color="warning" variant="text" @click="fullSyncConfirmDialog = true" size="small"
          prepend-icon="mdi-sync">
          全量同步
        </v-btn>
        <v-btn color="success" variant="text" @click="saveConfig" :loading="saveLoading" size="small"
          prepend-icon="mdi-content-save">
          保存配置
        </v-btn>
      </v-card-actions>
    </v-card>

    <!-- 全量同步确认对话框 -->
    <FullSyncConfirmDialog v-model="fullSyncConfirmDialog" :loading="syncLoading"
      :has-media-server-refresh="config.full_sync_media_server_refresh_enabled" @confirm="handleConfirmFullSync" />

    <!-- 目录选择器对话框 -->
    <DirSelectorDialog :dir-dialog="dirDialog" @load-dir="loadDirContent" @navigate-up="navigateToParentDir"
      @select-dir="selectDir" @confirm="confirmDirSelection" @close="closeDirDialog" />

    <!-- 手动整理确认对话框 -->
    <ManualTransferDialog :manual-transfer-dialog="manualTransferDialog" @confirm="confirmManualTransfer"
      @close="closeManualTransferDialog" />

    <!-- 115网盘扫码登录对话框 -->
    <QrCodeDialog :qr-dialog="qrDialog" :client-types="clientTypes" @refresh="refreshQrCode" @close="closeQrDialog" />

    <!-- 阿里云盘扫码登录对话框 -->
    <AliQrCodeDialog :ali-qr-dialog="aliQrDialog" @refresh="refreshAliQrCode" @close="closeAliQrCodeDialog" />

    <!-- 捐赠/授权对话框 -->
    <DonateDialog :donate-dialog="donateDialog" :format-authorization-expiration="formatAuthorizationExpiration"
      @close="closeDonateDialog" />

    <!-- Emby 反代 302 配置生成对话框 -->
    <ConfigGeneratorDialog :config-generator-dialog="configGeneratorDialog" @close="closeConfigGeneratorDialog"
      @copy="copyGeneratedConfig" @regenerate="generateConfig" />

    <!-- 生活事件故障检查对话框 -->
    <LifeEventCheckDialog :life-event-check-dialog="lifeEventCheckDialog" @check="checkLifeEventStatus"
      @close="closeLifeEventCheckDialog" @copy-debug="copyDebugInfo" />

    <!-- 频道配置导入对话框 -->
    <ImportChannelDialog :import-dialog="importDialog" @close="closeImportDialog" @confirm="handleConfirmImport" />

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, provide } from 'vue';
import { P115_STRM_HELPER_PLUGIN_ID } from '../utils/pluginId.js';
import { usePathManagement } from './composables/usePathManagement.js';
import { useQrCode } from './composables/useQrCode.js';
import { useDirSelector } from './composables/useDirSelector.js';
import { useSizeFormatter } from './composables/useSizeFormatter.js';
import QrCodeDialog from './dialogs/QrCodeDialog.vue';
import AliQrCodeDialog from './dialogs/AliQrCodeDialog.vue';
import DirSelectorDialog from './dialogs/DirSelectorDialog.vue';
import DonateDialog from './dialogs/DonateDialog.vue';
import ConfigGeneratorDialog from './dialogs/ConfigGeneratorDialog.vue';
import LifeEventCheckDialog from './dialogs/LifeEventCheckDialog.vue';
import ManualTransferDialog from './dialogs/ManualTransferDialog.vue';
import FullSyncConfirmDialog from './dialogs/FullSyncConfirmDialog.vue';
import ImportChannelDialog from './dialogs/ImportChannelDialog.vue';
import StrmSyncSection from './sections/StrmSyncSection.vue';
import PanManagementSection from './sections/PanManagementSection.vue';
import OtherFeaturesSection from './sections/OtherFeaturesSection.vue';
import SystemConfigSection from './sections/SystemConfigSection.vue';

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true
  },
  initialConfig: {
    type: Object,
    default: () => ({})
  }
});

const emit = defineEmits(['save', 'close', 'switch']);

const PLUGIN_ID = P115_STRM_HELPER_PLUGIN_ID;

// 状态变量
const loading = ref(true);
const saveLoading = ref(false);
const syncLoading = ref(false);
const clearIdPathCacheLoading = ref(false);
const clearIncrementSkipCacheLoading = ref(false);
const clearR302CacheLoading = ref(false);
// 主分类标签
const mainCategory = ref('category-strm');
const mediaservers = ref([]);
// 过滤出 Emby 类型的媒体服务器（用于同步删除功能）
const embyMediaservers = computed(() => {
  return mediaservers.value.filter(server => server.type === 'emby');
});
const isCookieVisible = ref(false);
const isAliTokenVisible = ref(false);
const isTransferModuleEnhancementLocked = ref(true);
// 基础设置折叠状态
const basicConfigExpanded = ref((() => {
  try {
    const saved = localStorage.getItem('p115strmhelper_basic_config_expanded');
    return saved !== null ? JSON.parse(saved) : ['basic-config'];
  } catch (e) {
    return ['basic-config'];
  }
})());
const config = reactive({
  language: "zh_CN",
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
  full_sync_overwrite_mode: "never",
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
  full_sync_cleanup_confirm_mode: "none",
  increment_sync_strm_enabled: false,
  increment_sync_auto_download_mediainfo_enabled: false,
  increment_sync_cron: "0 * * * *",
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
  directory_upload_enabled: false,
  directory_upload_mode: 'compatibility',
  directory_upload_uploadext: 'mp4,mkv,ts,iso,rmvb,avi,mov,mpeg,mpg,wmv,3gp,asf,m4v,flv,m2ts,tp,f4v',
  directory_upload_copyext: 'srt,ssa,ass',
  directory_upload_skip_bdmv_stream: true,
  directory_upload_path: [],
  directory_upload_clouddrive2_config: { enabled: false, prefix: '' },
  tg_search_channels: [],
  hdhive_search_enabled: false,
  hdhive_checkin_username: '',
  hdhive_checkin_password: '',
  hdhive_checkin_daily_enabled: false,
  hdhive_checkin_gamble_enabled: false,
  hdhive_checkin_time_range: '06:00-09:00',
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

// 消息提示
const message = reactive({
  text: '',
  type: 'info'
});

// 使用 composables
const pathMgmt = usePathManagement(config);
const {
  transferPaths, transferMpPaths, fullSyncPaths, incrementSyncPaths, incrementSyncMPPaths,
  monitorLifePaths, monitorLifeMpPaths, apiStrmPaths, apiStrmMPPaths, panTransferPaths,
  shareReceivePaths, offlineDownloadPaths, transferExcludePaths, incrementSyncExcludePaths,
  monitorLifeExcludePaths, directoryUploadPaths, syncDelLibraryPaths, fuseStrmTakeoverRules,
  generatePathsConfig,
  addPath, removePath, addPanTransferPath, removePanTransferPath,
  addShareReceivePath, removeShareReceivePath, addOfflineDownloadPath, removeOfflineDownloadPath,
} = pathMgmt;

const qrMgmt = useQrCode(props.api, config, message, PLUGIN_ID);
const {
  qrDialog, aliQrDialog, clientTypes,
  openQrCodeDialog, refreshQrCode, closeQrDialog,
  openAliQrCodeDialog, refreshAliQrCode, closeAliQrCodeDialog,
} = qrMgmt;

const dirMgmt = useDirSelector(props.api, config, message, PLUGIN_ID, pathMgmt);
const {
  dirDialog,
  openDirSelector, loadDirContent, selectDir, navigateToParentDir, confirmDirSelection, closeDirDialog,
  openExcludeDirSelector, removeExcludePathEntry,
} = dirMgmt;

// 文件大小输入使用 ref，避免输入时 get 返回 formatBytes 导致内容被重写（如输入 "500M" 时被截断）
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
  error: ''
});

// 捐赠对话框
const donateDialog = reactive({
  show: false,
  loading: false,
  error: null,
  donateInfo: null,
  activeTab: 'wechat',
  authorizationStatus: null,
});

// 生活事件故障检查对话框
const lifeEventCheckDialog = reactive({
  show: false,
  loading: false,
  error: null,
  result: null,
  startTime: '', // 拉取指定时间内的全部数据的开始时间（datetime-local 字符串）
});

// emby2Alist 配置生成对话框
const configGeneratorDialog = reactive({
  show: false,
  loading: false,
  configType: 'emby2alist', // 'emby2alist' | 'emby_reverse_proxy'
  mountDir: '',
  moviepilotAddress: '',
  generatedConfig: ''
});

// 手动整理对话框
const manualTransferDialog = reactive({
  show: false,
  loading: false,
  path: '',
  result: null, // { type: 'success' | 'error', title: string, message: string }
});

const manualTransfer = (index) => {
  if (index < 0 || index >= panTransferPaths.value.length) {
    message.text = '路径项不存在';
    message.type = 'error';
    return;
  }
  const pathItem = panTransferPaths.value[index];
  if (!pathItem) {
    message.text = '路径项不存在';
    message.type = 'error';
    return;
  }
  const path = pathItem.path;
  if (!path || typeof path !== 'string' || !path.trim()) {
    message.text = '请先配置网盘路径';
    message.type = 'warning';
    return;
  }
  Object.assign(manualTransferDialog, {
    path: path.trim(),
    loading: false,
    result: null,
    show: true
  });
};

const confirmManualTransfer = async () => {
  if (!manualTransferDialog.path) return;
  manualTransferDialog.loading = true;
  manualTransferDialog.result = null;
  try {
    const result = await props.api.post(`plugin/${PLUGIN_ID}/manual_transfer`, {
      path: manualTransferDialog.path
    });
    if (result.code === 0) {
      manualTransferDialog.result = {
        type: 'success',
        title: '整理任务已启动',
        message: '整理任务已在后台启动，正在执行中。您可以在日志中查看详细进度。'
      };
    } else {
      manualTransferDialog.result = {
        type: 'error',
        title: '启动失败',
        message: result.msg || '启动整理任务失败，请检查配置和网络连接。'
      };
    }
  } catch (error) {
    manualTransferDialog.result = {
      type: 'error',
      title: '启动失败',
      message: `启动整理任务时发生错误：${error.message || error}`
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
    result: null
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

// 加载配置
const loadConfig = async () => {
  try {
    loading.value = true;
    const data = await props.api.get(`plugin/${PLUGIN_ID}/get_config`);
    if (data) {
      Object.assign(config, data);
      directoryUploadPaths.value = (Array.isArray(config.directory_upload_path) && config.directory_upload_path.length > 0)
        ? config.directory_upload_path.map(p => ({ src: p.src ?? '', dest_remote: p.dest_remote ?? '', dest_local: p.dest_local ?? '', dest_strm: p.dest_strm ?? '', delete: !!p.delete }))
        : [{ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }];
      let parsedChannels = [];
      if (config.tg_search_channels) {
        if (Array.isArray(config.tg_search_channels)) {
          parsedChannels = config.tg_search_channels;
        }
        else if (typeof config.tg_search_channels === 'string') {
          try {
            parsedChannels = JSON.parse(config.tg_search_channels);
          } catch (e) {
            console.error('解析旧的TG频道配置字符串失败:', e);
            parsedChannels = [];
          }
        }
      }
      if (Array.isArray(parsedChannels) && parsedChannels.length > 0) {
        tgChannels.value = parsedChannels;
      } else {
        tgChannels.value = [{ name: '', id: '' }];
      }
      if (data.mediaservers) {
        mediaservers.value = data.mediaservers;
      }
      // 加载 FUSE STRM 接管规则
      if (config.fuse_strm_takeover_rules && Array.isArray(config.fuse_strm_takeover_rules) && config.fuse_strm_takeover_rules.length > 0) {
        fuseStrmTakeoverRules.value = config.fuse_strm_takeover_rules.map(rule => {
          const extensions = Array.isArray(rule.extensions) ? rule.extensions : [];
          const names = Array.isArray(rule.names) ? rule.names : [];
          const paths = Array.isArray(rule.paths) ? rule.paths : [];
          return {
            extensions: extensions.join('\n'),
            names: names.join('\n'),
            paths: paths.join('\n'),
            _use_extensions: extensions.length > 0,
            _use_names: names.length > 0,
            _use_paths: paths.length > 0
          };
        });
      } else {
        fuseStrmTakeoverRules.value = [{ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }];
      }
      // 确保 sync_del_mediaservers 如果是 null，转换为空数组以匹配前端显示
      if (config.sync_del_mediaservers === null || config.sync_del_mediaservers === undefined) {
        config.sync_del_mediaservers = [];
      }
      const p115LocalPaths = new Set();
      if (config.transfer_monitor_paths) {
        config.transfer_monitor_paths.split('\n')
          .map(p => p.split('#')[0]?.trim()).filter(p => p).forEach(p => p115LocalPaths.add(p));
      }
      if (config.full_sync_strm_paths) {
        config.full_sync_strm_paths.split('\n')
          .map(p => p.split('#')[0]?.trim()).filter(p => p).forEach(p => p115LocalPaths.add(p));
      }
      if (config.monitor_life_paths) {
        config.monitor_life_paths.split('\n')
          .map(p => p.split('#')[0]?.trim()).filter(p => p).forEach(p => p115LocalPaths.add(p));
      }
      // 文件大小输入框：从 config 同步到 ref，避免输入时被 formatBytes 重写
      skipUploadWaitSizeFormattedRef.value = (config.upload_module_skip_upload_wait_size > 0) ? formatBytes(config.upload_module_skip_upload_wait_size) : '';
      forceUploadWaitSizeFormattedRef.value = (config.upload_module_force_upload_wait_size > 0) ? formatBytes(config.upload_module_force_upload_wait_size) : '';
      skipSlowUploadSizeFormattedRef.value = (config.upload_module_skip_slow_upload_size > 0) ? formatBytes(config.upload_module_skip_slow_upload_size) : '';
      fullSyncMinFileSizeFormattedRef.value = (config.full_sync_min_file_size > 0) ? formatBytes(config.full_sync_min_file_size) : '';
      incrementSyncMinFileSizeFormattedRef.value = (config.increment_sync_min_file_size > 0) ? formatBytes(config.increment_sync_min_file_size) : '';
      monitorLifeMinFileSizeFormattedRef.value = (config.monitor_life_min_file_size > 0) ? formatBytes(config.monitor_life_min_file_size) : '';
    }
  } catch (err) {
    console.error('加载配置失败:', err);
    message.text = `加载配置失败: ${err.message || '未知错误'}`;
    message.type = 'error';
  } finally {
    loading.value = false;
  }
};

// 保存配置
const saveConfig = async () => {
  saveLoading.value = true;
  message.text = '';
  message.type = 'info';
  try {
    // 文件大小输入框：从 ref 同步到 config 再提交
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
      .filter(p => p.local?.trim() && p.remote?.trim())
      .map(p => ({ local_path: p.local.trim(), pan_path: p.remote.trim() }));
    config.api_strm_mp_mediaserver_paths = generatePathsConfig(apiStrmMPPaths.value, 'apiStrm-mp');
    config.sync_del_p115_library_path = syncDelLibraryPaths.value
      .filter(p => p.mediaserver?.trim() || p.moviepilot?.trim() || p.p115?.trim())
      .map(p => `${p.mediaserver || ''}#${p.moviepilot || ''}#${p.p115 || ''}`)
      .join('\n');
    // 处理 sync_del_mediaservers：如果数组为空，转换为 null 以匹配后端的 Optional[List[str]]
    if (Array.isArray(config.sync_del_mediaservers) && config.sync_del_mediaservers.length === 0) {
      config.sync_del_mediaservers = null;
    }
    config.pan_transfer_paths = generatePathsConfig(panTransferPaths.value, 'panTransfer');
    config.share_recieve_paths = shareReceivePaths.value.filter(p => p.path?.trim()).map(p => p.path);
    config.offline_download_paths = offlineDownloadPaths.value.filter(p => p.path?.trim()).map(p => p.path);
    config.directory_upload_path = directoryUploadPaths.value.filter(p => p.src?.trim() || p.dest_remote?.trim() || p.dest_local?.trim() || p.dest_strm?.trim());
    const validChannels = tgChannels.value.filter(
      c => c.name && c.name.trim() !== '' && c.id && c.id.trim() !== ''
    );
    config.tg_search_channels = validChannels;
    // 保存 FUSE STRM 接管规则
    config.fuse_strm_takeover_rules = fuseStrmTakeoverRules.value
      .map(rule => {
        const extensions = typeof rule.extensions === 'string'
          ? rule.extensions.split('\n').map(ext => ext.trim()).filter(ext => ext)
          : (rule.extensions || []);
        const names = typeof rule.names === 'string'
          ? rule.names.split('\n').map(name => name.trim()).filter(name => name)
          : (rule.names || []);
        const paths = typeof rule.paths === 'string'
          ? rule.paths.split('\n').map(path => path.trim()).filter(path => path)
          : (rule.paths || []);
        return { extensions, names, paths };
      })
      .filter(rule => rule.extensions.length > 0 || rule.names.length > 0 || rule.paths.length > 0);
    emit('save', JSON.parse(JSON.stringify(config)));
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

// 格式化授权过期时间（UTC转本地时间）
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
      hour12: false
    });
  } catch (err) {
    console.error('格式化时间失败:', err);
    return utcTimeStr;
  }
};

// 打开捐赠对话框
const openDonateDialog = async () => {
  donateDialog.show = true;
  donateDialog.loading = true;
  donateDialog.error = null;
  donateDialog.donateInfo = null;
  donateDialog.authorizationStatus = null;

  try {
    // 并行获取捐赠信息和授权状态
    const [donateResult, authResult] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/get_donate_info`),
      props.api.get(`plugin/${PLUGIN_ID}/get_authorization_status`)
    ]);

    // 处理捐赠信息
    if (donateResult && donateResult.code === 0 && donateResult.data) {
      donateDialog.donateInfo = donateResult.data;
      // 设置默认激活的tab（默认优先微信）
      if (donateResult.data.wechat?.enabled) {
        donateDialog.activeTab = 'wechat';
      } else if (donateResult.data.alipay?.enabled) {
        donateDialog.activeTab = 'alipay';
      }
    } else {
      throw new Error(donateResult?.msg || '获取捐赠信息失败');
    }

    // 处理授权状态
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

// 关闭捐赠对话框
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

// 清理文件路径ID缓存
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
    console.error('文件路径ID缓存清理失败:', err);
  } finally {
    clearIdPathCacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') {
        message.text = '';
      }
    }, 3000);
  }
};

// 清理增量同步跳过路径缓存
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
    console.error('增量同步跳过路径缓存清理失败:', err);
  } finally {
    clearIncrementSkipCacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') {
        message.text = '';
      }
    }, 3000);
  }
};

// 清理302跳转缓存
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
    console.error('302跳转缓存清理失败:', err);
  } finally {
    clearR302CacheLoading.value = false;
    setTimeout(() => {
      if (message.type === 'success' || message.type === 'error') {
        message.text = '';
      }
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
    if (!Array.isArray(parsedData)) throw new Error("数据必须是一个数组。");
    const isValidStructure = parsedData.every(
      item => typeof item === 'object' && item !== null && 'name' in item && 'id' in item
    );
    if (!isValidStructure) throw new Error("数组中的每个元素都必须是包含 'name' 和 'id' 键的对象。");
    tgChannels.value = parsedData.length > 0 ? parsedData : [{ name: '', id: '' }];
    message.text = '频道配置导入成功！';
    message.type = 'success';
    closeImportDialog();
  } catch (e) {
    importDialog.error = `导入失败: ${e.message}`;
    console.error("频道导入解析失败:", e);
  }
};

const copyCookieToClipboard = async () => {
  if (!config.cookies) { message.text = 'Cookie为空，无法复制。'; message.type = 'warning'; return; }
  try {
    await navigator.clipboard.writeText(config.cookies);
    message.text = 'Cookie已复制到剪贴板！';
    message.type = 'success';
  } catch (err) {
    console.error('复制Cookie失败:', err);
    message.text = '复制Cookie失败。请检查浏览器权限或确保通过HTTPS访问，或尝试手动复制。';
    message.type = 'error';
  }
  setTimeout(() => { if (message.type === 'success' || message.type === 'warning' || message.type === 'error') message.text = ''; }, 3000);
};
const copyAliTokenToClipboard = async () => {
  if (!config.aliyundrive_token) { message.text = 'Token为空，无法复制。'; message.type = 'warning'; return; }
  try {
    await navigator.clipboard.writeText(config.aliyundrive_token);
    message.text = '阿里云盘Token已复制到剪贴板！';
    message.type = 'success';
  } catch (err) {
    console.error('复制Token失败:', err);
    message.text = '复制Token失败。请检查浏览器权限或手动复制。';
    message.type = 'error';
  }
  setTimeout(() => { message.text = ''; }, 3000);
};

// emby2Alist 配置生成相关函数
const openConfigGeneratorDialog = async () => {
  configGeneratorDialog.show = true;
  configGeneratorDialog.configType = configGeneratorDialog.configType || 'emby2alist';
  configGeneratorDialog.mountDir = config.fuse_strm_mount_dir || '/emby/115';
  configGeneratorDialog.moviepilotAddress = config.moviepilot_address || window.location.origin || 'http://localhost:3000';
  configGeneratorDialog.generatedConfig = ''; // 清空之前的配置

  // 从后端 API 获取生成的配置
  await generateConfig();
};

const closeConfigGeneratorDialog = () => {
  configGeneratorDialog.show = false;
};

const generateConfig = async () => {
  try {
    configGeneratorDialog.loading = true;
    const mountDir = configGeneratorDialog.mountDir || '/emby/115';
    const moviepilotAddress = configGeneratorDialog.moviepilotAddress || window.location.origin || 'http://localhost:3000';

    // 从后端 API 获取生成的配置
    const configType = configGeneratorDialog.configType || 'emby2alist';
    const response = await props.api.get(
      `plugin/${PLUGIN_ID}/generate_emby2alist_config?mount_dir=${encodeURIComponent(mountDir)}&moviepilot_address=${encodeURIComponent(moviepilotAddress)}&config_type=${encodeURIComponent(configType)}`
    );

    if (response && response.code === 0 && response.data) {
      configGeneratorDialog.generatedConfig = response.data.generated_config || '';
      // 更新显示的值（如果后端返回了不同的值）
      if (response.data.mount_dir) {
        configGeneratorDialog.mountDir = response.data.mount_dir;
      }
      if (response.data.moviepilot_address) {
        configGeneratorDialog.moviepilotAddress = response.data.moviepilot_address;
      }
      message.text = '配置生成成功！';
      message.type = 'success';
      setTimeout(() => {
        if (message.type === 'success') {
          message.text = '';
        }
      }, 3000);
    } else {
      message.text = response?.msg || '生成配置失败';
      message.type = 'error';
      setTimeout(() => {
        if (message.type === 'error') {
          message.text = '';
        }
      }, 3000);
    }
  } catch (err) {
    console.error('生成配置失败:', err);
    message.text = `生成配置失败: ${err.message || '未知错误'}`;
    message.type = 'error';
    setTimeout(() => {
      if (message.type === 'error') {
        message.text = '';
      }
    }, 3000);
  } finally {
    configGeneratorDialog.loading = false;
  }
};

// 切换配置类型时重新生成，使下方配置框内容与所选类型一致
watch(
  () => configGeneratorDialog.configType,
  (newVal, oldVal) => {
    if (!configGeneratorDialog.show || oldVal === undefined || newVal === oldVal) return;
    generateConfig();
  }
);

const copyGeneratedConfig = async () => {
  try {
    await navigator.clipboard.writeText(configGeneratorDialog.generatedConfig);
    message.text = '配置已复制到剪贴板！';
    message.type = 'success';
    setTimeout(() => {
      if (message.type === 'success') {
        message.text = '';
      }
    }, 3000);
  } catch (err) {
    message.text = '复制失败，请手动复制';
    message.type = 'error';
    setTimeout(() => {
      if (message.type === 'error') {
        message.text = '';
      }
    }, 3000);
  }
};

// 生活事件故障检查
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
      Object.keys(body).length ? body : undefined
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
  // 不重置 startTime，方便用户再次打开时沿用
};

const copyDebugInfo = async () => {
  if (lifeEventCheckDialog.result?.data?.debug_info) {
    try {
      await navigator.clipboard.writeText(lifeEventCheckDialog.result.data.debug_info);
      message.text = '调试信息已复制到剪贴板';
      message.type = 'success';
    } catch (error) {
      message.text = '复制失败，请手动选择文本复制';
      message.type = 'error';
    }
  }
};

onMounted(async () => {
  await loadConfig();
  await checkTransferModuleEnhancement();
});


// 监听基础设置折叠状态变化并保存到 localStorage
watch(basicConfigExpanded, (newVal) => {
  localStorage.setItem('p115strmhelper_basic_config_expanded', JSON.stringify(newVal));
}, { deep: true });

const setMoviePilotAddressToCurrentOrigin = () => {
  if (window && window.location && window.location.origin) {
    config.moviepilot_address = window.location.origin;
    message.text = 'MoviePilot地址已设置为当前站点地址！';
    message.type = 'success';
  } else {
    message.text = '无法获取当前站点地址。';
    message.type = 'error';
  }
  setTimeout(() => {
    if (message.type === 'success' || message.type === 'error') {
      message.text = '';
    }
  }, 3000);
};

provide('config', config);
provide('message', message);
provide('api', props.api);
provide('PLUGIN_ID', PLUGIN_ID);
provide('mediaservers', mediaservers);
provide('embyMediaservers', embyMediaservers);

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
provide('clearIncrementSkipCacheLoading', clearIncrementSkipCacheLoading);
provide('clearR302CacheLoading', clearR302CacheLoading);

// UI states
provide('isTransferModuleEnhancementLocked', isTransferModuleEnhancementLocked);
provide('isCookieVisible', isCookieVisible);
provide('isAliTokenVisible', isAliTokenVisible);

// Actions
provide('triggerFullSync', triggerFullSync);
provide('clearIdPathCache', clearIdPathCache);
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
/* ============================================
   动画关键帧定义
   ============================================ */

/* 卡片入场动画 */
@keyframes cardEnter {
  0% {
    opacity: 0;
    transform: translateY(12px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 列表项交错入场动画 */
@keyframes listItemEnter {
  0% {
    opacity: 0;
    transform: translateX(-10px);
  }

  100% {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 图标弹跳动画 */
@keyframes iconBounce {

  0%,
  100% {
    transform: scale(1);
  }

  50% {
    transform: scale(1.15);
  }
}

/* 标签页滑入动画 */
@keyframes tabSlideIn {
  0% {
    opacity: 0;
    transform: translateY(6px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}


/* 优化基础设置折叠面板动画速度 */
:deep(.v-expansion-panel) {
  transition: margin 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

:deep(.v-expansion-panel-text__wrapper) {
  transition: padding 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

:deep(.v-expansion-panel__shadow) {
  transition: box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

/* 统一字体 - 现代字体栈 */
:deep(.v-card-title),
:deep(.v-card-text),
:deep(.v-list-item-title),
:deep(.v-list-item-subtitle),
:deep(.v-alert),
:deep(.v-btn),
:deep(.text-caption),
:deep(.text-subtitle-1),
:deep(.text-body-1),
:deep(.text-body-2) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 标题字体优化 */
:deep(.v-card-title) {
  font-weight: 700 !important;
  font-size: 1.1rem !important;
  letter-spacing: -0.02em !important;
  line-height: 1.3 !important;
}

:deep(.text-subtitle-1) {
  font-weight: 600 !important;
  font-size: 1rem !important;
  letter-spacing: -0.01em !important;
  line-height: 1.4 !important;
}

:deep(.text-subtitle-2) {
  font-weight: 600 !important;
  font-size: 0.9rem !important;
  letter-spacing: 0 !important;
  line-height: 1.35 !important;
}

/* 正文字体优化 */
:deep(.text-body-1) {
  font-weight: 400 !important;
  font-size: 1rem !important;
  line-height: 1.6 !important;
  letter-spacing: 0 !important;
}

:deep(.text-body-2) {
  font-weight: 400 !important;
  font-size: 0.9rem !important;
  line-height: 1.5 !important;
  letter-spacing: 0 !important;
}

/* 小字字体优化 */
:deep(.text-caption) {
  font-weight: 400 !important;
  font-size: 0.8rem !important;
  line-height: 1.4 !important;
  letter-spacing: 0.01em !important;
}

/* 列表项字体优化 */
:deep(.v-list-item-title) {
  font-weight: 500 !important;
  font-size: 0.9rem !important;
  line-height: 1.4 !important;
}

:deep(.v-list-item-subtitle) {
  font-weight: 400 !important;
  font-size: 0.8rem !important;
  line-height: 1.4 !important;
  letter-spacing: 0.01em !important;
}

/* 按钮字体优化 */
:deep(.v-btn) {
  font-weight: 500 !important;
  font-size: 0.875rem !important;
  letter-spacing: 0.02em !important;
  text-transform: none !important;
}

/* 标签字体优化 */
:deep(.v-tab) {
  font-weight: 500 !important;
  font-size: 0.875rem !important;
  letter-spacing: 0.01em !important;
}

/* 输入框字体优化 */
:deep(.v-field__input) {
  font-weight: 400 !important;
  font-size: 0.9rem !important;
  letter-spacing: 0 !important;
}

:deep(.v-label) {
  font-weight: 500 !important;
  font-size: 0.85rem !important;
  letter-spacing: 0.01em !important;
}

/* 警告/提示字体优化 */
:deep(.v-alert) {
  font-weight: 400 !important;
  font-size: 0.85rem !important;
  line-height: 1.5 !important;
}

/* 卡片入场动画 */
.plugin-config :deep(.v-card) {
  animation: cardEnter 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

/* 配置卡片悬停动画优化 */
.config-card {
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.35s cubic-bezier(0.22, 1, 0.36, 1) !important;
}

.config-card:hover {
  transform: translateY(-3px);
  box-shadow:
    0 12px 28px rgba(91, 207, 250, 0.25),
    0 4px 12px rgba(245, 171, 185, 0.18),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
}

/* 按钮动画优化 */
:deep(.v-btn) {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.25s cubic-bezier(0.22, 1, 0.36, 1), background-color 0.2s ease !important;
}

:deep(.v-btn:hover) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(91, 207, 250, 0.25) !important;
}

:deep(.v-btn:active) {
  transform: scale(0.97);
  transition: transform 0.1s ease !important;
}

/* 图标动画优化 */
:deep(.v-icon) {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), color 0.2s ease !important;
}

:deep(.v-btn:hover .v-icon) {
  transform: scale(1.1);
}

:deep(.v-tab:hover .v-icon) {
  animation: iconBounce 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}

/* 标签页动画优化 */
.main-category-tabs {
  animation: tabSlideIn 0.4s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

:deep(.main-category-tabs .v-tab) {
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1), background 0.25s ease, color 0.25s ease, box-shadow 0.3s ease !important;
}

:deep(.main-category-tabs .v-tab:hover) {
  transform: translateY(-2px);
}

/* 子标签页动画 */
:deep(.sub-category-tabs .v-tab) {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), background 0.2s ease, color 0.2s ease !important;
}

:deep(.sub-category-tabs .v-tab:hover) {
  transform: translateY(-1px);
}

/* v-window 标签页内容切换动画 */
.tab-window :deep(.v-window__container) {
  transition: none !important;
}

.tab-window :deep(.v-window-item--active) {
  animation: tabContentEnter 0.3s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

@keyframes tabContentEnter {
  0% {
    opacity: 0;
    transform: translateY(8px);
  }

  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 输入框动画优化 */
:deep(.v-field) {
  transition: box-shadow 0.25s ease, border-color 0.25s ease !important;
}

/* 开关动画优化 */
:deep(.v-switch__track) {
  transition: background-color 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

:deep(.v-switch__thumb) {
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
}

/* 列表项动画优化 */
:deep(.v-list-item) {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), background 0.2s ease !important;
}

:deep(.v-list-item:hover) {
  transform: translateX(3px);
}

/* 芯片动画优化 */
:deep(.v-chip) {
  transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.2s ease !important;
}

:deep(.v-chip:hover) {
  transform: scale(1.05) translateY(-1px);
  box-shadow: 0 3px 8px rgba(91, 207, 250, 0.2) !important;
}

/* 对话框动画优化 */
:deep(.v-dialog .v-overlay__content) {
  animation: cardEnter 0.35s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

/* 警告框动画优化 */
:deep(.v-alert) {
  transition: opacity 0.3s ease, transform 0.3s ease !important;
}

/* alert-fade 过渡动画 */
.alert-fade-enter-active {
  transition: opacity 0.3s cubic-bezier(0.22, 1, 0.36, 1), transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.alert-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.alert-fade-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.98);
}

.alert-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}

/* content-fade 加载过渡动画 */
.content-fade-enter-active {
  transition: opacity 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

.content-fade-leave-active {
  transition: opacity 0.15s ease;
}

.content-fade-enter-from,
.content-fade-leave-to {
  opacity: 0;
}

/* 展开面板动画优化 */
:deep(.v-expansion-panel-title) {
  transition: background 0.25s ease !important;
}

:deep(.v-expansion-panel-title:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.1) 0%,
      rgba(245, 171, 185, 0.08) 100%) !important;
}

/* 路径组动画优化 */
.path-group {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.25s ease !important;
}

.path-group:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(91, 207, 250, 0.12) !important;
}

/* 进度条动画优化 */
:deep(.v-progress-linear__determinate) {
  transition: width 0.4s cubic-bezier(0.22, 1, 0.36, 1) !important;
}

/* 选择器动画优化 */
:deep(.v-select__selection) {
  transition: opacity 0.2s ease !important;
}

/* 菜单动画优化 */
:deep(.v-menu .v-overlay__content) {
  animation: cardEnter 0.25s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

/* 滚动条动画优化 */
:deep(::-webkit-scrollbar-thumb) {
  transition: background 0.3s ease !important;
}

:deep(::-webkit-scrollbar-thumb:hover) {
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.9), rgba(245, 171, 185, 0.9)) !important;
}

:deep(.v-expansion-panel-text__wrapper) {
  transition: padding 0.2s ease !important;
}

:deep(.v-expansion-panel__shadow) {
  transition: box-shadow 0.2s ease !important;
}

/* 无障碍：尊重用户减少动画偏好 */
@media (prefers-reduced-motion: reduce) {

  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

/* 统一字体 - Inspired by Page.vue */
:deep(.v-card-title),
:deep(.v-card-text),
:deep(.v-list-item-title),
:deep(.v-list-item-subtitle),
:deep(.v-alert),
:deep(.v-btn),
:deep(.text-caption),
:deep(.text-subtitle-1),
:deep(.text-body-1),
:deep(.text-body-2) {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif !important;
}

/* 文字大小 - Unified with Page.vue */
:deep(.text-caption) {
  font-size: 0.8rem !important;
}

:deep(.text-body-2) {
  font-size: 0.85rem !important;
}

:deep(.text-subtitle-2) {
  /* Added for consistency with Page.vue inner card titles */
  font-size: 0.875rem !important;
  font-weight: 500 !important;
  line-height: 1.25rem !important;
}

:deep(.v-list-item-title) {
  font-size: 0.85rem !important;
  /* Unified with Page.vue's common list item title size */
}

:deep(.v-list-item-subtitle) {
  font-size: 0.8rem !important;
  /* Unified with Page.vue's common list item subtitle size */
}

/* ============================================
   配置界面样式 - 镜面效果 + 蓝粉白配色
   ============================================ */

/* 主容器 */
.plugin-config {
  padding: 12px;
  width: 100%;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
}

.plugin-config :deep(.v-card) {
  border-radius: 20px !important;
  overflow: hidden;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  /* 镜面效果 - 动态适配主题 */
  background: rgba(var(--v-theme-surface), 0.7) !important;
  backdrop-filter: blur(20px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
  box-shadow:
    0 8px 32px rgba(91, 207, 250, 0.25),
    0 2px 8px rgba(245, 171, 185, 0.2),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  transition: box-shadow 0.35s ease, border-color 0.25s ease !important;
}

/* 主卡片高度设置：桌面用 vh，移动端填满父级由内部滚动 */
.config-main-card {
  max-height: 85vh;
}

@media (max-width: 768px) {
  .config-main-card {
    flex: 1;
    min-height: 0;
    max-height: none;
    height: 100%;
  }
}

/* 暗色模式下的主卡片 */
:deep(.v-theme--dark) .plugin-config .v-card,
:deep([data-theme="dark"]) .plugin-config .v-card {
  background: rgba(var(--v-theme-surface), 0.75) !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  box-shadow:
    0 8px 32px rgba(91, 207, 250, 0.3),
    0 2px 8px rgba(245, 171, 185, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

.config-card {
  border-radius: 16px !important;
  /* 镜面效果 - 动态适配主题 */
  background: rgba(var(--v-theme-surface), 0.65) !important;
  backdrop-filter: blur(15px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(15px) saturate(180%) !important;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  overflow: hidden;
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.35s ease, border-color 0.25s ease, background 0.25s ease !important;
  margin-bottom: 16px !important;
  box-shadow:
    0 4px 16px rgba(91, 207, 250, 0.2),
    0 1px 4px rgba(245, 171, 185, 0.15),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
}

/* 暗色模式下的配置卡片 */
:deep(.v-theme--dark) .config-card,
:deep([data-theme="dark"]) .config-card {
  background: rgba(var(--v-theme-surface), 0.7) !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  box-shadow:
    0 4px 16px rgba(91, 207, 250, 0.25),
    0 1px 4px rgba(245, 171, 185, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

.config-card:hover {
  transform: translateY(-4px) scale(1.01);
  box-shadow:
    0 12px 32px rgba(91, 207, 250, 0.3),
    0 4px 12px rgba(245, 171, 185, 0.25),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
  border-color: rgba(91, 207, 250, 0.5) !important;
  background: rgba(var(--v-theme-surface), 0.75) !important;
}

/* 暗色模式下的配置卡片悬停状态 */
:deep(.v-theme--dark) .config-card:hover,
:deep([data-theme="dark"]) .config-card:hover {
  background: rgba(var(--v-theme-surface), 0.8) !important;
  border-color: rgba(91, 207, 250, 0.6) !important;
  box-shadow:
    0 12px 32px rgba(91, 207, 250, 0.4),
    0 4px 12px rgba(245, 171, 185, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
}

/* ============================================
   主分类标签样式优化
   ============================================ */
.main-category-tabs {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.08) 0%,
      rgba(245, 171, 185, 0.06) 50%,
      rgba(255, 184, 201, 0.04) 100%) !important;
  border-radius: 16px 16px 0 0 !important;
  padding: 4px 8px !important;
  display: flex;
  align-items: center;
}

:deep(.main-category-tabs .v-tab) {
  border-radius: 12px !important;
  margin: 4px 2px !important;
  padding: 10px 20px !important;
  font-size: 0.875rem !important;
  font-weight: 500 !important;
  text-transform: none !important;
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1), background 0.25s ease, color 0.25s ease, box-shadow 0.3s ease !important;
  min-height: 44px !important;
  color: rgba(var(--v-theme-on-surface), 0.7) !important;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.main-category-tabs .v-tab:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.15) 0%,
      rgba(245, 171, 185, 0.12) 100%) !important;
  color: rgba(var(--v-theme-primary), 0.95) !important;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(91, 207, 250, 0.2),
    0 1px 3px rgba(245, 171, 185, 0.15) !important;
}

:deep(.main-category-tabs .v-tab--selected) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 100%) !important;
  color: rgb(var(--v-theme-primary)) !important;
  font-weight: 600 !important;
  box-shadow: 0 3px 12px rgba(91, 207, 250, 0.35),
    0 2px 6px rgba(245, 171, 185, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
  position: relative;
  backdrop-filter: blur(12px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(12px) saturate(180%) !important;
}

/* 隐藏Vuetify默认滑块 */
:deep(.main-category-tabs .v-tab__slider) {
  display: none !important;
}


:deep(.main-category-tabs .v-tab .v-icon) {
  margin-right: 8px;
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), color 0.2s ease;
  color: rgba(var(--v-theme-on-surface), 0.6);
}

:deep(.main-category-tabs .v-tab:hover .v-icon) {
  color: rgba(var(--v-theme-primary), 0.8);
  transform: scale(1.05);
}

:deep(.main-category-tabs .v-tab--selected .v-icon) {
  transform: scale(1.15);
  color: rgb(var(--v-theme-primary));
}

:deep(.main-category-tabs .v-slider) {
  display: none !important;
}

/* ============================================
   子标签页样式优化
   ============================================ */
.sub-category-tabs {
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  padding: 8px 12px !important;
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.05) 0%,
      rgba(245, 171, 185, 0.03) 50%,
      rgba(255, 184, 201, 0.02) 100%) !important;
  border-radius: 0 !important;
  display: flex;
  align-items: center;
  backdrop-filter: blur(8px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(8px) saturate(180%) !important;
}

:deep(.sub-category-tabs .v-tab) {
  min-width: auto !important;
  padding: 10px 18px !important;
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 0.875rem !important;
  line-height: 1.5 !important;
  border-radius: 10px 10px 0 0 !important;
  margin: 0 4px !important;
  text-transform: none !important;
  font-weight: 500 !important;
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), background 0.2s ease, color 0.2s ease, box-shadow 0.25s ease !important;
  color: rgba(var(--v-theme-on-surface), 0.65) !important;
  position: relative;
  overflow: visible !important;
  display: flex;
  align-items: center;
  justify-content: center;
}


:deep(.sub-category-tabs .v-tab:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.12) 0%,
      rgba(245, 171, 185, 0.1) 100%) !important;
  color: rgba(var(--v-theme-primary), 0.9) !important;
  transform: translateY(-1px);
}

:deep(.sub-category-tabs .v-tab--selected) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.15) 0%,
      rgba(245, 171, 185, 0.12) 100%) !important;
  color: rgb(var(--v-theme-primary)) !important;
  font-weight: 600 !important;
  box-shadow: 0 -2px 12px rgba(91, 207, 250, 0.2),
    0 -1px 4px rgba(245, 171, 185, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
  position: relative;
  backdrop-filter: blur(10px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(10px) saturate(180%) !important;
}

/* 隐藏Vuetify默认滑块 */
:deep(.sub-category-tabs .v-tab__slider) {
  display: none !important;
}


:deep(.sub-category-tabs .v-tab .v-icon) {
  margin-right: 6px;
  flex-shrink: 0;
  transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), color 0.2s ease;
  color: rgba(var(--v-theme-on-surface), 0.55);
}

:deep(.sub-category-tabs .v-tab:hover .v-icon) {
  color: rgba(var(--v-theme-primary), 0.75);
  transform: scale(1.05);
}

:deep(.sub-category-tabs .v-tab--selected .v-icon) {
  transform: scale(1.12);
  color: rgb(var(--v-theme-primary));
}

:deep(.sub-category-tabs .v-tab__content) {
  display: flex;
  align-items: center;
  white-space: nowrap;
}

:deep(.sub-category-tabs .v-slider) {
  display: none !important;
}

/* 确保子标签页容器有足够空间 */
:deep(.v-window-item[value^="category-"] .v-card-text) {
  min-height: 0;
}

/* 优化分隔线样式 - 符合主题色 */
:deep(.config-card .v-divider) {
  border-color: rgba(91, 207, 250, 0.2) !important;
  background: linear-gradient(90deg,
      transparent 0%,
      rgba(91, 207, 250, 0.3) 20%,
      rgba(245, 171, 185, 0.3) 80%,
      transparent 100%) !important;
  height: 2px !important;
  opacity: 1 !important;
}

:deep(.v-theme--dark) .config-card .v-divider,
:deep([data-theme="dark"]) .config-card .v-divider {
  border-color: rgba(91, 207, 250, 0.3) !important;
  background: linear-gradient(90deg,
      transparent 0%,
      rgba(91, 207, 250, 0.4) 20%,
      rgba(245, 171, 185, 0.4) 80%,
      transparent 100%) !important;
}

/* 暗色模式下的标签页优化 */
:deep(.v-theme--dark) .main-category-tabs,
:deep([data-theme="dark"]) .main-category-tabs {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.12) 0%,
      rgba(245, 171, 185, 0.1) 50%,
      rgba(255, 184, 201, 0.08) 100%) !important;
}

:deep(.v-theme--dark) .sub-category-tabs,
:deep([data-theme="dark"]) .sub-category-tabs {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.08) 0%,
      rgba(245, 171, 185, 0.06) 50%,
      rgba(255, 184, 201, 0.04) 100%) !important;
}

:deep(.v-theme--dark) .sub-category-tabs .v-tab--selected,
:deep([data-theme="dark"]) .sub-category-tabs .v-tab--selected {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2) 0%,
      rgba(245, 171, 185, 0.15) 100%) !important;
  box-shadow: 0 -2px 12px rgba(91, 207, 250, 0.25),
    0 -1px 4px rgba(245, 171, 185, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
}



.bg-primary-gradient,
.bg-primary-lighten-5 {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 50%,
      rgba(255, 184, 201, 0.15) 100%) !important;
  backdrop-filter: blur(20px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  box-shadow: inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
}

/* 暗色模式下的标题区域 */
:deep(.v-theme--dark) .bg-primary-gradient,
:deep(.v-theme--dark) .bg-primary-lighten-5,
:deep([data-theme="dark"]) .bg-primary-gradient,
:deep([data-theme="dark"]) .bg-primary-lighten-5 {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.3) 0%,
      rgba(245, 171, 185, 0.25) 50%,
      rgba(255, 184, 201, 0.2) 100%) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.15) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

.plugin-config :deep(.v-card-title) {
  border-radius: 12px 12px 0 0;
}

.config-title {
  font-weight: 500;
  color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity));
}

/* 路径输入框组 - 镜面效果，动态适配主题 */
.path-group {
  padding: 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  border-radius: 12px;
  background: rgba(var(--v-theme-surface), 0.5) !important;
  backdrop-filter: blur(10px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(10px) saturate(180%) !important;
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.15),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
}

.path-group:hover {
  border-color: rgba(91, 207, 250, 0.4) !important;
  background: rgba(var(--v-theme-surface), 0.65) !important;
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.2),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
}

/* 暗色模式下的路径输入框组 */
:deep(.v-theme--dark) .path-group,
:deep([data-theme="dark"]) .path-group {
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  background: rgba(var(--v-theme-surface), 0.6) !important;
}

:deep(.v-theme--dark) .path-group:hover,
:deep([data-theme="dark"]) .path-group:hover {
  background: rgba(var(--v-theme-surface), 0.7) !important;
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

.path-input-row {
  display: flex;
  align-items: center;
}

.path-input-field {
  flex-grow: 1;
}

.path-input-action {
  margin-left: 8px;
}

.v-list-item-title.text-danger {
  color: rgb(var(--v-theme-error)) !important;
  font-weight: bold;
}

/* Cookie 输入框样式 */
:deep(.v-textarea .v-field__input) {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace;
  font-size: 0.8rem;
  line-height: 1.4;
}

/* Tab 样式调整 - 蓝粉配色 */
:deep(.v-tabs) {
  border-bottom: 2px solid rgba(91, 207, 250, 0.4) !important;
  border-radius: 12px 12px 0 0;
  background: rgba(var(--v-theme-surface), 0.3) !important;
  backdrop-filter: blur(10px) !important;
}

/* 暗色模式下的 Tab 背景 */
:deep(.v-theme--dark) .v-tabs,
:deep([data-theme="dark"]) .v-tabs {
  background: rgba(var(--v-theme-surface), 0.4) !important;
  border-bottom-color: rgba(91, 207, 250, 0.5) !important;
}

/* Tab 容器 - 确保没有白色背景，动态适配主题 */
:deep(.v-tabs .v-tabs-bar),
:deep(.v-tabs .v-tabs-bar__content),
:deep(.v-tabs .v-tabs-bar__wrapper) {
  background: transparent !important;
}

/* Tab 项背景 - 确保未选中状态在暗色模式下有合适的背景 */
:deep(.v-tab) {
  background: transparent !important;
}

/* 暗色模式下的未选中 Tab */
:deep(.v-theme--dark) .v-tab:not(.v-tab--selected),
:deep([data-theme="dark"]) .v-tab:not(.v-tab--selected) {
  background: rgba(var(--v-theme-surface), 0.15) !important;
  backdrop-filter: blur(5px) !important;
}

/* Tab 切换动画时的中间状态 */
:deep(.v-tab--transitioning),
:deep(.v-tab[aria-selected="true"]) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.3) 0%,
      rgba(245, 171, 185, 0.25) 100%) !important;
}

/* 暗色模式下的 Tab 切换动画 */
:deep(.v-theme--dark) .v-tab--transitioning,
:deep(.v-theme--dark) .v-tab[aria-selected="true"],
:deep([data-theme="dark"]) .v-tab--transitioning,
:deep([data-theme="dark"]) .v-tab[aria-selected="true"] {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.4) 0%,
      rgba(245, 171, 185, 0.35) 100%) !important;
}

:deep(.v-tab) {
  font-weight: 500;
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), background 0.2s ease, color 0.2s ease, box-shadow 0.25s ease !important;
  border-radius: 12px 12px 0 0 !important;
  margin: 0 2px;
  color: rgba(var(--v-theme-on-surface), 0.7) !important;
}

/* 暗色模式下的 Tab 文字颜色 */
:deep(.v-theme--dark) .v-tab,
:deep([data-theme="dark"]) .v-tab {
  color: rgba(255, 255, 255, 0.7) !important;
}

:deep(.v-tab:hover) {
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.2), rgba(245, 171, 185, 0.15)) !important;
  color: #5bcffa !important;
}

/* 暗色模式下的 Tab 悬停状态 */
:deep(.v-theme--dark) .v-tab:hover,
:deep([data-theme="dark"]) .v-tab:hover {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 100%) !important;
  color: #5bcffa !important;
}

/* Tab 未选中状态 - 确保在暗色模式下有合适的背景 */
:deep(.v-theme--dark) .v-tab:not(.v-tab--selected),
:deep([data-theme="dark"]) .v-tab:not(.v-tab--selected) {
  background: rgba(var(--v-theme-surface), 0.2) !important;
  backdrop-filter: blur(5px) !important;
}

:deep(.v-theme--dark) .v-tab:not(.v-tab--selected):hover,
:deep([data-theme="dark"]) .v-tab:not(.v-tab--selected):hover {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2) 0%,
      rgba(245, 171, 185, 0.15) 100%) !important;
}

:deep(.v-tab--selected) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.3) 0%,
      rgba(245, 171, 185, 0.25) 100%) !important;
  color: #5bcffa !important;
  border-radius: 12px 12px 0 0 !important;
  font-weight: 600 !important;
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.3),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
  backdrop-filter: blur(10px) !important;
}

/* 暗色模式下的选中 Tab - 使用深色背景而不是白色 */
:deep(.v-theme--dark) .v-tab--selected,
:deep([data-theme="dark"]) .v-tab--selected {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 100%) !important;
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
  color: #5bcffa !important;
  backdrop-filter: blur(10px) !important;
}

/* Tab 滑动指示器 - 动态适配主题（覆盖所有可能的类名） */
:deep(.v-tabs-slider),
:deep(.v-tabs-slider-wrapper),
:deep(.v-tabs .v-slider),
:deep(.v-tabs .v-slider__track),
:deep(.v-tabs .v-slider__thumb),
:deep(.v-tabs .v-tabs-bar__slider) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.8) 0%,
      rgba(245, 171, 185, 0.7) 100%) !important;
  border: none !important;
  box-shadow: none !important;
}

/* 暗色模式下的滑动指示器 */
:deep(.v-theme--dark) .v-tabs-slider,
:deep(.v-theme--dark) .v-tabs-slider-wrapper,
:deep(.v-theme--dark) .v-tabs .v-slider,
:deep(.v-theme--dark) .v-tabs .v-slider__track,
:deep(.v-theme--dark) .v-tabs .v-slider__thumb,
:deep(.v-theme--dark) .v-tabs .v-tabs-bar__slider,
:deep([data-theme="dark"]) .v-tabs-slider,
:deep([data-theme="dark"]) .v-tabs-slider-wrapper,
:deep([data-theme="dark"]) .v-tabs .v-slider,
:deep([data-theme="dark"]) .v-tabs .v-slider__track,
:deep([data-theme="dark"]) .v-tabs .v-slider__thumb,
:deep([data-theme="dark"]) .v-tabs .v-tabs-bar__slider {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.9) 0%,
      rgba(245, 171, 185, 0.8) 100%) !important;
  box-shadow:
    0 0 8px rgba(91, 207, 250, 0.5),
    0 0 4px rgba(245, 171, 185, 0.4) !important;
}

/* Tab 背景色 - 动态适配主题 */
:deep(.v-tabs) {
  background: rgba(var(--v-theme-surface), 0.3) !important;
}

/* 暗色模式下的 Tab 背景 */
:deep(.v-theme--dark) .v-tabs,
:deep([data-theme="dark"]) .v-tabs {
  background: rgba(var(--v-theme-surface), 0.4) !important;
}

/* Switch 样式调整 - 动态适配主题 */
:deep(.v-switch .v-selection-control__input > .v-icon) {
  color: rgba(var(--v-theme-medium-emphasis));
  transition: color 0.25s ease !important;
}

:deep(.v-switch .v-track) {
  background-color: rgba(var(--v-theme-medium-emphasis), 0.3) !important;
  border-radius: 12px !important;
  opacity: 1 !important;
  transition: background-color 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

/* 暗色模式下的开关轨道 */
:deep(.v-theme--dark) .v-switch .v-track,
:deep([data-theme="dark"]) .v-switch .v-track {
  background-color: rgba(255, 255, 255, 0.2) !important;
}

/* 开关启用状态 - 动态适配主题 */
:deep(.v-switch .v-selection-control--dirty .v-track) {
  background-color: rgb(var(--v-theme-primary)) !important;
}

/* 暗色模式下的开关启用状态 */
:deep(.v-theme--dark) .v-switch .v-selection-control--dirty .v-track,
:deep([data-theme="dark"]) .v-switch .v-selection-control--dirty .v-track {
  background-color: #5bcffa !important;
  box-shadow: 0 0 8px rgba(91, 207, 250, 0.4) !important;
}

/* 调整字体大小 */
:deep(.v-card-text .v-label) {
  font-size: 0.9rem;
  /* 调整标签字体大小 */
}

:deep(.v-card-text .v-input__details) {
  font-size: 0.8rem !important;
  /* Ensure input hints also match .text-caption */
}

:deep(.v-text-field input),
:deep(.v-textarea textarea) {
  font-size: 0.875rem !important;
}

/* 优化输入框样式 - 镜面效果，动态适配主题 */
:deep(.v-field) {
  border-radius: 12px !important;
  background: rgba(var(--v-theme-surface), 0.6) !important;
  backdrop-filter: blur(8px) !important;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  transition: box-shadow 0.25s ease, border-color 0.25s ease, background 0.25s ease !important;
  box-shadow:
    0 2px 4px rgba(91, 207, 250, 0.15),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
}

/* 暗色模式下的输入框 */
:deep(.v-theme--dark) .v-field,
:deep([data-theme="dark"]) .v-field {
  background: rgba(var(--v-theme-surface), 0.7) !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  box-shadow:
    0 2px 4px rgba(91, 207, 250, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
}

:deep(.v-field--focused) {
  box-shadow:
    0 0 0 3px rgba(91, 207, 250, 0.3),
    0 4px 12px rgba(245, 171, 185, 0.25),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
  border-color: rgba(91, 207, 250, 0.6) !important;
  background: rgba(var(--v-theme-surface), 0.75) !important;
}

/* 暗色模式下的输入框聚焦状态 */
:deep(.v-theme--dark) .v-field--focused,
:deep([data-theme="dark"]) .v-field--focused {
  background: rgba(var(--v-theme-surface), 0.8) !important;
  box-shadow:
    0 0 0 3px rgba(91, 207, 250, 0.4),
    0 4px 12px rgba(245, 171, 185, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
  border-color: rgba(91, 207, 250, 0.7) !important;
}

:deep(.v-select .v-field),
:deep(.v-text-field .v-field),
:deep(.v-textarea .v-field) {
  border-radius: 12px !important;
}

/* 输入框内部元素 - 确保没有白色背景 */
:deep(.v-field__input),
:deep(.v-field__control),
:deep(.v-input__control) {
  background: transparent !important;
}

/* 暗色模式下的输入框内部 */
:deep(.v-theme--dark) .v-field__input,
:deep(.v-theme--dark) .v-field__control,
:deep(.v-theme--dark) .v-input__control,
:deep([data-theme="dark"]) .v-field__input,
:deep([data-theme="dark"]) .v-field__control,
:deep([data-theme="dark"]) .v-input__control {
  background: transparent !important;
  color: rgba(255, 255, 255, 0.87) !important;
}

/* 优化按钮样式 - 镜面效果 */
:deep(.v-btn) {
  border-radius: 12px !important;
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.25s ease, background-color 0.2s ease !important;
  font-weight: 500 !important;
  text-transform: none !important;
  backdrop-filter: blur(10px) !important;
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.2),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
}

:deep(.v-btn:hover) {
  transform: translateY(-2px) scale(1.02);
  box-shadow:
    0 6px 16px rgba(91, 207, 250, 0.35),
    0 2px 8px rgba(245, 171, 185, 0.3),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.1) !important;
}

:deep(.v-btn--variant-elevated),
:deep(.v-btn--variant-flat) {
  background: rgba(var(--v-theme-surface), 0.7) !important;
  backdrop-filter: blur(10px) !important;
}

/* 暗色模式下的按钮 */
:deep(.v-theme--dark) .v-btn--variant-elevated,
:deep(.v-theme--dark) .v-btn--variant-flat,
:deep([data-theme="dark"]) .v-btn--variant-elevated,
:deep([data-theme="dark"]) .v-btn--variant-flat {
  background: rgba(var(--v-theme-surface), 0.8) !important;
}

/* 优化警告框样式 - 镜面效果，动态适配主题 */
:deep(.v-alert) {
  border-radius: 16px !important;
  border-left-width: 4px !important;
  background: rgba(var(--v-theme-surface), 0.7) !important;
  backdrop-filter: blur(15px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(15px) saturate(180%) !important;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.2),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
  transition: opacity 0.3s ease, transform 0.3s ease !important;
}

/* 暗色模式下的警告框 */
:deep(.v-theme--dark) .v-alert,
:deep([data-theme="dark"]) .v-alert {
  background: rgba(var(--v-theme-surface), 0.8) !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

/* 优化列表项样式 - 镜面效果 */
:deep(.v-list-item) {
  border-radius: 10px;
  margin: 2px 4px;
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1), background 0.2s ease, box-shadow 0.25s ease !important;
  background: rgba(255, 255, 255, 0.3) !important;
  backdrop-filter: blur(5px) !important;
}

:deep(.v-list-item:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2) 0%,
      rgba(245, 171, 185, 0.15) 100%) !important;
  backdrop-filter: blur(10px) !important;
  transform: translateX(4px);
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.25),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.08) !important;
}

/* Reduce vertical padding for columns within rows */
:deep(.v-row > .v-col) {
  padding-top: 4px !important;
  padding-bottom: 4px !important;
}

/* Tab 颜色已在上方更新，移除重复样式 */

/* Colorful Switches */
:deep(.v-switch .v-selection-control--dirty .v-track) {
  opacity: 0.8 !important;
  /* Ensure high opacity for color visibility */
}

:deep(.v-switch .v-selection-control--dirty .v-selection-control__input > .v-icon) {
  color: white !important;
}

/* Primary Color Switch - 动态适配主题 */
:deep(.v-switch[color="primary"] .v-selection-control--dirty .v-track),
:deep(.v-switch[color="primary"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-primary)) !important;
  border-color: rgb(var(--v-theme-primary)) !important;
}

/* 暗色模式下的 Primary Switch */
:deep(.v-theme--dark .v-switch[color="primary"] .v-selection-control--dirty .v-track),
:deep(.v-theme--dark .v-switch[color="primary"] .v-selection-control--dirty .v-switch__track),
:deep([data-theme="dark"] .v-switch[color="primary"] .v-selection-control--dirty .v-track),
:deep([data-theme="dark"] .v-switch[color="primary"] .v-selection-control--dirty .v-switch__track) {
  background-color: #5bcffa !important;
  border-color: #5bcffa !important;
  box-shadow: 0 0 8px rgba(91, 207, 250, 0.4) !important;
}

/* Success Color Switch - 动态适配主题 */
:deep(.v-switch[color="success"] .v-selection-control--dirty .v-track),
:deep(.v-switch[color="success"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-success)) !important;
  border-color: rgb(var(--v-theme-success)) !important;
}

/* 暗色模式下的 Success Switch */
:deep(.v-theme--dark .v-switch[color="success"] .v-selection-control--dirty .v-track),
:deep(.v-theme--dark .v-switch[color="success"] .v-selection-control--dirty .v-switch__track),
:deep([data-theme="dark"] .v-switch[color="success"] .v-selection-control--dirty .v-track),
:deep([data-theme="dark"] .v-switch[color="success"] .v-selection-control--dirty .v-switch__track) {
  box-shadow: 0 0 8px rgba(76, 175, 80, 0.4) !important;
}

/* Info Color Switch */
:deep(.v-switch[color="info"] .v-selection-control--dirty .v-track),
:deep(.v-switch[color="info"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-info)) !important;
  border-color: rgb(var(--v-theme-info)) !important;
}

/* Warning Color Switch */
:deep(.v-switch[color="warning"] .v-selection-control--dirty .v-track),
:deep(.v-switch[color="warning"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-warning)) !important;
  border-color: rgb(var(--v-theme-warning)) !important;
}

/* Error Color Switch */
:deep(.v-switch[color="error"] .v-selection-control--dirty .v-track),
:deep(.v-switch[color="error"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-error)) !important;
  border-color: rgb(var(--v-theme-error)) !important;
}

/* 缓存卡片响应式样式 */
.cache-card {
  min-height: 200px;
}

/* 移动端优化 - 保持镜面效果 */
@media (max-width: 959px) {
  .plugin-config {
    padding: 8px;
    width: 100%;
    max-width: 100vw;
    box-sizing: border-box;
  }

  /* 移动端减小圆角但保持镜面效果 */
  .plugin-config :deep(.v-card) {
    border-radius: 16px !important;
    backdrop-filter: blur(15px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(15px) saturate(180%) !important;
  }

  .config-card {
    border-radius: 14px !important;
    margin-bottom: 12px !important;
    backdrop-filter: blur(12px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(12px) saturate(180%) !important;
  }

  .plugin-config :deep(.v-card-title) {
    border-radius: 10px 10px 0 0;
    padding: 12px !important;
  }

  /* 优化触摸目标大小 */
  :deep(.v-btn) {
    min-height: 44px !important;
    min-width: 44px !important;
    padding: 8px 16px !important;
    font-size: 0.875rem !important;
  }

  :deep(.v-btn--icon) {
    min-width: 44px !important;
    min-height: 44px !important;
  }

  /* 优化输入框触摸区域 */
  :deep(.v-field) {
    border-radius: 8px !important;
    min-height: 48px !important;
  }

  :deep(.v-text-field .v-field),
  :deep(.v-select .v-field),
  :deep(.v-textarea .v-field) {
    min-height: 48px !important;
  }

  /* 优化开关触摸区域 */
  :deep(.v-switch) {
    min-height: 44px !important;
    padding: 8px 0 !important;
  }

  /* 优化列表项触摸区域 */
  :deep(.v-list-item) {
    min-height: 48px !important;
    padding: 8px 12px !important;
  }

  /* 优化Tab在移动端 */
  :deep(.v-tab) {
    min-height: 44px !important;
    padding: 0 16px !important;
    font-size: 0.875rem !important;
  }

  /* 主分类标签在移动端优化 */
  :deep(.main-category-tabs .v-tab) {
    min-height: 44px !important;
    padding: 8px 12px !important;
    font-size: 0.8rem !important;
    margin: 2px 1px !important;
  }

  /* 子标签页在移动端优化 */
  :deep(.sub-category-tabs .v-tab) {
    min-height: 44px !important;
    padding: 8px 14px !important;
    font-size: 0.8rem !important;
    margin: 0 3px !important;
  }

  :deep(.sub-category-tabs) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding: 6px 8px 0 8px !important;
  }

  /* 禁用 v-window 的触摸滑动 */
  :deep(.v-window) {
    touch-action: pan-y !important;
  }

  :deep(.v-window__container) {
    touch-action: pan-y !important;
  }

  /* 配置项区域禁用触摸滑动 */
  :deep(.v-card-text),
  :deep(.v-row),
  :deep(.v-col),
  :deep(.v-field),
  :deep(.v-switch),
  :deep(.v-btn),
  :deep(.v-select),
  :deep(.v-text-field),
  :deep(.v-textarea) {
    touch-action: manipulation !important;
  }

  /* 优化对话框在移动端 - 镜面效果 */
  :deep(.v-dialog > .v-card) {
    margin: 16px !important;
    max-height: calc(100vh - 32px) !important;
    border-radius: 20px !important;
    background: rgba(255, 255, 255, 0.85) !important;
    backdrop-filter: blur(25px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(25px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.4) !important;
    box-shadow:
      0 12px 48px rgba(91, 207, 250, 0.3),
      0 4px 16px rgba(245, 171, 185, 0.25),
      inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.1) !important;
  }

  :deep(.v-dialog) {
    max-width: calc(100vw - 32px) !important;
  }

  /* 路径输入组优化 */
  .path-group {
    padding: 10px !important;
    border-radius: 8px !important;
  }

  /* 优化警告框 */
  :deep(.v-alert) {
    border-radius: 10px !important;
    padding: 12px !important;
  }

  /* 优化卡片间距 */
  :deep(.v-card-text) {
    padding: 12px !important;
  }

  /* 优化芯片 */
  :deep(.v-chip) {
    font-size: 0.75rem !important;
    height: 28px !important;
    padding: 0 10px !important;
    min-height: 28px !important;
  }

  /* 优化图标大小 */
  :deep(.v-icon) {
    font-size: 20px !important;
  }

  :deep(.v-icon--size-small) {
    font-size: 18px !important;
  }

  /* 优化行和列的间距 */
  :deep(.v-row) {
    margin: -4px !important;
  }

  :deep(.v-row > .v-col) {
    padding: 6px !important;
  }

  .cache-card {
    min-height: auto;
    height: auto;
  }
}

/* 移动端小屏幕优化 (max-width: 600px) */
@media (max-width: 600px) {
  .plugin-config {
    padding: 6px;
    width: 100%;
    max-width: 100vw;
    box-sizing: border-box;
  }

  .plugin-config :deep(.v-card) {
    border-radius: 10px !important;
  }

  .config-card {
    border-radius: 8px !important;
    margin-bottom: 10px !important;
  }

  /* 移动端标签页优化 */
  :deep(.main-category-tabs .v-tab) {
    padding: 8px 10px !important;
    font-size: 0.75rem !important;
  }

  :deep(.sub-category-tabs .v-tab) {
    padding: 8px 12px !important;
    font-size: 0.75rem !important;
  }

  /* 对话框在小屏幕上全屏 - 保持镜面效果 */
  :deep(.v-dialog) {
    max-width: 100vw !important;
  }

  :deep(.v-dialog > .v-card) {
    margin: 0 !important;
    border-radius: 0 !important;
    max-height: 100vh !important;
    background: rgba(255, 255, 255, 0.9) !important;
    backdrop-filter: blur(30px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(30px) saturate(180%) !important;
  }

  /* 进一步优化间距 */
  :deep(.v-card-text) {
    padding: 10px !important;
  }

  :deep(.v-card-title) {
    padding: 10px !important;
  }
}

/* 桌面端保持固定高度 */
@media (min-width: 960px) {
  .cache-card {
    height: 200px;
  }
}
</style>
