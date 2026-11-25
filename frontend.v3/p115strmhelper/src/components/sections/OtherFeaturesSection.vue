<template>
  <div class="p115-section-stack">
    <!-- Top Segmented Control for 8 Feature Sub-Modules -->
    <div class="p115-subnav-bar">
      <AppleSegmentedControl v-model="otherSubTab" :items="subTabItems" />
    </div>

    <!-- ===================================================================
         1. 同步删除 (tab-sync-del)
         =================================================================== -->
    <div v-if="otherSubTab === 'tab-sync-del'" class="p115-section-stack">
      <AppleSettingsGroup
        title="Emby 媒体库同步删除"
        subtitle="在 Emby 中删除影片时联动删除本地 STRM、整理记录及可选 115 源文件"
        icon="mdi-delete-sweep-outline"
      >
        <AppleSettingsRow title="启用同步删除" description="监听媒体库删除回调并联动执行清理">
          <v-switch v-model="config.sync_del_enabled" color="warning" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="发送通知" description="同步删除执行完成后发送消息通知">
          <v-switch v-model="config.sync_del_notify" color="success" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="删除源文件" description="同时删除 115 网盘中对应的媒体源文件（高危操作请确认映射准确）">
          <v-switch v-model="config.sync_del_source" color="error" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="强制删除文件" description="绕过额外保护直接从 115 网盘执行文件删除">
          <v-switch v-model="config.sync_del_p115_force_delete_files" color="warning" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="开启多版本删除"
          description="将电影和电视剧季删除改为单部/单集精准删除以防止误删其它版本；无多版本需求推荐关闭以提升效率"
        >
          <v-switch v-model="config.sync_del_remove_versions" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体服务器"
          description="用于获取 TMDB ID，仅支持 Emby"
          wide-control
        >
          <v-select
            v-model="config.sync_del_mediaservers"
            :items="embyMediaservers"
            label="选择 Emby 服务器"
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
        title="三端媒体库路径映射"
        subtitle="媒体服务器 STRM 路径 ↔ MoviePilot 本地路径 ↔ 115 网盘媒体库路径"
        icon="mdi-routes"
        padded
      >
        <PathMappingComposer
          mode="triple"
          key-prefix="sync-del"
          :items="syncDelLibraryPaths"
          add-label="添加三端路径映射"
          @add="addPath('syncDelLibrary')"
          @remove="(i) => removePath(i, 'syncDelLibrary')"
          @browse-triple="({ index, side, field }) => openDirSelector(index, side, 'syncDelLibrary', field)"
        />

        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• <strong>媒体服务器STRM路径：</strong>媒体服务器中 STRM 文件的实际路径</div>
            <div>• <strong>MoviePilot路径：</strong>MoviePilot 中对应的路径</div>
            <div>• <strong>115网盘媒体库路径：</strong>115 网盘中媒体库的路径</div>
          </div>
        </div>

        <div class="p115-callout p115-callout--warn mt-2">
          <v-icon size="16" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
          <div>
            <div>• 不正确配置会导致查询不到转移记录！</div>
            <div>• 需要使用神医助手PRO且版本在 <strong>v3.0.0.3</strong> 及以上，或神医助手社区版且版本在 <strong>v2.0.0.27</strong> 及以上！</div>
            <div>• 同步删除多版本功能需要使用神医助手Pro <strong>v3.0.0.22</strong> 才支持！</div>
          </div>
        </div>
      </AppleSettingsGroup>
    </div>

    <!-- ===================================================================
         2. 频道搜索 (tab-tg-search)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-tg-search'" class="p115-section-stack">
      <AppleSettingsGroup
        title="自定义 Telegram 资源频道"
        subtitle="配置用于 /sh 聚合检索 115 分享链接的 Telegram 公开频道"
        icon="mdi-send-circle-outline"
        padded
      >
        <template #action>
          <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="openImportDialog">
            <v-icon size="15" icon="mdi-code-json" />
            <span>JSON 一键导入</span>
          </button>
        </template>

        <div class="d-flex flex-column gap-2">
          <div
            v-for="(channel, index) in tgChannels"
            :key="`tg-ch-${index}`"
            class="p115-item-card p115-tg-row"
          >
            <v-text-field
              v-model="channel.name"
              label="频道名称"
              placeholder="例如：爱影115资源分享频道"
              density="compact"
              variant="outlined"
              hide-details
            />
            <v-text-field
              v-model="channel.id"
              label="频道 ID"
              placeholder="例如：ayzgzf"
              density="compact"
              variant="outlined"
              hide-details
              class="p115-mono"
            />
            <button
              type="button"
              class="p115-btn p115-btn--icon p115-btn--danger"
              title="删除此频道"
              @click="removeTgChannel(index)"
            >
              <v-icon size="16" icon="mdi-trash-can-outline" />
            </button>
          </div>

          <div class="mt-1">
            <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="addTgChannel">
              <v-icon size="15" icon="mdi-plus" />
              <span>添加频道</span>
            </button>
          </div>
        </div>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="RE0 搜索 (原 HDHive)"
        subtitle="与 Telegram 检索结果合并展示，仅返回 115 网盘资源，确认转存时才解锁积分"
        icon="mdi-movie-search-outline"
      >
        <AppleSettingsRow
          title="启用 RE0 搜索"
          description="账户密码与「RE0 签到」页共用，任一页面修改会自动同步"
        >
          <v-switch v-model="config.hdhive_search_enabled" color="primary" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="RE0 账户" wide-control>
          <v-text-field
            v-model="config.hdhive_checkin_username"
            label="RE0 账户"
            autocomplete="username"
            density="compact"
            variant="outlined"
            hide-details
            :disabled="!config.hdhive_search_enabled"
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="RE0 密码" wide-control>
          <v-text-field
            v-model="config.hdhive_checkin_password"
            label="RE0 密码"
            :type="showRe0Pass ? 'text' : 'password'"
            autocomplete="new-password"
            density="compact"
            variant="outlined"
            hide-details
            :disabled="!config.hdhive_search_enabled"
          >
            <template #append-inner>
              <button
                type="button"
                class="p115-eye-btn"
                @click="showRe0Pass = !showRe0Pass"
              >
                <v-icon size="16" :icon="showRe0Pass ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" />
              </button>
            </template>
          </v-text-field>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="font-weight-bold mb-0.5">频道搜索说明（/sh）：</div>
          <div>• 请至少配置 <strong>Telegram 频道</strong> 或 <strong>启用 RE0 搜索并填写账户密码</strong>，否则无法使用 <code class="p115-mono">/sh</code> 检索资源</div>
          <div>• RE0 使用浏览器自动化拉取资源；若遇 Cloudflare 验证，请为 MoviePilot 配置代理</div>
          <div>• RE0 与 TG 结果会合并展示；RE0 仅展示 115 网盘类资源，积分需求在列表中可见，确认转存时才解锁</div>
        </div>
      </div>
    </div>

    <!-- ===================================================================
         3. 定期清理 (tab-cleanup)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-cleanup'" class="p115-section-stack">
      <div class="p115-callout p115-callout--error">
        <v-icon size="18" color="error" icon="mdi-alert-octagon-outline" class="mt-0.5 flex-shrink-0" />
        <span><strong>注意：</strong>清空「回收站 / 最近接收」后文件不可恢复，如果产生重要数据丢失本程序不负责！</span>
      </div>

      <AppleSettingsGroup
        title="115 回收站与最近接收定时清理"
        subtitle="按设定 Cron 周期自动清理云盘空间"
        icon="mdi-broom"
      >
        <AppleSettingsRow title="清空回收站" description="定时清空 115 网盘回收站中的全部文件">
          <v-switch v-model="config.clear_recyclebin_enabled" color="error" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="清空最近接收目录" description="定时清空 115 网盘最近接收目录中的文件">
          <v-switch v-model="config.clear_receive_path_enabled" color="error" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="115 访问密码" description="清空回收站所需的 115 网盘安全密码" wide-control>
          <v-text-field
            v-model="config.password"
            label="115 安全密码"
            :type="show115SafePass ? 'text' : 'password'"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #append-inner>
              <button
                type="button"
                class="p115-eye-btn"
                @click="show115SafePass = !show115SafePass"
              >
                <v-icon size="16" :icon="show115SafePass ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" />
              </button>
            </template>
          </v-text-field>
        </AppleSettingsRow>

        <AppleSettingsRow title="清理周期" description="设置清理任务的执行周期" wide-control>
          <VCronField v-model="config.cron_clear" label="清理周期" density="compact" hide-details />
        </AppleSettingsRow>
      </AppleSettingsGroup>
    </div>

    <!-- ===================================================================
         4. 多端播放 (tab-same-playback)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-same-playback'" class="p115-section-stack">
      <AppleSettingsGroup
        title="多设备同步播放"
        subtitle="支持多个设备同时播放同一影片"
        icon="mdi-devices"
      >
        <AppleSettingsRow title="启用多端播放" description="开启后允许在合规范围内多端同时拉取同一影片流">
          <v-switch v-model="config.same_playback" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <div class="p115-callout p115-callout--warn">
        <v-icon size="18" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="font-weight-bold mb-0.5">使用限制：</div>
          <div>• 最多支持双 IP 同时播放</div>
          <div>• 禁止多 IP 滥用</div>
          <div>• 违规操作可能导致账号封禁</div>
        </div>
      </div>
    </div>

    <!-- ===================================================================
         5. RE0 签到 (tab-hdhive-checkin)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-hdhive-checkin'" class="p115-section-stack">
      <AppleSettingsGroup
        title="RE0 (原 HDHive) 自动随机签到"
        subtitle="每日签到与赌狗签到互斥二选一，支持时间段内随机时刻执行"
        icon="mdi-calendar-check-outline"
      >
        <AppleSettingsRow title="签到模式" description="选择每日稳健签到或随机积分赌狗签到" wide-control>
          <AppleSegmentedControl v-model="re0CheckinMode" :items="re0CheckinModeItems" block />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="签到随机时间段"
          description="格式 HH:MM-HH:MM，例如 06:30-09:45"
          wide-control
        >
          <v-text-field
            v-model="config.hdhive_checkin_time_range"
            placeholder="06:00-09:00"
            density="compact"
            variant="outlined"
            hide-details
            class="p115-mono"
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="RE0 账户" description="与「频道搜索 → RE0 搜索」共用同一账户" wide-control>
          <v-text-field
            v-model="config.hdhive_checkin_username"
            label="RE0 账户"
            autocomplete="username"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="RE0 密码" wide-control>
          <v-text-field
            v-model="config.hdhive_checkin_password"
            label="RE0 密码"
            :type="showRe0Pass ? 'text' : 'password'"
            autocomplete="new-password"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #append-inner>
              <button
                type="button"
                class="p115-eye-btn"
                @click="showRe0Pass = !showRe0Pass"
              >
                <v-icon size="16" :icon="showRe0Pass ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" />
              </button>
            </template>
          </v-text-field>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="font-weight-bold mb-0.5">RE0 签到说明：</div>
          <div>• 站点已更名为 RE0（原 HDHive）：https://re0.me/；与「频道搜索 → RE0 搜索」<strong>共用</strong>同一配置</div>
          <div>• 每日签到与赌狗签到<strong>只能二选一</strong>开启；启用后将在设定时间窗口内<strong>每天随机一刻</strong>执行一次登录并签到</div>
          <div>• 也可在 Telegram 等渠道发送 <code class="p115-mono">/hdhivechin</code> 手动触发签到</div>
        </div>
      </div>
    </div>

    <!-- ===================================================================
         6. 115 签到 (tab-p115-checkin)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-p115-checkin'" class="p115-section-stack">
      <AppleSettingsGroup
        title="115 网盘每日随机签到"
        subtitle="无需额外账号，复用已配置的非 Web 客户端 Cookie 自动签到"
        icon="mdi-check-decagram-outline"
      >
        <AppleSettingsRow title="115 每日签到" description="开启后每天在时间窗口内随机一刻自动签到">
          <v-switch v-model="config.p115_checkin_enabled" color="primary" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="签到随机时间段"
          description="格式 HH:MM-HH:MM，例如 06:30-09:45"
          wide-control
        >
          <v-text-field
            v-model="config.p115_checkin_time_range"
            placeholder="06:00-09:00"
            density="compact"
            variant="outlined"
            hide-details
            class="p115-mono"
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="font-weight-bold mb-0.5">115 签到说明：</div>
          <div>• 无需额外账号，使用已配置的 115 Cookie 自动签到</div>
          <div>• 启用后将在设定时间窗口内<strong>每天随机一刻</strong>执行一次签到</div>
          <div>• 签到功能<strong>不支持 web 类型 Cookie</strong>，请使用其他客户端类型扫码登录</div>
          <div>• 也可在 Telegram 等渠道发送 <code class="p115-mono">/p115_checkin</code> 手动触发签到</div>
        </div>
      </div>
    </div>

    <!-- ===================================================================
         7. 实用工具 (tab-utility)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-utility'" class="p115-section-stack">
      <AppleSettingsGroup
        title="整理与覆盖增强工具集"
        subtitle="解决 STRM 体积误判、低质量冗余源文件与重复入库问题"
        icon="mdi-toolbox-outline"
      >
        <AppleSettingsRow
          title="分享 STRM 覆盖大小检查"
          description="解决按大小覆盖时 STRM 文件被误判为小文件的问题：优先使用生成时的缓存数据，未命中时使用 ffprobe 探测实际大小"
        >
          <v-switch
            v-model="config.share_strm_overwrite_check_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="自动删除低质量源文件"
          description="按文件大小整理失败时（媒体库已存在更高质量文件），自动删除源文件。支持所有存储类型：本地、115网盘、CloudDrive"
          :subtray-open="Boolean(config.auto_delete_inferior_source_enabled)"
        >
          <v-switch
            v-model="config.auto_delete_inferior_source_enabled"
            color="warning"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
              <span>开启后，当因目标已存在更大体积媒体导致整理跳过/失败时，源文件会被直接删除，请谨慎评估后启用。</span>
            </div>
          </template>
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体库已存在时拦截整理"
          description="整理前查询所有媒体服务器，若已存在则立即终止并记录失败"
          :subtray-open="Boolean(config.transfer_intercept_exists_enabled)"
        >
          <v-switch
            v-model="config.transfer_intercept_exists_enabled"
            color="error"
            density="compact"
            hide-details
            inset
          />
          <template #subtray>
            <div class="p115-callout p115-callout--error">
              <v-icon size="16" color="error" icon="mdi-cancel" class="mt-0.5 flex-shrink-0" />
              <div>
                <div>• <strong>生效条件：</strong>目标路径尚无同名文件时触发（首次入库场景）；若目标文件已存在，覆盖检查会优先介入</div>
                <div>• <strong>注意：</strong>每次整理均会请求媒体服务器，需确保媒体已完成刮削入库</div>
              </div>
            </div>
          </template>
        </AppleSettingsRow>
      </AppleSettingsGroup>
    </div>

    <!-- ===================================================================
         8. 本地 STRM 备份 (tab-strm-backup)
         =================================================================== -->
    <div v-else-if="otherSubTab === 'tab-strm-backup'" class="p115-section-stack">
      <AppleSettingsGroup
        title="本地 STRM 归档备份"
        subtitle="将本地 STRM 目录打包为 tar.gz 备份至本地或 115 网盘，支持一键恢复"
        icon="mdi-backup-restore"
      >
        <template #action>
          <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="addBackupItem">
            <v-icon size="14" icon="mdi-plus" />
            <span>添加备份任务</span>
          </button>
        </template>

        <AppleSettingsRow title="启用 STRM 备份" description="开启定时与手动 STRM 备份任务调度">
          <template #badge>
            <span class="p115-badge" :class="config.strm_backup_enabled ? 'p115-badge--green' : 'p115-badge--neutral'">
              <span class="p115-badge-dot" />
              {{ config.strm_backup_enabled ? '已开启' : '未开启' }}
            </span>
          </template>
          <v-switch v-model="config.strm_backup_enabled" color="primary" density="compact" hide-details inset />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <div v-for="(item, index) in strmBackupItems" :key="`backup-${index}`" class="p115-bezel">
        <div class="p115-bezel-core">
          <!-- Clean Apple Task Card Header -->
          <div class="p115-backup-head">
            <div class="p115-backup-head-left">
              <span class="p115-backup-icon">
                <v-icon size="16" icon="mdi-archive-outline" />
              </span>
              <span class="p115-backup-title">{{ item.name || `备份任务 #${index + 1}` }}</span>
              <span class="p115-badge" :class="item.enabled ? 'p115-badge--green' : 'p115-badge--neutral'">
                <span class="p115-badge-dot" />
                {{ item.enabled ? '已启用' : '已暂停' }}
              </span>
              <span class="p115-badge" :class="item.target_type === 'cloud' ? 'p115-badge--pink' : 'p115-badge--blue'">
                {{ item.target_type === 'cloud' ? '115 网盘' : '本地目录' }}
              </span>
            </div>

            <div class="p115-backup-head-actions">
              <button
                type="button"
                class="p115-btn p115-btn--primary p115-btn--sm"
                :disabled="!item.name || backupLoading[item.name]"
                @click="triggerBackup(item.name)"
              >
                <v-progress-circular v-if="backupLoading[item.name]" indeterminate size="13" width="2" />
                <v-icon v-else size="14" icon="mdi-backup-restore" />
                <span>立即备份</span>
              </button>
              <button
                type="button"
                class="p115-btn p115-btn--tonal p115-btn--sm"
                :disabled="!item.name"
                @click="listBackups(item.name)"
              >
                <v-icon size="14" icon="mdi-format-list-bulleted" />
                <span>查看备份</span>
              </button>
              <button
                type="button"
                class="p115-btn p115-btn--icon p115-btn--danger"
                title="删除此备份任务"
                @click="removeBackupItem(index)"
              >
                <v-icon size="16" icon="mdi-trash-can-outline" />
              </button>
            </div>
          </div>

          <!-- Structured Apple Settings Rows -->
          <AppleSettingsRow
            title="启用此任务"
            description="关闭后定时调度将跳过此任务，仍可通过上方按钮手动执行备份"
          >
            <v-switch v-model="item.enabled" color="success" density="compact" hide-details inset />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="任务名称"
            description="必填唯一标识，用作归档压缩包文件名前缀"
            wide-control
          >
            <v-text-field
              v-model="item.name"
              placeholder="例如：media-strm-daily"
              density="compact"
              variant="outlined"
              hide-details
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="备份目标存储"
            description="选择将打包后的 tar.gz 备份保存在本地或上传至 115 网盘"
            wide-control
          >
            <AppleSegmentedControl
              v-model="item.target_type"
              :items="[
                { label: '本地目录', value: 'local', icon: 'mdi-folder-outline' },
                { label: '115 网盘', value: 'cloud', icon: 'mdi-cloud-outline' },
              ]"
              block
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="源目录列表"
            description="需要一并打包进 tar.gz 归档的本地 STRM 目录，可添加多个"
            vertical
          >
            <div class="d-flex flex-column gap-2">
              <div
                v-if="!item.source_paths || item.source_paths.length === 0"
                class="p115-empty-inline"
              >
                尚未添加源目录，请点击下方「添加源目录」
              </div>

              <div
                v-for="(_sp, spIndex) in item.source_paths"
                :key="`sp-${index}-${spIndex}`"
                class="p115-backup-path-row"
              >
                <v-text-field
                  v-model="item.source_paths[spIndex]"
                  placeholder="例如：/config/plugins/p115strmhelper/strm"
                  density="compact"
                  variant="outlined"
                  hide-details
                >
                  <template #prepend-inner>
                    <v-icon size="16" color="primary" icon="mdi-folder-outline" />
                  </template>
                  <template #append-inner>
                    <button
                      type="button"
                      class="p115-inline-browse"
                      title="浏览本地源目录"
                      @click="openDirSelector(index, 'local', 'backupSourcePath', String(spIndex))"
                    >
                      <v-icon size="16" icon="mdi-folder-open-outline" />
                    </button>
                  </template>
                </v-text-field>

                <button
                  type="button"
                  class="p115-btn p115-btn--icon p115-btn--danger"
                  title="移除此源目录"
                  @click="removeSourcePath(index, spIndex)"
                >
                  <v-icon size="16" icon="mdi-trash-can-outline" />
                </button>
              </div>

              <div>
                <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="addSourcePath(index)">
                  <v-icon size="14" icon="mdi-plus" />
                  <span>添加源目录</span>
                </button>
              </div>
            </div>
          </AppleSettingsRow>

          <AppleSettingsRow
            :title="item.target_type === 'local' ? '本地备份存放目录' : '115 网盘备份存放目录'"
            :description="item.target_type === 'local' ? '归档压缩包 (.tar.gz) 的本地输出路径' : '归档压缩包上传保存的 115 网盘目录路径'"
            vertical
          >
            <v-text-field
              v-if="item.target_type === 'local'"
              v-model="item.local_target_path"
              placeholder="例如：/config/backups/strm"
              density="compact"
              variant="outlined"
              hide-details
            >
              <template #prepend-inner>
                <v-icon size="16" color="primary" icon="mdi-folder-zip-outline" />
              </template>
              <template #append-inner>
                <button
                  type="button"
                  class="p115-inline-browse"
                  title="浏览本地备份目录"
                  @click="openDirSelector(index, 'local', 'backupItems', 'local_target_path')"
                >
                  <v-icon size="16" icon="mdi-folder-open-outline" />
                </button>
              </template>
            </v-text-field>

            <v-text-field
              v-else
              v-model="item.cloud_target_path"
              placeholder="例如：/备份/STRM归档"
              density="compact"
              variant="outlined"
              hide-details
            >
              <template #prepend-inner>
                <v-icon size="16" color="secondary" icon="mdi-cloud-upload-outline" />
              </template>
              <template #append-inner>
                <button
                  type="button"
                  class="p115-inline-browse"
                  title="浏览 115 网盘备份目录"
                  @click="openDirSelector(index, 'remote', 'backupItems', 'cloud_target_path')"
                >
                  <v-icon size="16" icon="mdi-cloud-search-outline" />
                </button>
              </template>
            </v-text-field>
          </AppleSettingsRow>

          <AppleSettingsRow
            title="定时自动备份"
            description="按设定的 Cron 周期自动打包备份并清理超额历史归档"
          >
            <v-switch
              v-model="item.timing_enabled"
              color="primary"
              density="compact"
              hide-details
              inset
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            v-if="item.timing_enabled"
            title="备份周期"
            description="设置自动执行此备份任务的 Cron 表达式"
            wide-control
          >
            <VCronField v-model="item.cron" label="备份周期" density="compact" hide-details />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="保留最近备份个数"
            description="超出保留份数时将自动清理最早的备份归档"
            wide-control
          >
            <v-text-field
              v-model.number="item.retain_count"
              type="number"
              :min="1"
              suffix="份"
              density="compact"
              variant="outlined"
              hide-details
              class="p115-tabular"
            />
          </AppleSettingsRow>
        </div>
      </div>

      <div v-if="strmBackupItems.length === 0" class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-archive-plus-outline" class="mt-0.5 flex-shrink-0" />
        <span>尚未创建备份任务。点击上方「添加备份任务」即可配置本地或 115 云端归档备份。</span>
      </div>

      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="font-weight-bold mb-0.5">STRM 备份说明：</div>
          <div>• 支持将本地 STRM 目录打包为 <code class="p115-mono">tar.gz</code> 备份到本地目录或上传到 115 网盘</div>
          <div>• 支持定时自动备份和手动立即备份，按保留数量自动清理旧备份，并支持一键恢复</div>
        </div>
      </div>

      <!-- Backup List Apple Sheet -->
      <v-dialog v-model="backupListDialog" max-width="820" :content-class="dialogContentClass">
        <v-card class="p115-sheet" elevation="0">
          <div class="p115-sheet-header">
            <div class="p115-sheet-title">
              <v-icon size="19" color="primary" icon="mdi-archive-clock-outline" />
              <span>备份归档列表 · {{ currentListTaskName }}</span>
            </div>
            <button
              type="button"
              class="p115-btn p115-btn--ghost p115-btn--icon"
              @click="backupListDialog = false"
            >
              <v-icon size="18" icon="mdi-close" />
            </button>
          </div>

          <div class="p115-sheet-body">
            <v-skeleton-loader v-if="backupListLoading" type="table-row@4" class="bg-transparent" />
            <div v-else-if="backupListData.length === 0" class="p115-callout p115-callout--info">
              <v-icon size="18" color="primary" icon="mdi-information-outline" />
              <span>暂无备份记录</span>
            </div>
            <div v-else class="d-flex flex-column gap-2">
              <div
                v-for="(bItem, bIdx) in backupListData"
                :key="`bitem-${bIdx}`"
                class="p115-item-card d-flex align-center justify-space-between gap-3 flex-wrap"
              >
                <div class="min-w-0 flex-grow-1">
                  <div class="font-weight-medium p115-mono text-body-2 text-truncate">{{ bItem.filename }}</div>
                  <div class="text-caption opacity-75 p115-tabular mt-0.5">
                    大小：{{ formatBytes(bItem.file_size) }} · 创建于：{{ bItem.created_at || '-' }}
                    <span v-if="bItem.status"> · 状态：{{ bItem.status }}</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="p115-btn p115-btn--pink p115-btn--sm"
                  @click="showRestoreConfirm(bItem)"
                >
                  <v-icon size="14" icon="mdi-restore" />
                  <span>恢复此备份</span>
                </button>
              </div>
            </div>
          </div>

          <div class="p115-sheet-footer justify-end">
            <button type="button" class="p115-btn p115-btn--subtle p115-btn--sm" @click="backupListDialog = false">
              关闭
            </button>
          </div>
        </v-card>
      </v-dialog>

      <!-- Restore Confirm Apple Sheet -->
      <v-dialog v-model="restoreConfirmDialog" max-width="480" persistent :content-class="dialogContentClass">
        <v-card class="p115-sheet" elevation="0">
          <div class="p115-sheet-header">
            <div class="p115-sheet-title">
              <v-icon size="19" color="warning" icon="mdi-alert-circle-outline" />
              <span>确认恢复备份</span>
            </div>
          </div>

          <div class="p115-sheet-body">
            <div class="mb-2">
              确定要从备份 <strong class="p115-mono">{{ restoreTarget?.filename }}</strong> 恢复吗？
            </div>
            <div class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
              <span>恢复操作将解压备份文件到源目录，同名文件会被直接覆盖。</span>
            </div>
          </div>

          <div class="p115-sheet-footer justify-end">
            <button
              type="button"
              class="p115-btn p115-btn--subtle p115-btn--sm"
              :disabled="restoreConfirmLoading"
              @click="restoreConfirmDialog = false"
            >
              取消
            </button>
            <button
              type="button"
              class="p115-btn p115-btn--primary p115-btn--sm"
              :disabled="restoreConfirmLoading"
              @click="handleConfirmRestore"
            >
              <v-progress-circular v-if="restoreConfirmLoading" indeterminate size="13" width="2" />
              <span>确认恢复</span>
            </button>
          </div>
        </v-card>
      </v-dialog>
    </div>
  </div>
