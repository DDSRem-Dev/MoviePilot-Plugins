<template>
  <div class="p115-section-stack">
    <!-- Top Segmented Control for 5 STRM Sub-Modules -->
    <div class="p115-subnav-bar">
      <AppleSegmentedControl v-model="strmSubTab" :items="subTabItems" />
    </div>

    <!-- ===================================================================
         1. 监控 MP 整理 (tab-transfer)
         =================================================================== -->
    <div v-if="strmSubTab === 'tab-transfer'" class="p115-section-stack">
      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <strong>功能说明：</strong>监控 MoviePilot 整理入库事件，自动在本地对应目录生成 STRM 文件。
        </div>
      </div>

      <TransferPostprocessRecovery />

      <AppleSettingsGroup
        title="核心监控与刮削联动"
        subtitle="实时响应 MoviePilot 入库事件"
        icon="mdi-file-move-outline"
      >
        <AppleSettingsRow
          title="启用监控 MP 整理"
          description="开启后监听整理完成事件并在本地映射目录自动生成 STRM"
        >
          <v-switch v-model="config.transfer_monitor_enabled" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="CloudDrive2 储存监控"
          description="当整理目标存储为 CloudDrive2 挂载目录时开启，支持按行配置 CD2 挂载前缀"
          :subtray-open="Boolean(config.transfer_monitor_clouddrive2_enabled) || hasCd2ConfigWhenDisabled"
        >
          <v-switch
            v-model="config.transfer_monitor_clouddrive2_enabled"
            color="info"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div v-if="config.transfer_monitor_clouddrive2_enabled" class="p115-callout p115-callout--info">
              <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
              <span>仅 CloudDrive2 储存的路径需要填写「CD2 挂载前缀」，该前缀会与该行的网盘媒体库目录拼接成最终路径。</span>
            </div>
            <div v-if="hasCd2ConfigWhenDisabled" class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-circle-outline" class="mt-0.5 flex-shrink-0" />
              <span>CloudDrive2 储存监控已关闭，但「监控MP整理」目录配置中仍存在 CD2 挂载前缀，请检查配置。</span>
            </div>
          </template>
        </AppleSettingsRow>

        <AppleSettingsRow
          title="STRM 自动刮削"
          description="STRM 生成后自动调用 MoviePilot 元数据刮削流程"
        >
          <v-switch
            v-model="config.transfer_monitor_scrape_metadata_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.transfer_monitor_scrape_metadata_enabled"
          title="刮削排除目录"
          description="此处添加的本地目录在 STRM 生成后不会自动触发刮削"
          vertical
        >
          <div class="d-flex flex-column gap-2">
            <div
              v-for="(item, index) in transferExcludePaths"
              :key="`transfer-exclude-${index}`"
              class="d-flex align-center gap-2"
            >
              <v-text-field
                v-model="item.path"
                placeholder="点击下方按钮选择需要排除自动刮削的本地目录"
                density="compact"
                variant="outlined"
                readonly
                hide-details
                class="flex-grow-1"
              >
                <template #prepend-inner>
                  <v-icon size="16" color="primary" icon="mdi-folder-outline" />
                </template>
              </v-text-field>
              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger"
                :disabled="!item.path"
                title="移除排除目录"
                @click="removeExcludePathEntry(index, 'transfer_exclude')"
              >
                <v-icon size="16" icon="mdi-trash-can-outline" />
              </button>
            </div>
            <div>
              <button
                type="button"
                class="p115-btn p115-btn--tonal p115-btn--sm"
                @click="openExcludeDirSelector('transfer_monitor_scrape_metadata_exclude_paths')"
              >
                <v-icon size="15" icon="mdi-folder-plus-outline" />
                <span>添加刮削排除目录</span>
              </button>
            </div>
          </div>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="媒体服务器刷新与信息提取"
        subtitle="入库后通知 Emby / Jellyfin / Plex 刷新并提取媒体流信息"
        icon="mdi-television-play"
      >
        <AppleSettingsRow title="媒体服务器刷新" description="生成 STRM 后通知选定的媒体服务器局部刷新">
          <v-switch
            v-model="config.transfer_monitor_media_server_refresh_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体库延迟刷新 (秒)"
          description="0 表示不延迟，立即刷新"
          wide-control
        >
          <v-text-field
            v-model.number="config.transfer_monitor_media_server_refresh_delay"
            type="number"
            min="0"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体服务器" description="选择需要联动的媒体服务器实例" wide-control>
          <v-select
            v-model="config.transfer_monitor_mediaservers"
            :items="mediaservers"
            label="选择媒体服务器"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="Emby 媒体信息提取"
          description="自动触发 Emby 探测 STRM 视频编码与分辨率元数据"
          :subtray-open="Boolean(config.transfer_monitor_emby_mediainfo_enabled && !config.native_emby_mediainfo_enabled)"
        >
          <v-switch
            v-model="config.transfer_monitor_emby_mediainfo_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-circle-outline" class="mt-0.5 flex-shrink-0" />
              <span>
                此功能需配合<strong>神医助手PRO</strong>使用，请确保神医助手PRO版本为 <strong>v3.0.0.40</strong> 及以上。
              </span>
            </div>
          </template>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="重新整理失效清理"
        subtitle="当整理方式为「移动」且源路径已在媒体库内时，自动清理源路径对应的旧失效 STRM 文件"
        icon="mdi-recycle"
      >
        <AppleSettingsRow
          title="清理失效 STRM"
          description="重新整理移动后清理源位置的旧 .strm 文件"
        >
          <v-switch
            v-model="config.transfer_monitor_remove_stale_strm"
            color="error"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <template v-if="config.transfer_monitor_remove_stale_strm">
          <AppleSettingsRow
            title="清理无效 STRM 空目录"
            description="移除旧 STRM 后若其父目录已为空则一并清理"
          >
            <v-switch
              v-model="config.transfer_monitor_remove_stale_strm_dir"
              color="error"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="清理无效 STRM 关联媒体信息文件"
            description="同步清理旧 STRM 同目录下的同名 NFO、字幕、海报等关联文件"
          >
            <v-switch
              v-model="config.transfer_monitor_remove_stale_strm_file"
              color="error"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="监控目录映射"
        subtitle="本地 STRM 生成路径 ↔ 网盘媒体库路径"
        icon="mdi-folder-swap-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="transfer"
          :items="transferPaths"
          :show-cd2-prefix="Boolean(config.transfer_monitor_clouddrive2_enabled)"
          add-label="添加监控路径映射"
          @add="addPath('transfer')"
          @remove="(i) => removePath(i, 'transfer')"
          @browse-local="(i) => openDirSelector(i, 'local', 'transfer')"
          @browse-remote="(i) => openDirSelector(i, 'remote', 'transfer')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• <strong>本地STRM目录：</strong>本地 STRM 文件生成路径</div>
            <div>• <strong>网盘媒体库目录：</strong>需要生成本地 STRM 文件的网盘媒体库路径</div>
            <div v-if="config.transfer_monitor_clouddrive2_enabled">
              • <strong>CD2 挂载前缀：</strong>仅 CloudDrive2 储存时填写，将与此行网盘路径拼接
            </div>
          </div>
        </div>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="MoviePilot 与媒体服务器目录转换 (可选)"
        subtitle="映射路径一致时可留空省略"
        icon="mdi-swap-horizontal-circle-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="transfer-mp"
          :items="transferMpPaths"
          local-label="媒体库服务器映射目录"
          local-placeholder="/media/strm"
          local-icon="mdi-television-play"
          remote-label="MP映射目录"
          remote-placeholder="/mnt/strm"
          remote-icon="mdi-folder-home-outline"
          :allow-local-browse="false"
          :allow-remote-browse="false"
          add-label="添加目录转换规则"
          @add="addPath('mp')"
          @remove="(i) => removePath(i, 'mp')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• 媒体服务器映射路径和 MP 映射路径不一样时请配置此项，如果不配置则无法正常刷新或 Emby 提取媒体信息。</div>
            <div>• 当映射路径一样时可省略此配置。</div>
          </div>
        </div>
      </AppleSettingsGroup>
    </div>

    <!-- ===================================================================
         2. 全量同步 (tab-sync)
         =================================================================== -->
    <div v-else-if="strmSubTab === 'tab-sync'" class="p115-section-stack">
      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <strong>功能说明：</strong>全量扫描配置的网盘目录，并在对应的本地目录生成 STRM 文件。
        </div>
      </div>

      <AppleSettingsGroup
        title="全量同步计划与生成策略"
        subtitle="定时周期、覆盖规则与附属媒体数据下载"
        icon="mdi-sync"
      >
        <AppleSettingsRow title="定期全量同步" description="按设定的 Cron 表达式定时自动执行全量扫描">
          <v-switch v-model="config.timing_full_sync_strm" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="运行全量同步周期" description="设置全量同步的定时执行周期" wide-control>
          <VCronField
            v-model="config.cron_full_sync_strm"
            label="运行全量同步周期"
            density="compact"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="覆盖模式" description="当本地同名 STRM 已存在时的处理方式" wide-control>
          <v-select
            v-model="config.full_sync_overwrite_mode"
            :items="[
              { title: '总是', value: 'always' },
              { title: '从不', value: 'never' },
            ]"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="下载媒体数据文件" description="同步期间自动下载网盘目录内的字幕等附属文件">
          <v-switch
            v-model="config.full_sync_auto_download_mediainfo_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="STRM 最小文件大小"
          description="小于此值的文件将不生成 STRM (支持单位 K, M, G)"
          wide-control
        >
          <v-text-field
            v-model="fullSyncMinFileSizeFormattedRef"
            placeholder="例如: 100M (可为空)"
            density="compact"
            variant="outlined"
            clearable
            hide-details
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="失效 STRM 清理与二次验证"
        subtitle="清理网盘已不存在的本地残留文件，支持二次人工确认保护"
        icon="mdi-broom"
      >
        <AppleSettingsRow
          title="清理失效 STRM 文件"
          description="扫描完成后清理网盘对应路径已不存在的本地 STRM"
        >
          <v-switch v-model="config.full_sync_remove_unless_strm" color="warning" density="compact" hide-details inset />
        </AppleSettingsRow>

        <template v-if="config.full_sync_remove_unless_strm">
          <AppleSettingsRow
            title="清理无效 STRM 目录"
            description="移除失效 STRM 后同步清理变为空目录的本地文件夹"
          >
            <v-switch
              v-model="config.full_sync_remove_unless_dir"
              color="warning"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="清理无效 STRM 文件关联的媒体信息文件"
            description="同步清理同目录下的同名 NFO、字幕与海报等附属文件"
          >
            <v-switch
              v-model="config.full_sync_remove_unless_file"
              color="warning"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="清理失效 STRM 二次验证"
            description="选择验证模式后待删文件先入队，确认后再执行物理删除"
            wide-control
          >
            <v-select
              v-model="config.full_sync_cleanup_confirm_mode"
              :items="[
                { title: '无（通过稳定性检查后立即删除）', value: 'none' },
                { title: '插件界面确认', value: 'plugin_ui' },
                { title: 'Telegram 通知按钮确认', value: 'telegram' },
              ]"
              density="compact"
              variant="outlined"
              hide-details
            />
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="媒体库全局刷新"
        subtitle="全量同步完成后刷新整个媒体服务器（谨慎开启）"
        icon="mdi-refresh-circle"
      >
        <AppleSettingsRow
          title="全量同步后刷新媒体库"
          description="完成后触发所选媒体服务器全库扫描"
          :subtray-open="Boolean(config.full_sync_media_server_refresh_enabled)"
        >
          <v-switch
            v-model="config.full_sync_media_server_refresh_enabled"
            color="error"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div class="p115-callout p115-callout--warn">
              <v-icon size="18" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
              <div>
                <strong>重要警告：</strong>启用此功能后，全量同步完成后将自动刷新整个媒体库。此操作会扫描所有媒体文件，可能导致媒体服务器负载增加，请确保您已了解此风险并自行承担相应责任。
              </div>
            </div>
          </template>
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体库延迟刷新 (秒)" description="0 表示不延迟" wide-control>
          <v-text-field
            v-model.number="config.full_sync_media_server_refresh_delay"
            type="number"
            min="0"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体服务器"
          description="全量同步完成后将刷新整个媒体库，请谨慎使用"
          wide-control
        >
          <v-select
            v-model="config.full_sync_mediaservers"
            :items="mediaservers"
            label="选择媒体服务器"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
            :disabled="!config.full_sync_media_server_refresh_enabled"
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="全量同步目录映射"
        subtitle="支持逐行独立开启/关闭该目录是否参与全量同步"
        icon="mdi-folder-sync-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="fullsync"
          :items="fullSyncPaths"
          :show-enabled-toggle="true"
          add-label="添加全量同步路径"
          @add="addPath('fullSync')"
          @remove="(i) => removePath(i, 'fullSync')"
          @browse-local="(i) => openDirSelector(i, 'local', 'fullSync')"
          @browse-remote="(i) => openDirSelector(i, 'remote', 'fullSync')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• <strong>同步图标按钮：</strong>开启时该目录参与全量同步，关闭则不参与（机器人命令按路径执行不受影响）</div>
            <div>• <strong>本地STRM目录：</strong>本地 STRM 文件生成路径</div>
            <div>• <strong>网盘媒体库目录：</strong>需要生成本地 STRM 文件的网盘媒体库路径</div>
          </div>
        </div>
      </AppleSettingsGroup>

      <div class="p115-disclosure-bezel">
        <details class="p115-disclosure">
          <summary>
            <span class="p115-disclosure-icon">
              <v-icon size="16" icon="mdi-tune-variant" />
            </span>
            <span class="p115-disclosure-meta">
              <span class="p115-disclosure-title">高级配置</span>
              <span class="p115-disclosure-sub">Rust 引擎、迭代函数、并发进程数与删除数据稳定性阈值</span>
            </span>
          </summary>
          <div class="p115-disclosure-body">
            <AppleSettingsRow
              title="输出 STRM 同步日志"
              description="在同步运行日志中输出逐条 STRM 文件处理明细"
            >
              <v-switch v-model="config.full_sync_strm_log" color="primary" density="compact" hide-details inset />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="Rust 模式处理数据"
              description="使用高性能 Rust 扩展模块加速大规模文件列表过滤与路径比对"
            >
              <v-switch v-model="config.full_sync_process_rust" color="primary" density="compact" hide-details inset />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="迭代函数"
              description="选择遍历 115 目录树的底层 API 函数"
              wide-control
            >
              <v-select
                v-model="config.full_sync_iter_function"
                :items="[
                  { title: 'iter_files_with_path_skim', value: 'iter_files_with_path_skim' },
                  { title: 'iter_files_with_path', value: 'iter_files_with_path' },
                ]"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="全量同步批处理数量"
              description="每次批量处理的文件与目录条目数量"
              wide-control
            >
              <v-text-field
                v-model.number="config.full_sync_batch_num"
                type="number"
                suffix="条"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="全量同步生成进程数"
              description="同时并发执行同步任务的进程/协程数量"
              wide-control
            >
              <v-text-field
                v-model.number="config.full_sync_process_num"
                type="number"
                suffix="个"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="清理无效 STRM 最大删除比例阈值"
              description="当待删除文件数占本地文件总数的百分比超过此值时，将进入数据稳定性检查（默认 10%）"
              wide-control
            >
              <v-text-field
                v-model.number="config.full_sync_remove_unless_max_threshold"
                type="number"
                suffix="%"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="清理数据稳定性检查阈值"
              description="数据稳定性检查的变异系数阈值，低于此值表示删除数据稳定可执行操作（默认 5%）"
              wide-control
            >
              <v-text-field
                v-model.number="config.full_sync_remove_unless_stable_threshold"
                type="number"
                suffix="%"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>
          </div>
        </details>
      </div>
    </div>

    <!-- ===================================================================
         3. 增量同步 (tab-increment-sync)
         =================================================================== -->
    <div v-else-if="strmSubTab === 'tab-increment-sync'" class="p115-section-stack">
      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <strong>功能说明：</strong>增量扫描配置的网盘目录，并在对应的本地目录生成 STRM 文件。
        </div>
      </div>

      <AppleSettingsGroup
        title="增量同步计划与刮削"
        subtitle="轻量周期增量对比目录树"
        icon="mdi-book-sync-outline"
      >
        <AppleSettingsRow title="启用增量同步" description="开启后按设定周期运行增量目录扫描">
          <v-switch v-model="config.increment_sync_strm_enabled" color="warning" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="运行增量同步周期" description="设置增量同步的执行周期" wide-control>
          <VCronField v-model="config.increment_sync_cron" label="运行增量同步周期" density="compact" hide-details />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="STRM 最小文件大小"
          description="小于此值的文件将不生成 STRM (单位 K, M, G)"
          wide-control
        >
          <v-text-field
            v-model="incrementSyncMinFileSizeFormattedRef"
            placeholder="例如: 100M (可为空)"
            density="compact"
            variant="outlined"
            clearable
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="下载媒体数据文件" description="增量发现新文件时自动下载附属媒体数据文件">
          <v-switch
            v-model="config.increment_sync_auto_download_mediainfo_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="STRM 自动刮削"
          description="新增 STRM 生成后自动触发元数据刮削"
        >
          <v-switch
            v-model="config.increment_sync_scrape_metadata_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.increment_sync_scrape_metadata_enabled"
          title="刮削排除目录"
          description="此处添加的本地目录在 STRM 生成后不会自动触发刮削"
          vertical
        >
          <div class="d-flex flex-column gap-2">
            <div
              v-for="(item, index) in incrementSyncExcludePaths"
              :key="`inc-exclude-${index}`"
              class="d-flex align-center gap-2"
            >
              <v-text-field
                v-model="item.path"
                placeholder="点击下方按钮选择需要排除自动刮削的本地目录"
                density="compact"
                variant="outlined"
                readonly
                hide-details
                class="flex-grow-1"
              >
                <template #prepend-inner>
                  <v-icon size="16" color="primary" icon="mdi-folder-outline" />
                </template>
              </v-text-field>
              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger"
                :disabled="!item.path"
                title="移除排除目录"
                @click="removeExcludePathEntry(index, 'increment_exclude')"
              >
                <v-icon size="16" icon="mdi-trash-can-outline" />
              </button>
            </div>
            <div>
              <button
                type="button"
                class="p115-btn p115-btn--tonal p115-btn--sm"
                @click="openExcludeDirSelector('increment_sync_scrape_metadata_exclude_paths')"
              >
                <v-icon size="15" icon="mdi-folder-plus-outline" />
                <span>添加刮削排除目录</span>
              </button>
            </div>
          </div>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="媒体服务器联动与失效清理"
        subtitle="增量入库刷新、Emby 提取与失效文件清理"
        icon="mdi-television-play"
      >
        <AppleSettingsRow title="媒体服务器刷新" description="增量同步产生更新后通知媒体服务器">
          <v-switch
            v-model="config.increment_sync_media_server_refresh_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体库延迟刷新 (秒)" description="0 表示不延迟" wide-control>
          <v-text-field
            v-model.number="config.increment_sync_media_server_refresh_delay"
            type="number"
            min="0"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体服务器" description="选择联动刷新的媒体服务器" wide-control>
          <v-select
            v-model="config.increment_sync_mediaservers"
            :items="mediaservers"
            label="选择媒体服务器"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="Emby 媒体信息提取"
          description="提取增量新增 STRM 的媒体编码信息"
          :subtray-open="Boolean(config.increment_sync_emby_mediainfo_enabled && !config.native_emby_mediainfo_enabled)"
        >
          <v-switch
            v-model="config.increment_sync_emby_mediainfo_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-circle-outline" class="mt-0.5 flex-shrink-0" />
              <span>
                此功能需配合<strong>神医助手PRO</strong>使用，请确保神医助手PRO版本为 <strong>v3.0.0.40</strong> 及以上。
              </span>
            </div>
          </template>
        </AppleSettingsRow>

        <AppleSettingsRow
          title="清理失效 STRM 文件"
          description="自动移除增量比对中网盘已删除的本地残留 STRM"
        >
          <v-switch
            v-model="config.increment_sync_remove_unless_strm"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <template v-if="config.increment_sync_remove_unless_strm">
          <AppleSettingsRow
            title="清理无效 STRM 目录"
            description="移除失效 STRM 后同步清理变为空目录的本地文件夹"
          >
            <v-switch
              v-model="config.increment_sync_remove_unless_dir"
              color="warning"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="清理无效 STRM 文件关联的媒体信息文件"
            description="同步清理同目录下的同名 NFO、字幕与海报等附属文件"
          >
            <v-switch
              v-model="config.increment_sync_remove_unless_file"
              color="warning"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>

      <AppleSettingsGroup title="增量同步目录映射" icon="mdi-folder-sync-outline" padded>
        <PathMappingComposer
          mode="dual"
          key-prefix="incsync"
          :items="incrementSyncPaths"
          add-label="添加增量同步路径"
          @add="addPath('incrementSync')"
          @remove="(i) => removePath(i, 'incrementSync')"
          @browse-local="(i) => openDirSelector(i, 'local', 'incrementSync')"
          @browse-remote="(i) => openDirSelector(i, 'remote', 'incrementSync')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• <strong>本地STRM目录：</strong>本地 STRM 文件生成路径</div>
            <div>• <strong>网盘媒体库目录：</strong>需要生成本地 STRM 文件的网盘媒体库路径</div>
          </div>
        </div>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="MoviePilot 与媒体服务器目录转换 (可选)"
        subtitle="映射路径一致时可省略"
        icon="mdi-swap-horizontal-circle-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="incsync-mp"
          :items="incrementSyncMPPaths"
          local-label="媒体库服务器映射目录"
          remote-label="MP映射目录"
          :allow-local-browse="false"
          :allow-remote-browse="false"
          add-label="添加目录转换规则"
          @add="addPath('increment-mp')"
          @remove="(i) => removePath(i, 'increment-mp')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• 媒体服务器映射路径和 MP 映射路径不一样时请配置此项，如果不配置则无法正常刷新或 Emby 提取媒体信息。</div>
            <div>• 当映射路径一样时可省略此配置。</div>
          </div>
        </div>
      </AppleSettingsGroup>

      <div class="p115-disclosure-bezel">
        <details class="p115-disclosure">
          <summary>
            <span class="p115-disclosure-icon">
              <v-icon size="16" icon="mdi-tune-variant" />
            </span>
            <span class="p115-disclosure-meta">
              <span class="p115-disclosure-title">高级配置</span>
              <span class="p115-disclosure-sub">二级目录树扫描、目录树导出超时与删除稳定性阈值</span>
            </span>
          </summary>
          <div class="p115-disclosure-body">
            <AppleSettingsRow
              title="扫描二级目录生成目录树"
              description="以网盘路径下的二级子目录为单位生成目录树（每个配置路径下仅允许包含子文件夹、不得直接包含文件，且二级目录不超过 100 个）"
            >
              <v-switch
                v-model="config.increment_sync_second_level_dir_scan"
                color="primary"
                density="compact"
                hide-details
                inset
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="目录树导出超时"
              description="115 云端导出目录树任务的最大等待时间；0 表示不限制"
              wide-control
            >
              <v-text-field
                v-model.number="config.increment_sync_itertree_timeout_seconds"
                type="number"
                min="0"
                hide-spin-buttons
                suffix="秒"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <template v-if="config.increment_sync_remove_unless_strm">
              <AppleSettingsRow
                title="清理无效 STRM 最大删除比例阈值"
                description="待删除文件数占本地文件总数的百分比超过此值时，将进入数据稳定性检查（默认 10%）"
                wide-control
              >
                <v-text-field
                  v-model.number="config.increment_sync_remove_unless_max_threshold"
                  type="number"
                  suffix="%"
                  density="compact"
                  variant="outlined"
                  hide-details
                />
              </AppleSettingsRow>

              <AppleSettingsRow
                title="清理数据稳定性检查阈值"
                description="数据稳定性检查的变异系数阈值，低于此值表示删除数据稳定可执行操作（默认 5%）"
                wide-control
              >
                <v-text-field
                  v-model.number="config.increment_sync_remove_unless_stable_threshold"
                  type="number"
                  suffix="%"
                  density="compact"
                  variant="outlined"
                  hide-details
                />
              </AppleSettingsRow>
            </template>
          </div>
        </details>
      </div>
    </div>

    <!-- ===================================================================
         4. 监控 115 生活事件 (tab-life)
         =================================================================== -->
    <div v-else-if="strmSubTab === 'tab-life'" class="p115-section-stack">
      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <strong>功能说明：</strong>监控 115 生活（上传、移动、接收文件、删除、复制、重命名）事件，自动在本地对应目录生成 STRM 文件或者删除 STRM 文件。
        </div>
      </div>

      <AppleSettingsGroup
        title="生活事件监控与基础响应"
        subtitle="实时拉取 115 账号操作流并同步到本地"
        icon="mdi-calendar-heart"
      >
        <AppleSettingsRow title="启用生活事件监控" description="持续监听 115 账号生活事件流">
          <v-switch v-model="config.monitor_life_enabled" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="处理事件类型" description="选择需要响应的 115 生活事件类别" wide-control>
          <v-select
            v-model="config.monitor_life_event_modes"
            :items="[
              { title: '新增事件', value: 'creata' },
              { title: '删除事件', value: 'remove' },
              { title: '重命名事件', value: 'rename' },
              { title: '网盘整理', value: 'transfer' },
            ]"
            label="选择事件类型"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="同步删除历史记录"
          description="当删除事件移除本地 STRM 时同步清理 MoviePilot 整理历史记录"
        >
          <v-switch
            v-model="config.monitor_life_remove_mp_history"
            color="warning"
            density="compact"
            hide-details
            inset
            :disabled="config.monitor_life_remove_mp_source"
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="同步删除源文件"
          description="删除事件发生时连同整理记录关联源文件一并处理（开启时将自动开启同步删除历史记录）"
        >
          <v-switch
            v-model="config.monitor_life_remove_mp_source"
            color="warning"
            density="compact"
            hide-details
            inset
            @update:model-value="(val) => { if (val) config.monitor_life_remove_mp_history = true; }"
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="重命名事件时同步重命名 STRM 关联文件"
          description="改名时自动同步修改同目录下的 NFO、字幕、海报等同名关联文件"
        >
          <v-switch
            v-model="config.monitor_life_rename_auto_related_files"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <!-- Real-Time Move Strategy Matrix Card -->
      <AppleSettingsGroup
        title="移动事件处理策略与实时动作矩阵"
        subtitle="实时计算「源目录 → 目标目录」处理动作（源目录类型以数据库可识别路径为准）"
        icon="mdi-routes"
      >
        <AppleSettingsRow title="媒体目录内移动模式" description="控制媒体目录之间移动文件时的 STRM 同步方式" wide-control>
          <v-select
            v-model="config.monitor_life_move_media_mode"
            :items="[
              { title: '删除/重建（recreate）', value: 'recreate' },
              { title: '纯本地迁移（local_move）', value: 'local_move' },
            ]"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体 -> 其它目录 时删除本地 STRM">
          <v-switch
            v-model="config.monitor_life_move_out_media_remove_local_strm"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体 -> 待整理 时删除本地 STRM">
          <v-switch
            v-model="config.monitor_life_move_media_to_transfer_remove_local_strm"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <template v-if="config.monitor_life_move_media_mode === 'recreate'">
          <AppleSettingsRow title="媒体 -> 媒体 时保留旧 STRM">
            <v-switch
              v-model="config.monitor_life_move_media_keep_old_strm"
              color="primary"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>
          <AppleSettingsRow title="媒体 -> 媒体 时生成新 STRM">
            <v-switch
              v-model="config.monitor_life_move_media_create_new_strm"
              color="primary"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>
        </template>

        <AppleSettingsRow
          v-if="config.monitor_life_move_media_mode === 'local_move'"
          title="local_move 时迁移 STRM 关联文件"
        >
          <v-switch
            v-model="config.monitor_life_move_media_local_move_related_files"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="实时移动策略预览表"
          description="下表根据你当前配置实时生成，展示“源目录 -> 目标目录”的实际处理动作"
          vertical
        >
          <div class="p115-table-scroll">
            <table class="p115-native-table">
              <thead>
                <tr>
                  <th>源目录</th>
                  <th>目标目录</th>
                  <th>当前处理动作（实时）</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in lifeMoveMatrixRows" :key="`${item.source}-${item.target}`">
                  <td><span class="p115-badge p115-badge--blue">{{ item.sourceLabel }}</span></td>
                  <td><span class="p115-badge p115-badge--pink">{{ item.targetLabel }}</span></td>
                  <td>{{ item.action }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="媒体服务器、刮削与附属下载"
        icon="mdi-television-play"
      >
        <AppleSettingsRow title="媒体服务器刷新">
          <v-switch
            v-model="config.monitor_life_media_server_refresh_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体库延迟刷新 (秒)" description="0 表示不延迟" wide-control>
          <v-text-field
            v-model.number="config.monitor_life_media_server_refresh_delay"
            type="number"
            min="0"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体服务器" wide-control>
          <v-select
            v-model="config.monitor_life_mediaservers"
            :items="mediaservers"
            label="选择媒体服务器"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="Emby 媒体信息提取"
          :subtray-open="Boolean(config.monitor_life_emby_mediainfo_enabled && !config.native_emby_mediainfo_enabled)"
        >
          <v-switch
            v-model="config.monitor_life_emby_mediainfo_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-circle-outline" class="mt-0.5 flex-shrink-0" />
              <span>
                此功能需配合<strong>神医助手PRO</strong>使用，请确保神医助手PRO版本为 <strong>v3.0.0.40</strong> 及以上。
              </span>
            </div>
          </template>
        </AppleSettingsRow>

        <AppleSettingsRow title="下载媒体数据文件">
          <v-switch
            v-model="config.monitor_life_auto_download_mediainfo_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="STRM 最小文件大小"
          description="小于此值的文件将不生成 STRM (单位 K, M, G)"
          wide-control
        >
          <v-text-field
            v-model="monitorLifeMinFileSizeFormattedRef"
            placeholder="例如: 100M (可为空)"
            density="compact"
            variant="outlined"
            clearable
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="STRM 自动刮削">
          <v-switch
            v-model="config.monitor_life_scrape_metadata_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.monitor_life_scrape_metadata_enabled"
          title="刮削排除目录"
          description="此处添加的本地目录，在 115 生活事件监控生成 STRM 后将不会自动触发刮削"
          vertical
        >
          <div class="d-flex flex-column gap-2">
            <div
              v-for="(item, index) in monitorLifeExcludePaths"
              :key="`life-exclude-${index}`"
              class="d-flex align-center gap-2"
            >
              <v-text-field
                v-model="item.path"
                placeholder="点击下方按钮选择需要排除自动刮削的本地目录"
                density="compact"
                variant="outlined"
                readonly
                hide-details
                class="flex-grow-1"
              >
                <template #prepend-inner>
                  <v-icon size="16" color="primary" icon="mdi-folder-outline" />
                </template>
              </v-text-field>
              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger"
                :disabled="!item.path"
                title="移除排除目录"
                @click="removeExcludePathEntry(index, 'life_exclude')"
              >
                <v-icon size="16" icon="mdi-trash-can-outline" />
              </button>
            </div>
            <div>
              <button
                type="button"
                class="p115-btn p115-btn--tonal p115-btn--sm"
                @click="openExcludeDirSelector('monitor_life_scrape_metadata_exclude_paths')"
              >
                <v-icon size="15" icon="mdi-folder-plus-outline" />
                <span>添加刮削排除目录</span>
              </button>
            </div>
          </div>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup title="生活事件监控目录映射" icon="mdi-folder-heart-outline" padded>
        <PathMappingComposer
          mode="dual"
          key-prefix="life"
          :items="monitorLifePaths"
          add-label="添加监控路径"
          @add="addPath('monitorLife')"
          @remove="(i) => removePath(i, 'monitorLife')"
          @browse-local="(i) => openDirSelector(i, 'local', 'monitorLife')"
          @browse-remote="(i) => openDirSelector(i, 'remote', 'monitorLife')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• <strong>本地STRM目录：</strong>本地 STRM 文件生成路径</div>
            <div>• <strong>网盘媒体库目录：</strong>需要生成本地 STRM 文件的网盘媒体库路径</div>
          </div>
        </div>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="MoviePilot 与媒体服务器目录转换 (可选)"
        subtitle="映射路径一致时可省略"
        icon="mdi-swap-horizontal-circle-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="life-mp"
          :items="monitorLifeMpPaths"
          local-label="媒体库服务器映射目录"
          remote-label="MP映射目录"
          :allow-local-browse="false"
          :allow-remote-browse="false"
          add-label="添加目录转换规则"
          @add="addPath('monitorLifeMp')"
          @remove="(i) => removePath(i, 'monitorLifeMp')"
        />
        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• 媒体服务器映射路径和 MP 映射路径不一样时请配置此项，如果不配置则无法正常刷新或 Emby 提取媒体信息。</div>
            <div>• 当映射路径一样时可省略此配置。</div>
          </div>
        </div>
      </AppleSettingsGroup>

      <AppleSettingsGroup title="高级配置与在线诊断" icon="mdi-bug-check-outline">
        <AppleSettingsRow
          title="整理无进展超时 (分钟)"
          description="队列持续无变化达到时限后记录残留任务并恢复监控"
          wide-control
        >
          <v-text-field
            v-model.number="config.monitor_life_transfer_stall_timeout_minutes"
            type="number"
            min="1"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="115 生活事件故障检查"
          description="检查 115 生活事件进程状态，测试数据拉取功能，并提供详细的调试信息"
        >
          <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="checkLifeEventStatus">
            <v-icon size="15" icon="mdi-bug-check-outline" />
            <span>故障检查</span>
          </button>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <!-- Reference Tables in Progressive Disclosure Drawers -->
      <details class="p115-guide-details">
        <summary>
          <v-icon size="16" icon="mdi-table-eye" />
          <span>事件处理逻辑与当前配置对照表</span>
        </summary>
        <div class="p115-guide-body">
          <div class="p115-table-scroll">
            <table class="p115-native-table p115-native-table--wide">
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
                  <td class="p115-tabular font-weight-medium">{{ item.types }}</td>
                  <td><strong class="p115-mono">{{ item.events }}</strong></td>
                  <td>
                    <span
                      v-if="item.mode"
                      class="p115-badge"
                      :class="isLifeModeEnabled(item.mode) ? 'p115-badge--green' : 'p115-badge--neutral'"
                    >
                      <span class="p115-badge-dot" />
                      {{ item.modeLabel }} · {{ isLifeModeEnabled(item.mode) ? '已启用' : '未启用' }}
                    </span>
                    <span v-else class="opacity-70">{{ item.modeLabel }}</span>
                  </td>
                  <td>{{ item.action }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="p115-callout p115-callout--info mt-3">
            <v-icon size="16" color="primary" icon="mdi-database-outline" class="mt-0.5 flex-shrink-0" />
            <span>所有拉取到的事件都会先保存到生活事件数据库；未接入的事件只留档，不操作文件数据库或本地文件。</span>
          </div>
        </div>
      </details>

      <details class="p115-guide-details">
        <summary>
          <v-icon size="16" icon="mdi-shield-check-outline" />
          <span>路径判断、文件类型与安全边界规则表</span>
        </summary>
        <div class="p115-guide-body">
          <div class="p115-table-scroll">
            <table class="p115-native-table p115-native-table--wide">
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
            </table>
          </div>
          <div class="p115-callout p115-callout--warn mt-3">
            <v-icon size="16" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
            <span>
              文件 type 24 已支持 115 将“移动 + 重命名”合并上报；文件夹 type 20 仍只支持同父目录改名。文件夹改名或移动不会逐个校验内部 STRM 内容，依赖路径型 URL 时需留意旧 file_path。
            </span>
          </div>
        </div>
      </details>

      <div class="p115-callout p115-callout--warn">
        <v-icon size="18" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
        <span>注意：当 MoviePilot 主程序运行整理任务时 115生活事件 监控会自动暂停，整理运行完成后会继续监控。</span>
      </div>
    </div>

    <!-- ===================================================================
         5. API STRM 生成 (tab-api-strm)
         =================================================================== -->
    <div v-else-if="strmSubTab === 'tab-api-strm'" class="p115-section-stack">
      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-api" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="mb-1">
            <strong>功能说明：</strong>API STRM 生成功能允许第三方开发者通过 HTTP API 调用，批量生成 STRM 文件。
          </div>
          <div>
            详细 API 文档请参考：
            <a
              href="https://github.com/DDSRem-Dev/MoviePilot-Plugins/blob/main/docs/p115strmhelper/API_STRM生成功能文档.md"
              target="_blank"
              rel="noopener noreferrer"
              class="p115-ext-link"
            >
              GitHub 文档链接
            </a>
          </div>
        </div>
      </div>

      <AppleSettingsGroup title="API 生成后处理设置" icon="mdi-cog-sync-outline">
        <AppleSettingsRow title="STRM 自动刮削" description="API 写入 STRM 后自动触发元数据刮削">
          <v-switch
            v-model="config.api_strm_scrape_metadata_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体服务器刷新" description="API 生成完成后刷新指定的媒体服务器">
          <v-switch
            v-model="config.api_strm_media_server_refresh_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体库延迟刷新 (秒)" description="0 表示不延迟" wide-control>
          <v-text-field
            v-model.number="config.api_strm_media_server_refresh_delay"
            type="number"
            min="0"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="媒体服务器" wide-control>
          <v-select
            v-model="config.api_strm_mediaservers"
            :items="mediaservers"
            label="选择媒体服务器"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="路径映射配置"
        subtitle="当 API 请求中未指定 local_path 时，系统会根据此配置自动匹配路径"
        icon="mdi-folder-swap-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="api-strm"
          :items="apiStrmPaths"
          add-label="添加 API 路径映射"
          @add="addPath('apiStrm')"
          @remove="(i) => removePath(i, 'apiStrm')"
          @browse-local="(i) => openDirSelector(i, 'local', 'apiStrm')"
          @browse-remote="(i) => openDirSelector(i, 'remote', 'apiStrm')"
        />
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="MoviePilot 与媒体库目录转换 (可选)"
        subtitle="媒体服务器映射路径和 MP 映射路径不一样时请配置此项，否则无法正常刷新或 Emby 提取媒体信息"
        icon="mdi-swap-horizontal-circle-outline"
        padded
      >
        <PathMappingComposer
          mode="dual"
          key-prefix="api-strm-mp"
          :items="apiStrmMPPaths"
          local-label="媒体库服务器映射目录"
          remote-label="MP映射目录"
          :allow-local-browse="false"
          :allow-remote-browse="false"
          add-label="添加目录转换规则"
          @add="addPath('apiStrm-mp')"
          @remove="(i) => removePath(i, 'apiStrm-mp')"
        />
      </AppleSettingsGroup>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, inject } from 'vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import AppleSettingsRow from '../ui/AppleSettingsRow.vue';
import PathMappingComposer from '../ui/PathMappingComposer.vue';
import TransferPostprocessRecovery from '../dialogs/TransferPostprocessRecovery.vue';

const activeSubTabs = inject('activeSubTabs', null);
const fallbackSubTab = ref('tab-transfer');

const strmSubTab = computed({
  get: () => (activeSubTabs ? activeSubTabs.strm : fallbackSubTab.value),
  set: (val) => {
    if (activeSubTabs) activeSubTabs.strm = val;
    else fallbackSubTab.value = val;
  },
});

const subTabItems = [
  { value: 'tab-transfer', label: '监控MP整理', icon: 'mdi-file-move-outline' },
  { value: 'tab-sync', label: '全量同步', icon: 'mdi-sync' },
  { value: 'tab-increment-sync', label: '增量同步', icon: 'mdi-book-sync-outline' },
  { value: 'tab-life', label: '监控115生活事件', icon: 'mdi-calendar-heart' },
  { value: 'tab-api-strm', label: 'API STRM生成', icon: 'mdi-api' },
];

const config = inject('config');
const mediaservers = inject('mediaservers');
const transferPaths = inject('transferPaths');
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

const hasCd2ConfigWhenDisabled = computed(() => {
  const c = config?.value ?? config;
  if (c?.transfer_monitor_clouddrive2_enabled) return false;
  const paths = transferPaths?.value ?? transferPaths ?? [];
  return Array.isArray(paths) && paths.some((p) => String(p?.cd2Prefix ?? '').trim() !== '');
});

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
    action: '根据旧、新路径所属的媒体、待整理或其它目录执行上方实时移动矩阵；没有独立事件模式开关。',
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
.p115-section-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  max-width: 100%;
}

.p115-subnav-bar {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  padding-bottom: 2px;
}

.p115-table-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border-radius: 11px;
  border: 1px solid var(--p115-border-hairline);
  background: var(--p115-bg-inset);
}

.p115-native-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.79rem;
  line-height: 1.5;
}

.p115-native-table--wide {
  min-width: 720px;
}

.p115-native-table th {
  text-align: left;
  padding: 9px 12px;
  font-size: 0.73rem;
  font-weight: 620;
  color: var(--p115-text-secondary);
  border-bottom: 1px solid var(--p115-border-hairline);
  white-space: nowrap;
}

.p115-native-table td {
  padding: 9px 12px;
  color: var(--p115-text-primary);
  border-bottom: 1px solid var(--p115-border-hairline);
  vertical-align: top;
}

.p115-native-table tbody tr:last-child td {
  border-bottom: none;
}

.p115-ext-link {
  color: var(--p115-blue-ink);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
