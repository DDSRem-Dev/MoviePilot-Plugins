<template>
  <div class="p115-section-stack">
    <!-- Top Segmented Control for 3 System Sub-Modules -->
    <div class="p115-subnav-bar">
      <AppleSegmentedControl v-model="systemSubTab" :items="subTabItems" />
    </div>

    <!-- ===================================================================
         1. 缓存配置 (tab-cache-config)
         =================================================================== -->
    <div v-if="systemSubTab === 'tab-cache-config'" class="p115-section-stack">
      <div class="p115-callout p115-callout--info">
        <v-icon size="18" color="primary" icon="mdi-cached" class="mt-0.5 flex-shrink-0" />
        <span>缓存清理功能可以帮助您清理插件运行过程中产生的内存与路径映射缓存数据，快速解决目录改名或跳转旧地址问题。</span>
      </div>

      <div class="p115-cache-grid">
        <AppleBentoCard title="清理文件路径 ID 缓存" icon="mdi-folder-cog-outline">
          <div class="d-flex flex-column justify-space-between h-100 gap-3">
            <p class="text-caption opacity-80 ma-0">
              清理文件路径 ID 缓存，包括目录 ID 到路径的映射缓存，适用于云盘大规模移动或重命名后重置索引。
            </p>
            <button
              type="button"
              class="p115-btn p115-btn--tonal w-100"
              :disabled="clearIdPathCacheLoading"
              @click="clearIdPathCache"
            >
              <v-progress-circular v-if="clearIdPathCacheLoading" indeterminate size="14" width="2" />
              <v-icon v-else size="16" icon="mdi-folder-cog-outline" />
              <span>清理文件路径 ID 缓存</span>
            </button>
          </div>
        </AppleBentoCard>

        <AppleBentoCard title="清理增量同步跳过路径缓存" icon="mdi-skip-next-circle-outline">
          <div class="d-flex flex-column justify-space-between h-100 gap-3">
            <p class="text-caption opacity-80 ma-0">
              清理增量同步跳过路径缓存，重置增量同步的跳过路径记录，用于重新处理之前跳过的文件。
            </p>
            <button
              type="button"
              class="p115-btn p115-btn--pink w-100"
              :disabled="clearIncrementSkipCacheLoading"
              @click="clearIncrementSkipCache"
            >
              <v-progress-circular v-if="clearIncrementSkipCacheLoading" indeterminate size="14" width="2" />
              <v-icon v-else size="16" icon="mdi-skip-next" />
              <span>清理增量同步跳过路径缓存</span>
            </button>
          </div>
        </AppleBentoCard>

        <AppleBentoCard title="清理 302 跳转缓存" icon="mdi-link-off">
          <div class="d-flex flex-column justify-space-between h-100 gap-3">
            <p class="text-caption opacity-80 ma-0">
              清理 302 跳转直链缓存，强制下次播放时向 115 重新请求最新下载跳转地址。
            </p>
            <button
              type="button"
              class="p115-btn p115-btn--tonal w-100"
              :disabled="clearR302CacheLoading"
              @click="clearR302Cache"
            >
              <v-progress-circular v-if="clearR302CacheLoading" indeterminate size="14" width="2" />
              <v-icon v-else size="16" icon="mdi-link-off" />
              <span>清理 302 跳转缓存</span>
            </button>
          </div>
        </AppleBentoCard>

        <AppleBentoCard title="清理 P115Client 缓存" icon="mdi-database-refresh-outline">
          <div class="d-flex flex-column justify-space-between h-100 gap-3">
            <p class="text-caption opacity-80 ma-0">
              清理 P115Client 共享的账号及分享目录节点缓存，后续访问时重新拉取最新目录信息。
            </p>
            <button
              type="button"
              class="p115-btn p115-btn--tonal w-100"
              :disabled="clearP115ClientCacheLoading"
              @click="clearP115ClientCache"
            >
              <v-progress-circular v-if="clearP115ClientCacheLoading" indeterminate size="14" width="2" />
              <v-icon v-else size="16" icon="mdi-cached" />
              <span>清理 P115Client 缓存</span>
            </button>
          </div>
        </AppleBentoCard>
      </div>
    </div>

    <!-- ===================================================================
         2. 数据增强 (tab-data-enhancement)
         =================================================================== -->
    <div v-else-if="systemSubTab === 'tab-data-enhancement'" class="p115-section-stack">
      <AppleSettingsGroup
        title="整理接管、元数据补充与遥测共享"
        subtitle="优化 MoviePilot 内置 115 上传、批量整理与重命名字段识别"
        icon="mdi-database-eye-outline"
      >
        <AppleSettingsRow
          title="存储模块选择"
          :description="
            config.pan_transfer_takeover
              ? '接管网盘整理功能必须使用 115网盘Plus'
              : '选择当前系统使用的 115 存储模块实例'
          "
          wide-control
        >
          <AppleSegmentedControl
            v-model="config.storage_module"
            :items="[
              { label: '115网盘', value: 'u115', icon: 'mdi-cloud-outline' },
              { label: '115网盘Plus', value: '115网盘Plus', icon: 'mdi-cloud-plus-outline' },
            ]"
            block
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="接管网盘整理"
          description="接管 MoviePilot 的 115 → 115 整理任务进行批量处理提升效率（需要存储模块为 115网盘Plus）"
          :subtray-open="Boolean(config.pan_transfer_takeover)"
        >
          <v-switch v-model="config.pan_transfer_takeover" color="info" density="compact" hide-details inset />
          <template #subtray>
            <div v-if="config.storage_module !== '115网盘Plus'" class="p115-callout p115-callout--warn">
              <v-icon size="16" color="warning" icon="mdi-alert-outline" class="mt-0.5 flex-shrink-0" />
              <span>
                接管网盘整理功能已启用，但当前存储模块为
                <strong>{{ config.storage_module === 'u115' ? '115网盘' : config.storage_module }}</strong>。请切换为
                <strong>115网盘Plus</strong>，否则接管功能将无法生效。
              </span>
            </div>
            <div v-else class="p115-callout p115-callout--info">
              <v-icon size="16" color="primary" icon="mdi-check-circle-outline" class="mt-0.5 flex-shrink-0" />
              <div>
                <div>• 当前存储模块为 <strong>115网盘Plus</strong>，批量接管整理流程可以正常生效</div>
                <div>• 与「整理模块增强」区别：本功能接管整理流程，而整理模块接口增强针对底层存储接口</div>
              </div>
            </div>
          </template>
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.pan_transfer_takeover"
          title="字幕与音轨关联整理"
          description="开启时同目录字幕与音轨随主视频一批处理；关闭时按独立任务处理"
        >
          <v-switch
            v-model="config.pan_transfer_linked_subtitle_audio"
            color="info"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体元数据补充"
          description="整理重命名时用 ffprobe 或中心化信息补全模板中未填的分辨率、编码等字段"
        >
          <v-switch v-model="config.rename_dict_supplement_enabled" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          v-if="config.rename_dict_supplement_enabled"
          title="媒体元数据写入策略"
          description="针对 videoFormat、videoCodec、videoBit、audioCodec、fps、effect 等字段：仅补全缺失空值或始终覆盖"
          wide-control
        >
          <v-select
            v-model="config.rename_dict_supplement_overwrite_mode"
            :items="[
              { title: '仅补全缺失或空值', value: 'fill_missing' },
              { title: '始终用探测结果覆盖上述键', value: 'always' },
            ]"
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="上传模块增强"
          description="开启后将对整个 MoviePilot 系统内所有调用 115 网盘上传的功能生效（支持秒传等待与分片复判）"
        >
          <v-switch v-model="config.upload_module_enhancement" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="整理模块增强" description="旧版接口增强开关">
          <template #badge>
            <span class="p115-badge p115-badge--neutral">此功能已废弃</span>
          </template>
          <v-switch
            v-model="config.transfer_module_enhancement"
            color="info"
            density="compact"
            hide-details
            inset
            :disabled="isTransferModuleEnhancementLocked"
          />
        </AppleSettingsRow>

        <AppleSettingsRow title="上传分享链接" description="参与社区共享匿名分享元数据">
          <v-switch v-model="config.upload_share_info" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="上传离线下载链接" description="参与优化离线秒传命中率">
          <v-switch v-model="config.upload_offline_info" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow title="错误信息上传" description="自动上报插件异常堆栈用于问题定位">
          <v-switch v-model="config.error_info_upload" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="设备标识 (Machine ID)"
          description="查看当前运行实例的唯一设备 ID（授权绑定与排查问题时使用）"
          :subtray-open="Boolean(machineId)"
        >
          <button type="button" class="p115-btn p115-btn--tonal p115-btn--sm" @click="getMachineId">
            <v-icon size="15" icon="mdi-identifier" />
            <span>显示设备 ID</span>
          </button>
          <template #subtray>
            <v-text-field
              v-model="machineId"
              label="Machine ID"
              readonly
              density="compact"
              variant="outlined"
              hide-details
              class="p115-mono"
            />
          </template>
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <div class="p115-disclosure-bezel">
        <details class="p115-disclosure" :open="Boolean(config.upload_module_enhancement)">
          <summary>
            <span class="p115-disclosure-icon">
              <v-icon size="16" icon="mdi-tune-variant" />
            </span>
            <span class="p115-disclosure-meta">
              <span class="p115-disclosure-title">上传模块增强详细参数配置</span>
              <span class="p115-disclosure-sub">秒传休眠等待、分片复判策略与文件大小阈值</span>
            </span>
          </summary>
          <div class="p115-disclosure-body">
            <AppleSettingsRow
              title="秒传失败直接退出"
              description="无法秒传或秒传等待超时时直接跳过实际分片上传并返回失败"
            >
              <v-switch
                v-model="config.upload_module_skip_slow_upload"
                color="info"
                density="compact"
                hide-details
                inset
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              v-if="config.upload_module_skip_slow_upload"
              title="秒传失败后跳过上传的文件大小阈值"
              description="大于等于此值跳过上传，小于此值继续普通上传（支持 K、M、G，留空则全部跳过）"
              wide-control
            >
              <v-text-field
                v-model="skipSlowUploadSizeFormattedRef"
                placeholder="例如: 100M, 1G (可为空)"
                clearable
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="秒传等待发送通知"
              description="文件进入秒传休眠等待队列时推送通知"
            >
              <v-switch v-model="config.upload_module_notify" color="info" density="compact" hide-details inset />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="上传结果通知"
              description="文件上传完成或失败后发送结果通知"
            >
              <v-switch v-model="config.upload_open_result_notify" color="info" density="compact" hide-details inset />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="秒传休眠等待时间"
              description="单次秒传未命中后的休眠等待间隔"
              wide-control
            >
              <v-text-field
                v-model.number="config.upload_module_wait_time"
                type="number"
                suffix="秒"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="秒传最长等待时间"
              description="秒传轮询等待的最大总时长"
              wide-control
            >
              <v-text-field
                v-model.number="config.upload_module_wait_timeout"
                type="number"
                suffix="秒"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="跳过等待秒传的文件大小阈值"
              description="文件小于此值将跳过等待秒传直接上传（支持 K、M、G）"
              wide-control
            >
              <v-text-field
                v-model="skipUploadWaitSizeFormattedRef"
                placeholder="例如: 5M, 1.5G (可为空)"
                clearable
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="强制等待秒传的文件大小阈值"
              description="文件大于此值将强制进入秒传等待（支持 K、M、G）"
              wide-control
            >
              <v-text-field
                v-model="forceUploadWaitSizeFormattedRef"
                placeholder="例如: 5M, 1.5G (可为空)"
                clearable
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              title="分片上传期间复判秒传"
              description="分片上传过程中每隔指定时长复判一次秒传，命中后立即中止剩余分片并转秒传"
            >
              <v-switch
                v-model="config.upload_module_recheck_secupload"
                color="info"
                density="compact"
                hide-details
                inset
              />
            </AppleSettingsRow>

            <AppleSettingsRow
              v-if="config.upload_module_recheck_secupload"
              title="分片上传复判秒传间隔"
              description="复判轮询周期，最小 60 秒"
              wide-control
            >
              <v-text-field
                v-model.number="config.upload_module_recheck_secupload_interval"
                type="number"
                min="60"
                suffix="秒"
                density="compact"
                variant="outlined"
                hide-details
              />
            </AppleSettingsRow>

            <div class="pa-3">
              <div class="p115-callout p115-callout--info">
                <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
                <div>
                  <strong>秒传失败直接退出：</strong>此功能开启后，对于无法秒传或者秒传等待超时的文件将直接跳过上传步骤，整理返回失败。若设置了“秒传失败后跳过上传的文件大小阈值”，则仅大于等于该阈值的文件跳过上传。
                </div>
              </div>
            </div>
          </div>
        </details>
      </div>

      <div class="p115-callout p115-callout--warn">
        <v-icon size="18" color="warning" icon="mdi-shield-alert-outline" class="mt-0.5 flex-shrink-0" />
        <div>
          <div class="font-weight-bold mb-0.5">风险与免责声明：</div>
          <div>
            • 插件程序内包含可选的 Sentry 分析组件，详见
            <a href="https://sentry.io/privacy/" target="_blank" rel="noopener noreferrer" class="p115-ext-link">
              Sentry Privacy Policy
            </a>
          </div>
          <div>• 插件程序将在必要时上传错误信息及运行环境信息，并记录程序运行重要节点保存追踪数据至少 72 小时</div>
        </div>
      </div>
    </div>

    <!-- ===================================================================
         3. 高级配置 (tab-advanced-configuration)
         =================================================================== -->
    <div v-else-if="systemSubTab === 'tab-advanced-configuration'" class="p115-section-stack">
      <AppleSettingsGroup
        title="宿主导航与原生媒体提取"
        icon="mdi-application-cog-outline"
      >
        <AppleSettingsRow
          title="侧栏显示的页面"
          description="可多选，顺序即侧栏顺序；全部取消则侧栏不显示对应入口，保存后刷新页面生效"
          wide-control
        >
          <v-select
            v-model="config.sidebar_nav_keys"
            :items="sidebarNavKeyItems"
            item-title="title"
            item-value="value"
            label="侧栏页面入口"
            multiple
            chips
            closable-chips
            density="compact"
            variant="outlined"
            hide-details
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="原生 Emby 媒体信息提取"
          description="开启后各处的「Emby 媒体信息提取」将仅通过 Emby API 触发，不依赖神医助手PRO"
        >
          <v-switch v-model="config.native_emby_mediainfo_enabled" color="primary" density="compact" hide-details inset />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="STRM URL 文件名称编码"
          :description="
            config.strm_url_template_enabled
              ? '已启用自定义模板时优先使用模板，模板渲染失败时将使用此设置作为后备方案（模板内可用 urlencode 过滤器）'
              : '启用后，STRM 文件中的 URL 会对文件名进行 URL 编码处理'
          "
        >
          <v-switch v-model="config.strm_url_encode" color="info" density="compact" hide-details inset />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <!-- Jinja2 URL Template -->
      <AppleSettingsGroup
        title="STRM URL 自定义模板 (Jinja2)"
        subtitle="支持按全局或特定文件扩展名自定义生成的直链 URL 结构"
        icon="mdi-code-braces"
      >
        <AppleSettingsRow
          title="启用 STRM URL 自定义模板"
          description="启用后可以使用 Jinja2 模板语法自定义 STRM 文件的 URL 格式"
        >
          <v-switch v-model="config.strm_url_template_enabled" color="primary" density="compact" hide-details inset />
        </AppleSettingsRow>

        <template v-if="config.strm_url_template_enabled">
          <AppleSettingsRow title="STRM URL 基础模板 (Jinja2)" vertical>
            <div class="p115-callout p115-callout--info mb-2">
              <v-icon size="16" color="primary" icon="mdi-information-outline" class="mt-0.5 flex-shrink-0" />
              <div>
                <strong>STRM URL 生成优先级：</strong> 1. URL 自定义模板 (Jinja2) → 2. FUSE STRM 接管 → 3. 基础设置默认格式
              </div>
            </div>
            <v-textarea
              v-model="config.strm_url_template"
              rows="3"
              variant="outlined"
              density="compact"
              clearable
              hide-details
              class="p115-mono"
              placeholder="{{ base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}"
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="STRM URL 扩展名特定模板 (Jinja2)"
            description="优先级高于基础模板。格式：ext1,ext2 => template（每行一个）"
            vertical
          >
            <v-textarea
              v-model="config.strm_url_template_custom"
              rows="4"
              variant="outlined"
              density="compact"
              clearable
              hide-details
              class="p115-mono"
              placeholder="mkv,mp4 => {{ base_url }}?pickcode={{ pickcode }}&file_name={{ file_name | urlencode }}&file_path={{ file_path | path_encode }}"
            />

            <details v-pre class="p115-guide-details mt-2">
              <summary>查看可用 Jinja2 变量、过滤器与示例</summary>
              <div class="p115-guide-body">
                <div class="mb-2">
                  <strong>可用变量：</strong>
                  <code>base_url</code>（基础URL）、<code>pickcode</code>（普通STRM）、<code>share_code</code>（分享码）、<code>receive_code</code>（提取码）、<code>file_id</code>（文件ID）、<code>file_name</code>（文件名称）、<code>file_path</code>（文件网盘路径）
                </div>
                <div class="mb-2">
                  <strong>可用过滤器：</strong>
                  <code>urlencode</code>（如 <code>{{ file_name | urlencode }}</code>）、<code>path_encode</code>（保留斜杠，如 <code>{{ file_path | path_encode }}</code>）、<code>upper</code>、<code>lower</code>、<code>default</code>（如 <code>{{ file_name | default('unknown') }}</code>）
                </div>
                <div class="mb-1"><strong>普通 STRM 示例：</strong></div>
                <pre class="p115-code-pre">{{ base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}</pre>
                <div class="mt-2 mb-1"><strong>分享 STRM 示例：</strong></div>
                <pre class="p115-code-pre">{{ base_url }}?share_code={{ share_code }}&receive_code={{ receive_code }}&id={{ file_id }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}</pre>
              </div>
            </details>
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>

      <!-- Jinja2 Filename Template -->
      <AppleSettingsGroup
        title="STRM 文件名自定义模板 (Jinja2)"
        subtitle="自定义生成的 .strm 本地文件命名规则"
        icon="mdi-rename-box-outline"
      >
        <AppleSettingsRow
          title="启用 STRM 文件名自定义模板"
          description="启用后可以使用 Jinja2 模板语法自定义 STRM 文件的文件名格式"
        >
          <v-switch
            v-model="config.strm_filename_template_enabled"
            color="primary"
            density="compact"
            hide-details
            inset
          />
        </AppleSettingsRow>

        <template v-if="config.strm_filename_template_enabled">
          <AppleSettingsRow title="STRM 文件名基础模板 (Jinja2)" vertical>
            <v-textarea
              v-model="config.strm_filename_template"
              rows="2"
              variant="outlined"
              density="compact"
              clearable
              hide-details
              class="p115-mono"
              placeholder="{{ file_stem }}.strm"
            />
          </AppleSettingsRow>

          <AppleSettingsRow
            title="STRM 文件名扩展名特定模板 (Jinja2)"
            description="优先级高于基础模板。格式：ext1,ext2 => template（每行一个）"
            vertical
          >
            <v-textarea
              v-model="config.strm_filename_template_custom"
              rows="3"
              variant="outlined"
              density="compact"
              clearable
              hide-details
              class="p115-mono"
              placeholder="iso => {{ file_stem }}.iso.strm&#10;mkv,mp4 => {{ file_stem | upper }}.strm"
            />

            <details v-pre class="p115-guide-details mt-2">
              <summary>查看文件名可用变量、过滤器与注意事项</summary>
              <div class="p115-guide-body">
                <div class="mb-2">
                  <strong>可用变量：</strong>
                  <code>file_name</code>（含扩展名）、<code>file_stem</code>（不含扩展名）、<code>file_suffix</code>（含点号，如 .mkv）
                </div>
                <div class="mb-2">
                  <strong>可用过滤器：</strong>
                  <code>upper</code>、<code>lower</code>、<code>sanitize</code>（清理非法字符，如 <code>{{ file_name | sanitize }}</code>）、<code>default</code>
                </div>
                <div class="mb-2">
                  <strong>示例：</strong>默认 <code>{{ file_stem }}.strm</code> · ISO <code>{{ file_stem }}.iso.strm</code> · 大写 <code>{{ file_stem | upper }}.strm</code>
                </div>
                <div>• 模板渲染后的文件名会自动清理非法字符（&lt;&gt;:&quot;/\|?*），未指定扩展名时自动补全 <code>.strm</code></div>
              </div>
            </details>
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>

      <!-- Keyword Whitelist / Blacklist -->
      <AppleSettingsGroup
        title="关键词过滤黑白名单"
        subtitle="输入关键词后按回车确认，可添加多个标签"
        icon="mdi-filter-check-outline"
      >
        <AppleSettingsRow
          title="STRM 文件关键词过滤黑名单"
          description="包含这些词的视频文件将不会生成 STRM 文件"
          vertical
        >
          <v-combobox
            v-model="config.strm_generate_blacklist"
            multiple
            chips
            closable-chips
            variant="outlined"
            density="compact"
            hide-details
            placeholder="输入关键词按回车添加"
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体信息文件下载关键词过滤白名单"
          description="不包含这些词的媒体信息文件将不会下载"
          vertical
        >
          <v-combobox
            v-model="config.mediainfo_download_whitelist"
            multiple
            chips
            closable-chips
            variant="outlined"
            density="compact"
            hide-details
            placeholder="输入关键词按回车添加"
          />
        </AppleSettingsRow>

        <AppleSettingsRow
          title="媒体信息文件下载关键词过滤黑名单"
          description="包含这些词的媒体信息文件将不会下载"
          vertical
        >
          <v-combobox
            v-model="config.mediainfo_download_blacklist"
            multiple
            chips
            closable-chips
            variant="outlined"
            density="compact"
            hide-details
            placeholder="输入关键词按回车添加"
          />
        </AppleSettingsRow>
      </AppleSettingsGroup>

      <!-- Request Timeout Control -->
      <AppleSettingsGroup
        title="网络请求超时控制"
        subtitle="为所有 115 网盘 API 请求附加超时保护，防止网络拥塞导致任务卡死（0 表示不限制）"
        icon="mdi-timer-cog-outline"
      >
        <AppleSettingsRow title="启用请求超时控制" description="区分快速元数据操作与长耗时传输操作超时阈值">
          <v-switch v-model="config.timeout_enabled" color="primary" density="compact" hide-details inset />
        </AppleSettingsRow>

        <template v-if="config.timeout_enabled">
          <AppleSettingsRow
            title="普通操作超时"
            description="适用于列表、详情、重命名、删除等快速 API 请求（0 表示不限制）"
            vertical
          >
            <div class="p115-timeout-grid">
              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">连接超时</span>
                  <span class="p115-field-default">默认 30s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_default_connect"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>

              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">连接池超时</span>
                  <span class="p115-field-default">默认 15s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_default_pool"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>

              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">读取超时</span>
                  <span class="p115-field-default">默认 60s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_default_read"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>

              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">写入超时</span>
                  <span class="p115-field-default">默认 60s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_default_write"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>
            </div>
          </AppleSettingsRow>

          <AppleSettingsRow
            title="慢操作超时"
            description="适用于下载链接获取、上传初始化、分享列表获取、生活事件拉取等长耗时请求（0 表示不限制）"
            vertical
          >
            <div class="p115-timeout-grid">
              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">连接超时</span>
                  <span class="p115-field-default">默认 30s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_slow_connect"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>

              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">连接池超时</span>
                  <span class="p115-field-default">默认 15s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_slow_pool"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>

              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">读取超时</span>
                  <span class="p115-field-default">默认 300s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_slow_read"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>

              <div class="p115-field-cell">
                <div class="p115-field-head">
                  <span class="p115-field-label">写入超时</span>
                  <span class="p115-field-default">默认 300s</span>
                </div>
                <v-text-field
                  v-model.number="config.timeout_slow_write"
                  type="number"
                  min="0"
                  hide-spin-buttons
                  suffix="秒"
                  density="compact"
                  variant="outlined"
                  hide-details
                  class="p115-tabular"
                />
              </div>
            </div>
          </AppleSettingsRow>
        </template>
      </AppleSettingsGroup>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, inject } from 'vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';