</template>

<script setup>
import { ref, inject, watch, computed, reactive } from 'vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import AppleSettingsRow from '../ui/AppleSettingsRow.vue';
import PathMappingComposer from '../ui/PathMappingComposer.vue';
import { useThemeAdapter } from '../composables/useThemeAdapter.js';

const { dialogContentClass } = useThemeAdapter();

const activeSubTabs = inject('activeSubTabs', null);
const fallbackSubTab = ref('tab-sync-del');

const otherSubTab = computed({
  get: () => (activeSubTabs ? activeSubTabs.other : fallbackSubTab.value),
  set: (val) => {
    if (activeSubTabs) activeSubTabs.other = val;
    else fallbackSubTab.value = val;
  },
});

const subTabItems = [
  { value: 'tab-sync-del', label: '同步删除', icon: 'mdi-delete-sweep-outline' },
  { value: 'tab-tg-search', label: '频道搜索', icon: 'mdi-magnify' },
  { value: 'tab-cleanup', label: '定期清理', icon: 'mdi-broom' },
  { value: 'tab-same-playback', label: '多端播放', icon: 'mdi-devices' },
  { value: 'tab-hdhive-checkin', label: 'RE0 签到', icon: 'mdi-calendar-check-outline' },
  { value: 'tab-p115-checkin', label: '115 签到', icon: 'mdi-check-circle-outline' },
  { value: 'tab-utility', label: '实用工具', icon: 'mdi-toolbox-outline' },
  { value: 'tab-strm-backup', label: '本地 STRM 备份', icon: 'mdi-backup-restore' },
];

