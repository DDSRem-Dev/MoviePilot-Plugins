<template>
  <v-card-text class="pa-0">
    <!-- 子标签页 -->
    <v-tabs v-model="strmSubTab" color="primary" class="sub-category-tabs" slider-color="primary">
      <v-tab value="tab-transfer" class="sub-tab">
        <v-icon size="small" start>mdi-file-move-outline</v-icon>监控MP整理
      </v-tab>
      <v-tab value="tab-sync" class="sub-tab">
        <v-icon size="small" start>mdi-sync</v-icon>全量同步
      </v-tab>
      <v-tab value="tab-increment-sync" class="sub-tab">
        <v-icon size="small" start>mdi-book-sync</v-icon>增量同步
      </v-tab>
      <v-tab value="tab-life" class="sub-tab">
        <v-icon size="small" start>mdi-calendar-heart</v-icon>监控115生活事件
      </v-tab>
      <v-tab value="tab-api-strm" class="sub-tab">
        <v-icon size="small" start>mdi-api</v-icon>API STRM生成
      </v-tab>
    </v-tabs>
    <v-divider></v-divider>
    <v-window v-model="strmSubTab" :touch="false" class="tab-window">
      <v-window-item value="tab-transfer">
        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
            <div class="text-caption mb-2">监控MoviePilot整理入库事件，自动在本地对应目录生成STRM文件。</div>
          </v-alert>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_monitor_enabled" label="启用" color="info"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_monitor_scrape_metadata_enabled" label="STRM自动刮削"
                color="primary"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_monitor_clouddrive2_enabled" label="CloudDrive2储存监控"
                color="info"></v-switch>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.transfer_monitor_media_server_refresh_enabled" label="媒体服务器刷新"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model.number="config.transfer_monitor_media_server_refresh_delay" label="媒体库延迟刷新(秒)"
                type="number" min="0" density="compact" hint="0 表示不延迟，立即刷新" persistent-hint></v-text-field>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.transfer_monitor_emby_mediainfo_enabled" label="Emby 媒体信息提取"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-select v-model="config.transfer_monitor_mediaservers" label="媒体服务器" :items="mediaservers" multiple
                chips closable-chips></v-select>
            </v-col>
          </v-row>

          <v-row v-if="config.transfer_monitor_emby_mediainfo_enabled && !config.native_emby_mediainfo_enabled">
            <v-col cols="12">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                <div class="text-caption">
                  此功能需配合<strong>神医助手PRO</strong>使用，请确保神医助手PRO版本为 <strong>v3.0.0.40</strong> 及以上。
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <!-- Transfer Monitor Exclude Paths -->
          <v-row v-if="config.transfer_monitor_scrape_metadata_enabled" class="mt-2 mb-2">
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(item, index) in transferExcludePaths" :key="`transfer-exclude-${index}`"
                  class="mb-2 d-flex align-center">
                  <v-text-field v-model="item.path" label="刮削排除目录" density="compact" variant="outlined" readonly
                    hide-details class="flex-grow-1 mr-2">
                  </v-text-field>
                  <v-btn icon size="small" color="error" class="ml-2"
                    @click="removeExcludePathEntry(index, 'transfer_exclude')" :disabled="!item.path">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-folder-plus-outline" variant="tonal" class="mt-1 align-self-start"
                  @click="openExcludeDirSelector('transfer_monitor_scrape_metadata_exclude_paths')">
                  添加刮削排除目录
                </v-btn>
              </div>
              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-caption">此处添加的本地目录，在STRM文件生成后将不会自动触发刮削。</div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-recycle">
                <div class="text-body-2 mb-1"><strong>重新整理清理：</strong></div>
                <div class="text-caption">当整理方式为「移动」且源路径已在媒体库内时（即重新整理场景），自动清理源路径对应的旧失效 STRM 文件。</div>
              </v-alert>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_monitor_remove_stale_strm" label="清理失效STRM" color="error"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_monitor_remove_stale_strm_dir" label="清理无效STRM目录" color="error"
                :disabled="!config.transfer_monitor_remove_stale_strm"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_monitor_remove_stale_strm_file" label="清理无效STRM关联媒体信息文件" color="error"
                :disabled="!config.transfer_monitor_remove_stale_strm"></v-switch>
            </v-col>
          </v-row>

          <v-row v-if="config.transfer_monitor_clouddrive2_enabled">
            <v-col cols="12">
              <v-alert type="info" variant="tonal" density="compact" icon="mdi-information">
                <div class="text-caption">仅 CloudDrive2 储存的路径需要填写「CD2 挂载前缀」，该前缀会与该行的网盘媒体库目录拼接成最终路径。</div>
              </v-alert>
            </v-col>
          </v-row>
          <v-row v-if="hasCd2ConfigWhenDisabled">
            <v-col cols="12">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                <div class="text-caption">CloudDrive2 储存监控已关闭，但「监控MP整理」目录配置中仍存在 CD2 挂载前缀，请检查配置。</div>
              </v-alert>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in transferPaths" :key="`transfer-${index}`"
                  class="mb-2 d-flex align-center flex-wrap">
                  <div class="path-selector flex-grow-1 mr-2" style="min-width: 140px;">
                    <v-text-field v-model="pair.local" label="本地STRM目录" density="compact" append-icon="mdi-folder"
                      @click:append="openDirSelector(index, 'local', 'transfer')"></v-text-field>
                  </div>
                  <v-icon class="mr-2">mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 mr-2" style="min-width: 140px;">
                    <v-text-field v-model="pair.remote" label="网盘媒体库目录" density="compact"
                      append-icon="mdi-folder-network"
                      @click:append="openDirSelector(index, 'remote', 'transfer')"></v-text-field>
                  </div>
                  <template v-if="config.transfer_monitor_clouddrive2_enabled">
                    <v-text-field v-model="pair.cd2Prefix" label="CD2 挂载前缀" density="compact"
                      placeholder="可选，如 /115open" class="mr-2" hide-details style="max-width: 160px;"></v-text-field>
                  </template>
                  <v-btn icon size="small" color="error" class="ml-1" @click="removePath(index, 'transfer')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('transfer')">
                  添加路径
                </v-btn>
              </div>

              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• <strong>本地STRM目录：</strong>本地STRM文件生成路径</div>
                  <div class="mb-1">• <strong>网盘媒体库目录：</strong>需要生成本地STRM文件的网盘媒体库路径</div>
                  <div v-if="config.transfer_monitor_clouddrive2_enabled">• <strong>CD2 挂载前缀：</strong>仅
                    CloudDrive2
                    储存时填写，将与此行网盘路径拼接</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in transferMpPaths" :key="`mp-${index}`" class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="媒体库服务器映射目录" density="compact"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="MP映射目录" density="compact"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'mp')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('mp')">
                  添加路径
                </v-btn>
              </div>

              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• 媒体服务器映射路径和MP映射路径不一样时请配置此项，如果不配置则无法正常刷新或Emby提取媒体信息。</div>
                  <div>• 当映射路径一样时可省略此配置。</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-sync">
        <v-card-text>
          <!-- 基础配置 -->
          <div class="basic-config">
            <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
              <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
              <div class="text-caption mb-2">全量扫描配置的网盘目录，并在对应的本地目录生成STRM文件。</div>
            </v-alert>
            <v-row>
              <v-col cols="12" md="3">
                <v-select v-model="config.full_sync_overwrite_mode" label="覆盖模式" :items="[
                  { title: '总是', value: 'always' },
                  { title: '从不', value: 'never' }
                ]" chips closable-chips></v-select>
              </v-col>
              <v-col cols="12" md="3">
                <v-switch v-model="config.full_sync_remove_unless_strm" label="清理失效STRM文件" color="warning"></v-switch>
              </v-col>
              <v-col cols="12" md="3">
                <v-switch v-model="config.full_sync_remove_unless_dir" label="清理无效STRM目录" color="warning"
                  :disabled="!config.full_sync_remove_unless_strm"></v-switch>
              </v-col>
              <v-col cols="12" md="3">
                <v-switch v-model="config.full_sync_remove_unless_file" label="清理无效STRM文件关联的媒体信息文件" color="warning"
                  :disabled="!config.full_sync_remove_unless_strm"></v-switch>
              </v-col>
            </v-row>

            <v-row>
              <v-col cols="12" md="12">
                <v-select v-model="config.full_sync_cleanup_confirm_mode" label="清理失效 STRM 二次验证" :items="[
                  { title: '无（通过稳定性检查后立即删除）', value: 'none' },
                  { title: '插件界面确认', value: 'plugin_ui' },
                  { title: 'Telegram 通知按钮确认', value: 'telegram' },
                ]" hint="需开启「清理失效STRM文件」；选择后待删文件先入队，确认后再物理删除" persistent-hint density="compact"
                  :disabled="!config.full_sync_remove_unless_strm"></v-select>
              </v-col>
            </v-row>

            <v-row>
              <v-col cols="12" md="3">
                <v-switch v-model="config.timing_full_sync_strm" label="定期全量同步" color="info"></v-switch>
              </v-col>
              <v-col cols="12" md="3">
                <VCronField v-model="config.cron_full_sync_strm" label="运行全量同步周期" hint="设置全量同步的执行周期" persistent-hint
                  density="compact"></VCronField>
              </v-col>
              <v-col cols="12" md="3">
                <v-switch v-model="config.full_sync_auto_download_mediainfo_enabled" label="下载媒体数据文件"
                  color="warning"></v-switch>
              </v-col>
              <v-col cols="12" md="3">
                <v-text-field v-model="fullSyncMinFileSizeFormattedRef" label="STRM最小文件大小"
                  hint="小于此值的文件将不生成STRM(单位K,M,G)" persistent-hint density="compact" placeholder="例如: 100M (可为空)"
                  clearable></v-text-field>
              </v-col>
            </v-row>

            <v-row>
              <v-col cols="12" md="3">
                <v-switch v-model="config.full_sync_media_server_refresh_enabled" label="全量同步后刷新媒体库" color="error"
                  density="compact"></v-switch>
              </v-col>
              <v-col cols="12" md="3">
                <v-text-field v-model.number="config.full_sync_media_server_refresh_delay" label="媒体库延迟刷新(秒)" type="number"
                  min="0" density="compact" hint="0 表示不延迟" persistent-hint></v-text-field>
              </v-col>
              <v-col cols="12" md="6">
                <v-select v-model="config.full_sync_mediaservers" label="媒体服务器" :items="mediaservers" multiple chips
                  closable-chips :disabled="!config.full_sync_media_server_refresh_enabled" hint="全量同步完成后将刷新整个媒体库，请谨慎使用"
                  persistent-hint></v-select>
              </v-col>
              <v-col v-if="config.full_sync_media_server_refresh_enabled" cols="12">
                <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
                  <div class="text-body-2 mb-1"><strong>重要警告</strong></div>
                  <div class="text-caption">
                    启用此功能后，全量同步完成后将自动刷新整个媒体库。此操作会扫描所有媒体文件，可能导致媒体服务器负载增加，请确保您已了解此风险并自行承担相应责任。
                  </div>
                </v-alert>
              </v-col>
            </v-row>

            <v-row>
              <v-col cols="12">
                <div class="d-flex flex-column">
                  <div v-for="(pair, index) in fullSyncPaths" :key="`full-${index}`"
                    class="mb-2 d-flex align-center gap-1">
                    <div class="path-selector flex-grow-1 mr-1">
                      <v-text-field v-model="pair.local" label="本地STRM目录" density="compact" append-icon="mdi-folder"
                        @click:append="openDirSelector(index, 'local', 'fullSync')"></v-text-field>
                    </div>
                    <v-icon class="shrink-0">mdi-pound</v-icon>
                    <div class="path-selector flex-grow-1 mx-1">
                      <v-text-field v-model="pair.remote" label="网盘媒体库目录" density="compact"
                        append-icon="mdi-folder-network"
                        @click:append="openDirSelector(index, 'remote', 'fullSync')"></v-text-field>
                    </div>
                    <v-tooltip :text="pair.enabled ? '参与全量同步，点击关闭' : '不参与全量同步，点击开启'" location="top">
                      <template #activator="{ props: tooltipProps }">
                        <v-btn v-bind="tooltipProps" icon size="small" :color="pair.enabled ? 'primary' : 'default'"
                          variant="text" class="shrink-0" @click="pair.enabled = !pair.enabled">
                          <v-icon>{{ pair.enabled ? 'mdi-sync' : 'mdi-sync-off' }}</v-icon>
                        </v-btn>
                      </template>
                    </v-tooltip>
                    <v-btn icon size="small" color="error" variant="text" class="shrink-0"
                      @click="removePath(index, 'fullSync')">
                      <v-icon>mdi-delete</v-icon>
                    </v-btn>
                  </div>
                  <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                    @click="addPath('fullSync')">
                    添加路径
                  </v-btn>
                </div>

                <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                  <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                  <div class="text-caption">
                    <div class="mb-1">• <strong>同步：</strong>开启时该目录参与全量同步，关闭则不参与（机器人命令按路径执行不受影响）</div>
                    <div class="mb-1">• <strong>本地STRM目录：</strong>本地STRM文件生成路径</div>
                    <div>• <strong>网盘媒体库目录：</strong>需要生成本地STRM文件的网盘媒体库路径</div>
                  </div>
                </v-alert>
              </v-col>
            </v-row>
          </div>

          <!-- 高级配置 -->
          <v-expansion-panels variant="tonal" class="mt-6">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon icon="mdi-tune-variant" class="mr-2"></v-icon>
                高级配置
              </v-expansion-panel-title>
              <v-expansion-panel-text class="pa-4">
                <v-row>
                  <v-col cols="12" md="3">
                    <v-switch v-model="config.full_sync_strm_log" label="输出STRM同步日志" color="primary"></v-switch>
                  </v-col>
                  <v-col cols="12" md="3">
                    <v-switch v-model="config.full_sync_process_rust" label="Rust模式处理数据" color="primary"></v-switch>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-select v-model="config.full_sync_iter_function" label="迭代函数" :items="[
                      { title: 'iter_files_with_path_skim', value: 'iter_files_with_path_skim' },
                      { title: 'iter_files_with_path', value: 'iter_files_with_path' }
                    ]" chips closable-chips></v-select>
                  </v-col>
                </v-row>
                <v-row>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.full_sync_batch_num" label="全量同步批处理数量" type="number"
                      hint="每次批量处理的文件/目录数量" persistent-hint density="compact"></v-text-field>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.full_sync_process_num" label="全量同步生成进程数" type="number"
                      hint="同时执行同步任务的进程数量" persistent-hint density="compact"></v-text-field>
                  </v-col>
                </v-row>
                <v-row>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.full_sync_remove_unless_max_threshold"
                      label="清理无效 STRM 最大删除比例阈值 (%)" type="number" hint="当待删除文件数占本地文件总数的百分比超过此值时，将进入数据稳定性检查（默认 10%）"
                      persistent-hint density="compact"></v-text-field>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.full_sync_remove_unless_stable_threshold"
                      label="清理数据稳定性检查阈值 (%)" type="number" hint="数据稳定性检查的变异系数阈值，低于此值表示删除数据稳定可执行操作（默认 5%）"
                      persistent-hint density="compact"></v-text-field>
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-increment-sync">
        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
            <div class="text-caption mb-2">增量扫描配置的网盘目录，并在对应的本地目录生成STRM文件。</div>
          </v-alert>
          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_strm_enabled" label="启用" color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <VCronField v-model="config.increment_sync_cron" label="运行增量同步周期" hint="设置增量同步的执行周期" persistent-hint
                density="compact"></VCronField>
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model="incrementSyncMinFileSizeFormattedRef" label="STRM最小文件大小"
                hint="小于此值的文件将不生成STRM(单位K,M,G)" persistent-hint density="compact" placeholder="例如: 100M (可为空)"
                clearable></v-text-field>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_auto_download_mediainfo_enabled" label="下载媒体数据文件"
                color="warning"></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_media_server_refresh_enabled" label="媒体服务器刷新"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model.number="config.increment_sync_media_server_refresh_delay" label="媒体库延迟刷新(秒)"
                type="number" min="0" density="compact" hint="0 表示不延迟" persistent-hint></v-text-field>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_emby_mediainfo_enabled" label="Emby 媒体信息提取"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-select v-model="config.increment_sync_mediaservers" label="媒体服务器" :items="mediaservers" multiple chips
                closable-chips></v-select>
            </v-col>
          </v-row>

          <v-row v-if="config.increment_sync_emby_mediainfo_enabled && !config.native_emby_mediainfo_enabled">
            <v-col cols="12">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                <div class="text-caption">
                  此功能需配合<strong>神医助手PRO</strong>使用，请确保神医助手PRO版本为 <strong>v3.0.0.40</strong> 及以上。
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_scrape_metadata_enabled" label="STRM自动刮削"
                color="primary"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_remove_unless_strm" label="清理失效STRM文件"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_remove_unless_dir" label="清理无效STRM目录" color="warning"
                :disabled="!config.increment_sync_remove_unless_strm"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.increment_sync_remove_unless_file" label="清理无效STRM文件关联的媒体信息文件" color="warning"
                :disabled="!config.increment_sync_remove_unless_strm"></v-switch>
            </v-col>
          </v-row>

          <v-row v-if="config.increment_sync_scrape_metadata_enabled" class="mt-2 mb-2">
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(item, index) in incrementSyncExcludePaths" :key="`increment-exclude-${index}`"
                  class="mb-2 d-flex align-center">
                  <v-text-field v-model="item.path" label="刮削排除目录" density="compact" variant="outlined" readonly
                    hide-details class="flex-grow-1 mr-2">
                  </v-text-field>
                  <v-btn icon size="small" color="error" class="ml-2"
                    @click="removeExcludePathEntry(index, 'increment_exclude')" :disabled="!item.path">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-folder-plus-outline" variant="tonal" class="mt-1 align-self-start"
                  @click="openExcludeDirSelector('increment_sync_scrape_metadata_exclude_paths')">
                  添加刮削排除目录
                </v-btn>
              </div>
              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-caption">此处添加的本地目录，在STRM文件生成后将不会自动触发刮削。</div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in incrementSyncPaths" :key="`increment-${index}`"
                  class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="本地STRM目录" density="compact" append-icon="mdi-folder"
                      @click:append="openDirSelector(index, 'local', 'incrementSync')"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="网盘媒体库目录" density="compact"
                      append-icon="mdi-folder-network"
                      @click:append="openDirSelector(index, 'remote', 'incrementSync')"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'incrementSync')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('incrementSync')">
                  添加路径
                </v-btn>
              </div>

              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• <strong>本地STRM目录：</strong>本地STRM文件生成路径</div>
                  <div>• <strong>网盘媒体库目录：</strong>需要生成本地STRM文件的网盘媒体库路径</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in incrementSyncMPPaths" :key="`increment-mp-${index}`"
                  class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="媒体库服务器映射目录" density="compact"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="MP映射目录" density="compact"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'increment-mp')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('increment-mp')">
                  添加路径
                </v-btn>
              </div>

              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• 媒体服务器映射路径和MP映射路径不一样时请配置此项，如果不配置则无法正常刷新或 Emby 提取媒体信息。</div>
                  <div>• 当映射路径一样时可省略此配置。</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <!-- 高级配置 -->
          <v-expansion-panels variant="tonal" class="mt-6">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon icon="mdi-tune-variant" class="mr-2"></v-icon>
                高级配置
              </v-expansion-panel-title>
              <v-expansion-panel-text class="pa-4">
                <v-row>
                  <v-col cols="12" md="6">
                    <v-switch v-model="config.increment_sync_second_level_dir_scan" label="扫描二级目录生成目录树"
                      color="primary"></v-switch>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.increment_sync_itertree_timeout_seconds" label="目录树导出超时（秒）"
                      type="number" min="0" hide-spin-buttons hint="115 云端导出目录树任务的最大等待时间；0 表示不限制"
                      persistent-hint></v-text-field>
                  </v-col>
                </v-row>
                <v-row>
                  <v-col cols="12">
                    <v-alert type="info" variant="tonal" density="compact" icon="mdi-information">
                      <div class="text-caption">
                        开启后，将扫描「增量同步目录」中配置的网盘路径下的二级子目录，并以这些二级目录为单位生成目录树。每个配置路径下仅允许包含子文件夹、不得包含文件，且二级目录数量不超过
                        100 个。
                      </div>
                    </v-alert>
                  </v-col>
                </v-row>
                <v-row v-if="config.increment_sync_remove_unless_strm">
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.increment_sync_remove_unless_max_threshold"
                      label="清理无效 STRM 最大删除比例阈值 (%)" type="number" hint="待删除文件数占本地文件总数的百分比超过此值时，将进入数据稳定性检查（默认 10%）"
                      persistent-hint density="compact"></v-text-field>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.increment_sync_remove_unless_stable_threshold"
                      label="清理数据稳定性检查阈值 (%)" type="number" hint="数据稳定性检查的变异系数阈值，低于此值表示删除数据稳定可执行操作（默认 5%）"
                      persistent-hint density="compact"></v-text-field>
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-life">
        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
            <div class="text-caption mb-2">监控115生活（上传、移动、接收文件、删除、复制、重命名）事件，自动在本地对应目录生成STRM文件或者删除STRM文件。</div>
          </v-alert>
          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.monitor_life_enabled" label="启用" color="info"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-select v-model="config.monitor_life_event_modes" label="处理事件类型" :items="[
                { title: '新增事件', value: 'creata' },
                { title: '删除事件', value: 'remove' },
                { title: '重命名事件', value: 'rename' },
                { title: '网盘整理', value: 'transfer' }
              ]" multiple chips closable-chips></v-select>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.monitor_life_remove_mp_history" label="同步删除历史记录" color="warning"
                :disabled="config.monitor_life_remove_mp_source"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.monitor_life_remove_mp_source" label="同步删除源文件" color="warning"
                @change="value => { if (value) config.monitor_life_remove_mp_history = true }"></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="6">
              <v-switch v-model="config.monitor_life_rename_auto_related_files" label="重命名事件时同步重命名 STRM 关联文件"
                color="primary" density="compact" hide-details></v-switch>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <v-card variant="outlined" class="pa-3 life-move-strategy-card">
                <div class="d-flex align-center mb-2 life-move-title">
                  <v-icon icon="mdi-tune-variant" size="14" class="mr-1"></v-icon>
                  <span>移动事件处理策略</span>
                </div>
                <v-divider class="mb-3"></v-divider>
                <v-row>
                  <v-col cols="12" md="4">
                    <v-select v-model="config.monitor_life_move_media_mode" label="媒体目录内移动模式" :items="[
                      { title: '删除/重建（recreate）', value: 'recreate' },
                      { title: '纯本地迁移（local_move）', value: 'local_move' }
                    ]" density="compact" variant="outlined" hide-details="auto"></v-select>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-switch v-model="config.monitor_life_move_out_media_remove_local_strm"
                      label="媒体 -> 其它目录 时删除本地STRM" color="warning" density="compact" hide-details></v-switch>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-switch v-model="config.monitor_life_move_media_to_transfer_remove_local_strm"
                      label="媒体 -> 待整理 时删除本地STRM" color="warning" density="compact" hide-details></v-switch>
                  </v-col>
                </v-row>

                <v-row v-if="config.monitor_life_move_media_mode === 'recreate'">
                  <v-col cols="12" md="6">
                    <v-switch v-model="config.monitor_life_move_media_keep_old_strm" label="媒体 -> 媒体 时保留旧STRM"
                      color="primary" density="compact" hide-details></v-switch>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-switch v-model="config.monitor_life_move_media_create_new_strm" label="媒体 -> 媒体 时生成新STRM"
                      color="primary" density="compact" hide-details></v-switch>
                  </v-col>
                </v-row>

                <v-row v-if="config.monitor_life_move_media_mode === 'local_move'">
                  <v-col cols="12">
                    <v-switch v-model="config.monitor_life_move_media_local_move_related_files"
                      label="local_move 时迁移 STRM 关联文件" color="primary" density="compact" hide-details></v-switch>
                  </v-col>
                </v-row>

                <v-alert type="info" variant="text" density="compact" class="mt-3" icon="mdi-information">
                  <div class="text-caption">
                    <div class="mb-1">下表根据你当前配置实时生成，展示“源目录 -> 目标目录”的实际处理动作</div>
                    <div>说明：源目录类型以数据库可识别路径为准</div>
                  </div>
                </v-alert>

                <v-table density="compact" class="mt-2 life-move-matrix">
                  <thead>
                    <tr>
                      <th class="text-left">源目录</th>
                      <th class="text-left">目标目录</th>
                      <th class="text-left">当前处理动作（实时）</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in lifeMoveMatrixRows" :key="`${item.source}-${item.target}`">
                      <td>{{ item.sourceLabel }}</td>
                      <td>{{ item.targetLabel }}</td>
                      <td>{{ item.action }}</td>
                    </tr>
                  </tbody>
                </v-table>
              </v-card>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.monitor_life_media_server_refresh_enabled" label="媒体服务器刷新"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model.number="config.monitor_life_media_server_refresh_delay" label="媒体库延迟刷新(秒)"
                type="number" min="0" density="compact" hint="0 表示不延迟" persistent-hint></v-text-field>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.monitor_life_emby_mediainfo_enabled" label="Emby 媒体信息提取"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-select v-model="config.monitor_life_mediaservers" label="媒体服务器" :items="mediaservers" multiple chips
                closable-chips></v-select>
            </v-col>
          </v-row>

          <v-row v-if="config.monitor_life_emby_mediainfo_enabled && !config.native_emby_mediainfo_enabled">
            <v-col cols="12">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-alert-circle-outline">
                <div class="text-caption">
                  此功能需配合<strong>神医助手PRO</strong>使用，请确保神医助手PRO版本为 <strong>v3.0.0.40</strong> 及以上。
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.monitor_life_auto_download_mediainfo_enabled" label="下载媒体数据文件"
                color="warning"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.monitor_life_scrape_metadata_enabled" label="STRM自动刮削"
                color="primary"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field v-model="monitorLifeMinFileSizeFormattedRef" label="STRM最小文件大小"
                hint="小于此值的文件将不生成STRM(单位K,M,G)" persistent-hint density="compact" placeholder="例如: 100M (可为空)"
                clearable></v-text-field>
            </v-col>
          </v-row>

          <!-- Monitor Life Exclude Paths -->
          <v-row v-if="config.monitor_life_scrape_metadata_enabled" class="mt-2 mb-2">
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(item, index) in monitorLifeExcludePaths" :key="`life-exclude-${index}`"
                  class="mb-2 d-flex align-center">
                  <v-text-field v-model="item.path" label="刮削排除目录" density="compact" variant="outlined" readonly
                    hide-details class="flex-grow-1 mr-2">
                  </v-text-field>
                  <v-btn icon size="small" color="error" class="ml-2"
                    @click="removeExcludePathEntry(index, 'life_exclude')" :disabled="!item.path">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-folder-plus-outline" variant="tonal" class="mt-1 align-self-start"
                  @click="openExcludeDirSelector('monitor_life_scrape_metadata_exclude_paths')">
                  添加刮削排除目录
                </v-btn>
              </div>
              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-caption">此处添加的本地目录，在115生活事件监控生成STRM后将不会自动触发刮削。</div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in monitorLifePaths" :key="`life-${index}`" class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="本地STRM目录" density="compact" append-icon="mdi-folder"
                      @click:append="openDirSelector(index, 'local', 'monitorLife')"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="网盘媒体库目录" density="compact"
                      append-icon="mdi-folder-network"
                      @click:append="openDirSelector(index, 'remote', 'monitorLife')"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'monitorLife')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('monitorLife')">
                  添加路径
                </v-btn>
              </div>

              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• <strong>本地STRM目录：</strong>本地STRM文件生成路径</div>
                  <div>• <strong>网盘媒体库目录：</strong>需要生成本地STRM文件的网盘媒体库路径</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in monitorLifeMpPaths" :key="`life-mp-${index}`"
                  class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="媒体库服务器映射目录" density="compact"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="MP映射目录" density="compact"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'monitorLifeMp')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('monitorLifeMp')">
                  添加路径
                </v-btn>
              </div>

              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• 媒体服务器映射路径和MP映射路径不一样时请配置此项，如果不配置则无法正常刷新或 Emby 提取媒体信息。</div>
                  <div>• 当映射路径一样时可省略此配置。</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>

          <v-expansion-panels variant="tonal" class="mt-6">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon icon="mdi-tune-variant" class="mr-2"></v-icon>
                高级配置
              </v-expansion-panel-title>
              <v-expansion-panel-text class="pa-4">
                <v-row>
                  <v-col cols="12" md="3">
                    <v-text-field v-model.number="config.monitor_life_transfer_stall_timeout_minutes"
                      label="整理无进展超时(分钟)" type="number" min="1" density="compact" hint="队列持续无变化达到时限后记录残留任务并恢复监控"
                      persistent-hint></v-text-field>
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <v-expansion-panels variant="tonal" class="mt-3 life-logic-panels">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon icon="mdi-table-eye" class="mr-2"></v-icon>
                事件处理逻辑与当前配置
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div class="life-table-scroll">
                  <v-table density="compact" class="life-logic-table">
                    <thead>
                      <tr>
                        <th>类型</th>
                        <th>115 事件</th>
                        <th>所需模式</th>
                        <th>实际处理</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="item in lifeEventLogicRows" :key="item.types">
                        <td class="life-type-cell">{{ item.types }}</td>
                        <td><strong>{{ item.events }}</strong></td>
                        <td>
                          <v-chip v-if="item.mode" size="x-small" variant="tonal"
                            :color="isLifeModeEnabled(item.mode) ? 'success' : 'default'">
                            {{ item.modeLabel }} · {{ isLifeModeEnabled(item.mode) ? '已启用' : '未启用' }}
                          </v-chip>
                          <span v-else class="text-medium-emphasis">{{ item.modeLabel }}</span>
                        </td>
                        <td>{{ item.action }}</td>
                      </tr>
                    </tbody>
                  </v-table>
                </div>
                <v-alert type="info" variant="text" density="compact" class="mt-2" icon="mdi-database-outline">
                  <div class="text-caption">
                    所有拉取到的事件都会先保存到生活事件数据库；未接入的事件只留档，不操作文件数据库或本地文件。
                  </div>
                </v-alert>
              </v-expansion-panel-text>
            </v-expansion-panel>

            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon icon="mdi-routes" class="mr-2"></v-icon>
                路径判断、文件类型与安全边界
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <div class="life-table-scroll">
                  <v-table density="compact" class="life-logic-table life-rule-table">
                    <thead>
                      <tr>
                        <th>判断阶段</th>
                        <th>条件</th>
                        <th>结果</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="item in lifePathRuleRows" :key="`${item.stage}-${item.condition}`">
                        <td><strong>{{ item.stage }}</strong></td>
                        <td>{{ item.condition }}</td>
                        <td>{{ item.result }}</td>
                      </tr>
                    </tbody>
                  </v-table>
                </div>
                <v-alert type="warning" variant="tonal" density="compact" class="mt-3"
                  icon="mdi-alert-outline">
                  <div class="text-caption">
                    文件 type 24 已支持 115 将“移动 + 重命名”合并上报；文件夹 type 20 仍只支持同父目录改名。
                    文件夹改名或移动不会逐个校验内部 STRM 内容，依赖路径型 URL 时需留意旧 file_path。
                  </div>
                </v-alert>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-caption">注意：当 MoviePilot 主程序运行整理任务时 115生活事件 监控会自动暂停，整理运行完成后会继续监控。</div>
          </v-alert>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-btn color="info" variant="outlined" prepend-icon="mdi-bug-check" @click="checkLifeEventStatus">
                故障检查
              </v-btn>
              <div class="text-caption text-grey mt-2">
                检查115生活事件进程状态，测试数据拉取功能，并提供详细的调试信息
              </div>
            </v-col>
          </v-row>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-api-strm">
        <v-card-text>
          <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
            <div class="text-caption mb-2">API STRM 生成功能允许第三方开发者通过 HTTP API 调用，批量生成 STRM 文件。</div>
            <div class="text-caption">
              详细 API 文档请参考：
              <a href="https://github.com/DDSRem-Dev/MoviePilot-Plugins/blob/main/docs/p115strmhelper/API_STRM生成功能文档.md"
                target="_blank" rel="noopener noreferrer" style="color: inherit; text-decoration: underline;">
                GitHub 文档链接
              </a>
            </div>
          </v-alert>

          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.api_strm_scrape_metadata_enabled" label="STRM自动刮削" color="primary"
                density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.api_strm_media_server_refresh_enabled" label="媒体服务器刷新" color="warning"
                density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model.number="config.api_strm_media_server_refresh_delay" label="媒体库延迟刷新(秒)" type="number"
                min="0" density="compact" hint="0 表示不延迟" persistent-hint></v-text-field>
            </v-col>
            <v-col cols="12" md="3">
              <v-select v-model="config.api_strm_mediaservers" label="媒体服务器" :items="mediaservers" multiple chips
                closable-chips density="compact"></v-select>
            </v-col>
          </v-row>

          <v-divider class="my-4"></v-divider>

          <div class="text-subtitle-2 mb-2">路径映射配置:</div>
          <v-alert type="info" variant="tonal" density="compact" class="mb-3" icon="mdi-information">
            <div class="text-caption">配置网盘路径到本地路径的映射关系。当 API 请求中未指定 local_path 时，系统会根据此配置自动匹配路径。</div>
          </v-alert>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in apiStrmPaths" :key="`api-strm-${index}`" class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="本地STRM目录" density="compact" append-icon="mdi-folder"
                      @click:append="openDirSelector(index, 'local', 'apiStrm')"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="网盘媒体库目录" density="compact"
                      append-icon="mdi-folder-network"
                      @click:append="openDirSelector(index, 'remote', 'apiStrm')"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'apiStrm')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('apiStrm')">
                  添加路径
                </v-btn>
              </div>
            </v-col>
          </v-row>

          <v-divider class="my-4"></v-divider>

          <div class="text-subtitle-2 mb-2">MoviePilot-媒体库 目录转换:</div>
          <v-alert type="info" variant="tonal" density="compact" class="mb-3" icon="mdi-information">
            <div class="text-caption">媒体服务器映射路径和MP映射路径不一样时请配置此项，如果不配置则无法正常刷新或Emby提取媒体信息</div>
          </v-alert>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(pair, index) in apiStrmMPPaths" :key="`api-strm-mp-${index}`"
                  class="mb-2 d-flex align-center">
                  <div class="path-selector flex-grow-1 mr-2">
                    <v-text-field v-model="pair.local" label="媒体库服务器映射目录" density="compact"></v-text-field>
                  </div>
                  <v-icon>mdi-pound</v-icon>
                  <div class="path-selector flex-grow-1 ml-2">
                    <v-text-field v-model="pair.remote" label="MP映射目录" density="compact"></v-text-field>
                  </div>
                  <v-btn icon size="small" color="error" class="ml-2" @click="removePath(index, 'apiStrm-mp')">
                    <v-icon>mdi-delete</v-icon>
                  </v-btn>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('apiStrm-mp')">
                  添加路径
                </v-btn>
              </div>
            </v-col>
          </v-row>
        </v-card-text>
      </v-window-item>
    </v-window>
  </v-card-text>