import AppleBentoCard from '../ui/AppleBentoCard.vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import AppleSettingsRow from '../ui/AppleSettingsRow.vue';

const activeSubTabs = inject('activeSubTabs', null);
const fallbackSubTab = ref('tab-cache-config');

const systemSubTab = computed({
  get: () => (activeSubTabs ? activeSubTabs.system : fallbackSubTab.value),
  set: (val) => {
    if (activeSubTabs) activeSubTabs.system = val;
    else fallbackSubTab.value = val;
  },
});

const subTabItems = [
  { value: 'tab-cache-config', label: '缓存配置', icon: 'mdi-cached' },
  { value: 'tab-data-enhancement', label: '数据增强', icon: 'mdi-database-eye-outline' },
  { value: 'tab-advanced-configuration', label: '高级配置', icon: 'mdi-tune' },
];

const sidebarNavKeyItems = [{ title: '115助手仪表盘', value: 'start' }];

const config = inject('config');
const isTransferModuleEnhancementLocked = inject('isTransferModuleEnhancementLocked');
const clearIdPathCacheLoading = inject('clearIdPathCacheLoading');
const clearP115ClientCacheLoading = inject('clearP115ClientCacheLoading');
const clearIncrementSkipCacheLoading = inject('clearIncrementSkipCacheLoading');
const clearR302CacheLoading = inject('clearR302CacheLoading');
const skipUploadWaitSizeFormattedRef = inject('skipUploadWaitSizeFormattedRef');
const forceUploadWaitSizeFormattedRef = inject('forceUploadWaitSizeFormattedRef');
const skipSlowUploadSizeFormattedRef = inject('skipSlowUploadSizeFormattedRef');
const machineId = inject('machineId');
const clearIdPathCache = inject('clearIdPathCache');
const clearP115ClientCache = inject('clearP115ClientCache');
const clearIncrementSkipCache = inject('clearIncrementSkipCache');
const clearR302Cache = inject('clearR302Cache');
const getMachineId = inject('getMachineId');
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

.p115-cache-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.p115-code-pre {
  margin: 0;
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--p115-bg-card);
  border: 1px solid var(--p115-border-hairline);
  font-family: var(--p115-font-mono);
  font-size: 0.76rem;
  white-space: pre-wrap;
  word-break: break-all;
}

.p115-ext-link {
  color: var(--p115-blue-ink);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
}

@media (max-width: 680px) {
  .p115-cache-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