const config = inject('config');
const embyMediaservers = inject('embyMediaservers');
const syncDelLibraryPaths = inject('syncDelLibraryPaths');
const tgChannels = inject('tgChannels');
const addPath = inject('addPath');
const removePath = inject('removePath');
const openDirSelector = inject('openDirSelector');
const addTgChannel = inject('addTgChannel');
const removeTgChannel = inject('removeTgChannel');
const openImportDialog = inject('openImportDialog');
const api = inject('api');
const message = inject('message');
const PLUGIN_ID = inject('PLUGIN_ID');
const formatBytes = inject('formatBytes');

const showRe0Pass = ref(false);
const show115SafePass = ref(false);

const re0CheckinModeItems = [
  { label: '关闭', value: 'off', icon: 'mdi-close-circle-outline' },
  { label: '每日签到', value: 'daily', icon: 'mdi-calendar-check' },
  { label: '赌狗签到', value: 'gamble', icon: 'mdi-dice-multiple-outline' },
];

const re0CheckinMode = computed({
  get: () => {
    if (config.hdhive_checkin_gamble_enabled) return 'gamble';
    if (config.hdhive_checkin_daily_enabled) return 'daily';
    return 'off';
  },
  set: (mode) => {
    config.hdhive_checkin_daily_enabled = mode === 'daily';
    config.hdhive_checkin_gamble_enabled = mode === 'gamble';
  },
});

