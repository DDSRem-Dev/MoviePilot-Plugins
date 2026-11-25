<template>
  <div class="p115-section-stack">
    <!-- Top Segmented Control for 3 Cloud Drive Sub-Modules -->
    <div class="p115-subnav-bar">
      <AppleSegmentedControl v-model="panSubTab" :items="subTabItems" />
    </div>

    <!-- ===================================================================
         1. 网盘整理 (tab-pan-transfer)
         =================================================================== -->
    <div v-if="panSubTab === 'tab-pan-transfer'" class="p115-section-stack">
      <AppleSettingsGroup
        title="网盘整理总开关与 CloudDrive2 协同"
        subtitle="阿里云盘秒传、115 分享转存与频道搜索转存均依赖网盘整理"
        icon="mdi-transfer"
      >
        <AppleSettingsRow title="启用网盘整理" description="开启后自动对进入待整理目录的资源触发 MoviePilot 整理">
          <v-switch v-model="config.pan_transfer_enabled" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.pan_transfer_clouddrive2_config"
          title="交由 CloudDrive2 储存整理"
          description="将 115 待整理路径交由 CloudDrive2 挂载目录执行整理"
        >
          <v-switch
            v-model="config.pan_transfer_clouddrive2_config.enabled"
            color="info"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.pan_transfer_clouddrive2_config && config.pan_transfer_clouddrive2_config.enabled"
          title="CD2 挂载前缀"
          description="必填，将与 115 待整理目录拼接为完整 CD2 挂载路径"
          wide-control
        >
          <v-text-field
            v-model="config.pan_transfer_clouddrive2_config.prefix"
            placeholder="必填，例如 /115open"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" icon="mdi-link-variant" />
            </template>
          </v-text-field>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <!-- 待整理和未识别目录 -->
      <AppleSettingsGroup
        title="待整理与未识别目录"
        subtitle="点击行右侧播放图标可对该目录立即启动一次手动整理任务"
        icon="mdi-folder-move-outline"
        padded
      >
        <PathMappingComposer
          mode="single"
          key-prefix="pan-transfer"
          :items="panTransferPaths"
          single-label="网盘待整理目录"
          single-placeholder="/待整理"
          single-icon="mdi-cloud-outline"
          add-label="添加待整理路径"
          @add="addPanTransferPath"
          @remove="removePanTransferPath"
          @browse-single="(i) => openDirSelector(i, 'remote', 'panTransfer')"
        >
          <template #row-action="{ item, index }">
            <button
              type="button"
              class="p115-btn p115-btn--icon p115-btn--tonal"
              :disabled="!item.path"
              title="手动整理此目录"
              @click="manualTransfer(index)"
            >
              <v-icon size="16" icon="mdi-play" />
            </button>
          </template>
        </PathMappingComposer>

        <div class="mt-4">
          <v-text-field
            v-model="config.pan_transfer_unrecognized_path"
            label="网盘整理未识别目录"
            placeholder="例如：/未识别"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="warning" icon="mdi-folder-question-outline" />
            </template>
            <template #append-inner>
              <button
                type="button"
                class="p115-inline-browse"
                title="浏览网盘未识别目录"
                @click="openDirSelector('unrecognized', 'remote', 'panTransferUnrecognized')"
              >
                <v-icon size="16" icon="mdi-cloud-search-outline" />
              </button>
            </template>
          </v-text-field>
        </div>

        <div v-if="unrecognizedNestedWarning" class="p115-callout p115-callout--error mt-3">
          <v-icon size="16" color="error" icon="mdi-alert-octagon-outline" class="mt-0.5 flex-shrink-0" />
          <span>{{ unrecognizedNestedWarning }}</span>
        </div>

        <div class="p115-callout p115-callout--info mt-3">
          <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
          <span>提示：此目录用于存放整理过程中未能识别的媒体文件。</span>
        </div>

        <div class="p115-callout p115-callout--warn mt-2">
          <v-icon size="16" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
          <span>注意：未识别目录不能设置在任何媒体库目录或待整理目录的内部。</span>
        </div>
      </AppleSettingsGroup>

      <!-- 分享转存目录 -->
      <AppleSettingsGroup
        title="分享转存目录"
        subtitle="用于存放通过分享链接转存的资源"
        icon="mdi-share-variant-outline"
        padded
      >
        <PathMappingComposer
          mode="single"
          key-prefix="share-receive"
          :items="shareReceivePaths"
          single-label="分享转存目录"
          single-placeholder="/分享转存"
          single-icon="mdi-share-variant-outline"
          add-label="添加分享转存路径"
          @add="addShareReceivePath"
          @remove="removeShareReceivePath"
          @browse-single="(i) => openDirSelector(i, 'remote', 'shareReceive')"
        />
      </AppleSettingsGroup>

      <!-- 离线下载目录 -->
      <AppleSettingsGroup
        title="离线下载目录"
        subtitle="用于存放通过离线下载功能下载的资源"
        icon="mdi-cloud-download-outline"
        padded
      >
        <PathMappingComposer
          mode="single"
          key-prefix="offline-dl"
          :items="offlineDownloadPaths"
          single-label="离线下载目录"
          single-placeholder="/离线下载"
          single-icon="mdi-cloud-download-outline"
          add-label="添加离线下载路径"
          @add="addOfflineDownloadPath"
          @remove="removeOfflineDownloadPath"
          @browse-single="(i) => openDirSelector(i, 'remote', 'offlineDownload')"
        />
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="离线下载失败重试"
        subtitle="处理当前 115 账号的可重试失败任务，包含历史积压项，不依赖网盘整理开关"
        icon="mdi-refresh"
      >
        <AppleSettingsRow title="自动重试失败任务" description="重启后保留已用次数；达到上限仍失败则停止自动重试">
          <v-switch v-model="config.offline_retry_enabled" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>
        <AppleSettingsRow
          v-if="config.offline_retry_enabled"
          title="最多重试次数"
          description="每个任务最多尝试 1～100 次；重试请求失败或超时也计入次数"
        >
          <v-text-field
            v-model.number="config.offline_retry_max_attempts"
            type="number"
            min="1"
            max="100"
            step="1"
            aria-label="离线下载最多重试次数"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>
        <AppleSettingsRow
          v-if="config.offline_retry_enabled"
          title="重试间隔（小时）"
          description="首次发现失败后开始计时，每两分钟检查一次；新间隔在下次安排时生效"
        >
          <v-text-field
            v-model.number="config.offline_retry_interval_hours"
            type="number"
            min="1"
            max="8760"
            step="1"
            aria-label="离线下载重试间隔（小时）"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <details class="p115-guide-details" open>
        <summary>
          <v-icon size="16" icon="mdi-book-open-variant" />
          <span>配置说明与重要注意事项</span>
        </summary>
        <div class="p115-guide-body">
          <div class="font-weight-bold mb-1">使用本功能需要先进入「设定 - 目录」进行配置：</div>
          <div class="mb-1">1. 添加目录配置卡，按需配置媒体类型和媒体类别，资源存储选择 115网盘，资源目录输入网盘待整理文件夹</div>
          <div class="mb-1">2. 自动整理模式选择手动整理，媒体库存储依旧选择 115网盘，并配置好媒体库路径，整理方式选择移动，按需配置分类、重命名、通知</div>
          <div class="mb-3">3. 配置完成目录设置后只需要在上方「网盘待整理目录」填入网盘待整理文件夹即可</div>

          <div class="p115-callout p115-callout--error mb-2">
            <v-icon size="16" color="error" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
            <span><strong>注意：</strong>配置目录时不能选择刮削元数据，否则可能导致风控！</span>
          </div>

          <div class="p115-callout p115-callout--warn mb-2">
            <v-icon size="16" color="warning" icon="mdi-alert-circle-outline" class="mt-0.5 flex-shrink-0" />
            <div>
              <div>• 阿里云盘、115网盘分享链接秒传或转存都依赖于网盘整理</div>
              <div>• TG/Slack 资源搜索转存也依赖于网盘整理</div>
              <div>• 当阿里云盘分享秒传未能识别分享媒体信息时，会自动将资源转存到网盘整理未识别目录，后续需要用户手动重命名整理</div>
              <div>• 115 生活事件监控默认会忽略网盘整理触发的移动事件，所以推荐使用 MP 整理事件监控生成 STRM</div>
            </div>
          </div>
        </div>
      </details>

      <AppleSettingsGroup title="在线诊断" icon="mdi-bug-check-outline">
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
    </div>

    <!-- ===================================================================
         2. 网盘挂载 FUSE (tab-pan-mount)
         =================================================================== -->
    <div v-else-if="panSubTab === 'tab-pan-mount'" class="p115-section-stack">
      <AppleSettingsGroup
        title="FUSE 本地文件系统挂载"
        subtitle="将 115 网盘挂载为容器内的本地目录"
        icon="mdi-harddisk"
      >
        <AppleSettingsRow title="启用网盘挂载" description="将 115 网盘挂载为本地文件系统">
          <v-switch v-model="config.fuse_enabled" color="success" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="挂载点路径" description="文件系统挂载的本地路径（必须是已存在的目录）" wide-control>
          <v-text-field
            v-model="config.fuse_mountpoint"
            placeholder="/mnt/115"
            density="compact"
            variant="outlined"
            hide-details
            class="p115-mono"
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="目录读取缓存 TTL (秒)" description="目录列表缓存时间，默认 60 秒" wide-control>
          <v-text-field
            v-model.number="config.fuse_readdir_ttl"
            type="number"
            min="0"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="文件所有者 UID" description="挂载文件的用户 ID，留空则使用当前运行用户" wide-control>
          <v-text-field
            v-model.number="config.fuse_uid"
            type="number"
            min="0"
            clearable
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="文件所有者 GID" description="挂载文件的组 ID，留空则使用当前运行用户" wide-control>
          <v-text-field
            v-model.number="config.fuse_gid"
            type="number"
            min="0"
            clearable
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="STRM 文件生成内容接管"
        subtitle="匹配规则的文件将生成指向挂载路径的 STRM 内容"
        icon="mdi-file-replace-outline"
      >
        <AppleSettingsRow
          title="接管 STRM 文件生成内容"
          description="启用后，匹配规则的文件将生成指向挂载路径的 STRM 内容"
        >
          <template #badge>
            <button
              v-if="config.fuse_strm_takeover_enabled"
              type="button"
              class="p115-btn p115-btn--tonal p115-btn--sm"
              @click="openConfigGeneratorDialog"
            >
              <v-icon size="14" icon="mdi-code-tags" />
              <span>生成 Emby 反代 302 配置</span>
            </button>
          </template>
          <v-switch
            v-model="config.fuse_strm_takeover_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <template v-if="config.fuse_strm_takeover_enabled">
          <AppleSettingsRow
            title="媒体服务器网盘挂载目录"
            description="媒体服务器中配置的 115 网盘挂载路径"
            wide-control
          >
            <v-text-field
              v-model="config.fuse_strm_mount_dir"
              placeholder="/media/115"
              density="compact"
              variant="outlined"
              hide-details
              class="p115-mono"
            />
          </AppleSettingsRow>

          <AppleSettingsRow title="STRM 接管匹配规则" vertical>
            <div class="p115-callout p115-callout--info mb-2">
              <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
              <div>
                <div class="font-weight-bold mb-1">STRM URL 生成优先级：</div>
                <div>1. <strong>URL 自定义模板</strong>（如果启用）：优先使用 Jinja2 模板渲染</div>
                <div>2. <strong>FUSE STRM 接管</strong>（如果启用且匹配规则）：生成指向挂载路径的 STRM 内容</div>
                <div>3. <strong>默认格式</strong>：使用基础设置中的「STRM文件URL格式」和「STRM URL 文件名称编码」</div>
              </div>
            </div>

            <div class="d-flex flex-column gap-3">
              <div
                v-for="(rule, index) in fuseStrmTakeoverRules"
                :key="`fuse-rule-${index}`"
                class="p115-rule-card"
              >
                <div class="d-flex align-center justify-space-between mb-2">
                  <span class="p115-badge p115-badge--blue">规则 #{{ index + 1 }}</span>
                  <button
                    type="button"
                    class="p115-btn p115-btn--icon p115-btn--danger"
                    title="移除规则"
                    @click="removePath(index, 'fuseStrmTakeover')"
                  >
                    <v-icon size="16" icon="mdi-trash-can-outline" />
                  </button>
                </div>

                <div class="text-caption opacity-75 mb-2">选择匹配方式（可多选，同时满足才匹配）：</div>
                <div class="d-flex flex-wrap gap-5 mb-2">
                  <v-switch v-model="rule._use_extensions" label="文件后缀" color="primary" density="compact" hide-details inset />
                  <v-switch v-model="rule._use_names" label="文件名称" color="primary" density="compact" hide-details inset />
                  <v-switch v-model="rule._use_paths" label="网盘路径" color="primary" density="compact" hide-details inset />
                </div>

                <v-textarea
                  v-if="rule._use_extensions"
                  v-model="rule.extensions"
                  label="文件后缀（每行一个，不包含点号，如 mkv、mp4）"
                  placeholder="mkv&#10;mp4&#10;avi"
                  rows="2"
                  density="compact"
                  variant="outlined"
                  class="mb-2"
                  hide-details
                />
                <v-textarea
                  v-if="rule._use_names"
                  v-model="rule.names"
                  label="文件名称白名单（每行一个，支持部分匹配）"
                  placeholder="蓝光&#10;BluRay"
                  rows="2"
                  density="compact"
                  variant="outlined"
                  class="mb-2"
                  hide-details
                />
                <v-textarea
                  v-if="rule._use_paths"
                  v-model="rule.paths"
                  label="网盘文件夹路径（每行一个，支持部分匹配）"
                  placeholder="/电影/4K&#10;/电视剧"
                  rows="2"
                  density="compact"
                  variant="outlined"
                  hide-details
                />
              </div>

              <div>
                <button
                  type="button"
                  class="p115-btn p115-btn--tonal p115-btn--sm"
                  @click="addPath('fuseStrmTakeover')"
                >
                  <v-icon size="15" icon="mdi-plus" />
                  <span>添加接管规则</span>
                </button>
              </div>
            </div>

            <div class="p115-callout p115-callout--info mt-3">
              <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
              <div>
                <div>• 三种匹配方式可以组合使用，<strong>同时满足</strong>（与关系）才会匹配；若某条件为空则不检查该条件</div>
                <div>
                  • 匹配成功后生成的 STRM 内容格式：
                  <code class="p115-mono">{{ config.fuse_strm_mount_dir || '媒体服务器挂载目录' }}/文件网盘路径</code>
                </div>
                <div>
                  • 示例：挂载目录为 <code class="p115-mono">/media/115</code>，网盘路径为
                  <code class="p115-mono">/电影/示例.mkv</code>，则生成 <code class="p115-mono">/media/115/电影/示例.mkv</code>
                </div>
              </div>
            </div>
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>

      <details class="p115-guide-details" open>
        <summary>
          <v-icon size="16" icon="mdi-information-outline" />
          <span>平台限制、权限说明与防风控必读指南</span>
        </summary>
        <div class="p115-guide-body">
          <div class="p115-callout p115-callout--error mb-2">
            <v-icon size="16" color="error" icon="mdi-alert-octagon-outline" class="mt-0.5 flex-shrink-0" />
            <div>
              <div>• <strong>切勿直接使用媒体服务器刮削挂载路径</strong>，这会导致网盘风控！</div>
              <div>• <strong>正确方法：</strong>使用本插件的 STRM 文件生成功能，在本地生成 STRM 文件后，再让媒体服务器对 STRM 文件进行刮削</div>
            </div>
          </div>

          <div class="p115-callout p115-callout--warn mb-2">
            <v-icon size="16" color="warning" icon="mdi-laptop" class="mt-0.5 flex-shrink-0" />
            <div>
              <div class="font-weight-bold mb-0.5">平台限制说明：</div>
              <div>• <strong>Windows 系统不支持：</strong>FUSE 功能基于 Linux 文件系统，无法在 Windows 环境下运行</div>
              <div>• <strong>Linux 裸机：</strong>理论上支持，需要安装 libfuse（libfuse2 或 libfuse3）</div>
              <div>• <strong>macOS 裸机：</strong>理论上支持，需要安装 macFUSE</div>
              <div>• <strong>推荐使用 Docker 容器：</strong>需要容器以 <code class="p115-mono">--privileged</code> 或 <code class="p115-mono">--cap-add SYS_ADMIN</code> 权限运行，UID/GID 建议设为非 root 用户</div>
            </div>
          </div>

          <div class="mt-2">
            详细的 FUSE 挂载配置指南请参考：
            <a
              href="https://blog.ddsrem.com/archives/115strmhelper-fuse-use"
              target="_blank"
              rel="noopener noreferrer"
              class="p115-ext-link"
            >
              FUSE 挂载详细配置指南
            </a>
          </div>
        </div>
      </details>
    </div>

    <!-- ===================================================================
         3. 目录上传 (tab-directory-upload)
         =================================================================== -->
    <div v-else-if="panSubTab === 'tab-directory-upload'" class="p115-section-stack">
      <AppleSettingsGroup
        title="目录监控自动上传"
        subtitle="监控本地目录新文件并自动上传至 115 网盘或复制到本地目录"
        icon="mdi-upload-network-outline"
      >
        <AppleSettingsRow title="启用目录上传" description="开启本地文件夹监控自动上传流程">
          <v-switch v-model="config.directory_upload_enabled" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="监控模式"
          description="性能模式适用于物理盘原生事件；兼容模式使用轮询适用于 SMB/NFS 网络共享目录"
          wide-control
        >
          <AppleSegmentedControl
            v-model="config.directory_upload_mode"
            :items="[
              { label: '兼容模式', value: 'compatibility', icon: 'mdi-lan-connect' },
              { label: '性能模式', value: 'fast', icon: 'mdi-lightning-bolt-outline' },
            ]"
            block
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.directory_upload_clouddrive2_config"
          title="交由 CloudDrive2 上传"
          description="通过本地挂载的 CloudDrive2 目录执行上传写入"
        >
          <v-switch
            v-model="config.directory_upload_clouddrive2_config.enabled"
            color="info"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.directory_upload_clouddrive2_config && config.directory_upload_clouddrive2_config.enabled"
          title="CD2 挂载前缀"
          description="必填，将与网盘上传目标目录拼接为完整 CD2 挂载路径"
          wide-control
        >
          <v-text-field
            v-model="config.directory_upload_clouddrive2_config.prefix"
            placeholder="必填，例如 /115open"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" icon="mdi-link-variant" />
            </template>
          </v-text-field>
        </AppleSettingsRow>

        <AppleSettingsRow
          title="跳过蓝光原盘 STREAM 目录"
          description="关闭后将允许上传 BDMV/STREAM 下的 m2ts 等文件"
        >
          <v-switch
            v-model="config.directory_upload_skip_bdmv_stream"
            color="info"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="上传文件扩展名"
          description="指定哪些扩展名的文件会被上传到 115 网盘，多个用逗号分隔；留空或填 * 表示不限制后缀"
          vertical
        >
          <v-text-field
            v-model="config.directory_upload_uploadext"
            density="compact"
            variant="outlined"
            hide-details
            class="p115-mono"
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="复制文件扩展名"
          description="指定哪些扩展名的文件会被复制到本地目标目录，多个用逗号分隔"
          vertical
        >
          <v-text-field
            v-model="config.directory_upload_copyext"
            density="compact"
            variant="outlined"
            hide-details
            class="p115-mono"
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="漏传巡检与队列保护"
        subtitle="周期扫描缺少 STRM 的上传文件，自动补交上传队列"
        icon="mdi-radar"
      >
        <AppleSettingsRow
          title="启用漏传巡检"
          description="首次启动后约 2 分钟开始巡检，之后按巡检间隔执行"
        >
          <v-switch
            v-model="config.directory_upload_rescan_enabled"
            color="info"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="巡检间隔 (分钟)" description="范围 1 ~ 1440 分钟" wide-control>
          <v-text-field
            v-model.number="config.directory_upload_rescan_interval"
            type="number"
            min="1"
            max="1440"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="单轮提交上限" description="限制单轮补交任务数量，避免集中占用上传队列" wide-control>
          <v-text-field
            v-model.number="config.directory_upload_rescan_max_submit"
            type="number"
            min="1"
            max="10000"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <AppleSettingsGroup
        title="监控路径组配置"
        subtitle="支持同时配置网盘上传目标、本地复制目录与上传后即时 STRM 输出目录"
        icon="mdi-folder-multiple-plus-outline"
        padded
      >
        <div class="d-flex flex-column gap-3">
          <div
            v-for="(pair, index) in directoryUploadPaths"
            :key="`upload-${index}`"
            class="p115-rule-card"
          >
            <div class="d-flex align-center justify-space-between mb-3">
              <span class="p115-badge p115-badge--blue">监控组 #{{ index + 1 }}</span>
              <div class="d-flex align-center gap-3">
                <v-switch
                  v-model="pair.delete"
                  label="处理后删除源文件"
                  color="error"
                  density="compact"
                  hide-details
                  inset
                />
                <button
                  type="button"
                  class="p115-btn p115-btn--icon p115-btn--danger"
                  title="删除此路径配置"
                  @click="removePath(index, 'directoryUpload')"
                >
                  <v-icon size="16" icon="mdi-trash-can-outline" />
                </button>
              </div>
            </div>

            <v-row dense>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="pair.src"
                  label="本地监控目录"
                  density="compact"
                  variant="outlined"
                  hide-details
                >
                  <template #prepend-inner>
                    <v-icon size="16" color="primary" icon="mdi-folder-search-outline" />
                  </template>
                  <template #append-inner>
                    <button
                      type="button"
                      class="p115-inline-browse"
                      title="浏览本地监控目录"
                      @click="openDirSelector(index, 'local', 'directoryUpload', 'src')"
                    >
                      <v-icon size="16" icon="mdi-folder-open-outline" />
                    </button>
                  </template>
                </v-text-field>
              </v-col>

              <v-col cols="12" md="6">
                <v-text-field
                  v-model="pair.dest_remote"
                  label="网盘上传目标目录"
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
                      title="浏览网盘上传目标目录"
                      @click="openDirSelector(index, 'remote', 'directoryUpload', 'dest_remote')"
                    >
                      <v-icon size="16" icon="mdi-cloud-search-outline" />
                    </button>
                  </template>
                </v-text-field>
              </v-col>

              <v-col cols="12" md="6" class="mt-2">
                <v-text-field
                  v-model="pair.dest_local"
                  label="本地复制目标目录 (可选)"
                  density="compact"
                  variant="outlined"
                  hide-details
                >
                  <template #prepend-inner>
                    <v-icon size="16" color="warning" icon="mdi-content-copy" />
                  </template>
                  <template #append-inner>
                    <button
                      type="button"
                      class="p115-inline-browse"
                      title="浏览本地复制目标目录"
                      @click="openDirSelector(index, 'local', 'directoryUpload', 'dest_local')"
                    >
                      <v-icon size="16" icon="mdi-folder-open-outline" />
                    </button>
                  </template>
                </v-text-field>
              </v-col>

              <v-col cols="12" md="6" class="mt-2">
                <v-text-field
                  v-model="pair.dest_strm"
                  label="STRM 输出目录 (可选)"
                  density="compact"
                  variant="outlined"
                  hide-details
                >
                  <template #prepend-inner>
                    <v-icon size="16" color="primary" icon="mdi-file-link-outline" />
                  </template>
                  <template #append-inner>
                    <button
                      type="button"
                      class="p115-inline-browse"
                      title="浏览 STRM 输出目录"
                      @click="openDirSelector(index, 'local', 'directoryUpload', 'dest_strm')"
                    >
                      <v-icon size="16" icon="mdi-folder-open-outline" />
                    </button>
                  </template>
                </v-text-field>
              </v-col>
            </v-row>
          </div>

          <div>
            <button
              type="button"
              class="p115-btn p115-btn--tonal p115-btn--sm"
              @click="addPath('directoryUpload')"
            >
              <v-icon size="15" icon="mdi-plus" />
              <span>添加监控路径组</span>
            </button>
          </div>
        </div>
      </AppleSettingsGroup>

      <details class="p115-guide-details">
        <summary>
          <v-icon size="16" icon="mdi-information-outline" />
          <span>目录上传工作机制与权限注意事项</span>
        </summary>
        <div class="p115-guide-body">
          <div>• 监控指定的“本地监控目录”，出现新文件时：</div>
          <div class="ml-3">- 若扩展名匹配“上传文件扩展名”，上传至“网盘上传目标目录”；若同时配置了“STRM 输出目录”，上传成功后立即按相对路径生成对应 .strm 文件</div>
          <div class="ml-3">- 若扩展名匹配“复制文件扩展名”，将其复制到“本地复制目标目录”</div>
          <div>• 处理完成后，若“处理后删除源文件”开关打开，将删除原始文件；扩展名不匹配的文件会被忽略</div>
          <div class="mt-2"><strong>注意：</strong>请确保 MoviePilot 对本地目录有读写权限、对网盘目录有写入权限。“本地复制目标目录”和“STRM 输出目录”均为可选项。</div>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, inject } from 'vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import AppleSettingsRow from '../ui/AppleSettingsRow.vue';
