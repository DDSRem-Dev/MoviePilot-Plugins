<template>
  <v-card-text class="pa-0">
    <v-tabs v-model="systemSubTab" color="primary" class="sub-category-tabs" slider-color="primary">
      <v-tab value="tab-cache-config" class="sub-tab">
        <v-icon size="small" start>mdi-cached</v-icon>缓存配置
      </v-tab>
      <v-tab value="tab-data-enhancement" class="sub-tab">
        <v-icon size="small" start>mdi-database-eye-outline</v-icon>数据增强
      </v-tab>
      <v-tab value="tab-advanced-configuration" class="sub-tab">
        <v-icon size="small" start>mdi-tune</v-icon>高级配置
      </v-tab>
    </v-tabs>
    <v-divider></v-divider>
    <v-window v-model="systemSubTab" :touch="false" class="tab-window">
      <v-window-item value="tab-cache-config">
        <v-card-text>
          <v-row>
            <v-col cols="12">
              <v-card variant="outlined" class="mb-4">
                <v-card-item>
                  <v-card-title class="d-flex align-center">
                    <v-icon start>mdi-cached</v-icon>
                    <span class="text-h6">缓存管理</span>
                  </v-card-title>
                </v-card-item>
                <v-card-text>
                  <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
                    <div class="text-caption">缓存清理功能可以帮助您清理插件运行过程中产生的缓存数据，解决部分因缓存导致的问题。</div>
                  </v-alert>

                  <v-row>
                    <v-col cols="12" md="6">
                      <v-card variant="outlined" class="pa-4 d-flex flex-column cache-card" style="height: 100%;">
                        <div class="d-flex align-center mb-3">
                          <v-icon color="primary" class="mr-2">mdi-folder-cog</v-icon>
                          <span class="text-subtitle-1 font-weight-medium">清理文件路径ID缓存</span>
                        </div>
                        <p class="text-body-2 text-grey-darken-1 mb-3 flex-grow-1">
                          清理文件路径ID缓存，包括目录ID到路径的映射缓存。
                        </p>
                        <v-btn color="primary" variant="outlined" :loading="clearIdPathCacheLoading"
                          @click="clearIdPathCache" prepend-icon="mdi-folder-cog" block>
                          清理文件路径ID缓存
                        </v-btn>
                      </v-card>
                    </v-col>

                    <v-col cols="12" md="6">
                      <v-card variant="outlined" class="pa-4 d-flex flex-column cache-card" style="height: 100%;">
                        <div class="d-flex align-center mb-3">
                          <v-icon color="warning" class="mr-2">mdi-skip-next</v-icon>
                          <span class="text-subtitle-1 font-weight-medium">清理增量同步跳过路径缓存</span>
                        </div>
                        <p class="text-body-2 text-grey-darken-1 mb-3 flex-grow-1">
                          清理增量同步跳过路径缓存，重置增量同步的跳过路径记录，用于重新处理之前跳过的文件。
                        </p>
                        <v-btn color="warning" variant="outlined" :loading="clearIncrementSkipCacheLoading"
                          @click="clearIncrementSkipCache" prepend-icon="mdi-skip-next" block>
                          清理增量同步跳过路径缓存
                        </v-btn>
                      </v-card>
                    </v-col>

                    <v-col cols="12" md="6">
                      <v-card variant="outlined" class="pa-4 d-flex flex-column cache-card" style="height: 100%;">
                        <div class="d-flex align-center mb-3">
                          <v-icon color="info" class="mr-2">mdi-link-off</v-icon>
                          <span class="text-subtitle-1 font-weight-medium">清理302跳转缓存</span>
                        </div>
                        <p class="text-body-2 text-grey-darken-1 mb-3 flex-grow-1">
                          清理302跳转链接缓存，强制重新获取最新下载跳转地址。
                        </p>
                        <v-btn color="info" variant="outlined" :loading="clearR302CacheLoading" @click="clearR302Cache"
                          prepend-icon="mdi-link-off" block>
                          清理302跳转缓存
                        </v-btn>
                      </v-card>
                    </v-col>
                  </v-row>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-data-enhancement">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.error_info_upload" label="错误信息上传" color="info" density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.upload_module_enhancement" label="上传模块增强" color="info"
                density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.transfer_module_enhancement" label="整理模块增强" color="info" density="compact"
                :disabled="isTransferModuleEnhancementLocked" hint="此功能已废弃" persistent-hint></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="6">
              <v-switch v-model="config.pan_transfer_takeover" label="接管网盘整理" color="info" density="compact"
                hint="接管 115 → 115 整理任务进行批量处理，需要存储模块为 115网盘Plus" persistent-hint></v-switch>
            </v-col>
            <v-col cols="12" md="6" v-if="config.pan_transfer_takeover">
              <v-switch v-model="config.pan_transfer_linked_subtitle_audio" label="字幕与音轨关联整理" color="info"
                density="compact" hint="开：同目录字幕/音轨随主视频一批处理；关：与 MP 一致，字幕/音轨为独立任务" persistent-hint></v-switch>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.rename_dict_supplement_enabled" label="媒体元数据补充" color="info" density="compact"
                hint="整理重命名时用 ffprobe 或中心化信息补全模板中未填的分辨率、编码等字段" persistent-hint></v-switch>
            </v-col>
            <v-col cols="12" md="8">
              <v-select v-model="config.rename_dict_supplement_overwrite_mode" label="媒体元数据写入策略" :items="[
                { title: '仅补全缺失或空值', value: 'fill_missing' },
                { title: '始终用探测结果覆盖上述键', value: 'always' },
              ]" density="compact" color="info" :disabled="!config.rename_dict_supplement_enabled"
                hint="针对 videoFormat、videoCodec、videoBit、audioCodec、fps、effect 等：仅补全＝缺或空才写入；始终覆盖＝以 ffprobe/中心化结果为准覆盖"
                persistent-hint></v-select>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.upload_share_info" label="上传分享链接" color="info" density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.upload_offline_info" label="上传离线下载链接" color="info" density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="4">
              <v-select v-model="config.storage_module" label="存储模块选择" :items="[
                { title: '115网盘', value: 'u115' },
                { title: '115网盘Plus', value: '115网盘Plus' }
              ]" chips closable-chips :hint="config.pan_transfer_takeover ? '接管网盘整理功能必须使用 115网盘Plus' : '选择使用的存储模块'"
                persistent-hint></v-select>
            </v-col>
          </v-row>
          <v-row v-if="config.pan_transfer_takeover">
            <v-col cols="12">
              <v-alert type="warning" variant="tonal" density="compact" icon="mdi-alert"
                v-if="config.storage_module !== '115网盘Plus'">
                <div class="text-body-2 mb-1"><strong>提示：</strong></div>
                <div class="text-caption">
                  接管网盘整理功能已启用，但当前存储模块为 <strong>{{ config.storage_module === 'u115' ? '115网盘' :
                    config.storage_module
                  }}</strong>。
                  请将存储模块切换为 <strong>115网盘Plus</strong>，否则接管功能将无法生效。
                </div>
              </v-alert>
              <v-alert type="info" variant="tonal" density="compact" icon="mdi-information" v-else>
                <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• <strong>接管网盘整理：</strong>启用后将接管 MoviePilot 的 115 → 115
                    整理任务，使用批量处理提升整理效率
                  </div>
                  <div class="mb-1">• <strong>与整理模块接口增强的区别：</strong>此功能是接管整理流程，而整理模块接口增强是对存储接口的优化</div>
                  <div class="mb-1">• <strong>字幕与音轨关联整理：</strong>可在上方单独开关；关闭后与 MoviePilot 一致按独立字幕/音轨任务处理</div>
                  <div>• 当前存储模块为 <strong>115网盘Plus</strong>，功能可以正常使用</div>
                </div>
              </v-alert>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4" class="d-flex align-center">
              <v-btn @click="getMachineId" size="small" prepend-icon="mdi-identifier">显示设备ID</v-btn>
            </v-col>
          </v-row>

          <v-row v-if="machineId">
            <v-col cols="12">
              <v-text-field v-model="machineId" label="Machine ID" readonly density="compact" variant="outlined"
                hide-details="auto"></v-text-field>
            </v-col>
          </v-row>

          <!-- 上传模块增强配置 -->
          <v-expansion-panels variant="tonal" class="mt-6">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon icon="mdi-tune-variant" class="mr-2"></v-icon>
                上传模块增强配置
              </v-expansion-panel-title>
              <v-expansion-panel-text class="pa-4">
                <v-row>
                  <v-col cols="12" md="4">
                    <v-switch v-model="config.upload_module_skip_slow_upload" label="秒传失败直接退出" color="info"
                      density="compact"></v-switch>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-switch v-model="config.upload_module_notify" label="秒传等待发送通知" color="info"
                      density="compact"></v-switch>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-switch v-model="config.upload_open_result_notify" label="上传结果通知" color="info"
                      density="compact"></v-switch>
                  </v-col>
                </v-row>
                <v-row>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.upload_module_wait_time" label="秒传休眠等待时间（单位秒）" type="number"
                      hint="秒传休眠等待时间（单位秒）" persistent-hint density="compact"></v-text-field>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field v-model.number="config.upload_module_wait_timeout" label="秒传最长等待时间（单位秒）" type="number"
                      hint="秒传最长等待时间（单位秒）" persistent-hint density="compact"></v-text-field>
                  </v-col>
                </v-row>
                <v-row>
                  <v-col cols="12" md="6">
                    <v-text-field v-model="skipUploadWaitSizeFormattedRef" label="跳过等待秒传的文件大小阈值"
                      hint="文件小于此值将跳过等待秒传（单位支持K，M，G）" persistent-hint density="compact" placeholder="例如: 5M, 1.5G (可为空)"
                      clearable></v-text-field>
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field v-model="forceUploadWaitSizeFormattedRef" label="强制等待秒传的文件大小阈值"
                      hint="文件大于此值将强制等待秒传（单位支持K，M，G）" persistent-hint density="compact" placeholder="例如: 5M, 1.5G (可为空)"
                      clearable></v-text-field>
                  </v-col>
                </v-row>
                <v-row v-if="config.upload_module_skip_slow_upload">
                  <v-col cols="12" md="6">
                    <v-text-field v-model="skipSlowUploadSizeFormattedRef" label="秒传失败后跳过上传的文件大小阈值"
                      hint="秒传失败后，大于等于此值的文件将跳过上传，小于此值的文件将继续上传（单位支持K，M，G）" persistent-hint density="compact"
                      placeholder="例如: 100M, 1G (可为空)" clearable></v-text-field>
                  </v-col>
                </v-row>
                <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                  <div class="text-body-2 mb-1"><strong>秒传失败直接退出：</strong></div>
                  <div class="text-caption">此功能开启后，对于无法秒传或者秒传等待超时的文件将直接跳过上传步骤，整理返回失败。</div>
                  <div class="text-caption mt-1">
                    如果设置了"秒传失败后跳过上传的文件大小阈值"，则只有大于等于该阈值的文件才会跳过上传，小于该阈值的文件将继续执行上传。
                  </div>
                </v-alert>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>

          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>115上传增强有效范围：</strong></div>
            <div class="text-caption">此功能开启后，将对整个MoviePilot系统内所有调用115网盘上传的功能生效。</div>
          </v-alert>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-body-2 mb-1"><strong>风险与免责声明</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 插件程序内包含可选的Sentry分析组件，详见<a href="https://sentry.io/privacy/" target="_blank"
                  style="color: inherit; text-decoration: underline;">Sentry Privacy
                  Policy</a></div>
              <div class="mb-1">• 插件程序将在必要时上传错误信息及运行环境信息</div>
              <div>• 插件程序将记录程序运行重要节点并保存追踪数据至少72小时</div>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-advanced-configuration">
        <v-card-text>
          <v-row>
            <v-col cols="12">
              <v-select v-model="config.sidebar_nav_keys" :items="sidebarNavKeyItems" item-title="title"
                item-value="value" label="侧栏显示的页面" multiple chips closable-chips color="primary" density="compact"
                hint="可多选，顺序即侧栏顺序；全部取消则侧栏不显示对应入口，保存后刷新页面生效" persistent-hint></v-select>
            </v-col>
          </v-row>

          <v-divider class="my-6"></v-divider>

          <v-row>
            <v-col cols="12">
              <v-switch v-model="config.native_emby_mediainfo_enabled" label="原生 Emby 媒体信息提取" color="primary"
                density="compact" hint="开启后各处的「Emby 媒体信息提取」将仅通过 Emby API 触发，不依赖神医助手PRO" persistent-hint></v-switch>
            </v-col>
          </v-row>

          <v-divider class="my-6"></v-divider>

          <!-- STRM URL 自定义模板 -->
          <v-row>
            <v-col cols="12">
              <v-switch v-model="config.strm_url_template_enabled" label="启用 STRM URL 自定义模板 (Jinja2)" color="primary"
                density="compact" hint="启用后可以使用 Jinja2 模板语法自定义 STRM 文件的 URL 格式" persistent-hint></v-switch>
            </v-col>
          </v-row>

          <v-expand-transition>
            <div v-if="config.strm_url_template_enabled">
              <v-alert type="info" variant="tonal" density="compact" class="mt-2 mb-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>STRM URL 生成优先级：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">1. <strong>URL 自定义模板</strong>（如果启用）：优先使用 Jinja2 模板渲染</div>
                  <div class="mb-1">2. <strong>FUSE STRM 接管</strong>（如果启用且匹配规则）：生成指向挂载路径的 STRM 内容</div>
                  <div>3. <strong>默认格式</strong>：使用基础设置中的「STRM文件URL格式」和「STRM URL 文件名称编码」</div>
                </div>
              </v-alert>
              <v-row class="mt-2">
                <v-col cols="12">
                  <v-textarea v-model="config.strm_url_template" label="STRM URL 基础模板 (Jinja2)"
                    hint="支持 Jinja2 语法，可用变量和过滤器见下方说明" persistent-hint rows="4" variant="outlined" density="compact"
                    placeholder="{{ base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif %}"
                    clearable></v-textarea>
                </v-col>
              </v-row>

              <v-row class="mt-2">
                <v-col cols="12">
                  <v-textarea v-model="config.strm_url_template_custom" label="STRM URL 扩展名特定模板 (Jinja2)"
                    hint="为特定文件扩展名指定 URL 模板，优先级高于基础模板。格式：ext1,ext2 => template（每行一个）" persistent-hint rows="5"
                    variant="outlined" density="compact"
                    placeholder="例如：&#10;mkv,mp4 => {{ base_url }}?pickcode={{ pickcode }}&file_name={{ file_name | urlencode }}&file_path={{ file_path | path_encode }}&#10;iso => {{ base_url }}?pickcode={{ pickcode }}&file_name={{ file_name | urlencode }}"
                    clearable></v-textarea>
                </v-col>
              </v-row>

              <v-card variant="outlined" class="mt-3" color="info" v-pre>
                <v-card-text class="pa-3">
                  <div class="mb-3">
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-information" size="small" class="mr-2" color="info"></v-icon>
                      <strong class="text-body-2">可用变量</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-1"><code class="text-caption">base_url</code> - 基础 URL</div>
                      <div class="mb-1"><code class="text-caption">pickcode</code> - 文件 pickcode（仅普通 STRM）
                      </div>
                      <div class="mb-1"><code class="text-caption">share_code</code> - 分享码（仅分享 STRM）</div>
                      <div class="mb-1"><code class="text-caption">receive_code</code> - 提取码（仅分享 STRM）
                      </div>
                      <div class="mb-1"><code class="text-caption">file_id</code> - 文件 ID</div>
                      <div class="mb-1"><code class="text-caption">file_name</code> - 文件名称</div>
                      <div class="mb-1"><code class="text-caption">file_path</code> - 文件网盘路径</div>
                    </div>
                  </div>

                  <v-divider class="my-3"></v-divider>

                  <div class="mb-3">
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-filter" size="small" class="mr-2" color="info"></v-icon>
                      <strong class="text-body-2">可用过滤器</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-1"><code class="text-caption">urlencode</code> - URL 编码（如：<code
                          class="text-caption">{{ file_name | urlencode }}</code>）</div>
                      <div class="mb-1"><code class="text-caption">path_encode</code> - 路径编码，保留斜杠（如：<code
                          class="text-caption">{{ file_path | path_encode }}</code>）</div>
                      <div class="mb-1"><code class="text-caption">upper</code> - 转大写</div>
                      <div class="mb-1"><code class="text-caption">lower</code> - 转小写</div>
                      <div class="mb-1"><code class="text-caption">default</code> - 默认值（如：<code class="text-caption">{{
                    file_name | default('unknown') }}</code>）</div>
                    </div>
                  </div>

                  <v-divider class="my-3"></v-divider>

                  <div>
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-code-tags" size="small" class="mr-2" color="info"></v-icon>
                      <strong class="text-body-2">模板示例</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-2">
                        <div class="text-caption text-medium-emphasis mb-1">普通 STRM:</div>
                        <code class="text-caption pa-2 d-block"
                          style="background-color: rgba(var(--v-theme-on-surface), 0.05); border-radius: 8px; font-family: 'Courier New', monospace; word-break: break-all; display: block; white-space: pre-wrap; border: 1px solid rgba(var(--v-theme-on-surface), 0.12); padding: 10px;">{{
                    base_url }}?pickcode={{ pickcode }}{% if file_name %}&file_name={{ file_name
                    | urlencode }}{% endif %}</code>
                      </div>
                      <div>
                        <div class="text-caption text-medium-emphasis mb-1">分享 STRM:</div>
                        <code class="text-caption pa-2 d-block"
                          style="background-color: rgba(var(--v-theme-on-surface), 0.05); border-radius: 8px; font-family: 'Courier New', monospace; word-break: break-all; display: block; white-space: pre-wrap; border: 1px solid rgba(var(--v-theme-on-surface), 0.12); padding: 10px;">{{
                    base_url }}?share_code={{ share_code }}&receive_code={{ receive_code
                    }}&id={{ file_id }}{% if file_name %}&file_name={{ file_name | urlencode }}{% endif
                    %}</code>
                      </div>
                    </div>
                  </div>
                </v-card-text>
              </v-card>
            </div>
          </v-expand-transition>

          <!-- STRM 文件名自定义模板 -->
          <v-divider class="my-6"></v-divider>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-switch v-model="config.strm_filename_template_enabled" label="启用 STRM 文件名自定义模板 (Jinja2)"
                color="primary" density="compact" hint="启用后可以使用 Jinja2 模板语法自定义 STRM 文件的文件名格式"
                persistent-hint></v-switch>
            </v-col>
          </v-row>

          <v-expand-transition>
            <div v-if="config.strm_filename_template_enabled">
              <v-row class="mt-2">
                <v-col cols="12">
                  <v-textarea v-model="config.strm_filename_template" label="STRM 文件名基础模板 (Jinja2)"
                    hint="支持 Jinja2 语法，可用变量和过滤器见下方说明" persistent-hint rows="3" variant="outlined" density="compact"
                    placeholder="{{ file_stem }}.strm" clearable></v-textarea>
                </v-col>
              </v-row>

              <v-row class="mt-2">
                <v-col cols="12">
                  <v-textarea v-model="config.strm_filename_template_custom" label="STRM 文件名扩展名特定模板 (Jinja2)"
                    hint="为特定文件扩展名指定文件名模板，优先级高于基础模板。格式：ext1,ext2 => template（每行一个）" persistent-hint rows="4"
                    variant="outlined" density="compact"
                    placeholder="例如：&#10;iso => {{ file_stem }}.iso.strm&#10;mkv,mp4 => {{ file_stem | upper }}.strm"
                    clearable></v-textarea>
                </v-col>
              </v-row>

              <v-card variant="outlined" class="mt-3" color="info" v-pre>
                <v-card-text class="pa-3">
                  <div class="mb-3">
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-information" size="small" class="mr-2" color="info"></v-icon>
                      <strong class="text-body-2">可用变量</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-1"><code class="text-caption">file_name</code> - 完整文件名（包含扩展名）</div>
                      <div class="mb-1"><code class="text-caption">file_stem</code> - 文件名（不含扩展名）</div>
                      <div class="mb-1"><code class="text-caption">file_suffix</code> - 文件扩展名（包含点号，如 .mkv）
                      </div>
                    </div>
                  </div>

                  <v-divider class="my-3"></v-divider>

                  <div class="mb-3">
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-filter" size="small" class="mr-2" color="info"></v-icon>
                      <strong class="text-body-2">可用过滤器</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-1"><code class="text-caption">upper</code> - 转大写（如：<code class="text-caption">{{
                    file_stem | upper }}</code>）</div>
                      <div class="mb-1"><code class="text-caption">lower</code> - 转小写（如：<code class="text-caption">{{
                    file_stem | lower }}</code>）</div>
                      <div class="mb-1"><code class="text-caption">sanitize</code> - 清理文件名中的非法字符（如：<code
                          class="text-caption">{{ file_name | sanitize }}</code>）</div>
                      <div class="mb-1"><code class="text-caption">default</code> - 默认值（如：<code class="text-caption">{{
                    file_stem | default('unknown') }}</code>）</div>
                    </div>
                  </div>

                  <v-divider class="my-3"></v-divider>

                  <div class="mb-3">
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-code-tags" size="small" class="mr-2" color="info"></v-icon>
                      <strong class="text-body-2">模板示例</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-2">
                        <div class="text-caption text-medium-emphasis mb-1">默认格式:</div>
                        <code class="text-caption pa-2 d-block"
                          style="background-color: rgba(var(--v-theme-on-surface), 0.05); border-radius: 8px; font-family: 'Courier New', monospace; display: block; border: 1px solid rgba(var(--v-theme-on-surface), 0.12); padding: 10px;">{{
                    file_stem }}.strm</code>
                      </div>
                      <div class="mb-2">
                        <div class="text-caption text-medium-emphasis mb-1">ISO 格式:</div>
                        <code class="text-caption pa-2 d-block"
                          style="background-color: rgba(var(--v-theme-on-surface), 0.05); border-radius: 8px; font-family: 'Courier New', monospace; display: block; border: 1px solid rgba(var(--v-theme-on-surface), 0.12); padding: 10px;">{{
                    file_stem }}.iso.strm</code>
                      </div>
                      <div>
                        <div class="text-caption text-medium-emphasis mb-1">大写文件名:</div>
                        <code class="text-caption pa-2 d-block"
                          style="background-color: rgba(var(--v-theme-on-surface), 0.05); border-radius: 8px; font-family: 'Courier New', monospace; display: block; border: 1px solid rgba(var(--v-theme-on-surface), 0.12); padding: 10px;">{{
                    file_stem | upper }}.strm</code>
                      </div>
                    </div>
                  </div>

                  <v-divider class="my-3"></v-divider>

                  <div>
                    <div class="d-flex align-center mb-2">
                      <v-icon icon="mdi-alert-circle-outline" size="small" class="mr-2" color="warning"></v-icon>
                      <strong class="text-body-2">注意事项</strong>
                    </div>
                    <div class="ml-6">
                      <div class="mb-1 text-caption">• 模板渲染后的文件名会自动清理非法字符（&lt;&gt;:&quot;/\\|?*）</div>
                      <div class="mb-1 text-caption">• 建议模板以 .strm 结尾，确保生成的文件具有正确的扩展名</div>
                      <div class="text-caption">• 如果模板未指定扩展名，系统会自动添加 .strm</div>
                    </div>
                  </div>
                </v-card-text>
              </v-card>
            </div>
          </v-expand-transition>

          <v-divider class="my-6"></v-divider>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-combobox v-model="config.strm_generate_blacklist" label="STRM文件关键词过滤黑名单"
                hint="输入关键词后按回车确认，可添加多个。包含这些词的视频文件将不会生成STRM文件。" persistent-hint multiple chips closable-chips
                variant="outlined" density="compact"></v-combobox>
            </v-col>
          </v-row>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-combobox v-model="config.mediainfo_download_whitelist" label="媒体信息文件下载关键词过滤白名单"
                hint="输入关键词后按回车确认，可添加多个。不包含这些词的媒体信息文件将不会下载。" persistent-hint multiple chips closable-chips
                variant="outlined" density="compact"></v-combobox>
            </v-col>
          </v-row>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-combobox v-model="config.mediainfo_download_blacklist" label="媒体信息文件下载关键词过滤黑名单"
                hint="输入关键词后按回车确认，可添加多个。包含这些词的媒体信息文件将不会下载。" persistent-hint multiple chips closable-chips
                variant="outlined" density="compact"></v-combobox>
            </v-col>
          </v-row>

          <v-divider class="my-6"></v-divider>

          <v-row class="mt-4">
            <v-col cols="12" md="4">
              <v-switch v-model="config.strm_url_encode" label="STRM URL 文件名称编码" color="info" density="compact"
                :hint="config.strm_url_template_enabled ? '已启用自定义模板时优先使用模板，模板渲染失败时将使用此设置作为后备方案。在模板中可使用 urlencode 过滤器进行编码。' : '启用后，STRM文件中的URL会对文件名进行编码处理'"
                persistent-hint></v-switch>
            </v-col>
          </v-row>

          <v-divider class="my-6"></v-divider>

          <!-- 请求超时控制 -->
          <v-row>
            <v-col cols="12">
              <v-switch v-model="config.timeout_enabled" label="启用请求超时控制" color="primary" density="compact"
                hint="启用后将为所有 115 网盘 API 请求添加超时控制，防止网络卡死" persistent-hint></v-switch>
            </v-col>
          </v-row>

          <v-expand-transition>
            <div v-if="config.timeout_enabled">
              <v-alert type="info" variant="tonal" density="compact" class="mt-2 mb-3" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>超时类型说明：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">• <strong>连接超时</strong>：建立 TCP 连接的最大等待时间</div>
                  <div class="mb-1">• <strong>连接池超时</strong>：从连接池获取连接的最大等待时间</div>
                  <div class="mb-1">• <strong>读取超时</strong>：等待服务器响应数据的最大时间</div>
                  <div>• <strong>写入超时</strong>：发送请求数据的最大时间</div>
                </div>
              </v-alert>

              <v-card variant="outlined" class="mt-3 mb-4">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-2 bg-grey-lighten-4">
                  <v-icon icon="mdi-lightning-bolt" class="mr-2" color="primary" size="small" />
                  <span>普通操作超时</span>
                </v-card-title>
                <v-card-text class="pa-3">
                  <v-row>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_default_connect" label="连接超时(秒)" type="number"
                        hint="默认30秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_default_pool" label="连接池超时(秒)" type="number"
                        hint="默认15秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_default_read" label="读取超时(秒)" type="number"
                        hint="默认60秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_default_write" label="写入超时(秒)" type="number"
                        hint="默认60秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                  </v-row>
                  <v-alert type="info" variant="tonal" density="compact" class="mt-2" icon="mdi-information">
                    <div class="text-caption">适用于列表、详情、重命名、删除等快速操作。0 表示不限制。</div>
                  </v-alert>
                </v-card-text>
              </v-card>

              <v-card variant="outlined" class="mb-4">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-2 bg-grey-lighten-4">
                  <v-icon icon="mdi-turtle" class="mr-2" color="warning" size="small" />
                  <span>慢操作超时</span>
                </v-card-title>
                <v-card-text class="pa-3">
                  <v-row>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_slow_connect" label="连接超时(秒)" type="number"
                        hint="默认30秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_slow_pool" label="连接池超时(秒)" type="number"
                        hint="默认15秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_slow_read" label="读取超时(秒)" type="number"
                        hint="默认300秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                    <v-col cols="6" md="3">
                      <v-text-field v-model.number="config.timeout_slow_write" label="写入超时(秒)" type="number"
                        hint="默认300秒" persistent-hint density="compact" variant="outlined" hide-details="auto"
                        min="0" step="1"></v-text-field>
                    </v-col>
                  </v-row>
                  <v-alert type="warning" variant="tonal" density="compact" class="mt-2" icon="mdi-alert">
                    <div class="text-caption">
                      适用于下载链接获取、上传初始化、分享列表获取、生活事件拉取等慢操作。0 表示不限制。
                    </div>
                  </v-alert>
                </v-card-text>
              </v-card>
            </div>
          </v-expand-transition>
        </v-card-text>
      </v-window-item>
    </v-window>
  </v-card-text>
</template>

<script setup>
import { ref, inject } from 'vue';

const systemSubTab = ref('tab-cache-config');

/** 与后端 sidebar_nav.SIDEBAR_NAV_ITEMS 的 nav_key 一致，新增页面时在此补充 */
const sidebarNavKeyItems = [
  { title: '115助手仪表盘', value: 'start' },
];

const config = inject('config');
const isTransferModuleEnhancementLocked = inject('isTransferModuleEnhancementLocked');
const clearIdPathCacheLoading = inject('clearIdPathCacheLoading');
const clearIncrementSkipCacheLoading = inject('clearIncrementSkipCacheLoading');
const clearR302CacheLoading = inject('clearR302CacheLoading');
const skipUploadWaitSizeFormattedRef = inject('skipUploadWaitSizeFormattedRef');
const forceUploadWaitSizeFormattedRef = inject('forceUploadWaitSizeFormattedRef');
const skipSlowUploadSizeFormattedRef = inject('skipSlowUploadSizeFormattedRef');
const machineId = inject('machineId');
const clearIdPathCache = inject('clearIdPathCache');
const clearIncrementSkipCache = inject('clearIncrementSkipCache');
const clearR302Cache = inject('clearR302Cache');
const getMachineId = inject('getMachineId');
</script>