const strmBackupItems = computed(() => config.strm_backup_items || []);

const backupLoading = reactive({});
const backupListDialog = ref(false);
const backupListLoading = ref(false);
const backupListData = ref([]);
const currentListTaskName = ref('');

function addBackupItem() {
  const newItem = {
    name: '',
    enabled: true,
    source_paths: [],
    target_type: 'local',
    local_target_path: null,
    cloud_target_path: null,
    cron: '0 */6 * * *',
    retain_count: 7,
    timing_enabled: false,
  };
  if (!config.strm_backup_items) {
    config.strm_backup_items = [];
  }
  config.strm_backup_items.push(newItem);
}

function removeBackupItem(index) {
  config.strm_backup_items.splice(index, 1);
}

function addSourcePath(itemIndex) {
  const item = config.strm_backup_items[itemIndex];
  if (item) {
    item.source_paths.push('');
  }
}

function removeSourcePath(itemIndex, spIndex) {
  const item = config.strm_backup_items[itemIndex];
  if (item && item.source_paths) {
    item.source_paths.splice(spIndex, 1);
  }
}

async function triggerBackup(taskName) {
  backupLoading[taskName] = true;
  try {
    const response = await api.post(`plugin/${PLUGIN_ID}/trigger_backup`, { task_name: taskName });
    if (response.code === 0) {
      message.text = response.msg || '备份任务已启动';
      message.type = 'success';
    } else {
      message.text = response.msg || '启动备份任务失败';
      message.type = 'error';
    }
  } catch (error) {
    message.text = `启动备份任务失败: ${error.message}`;
    message.type = 'error';
  } finally {
    backupLoading[taskName] = false;
  }
}

