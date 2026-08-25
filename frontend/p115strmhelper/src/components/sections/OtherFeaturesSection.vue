<template>
  <v-card-text class="pa-0">
    <v-tabs v-model="otherSubTab" color="primary" class="sub-category-tabs" slider-color="primary">
      <v-tab value="tab-sync-del" class="sub-tab">
        <v-icon size="small" start>mdi-delete-sweep</v-icon>同步删除
      </v-tab>
      <v-tab value="tab-tg-search" class="sub-tab">
        <v-icon size="small" start>mdi-tab-search</v-icon>频道搜索
      </v-tab>
      <v-tab value="tab-cleanup" class="sub-tab">
        <v-icon size="small" start>mdi-broom</v-icon>定期清理
      </v-tab>
      <v-tab value="tab-same-playback" class="sub-tab">
        <v-icon size="small" start>mdi:code-block-parentheses</v-icon>多端播放
      </v-tab>
      <v-tab value="tab-hdhive-checkin" class="sub-tab">
        <v-icon size="small" start>mdi-calendar-check</v-icon>HDHive 签到
      </v-tab>
      <v-tab value="tab-p115-checkin" class="sub-tab">
        <v-icon size="small" start>mdi-check-circle-outline</v-icon>115 签到
      </v-tab>
      <v-tab value="tab-utility" class="sub-tab">
        <v-icon size="small" start>mdi-toolbox</v-icon>实用工具
      </v-tab>
      <v-tab value="tab-strm-backup" class="sub-tab">
        <v-icon size="small" start>mdi-backup-restore</v-icon>本地 STRM 备份
      </v-tab>
    </v-tabs>
    <v-divider></v-divider>
    <v-window v-model="otherSubTab" :touch="false" class="tab-window">
      <v-window-item value="tab-sync-del">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.sync_del_enabled" label="启用同步删除" color="warning" density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.sync_del_notify" label="发送通知" color="success" density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.sync_del_source" label="删除源文件" color="error" density="compact"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.sync_del_p115_force_delete_files" label="强制删除文件" color="warning"
                density="compact"></v-switch>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12" md="6">
              <v-switch v-model="config.sync_del_remove_versions" label="开启多版本删除" color="info" density="compact" chips
                closable-chips hint="请查看下方警告提示了解详细说明" persistent-hint></v-switch>
            </v-col>
            <v-col cols="12" md="6">
              <v-select v-model="config.sync_del_mediaservers" label="媒体服务器" :items="embyMediaservers" multiple
                density="compact" chips closable-chips hint="用于获取TMDB ID，仅支持Emby" persistent-hint></v-select>
            </v-col>
          </v-row>

          <v-row>
            <v-col cols="12">
              <div class="d-flex flex-column">
                <div v-for="(path, index) in syncDelLibraryPaths" :key="`sync-del-${index}`"
                  class="mb-3 pa-3 border rounded">
                  <v-row dense>
                    <v-col cols="12" md="4">
                      <v-text-field v-model="path.mediaserver" label="媒体服务器STRM路径" density="compact" variant="outlined"
                        hint="例如：/media/strm" persistent-hint></v-text-field>
                    </v-col>
                    <v-col cols="12" md="4">
                      <v-text-field v-model="path.moviepilot" label="MoviePilot路径" density="compact" variant="outlined"
                        hint="例如：/mnt/strm" persistent-hint append-icon="mdi-folder-home"
                        @click:append="openDirSelector(index, 'local', 'syncDelLibrary', 'moviepilot')"></v-text-field>
                    </v-col>
                    <v-col cols="12" md="4">
                      <v-text-field v-model="path.p115" label="115网盘媒体库路径" density="compact" variant="outlined"
                        hint="例如：/影视" persistent-hint append-icon="mdi-cloud"
                        @click:append="openDirSelector(index, 'remote', 'syncDelLibrary', 'p115')"></v-text-field>
                    </v-col>
                  </v-row>
                  <v-row dense>
                    <v-col cols="12" class="d-flex justify-end">
                      <v-btn icon size="small" color="error" @click="removePath(index, 'syncDelLibrary')">
                        <v-icon>mdi-delete</v-icon>
                      </v-btn>
                    </v-col>
                  </v-row>
                </div>
                <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2 align-self-start"
                  @click="addPath('syncDelLibrary')">
                  添加路径映射
                </v-btn>
              </div>
            </v-col>
          </v-row>

          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>关于路径映射：</strong></div>
            <div class="text-caption">
              <div class="mb-1">• <strong>媒体服务器STRM路径：</strong>媒体服务器中STRM文件的实际路径</div>
              <div class="mb-1">• <strong>MoviePilot路径：</strong>MoviePilot中对应的路径</div>
              <div>• <strong>115网盘媒体库路径：</strong>115网盘中媒体库的路径</div>
            </div>
          </v-alert>

          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-caption">
              <div class="mb-1">• 不正确配置会导致查询不到转移记录！</div>
              <div class="mb-1">• 需要使用神医助手PRO且版本在v3.0.0.3及以上或神医助手社区版且版本在v2.0.0.27及以上！</div>
              <div class="mb-1">• 同步删除多版本功能需要使用助手Pro v3.0.0.22才支持！</div>
              <div>•
                <strong>开启多版本删除：</strong>开启后会将电影和电视剧季删除通过神医返回的路径改为电影单部/电视剧单集删除，从而防止误删其它版本，如果无多版本电影和电视剧季删除的需求，推荐关闭此按钮，提升删除效率
              </div>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-tg-search">
        <v-card-text>

          <!-- 自定义频道搜索配置 -->
          <v-card variant="outlined">
            <v-card-item>
              <v-card-title class="d-flex align-center">
                <v-icon start>mdi-telegram</v-icon>
                <span class="text-h6">自定义Telegram频道</span>
              </v-card-title>
            </v-card-item>
            <v-card-text>
              <div v-for="(channel, index) in tgChannels" :key="index" class="d-flex align-center mb-4">
                <v-text-field v-model="channel.name" label="频道名称" placeholder="例如：爱影115资源分享频道" density="compact"
                  variant="outlined" hide-details class="mr-3"></v-text-field>
                <v-text-field v-model="channel.id" label="频道ID" placeholder="例如：ayzgzf" density="compact"
                  variant="outlined" hide-details class="mr-3"></v-text-field>
                <v-btn icon size="small" color="error" variant="tonal" @click="removeTgChannel(index)" title="删除此频道">
                  <v-icon>mdi-delete-outline</v-icon>
                </v-btn>
              </div>

              <!-- 操作按钮组 -->
              <div class="d-flex ga-2">
                <v-btn size="small" prepend-icon="mdi-plus-circle-outline" variant="tonal" color="primary"
                  @click="addTgChannel">
                  添加频道
                </v-btn>
                <v-btn size="small" prepend-icon="mdi-import" variant="tonal" @click="openImportDialog">
                  一键导入
                </v-btn>
              </div>
            </v-card-text>
          </v-card>

          <v-card variant="outlined" class="mt-4">
            <v-card-item>
              <v-card-title class="d-flex align-center">
                <v-icon start>mdi-movie-search</v-icon>
                <span class="text-h6">HDHive 搜索</span>
              </v-card-title>
            </v-card-item>
            <v-card-text>
              <v-switch v-model="config.hdhive_search_enabled" label="启用 HDHive 搜索" color="primary" density="compact"
                class="mb-4" />
              <v-row>
                <v-col cols="12" md="6">
                  <v-text-field v-model="config.hdhive_checkin_username" label="HDHive 账户" density="compact"
                    variant="outlined" autocomplete="username" :disabled="!config.hdhive_search_enabled" />
                </v-col>
                <v-col cols="12" md="6">
                  <v-text-field v-model="config.hdhive_checkin_password" label="HDHive 密码" type="password"
                    density="compact" variant="outlined" autocomplete="new-password"
                    :disabled="!config.hdhive_search_enabled" />
                </v-col>
              </v-row>
              <v-alert type="info" variant="tonal" density="compact" icon="mdi-information">
                <div class="text-caption">
                  <div class="mb-1">• 账户密码与「HDHive 签到」页<strong>共用</strong>，任一页面修改会自动同步</div>
                  <div class="mb-1">• 使用浏览器自动化拉取资源；若遇 Cloudflare 验证，请为 MoviePilot 配置代理</div>
                  <div>• 与 TG 结果合并展示；仅 115 网盘资源；确认转存时才解锁</div>
                </div>
              </v-alert>
            </v-card-text>
          </v-card>

          <v-alert type="info" variant="tonal" density="compact" class="mt-6" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>频道搜索说明（/sh）</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 请至少配置 <strong>Telegram 频道</strong> 或<strong>启用 HDHive 搜索并填写账户密码</strong>，否则无法使用
                <code>/sh</code> 检索资源
              </div>
              <div>• HDHive 与 TG 结果会合并展示；HDHive 仅展示 115 网盘类资源，积分需求在列表中可见，确认转存时才解锁</div>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-cleanup">
        <v-card-text>
          <v-alert type="warning" variant="tonal" density="compact" class="mb-4" icon="mdi-alert">
            <div class="text-caption">注意，清空 回收站/最近接收 后文件不可恢复，如果产生重要数据丢失本程序不负责！</div>
          </v-alert>

          <v-row>
            <v-col cols="12" md="3">
              <v-switch v-model="config.clear_recyclebin_enabled" label="清空回收站" color="error"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="config.clear_receive_path_enabled" label="清空最近接收目录" color="error"></v-switch>
            </v-col>
            <v-col cols="12" md="3">
              <v-text-field v-model="config.password" label="115访问密码" hint="115网盘安全密码" persistent-hint type="password"
                density="compact" variant="outlined" hide-details="auto"></v-text-field>
            </v-col>
            <v-col cols="12" md="3">
              <VCronField v-model="config.cron_clear" label="清理周期" hint="设置清理任务的执行周期" persistent-hint density="compact">
              </VCronField>
            </v-col>
          </v-row>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-same-playback">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.same_playback" label="启用" color="info" density="compact"
                hide-details></v-switch>
            </v-col>
          </v-row>

          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>多设备同步播放</strong></div>
            <div class="text-caption">支持多个设备同时播放同一影片</div>
          </v-alert>
          <v-alert type="warning" variant="tonal" density="compact" class="mt-3" icon="mdi-alert">
            <div class="text-body-2 mb-1"><strong>使用限制</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 最多支持双IP同时播放</div>
              <div class="mb-1">• 禁止多IP滥用</div>
              <div>• 违规操作可能导致账号封禁</div>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-hdhive-checkin">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="6">
              <v-text-field v-model="config.hdhive_checkin_username" label="HDHive账户" density="compact"
                variant="outlined" autocomplete="username" />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field v-model="config.hdhive_checkin_password" label="HDHive密码" type="password" density="compact"
                variant="outlined" autocomplete="new-password" />
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.hdhive_checkin_daily_enabled" label="每日签到" color="primary" density="compact" />
            </v-col>
            <v-col cols="12" md="4">
              <v-switch v-model="config.hdhive_checkin_gamble_enabled" label="赌狗签到" color="warning" density="compact" />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field v-model="config.hdhive_checkin_time_range" label="签到随机时间段"
                hint="格式 HH:MM-HH:MM，例如 06:30-09:45" persistent-hint density="compact" variant="outlined" />
            </v-col>
          </v-row>
          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>HDHive 签到</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 请填写 HDHive 账户与密码；与「频道搜索 → HDHive 搜索」<strong>共用</strong>同一配置</div>
              <div class="mb-1">• 每日签到与赌狗签到<strong>只能二选一</strong>开启</div>
              <div class="mb-1">• 启用后将在设定时间窗口内<strong>每天随机一刻</strong>执行一次登录并签到</div>
              <div>• 也可在 Telegram 等渠道发送 <code>/hdhivechin</code> 手动触发签到</div>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-p115-checkin">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.p115_checkin_enabled" label="115 每日签到" color="primary" density="compact" />
            </v-col>
            <v-col cols="12" md="4">
              <v-text-field v-model="config.p115_checkin_time_range" label="签到随机时间段"
                hint="格式 HH:MM-HH:MM，例如 06:30-09:45" persistent-hint density="compact" variant="outlined" />
            </v-col>
          </v-row>
          <v-alert type="info" variant="tonal" density="compact" class="mt-3" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>115 签到</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 无需额外账号，使用已配置的 115 Cookie 自动签到</div>
              <div class="mb-1">• 启用后将在设定时间窗口内<strong>每天随机一刻</strong>执行一次签到</div>
              <div class="mb-1">• 签到功能不支持 web 类型 Cookie，请使用其他客户端类型扫码登录</div>
              <div>• 也可在 Telegram 等渠道发送 <code>/p115_checkin</code> 手动触发签到</div>
            </div>
          </v-alert>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-utility">
        <v-card-text class="px-2">
          <!-- 功能 1: 分享STRM覆盖大小检查 -->
          <v-card variant="outlined" class="mb-4" density="compact">
            <v-card-title class="d-flex align-center py-2 px-4 bg-primary-lighten-5">
              <v-icon size="small" color="primary" class="mr-2">mdi-file-compare</v-icon>
              <span class="text-subtitle-2 font-weight-medium">分享STRM覆盖大小检查</span>
            </v-card-title>
            <v-divider></v-divider>
            <v-card-text class="py-3 px-4">
              <v-row>
                <v-col cols="12">
                  <v-switch v-model="config.share_strm_overwrite_check_enabled" label="启用功能" color="primary"
                    density="compact" hide-details></v-switch>
                </v-col>
                <v-col cols="12">
                  <v-alert type="info" variant="tonal" density="compact" class="text-caption">
                    解决按大小覆盖时 STRM 文件被误判为小文件的问题<br>
                    优先使用生成时的缓存数据，未命中时使用 ffprobe 探测实际大小
                  </v-alert>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- 功能 2: 自动删除低质量源文件 -->
          <v-card variant="outlined" class="mb-4" density="compact">
            <v-card-title class="d-flex align-center py-2 px-4 bg-warning-lighten-5">
              <v-icon size="small" color="warning" class="mr-2">mdi-delete-alert</v-icon>
              <span class="text-subtitle-2 font-weight-medium">自动删除低质量源文件</span>
            </v-card-title>
            <v-divider></v-divider>
            <v-card-text class="py-3 px-4">
              <v-row>
                <v-col cols="12">
                  <v-switch v-model="config.auto_delete_inferior_source_enabled" label="启用功能" color="warning"
                    density="compact" hide-details></v-switch>
                </v-col>
                <v-col cols="12">
                  <v-alert type="warning" variant="tonal" density="compact" class="text-caption">
                    <strong>注意：</strong>按文件大小整理失败时（媒体库已存在更高质量文件），自动删除源文件<br>
                    支持所有存储类型：本地、115网盘、CloudDrive
                  </v-alert>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>

          <!-- 功能 3: 媒体库已存在时拦截整理 -->
          <v-card variant="outlined" class="mb-4" density="compact">
            <v-card-title class="d-flex align-center py-2 px-4 bg-error-lighten-5">
              <v-icon size="small" color="error" class="mr-2">mdi-cancel</v-icon>
              <span class="text-subtitle-2 font-weight-medium">媒体库已存在时拦截整理</span>
            </v-card-title>
            <v-divider></v-divider>
            <v-card-text class="py-3 px-4">
              <v-row>
                <v-col cols="12">
                  <v-switch v-model="config.transfer_intercept_exists_enabled" label="启用功能" color="error"
                    density="compact" hide-details></v-switch>
                </v-col>
                <v-col cols="12">
                  <v-alert type="error" variant="tonal" density="compact" class="text-caption">
                    整理前查询所有媒体服务器，若已存在则立即终止并记录失败<br>
                    <strong>生效条件：</strong>目标路径尚无同名文件时触发（首次入库场景）<br>
                    若目标文件已存在，覆盖检查会优先介入，本功能不会触发<br>
                    <strong>注意：</strong>每次整理均会请求媒体服务器，需确保媒体已完成刮削入库
                  </v-alert>
                </v-col>
              </v-row>
            </v-card-text>
          </v-card>
        </v-card-text>
      </v-window-item>
      <v-window-item value="tab-strm-backup">
        <v-card-text>
          <v-row>
            <v-col cols="12" md="4">
              <v-switch v-model="config.strm_backup_enabled" label="启用 STRM 备份" color="primary" density="compact"
                hide-details></v-switch>
            </v-col>
          </v-row>

          <v-divider class="my-4"></v-divider>

          <div v-for="(item, index) in strmBackupItems" :key="`backup-${index}`" class="mb-4">
            <v-card variant="outlined">
              <v-card-title class="d-flex align-center py-2 px-4 bg-primary-lighten-5">
                <v-icon size="small" color="primary" class="mr-2">mdi-archive</v-icon>
                <span class="text-subtitle-2 font-weight-medium">{{ item.name || `备份任务 ${index + 1}` }}</span>
                <v-spacer></v-spacer>
                <v-btn icon size="small" color="error" variant="tonal" @click="removeBackupItem(index)" title="删除此任务">
                  <v-icon>mdi-delete-outline</v-icon>
                </v-btn>
              </v-card-title>
              <v-divider></v-divider>
              <v-card-text class="py-3 px-4">
                <v-row>
                  <v-col cols="12" md="4">
                    <v-text-field v-model="item.name" label="任务名称" density="compact" variant="outlined"
                      hint="备份任务名称，用于标识" persistent-hint></v-text-field>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-select v-model="item.target_type" label="备份目标" :items="[
                      { title: '本地目录', value: 'local' },
                      { title: '115网盘', value: 'cloud' }
                    ]" density="compact" variant="outlined" hide-details></v-select>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-switch v-model="item.enabled" label="启用" color="success" density="compact"
                      hide-details></v-switch>
                  </v-col>
                </v-row>

                <v-row>
                  <v-col cols="12">
                    <div class="text-caption mb-2 font-weight-medium">源目录列表</div>
                    <div v-for="(sp, spIndex) in item.source_paths" :key="`sp-${index}-${spIndex}`"
                      class="d-flex align-center mb-2">
                      <v-text-field v-model="item.source_paths[spIndex]" label="源目录路径" density="compact"
                        variant="outlined" hide-details class="mr-2" append-icon="mdi-folder-home"
                        @click:append="openDirSelector(index, 'local', 'backupSourcePath', String(spIndex))"></v-text-field>
                      <v-btn icon size="small" color="error" variant="tonal" @click="removeSourcePath(index, spIndex)"
                        title="删除此目录">
                        <v-icon>mdi-delete-outline</v-icon>
                      </v-btn>
                    </div>
                    <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-1"
                      @click="addSourcePath(index)">
                      添加目录
                    </v-btn>
                  </v-col>
                </v-row>

                <v-row v-if="item.target_type === 'local'">
                  <v-col cols="12">
                    <v-text-field v-model="item.local_target_path" label="本地备份目录" density="compact" variant="outlined"
                      hint="备份文件存放的本地目录" persistent-hint append-icon="mdi-folder-home"
                      @click:append="openDirSelector(index, 'local', 'backupItems', 'local_target_path')"></v-text-field>
                  </v-col>
                </v-row>

                <v-row v-if="item.target_type === 'cloud'">
                  <v-col cols="12">
                    <v-text-field v-model="item.cloud_target_path" label="115网盘备份目录" density="compact"
                      variant="outlined" hint="备份文件存放的115网盘目录" persistent-hint append-icon="mdi-cloud"
                      @click:append="openDirSelector(index, 'remote', 'backupItems', 'cloud_target_path')"></v-text-field>
                  </v-col>
                </v-row>

                <v-row>
                  <v-col cols="12" md="4">
                    <v-switch v-model="item.timing_enabled" label="定时备份" color="info" density="compact"
                      hide-details></v-switch>
                  </v-col>
                  <v-col cols="12" md="4" v-if="item.timing_enabled">
                    <VCronField v-model="item.cron" label="备份周期" density="compact" variant="outlined" hint="设置备份任务的执行周期"
                      persistent-hint></VCronField>
                  </v-col>
                  <v-col cols="12" md="4">
                    <v-text-field v-model.number="item.retain_count" label="保留备份数" type="number" density="compact"
                      variant="outlined" :min="1" hint="保留最近N个备份" persistent-hint></v-text-field>
                  </v-col>
                </v-row>

                <v-row>
                  <v-col cols="12" class="d-flex ga-2">
                    <v-btn size="small" color="primary" prepend-icon="mdi-backup-restore"
                      @click="triggerBackup(item.name)" :loading="backupLoading[item.name]" :disabled="!item.name">
                      立即备份
                    </v-btn>
                    <v-btn size="small" color="info" prepend-icon="mdi-format-list-bulleted"
                      @click="listBackups(item.name)" :disabled="!item.name">
                      查看备份
                    </v-btn>
                  </v-col>
                </v-row>
              </v-card-text>
            </v-card>
          </div>

          <v-btn size="small" prepend-icon="mdi-plus" variant="outlined" class="mt-2" @click="addBackupItem">
            添加备份任务
          </v-btn>

          <v-alert type="info" variant="tonal" density="compact" class="mt-4" icon="mdi-information">
            <div class="text-body-2 mb-1"><strong>STRM 备份说明</strong></div>
            <div class="text-caption">
              <div class="mb-1">• 支持将本地 STRM 目录打包为 tar.gz 备份文件</div>
              <div class="mb-1">• 支持备份到本地目录或上传到 115 网盘</div>
              <div class="mb-1">• 支持定时自动备份和手动立即备份</div>
              <div class="mb-1">• 可设置保留备份数量，自动清理旧备份</div>
              <div>• 支持从备份文件一键恢复</div>
            </div>
          </v-alert>

          <v-dialog v-model="backupListDialog" max-width="800">
            <v-card>
              <v-card-title class="d-flex align-center">
                <v-icon class="mr-2">mdi-archive</v-icon>
                <span>备份列表 - {{ currentListTaskName }}</span>
                <v-spacer></v-spacer>
                <v-btn icon size="small" @click="backupListDialog = false">
                  <v-icon>mdi-close</v-icon>
                </v-btn>
              </v-card-title>
              <v-divider></v-divider>
              <v-card-text>
                <v-data-table :headers="backupListHeaders" :items="backupListData" density="compact"
                  :loading="backupListLoading" no-data-text="暂无备份记录" items-per-page-text="每页条数">
                  <template v-slot:item.file_size="{ item }">
                    {{ formatBytes(item.file_size) }}
                  </template>
                  <template v-slot:item.actions="{ item }">
                    <v-btn size="small" color="warning" variant="tonal" @click="showRestoreConfirm(item)">
                      恢复
                    </v-btn>
                  </template>
                </v-data-table>
              </v-card-text>
            </v-card>
          </v-dialog>

          <v-dialog v-model="restoreConfirmDialog" max-width="500" persistent>
            <v-card>
              <v-card-title class="text-h6 d-flex align-center">
                <v-icon icon="mdi-alert-circle-outline" color="warning" class="mr-2"></v-icon>
                确认恢复
              </v-card-title>
              <v-card-text>
                <div class="mb-2">确定要从备份 <strong>{{ restoreTarget?.filename }}</strong> 恢复吗？</div>
                <div class="text-caption text-grey">恢复操作将解压备份文件到源目录，同名文件会被覆盖</div>
              </v-card-text>
              <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="grey" variant="text" @click="restoreConfirmDialog = false"
                  :disabled="restoreConfirmLoading">
                  取消
                </v-btn>
                <v-btn color="warning" variant="text" @click="handleConfirmRestore" :loading="restoreConfirmLoading">
                  确认恢复
                </v-btn>
              </v-card-actions>
            </v-card>
          </v-dialog>
        </v-card-text>
      </v-window-item>
    </v-window>
  </v-card-text>
</template>

<script setup>
import { ref, inject, watch, computed, reactive } from 'vue';

const otherSubTab = ref('tab-sync-del');

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

const strmBackupItems = computed(() => config.strm_backup_items || []);

const backupLoading = reactive({});
const backupListDialog = ref(false);
const backupListLoading = ref(false);
const backupListData = ref([]);
const currentListTaskName = ref('');

const backupListHeaders = [
  { title: '文件名', key: 'filename', sortable: true },
  { title: '大小', key: 'file_size', sortable: true },
  { title: '创建时间', key: 'created_at', sortable: true },
  { title: '状态', key: 'status', sortable: true },
  { title: '操作', key: 'actions', sortable: false },
];

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
    if (v) {
      config.hdhive_checkin_gamble_enabled = false;
    }
  },
);

watch(
  () => config.hdhive_checkin_gamble_enabled,
  (v) => {
    if (v) {
      config.hdhive_checkin_daily_enabled = false;
    }
  },
);
</script>