import PathMappingComposer from '../ui/PathMappingComposer.vue';

const activeSubTabs = inject('activeSubTabs', null);
const fallbackSubTab = ref('tab-pan-transfer');

const panSubTab = computed({
  get: () => (activeSubTabs ? activeSubTabs.pan : fallbackSubTab.value),
  set: (val) => {
    if (activeSubTabs) activeSubTabs.pan = val;
    else fallbackSubTab.value = val;
  },
});

const subTabItems = [
  { value: 'tab-pan-transfer', label: '网盘整理', icon: 'mdi-transfer' },
  { value: 'tab-pan-mount', label: '网盘挂载', icon: 'mdi-harddisk' },
  { value: 'tab-directory-upload', label: '目录上传', icon: 'mdi-upload' },
];

const config = inject('config');
const panTransferPaths = inject('panTransferPaths');
const shareReceivePaths = inject('shareReceivePaths');
const offlineDownloadPaths = inject('offlineDownloadPaths');
const directoryUploadPaths = inject('directoryUploadPaths');
const fuseStrmTakeoverRules = inject('fuseStrmTakeoverRules');
const addPath = inject('addPath');
const removePath = inject('removePath');
const addPanTransferPath = inject('addPanTransferPath');
const removePanTransferPath = inject('removePanTransferPath');
const addShareReceivePath = inject('addShareReceivePath');
const removeShareReceivePath = inject('removeShareReceivePath');
const addOfflineDownloadPath = inject('addOfflineDownloadPath');
const removeOfflineDownloadPath = inject('removeOfflineDownloadPath');
const openDirSelector = inject('openDirSelector');
const manualTransfer = inject('manualTransfer');
const checkLifeEventStatus = inject('checkLifeEventStatus');
const openConfigGeneratorDialog = inject('openConfigGeneratorDialog');

const unrecognizedNestedWarning = computed(() => {
  const unrec = String(config?.pan_transfer_unrecognized_path || '').trim().replace(/\/+$/, '');
  if (!unrec || unrec === '/') return '';
  const list = panTransferPaths?.value || [];
  for (const item of list) {
    const p = String(item?.path || '').trim().replace(/\/+$/, '');
    if (!p || p === '/') continue;
    if (unrec === p || unrec.startsWith(`${p}/`)) {
      return `检测到未识别目录「${unrec}」位于待整理目录「${p}」内部，这会导致循环触发整理，请修改为独立目录！`;
    }
  }
  return '';
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

.p115-rule-card {
  padding: 12px 14px;
  border-radius: 13px;
  background: var(--p115-bg-inset);
  border: 1px solid var(--p115-border-hairline);
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
  background: rgba(91, 207, 250, 0.24);
}

.p115-ext-link {
  color: var(--p115-blue-ink);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