async function listBackups(taskName) {
  currentListTaskName.value = taskName;
  backupListDialog.value = true;
  backupListLoading.value = true;
  backupListData.value = [];
  try {
    const response = await api.get(`plugin/${PLUGIN_ID}/list_backups?task_name=${encodeURIComponent(taskName)}`);
    if (response.code === 0) {
      backupListData.value = response.data || [];
    } else {
      message.text = response.msg || '获取备份列表失败';
      message.type = 'error';
    }
  } catch (error) {
    message.text = `获取备份列表失败: ${error.message}`;
    message.type = 'error';
  } finally {
    backupListLoading.value = false;
  }
}

const restoreConfirmDialog = ref(false);
const restoreConfirmLoading = ref(false);
const restoreTarget = ref(null);

function showRestoreConfirm(backupItem) {
  restoreTarget.value = backupItem;
  restoreConfirmDialog.value = true;
}

async function handleConfirmRestore() {
  if (!restoreTarget.value) return;
  const backupItem = restoreTarget.value;
  restoreConfirmLoading.value = true;
  try {
    const response = await api.post(`plugin/${PLUGIN_ID}/restore_backup`, {
      task_name: backupItem.task_name,
      backup_path: backupItem.target_path,
    });
    if (response.code === 0) {
      message.text = response.msg || '恢复任务已启动，后台执行中';
      message.type = 'success';
    } else {
      message.text = response.msg || '启动恢复任务失败';
      message.type = 'error';
    }
  } catch (error) {
    message.text = `备份恢复失败: ${error.message}`;
    message.type = 'error';
  } finally {
    restoreConfirmLoading.value = false;
    restoreConfirmDialog.value = false;
    restoreTarget.value = null;
  }
}