</template>

<script setup>
import { computed, ref, inject } from 'vue';

const strmSubTab = ref('tab-transfer');

const config = inject('config');
const mediaservers = inject('mediaservers');
const transferPaths = inject('transferPaths');
/** CloudDrive2 已关闭但目录配置中仍有 CD2 前缀时为 true */
const hasCd2ConfigWhenDisabled = computed(() => {
  const c = config?.value ?? config;
  if (c?.transfer_monitor_clouddrive2_enabled) return false;
  const paths = transferPaths?.value ?? transferPaths ?? [];
  return (
    Array.isArray(paths) &&
    paths.some((p) => String(p?.cd2Prefix ?? '').trim() !== '')
  );
});
const transferMpPaths = inject('transferMpPaths');
const fullSyncPaths = inject('fullSyncPaths');
const incrementSyncPaths = inject('incrementSyncPaths');
const incrementSyncMPPaths = inject('incrementSyncMPPaths');
const monitorLifePaths = inject('monitorLifePaths');
const monitorLifeMpPaths = inject('monitorLifeMpPaths');
const apiStrmPaths = inject('apiStrmPaths');
const apiStrmMPPaths = inject('apiStrmMPPaths');
const transferExcludePaths = inject('transferExcludePaths');
const incrementSyncExcludePaths = inject('incrementSyncExcludePaths');
const monitorLifeExcludePaths = inject('monitorLifeExcludePaths');
const fullSyncMinFileSizeFormattedRef = inject('fullSyncMinFileSizeFormattedRef');
const incrementSyncMinFileSizeFormattedRef = inject('incrementSyncMinFileSizeFormattedRef');
const monitorLifeMinFileSizeFormattedRef = inject('monitorLifeMinFileSizeFormattedRef');
const addPath = inject('addPath');
const removePath = inject('removePath');
const openDirSelector = inject('openDirSelector');
const openExcludeDirSelector = inject('openExcludeDirSelector');
const removeExcludePathEntry = inject('removeExcludePathEntry');
const checkLifeEventStatus = inject('checkLifeEventStatus');

