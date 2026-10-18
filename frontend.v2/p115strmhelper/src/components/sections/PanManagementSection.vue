<template>
  <v-card-text class="pa-0">
    <v-tabs v-model="panSubTab" color="primary" class="sub-category-tabs" slider-color="primary">
      <v-tab value="tab-pan-transfer" class="sub-tab">
        <v-icon size="small" start>mdi-transfer</v-icon>网盘整理
      </v-tab>
      <v-tab value="tab-pan-mount" class="sub-tab">
        <v-icon size="small" start>mdi-folder-network</v-icon>网盘挂载
      </v-tab>
      <v-tab value="tab-directory-upload" class="sub-tab">
        <v-icon size="small" start>mdi-upload</v-icon>目录上传
      </v-tab>
    </v-tabs>
    <v-divider></v-divider>
    <v-window v-model="panSubTab" :touch="false" class="tab-window">
      <v-window-item value="tab-pan-transfer">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.pan_transfer_enabled" label="启用" color="info"></v-switch>
            </v-col>
          </v-row>

          <v-row v-if="config.pan_transfer_clouddrive2_config">
            <v-col cols="12" class="d-flex align-center flex-wrap gap-4">
              <v-switch v-model="config.pan_transfer_clouddrive2_config.enabled"
                label="交由 CloudDrive2 储存整理" color="info" hide-details></v-switch>
              <v-text-field v-if="config.pan_transfer_clouddrive2_config.enabled"
                v-model="config.pan_transfer_clouddrive2_config.prefix" label="挂载前缀"
                placeholder="必填，如 /115open" density="compact" hide-details class="flex-grow-1"
                style="max-width: 280px;"></v-text-field>
            </v-col>
          </v-row>

          <!-- 待整理和未识别目录 -->
          <v-card variant="outlined" class="mt-4">
            <v-card-title class="text-subtitle-1">
              <v-icon start>mdi-folder-move</v-icon>
              待整理和未识别目录
            </v-card-title>
            <v-card-text>
              <v-row>
                <v-col cols="12">
                  <div class="d-flex flex-column">
                    <div v-for="(path, index) in panTransferPaths" :key="`pan-${index}`"
                      class="mb-2 d-flex align-center">
                      <v-text-field v-model="path.path" label="网盘待整理目录" density="compact"
                        append-icon="mdi-folder-network"
                        @click:append="openDirSelector(index, 'remote', 'panTransfer')"
                        class="flex-grow-1"></v-text-field>
                      <v-btn icon size="small" color="primary" class="ml-2" @click="manualTransfer(index)"
                        :disabled="!path.path" title="手动整理此目录">
                        <v-icon>mdi-play</v-icon>
                      </v-btn>
                      <v-btn icon size="small" color="error" class="ml-2"
                        @click="removePanTransferPath(index)">
                        <v-icon>mdi-delete</v-icon>
                      </v-btn>
                    </div>
                    <v-btn size="small" prepend-icon="mdi-plus" variant="outlined"
                      class="mt-2 align-self-start" @click="addPanTransferPath">
                      添加路径
                    </v-btn>
                  </div>
                </v-col>
              </v-row>

              <v-row class="mt-4">
                <v-col cols="12">
                  <v-text-field v-model="config.pan_transfer_unrecognized_path" label="网盘整理未识别目录"
                    density="compact" append-icon="mdi-folder-network"
                    @click:append="openDirSelector('unrecognized', 'remote', 'panTransferUnrecognized')"></v-text-field>
                  <v-alert type="info" variant="tonal" density="compact" class="mt-3"
                    icon="mdi-information">
                    <div class="text-caption">提示：此目录用于存放整理过程中未能识别的媒体文件。</div>
                  </v-alert>
                  <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
                    <div class="text-caption">注意：未识别目录不能设置在任何媒体库目录或待整理目录的内部。</div>
                  </v-alert>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- 分享转存目录 -->
          <v-card variant="outlined" class="mt-4">
            <v-card-title class="text-subtitle-1">
              <v-icon start>mdi-share-variant</v-icon>
              分享转存目录
            </v-card-title>
            <v-card-text>
              <v-row>
                <v-col cols="12">
                  <div class="d-flex flex-column">
                    <div v-for="(path, index) in shareReceivePaths" :key="`share-${index}`"
                      class="mb-2 d-flex align-center">
                      <v-text-field v-model="path.path" label="分享转存目录" density="compact"
                        append-icon="mdi-folder-network"
                        @click:append="openDirSelector(index, 'remote', 'shareReceive')"
                        class="flex-grow-1"></v-text-field>
                      <v-btn icon size="small" color="error" class="ml-2"
                        @click="removeShareReceivePath(index)">
                        <v-icon>mdi-delete</v-icon>
                      </v-btn>
                    </div>
                    <v-btn size="small" prepend-icon="mdi-plus" variant="outlined"
                      class="mt-2 align-self-start" @click="addShareReceivePath">
                      添加路径
                    </v-btn>
                  </div>
                </v-col>
              </v-row>
              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-caption">提示：此目录用于存放通过分享链接转存的资源。</div>
              </v-alert>
            </v-card-text>
          </v-card>

          <!-- 离线下载目录 -->
          <v-card variant="outlined" class="mt-4">
            <v-card-title class="text-subtitle-1">
              <v-icon start>mdi-download</v-icon>
              离线下载目录
            </v-card-title>
            <v-card-text>
              <v-row>
                <v-col cols="12">
                  <div class="d-flex flex-column">
                    <div v-for="(path, index) in offlineDownloadPaths" :key="`offline-${index}`"
                      class="mb-2 d-flex align-center">
                      <v-text-field v-model="path.path" label="离线下载目录" density="compact"
                        append-icon="mdi-folder-network"
                        @click:append="openDirSelector(index, 'remote', 'offlineDownload')"
                        class="flex-grow-1"></v-text-field>
                      <v-btn icon size="small" color="error" class="ml-2"
                        @click="removeOfflineDownloadPath(index)">
                        <v-icon>mdi-delete</v-icon>
                      </v-btn>
                    </div>
                    <v-btn size="small" prepend-icon="mdi-plus" variant="outlined"
                      class="mt-2 align-self-start" @click="addOfflineDownloadPath">
                      添加路径
                    </v-btn>
                  </div>
                </v-col>
              </v-row>
              <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
                <div class="text-caption">提示：此目录用于存放通过离线下载功能下载的资源。</div>
              </v-alert>
            </v-card-text>
          </v-card>

          <v-divider class="my-4"></v-divider>

          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>配置说明：</strong></div>
            <div class="text-caption">
              <div class="mb-1">使用本功能需要先进入 设定-目录 进行配置：</div>
              <div class="mb-1">1. 添加目录配置卡，按需配置媒体类型和媒体类别，资源存储选择115网盘，资源目录输入网盘待整理文件夹</div>
              <div class="mb-1">2. 自动整理模式选择手动整理，媒体库存储依旧选择115网盘，并配置好媒体库路径，整理方式选择移动，按需配置分类、重命名、通知</div>
              <div>3. 配置完成目录设置后只需要在上方 网盘待整理目录 填入 网盘待整理文件夹 即可</div>
            </div>
          </v-alert>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-caption">注意：配置目录时不能选择刮削元数据，否则可能导致风控！</div>
          </v-alert>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-body-2 mb-1"><strong>注意事项：</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 阿里云盘，115网盘分享链接秒传或转存都依赖于网盘整理</div>
              <div class="mb-1">• TG/Slack资源搜索转存也依赖于网盘整理</div>
              <div>• 当阿里云盘分享秒传未能识别分享媒体信息时，会自动将资源转存到网盘整理未识别目录，后续需要用户手动重命名整理</div>
            </div>
          </v-alert>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-caption">注意：115生活事件监控默认会忽略网盘整理触发的移动事件，所以推荐使用MP整理事件监控生成STRM</div>
          </v-alert>

          <v-row class="mt-4">
            <v-col cols="12">
              <v-btn color="info" variant="outlined" prepend-icon="mdi-bug-check"
                @click="checkLifeEventStatus">
                故障检查
              </v-btn>
              <div class="text-caption text-grey mt-2">
                检查115生活事件进程状态，测试数据拉取功能，并提供详细的调试信息
              </div>
            </v-col>
          </v-row>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-pan-mount">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-switch v-model="config.fuse_enabled" label="启用" color="success" density="compact"
                hint="将115网盘挂载为本地文件系统" persistent-hint></v-switch>
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field v-model="config.fuse_mountpoint" label="挂载点路径" hint="文件系统挂载的本地路径"
                persistent-hint density="compact" variant="outlined" hide-details="auto"
                placeholder="/mnt/115"></v-text-field>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4">
              <v-text-field v-model.number="config.fuse_readdir_ttl" label="目录读取缓存 TTL（秒）" type="number"
                hint="目录列表缓存时间，默认60秒" persistent-hint density="compact" variant="outlined"
                hide-details="auto" min="0"></v-text-field>
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field v-model.number="config.fuse_uid" label="文件所有者 UID" type="number"
                hint="挂载文件的用户ID，留空则使用当前运行用户" persistent-hint density="compact" variant="outlined"
                hide-details="auto" min="0" clearable></v-text-field>
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field v-model.number="config.fuse_gid" label="文件所有者 GID" type="number"
                hint="挂载文件的组ID，留空则使用当前运行用户" persistent-hint density="compact" variant="outlined"
                hide-details="auto" min="0" clearable></v-text-field>
            </v-col>
          </v-row>

          <!-- STRM 文件生成内容接管 -->
          <v-divider class="my-4"></v-divider>
          <v-row>
            <v-col cols="12">
              <v-switch v-model="config.fuse_strm_takeover_enabled" label="接管 STRM 文件生成内容" color="primary"
                density="compact" hint="启用后，匹配规则的文件将生成指向挂载路径的 STRM 内容" persistent-hint></v-switch>
            </v-col>
          </v-row>
          <v-expand-transition>
            <div v-if="config.fuse_strm_takeover_enabled">
              <v-divider class="my-4"></v-divider>
              <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-information">
                <div class="text-body-2 mb-1"><strong>STRM URL 生成优先级：</strong></div>
                <div class="text-caption">
                  <div class="mb-1">1. <strong>URL 自定义模板</strong>（如果启用）：优先使用 Jinja2 模板渲染</div>
                  <div class="mb-1">2. <strong>FUSE STRM 接管</strong>（如果启用且匹配规则）：生成指向挂载路径的 STRM 内容</div>
                  <div>3. <strong>默认格式</strong>：使用基础设置中的「STRM文件URL格式」和「STRM URL 文件名称编码」</div>
                </div>
              </v-alert>
              <v-divider class="mb-4"></v-divider>
              <v-row>
                <v-col cols="12" md="6">
                  <v-text-field v-model="config.fuse_strm_mount_dir" label="媒体服务器网盘挂载目录"
                    hint="媒体服务器中配置的 115 网盘挂载路径" persistent-hint density="compact" variant="outlined"
                    hide-details="auto" placeholder="/media/115"></v-text-field>
                </v-col>
              </v-row>
              <v-row>
                <v-col cols="12">
                  <v-btn color="primary" variant="outlined" prepend-icon="mdi-code-tags" size="small"
                    @click="openConfigGeneratorDialog">
                    生成 Emby 反代 302 配置
                  </v-btn>
                </v-col>
              </v-row>
              <v-row>
                <v-col cols="12">
                  <div class="text-body-2 mb-2"><strong>接管规则：</strong></div>
                  <div class="d-flex flex-column">
                    <v-card v-for="(rule, index) in fuseStrmTakeoverRules"
                      :key="`fuse-strm-takeover-${index}`" variant="outlined" class="mb-3">
                      <v-card-text>
                        <div class="d-flex align-center mb-2">
                          <span class="text-caption text-medium-emphasis">规则 #{{ index + 1 }}</span>
                          <v-spacer></v-spacer>
                          <v-btn icon size="small" color="error"
                            @click="removePath(index, 'fuseStrmTakeover')">
                            <v-icon>mdi-delete</v-icon>
                          </v-btn>
                        </div>

                        <!-- 匹配方式选择 -->
                        <div class="mb-3">
                          <div class="text-caption text-medium-emphasis mb-2">选择匹配方式（可多选）：</div>
                          <div class="d-flex flex-wrap gap-3">
                            <v-switch v-model="rule._use_extensions" label="文件后缀" density="compact"
                              color="primary" hide-details class="ma-0"></v-switch>
                            <v-switch v-model="rule._use_names" label="文件名称" density="compact"
                              color="primary" hide-details class="ma-0"></v-switch>
                            <v-switch v-model="rule._use_paths" label="网盘路径" density="compact"
                              color="primary" hide-details class="ma-0"></v-switch>
                          </div>
                        </div>

                        <!-- 文件后缀 -->
                        <v-expand-transition>
                          <div v-if="rule._use_extensions">
                            <v-textarea v-model="rule.extensions" label="文件后缀（每行一个，例如：mkv、mp4）"
                              hint="匹配的文件后缀，不包含点号，每行一个" persistent-hint density="compact"
                              variant="outlined" rows="2" class="mb-2"
                              placeholder="mkv&#10;mp4&#10;avi"></v-textarea>
                          </div>
                        </v-expand-transition>

                        <!-- 文件名称白名单 -->
                        <v-expand-transition>
                          <div v-if="rule._use_names">
                            <v-textarea v-model="rule.names" label="文件名称白名单（每行一个，支持部分匹配）"
                              hint="文件名包含这些关键词时匹配，每行一个" persistent-hint density="compact"
                              variant="outlined" rows="2" class="mb-2"
                              placeholder="蓝光&#10;BluRay"></v-textarea>
                          </div>
                        </v-expand-transition>

                        <!-- 网盘文件夹路径 -->
                        <v-expand-transition>
                          <div v-if="rule._use_paths">
                            <v-textarea v-model="rule.paths" label="网盘文件夹路径（每行一个，支持部分匹配）"
                              hint="文件路径包含这些路径时匹配，每行一个" persistent-hint density="compact"
                              variant="outlined" rows="2" placeholder="/电影/4K&#10;/电视剧"></v-textarea>
                          </div>
                        </v-expand-transition>
                      </v-card-text>
                    </v-card>
                    <v-btn size="small" prepend-icon="mdi-plus" variant="outlined"
                      class="align-self-start" @click="addPath('fuseStrmTakeover')">
                      添加接管规则
                    </v-btn>
                  </div>
                  <v-alert type="info" variant="tonal" density="compact" class="mt-3"
                    icon="mdi-information">
                    <div class="text-caption">
                      <div class="mb-1">• 三种匹配方式可以组合使用，<strong>同时满足</strong>（与关系）才会匹配</div>
                      <div class="mb-1">• 如果某个匹配条件为空，则<strong>不检查</strong>该条件</div>
                      <div class="mb-1">• <strong>匹配成功后生成的 STRM 内容：</strong></div>
                      <div class="mb-1">
                        格式：<code>{{ config.fuse_strm_mount_dir || '媒体服务器挂载目录' }}/文件网盘路径</code></div>
                      <div> 示例：如果挂载目录为 <code>/media/115</code>，文件网盘路径为 <code>/电影/示例.mkv</code>，则生成的 STRM
                        内容为
                        <code>/media/115/电影/示例.mkv</code>
                      </div>
                    </div>
                  </v-alert>
                </v-col>
              </v-row>
            </div>
          </v-expand-transition>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-body-2 mb-1"><strong>平台限制说明：</strong></div>
            <div class="text-caption">
              <div class="mb-1">• <strong>Windows 系统不支持：</strong>FUSE 功能基于 Linux 文件系统，无法在 Windows 环境下运行
              </div>
              <div class="mb-1">• <strong>Linux 裸机：</strong>理论上支持，需要安装 libfuse（libfuse2 或 libfuse3）</div>
              <div class="mb-1">• <strong>macOS 裸机：</strong>理论上支持，需要安装 macFUSE</div>
              <div>• <strong>推荐使用 Docker 容器：</strong>目前仅对 Docker 容器环境有较好的支持和测试，建议在 Docker 容器中使用此功能</div>
            </div>
          </v-alert>
          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
            <div class="text-caption mb-2">启用后，115网盘将挂载为容器内的文件系统，可通过文件管理器直接访问。配合上方的"STRM
              文件生成内容接管"功能，可以让生成的 STRM
              文件直接指向挂载路径，实现本地文件系统访问。</div>
            <div class="text-body-2 mt-2 mb-1"><strong>配置说明：</strong></div>
            <div class="text-caption">
              <div class="mb-1">• <strong>挂载点路径：</strong>容器内的挂载路径，必须是已存在的目录（例如：<code>/media/115</code> 或
                <code>/data/115</code>）
              </div>
              <div class="mb-1">• <strong>目录读取缓存 TTL：</strong>目录列表缓存时间，默认60秒</div>
              <div class="mb-1">• <strong>文件所有者 UID/GID：</strong>设置挂载文件的用户和组ID，留空则自动使用当前运行用户（Docker
                容器中建议设置为非
                root 用户）
              </div>
              <div class="mb-1">• <strong>容器权限：</strong>需要容器以 <code>--privileged</code> 或
                <code>--cap-add SYS_ADMIN</code>
                权限运行
              </div>
              <div>• <strong>STRM 接管：</strong>启用上方的"接管 STRM 文件生成内容"后，匹配规则的文件将生成指向挂载路径的 STRM
                内容，媒体服务器可直接通过挂载路径访问文件</div>
            </div>
          </v-alert>
          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-body-2 mb-1"><strong>重要提示：</strong></div>
            <div class="text-caption">
              <div class="mb-1">• <strong>切勿直接使用媒体服务器刮削挂载路径</strong>，这会导致网盘风控</div>
              <div>• <strong>正确方法：</strong>使用本插件的 STRM 文件生成功能，在本地生成 STRM 文件后，再让媒体服务器对 STRM 文件进行刮削</div>
            </div>
          </v-alert>
          <v-alert type="info" variant="tonal" density="compact" class="mt-3"
            icon="mdi-book-open-page-variant">
            <div class="text-body-2 mb-1"><strong>配置教程：</strong></div>
            <div class="text-caption">
              详细的 FUSE 挂载配置指南请参考：
              <a href="https://blog.ddsrem.com/archives/115strmhelper-fuse-use" target="_blank"
                rel="noopener noreferrer" style="color: inherit; text-decoration: underline;">FUSE
                挂载详细配置指南</a>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-directory-upload">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.directory_upload_enabled" label="启用" color="info"
                density="compact" hide-details></v-switch>
            </v-col>
            <v-col cols="12" md="8">
              <v-select v-model="config.directory_upload_mode" label="监控模式" :items="[
                { title: '兼容模式', value: 'compatibility' },
                { title: '性能模式', value: 'fast' }
              ]" chips closable-chips density="compact" hide-details></v-select>
            </v-col>
          </v-row>
          <v-row v-if="config.directory_upload_clouddrive2_config">
            <v-col cols="12" md="4">
              <v-switch v-model="config.directory_upload_clouddrive2_config.enabled"
                label="交由 CloudDrive2 上传" color="info" density="compact"
                hide-details></v-switch>
            </v-col>
            <v-col v-if="config.directory_upload_clouddrive2_config.enabled" cols="12" md="8">
              <v-text-field v-model="config.directory_upload_clouddrive2_config.prefix"
                label="挂载前缀" placeholder="必填，如 /115open" density="compact"
                variant="outlined" hide-details></v-text-field>
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4">
              <v-text-field v-model="config.directory_upload_uploadext" label="上传文件扩展名"
                hint="指定哪些扩展名的文件会被上传到115网盘，多个用逗号分隔；留空或填 * 表示不限制后缀" persistent-hint density="compact" variant="outlined"
                hide-details="auto"></v-text-field>
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field v-model="config.directory_upload_copyext" label="复制文件扩展名"
                hint="指定哪些扩展名的文件会被复制到本地目标目录，多个用逗号分隔" persistent-hint density="compact" variant="outlined"
                hide-details="auto"></v-text-field>
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.directory_upload_skip_bdmv_stream" label="跳过蓝光原盘 STREAM 目录"
                hint="关闭后将允许上传 BDMV/STREAM 下的 m2ts 等文件" persistent-hint color="info" density="compact"
                hide-details="auto"></v-switch>
            </v-col>
          </v-row>

          <v-divider class="my-3"></v-divider>
          <div class="text-subtitle-2 mb-2">路径配置:</div>

          <div v-for="(pair, index) in directoryUploadPaths" :key="`upload-${index}`"
            class="path-group mb-3 pa-2 border rounded">
            <v-row dense>
              <!-- 本地监控目录 -->
              <v-col cols="12" md="6">
                <v-text-field v-model="pair.src" label="本地监控目录" density="compact" variant="outlined"
                  hide-details append-icon="mdi-folder-search-outline"
                  @click:append="openDirSelector(index, 'local', 'directoryUpload', 'src')">
                  <template v-slot:prepend-inner>
                    <v-icon color="blue">mdi-folder-table</v-icon>
                  </template>
                </v-text-field>
              </v-col>
              <!-- 网盘上传目录 -->
              <v-col cols="12" md="6">
                <v-text-field v-model="pair.dest_remote" label="网盘上传目标目录" density="compact"
                  variant="outlined" hide-details append-icon="mdi-folder-network-outline"
                  @click:append="openDirSelector(index, 'remote', 'directoryUpload', 'dest_remote')">
                  <template v-slot:prepend-inner>
                    <v-icon color="green">mdi-cloud-upload</v-icon>
                  </template>
                </v-text-field>
              </v-col>
            </v-row>
            <v-row dense class="mt-1">
              <!-- 非上传文件目标目录 -->
              <v-col cols="12" md="6">
                <v-text-field v-model="pair.dest_local" label="本地复制目标目录 (可选)" density="compact"
                  variant="outlined" hide-details append-icon="mdi-folder-plus-outline"
                  @click:append="openDirSelector(index, 'local', 'directoryUpload', 'dest_local')">
                  <template v-slot:prepend-inner>
                    <v-icon color="orange">mdi-content-copy</v-icon>
                  </template>
                </v-text-field>
              </v-col>
              <!-- STRM 输出目录 -->
              <v-col cols="12" md="6">
                <v-text-field v-model="pair.dest_strm" label="STRM 输出目录 (可选)" density="compact"
                  variant="outlined" append-icon="mdi-file-document-outline" hide-details="auto"
                  @click:append="openDirSelector(index, 'local', 'directoryUpload', 'dest_strm')">
                  <template v-slot:prepend-inner>
                    <v-icon color="purple">mdi-file-star</v-icon>
                  </template>
                </v-text-field>
              </v-col>
            </v-row>
            <v-row dense class="mt-1">
              <!-- 删除源文件开关 -->
              <v-col cols="12" md="10" class="d-flex align-center">
                <v-switch v-model="pair.delete" label="处理后删除源文件" color="error" density="compact"
                  hide-details></v-switch>
              </v-col>
              <!-- 删除按钮 -->
              <v-col cols="12" md="2" class="d-flex align-center justify-end">
                <v-btn icon="mdi-delete-outline" size="small" color="error" variant="text" title="删除此路径配置"
                  @click="removePath(index, 'directoryUpload')">
                </v-btn>
              </v-col>
            </v-row>
          </div>

          <v-btn size="small" prepend-icon="mdi-plus-box-multiple-outline" variant="tonal" class="mt-2"
            color="primary" @click="addPath('directoryUpload')">
            添加监控路径组
          </v-btn>

          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>功能说明：</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 监控指定的"本地监控目录"</div>
              <div class="mb-1">• 当目录中出现新文件时：</div>
              <div class="ml-4 mb-1">- 如果文件扩展名匹配"上传文件扩展名"，则将其上传到对应的"网盘上传目标目录"；若配置了"STRM
                输出目录"，上传成功后会立即在该目录生成对应
                .strm 文件
              </div>
              <div class="ml-4 mb-1">- 如果文件扩展名匹配"复制文件扩展名"，则将其复制到对应的"本地复制目标目录"</div>
              <div class="mb-1">• 处理完成后，如果"删除源文件"开关打开，则会删除原始文件</div>
              <div class="mb-1">• 扩展名不匹配的文件将被忽略</div>
              <div class="mb-1">• "STRM 输出目录"：上传成功后立即在此目录生成对应 .strm 文件，目录结构同监控目录相对路径</div>
            </div>
            <strong>注意:</strong><br>
            - 请确保MoviePilot对本地目录有读写权限，对网盘目录有写入权限。<br>
            - "本地复制目标目录"和"STRM 输出目录"是可选的，如果不填，则仅执行上传操作（如果匹配）。<br>
            - 监控模式："性能模式"使用系统原生文件系统事件，适用于物理路径，性能高且更稳定；"兼容模式"使用轮询方式，适用于网络共享目录（如SMB/NFS），性能较低但兼容性好。
          </v-alert>
        </v-card-text>
      </v-window-item>
    </v-window>
  </v-card-text>
</template>

<script setup>
import { ref, inject } from 'vue';

const panSubTab = ref('tab-pan-transfer');

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
</script>