watch(
  () => config.hdhive_checkin_daily_enabled,
  (v) => {
    if (v) config.hdhive_checkin_gamble_enabled = false;
  },
);

watch(
  () => config.hdhive_checkin_gamble_enabled,
  (v) => {
    if (v) config.hdhive_checkin_daily_enabled = false;
  },
);
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

.p115-item-card {
  padding: 11px 13px;
  border-radius: 12px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
}

.p115-tg-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.p115-backup-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--p115-border-hairline);
  background: linear-gradient(
    120deg,
    rgba(91, 207, 250, 0.08) 0%,
    rgba(245, 171, 185, 0.05) 100%
  );
  flex-wrap: wrap;
}

.p115-backup-head-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.p115-backup-icon {
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

.p115-backup-title {
  font-size: 0.9rem;
  font-weight: 640;
  color: var(--p115-text-primary);
  letter-spacing: -0.01em;
}

.p115-backup-head-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.p115-backup-path-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}

.p115-empty-inline {
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--p115-bg-inset);
  border: 1px dashed var(--p115-border-hairline);
  font-size: 0.77rem;
  color: var(--p115-text-secondary);
}

@media (max-width: 640px) {
  .p115-tg-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .p115-tg-row > button {
    justify-self: end;
  }

  .p115-backup-head {
    padding: 11px 13px;
  }
}

.p115-inline-browse,
.p115-eye-btn {
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
}

.p115-eye-btn {
  background: transparent;
  color: var(--p115-text-secondary);
}
</style>