const lifeEventLogicRows = [
  {
    types: '1, 2',
    events: 'upload_image_file / upload_file',
    mode: 'creata',
    modeLabel: '新增事件',
    action: '解析新路径；待整理目录优先进入整理。媒体文件生成 STRM，可下载扩展名按下载开关和黑白名单下载；目录会递归处理。',
  },
  {
    types: '5, 6',
    events: 'move_image_file / move_file',
    mode: null,
    modeLabel: '移动策略',
    action: '根据旧、新路径所属的媒体、待整理或其它目录执行下方实时移动矩阵；没有独立事件模式开关。',
  },
  {
    types: '14',
    events: 'receive_files',
    mode: 'creata',
    modeLabel: '新增事件',
    action: '作为新路径处理；按文件类型生成 STRM、下载媒体数据文件，或在命中待整理目录时进入整理。',
  },
  {
    types: '17',
    events: 'new_folder',
    mode: null,
    modeLabel: '自动维护',
    action: '仅写入文件夹路径数据库，供后续事件解析父目录；待整理目录和未识别目录不写入。',
  },
  {
    types: '18, 23',
    events: 'copy_folder / copy_file',
    mode: 'creata',
    modeLabel: '新增事件',
    action: '作为新路径处理；复制文件夹会递归扫描，复制文件直接按媒体或可下载扩展名处理。',
  },
  {
    types: '20',
    events: 'folder_rename',
    mode: 'rename',
    modeLabel: '重命名事件',
    action: '先同步数据库和目录缓存；同父目录时重命名本地映射目录，跨父目录时仅同步路径记录。',
  },
  {
    types: '22',
    events: 'delete_file',
    mode: 'remove',
    modeLabel: '删除事件',
    action: '数据库能确认旧路径且 115 当前路径已不存在时，删除对应 STRM、非媒体文件或本地目录；可同步清理整理历史。',
  },
  {
    types: '24',
    events: 'rename_file',
    mode: 'rename',
    modeLabel: '重命名事件',
    action: '支持普通改名及“移动 + 改名”；迁移并更新 STRM，同步关联文件。非媒体事件只处理文件自身，缺失时按新路径恢复。',
  },
  {
    types: '其它',
    events: '浏览、标星、标签及未接入类型',
    mode: null,
    modeLabel: '不处理',
    action: '仅保存生活事件记录，不修改文件数据库，也不操作本地文件。',
  },
];

