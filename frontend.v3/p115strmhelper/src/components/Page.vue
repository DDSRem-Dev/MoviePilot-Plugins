<template>
  <div
    class="p115-page-host p115-scope"
    :data-p115-theme="themeMode"
    :data-p115-transparent="isTransparent ? 'true' : 'false'"
  >
    <div class="p115-window">
      <div class="p115-aurora" />

      <!-- Top Vibrancy Header -->
      <header class="p115-window-header">
        <div class="p115-header-brand">
          <div class="p115-squircle-icon">
            <v-icon icon="mdi-file-link-outline" size="21" />
          </div>
          <div class="p115-header-titles">
            <div class="p115-header-title">
              <span>115网盘STRM助手</span>
              <span
                v-if="initialDataLoaded"
                class="p115-badge"
                :class="status.enabled ? 'p115-badge--green' : 'p115-badge--neutral'"
              >
                <span class="p115-badge-dot" />
                {{ status.enabled ? '已启用' : '已禁用' }}
              </span>
              <span
                v-if="initialDataLoaded && status.running"
                class="p115-badge p115-badge--amber"
              >
                <span class="p115-badge-dot p115-pulse-dot" />
                任务运行中
              </span>
            </div>
            <div class="p115-header-subtitle">
              点击任意状态或功能模块即可直达对应配置分组 · 蓝白粉多主题自适应
            </div>
          </div>
        </div>

        <div class="d-flex align-center gap-2 flex-shrink-0">
          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            :disabled="refreshing"
            title="刷新插件运行状态与账户容量"
            @click="refreshStatus"
          >
            <v-progress-circular v-if="refreshing" indeterminate size="13" width="2" />
            <v-icon v-else size="15" icon="mdi-refresh" />
            <span class="d-none d-sm-inline">刷新状态</span>
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--primary p115-btn--sm"
            @click="emit('switch')"
          >
            <v-icon size="15" icon="mdi-cog-outline" />
            <span>配置中心</span>
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--ghost p115-btn--icon p115-btn--sm"
            aria-label="关闭窗口"
            title="关闭窗口"
            @click="emit('close')"
          >
            <v-icon size="17" icon="mdi-close" />
          </button>
        </div>
      </header>

      <!-- Scrollable Bento Content -->
      <div class="p115-window-body">
        <!-- Global Alerts -->
        <div v-if="error" class="p115-callout p115-callout--error mb-3">
          <v-icon size="18" color="error" icon="mdi-alert-circle-outline" class="mt-0.5 flex-shrink-0" />
          <span class="flex-grow-1">{{ error }}</span>
          <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" @click="error = null">
            <v-icon size="16" icon="mdi-close" />
          </button>
        </div>

        <div
          v-if="actionMessage"
          class="p115-callout mb-3"
          :class="`p115-callout--${actionMessageType === 'success' ? 'success' : actionMessageType === 'error' ? 'error' : actionMessageType === 'warning' ? 'warn' : 'info'}`"
        >
          <v-icon
            size="18"
            :color="actionMessageType"
            :icon="actionMessageType === 'success' ? 'mdi-check-circle-outline' : 'mdi-information-outline'"
          />
          <span class="flex-grow-1">{{ actionMessage }}</span>
          <button type="button" class="p115-btn p115-btn--ghost p115-btn--icon" @click="actionMessage = null">
            <v-icon size="16" icon="mdi-close" />
          </button>
        </div>

        <v-skeleton-loader v-if="loading && !initialDataLoaded" type="article, actions" class="bg-transparent" />

        <div v-if="initialDataLoaded" class="p115-bento-stage">
          <!-- Diagnostic Onboarding Callouts (Cookie / Incomplete Paths) -->
          <div
            v-if="!status.has_client || !initialConfig?.cookies"
            class="p115-callout p115-callout--error p115-col-12"
          >
            <v-icon size="20" color="error" icon="mdi-key-alert-outline" class="mt-0.5 flex-shrink-0" />
            <div class="flex-grow-1">
              <div class="font-weight-bold mb-0.5">未配置 115 Cookie 或 Cookie 无效</div>
              <div>请在配置页面中设置有效的 115 网盘 Cookie，支持支付宝/微信/iOS 等多端扫码一键获取。</div>
            </div>
            <button
              type="button"
              class="p115-btn p115-btn--primary p115-btn--sm flex-shrink-0"
              @click="jumpToConfig('category-basic', '')"
            >
              <v-icon size="14" icon="mdi-qrcode-scan" />
              <span>前往配置凭证</span>
            </button>
          </div>

          <div
            v-else-if="!isProperlyCongifured"
            class="p115-callout p115-callout--warn p115-col-12"
          >
            <v-icon size="20" color="warning" icon="mdi-folder-alert-outline" class="mt-0.5 flex-shrink-0" />
            <div class="flex-grow-1">
              <div class="font-weight-bold mb-0.5">路径配置不完整</div>
              <div>您已配置 115 Cookie，但尚未启用并配置任一同步或监控目录。请前往配置中心完善目录映射。</div>
            </div>
            <button
              type="button"
              class="p115-btn p115-btn--tonal p115-btn--sm flex-shrink-0"
              @click="jumpToConfig('category-strm', 'tab-transfer')"
            >
              <v-icon size="14" icon="mdi-cog-outline" />
              <span>完善路径配置</span>
            </button>
          </div>

          <!-- ROW 1: 115 Account & Storage (7 cols) + Core System Status (5 cols) -->
          <AppleBentoCard title="115 账户信息" icon="mdi-cloud-circle-outline" class="p115-col-7">
            <template #badge>
              <span
                v-if="!userInfo.loading && !userInfo.error && userInfo.is_vip !== null"
                class="p115-badge"
                :class="userInfo.is_vip ? 'p115-badge--pink' : 'p115-badge--neutral'"
              >
                <v-icon size="13" icon="mdi-crown" />
                {{
                  userInfo.is_vip
                    ? userInfo.is_forever_vip
                      ? '永久VIP'
                      : `VIP (至 ${userInfo.vip_expire_date || 'N/A'})`
                    : '非VIP'
                }}
              </span>
            </template>

            <v-skeleton-loader
              v-if="userInfo.loading || storageInfo.loading"
              type="list-item-avatar-two-line, list-item-two-line"
              class="bg-transparent"
            />
            <div v-else-if="userInfo.error || storageInfo.error" class="p115-callout p115-callout--warn">
              <v-icon size="18" color="warning" icon="mdi-alert-outline" />
              <span>{{ userInfo.error || storageInfo.error }}</span>
            </div>
            <div v-else class="p115-account-box">
              <div class="p115-account-profile">
                <div class="p115-avatar-ring">
                  <v-avatar size="44">
                    <v-img v-if="userInfo.avatar" :src="userInfo.avatar" :alt="userInfo.name" />
                    <v-icon v-else icon="mdi-account-circle" size="32" color="primary" />
                  </v-avatar>
                </div>
                <div class="min-w-0">
                  <div class="p115-account-name">{{ userInfo.name || '未知用户' }}</div>
                  <div class="p115-account-meta">
                    {{
                      userInfo.is_vip
                        ? userInfo.is_forever_vip
                          ? '尊享永久 VIP 云端存储特权'
                          : `VIP 有效期至 ${userInfo.vip_expire_date || 'N/A'}`
                        : '普通账户在线'
                    }}
                  </div>
                </div>
              </div>

              <div class="p115-storage-panel">
                <div class="d-flex align-baseline justify-space-between flex-wrap gap-2 mb-2">
                  <span class="text-caption font-weight-bold">云端存储空间</span>
                  <span v-if="storageInfo.used && storageInfo.total" class="text-caption p115-tabular">
                    已用 <strong>{{ storageInfo.used }}</strong> / 总共 {{ storageInfo.total }}
                    <span class="opacity-75">(剩余 {{ storageInfo.remaining }})</span>
                  </span>
                  <span v-else class="text-caption opacity-60">存储信息不可用</span>
                </div>
                <div v-if="storageInfo.used && storageInfo.total" class="p115-progress-track">
                  <div
                    class="p115-progress-fill"
                    :style="{ width: `${calculateStoragePercentage(storageInfo.used, storageInfo.total)}%` }"
                  />
                </div>
              </div>
            </div>
          </AppleBentoCard>

          <AppleBentoCard title="系统状态" icon="mdi-pulse" class="p115-col-5" flush>
            <div class="p115-inset-list">
              <div
                class="p115-inset-row p115-inset-row--interactive"
                @click="jumpToConfig('category-basic', '')"
              >
                <div class="d-flex align-center gap-2">
                  <v-icon :color="status.enabled ? 'success' : 'grey'" icon="mdi-power" size="18" />
                  <span class="text-body-2 font-weight-medium">插件状态</span>
                </div>
                <span class="p115-badge" :class="status.enabled ? 'p115-badge--green' : 'p115-badge--neutral'">
                  <span class="p115-badge-dot" />
                  {{ status.enabled ? '已启用' : '已禁用' }}
                </span>
              </div>

              <div
                class="p115-inset-row p115-inset-row--interactive"
                @click="jumpToConfig('category-basic', '')"
              >
                <div class="d-flex align-center gap-2">
                  <v-icon
                    :color="status.has_client && initialConfig?.cookies ? 'success' : 'error'"
                    icon="mdi-account-check-outline"
                    size="18"
                  />
                  <span class="text-body-2 font-weight-medium">115客户端状态</span>
                </div>
                <span
                  class="p115-badge"
                  :class="status.has_client && initialConfig?.cookies ? 'p115-badge--blue' : 'p115-badge--red'"
                >
                  <span class="p115-badge-dot" />
                  {{ status.has_client && initialConfig?.cookies ? '已连接' : '未连接' }}
                </span>
              </div>

              <div class="p115-inset-row">
                <div class="d-flex align-center gap-2">
                  <v-icon :color="status.running ? 'warning' : 'success'" icon="mdi-play-circle-outline" size="18" />
                  <span class="text-body-2 font-weight-medium">任务状态</span>
                </div>
                <span class="p115-badge" :class="status.running ? 'p115-badge--amber' : 'p115-badge--green'">
                  <span class="p115-badge-dot" :class="{ 'p115-pulse-dot': status.running }" />
                  {{ status.running ? '运行中' : '空闲' }}
                </span>
              </div>
            </div>
          </AppleBentoCard>

          <!-- ROW 2: Feature Matrix (All 8 Modules — Clickable Deep-Link to Config!) -->
          <AppleBentoCard title="功能配置概览" icon="mdi-apps" class="p115-col-12">
            <template #badge>
              <span class="p115-badge p115-badge--blue p115-tabular">
                已启用 {{ enabledFeatureCount }} / 8
              </span>
            </template>

            <div class="p115-feature-grid">
              <button
                v-for="feat in featureTiles"
                :key="feat.key"
                type="button"
                class="p115-feature-tile"
                @click="jumpToConfig(feat.category, feat.subTab)"
              >
                <div class="d-flex align-center gap-2 min-w-0">
                  <v-icon :icon="feat.icon" :color="feat.active ? 'primary' : 'grey'" size="18" />
                  <span class="p115-feature-name">{{ feat.label }}</span>
                </div>
                <span class="p115-badge" :class="feat.badgeClass">
                  {{ feat.statusText }}
                </span>
              </button>
            </div>
          </AppleBentoCard>

          <!-- Optional Row: FUSE File System Control + Sync Delete History Preview -->
          <AppleBentoCard
            v-if="initialConfig?.fuse_enabled"
            title="FUSE 文件系统"
            icon="mdi-folder-network-outline"
            :class="initialConfig?.sync_del_enabled ? 'p115-col-6' : 'p115-col-12'"
          >
            <template #actions>
              <button
                type="button"
                class="p115-btn p115-btn--ghost p115-btn--icon"
                :disabled="fuseStatus.loading"
                title="刷新 FUSE 状态"
                @click="getFuseStatus"
              >
                <v-icon size="16" icon="mdi-refresh" />
              </button>
            </template>

            <v-skeleton-loader v-if="fuseStatus.loading" type="list-item-three-line" class="bg-transparent" />
            <div v-else>
              <div v-if="fuseStatus.error" class="p115-callout p115-callout--warn mb-3">
                <v-icon size="18" color="warning" icon="mdi-alert-outline" />
                <span>{{ fuseStatus.error }}</span>
              </div>

              <div class="p115-fuse-kv mb-3">
                <div class="p115-fuse-row">
                  <span>挂载状态</span>
                  <span class="p115-badge" :class="fuseStatus.mounted ? 'p115-badge--green' : 'p115-badge--neutral'">
                    <span class="p115-badge-dot" />
                    {{ fuseStatus.mounted ? '已挂载' : '未挂载' }}
                  </span>
                </div>
                <div v-if="fuseStatus.mountpoint" class="p115-fuse-row">
                  <span>挂载点</span>
                  <span class="p115-mono text-caption">{{ fuseStatus.mountpoint }}</span>
                </div>
                <div class="p115-fuse-row">
                  <span>目录缓存 TTL</span>
                  <span class="p115-tabular text-caption">{{ fuseStatus.readdir_ttl }} 秒</span>
                </div>
              </div>

              <div class="d-flex gap-2">
                <button
                  type="button"
                  class="p115-btn p115-btn--primary flex-grow-1"
                  :disabled="fuseStatus.mounted || fuseStatus.mounting"
                  @click="mountFuse"
                >
                  <v-progress-circular v-if="fuseStatus.mounting" indeterminate size="14" width="2" />
                  <v-icon v-else size="16" icon="mdi-folder-plus-outline" />
                  <span>挂载</span>
                </button>
                <button
                  type="button"
                  class="p115-btn p115-btn--danger flex-grow-1"
                  :disabled="!fuseStatus.mounted || fuseStatus.unmounting"
                  @click="unmountFuse"
                >
                  <v-progress-circular v-if="fuseStatus.unmounting" indeterminate size="14" width="2" />
                  <v-icon v-else size="16" icon="mdi-folder-remove-outline" />
                  <span>卸载</span>
                </button>
              </div>
            </div>
          </AppleBentoCard>

          <AppleBentoCard
            v-if="initialConfig?.sync_del_enabled"
            title="同步删除历史"
            icon="mdi-history"
            :class="initialConfig?.fuse_enabled ? 'p115-col-6' : 'p115-col-12'"
            flush
          >
            <template #badge>
              <span v-if="syncDelHistoryTotal > 0" class="p115-badge p115-badge--pink p115-tabular">
                {{ syncDelHistoryTotal }} 条
              </span>
            </template>
            <template #actions>
              <button
                v-if="syncDelHistoryTotal > 5"
                type="button"
                class="p115-btn p115-btn--tonal p115-btn--sm"
                @click="syncDelHistoryDialog.show = true"
              >
                <span>查看全部 ({{ syncDelHistoryTotal }})</span>
              </button>
              <button
                type="button"
                class="p115-btn p115-btn--ghost p115-btn--icon"
                :disabled="syncDelHistoryLoading"
                @click="loadSyncDelHistory"
              >
                <v-icon size="16" icon="mdi-refresh" />
              </button>
            </template>

            <v-skeleton-loader
              v-if="syncDelHistoryLoading"
              type="list-item-avatar-two-line@3"
              class="bg-transparent"
            />
            <div v-else-if="syncDelHistory.length === 0" class="pa-6 text-center text-caption opacity-70">
              <v-icon icon="mdi-check-decagram-outline" size="28" class="mb-1 opacity-50" />
              <div>暂无同步删除历史</div>
            </div>
            <div v-else class="p115-inset-list">
              <div
                v-for="(item, index) in displayedSyncDelHistory"
                :key="item.unique || index"
                class="p115-inset-row"
              >
                <div class="d-flex align-center gap-3 min-w-0">
                  <v-avatar size="42" rounded="lg" class="flex-shrink-0">
                    <v-img v-if="item.image" :src="item.image" :alt="item.title" cover />
                    <v-icon v-else icon="mdi-movie-open-outline" />
                  </v-avatar>
                  <div class="min-w-0">
                    <div class="text-body-2 font-weight-medium text-truncate">{{ item.title }}</div>
                    <div class="d-flex flex-wrap align-center gap-1 text-caption opacity-75 mt-0.5">
                      <span class="p115-badge p115-badge--blue">{{ item.type }}</span>
                      <span v-if="item.year">· {{ item.year }}</span>
                      <span v-if="item.season">· S{{ String(item.season).padStart(2, '0') }}</span>
                      <span v-if="item.episode">· E{{ String(item.episode).padStart(2, '0') }}</span>
                      <span class="p115-tabular">· {{ item.del_time }}</span>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  class="p115-btn p115-btn--icon p115-btn--danger flex-shrink-0"
                  :disabled="deletingHistoryId === item.unique"
                  @click="confirmDeleteHistory(item)"
                >
                  <v-icon size="15" icon="mdi-trash-can-outline" />
                </button>
              </div>
            </div>
          </AppleBentoCard>

          <!-- ROW 3: Active Path Mapping Topology (All 6 Path Types Preserved!) -->
          <AppleBentoCard title="路径配置拓扑" icon="mdi-sitemap-outline" class="p115-col-12">
            <template #actions>
              <button
                type="button"
                class="p115-btn p115-btn--tonal p115-btn--sm"
                @click="jumpToConfig('category-strm', 'tab-transfer')"
              >
                <span>管理路径映射</span>
              </button>
            </template>

            <div v-if="!hasAnyEnabledPathSection" class="py-4 text-center text-caption opacity-70">
              当前未开启需要目录映射的功能模块，点击右上角「配置」即可按需开启
            </div>

            <div v-else class="d-flex flex-column gap-4">
              <!-- Dual-Path Sections: MP Transfer / Full Sync / Increment Sync / Life Events -->
              <div v-for="sec in activeDualPathSections" :key="sec.key">
                <div class="d-flex align-center justify-space-between mb-2">
                  <span class="text-caption font-weight-bold">{{ sec.label }}</span>
                  <span class="p115-badge p115-badge--blue p115-tabular">{{ sec.paths.length }} 组映射</span>
                </div>

                <div v-if="sec.paths.length === 0" class="text-caption text-error">未配置路径</div>
                <div v-else class="d-flex flex-column gap-2">
                  <div
                    v-for="(path, idx) in sec.paths"
                    :key="`${sec.key}-${idx}`"
                    class="p115-path-pipeline"
                  >
                    <div class="p115-path-box" :title="path.local">
                      <v-icon size="16" color="primary" icon="mdi-folder-home-outline" />
                      <div class="p115-path-box-meta">
                        <div class="p115-path-box-label">本地目录</div>
                        <div class="p115-path-box-val">{{ path.local || '-' }}</div>
                      </div>
                    </div>

                    <div class="p115-path-arrow">
                      <v-icon
                        size="16"
                        :icon="status.running ? 'mdi-sync' : 'mdi-arrow-left-right'"
                        :class="{ 'p115-spin-active': status.running }"
                      />
                    </div>

                    <div class="p115-path-box" :title="path.remote">
                      <v-icon size="16" color="secondary" icon="mdi-cloud-outline" />
                      <div class="p115-path-box-meta">
                        <div class="p115-path-box-label">网盘目录</div>
                        <div class="p115-path-box-val">{{ path.remote || '-' }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Pan Transfer Directories -->
              <div v-if="initialConfig?.pan_transfer_enabled">
                <div class="d-flex align-center justify-space-between mb-2">
                  <span class="text-caption font-weight-bold">网盘整理目录</span>
                  <span class="p115-badge p115-badge--pink p115-tabular">
                    {{ getPanTransferPathsCount(initialConfig?.pan_transfer_paths) }} 个目录
                  </span>
                </div>

                <div v-if="getPanTransferPathsCount(initialConfig?.pan_transfer_paths) === 0" class="text-caption text-error">
                  未配置网盘整理目录
                </div>
                <div v-else class="d-flex flex-column gap-2">
                  <div
                    v-for="(pathItem, idx) in getParsedPanTransferPaths(initialConfig?.pan_transfer_paths)"
                    :key="`pan-${idx}`"
                    class="p115-path-box"
                    :title="pathItem.path"
                  >
                    <v-icon size="16" color="secondary" icon="mdi-folder-arrow-down-outline" />
                    <div class="p115-path-box-meta">
                      <div class="p115-path-box-label">待整理网盘目录</div>
                      <div class="p115-path-box-val">{{ pathItem.path }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Directory Upload Paths -->
              <div v-if="initialConfig?.directory_upload_enabled">
                <div class="d-flex align-center justify-space-between mb-2">
                  <span class="text-caption font-weight-bold">目录上传路径</span>
                  <span class="p115-badge p115-badge--blue p115-tabular">
                    {{ initialConfig?.directory_upload_path?.length || 0 }} 组规则
                  </span>
                </div>

                <div
                  v-if="!initialConfig?.directory_upload_path || initialConfig.directory_upload_path.length === 0"
                  class="text-caption text-error"
                >
                  未配置路径
                </div>
                <div v-else class="d-flex flex-column gap-2">
                  <div
                    v-for="(pathGroup, groupIndex) in initialConfig.directory_upload_path"
                    :key="`upload-group-${groupIndex}`"
                    class="p115-upload-flow-card"
                  >
                    <div class="p115-path-pipeline" style="padding: 0; border: none; background: transparent;">
                      <div class="p115-path-box" :title="pathGroup.src">
                        <v-icon size="16" color="primary" icon="mdi-folder-table-outline" />
                        <div class="p115-path-box-meta">
                          <div class="p115-path-box-label">本地监控</div>
                          <div class="p115-path-box-val">{{ pathGroup.src || '-' }}</div>
                        </div>
                      </div>

                      <div class="p115-path-arrow">
                        <v-icon size="16" icon="mdi-cloud-upload-outline" />
                      </div>

                      <div class="p115-path-box" :title="pathGroup.dest_remote">
                        <v-icon size="16" color="secondary" icon="mdi-cloud-check-outline" />
                        <div class="p115-path-box-meta">
                          <div class="p115-path-box-label">网盘上传</div>
                          <div class="p115-path-box-val">{{ pathGroup.dest_remote || '-' }}</div>
                        </div>
                      </div>
                    </div>

                    <div
                      v-if="pathGroup.dest_local || pathGroup.dest_strm || typeof pathGroup.delete === 'boolean'"
                      class="d-flex align-center flex-wrap gap-2 mt-2 pt-2"
                      style="border-top: 1px dashed var(--p115-border-hairline);"
                    >
                      <span v-if="pathGroup.dest_local" class="p115-badge p115-badge--amber p115-mono">
                        本地复制: {{ pathGroup.dest_local }}
                      </span>
                      <span v-if="pathGroup.dest_strm" class="p115-badge p115-badge--blue p115-mono">
                        STRM输出: {{ pathGroup.dest_strm }}
                      </span>
                      <span
                        v-if="typeof pathGroup.delete === 'boolean'"
                        class="p115-badge ml-auto"
                        :class="pathGroup.delete ? 'p115-badge--red' : 'p115-badge--neutral'"
                      >
                        {{ pathGroup.delete ? '处理后删除源' : '保留源文件' }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </AppleBentoCard>

          <!-- Help Footer Note -->
          <div class="p115-callout p115-callout--info p115-col-12">
            <v-icon size="18" color="primary" icon="mdi-lightbulb-on-outline" />
            <span>点击底栏快捷按钮可直接触发「全量同步」、「全量同步数据库」、「分享同步」与「离线下载」，无需层层翻找菜单。</span>
          </div>
        </div>
      </div>

      <!-- Bottom Floating Apple Action Bar (Direct Quick Actions — No Hidden 3-Dot Trap!) -->
      <footer class="p115-window-footer">
        <div class="p115-dock-scroll">
          <button
            type="button"
            class="p115-btn p115-btn--tonal p115-btn--sm"
            :disabled="!status.enabled || !status.has_client || actionLoading"
            @click="fullSyncConfirmDialog = true"
          >
            <v-icon size="15" icon="mdi-sync" />
            <span>全量同步</span>
          </button>

          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            :disabled="!status.enabled || !status.has_client || actionLoading"
            @click="fullSyncDbConfirmDialog = true"
          >
            <v-icon size="15" icon="mdi-database-sync-outline" />
            <span>同步数据库</span>
          </button>

          <button
            type="button"
            class="p115-btn p115-btn--pink p115-btn--sm"
            :disabled="!status.enabled || !status.has_client || actionLoading"
            @click="openShareDialog"
          >
            <v-icon size="15" icon="mdi-share-variant-outline" />
            <span>分享同步</span>
          </button>

          <button
            type="button"
            class="p115-btn p115-btn--subtle p115-btn--sm"
            :disabled="!status.enabled || !status.has_client || actionLoading"
            @click="openOfflineDownloadDialog"
          >
            <v-icon size="15" icon="mdi-cloud-download-outline" />
            <span>离线下载</span>
          </button>
        </div>

        <div class="d-none d-md-flex align-center gap-2 text-caption opacity-65 ml-auto">
          <v-icon size="14" icon="mdi-lightning-bolt-outline" color="primary" />
          <span>快捷任务栏</span>
        </div>
      </footer>
    </div>

    <!-- =======================================================================
         Apple Interactive Sheets & Dialogs
         ======================================================================= -->
    <ShareSyncSheet
      :share-dialog="shareDialog"
      :share-config-dialog="shareConfigDialog"
      :mediaservers="mediaservers"
      :share-iterator-items="shareIteratorItems"
      :speed-mode-items="speedModeItems"
      :is-share-dialog-valid="isShareDialogValid"
      :is-share-config-dialog-valid="isShareConfigDialogValid"
      :saving="shareConfigSaving"
      :syncing="shareSyncLoading"
      :cleanup-scan-loading="shareStrmCleanupScanLoading"
      :format-bytes="formatBytes"
      @close="closeShareDialog"
      @save-only="saveShareConfigs"
      @save-and-sync="executeShareSync"
      @add-item="addShareConfig"
      @edit-item="editShareConfig"
      @remove-item="removeShareConfig"
      @save-item="saveShareConfig"
      @close-item-editor="closeShareConfigDialog"
      @browse-item-local="openShareConfigDirSelector('local')"
      @browse-interactive-dir="openInteractiveGenStrmDirSelector"
      @add-cleanup-path="addShareStrmCleanupPath"
      @remove-cleanup-path="removeShareStrmCleanupPath"
      @browse-cleanup-path="openShareStrmCleanupDirSelector"
      @run-cleanup-scan="runShareStrmCleanupScan"
    />

    <OfflineDownloadSheet
      :offline-download-dialog="offlineDownloadDialog"
      :get-path-label="getPathLabel"
      @close="closeOfflineDownloadDialog"
      @add-task="addOfflineTask"
      @fetch-tasks="fetchOfflineTasks"
      @browse-dest="openOfflineDestDirSelector"
    />

    <DirSelectorDialog
      :dir-dialog="dirDialog"
      :disable-root="true"
      @load-dir="loadDirContent"
      @navigate-up="navigateToParentDir"
      @select-dir="selectDir"
      @confirm="confirmDirSelection"
      @close="closeDirDialog"
    />

    <FullSyncConfirmDialog
      v-model="fullSyncConfirmDialog"
      :loading="syncLoading"
      :has-media-server-refresh="Boolean(initialConfig?.full_sync_media_server_refresh_enabled)"
      @confirm="handleConfirmFullSync"
    />

    <!-- Full Sync Database Confirm Sheet -->
    <v-dialog v-model="fullSyncDbConfirmDialog" max-width="460" persistent :content-class="dialogContentClass">
      <v-card flat class="p115-sheet">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon icon="mdi-database-sync-outline" color="warning" size="20" />
            <span>确认同步数据库</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div class="text-body-2">您确定要立即执行全量同步数据库吗？该操作会覆盖原有数据库缓存记录。</div>
        </div>
        <div class="p115-sheet-footer">
          <button
            type="button"
            class="p115-btn p115-btn--subtle"
            :disabled="syncDbLoading"
            @click="fullSyncDbConfirmDialog = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--primary"
            :disabled="syncDbLoading"
            @click="handleConfirmFullSyncDb"
          >
            <v-progress-circular v-if="syncDbLoading" indeterminate size="14" width="2" />
            <span>确认执行</span>
          </button>
        </div>
      </v-card>
    </v-dialog>

    <!-- Confirm Delete Single Sync-Del History Sheet -->
    <v-dialog v-model="deleteHistoryConfirmDialog.show" max-width="460" persistent :content-class="dialogContentClass">
      <v-card flat class="p115-sheet">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon icon="mdi-alert-circle-outline" color="error" size="20" />
            <span>确认删除历史记录</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div class="text-body-2 mb-3">确定要删除这条同步删除历史记录吗？</div>
          <div v-if="deleteHistoryConfirmDialog.item" class="p115-callout p115-callout--info mb-3">
            <div>
              <div class="font-weight-bold">{{ deleteHistoryConfirmDialog.item.title }}</div>
              <div v-if="deleteHistoryConfirmDialog.item.path" class="p115-mono text-caption mt-1" style="word-break: break-all;">
                {{ deleteHistoryConfirmDialog.item.path }}
              </div>
              <div class="text-caption opacity-70 mt-1">{{ deleteHistoryConfirmDialog.item.del_time }}</div>
            </div>
          </div>
          <div class="p115-callout p115-callout--warn">
            <v-icon size="16" color="warning" icon="mdi-alert-outline" />
            <span>此操作不可恢复，请谨慎操作</span>
          </div>
        </div>
        <div class="p115-sheet-footer">
          <button
            type="button"
            class="p115-btn p115-btn--subtle"
            :disabled="deletingHistoryId === deleteHistoryConfirmDialog.item?.unique"
            @click="deleteHistoryConfirmDialog.show = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger"
            :disabled="deletingHistoryId === deleteHistoryConfirmDialog.item?.unique"
            @click="handleConfirmDeleteHistory"
          >
            确认删除
          </button>
        </div>
      </v-card>
    </v-dialog>

    <!-- Confirm Delete All Sync-Del History Sheet -->
    <v-dialog v-model="deleteAllHistoryConfirmDialog" max-width="460" persistent :content-class="dialogContentClass">
      <v-card flat class="p115-sheet">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon icon="mdi-delete-sweep-outline" color="error" size="20" />
            <span>确认清空历史</span>
          </div>
        </div>
        <div class="p115-sheet-body">
          <div class="text-body-2 mb-3">
            确定要删除全部 <strong class="p115-tabular">{{ syncDelHistoryTotal }}</strong> 条同步删除历史记录吗？
          </div>
          <div class="p115-callout p115-callout--error">
            <v-icon size="16" color="error" icon="mdi-alert-outline" />
            <span>此操作不可恢复，请谨慎操作</span>
          </div>
        </div>
        <div class="p115-sheet-footer">
          <button
            type="button"
            class="p115-btn p115-btn--subtle"
            :disabled="deletingAllHistory"
            @click="deleteAllHistoryConfirmDialog = false"
          >
            取消
          </button>
          <button
            type="button"
            class="p115-btn p115-btn--danger"
            :disabled="deletingAllHistory"
            @click="handleConfirmDeleteAllHistory"
          >
            确认清空
          </button>
        </div>
      </v-card>
    </v-dialog>

    <!-- Full Paginated Sync-Del History Sheet -->
    <v-dialog v-model="syncDelHistoryDialog.show" max-width="860" :content-class="dialogContentClass">
      <v-card flat class="p115-sheet">
        <div class="p115-sheet-header">
          <div class="p115-sheet-title">
            <v-icon icon="mdi-history" color="primary" size="20" />
            <span>同步删除历史记录</span>
            <span class="p115-badge p115-badge--pink p115-tabular">共 {{ syncDelHistoryTotal }} 条</span>
          </div>
          <div class="d-flex align-center gap-2">
            <button
              v-if="syncDelHistoryTotal > 0"
              type="button"
              class="p115-btn p115-btn--danger p115-btn--sm"
              :disabled="deletingAllHistory"
              @click="confirmDeleteAllHistory"
            >
              <v-icon size="14" icon="mdi-delete-sweep-outline" />
              <span>一键全部删除</span>
            </button>
            <button
              type="button"
              class="p115-btn p115-btn--ghost p115-btn--icon"
              :disabled="syncDelHistoryLoading"
              @click="loadSyncDelHistory"
            >
              <v-icon size="16" icon="mdi-refresh" />
            </button>
            <button
              type="button"
              class="p115-btn p115-btn--ghost p115-btn--icon"
              @click="syncDelHistoryDialog.show = false"
            >
              <v-icon size="18" icon="mdi-close" />
            </button>
          </div>
        </div>

        <div class="p115-sheet-body pa-0">
          <v-skeleton-loader v-if="syncDelHistoryLoading" type="list-item-avatar-three-line@5" class="bg-transparent" />
          <div v-else-if="syncDelHistory.length === 0" class="py-10 text-center text-caption opacity-70">
            暂无删除历史
          </div>
          <div v-else class="p115-inset-list">
            <div
              v-for="(item, index) in syncDelHistory"
              :key="item.unique || index"
              class="p115-inset-row py-3"
            >
              <div class="d-flex align-center gap-3 min-w-0">
                <v-avatar size="50" rounded="lg" class="flex-shrink-0">
                  <v-img v-if="item.image" :src="item.image" :alt="item.title" cover />
                  <v-icon v-else icon="mdi-movie-open-outline" />
                </v-avatar>
                <div class="min-w-0">
                  <div class="text-body-2 font-weight-bold">{{ item.title }}</div>
                  <div class="d-flex flex-wrap align-center gap-1 text-caption opacity-80 mt-1">
                    <span class="p115-badge p115-badge--blue">{{ item.type }}</span>
                    <span v-if="item.year">· {{ item.year }}</span>
                    <span v-if="item.season">· S{{ String(item.season).padStart(2, '0') }}</span>
                    <span v-if="item.episode">· E{{ String(item.episode).padStart(2, '0') }}</span>
                  </div>
                  <div v-if="item.path" class="p115-mono text-caption opacity-70 mt-1" style="word-break: break-all;">
                    {{ item.path }}
                  </div>
                  <div class="text-caption opacity-60 mt-0.5 p115-tabular">{{ item.del_time }}</div>
                </div>
              </div>
              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger flex-shrink-0"
                :disabled="deletingHistoryId === item.unique"
                @click="confirmDeleteHistory(item)"
              >
                <v-icon size="16" icon="mdi-trash-can-outline" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="syncDelHistoryTotal > 0" class="p115-sheet-footer">
          <div class="text-caption opacity-75 p115-tabular">
            显示第 {{ (syncDelHistoryPage - 1) * syncDelHistoryLimit + 1 }} -
            {{ Math.min(syncDelHistoryPage * syncDelHistoryLimit, syncDelHistoryTotal) }} 条，共 {{ syncDelHistoryTotal }} 条
          </div>
          <v-pagination
            v-model="syncDelHistoryPage"
            :length="Math.ceil(syncDelHistoryTotal / syncDelHistoryLimit)"
            :total-visible="5"
            density="compact"
            size="small"
            @update:model-value="loadSyncDelHistory"
          />
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import '../styles/apple-theme.css';
import { P115_STRM_HELPER_PLUGIN_ID } from '../utils/pluginId.js';
import { requestConfigJump } from '../utils/navigationBridge.js';
import { useThemeAdapter } from './composables/useThemeAdapter.js';
import AppleBentoCard from './ui/AppleBentoCard.vue';
import FullSyncConfirmDialog from './dialogs/FullSyncConfirmDialog.vue';
import DirSelectorDialog from './dialogs/DirSelectorDialog.vue';
import ShareSyncSheet from './dialogs/ShareSyncSheet.vue';
import OfflineDownloadSheet from './dialogs/OfflineDownloadSheet.vue';

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

const emit = defineEmits(['close', 'switch', 'update:config', 'action']);

const pluginId = P115_STRM_HELPER_PLUGIN_ID;
const { isTransparent, themeMode, dialogContentClass } = useThemeAdapter();

const jumpToConfig = (category, subTab = '') => {
  requestConfigJump({ category, subTab });
  emit('switch');
};

const parseSize = (sizeString) => {
  if (!sizeString || typeof sizeString !== 'string') return 0;
  const regex = /^(\d*\.?\d+)\s*(k|m|g|t)?b?$/i;
  const match = sizeString.trim().match(regex);
  if (!match) return 0;
  const num = parseFloat(match[1]);
  const unit = (match[2] || '').toLowerCase();
  switch (unit) {
    case 't': return Math.round(num * 1024 * 1024 * 1024 * 1024);
    case 'g': return Math.round(num * 1024 * 1024 * 1024);
    case 'm': return Math.round(num * 1024 * 1024);
    case 'k': return Math.round(num * 1024);
    default: return Math.round(num);
  }
};

const formatBytes = (bytes, decimals = 2) => {
  if (!+bytes) return '';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'K', 'M', 'G', 'T'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const formattedNum = parseFloat((bytes / Math.pow(k, i)).toFixed(dm));
  return `${formattedNum} ${sizes[i]}`;
};

const loading = ref(true);
const refreshing = ref(false);
const syncLoading = ref(false);
const syncDbLoading = ref(false);
const shareSyncLoading = ref(false);
const shareConfigSaving = ref(false);
const initialDataLoaded = ref(false);
const error = ref(null);
const actionMessage = ref(null);
const actionMessageType = ref('info');
const actionLoading = ref(false);
const fullSyncConfirmDialog = ref(false);
const fullSyncDbConfirmDialog = ref(false);
const deleteAllHistoryConfirmDialog = ref(false);
const deleteHistoryConfirmDialog = reactive({
  show: false,
  item: null,
});
const syncDelHistory = ref([]);
const syncDelHistoryLoading = ref(false);
const deletingHistoryId = ref(null);
const deletingAllHistory = ref(false);
const syncDelHistoryTotal = ref(0);

const fuseStatus = reactive({
  loading: false,
  mounted: false,
  mountpoint: null,
  readdir_ttl: 60,
  error: null,
  mounting: false,
  unmounting: false,
});

const syncDelHistoryPage = ref(1);
const syncDelHistoryLimit = ref(20);
let syncDelHistoryRefreshTimer = null;

const displayedSyncDelHistory = computed(() => syncDelHistory.value.slice(0, 5));

const syncDelHistoryDialog = reactive({
  show: false,
});

const status = reactive({
  enabled: false,
  has_client: false,
  running: false,
});

const userInfo = reactive({
  name: null,
  is_vip: null,
  is_forever_vip: null,
  vip_expire_date: null,
  avatar: null,
  error: null,
  loading: true,
});

const storageInfo = reactive({
  total: null,
  used: null,
  remaining: null,
  error: null,
  loading: true,
});

const featureTiles = computed(() => {
  const c = props.initialConfig || {};
  const clearActive = Boolean(c.clear_recyclebin_enabled || c.clear_receive_path_enabled);
  return [
    {
      key: 'transfer_monitor',
      label: '监控MP整理',
      icon: 'mdi-file-move-outline',
      active: Boolean(c.transfer_monitor_enabled),
      statusText: c.transfer_monitor_enabled ? '已启用' : '已禁用',
      badgeClass: c.transfer_monitor_enabled ? 'p115-badge--blue' : 'p115-badge--neutral',
      category: 'category-strm',
      subTab: 'tab-transfer',
    },
    {
      key: 'full_sync',
      label: '定期全量同步',
      icon: 'mdi-sync',
      active: Boolean(c.timing_full_sync_strm),
      statusText: c.timing_full_sync_strm ? '已启用' : '已禁用',
      badgeClass: c.timing_full_sync_strm ? 'p115-badge--blue' : 'p115-badge--neutral',
      category: 'category-strm',
      subTab: 'tab-sync',
    },
    {
      key: 'increment_sync',
      label: '定期增量同步',
      icon: 'mdi-book-sync-outline',
      active: Boolean(c.increment_sync_strm_enabled),
      statusText: c.increment_sync_strm_enabled ? '已启用' : '已禁用',
      badgeClass: c.increment_sync_strm_enabled ? 'p115-badge--blue' : 'p115-badge--neutral',
      category: 'category-strm',
      subTab: 'tab-increment-sync',
    },
    {
      key: 'monitor_life',
      label: '监控115生活事件',
      icon: 'mdi-calendar-heart-outline',
      active: Boolean(c.monitor_life_enabled),
      statusText: c.monitor_life_enabled ? '已启用' : '已禁用',
      badgeClass: c.monitor_life_enabled ? 'p115-badge--pink' : 'p115-badge--neutral',
      category: 'category-strm',
      subTab: 'tab-life',
    },
    {
      key: 'pan_transfer',
      label: '网盘整理',
      icon: 'mdi-transfer',
      active: Boolean(c.pan_transfer_enabled),
      statusText: c.pan_transfer_enabled ? '已启用' : '已禁用',
      badgeClass: c.pan_transfer_enabled ? 'p115-badge--blue' : 'p115-badge--neutral',
      category: 'category-pan',
      subTab: 'tab-pan-transfer',
    },
    {
      key: 'clear_schedule',
      label: '定期清理',
      icon: 'mdi-broom',
      active: clearActive,
      statusText: clearActive ? '已启用' : '已禁用',
      badgeClass: clearActive ? 'p115-badge--blue' : 'p115-badge--neutral',
      category: 'category-other',
      subTab: 'tab-cleanup',
    },
    {
      key: 'sync_del',
      label: '同步删除',
      icon: 'mdi-delete-sweep-outline',
      active: Boolean(c.sync_del_enabled),
      statusText: c.sync_del_enabled ? '已启用' : '已禁用',
      badgeClass: c.sync_del_enabled ? 'p115-badge--amber' : 'p115-badge--neutral',
      category: 'category-other',
      subTab: 'tab-sync-del',
    },
    {
      key: 'fuse_fs',
      label: 'FUSE 文件系统',
      icon: 'mdi-folder-network-outline',
      active: Boolean(fuseStatus.mounted),
      statusText: fuseStatus.mounted ? '已挂载' : '未挂载',
      badgeClass: fuseStatus.mounted ? 'p115-badge--pink' : 'p115-badge--neutral',
      category: 'category-pan',
      subTab: 'tab-pan-mount',
    },
  ];
});

const enabledFeatureCount = computed(() => featureTiles.value.filter((f) => f.active).length);

const activeDualPathSections = computed(() => {
  const c = props.initialConfig || {};
  const list = [];
  if (c.transfer_monitor_enabled) {
    list.push({ key: 'transfer', label: '监控MP整理路径', paths: getParsedPaths(c.transfer_monitor_paths) });
  }
  if (c.timing_full_sync_strm) {
    list.push({ key: 'fullsync', label: '全量同步路径', paths: getParsedPaths(c.full_sync_strm_paths) });
  }
  if (c.increment_sync_strm_enabled) {
    list.push({ key: 'incsync', label: '增量同步路径', paths: getParsedPaths(c.increment_sync_strm_paths) });
  }
  if (c.monitor_life_enabled) {
    list.push({ key: 'life', label: '监控115生活事件路径', paths: getParsedPaths(c.monitor_life_paths) });
  }
  return list;
});

const hasAnyEnabledPathSection = computed(() => {
  const c = props.initialConfig || {};
  return (
    activeDualPathSections.value.length > 0 ||
    Boolean(c.pan_transfer_enabled) ||
    Boolean(c.directory_upload_enabled)
  );
});

const OFFLINE_PATH_CACHE_KEY = 'p115strmhelper_offline_paths_cache';
const MAX_CACHED_PATHS = 20;

const getCachedPaths = () => {
  try {
    const cached = localStorage.getItem(OFFLINE_PATH_CACHE_KEY);
    if (cached) {
      const paths = JSON.parse(cached);
      return Array.isArray(paths) ? paths.filter((p) => p && typeof p === 'string') : [];
    }
  } catch (e) {
    console.error('读取路径缓存失败:', e);
  }
  return [];
};

const addPathToCache = (path) => {
  if (!path || !path.trim()) return;
  const trimmedPath = path.trim();
  let cached = getCachedPaths().filter((p) => p !== trimmedPath);
  cached.unshift(trimmedPath);
  cached = cached.slice(0, MAX_CACHED_PATHS);
  try {
    localStorage.setItem(OFFLINE_PATH_CACHE_KEY, JSON.stringify(cached));
  } catch (e) {
    console.error('保存路径缓存失败:', e);
  }
};

const offlineDownloadDialog = reactive({
  show: false,
  activeTab: 'add',
  loading: false,
  adding: false,
  error: null,
  addError: null,
  tasks: [],
  totalTasks: 0,
  itemsPerPage: 10,
  headers: [
    { title: '文件名', key: 'name', align: 'start', sortable: false, minWidth: '200px' },
    { title: '大小', key: 'size_text', align: 'end', sortable: false, cellProps: { class: 'text-no-wrap' }, minWidth: '80px' },
    { title: '状态', key: 'status_text', align: 'center', sortable: false, minWidth: '80px' },
    { title: '进度', key: 'progress', align: 'start', sortable: false, minWidth: '120px' },
  ],
  links: '',
  destPath: '',
  availablePaths: [],
  availablePathStrings: [],
});

const calculateStoragePercentage = (used, total) => {
  if (!used || !total) return 0;
  const parseUnitSize = (sizeStr) => {
    if (!sizeStr || typeof sizeStr !== 'string') return 0;
    const value = parseFloat(sizeStr);
    if (Number.isNaN(value)) return 0;
    if (sizeStr.toUpperCase().includes('TB')) return value * 1024 * 1024;
    if (sizeStr.toUpperCase().includes('GB')) return value * 1024;
    if (sizeStr.toUpperCase().includes('MB')) return value;
    return value;
  };
  const usedValue = parseUnitSize(used);
  const totalValue = parseUnitSize(total);
  if (totalValue === 0) return 0;
  return Math.min(Math.max((usedValue / totalValue) * 100, 0), 100);
};

const getPathsCount = (pathString) => {
  if (!pathString) return 0;
  try {
    return pathString.split('\n').filter((line) => line.trim() && line.includes('#')).length;
  } catch (e) {
    console.error('解析路径字符串失败:', e);
    return 0;
  }
};

const getPanTransferPathsCount = (pathString) => {
  if (!pathString) return 0;
  try {
    return pathString.split('\n').filter((line) => line.trim()).length;
  } catch (e) {
    console.error('解析网盘整理路径字符串失败:', e);
    return 0;
  }
};

const isProperlyCongifured = computed(() => {
  if (!props.initialConfig) return false;
  const hasBasicConfig = props.initialConfig.enabled && props.initialConfig.cookies && props.initialConfig.moviepilot_address;
  if (!hasBasicConfig) return false;
  const hasTransferPaths = getPathsCount(props.initialConfig.transfer_monitor_paths) > 0 && props.initialConfig.transfer_monitor_enabled;
  const hasFullSyncPaths = getPathsCount(props.initialConfig.full_sync_strm_paths) > 0 && props.initialConfig.timing_full_sync_strm;
  const hasIncrementSyncPaths = getPathsCount(props.initialConfig.increment_sync_strm_paths) > 0 && props.initialConfig.increment_sync_strm_enabled;
  const hasLifePaths = getPathsCount(props.initialConfig.monitor_life_paths) > 0 && props.initialConfig.monitor_life_enabled;
  const hasSharePaths = Array.isArray(props.initialConfig.share_strm_config) && props.initialConfig.share_strm_config.length > 0;
  return hasTransferPaths || hasFullSyncPaths || hasIncrementSyncPaths || hasLifePaths || hasSharePaths;
});

const getStatus = async () => {
  loading.value = true;
  error.value = null;
  try {
    const result = await props.api.get(`plugin/${pluginId}/get_status`);
    if (result && result.code === 0 && result.data) {
      status.enabled = Boolean(result.data.enabled);
      status.has_client = Boolean(result.data.has_client);
      status.running = Boolean(result.data.running);
      try {
        const configData = await props.api.get(`plugin/${pluginId}/get_config`);
        if (configData) {
          Object.assign(props.initialConfig, configData);
        }
      } catch (configErr) {
        console.error('获取配置失败:', configErr);
      }
      initialDataLoaded.value = true;
    } else if (props.initialConfig) {
      status.enabled = Boolean(props.initialConfig.enabled);
      status.has_client = Boolean(props.initialConfig.cookies && props.initialConfig.cookies.trim() !== '');
      status.running = false;
      initialDataLoaded.value = true;
      if (Object.keys(props.initialConfig).length <= 1) {
        try {
          const configData = await props.api.get(`plugin/${pluginId}/get_config`);
          if (configData) {
            Object.assign(props.initialConfig, configData);
          }
        } catch (configErr) {
          console.error('获取配置失败:', configErr);
        }
      }
      throw new Error('状态API调用失败，使用配置数据显示状态');
    } else {
      throw new Error(result?.msg || '获取状态失败，请检查网络连接');
    }
  } catch (err) {
    if (!err.message.includes('使用配置数据显示状态')) {
      error.value = `获取状态失败: ${err.message || '未知错误'}`;
    }
    console.error('获取状态失败:', err);
  } finally {
    loading.value = false;
  }
};

const refreshStatus = async () => {
  refreshing.value = true;
  await getStatus();
  if (status.has_client && props.initialConfig?.cookies) {
    await fetchUserStorageStatus();
  } else {
    userInfo.loading = false;
    storageInfo.loading = false;
    if (!props.initialConfig?.cookies) {
      userInfo.error = '请先配置115 Cookie。';
      storageInfo.error = '请先配置115 Cookie。';
    } else if (!status.has_client) {
      userInfo.error = '115客户端未连接或Cookie无效。';
      storageInfo.error = '115客户端未连接或Cookie无效。';
    }
  }
  if (props.initialConfig?.fuse_enabled) {
    await getFuseStatus();
  }
  refreshing.value = false;
  actionMessage.value = '状态已刷新';
  actionMessageType.value = 'success';
  setTimeout(() => { actionMessage.value = null; }, 3000);
};

const getFuseStatus = async () => {
  fuseStatus.loading = true;
  fuseStatus.error = null;
  try {
    const result = await props.api.get(`plugin/${pluginId}/fuse_status`);
    if (result && result.code === 0 && result.data) {
      fuseStatus.mounted = Boolean(result.data.mounted);
      fuseStatus.mountpoint = result.data.mountpoint || null;
      fuseStatus.readdir_ttl = result.data.readdir_ttl || 60;
    } else {
      fuseStatus.error = result?.msg || '获取 FUSE 状态失败';
    }
  } catch (err) {
    fuseStatus.error = `获取 FUSE 状态失败: ${err.message || '未知错误'}`;
    console.error('获取 FUSE 状态失败:', err);
  } finally {
    fuseStatus.loading = false;
  }
};

const mountFuse = async () => {
  if (!props.initialConfig?.fuse_mountpoint) {
    actionMessage.value = '请先配置挂载点路径';
    actionMessageType.value = 'error';
    setTimeout(() => { actionMessage.value = null; }, 3000);
    return;
  }
  fuseStatus.mounting = true;
  fuseStatus.error = null;
  try {
    const result = await props.api.post(`plugin/${pluginId}/fuse_mount`, {
      mountpoint: props.initialConfig.fuse_mountpoint,
      readdir_ttl: props.initialConfig.fuse_readdir_ttl || 60,
    });
    if (result && result.code === 0) {
      actionMessage.value = 'FUSE 文件系统挂载成功';
      actionMessageType.value = 'success';
      await getFuseStatus();
    } else {
      fuseStatus.error = result?.msg || '挂载失败';
      actionMessage.value = result?.msg || '挂载失败';
      actionMessageType.value = 'error';
    }
  } catch (err) {
    fuseStatus.error = `挂载失败: ${err.message || '未知错误'}`;
    actionMessage.value = `挂载失败: ${err.message || '未知错误'}`;
    actionMessageType.value = 'error';
    console.error('挂载 FUSE 失败:', err);
  } finally {
    fuseStatus.mounting = false;
    setTimeout(() => { actionMessage.value = null; }, 3000);
  }
};

const unmountFuse = async () => {
  fuseStatus.unmounting = true;
  fuseStatus.error = null;
  try {
    const result = await props.api.post(`plugin/${pluginId}/fuse_unmount`);
    if (result && result.code === 0) {
      actionMessage.value = 'FUSE 文件系统卸载成功';
      actionMessageType.value = 'success';
      await getFuseStatus();
    } else {
      fuseStatus.error = result?.msg || '卸载失败';
      actionMessage.value = result?.msg || '卸载失败';
      actionMessageType.value = 'error';
    }
  } catch (err) {
    fuseStatus.error = `卸载失败: ${err.message || '未知错误'}`;
    actionMessage.value = `卸载失败: ${err.message || '未知错误'}`;
    actionMessageType.value = 'error';
    console.error('卸载 FUSE 失败:', err);
  } finally {
    fuseStatus.unmounting = false;
    setTimeout(() => { actionMessage.value = null; }, 3000);
  }
};

const handleConfirmFullSync = async () => {
  fullSyncConfirmDialog.value = false;
  await triggerFullSync();
};

const handleConfirmFullSyncDb = async () => {
  fullSyncDbConfirmDialog.value = false;
  await triggerFullSyncDb();
};

const triggerFullSync = async () => {
  syncLoading.value = true;
  actionLoading.value = true;
  error.value = null;
  actionMessage.value = null;
  try {
    if (!status.enabled) throw new Error('插件未启用，请先在配置页面启用插件');
    if (!status.has_client) throw new Error('插件未配置Cookie或Cookie无效，请先在配置页面设置115 Cookie');
    if (getPathsCount(props.initialConfig?.full_sync_strm_paths) === 0) {
      throw new Error('未配置全量同步路径，请先在配置页面设置同步路径');
    }
    const result = await props.api.post(`plugin/${pluginId}/full_sync`);
    if (result && result.code === 0) {
      actionMessage.value = result.msg || '全量同步任务已启动';
      actionMessageType.value = 'success';
      await getStatus();
    } else {
      throw new Error(result?.msg || '启动全量同步失败');
    }
  } catch (err) {
    error.value = `启动全量同步失败: ${err.message || '未知错误'}`;
    console.error('启动全量同步失败:', err);
  } finally {
    syncLoading.value = false;
    actionLoading.value = false;
  }
};

const triggerFullSyncDb = async () => {
  syncDbLoading.value = true;
  actionLoading.value = true;
  error.value = null;
  actionMessage.value = null;
  try {
    if (!status.enabled) throw new Error('插件未启用，请先在配置页面启用插件');
    if (!status.has_client) throw new Error('插件未配置Cookie或Cookie无效，请先在配置页面设置115 Cookie');
    const result = await props.api.post(`plugin/${pluginId}/full_sync_db`);
    if (result && result.code === 0) {
      actionMessage.value = result.msg || '全量同步数据库任务已启动';
      actionMessageType.value = 'success';
      await getStatus();
    } else {
      throw new Error(result?.msg || '启动全量同步数据库失败');
    }
  } catch (err) {
    error.value = `启动全量同步数据库失败: ${err.message || '未知错误'}`;
    console.error('启动全量同步数据库失败:', err);
  } finally {
    syncDbLoading.value = false;
    actionLoading.value = false;
  }
};

const defaultInteractiveGenStrm = () => ({
  minFileSizeFormatted: '',
  autoDownloadMediainfo: false,
  localPath: '',
  moviepilotTransfer: false,
  moviepilotTransferDownloadRmtAudioSub: false,
  iterFunction: 'iter_share_files_with_path',
  speedMode: 3,
});

const shareDialog = reactive({
  show: false,
  error: null,
  configs: [],
  globalMediaservers: [],
  globalMediaServerRefreshDelay: 0,
  globalMpMediaserverPaths: '',
  auditQueueEnabled: true,
  auditMaxWaitHours: 6,
  auditRetryIntervalMinutes: 30,
  interactiveGenStrm: defaultInteractiveGenStrm(),
  shareInteractiveGenStrmExpanded: [],
  cleanupPaths: [],
  timingShareStrmCleanup: false,
  cronShareStrmCleanup: '0 */12 * * *',
  deleteMode: 'plugin_ui',
  removeRelatedMediainfo: true,
  removeEmptyParentDirs: true,
  removeStaleTransferHistory: false,
  recordMissingMediaFromHistory: true,
  shareStrmCleanupExpanded: [],
});

const shareStrmCleanupScanLoading = ref(false);

const shareConfigDialog = reactive({
  show: false,
  error: null,
  editingIndex: -1,
  comment: '',
  enabled: true,
  shareLink: '',
  shareCode: '',
  shareReceive: '',
  sharePath: '/',
  localPath: '',
  minFileSizeFormatted: '',
  iterFunction: 'iter_share_files_with_path',
  speedMode: 3,
  moviepilotTransfer: false,
  moviepilotTransferDownloadRmtAudioSub: false,
  autoDownloadMediainfo: false,
  mediaServerRefresh: false,
  scrapeMetadata: false,
});

const speedModeItems = [
  { title: '最快', subtitle: '0.25s, 0.25s, 0.75s', value: 0 },
  { title: '快', subtitle: '0.5s, 0.5s, 1.5s', value: 1 },
  { title: '慢', subtitle: '1s, 1s, 2s', value: 2 },
  { title: '最慢', subtitle: '1.5s, 1.5s, 2s (推荐)', value: 3 },
];

const shareIteratorItems = [
  { title: 'iter_share_files_with_path（详细数据，默认）', value: 'iter_share_files_with_path' },
  { title: 'share_iter_files（高速简略）', value: 'share_iter_files' },
];

const mediaservers = ref([]);

const isShareDialogValid = computed(() => {
  return shareDialog.configs.length > 0 && shareDialog.configs.every((cfg) => {
    if (!cfg.local_path) return false;
    if (!cfg.share_link && !cfg.share_code) return false;
    if (cfg.share_code && !cfg.share_receive) return false;
    return true;
  });
});

const isShareConfigDialogValid = computed(() => {
  if (!shareConfigDialog.localPath) return false;
  if (!shareConfigDialog.shareLink && !shareConfigDialog.shareCode) return false;
  if (shareConfigDialog.shareCode && !shareConfigDialog.shareReceive) return false;
  return true;
});

const dirDialog = reactive({
  show: false,
  isLocal: true,
  loading: false,
  error: null,
  currentPath: '/',
  items: [],
  selectedPath: '',
  callback: null,
});

const openShareDialog = () => {
  shareDialog.show = true;
  shareDialog.error = null;
  shareConfigDialog.show = false;
  if (props.initialConfig) {
    shareDialog.configs = Array.isArray(props.initialConfig.share_strm_config)
      ? JSON.parse(JSON.stringify(props.initialConfig.share_strm_config))
      : [];
    shareDialog.globalMediaservers = Array.isArray(props.initialConfig.share_strm_mediaservers)
      ? [...props.initialConfig.share_strm_mediaservers]
      : [];
    shareDialog.globalMpMediaserverPaths = props.initialConfig.share_strm_mp_mediaserver_paths || '';
    shareDialog.globalMediaServerRefreshDelay = props.initialConfig.share_strm_media_server_refresh_delay || 0;
    shareDialog.auditQueueEnabled = props.initialConfig.share_audit_queue_enabled !== false;
    shareDialog.auditMaxWaitHours = Math.max(
      1,
      Math.round((props.initialConfig.share_audit_max_wait_seconds || 21600) / 3600),
    );
    shareDialog.auditRetryIntervalMinutes = Math.max(
      1,
      Math.round((props.initialConfig.share_audit_retry_interval_seconds || 1800) / 60),
    );

    const ig = props.initialConfig.share_interactive_gen_strm_config || {};
    shareDialog.interactiveGenStrm.minFileSizeFormatted = formatBytes(ig.min_file_size || 0);
    shareDialog.interactiveGenStrm.autoDownloadMediainfo = ig.auto_download_mediainfo || false;
    shareDialog.interactiveGenStrm.localPath = ig.local_path || '';
    shareDialog.interactiveGenStrm.moviepilotTransfer = ig.moviepilot_transfer || false;
    shareDialog.interactiveGenStrm.moviepilotTransferDownloadRmtAudioSub =
      ig.moviepilot_transfer_download_rmt_audio_sub || false;
    shareDialog.interactiveGenStrm.iterFunction = ig.iter_function || 'iter_share_files_with_path';
    shareDialog.interactiveGenStrm.speedMode = ig.speed_mode !== undefined ? ig.speed_mode : 3;

    const sc = props.initialConfig.share_strm_cleanup_config || {};
    shareDialog.cleanupPaths = Array.isArray(sc.cleanup_paths)
      ? sc.cleanup_paths.map((p) => String(p ?? ''))
      : [];
    shareDialog.timingShareStrmCleanup = sc.timing_share_strm_cleanup || false;
    shareDialog.cronShareStrmCleanup = sc.cron_share_strm_cleanup || '0 */12 * * *';
    shareDialog.deleteMode = sc.delete_mode || 'plugin_ui';
    shareDialog.removeRelatedMediainfo = sc.remove_related_mediainfo !== false;
    shareDialog.removeEmptyParentDirs = sc.remove_empty_parent_dirs !== false;
    shareDialog.removeStaleTransferHistory = !!sc.remove_stale_transfer_history;
    shareDialog.recordMissingMediaFromHistory = sc.record_missing_media_from_history !== false;
  }
};

const flushShareInteractiveGenStrmToInitialConfig = () => {
  if (!props.initialConfig) return;
  const m = shareDialog.interactiveGenStrm;
  const detailed = m.iterFunction === 'iter_share_files_with_path';
  props.initialConfig.share_interactive_gen_strm_config = {
    min_file_size: parseSize(m.minFileSizeFormatted) || null,
    auto_download_mediainfo: detailed && !m.moviepilotTransfer ? m.autoDownloadMediainfo : false,
    local_path: m.localPath || null,
    moviepilot_transfer: m.moviepilotTransfer,
    moviepilot_transfer_download_rmt_audio_sub: detailed && m.moviepilotTransfer
      ? m.moviepilotTransferDownloadRmtAudioSub
      : false,
    iter_function: m.iterFunction,
    speed_mode: m.speedMode,
  };
};

const flushShareAuditQueueToInitialConfig = () => {
  if (!props.initialConfig) return;
  const maxWaitHours = Math.max(1, Number(shareDialog.auditMaxWaitHours) || 6);
  const retryIntervalMinutes = Math.max(1, Number(shareDialog.auditRetryIntervalMinutes) || 30);
  if (retryIntervalMinutes * 60 > maxWaitHours * 3600) {
    throw new Error('审核检查间隔不能超过最长审核等待时间');
  }
  props.initialConfig.share_audit_queue_enabled = shareDialog.auditQueueEnabled;
  props.initialConfig.share_audit_max_wait_seconds = maxWaitHours * 3600;
  props.initialConfig.share_audit_retry_interval_seconds = retryIntervalMinutes * 60;
};

const flushShareStrmCleanupToInitialConfig = () => {
  if (!props.initialConfig) return;
  const lines = (shareDialog.cleanupPaths || []).map((s) => String(s).trim()).filter(Boolean);
  props.initialConfig.share_strm_cleanup_config = {
    cleanup_paths: lines,
    timing_share_strm_cleanup: shareDialog.timingShareStrmCleanup,
    cron_share_strm_cleanup: shareDialog.cronShareStrmCleanup || '0 */12 * * *',
    delete_mode: shareDialog.deleteMode,
    remove_related_mediainfo: shareDialog.removeRelatedMediainfo,
    remove_empty_parent_dirs: shareDialog.removeEmptyParentDirs,
    remove_stale_transfer_history: shareDialog.removeStaleTransferHistory,
    record_missing_media_from_history: shareDialog.recordMissingMediaFromHistory,
  };
};

const openInteractiveGenStrmDirSelector = () => {
  dirDialog.show = true;
  dirDialog.isLocal = true;
  dirDialog.loading = false;
  dirDialog.error = null;
  dirDialog.items = [];
  dirDialog.currentPath = shareDialog.interactiveGenStrm.localPath || '/';
  dirDialog.callback = (path) => {
    shareDialog.interactiveGenStrm.localPath = path;
  };
  loadDirContent();
};

const addShareStrmCleanupPath = () => {
  shareDialog.cleanupPaths.push('');
};

const removeShareStrmCleanupPath = (index) => {
  if (index < 0 || index >= shareDialog.cleanupPaths.length) return;
  shareDialog.cleanupPaths.splice(index, 1);
};

const openShareStrmCleanupDirSelector = (index) => {
  if (index < 0 || index >= shareDialog.cleanupPaths.length) return;
  dirDialog.show = true;
  dirDialog.isLocal = true;
  dirDialog.loading = false;
  dirDialog.error = null;
  dirDialog.items = [];
  const cur = String(shareDialog.cleanupPaths[index] || '').trim();
  dirDialog.currentPath = cur || '/';
  dirDialog.callback = (path) => {
    shareDialog.cleanupPaths[index] = path;
  };
  loadDirContent();
};

const closeShareDialog = () => {
  shareDialog.show = false;
  shareConfigDialog.show = false;
  shareDialog.configs = [];
  shareDialog.error = null;
  shareDialog.interactiveGenStrm = defaultInteractiveGenStrm();
  shareDialog.cleanupPaths = [];
};

const addShareConfig = () => {
  shareConfigDialog.editingIndex = -1;
  shareConfigDialog.comment = '';
  shareConfigDialog.enabled = true;
  shareConfigDialog.shareLink = '';
  shareConfigDialog.shareCode = '';
  shareConfigDialog.shareReceive = '';
  shareConfigDialog.sharePath = '/';
  shareConfigDialog.localPath = '';
  shareConfigDialog.minFileSizeFormatted = '';
  shareConfigDialog.iterFunction = 'iter_share_files_with_path';
  shareConfigDialog.speedMode = 3;
  shareConfigDialog.moviepilotTransfer = false;
  shareConfigDialog.moviepilotTransferDownloadRmtAudioSub = false;
  shareConfigDialog.autoDownloadMediainfo = false;
  shareConfigDialog.mediaServerRefresh = false;
  shareConfigDialog.scrapeMetadata = false;
  shareConfigDialog.error = null;
  shareConfigDialog.show = true;
};

const editShareConfig = (index) => {
  if (index < 0 || index >= shareDialog.configs.length) return;
  const config = shareDialog.configs[index];
  shareConfigDialog.editingIndex = index;
  shareConfigDialog.comment = config.comment || '';
  shareConfigDialog.enabled = config.enabled !== undefined ? config.enabled : true;
  shareConfigDialog.shareLink = config.share_link || '';
  shareConfigDialog.shareCode = config.share_code || '';
  shareConfigDialog.shareReceive = config.share_receive || '';
  shareConfigDialog.sharePath = config.share_path || '/';
  shareConfigDialog.localPath = config.local_path || '';
  shareConfigDialog.minFileSizeFormatted = formatBytes(config.min_file_size || 0);
  shareConfigDialog.iterFunction = config.iter_function || 'iter_share_files_with_path';
  shareConfigDialog.speedMode = config.speed_mode !== undefined ? config.speed_mode : 3;
  shareConfigDialog.moviepilotTransfer = config.moviepilot_transfer || false;
  shareConfigDialog.moviepilotTransferDownloadRmtAudioSub =
    config.moviepilot_transfer_download_rmt_audio_sub || false;
  shareConfigDialog.autoDownloadMediainfo = config.auto_download_mediainfo || false;
  shareConfigDialog.mediaServerRefresh = config.media_server_refresh || false;
  shareConfigDialog.scrapeMetadata = config.scrape_metadata || false;
  shareConfigDialog.error = null;
  shareConfigDialog.show = true;
};

const removeShareConfig = (index) => {
  if (index >= 0 && index < shareDialog.configs.length) {
    shareDialog.configs.splice(index, 1);
  }
};

const saveShareConfigs = async () => {
  shareConfigSaving.value = true;
  shareDialog.error = null;
  try {
    if (props.initialConfig) {
      props.initialConfig.share_strm_config = shareDialog.configs;
      props.initialConfig.share_strm_mediaservers = shareDialog.globalMediaservers.length > 0
        ? [...shareDialog.globalMediaservers]
        : null;
      props.initialConfig.share_strm_mp_mediaserver_paths = shareDialog.globalMpMediaserverPaths || null;
      props.initialConfig.share_strm_media_server_refresh_delay = shareDialog.globalMediaServerRefreshDelay || 0;
      flushShareAuditQueueToInitialConfig();
      flushShareInteractiveGenStrmToInitialConfig();
      flushShareStrmCleanupToInitialConfig();

      const result = await props.api.post(`plugin/${pluginId}/save_config`, props.initialConfig);
      if (result && result.code === 0) {
        actionMessage.value = '分享配置已保存';
        actionMessageType.value = 'success';
        await getStatus();
        closeShareDialog();
      } else {
        throw new Error(result?.msg || '保存配置失败');
      }
    } else {
      throw new Error('配置对象不存在');
    }
  } catch (err) {
    shareDialog.error = `保存配置失败: ${err.message || '未知错误'}`;
    console.error('保存配置失败:', err);
  } finally {
    shareConfigSaving.value = false;
  }
};

const closeShareConfigDialog = () => {
  shareConfigDialog.show = false;
  shareConfigDialog.editingIndex = -1;
  shareConfigDialog.error = null;
};

const saveShareConfig = () => {
  shareConfigDialog.error = null;
  if (!isShareConfigDialogValid.value) {
    shareConfigDialog.error = '请填写必填项';
    return;
  }
  const detailed = shareConfigDialog.iterFunction === 'iter_share_files_with_path';
  const cfg = {
    comment: shareConfigDialog.comment || null,
    enabled: shareConfigDialog.enabled,
    share_link: shareConfigDialog.shareLink || null,
    share_code: shareConfigDialog.shareCode || null,
    share_receive: shareConfigDialog.shareReceive || null,
    share_path: shareConfigDialog.sharePath || null,
    local_path: shareConfigDialog.localPath,
    min_file_size: parseSize(shareConfigDialog.minFileSizeFormatted) || null,
    iter_function: shareConfigDialog.iterFunction,
    speed_mode: shareConfigDialog.speedMode,
    moviepilot_transfer: shareConfigDialog.moviepilotTransfer,
    moviepilot_transfer_download_rmt_audio_sub: detailed && shareConfigDialog.moviepilotTransfer
      ? shareConfigDialog.moviepilotTransferDownloadRmtAudioSub
      : false,
    auto_download_mediainfo: detailed && !shareConfigDialog.moviepilotTransfer
      ? shareConfigDialog.autoDownloadMediainfo
      : false,
    media_server_refresh: shareConfigDialog.moviepilotTransfer ? false : shareConfigDialog.mediaServerRefresh,
    scrape_metadata: shareConfigDialog.moviepilotTransfer ? false : shareConfigDialog.scrapeMetadata,
  };

  if (shareConfigDialog.editingIndex >= 0) {
    shareDialog.configs[shareConfigDialog.editingIndex] = cfg;
  } else {
    shareDialog.configs.push(cfg);
  }
  closeShareConfigDialog();
};

const openShareConfigDirSelector = (type) => {
  dirDialog.show = true;
  dirDialog.isLocal = type === 'local';
  dirDialog.loading = false;
  dirDialog.error = null;
  dirDialog.items = [];
  dirDialog.currentPath = dirDialog.isLocal ? (shareConfigDialog.localPath || '/') : '/';
  dirDialog.callback = (path) => {
    if (dirDialog.isLocal) shareConfigDialog.localPath = path;
  };
  loadDirContent();
};

const loadDirContent = async () => {
  dirDialog.loading = true;
  dirDialog.error = null;
  dirDialog.items = [];
  try {
    if (dirDialog.isLocal) {
      try {
        const response = await props.api.post('storage/list', {
          path: dirDialog.currentPath || '/',
          type: 'share',
          flag: 'ROOT',
        });
        const items = Array.isArray(response) ? response : response?.data;
        if (Array.isArray(items)) {
          dirDialog.items = items
            .filter((item) => item.type === 'dir')
            .map((item) => ({ name: item.name, path: item.path, is_dir: true }))
            .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
        } else {
          throw new Error(response?.message || '浏览目录失败：无效响应');
        }
      } catch (err) {
        console.error('浏览本地目录失败:', err);
        dirDialog.error = `浏览本地目录失败: ${err.message || '未知错误'}`;
        dirDialog.items = [];
      }
    } else {
      if (!props.initialConfig?.cookies || props.initialConfig?.cookies.trim() === '') {
        throw new Error('请先设置115 Cookie才能浏览网盘目录');
      }
      const result = await props.api.get(
        `plugin/${pluginId}/browse_dir?path=${encodeURIComponent(dirDialog.currentPath)}&is_local=${dirDialog.isLocal}`,
      );
      if (result && result.code === 0 && result.data) {
        dirDialog.items = result.data.items.filter((item) => item.is_dir);
        dirDialog.currentPath = result.data.path || dirDialog.currentPath;
      } else {
        throw new Error(result?.msg || '获取网盘目录内容失败');
      }
    }
  } catch (err) {
    console.error('加载目录内容失败:', err);
    dirDialog.error = err.message || '获取目录内容失败';
    if (err.message.includes('Cookie') || err.message.includes('cookie')) {
      dirDialog.items = [];
    }
  } finally {
    dirDialog.loading = false;
  }
};

const selectDir = (item) => {
  if (!item || !item.is_dir) return;
  if (item.path) {
    dirDialog.currentPath = item.path;
    loadDirContent();
  }
};

const navigateToParentDir = () => {
  const path = dirDialog.currentPath;
  if (!dirDialog.isLocal) {
    if (path === '/') return;
    let current = path.replace(/\\/g, '/');
    if (current.length > 1 && current.endsWith('/')) current = current.slice(0, -1);
    const parent = current.substring(0, current.lastIndexOf('/'));
    dirDialog.currentPath = parent === '' ? '/' : parent;
    loadDirContent();
    return;
  }
  if (path === '/' || path === 'C:\\' || path === 'C:/') return;
  const normalizedPath = path.replace(/\\/g, '/');
  const parts = normalizedPath.split('/').filter(Boolean);
  if (parts.length === 0) {
    dirDialog.currentPath = '/';
  } else if (parts.length === 1 && normalizedPath.includes(':')) {
    dirDialog.currentPath = `${parts[0]}:/`;
  } else {
    parts.pop();
    dirDialog.currentPath = parts.length === 0 ? '/' : `${normalizedPath.startsWith('/') ? '/' : ''}${parts.join('/')}/`;
  }
  loadDirContent();
};

const confirmDirSelection = () => {
  if (!dirDialog.currentPath) return;
  let processedPath = dirDialog.currentPath;
  if (
    processedPath !== '/' &&
    !/^[a-zA-Z]:[\\\/]$/.test(processedPath) &&
    (processedPath.endsWith('/') || processedPath.endsWith('\\'))
  ) {
    processedPath = processedPath.slice(0, -1);
  }
  if (typeof dirDialog.callback === 'function') {
    dirDialog.callback(processedPath);
  }
  closeDirDialog();
};

const closeDirDialog = () => {
  dirDialog.show = false;
  dirDialog.items = [];
  dirDialog.error = null;
};

const runShareStrmCleanupScan = async () => {
  shareStrmCleanupScanLoading.value = true;
  shareDialog.error = null;
  try {
    if (!props.initialConfig) throw new Error('配置对象不存在');
    flushShareStrmCleanupToInitialConfig();
    const saveResult = await props.api.post(`plugin/${pluginId}/save_config`, props.initialConfig);
    if (!saveResult || saveResult.code !== 0) {
      throw new Error(saveResult?.msg || '保存配置失败');
    }
    const result = await props.api.post(`plugin/${pluginId}/share_strm_cleanup_scan`);
    if (result && result.code === 0) {
      actionMessage.value = result.msg || '分享 STRM 清理扫描已启动';
      actionMessageType.value = 'success';
    } else {
      throw new Error(result?.msg || '启动扫描失败');
    }
  } catch (err) {
    shareDialog.error = `启动扫描失败: ${err.message || '未知错误'}`;
    console.error('分享 STRM 清理扫描:', err);
  } finally {
    shareStrmCleanupScanLoading.value = false;
  }
};

const executeShareSync = async () => {
  shareSyncLoading.value = true;
  shareDialog.error = null;
  try {
    if (shareDialog.configs.length === 0) throw new Error('请至少添加一个分享配置');
    if (props.initialConfig) {
      props.initialConfig.share_strm_config = shareDialog.configs;
      props.initialConfig.share_strm_mediaservers = shareDialog.globalMediaservers.length > 0
        ? [...shareDialog.globalMediaservers]
        : null;
      props.initialConfig.share_strm_mp_mediaserver_paths = shareDialog.globalMpMediaserverPaths || null;
      props.initialConfig.share_strm_media_server_refresh_delay = shareDialog.globalMediaServerRefreshDelay || 0;
      flushShareAuditQueueToInitialConfig();
      flushShareInteractiveGenStrmToInitialConfig();
      flushShareStrmCleanupToInitialConfig();
      await props.api.post(`plugin/${pluginId}/save_config`, props.initialConfig);
    }
    const result = await props.api.post(`plugin/${pluginId}/share_sync`);
    if (result && result.code === 0) {
      actionMessage.value = result.msg || '分享同步任务已启动';
      actionMessageType.value = 'success';
      await getStatus();
      closeShareDialog();
    } else {
      throw new Error(result?.msg || '启动分享同步失败');
    }
  } catch (err) {
    shareDialog.error = `启动分享同步失败: ${err.message || '未知错误'}`;
    console.error('启动分享同步失败:', err);
  } finally {
    shareSyncLoading.value = false;
  }
};

const buildAvailablePaths = () => {
  const paths = [];
  const pathSet = new Set();
  getCachedPaths().forEach((p) => {
    if (p && !pathSet.has(p)) {
      paths.push({ label: `📁 ${p}`, path: p, type: 'cached' });
      pathSet.add(p);
    }
  });
  if (Array.isArray(props.initialConfig?.offline_download_paths)) {
    props.initialConfig.offline_download_paths.forEach((p) => {
      if (p && typeof p === 'string' && p.trim() && !pathSet.has(p.trim())) {
        paths.push({ label: `⚙️ ${p.trim()}`, path: p.trim(), type: 'config' });
        pathSet.add(p.trim());
      }
    });
  }
  offlineDownloadDialog.availablePaths = paths;
  offlineDownloadDialog.availablePathStrings = paths.map((p) => p.path);
};

const getPathLabel = (path) => {
  if (!path) return '';
  const found = offlineDownloadDialog.availablePaths.find((p) => p.path === path);
  return found ? found.label : path;
};

const openOfflineDownloadDialog = () => {
  offlineDownloadDialog.show = true;
  offlineDownloadDialog.activeTab = 'add';
  offlineDownloadDialog.error = null;
  offlineDownloadDialog.addError = null;
  buildAvailablePaths();
};

const closeOfflineDownloadDialog = () => {
  offlineDownloadDialog.show = false;
  offlineDownloadDialog.tasks = [];
  offlineDownloadDialog.totalTasks = 0;
  offlineDownloadDialog.links = '';
  offlineDownloadDialog.destPath = '';
};

const fetchOfflineTasks = async ({ page, itemsPerPage }) => {
  offlineDownloadDialog.loading = true;
  offlineDownloadDialog.error = null;
  try {
    const result = await props.api.post(`plugin/${pluginId}/offline_tasks`, {
      page,
      limit: itemsPerPage,
    });
    if (result && result.code === 0 && result.data) {
      offlineDownloadDialog.tasks = result.data.tasks || [];
      offlineDownloadDialog.totalTasks = result.data.total || 0;
    } else {
      throw new Error(result?.msg || '获取离线任务列表失败');
    }
  } catch (err) {
    offlineDownloadDialog.error = `获取任务失败: ${err.message || '未知错误'}`;
    offlineDownloadDialog.tasks = [];
    offlineDownloadDialog.totalTasks = 0;
  } finally {
    offlineDownloadDialog.loading = false;
  }
};

const addOfflineTask = async () => {
  if (!offlineDownloadDialog.links.trim()) {
    offlineDownloadDialog.addError = '下载链接不能为空。';
    return;
  }
  offlineDownloadDialog.adding = true;
  offlineDownloadDialog.addError = null;
  try {
    const links = offlineDownloadDialog.links.split('\n').map((l) => l.trim()).filter(Boolean);
    const result = await props.api.post(`plugin/${pluginId}/add_offline_task`, {
      links,
      path: offlineDownloadDialog.destPath || null,
    });
    if (result && result.code === 0) {
      actionMessage.value = result.msg || '离线任务添加成功';
      actionMessageType.value = 'success';
      if (offlineDownloadDialog.destPath && offlineDownloadDialog.destPath.trim()) {
        addPathToCache(offlineDownloadDialog.destPath);
        buildAvailablePaths();
      }
      offlineDownloadDialog.links = '';
      offlineDownloadDialog.destPath = '';
      offlineDownloadDialog.activeTab = 'tasks';
      fetchOfflineTasks({ page: 1, itemsPerPage: offlineDownloadDialog.itemsPerPage });
    } else {
      throw new Error(result?.msg || '添加离线任务失败');
    }
  } catch (err) {
    offlineDownloadDialog.addError = `添加任务失败: ${err.message || '未知错误'}`;
  } finally {
    offlineDownloadDialog.adding = false;
  }
};

const openOfflineDestDirSelector = () => {
  dirDialog.show = true;
  dirDialog.isLocal = false;
  dirDialog.loading = false;
  dirDialog.error = null;
  dirDialog.items = [];
  dirDialog.currentPath = offlineDownloadDialog.destPath || '/';
  dirDialog.callback = (path) => {
    offlineDownloadDialog.destPath = path;
  };
  loadDirContent();
};

const getParsedPaths = (pathString) => {
  if (!pathString) return [];
  try {
    return pathString
      .split('\n')
      .filter((line) => line.trim() && line.includes('#'))
      .map((p) => {
        const parts = p.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
  } catch {
    return [];
  }
};

const getParsedPanTransferPaths = (pathString) => {
  if (!pathString) return [];
  try {
    return pathString
      .split('\n')
      .filter((line) => line.trim())
      .map((path) => ({ path }));
  } catch {
    return [];
  }
};

watch(
  () => props.initialConfig?.fuse_enabled,
  (enabled) => {
    if (enabled) getFuseStatus();
    else {
      fuseStatus.mounted = false;
      fuseStatus.mountpoint = null;
    }
  },
);

watch(
  () => props.initialConfig,
  (newConfig) => {
    if (newConfig) {
      status.enabled = newConfig.enabled || false;
      status.has_client = Boolean(newConfig.cookies && newConfig.cookies.trim() !== '');
      if (newConfig.sync_del_enabled) {
        loadSyncDelHistory();
        if (syncDelHistoryRefreshTimer) clearInterval(syncDelHistoryRefreshTimer);
        syncDelHistoryRefreshTimer = setInterval(() => {
          if (props.initialConfig?.sync_del_enabled) loadSyncDelHistory();
        }, 30000);
      } else {
        syncDelHistory.value = [];
        if (syncDelHistoryRefreshTimer) {
          clearInterval(syncDelHistoryRefreshTimer);
          syncDelHistoryRefreshTimer = null;
        }
      }
    }
  },
  { immediate: true },
);

watch(
  () => syncDelHistoryDialog.show,
  (isOpen) => {
    if (isOpen) {
      syncDelHistoryPage.value = 1;
      loadSyncDelHistory();
    }
  },
);

const loadSyncDelHistory = async () => {
  if (!props.initialConfig?.sync_del_enabled) {
    syncDelHistory.value = [];
    return;
  }
  syncDelHistoryLoading.value = true;
  try {
    const response = await props.api.get(
      `plugin/${pluginId}/get_sync_del_history?page=${syncDelHistoryPage.value}&limit=${syncDelHistoryLimit.value}`,
    );
    if (response && response.code === 0 && response.data) {
      if (response.data.items && Array.isArray(response.data.items)) {
        syncDelHistory.value = response.data.items;
        syncDelHistoryTotal.value = response.data.total || 0;
      } else if (Array.isArray(response.data)) {
        syncDelHistory.value = response.data.sort((a, b) => {
          const timeA = new Date(a.del_time || 0).getTime();
          const timeB = new Date(b.del_time || 0).getTime();
          return timeB - timeA;
        });
        syncDelHistoryTotal.value = response.data.length;
      } else {
        syncDelHistory.value = [];
        syncDelHistoryTotal.value = 0;
      }
    } else {
      syncDelHistory.value = [];
      syncDelHistoryTotal.value = 0;
    }
  } catch (err) {
    console.error('加载同步删除历史失败:', err);
    syncDelHistory.value = [];
    syncDelHistoryTotal.value = 0;
  } finally {
    syncDelHistoryLoading.value = false;
  }
};

const confirmDeleteHistory = (item) => {
  if (!item || !item.unique) return;
  deleteHistoryConfirmDialog.item = item;
  deleteHistoryConfirmDialog.show = true;
};

const handleConfirmDeleteHistory = async () => {
  const unique = deleteHistoryConfirmDialog.item?.unique;
  if (!unique) return;
  deleteHistoryConfirmDialog.show = false;
  await deleteSyncDelHistory(unique);
};

const deleteSyncDelHistory = async (unique) => {
  if (!unique) return;
  deletingHistoryId.value = unique;
  try {
    const response = await props.api.post(`plugin/${pluginId}/delete_sync_del_history`, { key: unique });
    if (response && response.code === 0) {
      actionMessage.value = response.msg || '删除成功';
      actionMessageType.value = 'success';
      if (syncDelHistory.value.length === 1 && syncDelHistoryPage.value > 1) {
        syncDelHistoryPage.value--;
      }
      await loadSyncDelHistory();
    } else {
      actionMessage.value = response?.msg || '删除失败';
      actionMessageType.value = 'error';
    }
  } catch (err) {
    actionMessage.value = `删除失败: ${err.message || '未知错误'}`;
    actionMessageType.value = 'error';
  } finally {
    deletingHistoryId.value = null;
  }
};

const confirmDeleteAllHistory = () => {
  if (syncDelHistoryTotal.value === 0) return;
  deleteAllHistoryConfirmDialog.value = true;
};

const handleConfirmDeleteAllHistory = async () => {
  deleteAllHistoryConfirmDialog.value = false;
  await deleteAllSyncDelHistory();
};

const deleteAllSyncDelHistory = async () => {
  deletingAllHistory.value = true;
  try {
    const response = await props.api.post(`plugin/${pluginId}/delete_all_sync_del_history`);
    if (response && response.code === 0) {
      actionMessage.value = response.msg || '全部删除成功';
      actionMessageType.value = 'success';
      syncDelHistoryPage.value = 1;
      await loadSyncDelHistory();
    } else {
      actionMessage.value = response?.msg || '删除失败';
      actionMessageType.value = 'error';
    }
  } catch (err) {
    actionMessage.value = `删除失败: ${err.message || '未知错误'}`;
    actionMessageType.value = 'error';
  } finally {
    deletingAllHistory.value = false;
  }
};

async function fetchUserStorageStatus() {
  userInfo.loading = true;
  userInfo.error = null;
  storageInfo.loading = true;
  storageInfo.error = null;
  try {
    const response = await props.api.get(`plugin/${pluginId}/user_storage_status`);
    if (response && response.success) {
      if (response.user_info) Object.assign(userInfo, response.user_info);
      else userInfo.error = '未能获取有效的用户信息。';
      if (response.storage_info) Object.assign(storageInfo, response.storage_info);
      else storageInfo.error = '未能获取有效的存储空间信息。';
    } else {
      const errMsg = response?.error_message || '获取用户和存储信息失败。';
      userInfo.error = errMsg;
      storageInfo.error = errMsg;
      if (errMsg.includes('Cookie') || errMsg.includes('未配置')) {
        status.has_client = false;
      }
    }
  } catch (err) {
    const msg = `请求用户/存储状态时出错: ${err.message || '未知网络错误'}`;
    userInfo.error = msg;
    storageInfo.error = msg;
  } finally {
    userInfo.loading = false;
    storageInfo.loading = false;
  }
}

onMounted(async () => {
  await getStatus();
  if (status.has_client && props.initialConfig?.cookies) {
    await fetchUserStorageStatus();
  } else {
    userInfo.loading = false;
    storageInfo.loading = false;
    if (!props.initialConfig?.cookies) {
      userInfo.error = '请先配置115 Cookie。';
      storageInfo.error = '请先配置115 Cookie。';
    } else if (!status.has_client) {
      userInfo.error = '115客户端未连接或Cookie无效。';
      storageInfo.error = '115客户端未连接或Cookie无效。';
    }
  }
  try {
    const data = await props.api.get(`plugin/${pluginId}/get_config`);
    if (data && data.mediaservers) {
      mediaservers.value = data.mediaservers;
    }
  } catch (err) {
    console.error('加载媒体服务器列表失败:', err);
  }
  if (props.initialConfig?.fuse_enabled) {
    await getFuseStatus();
  }
  if (props.initialConfig?.sync_del_enabled) {
    await loadSyncDelHistory();
    syncDelHistoryRefreshTimer = setInterval(() => {
      if (props.initialConfig?.sync_del_enabled) loadSyncDelHistory();
    }, 30000);
  }
});

onBeforeUnmount(() => {
  if (syncDelHistoryRefreshTimer) {
    clearInterval(syncDelHistoryRefreshTimer);
    syncDelHistoryRefreshTimer = null;
  }
});
</script>

<style scoped>
.p115-bento-stage {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 14px;
  align-items: stretch;
}

.p115-col-12 { grid-column: span 12; }
.p115-col-7 { grid-column: span 7; }
.p115-col-6 { grid-column: span 6; }
.p115-col-5 { grid-column: span 5; }

.p115-account-box {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.p115-account-profile {
  display: flex;
  align-items: center;
  gap: 12px;
}

.p115-avatar-ring {
  padding: 2px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--p115-blue), var(--p115-pink));
  flex-shrink: 0;
}

.p115-account-name {
  font-size: 0.96rem;
  font-weight: 650;
  color: var(--p115-text-primary);
}

.p115-account-meta {
  font-size: 0.75rem;
  color: var(--p115-text-secondary);
  margin-top: 2px;
}

.p115-storage-panel {
  padding: 10px 12px;
  border-radius: 11px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
}

.p115-feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(195px, 1fr));
  gap: 9px;
}

.p115-feature-tile {
  appearance: none;
  border: 1px solid var(--p115-border-hairline);
  background: var(--p115-bg-inset);
  border-radius: 11px;
  padding: 10px 12px;
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
  color: var(--p115-text-primary);
  text-align: left;
  transition:
    transform 0.12s var(--p115-press),
    border-color 0.2s ease,
    background-color 0.2s ease;
}

.p115-feature-tile:hover {
  border-color: var(--p115-border-accent);
  background: var(--p115-bg-hover);
}

.p115-feature-tile:active {
  transform: scale(0.975);
}

.p115-feature-name {
  font-size: 0.82rem;
  font-weight: 560;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.p115-fuse-kv {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.p115-fuse-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 9px;
  background: var(--p115-bg-inset);
  font-size: 0.8rem;
}

.p115-upload-flow-card {
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
}

.p115-dock-scroll {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  max-width: 100%;
}

.p115-dock-scroll::-webkit-scrollbar {
  display: none;
}

@keyframes p115Spin {
  to { transform: rotate(360deg); }
}

.p115-spin-active {
  animation: p115Spin 1.4s linear infinite;
}

@keyframes p115Pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(1.25); }
}

.p115-pulse-dot {
  animation: p115Pulse 1.6s ease-in-out infinite;
}

@media (max-width: 900px) {
  .p115-col-7,
  .p115-col-6,
  .p115-col-5 {
    grid-column: span 12;
  }
}

@media (max-width: 599px) {
  .p115-bento-stage {
    gap: 10px;
  }

  .p115-feature-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 7px;
  }

  .p115-feature-tile {
    min-width: 0;
    padding: 9px 10px;
    gap: 6px;
  }

  .p115-feature-name {
    font-size: 0.76rem;
  }

  .p115-window-footer {
    flex-wrap: nowrap;
    gap: 6px;
  }

  .p115-dock-scroll {
    flex: 1 1 0%;
    min-width: 0;
  }
}

@media (max-width: 370px) {
  .p115-feature-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
