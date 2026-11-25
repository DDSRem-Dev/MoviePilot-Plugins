<template>
  <v-dialog v-model="shareDialog.show" max-width="860" :content-class="dialogContentClass">
    <v-card flat class="p115-sheet p115-sheet--workspace">
      <!-- Top Header: Supports Push-Back when editing a single Share Config -->
      <div class="p115-sheet-header">
        <div class="p115-sheet-title">
          <button
            v-if="shareConfigDialog.show"
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm mr-1"
            @click="$emit('close-item-editor')"
          >
            <v-icon size="15" icon="mdi-chevron-left" />
            <span>返回列表</span>
          </button>
          <v-icon v-else icon="mdi-share-variant-outline" color="primary" size="20" />
          <span>
            {{
              shareConfigDialog.show
                ? shareConfigDialog.editingIndex >= 0
                  ? '编辑分享配置'
                  : '添加分享配置'
                : '115 网盘分享同步'
            }}
          </span>
        </div>

        <button
          type="button"
          class="p115-btn p115-btn--ghost p115-btn--icon"
          aria-label="关闭"
          @click="shareConfigDialog.show ? $emit('close-item-editor') : $emit('close')"
        >
          <v-icon size="18" icon="mdi-close" />
        </button>
      </div>

      <!-- ===================================================================
           PUSH VIEW B: Single Share Item Editor (Zero Stacked Modal!)
           =================================================================== -->
      <template v-if="shareConfigDialog.show">
        <div class="p115-sheet-body">
          <div v-if="shareConfigDialog.error" class="p115-callout p115-callout--error mb-3">
            <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
            <span>{{ shareConfigDialog.error }}</span>
          </div>

          <AppleSettingsGroup title="状态与标识">
            <AppleSettingsRow title="启用此配置" description="关闭后执行全部分享同步时将跳过此条目">
              <v-switch v-model="shareConfigDialog.enabled" color="primary" density="compact" hide-details inset />
            </AppleSettingsRow>
            <AppleSettingsRow title="备注名称" description="为此分享链接设置易读备注，方便列表中快速识别" wide-control>
              <v-text-field
                v-model="shareConfigDialog.comment"
                placeholder="例如：杜比视界电影合集"
                variant="outlined"
                density="compact"
                clearable
                hide-details
              />
            </AppleSettingsRow>
          </AppleSettingsGroup>

          <AppleSettingsGroup title="115 分享源与本地目录" class="mt-4">
            <AppleSettingsRow
              title="分享链接"
              description="完整 115 分享链接（与下方「分享码+分享密码」二选一，同时填写时优先读取分享链接）"
              vertical
            >
              <v-text-field
                v-model="shareConfigDialog.shareLink"
                placeholder="https://115.com/s/..."
                variant="outlined"
                density="compact"
                prepend-inner-icon="mdi-link"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow title="或使用分享码与访问密码" vertical>
              <v-row dense>
                <v-col cols="12" sm="6">
                  <v-text-field
                    v-model="shareConfigDialog.shareCode"
                    label="分享码"
                    variant="outlined"
                    density="compact"
                    prepend-inner-icon="mdi-key-outline"
                    hide-details
                  />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-text-field
                    v-model="shareConfigDialog.shareReceive"
                    label="分享密码"
                    type="password"
                    variant="outlined"
                    density="compact"
                    prepend-inner-icon="mdi-lock-outline"
                    hide-details
                  />
                </v-col>
              </v-row>
            </AppleSettingsRow>

            <AppleSettingsRow title="目录映射" description="分享内相对路径默认为根目录 /；本地路径为 STRM 输出目录" vertical>
              <v-row dense>
                <v-col cols="12" sm="6">
                  <v-text-field
                    v-model="shareConfigDialog.sharePath"
                    label="分享内相对路径"
                    placeholder="/"
                    variant="outlined"
                    density="compact"
                    prepend-inner-icon="mdi-folder-network-outline"
                    hide-details
                  />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-text-field
                    v-model="shareConfigDialog.localPath"
                    label="本地生成 STRM 路径"
                    variant="outlined"
                    density="compact"
                    prepend-inner-icon="mdi-folder-outline"
                    hide-details
                  >
                    <template #append-inner>
                      <button
                        type="button"
                        class="p115-btn p115-btn--tonal p115-btn--sm"
                        @click="$emit('browse-item-local')"
                      >
                        浏览
                      </button>
                    </template>
                  </v-text-field>
                </v-col>
              </v-row>
            </AppleSettingsRow>
          </AppleSettingsGroup>

          <AppleSettingsGroup title="扫描速率与后处理策略" class="mt-4">
            <AppleSettingsRow title="最小生成文件大小" description="小于此值的文件不生成 STRM（支持 K、M、G）" wide-control>
              <v-text-field
                v-model="shareConfigDialog.minFileSizeFormatted"
                placeholder="例如: 100M"
                variant="outlined"
                density="compact"
                clearable
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="迭代函数"
              :description="
                shareConfigDialog.iterFunction === 'share_iter_files'
                  ? '高速模式：仅生成 STRM，不上传共享数据'
                  : '详细数据模式：支持网盘元数据下载与共享'
              "
              wide-control
            >
              <v-select
                v-model="shareConfigDialog.iterFunction"
                :items="shareIteratorItems"
                item-title="title"
                item-value="value"
                variant="outlined"
                density="compact"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              v-if="shareConfigDialog.iterFunction === 'iter_share_files_with_path'"
              title="运行速度模式"
              description="控制 API 调用间隔，避免触发 115 风控"
              wide-control
            >
              <v-select
                v-model="shareConfigDialog.speedMode"
                :items="speedModeItems"
                item-title="title"
                item-value="value"
                variant="outlined"
                density="compact"
                hide-details
              >
                <template #item="{ props: itemProps, item }">
                  <v-list-item v-bind="itemProps" :title="item.raw.title" :subtitle="item.raw.subtitle" />
                </template>
              </v-select>
            </AppleSettingsRow>

            <AppleSettingsRow
              title="STRM 交由 MoviePilot 整理"
              description="开启后由 MP 接管重命名与入库；关闭后可单独指定下载元数据、刷新与刮削"
            >
              <v-switch v-model="shareConfigDialog.moviepilotTransfer" color="primary" density="compact" hide-details inset />
            </AppleSettingsRow>

            <AppleSettingsRow
              v-if="shareConfigDialog.moviepilotTransfer && shareConfigDialog.iterFunction === 'iter_share_files_with_path'"
              title="下载 MoviePilot 可整理的音轨与字幕"
              description="仅下载 MP 允许的音轨和字幕，保存后与 STRM 一并整理"
            >
              <v-switch
                v-model="shareConfigDialog.moviepilotTransferDownloadRmtAudioSub"
                color="primary"
                density="compact"
                hide-details
                inset
              />
            </AppleSettingsRow>

            <template v-if="!shareConfigDialog.moviepilotTransfer">
              <AppleSettingsRow
                v-if="shareConfigDialog.iterFunction === 'iter_share_files_with_path'"
                title="自动下载网盘元数据"
                description="同步下载同目录字幕、NFO 等附属媒体数据文件"
              >
                <v-switch v-model="shareConfigDialog.autoDownloadMediainfo" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <AppleSettingsRow title="刷新媒体服务器" description="生成完成后通知全局配置的媒体服务器刷新">
                <v-switch v-model="shareConfigDialog.mediaServerRefresh" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <AppleSettingsRow title="刮削元数据" description="生成完成后自动触发本地元数据刮削">
                <v-switch v-model="shareConfigDialog.scrapeMetadata" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>
            </template>
          </AppleSettingsGroup>
        </div>

        <div class="p115-sheet-footer">
          <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close-item-editor')">取消</button>
          <button
            type="button"
            class="p115-btn p115-btn--primary"
            :disabled="!isShareConfigDialogValid"
            @click="$emit('save-item')"
          >
            <v-icon size="16" icon="mdi-check" />
            <span>保存此条分享</span>
          </button>
        </div>
      </template>

      <!-- ===================================================================
           MAIN VIEW A: Segmented Share Sync Hub
           =================================================================== -->
      <template v-else>
        <div class="p115-sheet-body">
          <div v-if="shareDialog.error" class="p115-callout p115-callout--error mb-3">
            <v-icon size="18" color="error" icon="mdi-alert-circle-outline" />
            <span>{{ shareDialog.error }}</span>
          </div>

          <div class="mb-4">
            <AppleSegmentedControl v-model="activeTab" :items="hubTabs" block />
          </div>

          <!-- TAB 1: Share Configs List -->
          <div v-show="activeTab === 'list'">
            <AppleSettingsGroup title="分享配置列表" subtitle="支持多个 115 分享源批量生成 STRM">
              <template #action>
                <div class="d-flex align-center gap-2">
                  <button
                    v-if="shareDialog.configs.length > 0 && !confirmingClearAll"
                    type="button"
                    class="p115-btn p115-btn--danger p115-btn--sm"
                    @click="confirmingClearAll = true"
                  >
                    <v-icon size="14" icon="mdi-delete-sweep-outline" />
                    <span>清空</span>
                  </button>
                  <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="$emit('add-item')">
                    <v-icon size="15" icon="mdi-plus" />
                    <span>添加分享</span>
                  </button>
                </div>
              </template>

              <!-- Non-blocking Inline Clear All Confirmation -->
              <div v-if="confirmingClearAll" class="p115-callout p115-callout--error ma-3">
                <v-icon size="18" color="error" icon="mdi-alert-outline" />
                <div class="flex-grow-1">确定要清空全部 {{ shareDialog.configs.length }} 条分享配置吗？保存后生效。</div>
                <div class="d-flex gap-2">
                  <button type="button" class="p115-btn p115-btn--subtle p115-btn--sm" @click="confirmingClearAll = false">
                    取消
                  </button>
                  <button
                    type="button"
                    class="p115-btn p115-btn--danger p115-btn--sm"
                    @click="
                      shareDialog.configs.splice(0, shareDialog.configs.length);
                      confirmingClearAll = false;
                    "
                  >
                    确认清空
                  </button>
                </div>
              </div>

              <div v-if="shareDialog.configs.length === 0" class="pa-6 text-center text-body-2 opacity-70">
                暂无分享配置，请点击右上角「添加分享」创建第一条规则
              </div>

              <div v-else class="p115-inset-list">
                <div
                  v-for="(cfg, idx) in shareDialog.configs"
                  :key="idx"
                  class="p115-inset-row p115-share-item"
                >
                  <div class="p115-share-item-main">
                    <div class="d-flex align-center flex-wrap gap-2">
                      <span class="p115-badge" :class="cfg.enabled !== false ? 'p115-badge--green' : 'p115-badge--neutral'">
                        <span class="p115-badge-dot" />
                        {{ cfg.enabled !== false ? '启用' : '停用' }}
                      </span>
                      <span class="font-weight-bold text-body-2">
                        {{ cfg.comment || cfg.share_link || cfg.share_code || `分享配置 #${idx + 1}` }}
                      </span>
                      <span class="p115-badge p115-badge--blue">
                        {{ cfg.iter_function === 'iter_share_files_with_path' ? '详细迭代' : '高速简略' }}
                      </span>
                      <span v-if="cfg.moviepilot_transfer" class="p115-badge p115-badge--pink">MP 整理</span>
                    </div>

                    <div
                      v-if="cfg.comment && (cfg.share_link || cfg.share_code)"
                      class="p115-mono text-caption opacity-70 mt-1 text-truncate"
                    >
                      {{ cfg.share_link || `分享码: ${cfg.share_code}` }}
                    </div>

                    <div class="d-flex flex-wrap gap-3 text-caption opacity-80 mt-1">
                      <span class="p115-mono">📁 本地: {{ cfg.local_path || '未配置' }}</span>
                      <span v-if="cfg.share_path && cfg.share_path !== '/'" class="p115-mono">
                        ☁️ 分享路径: {{ cfg.share_path }}
                      </span>
                      <span v-if="cfg.min_file_size" class="p115-tabular">
                        最小: {{ formatBytes(cfg.min_file_size) }}
                      </span>
                      <span v-if="cfg.iter_function === 'iter_share_files_with_path' && cfg.speed_mode !== undefined">
                        速度: {{ ['最快', '快', '慢', '最慢'][cfg.speed_mode] }}
                      </span>
                    </div>
                  </div>

                  <div class="d-flex align-center gap-1 flex-shrink-0">
                    <button
                      type="button"
                      class="p115-btn p115-btn--tonal p115-btn--sm"
                      @click="$emit('edit-item', idx)"
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      class="p115-btn p115-btn--icon p115-btn--danger"
                      title="删除"
                      @click="$emit('remove-item', idx)"
                    >
                      <v-icon size="16" icon="mdi-trash-can-outline" />
                    </button>
                  </div>
                </div>
              </div>
            </AppleSettingsGroup>
          </div>

          <!-- TAB 2: Interactive Share STRM (/p115_share_strm) -->
          <div v-show="activeTab === 'interactive'">
            <div class="p115-callout p115-callout--info mb-4">
              <v-icon size="18" color="primary" icon="mdi-chat-processing-outline" />
              <div>
                <div class="font-weight-bold">交互式命令 <code class="p115-mono">/p115_share_strm</code></div>
                <div>发送 <code class="p115-mono">/p115_share_strm</code> + 115 分享链接，或直接转发资源消息，任务将加入独立队列串行执行。</div>
              </div>
            </div>

            <AppleSettingsGroup title="分享交互生成 STRM 参数">
              <AppleSettingsRow title="最小生成文件大小" description="小于此值不生成 STRM，留空不限制（如 500M、1G）" wide-control>
                <v-text-field
                  v-model="shareDialog.interactiveGenStrm.minFileSizeFormatted"
                  placeholder="留空不限制"
                  variant="outlined"
                  density="compact"
                  hide-details
                />
              </AppleSettingsRow>

              <AppleSettingsRow
                title="迭代函数"
                :description="
                  shareDialog.interactiveGenStrm.iterFunction === 'share_iter_files'
                    ? '高速，仅生成 STRM；不上传共享数据'
                    : '详细数据，支持元数据下载与共享'
                "
                wide-control
              >
                <v-select
                  v-model="shareDialog.interactiveGenStrm.iterFunction"
                  :items="shareIteratorItems"
                  item-title="title"
                  item-value="value"
                  variant="outlined"
                  density="compact"
                  hide-details
                />
              </AppleSettingsRow>

              <AppleSettingsRow
                v-if="shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path'"
                title="运行速度模式"
                wide-control
              >
                <v-select
                  v-model="shareDialog.interactiveGenStrm.speedMode"
                  :items="speedModeItems"
                  item-title="title"
                  item-value="value"
                  variant="outlined"
                  density="compact"
                  hide-details
                />
              </AppleSettingsRow>

              <AppleSettingsRow title="本地生成目录" description="交互生成 STRM 文件落盘根目录" vertical>
                <div class="d-flex align-center gap-2">
                  <v-text-field
                    v-model="shareDialog.interactiveGenStrm.localPath"
                    label="本地生成目录"
                    density="compact"
                    variant="outlined"
                    clearable
                    hide-details
                  />
                  <button
                    type="button"
                    class="p115-btn p115-btn--tonal"
                    @click="$emit('browse-interactive-dir')"
                  >
                    <v-icon size="16" icon="mdi-folder-open-outline" />
                    <span>选择目录</span>
                  </button>
                </div>
              </AppleSettingsRow>

              <AppleSettingsRow
                v-if="shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path'"
                title="自动下载网盘元数据"
                description="启用 MP 整理时由下方音轨字幕开关控制"
              >
                <v-switch
                  v-model="shareDialog.interactiveGenStrm.autoDownloadMediainfo"
                  color="primary"
                  density="compact"
                  hide-details
                  inset
                  :disabled="shareDialog.interactiveGenStrm.moviepilotTransfer"
                />
              </AppleSettingsRow>

              <AppleSettingsRow title="交由 MoviePilot 整理" description="生成后交由 MoviePilot 自动重命名与归档入库">
                <v-switch
                  v-model="shareDialog.interactiveGenStrm.moviepilotTransfer"
                  color="primary"
                  density="compact"
                  hide-details
                  inset
                />
              </AppleSettingsRow>

              <AppleSettingsRow
                v-if="
                  shareDialog.interactiveGenStrm.moviepilotTransfer &&
                  shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path'
                "
                title="下载 MoviePilot 可整理的音轨与字幕"
                description="仅下载 MoviePilot 允许的音轨和字幕，保存后与 STRM 一并整理"
              >
                <v-switch
                  v-model="shareDialog.interactiveGenStrm.moviepilotTransferDownloadRmtAudioSub"
                  color="primary"
                  density="compact"
                  hide-details
                  inset
                />
              </AppleSettingsRow>
            </AppleSettingsGroup>

            <details v-if="shareDialog.interactiveGenStrm.moviepilotTransfer" class="p115-guide-details mt-3" open>
              <summary>
                <v-icon size="16" icon="mdi-book-open-variant" />
                <span>MoviePilot 整理目录配套配置说明</span>
              </summary>
              <div class="p115-guide-body">
                <div class="mb-1">开启 MP 整理时，「本地生成目录」作为临时待整理目录，请在 MoviePilot <strong>设定 → 目录</strong> 中配置：</div>
                <div>1. 资源存储选择<strong>本地</strong>，资源目录填写本页配置的<strong>本地生成目录</strong></div>
                <div>2. 自动整理选择<strong>手动整理</strong>，媒体库存储选择<strong>本地</strong>，整理方式选择<strong>移动</strong></div>
              </div>
            </details>
          </div>

          <!-- TAB 3: Invalid Share STRM Cleanup -->
          <div v-show="activeTab === 'cleanup'">
            <div class="p115-callout p115-callout--info mb-4">
              <v-icon size="18" color="primary" icon="mdi-broom" />
              <span>仅在下方配置的本地根目录下扫描无效分享 STRM；与「分享配置列表」中的本地路径相互独立。扫描前会自动保存本页清理配置。</span>
            </div>

            <AppleSettingsGroup title="清理扫描根目录">
              <template #action>
                <div class="d-flex align-center gap-2">
                  <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="$emit('add-cleanup-path')">
                    <v-icon size="15" icon="mdi-plus" />
                    <span>添加目录</span>
                  </button>
                  <button
                    type="button"
                    class="p115-btn p115-btn--primary p115-btn--sm"
                    :disabled="cleanupScanLoading"
                    @click="$emit('run-cleanup-scan')"
                  >
                    <v-progress-circular v-if="cleanupScanLoading" indeterminate size="13" width="2" />
                    <v-icon v-else size="15" icon="mdi-play" />
                    <span>立即扫描</span>
                  </button>
                </div>
              </template>

              <div class="pa-3">
                <div v-if="shareDialog.cleanupPaths.length === 0" class="text-caption opacity-70 py-2 text-center">
                  尚未添加清理扫描根目录
                </div>
                <div
                  v-for="(_p, idx) in shareDialog.cleanupPaths"
                  :key="'cleanup-' + idx"
                  class="d-flex align-center gap-2 mb-2"
                >
                  <v-text-field
                    v-model="shareDialog.cleanupPaths[idx]"
                    label="本地扫描根目录"
                    variant="outlined"
                    density="compact"
                    hide-details
                    prepend-inner-icon="mdi-folder-outline"
                  >
                    <template #append-inner>
                      <button
                        type="button"
                        class="p115-btn p115-btn--tonal p115-btn--sm"
                        @click="$emit('browse-cleanup-path', idx)"
                      >
                        浏览
                      </button>
                    </template>
                  </v-text-field>
                  <button
                    type="button"
                    class="p115-btn p115-btn--icon p115-btn--danger"
                    title="移除此路径"
                    @click="$emit('remove-cleanup-path', idx)"
                  >
                    <v-icon size="16" icon="mdi-close" />
                  </button>
                </div>
              </div>
            </AppleSettingsGroup>

            <AppleSettingsGroup title="清理调度与关联动作" class="mt-4">
              <AppleSettingsRow title="定时运行" description="按设定 Cron 周期自动扫描失效分享 STRM">
                <v-switch v-model="shareDialog.timingShareStrmCleanup" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <AppleSettingsRow title="定时清理周期" wide-control>
                <VCronField v-model="shareDialog.cronShareStrmCleanup" label="定时清理周期" density="compact" hide-details />
              </AppleSettingsRow>

              <AppleSettingsRow title="删除策略" description="待确认批次可在侧栏「115助手仪表盘」审批执行" wide-control>
                <AppleSegmentedControl
                  v-model="shareDialog.deleteMode"
                  :items="[
                    { label: '插件内待确认', value: 'plugin_ui' },
                    { label: '立即删除', value: 'immediate' },
                  ]"
                />
              </AppleSettingsRow>

              <AppleSettingsRow title="清理无效 STRM 关联的媒体信息文件" description="同步移除同名字幕、NFO 与海报等附属文件">
                <v-switch v-model="shareDialog.removeRelatedMediainfo" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <AppleSettingsRow title="清理无效 STRM 空父目录">
                <v-switch v-model="shareDialog.removeEmptyParentDirs" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <AppleSettingsRow title="删除 MoviePilot 整理记录">
                <v-switch v-model="shareDialog.removeStaleTransferHistory" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <AppleSettingsRow title="采集缺失媒体信息" description="从整理历史提取 TMDB/豆瓣 ID 记录至缺失媒体表">
                <v-switch v-model="shareDialog.recordMissingMediaFromHistory" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>
            </AppleSettingsGroup>
          </div>

          <!-- TAB 4: Global Share Settings & Audit Queue -->
          <div v-show="activeTab === 'global'">
            <AppleSettingsGroup title="全局媒体库刷新与路径转换">
              <AppleSettingsRow title="刷新媒体服务器" description="应用于所有分享配置的媒体服务器刷新目标" wide-control>
                <v-select
                  v-model="shareDialog.globalMediaservers"
                  :items="mediaservers"
                  multiple
                  chips
                  closable-chips
                  variant="outlined"
                  density="compact"
                  hide-details
                />
              </AppleSettingsRow>

              <AppleSettingsRow title="媒体库延迟刷新 (秒)" description="0 表示不延迟，立即刷新" wide-control>
                <v-text-field
                  v-model.number="shareDialog.globalMediaServerRefreshDelay"
                  type="number"
                  min="0"
                  density="compact"
                  variant="outlined"
                  hide-details
                />
              </AppleSettingsRow>

              <AppleSettingsRow
                title="MP-媒体库 目录转换"
                description="格式：媒体库路径#MP路径，多个用换行分隔，应用于所有分享配置"
                vertical
              >
                <v-textarea
                  v-model="shareDialog.globalMpMediaserverPaths"
                  variant="outlined"
                  density="compact"
                  rows="3"
                  auto-grow
                  hide-details
                  class="p115-mono"
                  placeholder="例如:&#10;/media#/mp&#10;/nas#/movie"
                />
              </AppleSettingsRow>
            </AppleSettingsGroup>

            <AppleSettingsGroup title="分享审核等待队列" class="mt-4">
              <AppleSettingsRow
                title="启用分享文件审核等待队列"
                description="分享文件仍在审核中时转入后台队列，审核通过后自动继续生成"
              >
                <v-switch v-model="shareDialog.auditQueueEnabled" color="primary" density="compact" hide-details inset />
              </AppleSettingsRow>

              <template v-if="shareDialog.auditQueueEnabled">
                <AppleSettingsRow
                  title="最长审核等待时间 (小时)"
                  description="超过该时间后终止等待并记录失败（范围 1 ~ 168 小时）"
                  wide-control
                >
                  <v-text-field
                    v-model.number="shareDialog.auditMaxWaitHours"
                    type="number"
                    min="1"
                    max="168"
                    suffix="小时"
                    density="compact"
                    variant="outlined"
                    hide-details
                  />
                </AppleSettingsRow>

                <AppleSettingsRow
                  title="审核检查间隔 (分钟)"
                  description="默认每 30 分钟检查一次（范围 1 ~ 360 分钟）"
                  wide-control
                >
                  <v-text-field
                    v-model.number="shareDialog.auditRetryIntervalMinutes"
                    type="number"
                    min="1"
                    max="360"
                    suffix="分钟"
                    density="compact"
                    variant="outlined"
                    hide-details
                  />
                </AppleSettingsRow>
              </template>
            </AppleSettingsGroup>
          </div>
        </div>

        <div class="p115-sheet-footer">
          <button type="button" class="p115-btn p115-btn--subtle" @click="$emit('close')">取消</button>
          <div class="d-flex align-center gap-2 flex-wrap">
            <button
              type="button"
              class="p115-btn p115-btn--tonal"
              :disabled="saving"
              title="仅保存配置到系统，不立即执行同步任务"
              @click="$emit('save-only')"
            >
              <v-progress-circular v-if="saving" indeterminate size="14" width="2" />
              <v-icon v-else size="16" icon="mdi-content-save-outline" />
              <span>仅保存配置</span>
            </button>
            <button
              type="button"
              class="p115-btn p115-btn--primary"
              :disabled="!isShareDialogValid || syncing"
              title="保存配置并立即执行分享同步任务"
              @click="$emit('save-and-sync')"
            >
              <v-progress-circular v-if="syncing" indeterminate size="14" width="2" />
              <v-icon v-else size="16" icon="mdi-play" />
              <span>保存并立即同步</span>
            </button>
          </div>
        </div>
      </template>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed } from 'vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import AppleSettingsRow from '../ui/AppleSettingsRow.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const props = defineProps({
  shareDialog: { type: Object, required: true },
  shareConfigDialog: { type: Object, required: true },
  mediaservers: { type: Array, default: () => [] },
  shareIteratorItems: { type: Array, required: true },
  speedModeItems: { type: Array, required: true },
  isShareDialogValid: { type: Boolean, default: false },
  isShareConfigDialogValid: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  syncing: { type: Boolean, default: false },
  cleanupScanLoading: { type: Boolean, default: false },
  formatBytes: { type: Function, required: true },
});

defineEmits([
  'close',
  'save-only',
  'save-and-sync',
  'add-item',
  'edit-item',
  'remove-item',
  'save-item',
  'close-item-editor',
  'browse-item-local',
  'browse-interactive-dir',
  'add-cleanup-path',
  'remove-cleanup-path',
  'browse-cleanup-path',
  'run-cleanup-scan',
]);

const { dialogContentClass } = useThemeAdapter();

const activeTab = ref('list');
const confirmingClearAll = ref(false);

const hubTabs = computed(() => [
  { label: '分享列表', value: 'list', badge: props.shareDialog.configs?.length || 0 },
  { label: '交互生成', value: 'interactive' },
  { label: '无效清理', value: 'cleanup' },
  { label: '全局与队列', value: 'global' },
]);
</script>

<style scoped>
.p115-share-item {
  align-items: flex-start;
  padding-block: 12px;
}

.p115-share-item-main {
  min-width: 0;
  flex: 1;
}
</style>