const lifePathRuleRows = [
  {
    stage: '路径优先级',
    condition: '新路径命中未识别目录',
    result: '跳过文件动作；重命名事件的数据库路径同步已在此前完成。',
  },
  {
    stage: '路径优先级',
    condition: '新路径命中待整理目录',
    result: '优先进入 MoviePilot 网盘整理，不直接按媒体库新增处理。',
  },
  {
    stage: '媒体目录',
    condition: '路径命中“本地 STRM 目录 # 网盘媒体库目录”映射',
    result: '将网盘相对路径映射到本地目录，再进行生成、迁移、重命名或删除。',
  },
  {
    stage: '媒体文件',
    condition: '扩展名属于可识别媒体后缀',
    result: '生成或迁移 STRM；生成前校验黑名单、最小文件大小和 pickcode。',
  },
  {
    stage: '非媒体文件',
    condition: '扩展名属于可下载媒体数据文件后缀',
    result: '还需开启“下载媒体数据文件”并通过黑白名单，才会下载；移动和重命名只处理文件自身。',
  },
  {
    stage: '删除保护',
    condition: '数据库没有旧路径、路径仍存在于 115、或位于待整理/未识别目录',
    result: '不删除本地文件，避免误删。',
  },
  {
    stage: '整理去重',
    condition: '事件由插件网盘整理流程触发',
    result: '通过创建和删除缓存抑制重复生成、重复删除；目标 STRM 由“网盘整理”模式决定是否补建。',
  },
];

const isLifeModeEnabled = (mode) => {
  const c = config?.value ?? config;
  return Array.isArray(c?.monitor_life_event_modes) && c.monitor_life_event_modes.includes(mode);
};

const lifeMoveMatrixRows = computed(() => {
  const c = config?.value ?? config;
  const mode = c.monitor_life_move_media_mode;
  const recreateKeep = Boolean(c.monitor_life_move_media_keep_old_strm);
  const recreateCreate = Boolean(c.monitor_life_move_media_create_new_strm);
  const outRemove = Boolean(c.monitor_life_move_out_media_remove_local_strm);
  const toTransferRemove = Boolean(c.monitor_life_move_media_to_transfer_remove_local_strm);
  const localMoveRelated = Boolean(c.monitor_life_move_media_local_move_related_files);

  const mediaToMediaAction =
    mode === 'local_move'
      ? `本地迁移旧 STRM（关联文件迁移=${localMoveRelated ? '开启' : '关闭'}）`
      : `按 recreate 执行：保留旧STRM=${recreateKeep ? '是' : '否'}，生成新STRM=${recreateCreate ? '是' : '否'}`;

  const map = {
    '媒体->媒体': mediaToMediaAction,
    '媒体->待整理': `可选删除旧本地STRM（当前=${toTransferRemove ? '是' : '否'}），然后走网盘整理`,
    '媒体->其它': `可选删除旧本地STRM（当前=${outRemove ? '是' : '否'}）`,
    '待整理->媒体': '按“迁入媒体目录”处理，生成新STRM',
    '待整理->待整理': '直接走网盘整理',
    '待整理->其它': '不处理（安全跳过）',
    '其它->媒体': '按“迁入媒体目录”处理，生成新STRM',
    '其它->待整理': '直接走网盘整理',
    '其它->其它': '不处理（安全跳过）',
  };

  const rows = [
    ['媒体', '媒体'],
    ['媒体', '待整理'],
    ['媒体', '其它'],
    ['待整理', '媒体'],
    ['待整理', '待整理'],
    ['待整理', '其它'],
    ['其它', '媒体'],
    ['其它', '待整理'],
    ['其它', '其它'],
  ];
  return rows.map(([source, target]) => ({
    source,
    target,
    sourceLabel: source,
    targetLabel: target,
    action: map[`${source}->${target}`],
  }));
});
</script>

<style scoped>
.life-move-strategy-card {
  background: rgba(var(--v-theme-on-surface), 0.02);
  border-color: rgba(var(--v-theme-on-surface), 0.08);
}

.life-move-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: rgba(var(--v-theme-on-surface), 0.85);
  letter-spacing: 0.01em;
}

.life-move-matrix {
  background: transparent;
}

.life-logic-panels :deep(.v-expansion-panel-text__wrapper) {
  padding: 12px 16px 16px;
}

.life-table-scroll {
  max-width: 100%;
  overflow-x: auto;
}

.life-logic-table {
  min-width: 820px;
  background: transparent;
}

.life-rule-table {
  min-width: 720px;
}

.life-logic-table :deep(th) {
  white-space: nowrap;
  color: rgba(var(--v-theme-on-surface), 0.72);
  font-size: 0.75rem;
}

.life-logic-table :deep(td) {
  min-width: 120px;
  padding-top: 10px !important;
  padding-bottom: 10px !important;
  vertical-align: top;
  line-height: 1.55;
}

.life-logic-table :deep(td:last-child) {
  min-width: 300px;
}

.life-type-cell {
  min-width: 64px !important;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 600px) {
  .life-logic-panels :deep(.v-expansion-panel-title) {
    min-height: 52px;
    padding: 12px;
    font-size: 0.875rem;
  }

  .life-logic-panels :deep(.v-expansion-panel-text__wrapper) {
    padding: 8px 10px 12px;
  }
}
</style>
