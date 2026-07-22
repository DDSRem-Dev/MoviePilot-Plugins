<template>
  <div class="plugin-page">
    <v-card flat class="rounded border page-main-card" style="display: flex; flex-direction: column;">
      <!-- 标题区域 -->
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-1 bg-primary-gradient">
        <v-icon icon="mdi-file-link" class="mr-2" color="primary" size="small" />
        <span>115网盘STRM助手</span>
      </v-card-title>

      <!-- 通知区域 -->
      <v-card-text class="px-3 py-1"
        style="flex-grow: 1; min-height: 0; overflow-y: auto; padding-bottom: 48px; -webkit-overflow-scrolling: touch;">
        <v-alert v-if="error" type="error" density="compact" class="mb-2" variant="tonal" closable>{{ error }}</v-alert>
        <v-alert v-if="actionMessage" :type="actionMessageType" density="compact" class="mb-2" variant="tonal"
          closable>{{ actionMessage }}</v-alert>

        <v-skeleton-loader v-if="loading && !initialDataLoaded" type="article, actions"></v-skeleton-loader>

        <div v-if="initialDataLoaded" class="my-1">
          <!-- 状态和功能区 -->
          <v-row>
            <v-col cols="12" md="6">
              <!-- 基础状态 -->
              <v-card flat class="rounded mb-3 border config-card">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-1 bg-primary-gradient">
                  <v-icon icon="mdi-information" class="mr-2" color="primary" size="small" />
                  <span>系统状态</span>
                </v-card-title>
                <v-card-text class="pa-0">
                  <v-list class="bg-transparent pa-0">
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="status.enabled ? 'success' : 'grey'" icon="mdi-power" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">插件状态</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="status.enabled ? 'success' : 'grey'" size="x-small" variant="tonal">
                          {{ status.enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="status.has_client && initialConfig?.cookies ? 'success' : 'error'"
                          icon="mdi-account-check" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">115客户端状态</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="status.has_client && initialConfig?.cookies ? 'success' : 'error'"
                          size="x-small" variant="tonal">
                          {{ status.has_client && initialConfig?.cookies ? '已连接' : '未连接' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="status.running ? 'warning' : 'success'" icon="mdi-play-circle" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">任务状态</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="status.running ? 'warning' : 'success'" size="x-small" variant="tonal">
                          {{ status.running ? '运行中' : '空闲' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                  </v-list>
                </v-card-text>
              </v-card>

              <!-- 账户信息 -->
              <v-card flat class="rounded mb-3 border config-card">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-1 bg-primary-gradient">
                  <v-icon icon="mdi-account-box" class="mr-2" color="primary" size="small" />
                  <span>115账户信息</span>
                </v-card-title>
                <v-card-text class="pa-0">
                  <v-skeleton-loader v-if="userInfo.loading || storageInfo.loading"
                    type="list-item-avatar-three-line, list-item-three-line"></v-skeleton-loader>
                  <div v-else>
                    <v-alert v-if="userInfo.error || storageInfo.error" type="warning" density="compact" class="ma-2"
                      variant="tonal">
                      {{ userInfo.error || storageInfo.error }}
                    </v-alert>
                    <v-list v-else class="bg-transparent pa-0">
                      <!-- 用户名和头像 -->
                      <v-list-item class="px-3 py-1">
                        <template v-slot:prepend>
                          <v-avatar size="32" class="mr-2">
                            <v-img :src="userInfo.avatar" :alt="userInfo.name" v-if="userInfo.avatar"></v-img>
                            <v-icon icon="mdi-account-circle" v-else></v-icon>
                          </v-avatar>
                        </template>
                        <v-list-item-title class="text-body-1 font-weight-medium">{{ userInfo.name || '未知用户'
                          }}</v-list-item-title>
                      </v-list-item>
                      <v-divider class="my-0"></v-divider>
                      <!-- VIP 信息 -->
                      <v-list-item class="px-3 py-1">
                        <template v-slot:prepend>
                          <v-icon :color="userInfo.is_vip ? 'amber-darken-2' : 'grey'" icon="mdi-shield-crown"
                            size="small" />
                        </template>
                        <v-list-item-title class="text-body-2">VIP状态</v-list-item-title>
                        <template v-slot:append>
                          <v-chip :color="userInfo.is_vip ? 'success' : 'grey'" size="x-small" variant="tonal">
                            {{ userInfo.is_vip ? (userInfo.is_forever_vip ? '永久VIP' : `VIP (至 ${userInfo.vip_expire_date
                              || 'N/A'})`) : '非VIP' }}
                          </v-chip>
                        </template>
                      </v-list-item>
                      <v-divider class="my-0"></v-divider>
                      <!-- 存储空间 -->
                      <v-list-item class="px-3 py-1">
                        <v-list-item-title class="text-body-2 mb-1">存储空间</v-list-item-title>
                        <v-list-item-subtitle v-if="storageInfo.used && storageInfo.total" class="text-caption">
                          已用 {{ storageInfo.used }} / 总共 {{ storageInfo.total }} (剩余 {{ storageInfo.remaining }})
                        </v-list-item-subtitle>
                        <v-progress-linear v-if="storageInfo.used && storageInfo.total"
                          :model-value="calculateStoragePercentage(storageInfo.used, storageInfo.total)" color="primary"
                          height="6" rounded class="mt-1"></v-progress-linear>
                        <v-list-item-subtitle v-else class="text-caption text-grey">
                          存储信息不可用
                        </v-list-item-subtitle>
                      </v-list-item>
                    </v-list>
                  </div>
                </v-card-text>
              </v-card>
              <!-- 功能状态 -->
              <v-card flat class="rounded mb-3 border config-card">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-1 bg-primary-gradient">
                  <v-icon icon="mdi-puzzle" class="mr-2" color="primary" size="small" />
                  <span>功能配置</span>
                </v-card-title>
                <v-card-text class="pa-0">
                  <v-list class="bg-transparent pa-0">
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="initialConfig?.transfer_monitor_enabled ? 'success' : 'grey'"
                          icon="mdi-file-move" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">监控MP整理</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="initialConfig?.transfer_monitor_enabled ? 'success' : 'grey'" size="x-small"
                          variant="tonal">
                          {{ initialConfig?.transfer_monitor_enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="initialConfig?.timing_full_sync_strm ? 'success' : 'grey'" icon="mdi-sync"
                          size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">定期全量同步</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="initialConfig?.timing_full_sync_strm ? 'success' : 'grey'" size="x-small"
                          variant="tonal">
                          {{ initialConfig?.timing_full_sync_strm ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="initialConfig?.increment_sync_strm_enabled ? 'success' : 'grey'"
                          icon="mdi-book-sync" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">定期增量同步</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="initialConfig?.increment_sync_strm_enabled ? 'success' : 'grey'" size="x-small"
                          variant="tonal">
                          {{ initialConfig?.increment_sync_strm_enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="initialConfig?.monitor_life_enabled ? 'success' : 'grey'"
                          icon="mdi-calendar-heart" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">监控115生活事件</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="initialConfig?.monitor_life_enabled ? 'success' : 'grey'" size="x-small"
                          variant="tonal">
                          {{ initialConfig?.monitor_life_enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="initialConfig?.pan_transfer_enabled ? 'success' : 'grey'" icon="mdi-transfer"
                          size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">网盘整理</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="initialConfig?.pan_transfer_enabled ? 'success' : 'grey'" size="x-small"
                          variant="tonal">
                          {{ initialConfig?.pan_transfer_enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon
                          :color="initialConfig?.clear_recyclebin_enabled || initialConfig?.clear_receive_path_enabled ? 'success' : 'grey'"
                          icon="mdi-broom" size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">定期清理</v-list-item-title>
                      <template v-slot:append>
                        <v-chip
                          :color="initialConfig?.clear_recyclebin_enabled || initialConfig?.clear_receive_path_enabled ? 'success' : 'grey'"
                          size="x-small" variant="tonal">
                          {{ initialConfig?.clear_recyclebin_enabled || initialConfig?.clear_receive_path_enabled ?
                            '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="initialConfig?.sync_del_enabled ? 'warning' : 'grey'" icon="mdi-delete-sweep"
                          size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">同步删除</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="initialConfig?.sync_del_enabled ? 'warning' : 'grey'" size="x-small"
                          variant="tonal">
                          {{ initialConfig?.sync_del_enabled ? '已启用' : '已禁用' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                    <v-list-item class="px-3 py-0" style="min-height: 34px;">
                      <template v-slot:prepend>
                        <v-icon :color="fuseStatus.mounted ? 'success' : 'grey'" icon="mdi-folder-network"
                          size="small" />
                      </template>
                      <v-list-item-title class="text-body-2">FUSE 文件系统</v-list-item-title>
                      <template v-slot:append>
                        <v-chip :color="fuseStatus.mounted ? 'success' : 'grey'" size="x-small" variant="tonal">
                          {{ fuseStatus.mounted ? '已挂载' : '未挂载' }}
                        </v-chip>
                      </template>
                    </v-list-item>
                    <v-divider class="my-0"></v-divider>
                  </v-list>
                </v-card-text>
              </v-card>

              <!-- FUSE 文件系统控制 -->
              <v-card v-if="initialConfig?.fuse_enabled" flat class="rounded mb-3 border config-card">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-1 bg-primary-gradient">
                  <v-icon icon="mdi-folder-network" class="mr-2" color="primary" size="small" />
                  <span>FUSE 文件系统</span>
                  <v-spacer></v-spacer>
                  <v-btn icon size="x-small" variant="text" @click="getFuseStatus" :loading="fuseStatus.loading"
                    class="ml-1">
                    <v-icon>mdi-refresh</v-icon>
                  </v-btn>
                </v-card-title>
                <v-card-text class="pa-3">
                  <v-skeleton-loader v-if="fuseStatus.loading" type="list-item-three-line"></v-skeleton-loader>
                  <div v-else>
                    <v-alert v-if="fuseStatus.error" type="warning" density="compact" class="mb-2" variant="tonal">
                      {{ fuseStatus.error }}
                    </v-alert>
                    <v-list class="bg-transparent pa-0">
                      <v-list-item class="px-0 py-1">
                        <template v-slot:prepend>
                          <v-icon :color="fuseStatus.mounted ? 'success' : 'grey'" icon="mdi-folder-network"
                            size="small" />
                        </template>
                        <v-list-item-title class="text-body-2">挂载状态</v-list-item-title>
                        <template v-slot:append>
                          <v-chip :color="fuseStatus.mounted ? 'success' : 'grey'" size="x-small" variant="tonal">
                            {{ fuseStatus.mounted ? '已挂载' : '未挂载' }}
                          </v-chip>
                        </template>
                      </v-list-item>
                      <v-list-item v-if="fuseStatus.mountpoint" class="px-0 py-1">
                        <template v-slot:prepend>
                          <v-icon icon="mdi-folder" size="small" color="primary" />
                        </template>
                        <v-list-item-title class="text-body-2">挂载点</v-list-item-title>
                        <template v-slot:append>
                          <span class="text-caption text-grey">{{ fuseStatus.mountpoint }}</span>
                        </template>
                      </v-list-item>
                      <v-list-item class="px-0 py-1">
                        <template v-slot:prepend>
                          <v-icon icon="mdi-clock-outline" size="small" color="primary" />
                        </template>
                        <v-list-item-title class="text-body-2">目录缓存 TTL</v-list-item-title>
                        <template v-slot:append>
                          <span class="text-caption text-grey">{{ fuseStatus.readdir_ttl }} 秒</span>
                        </template>
                      </v-list-item>
                    </v-list>
                    <v-row class="mt-2">
                      <v-col cols="12" md="6">
                        <v-btn color="success" variant="elevated" block @click="mountFuse"
                          :loading="fuseStatus.mounting" :disabled="fuseStatus.mounted">
                          <v-icon start>mdi-folder-plus</v-icon>
                          挂载
                        </v-btn>
                      </v-col>
                      <v-col cols="12" md="6">
                        <v-btn color="error" variant="elevated" block @click="unmountFuse"
                          :loading="fuseStatus.unmounting" :disabled="!fuseStatus.mounted">
                          <v-icon start>mdi-folder-remove</v-icon>
                          卸载
                        </v-btn>
                      </v-col>
                    </v-row>
                  </div>
                </v-card-text>
              </v-card>

              <!-- 同步删除历史记录 -->
              <v-card v-if="initialConfig?.sync_del_enabled" flat class="rounded mb-3 border config-card">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-1 bg-primary-gradient">
                  <v-icon icon="mdi-history" class="mr-2" color="primary" size="small" />
                  <span>同步删除历史</span>
                  <v-spacer></v-spacer>
                  <v-btn v-if="syncDelHistoryTotal > 5" size="x-small" variant="text"
                    @click="syncDelHistoryDialog.show = true" prepend-icon="mdi-open-in-new">
                    查看全部 ({{ syncDelHistoryTotal }})
                  </v-btn>
                  <v-btn icon size="x-small" variant="text" @click="loadSyncDelHistory" :loading="syncDelHistoryLoading"
                    class="ml-1">
                    <v-icon>mdi-refresh</v-icon>
                  </v-btn>
                </v-card-title>
                <v-card-text class="pa-0">
                  <v-skeleton-loader v-if="syncDelHistoryLoading"
                    type="list-item-avatar-three-line@3"></v-skeleton-loader>
                  <div v-else-if="syncDelHistory.length === 0" class="text-center py-4">
                    <v-icon icon="mdi-information-outline" size="large" color="grey" class="mb-2"></v-icon>
                    <div class="text-caption text-grey">暂无删除历史</div>
                  </div>
                  <v-list v-else class="bg-transparent pa-0">
                    <template v-for="(item, index) in displayedSyncDelHistory" :key="item.unique || index">
                      <v-list-item class="px-3 py-2">
                        <template v-slot:prepend>
                          <v-avatar size="48" rounded class="mr-3">
                            <v-img :src="item.image" :alt="item.title" cover v-if="item.image"></v-img>
                            <v-icon icon="mdi-movie" v-else></v-icon>
                          </v-avatar>
                        </template>
                        <v-list-item-title class="text-body-2 font-weight-medium">{{ item.title }}</v-list-item-title>
                        <v-list-item-subtitle class="text-caption">
                          <div class="d-flex flex-wrap align-center gap-1 mt-1">
                            <v-chip size="x-small" variant="tonal" color="primary">{{ item.type }}</v-chip>
                            <span v-if="item.year" class="text-grey">· {{ item.year }}</span>
                            <span v-if="item.season" class="text-grey">· S{{ String(item.season).padStart(2, '0')
                            }}</span>
                            <span v-if="item.episode" class="text-grey">· E{{ String(item.episode).padStart(2, '0')
                            }}</span>
                          </div>
                          <div class="text-grey mt-1">{{ item.del_time }}</div>
                        </v-list-item-subtitle>
                        <template v-slot:append>
                          <v-btn icon size="x-small" variant="text" color="error" @click="confirmDeleteHistory(item)"
                            :loading="deletingHistoryId === item.unique">
                            <v-icon>mdi-delete</v-icon>
                          </v-btn>
                        </template>
                      </v-list-item>
                      <v-divider v-if="index < displayedSyncDelHistory.length - 1" class="my-0"></v-divider>
                    </template>
                  </v-list>
                </v-card-text>
              </v-card>
            </v-col>



            <v-col cols="12" md="6">
              <!-- 路径状态 -->
              <v-card flat class="rounded mb-3 border config-card">
                <v-card-title class="text-subtitle-2 d-flex align-center px-3 py-1 bg-primary-gradient">
                  <v-icon icon="mdi-folder-search" class="mr-2" color="primary" size="small" />
                  <span>路径配置</span>
                </v-card-title>
                <v-card-text class="pa-0">
                  <v-list class="bg-transparent pa-0">
                    <!-- 监控MP整理路径 -->
                    <v-list-item v-if="initialConfig?.transfer_monitor_enabled" class="px-3 py-2">
                      <div>
                        <div class="text-body-2 font-weight-medium mb-1">监控MP整理路径</div>
                        <template v-if="getPathsCount(initialConfig?.transfer_monitor_paths) > 0">
                          <template v-for="(path, index) in getParsedPaths(initialConfig?.transfer_monitor_paths)"
                            :key="`transfer-${index}`">
                            <v-divider v-if="index > 0" class="my-1"></v-divider>
                            <div class="path-mapping-item pa-2 border rounded-sm"
                              style="background-color: rgba(var(--v-theme-on-surface), 0.02);">
                              <v-row dense align="center">
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="primary"
                                    class="mr-2 flex-shrink-0">mdi-folder-home</v-icon>
                                  <div class="text-truncate w-100" :title="path.local">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">本地目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.local || '-' }}</span>
                                  </div>
                                </v-col>
                                <v-col cols="12" sm="2" class="text-center my-1 my-sm-0">
                                  <v-icon color="primary" class="icon-spin-animation">mdi-sync</v-icon>
                                </v-col>
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="success" class="mr-2 flex-shrink-0">mdi-cloud</v-icon>
                                  <div class="text-truncate w-100" :title="path.remote">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">网盘目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.remote || '-' }}</span>
                                  </div>
                                </v-col>
                              </v-row>
                            </div>
                          </template>
                        </template>
                        <template v-else>
                          <div class="text-caption text-error mt-1">未配置路径</div>
                        </template>
                      </div>
                    </v-list-item>

                    <v-divider
                      v-if="initialConfig?.transfer_monitor_enabled && (initialConfig?.increment_sync_strm_enabled || initialConfig?.timing_full_sync_strm || initialConfig?.monitor_life_enabled || initialConfig?.pan_transfer_enabled || initialConfig?.directory_upload_enabled)"
                      class="my-0"></v-divider>

                    <!-- 全量同步路径 -->
                    <v-list-item v-if="initialConfig?.timing_full_sync_strm" class="px-3 py-2">
                      <div>
                        <div class="text-body-2 font-weight-medium mb-1">全量同步路径</div>
                        <template v-if="getPathsCount(initialConfig?.full_sync_strm_paths) > 0">
                          <template v-for="(path, index) in getParsedPaths(initialConfig?.full_sync_strm_paths)"
                            :key="`fullsync-${index}`">
                            <v-divider v-if="index > 0" class="my-1"></v-divider>
                            <div class="path-mapping-item pa-2 border rounded-sm"
                              style="background-color: rgba(var(--v-theme-on-surface), 0.02);">
                              <v-row dense align="center">
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="primary"
                                    class="mr-2 flex-shrink-0">mdi-folder-home</v-icon>
                                  <div class="text-truncate w-100" :title="path.local">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">本地目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.local || '-' }}</span>
                                  </div>
                                </v-col>
                                <v-col cols="12" sm="2" class="text-center my-1 my-sm-0">
                                  <v-icon color="primary" class="icon-spin-animation">mdi-sync</v-icon>
                                </v-col>
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="success" class="mr-2 flex-shrink-0">mdi-cloud</v-icon>
                                  <div class="text-truncate w-100" :title="path.remote">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">网盘目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.remote || '-' }}</span>
                                  </div>
                                </v-col>
                              </v-row>
                            </div>
                          </template>
                        </template>
                        <template v-else>
                          <div class="text-caption text-error mt-1">未配置路径</div>
                        </template>
                      </div>
                    </v-list-item>

                    <v-divider
                      v-if="initialConfig?.timing_full_sync_strm && (initialConfig?.increment_sync_strm_enabled || initialConfig?.monitor_life_enabled || initialConfig?.pan_transfer_enabled || initialConfig?.directory_upload_enabled)"
                      class="my-0"></v-divider>

                    <!-- 增量同步路径 -->
                    <v-list-item v-if="initialConfig?.increment_sync_strm_enabled" class="px-3 py-2">
                      <div>
                        <div class="text-body-2 font-weight-medium mb-1">增量同步路径</div>
                        <template v-if="getPathsCount(initialConfig?.increment_sync_strm_paths) > 0">
                          <template v-for="(path, index) in getParsedPaths(initialConfig?.increment_sync_strm_paths)"
                            :key="`incsync-${index}`">
                            <v-divider v-if="index > 0" class="my-1"></v-divider>
                            <div class="path-mapping-item pa-2 border rounded-sm"
                              style="background-color: rgba(var(--v-theme-on-surface), 0.02);">
                              <v-row dense align="center">
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="primary"
                                    class="mr-2 flex-shrink-0">mdi-folder-home</v-icon>
                                  <div class="text-truncate w-100" :title="path.local">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">本地目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.local || '-' }}</span>
                                  </div>
                                </v-col>
                                <v-col cols="12" sm="2" class="text-center my-1 my-sm-0">
                                  <v-icon color="primary" class="icon-spin-animation">mdi-sync</v-icon>
                                </v-col>
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="success" class="mr-2 flex-shrink-0">mdi-cloud</v-icon>
                                  <div class="text-truncate w-100" :title="path.remote">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">网盘目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.remote || '-' }}</span>
                                  </div>
                                </v-col>
                              </v-row>
                            </div>
                          </template>
                        </template>
                        <template v-else>
                          <div class="text-caption text-error mt-1">未配置路径</div>
                        </template>
                      </div>
                    </v-list-item>

                    <v-divider
                      v-if="initialConfig?.increment_sync_strm_enabled && (initialConfig?.monitor_life_enabled || initialConfig?.pan_transfer_enabled || initialConfig?.directory_upload_enabled)"
                      class="my-0"></v-divider>

                    <!-- 监控115生活事件路径 -->
                    <v-list-item v-if="initialConfig?.monitor_life_enabled" class="px-3 py-2">
                      <div>
                        <div class="text-body-2 font-weight-medium mb-1">监控115生活事件路径</div>
                        <template v-if="getPathsCount(initialConfig?.monitor_life_paths) > 0">
                          <template v-for="(path, index) in getParsedPaths(initialConfig?.monitor_life_paths)"
                            :key="`life-${index}`">
                            <v-divider v-if="index > 0" class="my-1"></v-divider>
                            <div class="path-mapping-item pa-2 border rounded-sm"
                              style="background-color: rgba(var(--v-theme-on-surface), 0.02);">
                              <v-row dense align="center">
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="primary"
                                    class="mr-2 flex-shrink-0">mdi-folder-home</v-icon>
                                  <div class="text-truncate w-100" :title="path.local">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">本地目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.local || '-' }}</span>
                                  </div>
                                </v-col>
                                <v-col cols="12" sm="2" class="text-center my-1 my-sm-0">
                                  <v-icon color="primary" class="icon-spin-animation">mdi-sync</v-icon>
                                </v-col>
                                <v-col cols="12" sm="5" class="d-flex align-center">
                                  <v-icon size="small" color="success" class="mr-2 flex-shrink-0">mdi-cloud</v-icon>
                                  <div class="text-truncate w-100" :title="path.remote">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height: 1.2;">网盘目录</span>
                                    <span class="text-caption" style="line-height: 1.2;">{{ path.remote || '-' }}</span>
                                  </div>
                                </v-col>
                              </v-row>
                            </div>
                          </template>
                        </template>
                        <template v-else>
                          <div class="text-caption text-error mt-1">未配置路径</div>
                        </template>
                      </div>
                    </v-list-item>

                    <v-divider
                      v-if="initialConfig?.monitor_life_enabled && (initialConfig?.pan_transfer_enabled || initialConfig?.directory_upload_enabled)"
                      class="my-0"></v-divider>

                    <!-- 网盘整理目录 -->
                    <v-list-item v-if="initialConfig?.pan_transfer_enabled" class="px-3 py-2">
                      <div>
                        <div class="text-body-2 font-weight-medium mb-1">网盘整理目录</div>
                        <template v-if="getPanTransferPathsCount(initialConfig?.pan_transfer_paths) > 0">
                          <template
                            v-for="(pathItem, index) in getParsedPanTransferPaths(initialConfig?.pan_transfer_paths)"
                            :key="`pan-${index}`">
                            <v-divider v-if="index > 0" class="my-1"></v-divider>
                            <div class="path-item pa-2 border rounded-sm"
                              style="background-color: rgba(var(--v-theme-on-surface), 0.02);">
                              <div class="d-flex align-center">
                                <v-icon size="small" color="success"
                                  class="mr-2 flex-shrink-0">mdi-folder-arrow-down</v-icon>
                                <div class="text-truncate w-100" :title="pathItem.path">
                                  <span class="text-caption font-weight-medium d-block"
                                    style="line-height: 1.2;">待整理网盘目录</span>
                                  <span class="text-caption" style="line-height: 1.2;">{{ pathItem.path }}</span>
                                </div>
                              </div>
                            </div>
                          </template>
                        </template>
                        <template v-else>
                          <div class="text-caption text-error mt-1">未配置网盘整理目录</div>
                        </template>
                      </div>
                    </v-list-item>

                    <v-divider v-if="initialConfig?.pan_transfer_enabled && initialConfig?.directory_upload_enabled"
                      class="my-0"></v-divider>

                    <!-- Directory Upload Paths Display -->
                    <v-list-item v-if="initialConfig?.directory_upload_enabled" class="px-3 py-2">
                      <div>
                        <div class="text-body-2 font-weight-medium mb-1">目录上传路径</div>
                        <template
                          v-if="initialConfig?.directory_upload_path && initialConfig.directory_upload_path.length > 0">
                          <template v-for="(pathGroup, groupIndex) in initialConfig.directory_upload_path"
                            :key="`upload-group-${groupIndex}`">
                            <v-divider v-if="groupIndex > 0" class="my-1"></v-divider>
                            <div class="path-group-item pa-2 border rounded-sm"
                              style="background-color: rgba(var(--v-theme-on-surface), 0.02);">
                              <v-row dense align="center">
                                <v-col cols="12" md="5" class="d-flex align-center">
                                  <v-icon size="small" color="primary"
                                    class="mr-2 flex-shrink-0">mdi-folder-table</v-icon>
                                  <div class="text-truncate w-100" :title="pathGroup.src">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height:1.2;">本地监控</span>
                                    <span class="text-caption" style="line-height:1.2;">{{ pathGroup.src || '-'
                                      }}</span>
                                  </div>
                                </v-col>
                                <v-col cols="12" md="2" class="text-center my-1 my-md-0">
                                  <v-icon color="primary" class="icon-spin-animation">mdi-sync</v-icon>
                                </v-col>
                                <v-col cols="12" md="5" class="d-flex align-center">
                                  <v-icon size="small" color="success"
                                    class="mr-2 flex-shrink-0">mdi-cloud-upload</v-icon>
                                  <div class="text-truncate w-100" :title="pathGroup.dest_remote">
                                    <span class="text-caption font-weight-medium d-block"
                                      style="line-height:1.2;">网盘上传</span>
                                    <span class="text-caption" style="line-height:1.2;">{{ pathGroup.dest_remote || '-'
                                      }}</span>
                                  </div>
                                </v-col>
                              </v-row>
                              <div v-if="pathGroup.dest_local || typeof pathGroup.delete === 'boolean'"
                                class="mt-1 pt-1" style="border-top: 1px dashed rgba(var(--v-border-color), 0.2);">
                                <v-row dense align="center" class="mt-1">
                                  <v-col cols="12" :md="typeof pathGroup.delete === 'boolean' ? 7 : 12">
                                    <div v-if="pathGroup.dest_local" class="d-flex align-center">
                                      <v-icon size="small" color="warning"
                                        class="mr-2 flex-shrink-0">mdi-content-copy</v-icon>
                                      <div class="text-truncate w-100" :title="pathGroup.dest_local">
                                        <span class="text-caption font-weight-medium d-block"
                                          style="line-height:1.2;">本地复制</span>
                                        <span class="text-caption" style="line-height:1.2;">{{ pathGroup.dest_local
                                          }}</span>
                                      </div>
                                    </div>
                                  </v-col>
                                  <v-col v-if="typeof pathGroup.delete === 'boolean'" cols="12"
                                    :md="pathGroup.dest_local ? 5 : 12" class="d-flex align-center"
                                    :class="{ 'justify-md-end': pathGroup.dest_local, 'mt-1 mt-md-0': pathGroup.dest_local }">
                                    <v-icon size="small" :color="pathGroup.delete ? 'error' : 'grey-darken-1'"
                                      class="mr-1 flex-shrink-0">
                                      {{ pathGroup.delete ? 'mdi-delete' : 'mdi-delete-off' }}
                                    </v-icon>
                                    <span class="text-caption"
                                      :class="pathGroup.delete ? 'text-error' : 'text-grey-darken-1'">
                                      {{ pathGroup.delete ? '删除源' : '不删源' }}
                                    </span>
                                  </v-col>
                                </v-row>
                              </div>
                            </div>
                          </template>
                        </template>
                        <template v-else>
                          <div class="text-caption text-error mt-1">未配置路径</div>
                        </template>
                      </div>
                    </v-list-item>
                  </v-list>
                </v-card-text>
              </v-card>

              <!-- 配置提示卡片 -->
              <v-card v-if="!status.has_client || !initialConfig.cookies" flat class="rounded mb-3 border config-card">
                <v-card-text class="pa-3">
                  <div class="d-flex">
                    <v-icon icon="mdi-alert-circle" color="error" class="mr-2" size="small"></v-icon>
                    <div class="text-body-2">
                      <p class="mb-1"><strong>未配置115 Cookie或Cookie无效</strong></p>
                      <p class="mb-0">请在配置页面中设置有效的115网盘Cookie，可通过扫码登录获取。</p>
                      <v-btn color="primary" variant="text" size="small" class="mt-1 px-2 py-0" @click="emit('switch')">
                        <v-icon size="small" class="mr-1">mdi-cog</v-icon>前往配置
                      </v-btn>
                    </div>
                  </div>
                </v-card-text>
              </v-card>

              <v-card v-else-if="!isProperlyCongifured" flat class="rounded mb-3 border config-card">
                <v-card-text class="pa-3">
                  <div class="d-flex">
                    <v-icon icon="mdi-alert-circle" color="warning" class="mr-2" size="small"></v-icon>
                    <div class="text-body-2">
                      <p class="mb-1"><strong>路径配置不完整</strong></p>
                      <p class="mb-0">您已配置115 Cookie，但部分功能路径未配置。请前往配置页面完善路径设置。</p>
                      <v-btn color="primary" variant="text" size="small" class="mt-1 px-2 py-0" @click="emit('switch')">
                        <v-icon size="small" class="mr-1">mdi-cog</v-icon>前往配置
                      </v-btn>
                    </div>
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>

          <!-- 帮助信息卡片 -->
          <v-card flat class="rounded mb-3 border config-card">
            <v-card-text class="d-flex align-center px-3 py-1">
              <v-icon icon="mdi-information" color="info" class="mr-2" size="small"></v-icon>
              <span class="text-body-2">
                点击"配置"按钮进行设置，"全量同步"和"分享同步"按钮可立即执行相应任务。
              </span>
            </v-card-text>
          </v-card>
        </div>
      </v-card-text>

      <v-divider></v-divider>

      <v-card-actions class="px-2 py-1 sticky-actions d-flex justify-space-between align-center"
        style="flex-shrink: 0; gap: 8px;">
        <v-btn color="info" @click="refreshStatus" prepend-icon="mdi-refresh" :disabled="refreshing"
          :loading="refreshing" variant="text" size="small">刷新状态</v-btn>

        <div class="d-flex align-center" style="gap: 4px;">
          <!-- “更多操作” 菜单 -->
          <v-menu offset-y>
            <template v-slot:activator="{ props }">
              <v-btn v-bind="props" variant="text" size="small" append-icon="mdi-dots-vertical">
                更多
              </v-btn>
            </template>
            <v-list density="compact">
              <v-list-item @click="fullSyncConfirmDialog = true"
                :disabled="!status.enabled || !status.has_client || actionLoading">
                <template v-slot:prepend>
                  <v-icon color="warning">mdi-sync</v-icon>
                </template>
                <v-list-item-title>全量同步</v-list-item-title>
              </v-list-item>
              <v-list-item @click="fullSyncDbConfirmDialog = true"
                :disabled="!status.enabled || !status.has_client || actionLoading">
                <template v-slot:prepend>
                  <v-icon color="primary">mdi-database-sync</v-icon>
                </template>
                <v-list-item-title>全量同步数据库</v-list-item-title>
              </v-list-item>
              <v-list-item @click="openShareDialog" :disabled="!status.enabled || !status.has_client || actionLoading"
                :loading="shareSyncLoading">
                <template v-slot:prepend>
                  <v-icon color="info">mdi-share-variant</v-icon>
                </template>
                <v-list-item-title>分享同步</v-list-item-title>
              </v-list-item>
              <v-list-item @click="openOfflineDownloadDialog"
                :disabled="!status.enabled || !status.has_client || actionLoading">
                <template v-slot:prepend>
                  <v-icon color="secondary">mdi-cloud-download-outline</v-icon>
                </template>
                <v-list-item-title>离线下载</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-menu>

          <!-- 始终可见的核心按钮 -->
          <v-btn color="primary" @click="emit('switch')" prepend-icon="mdi-cog" variant="text" size="small">配置</v-btn>
          <v-btn color="error" @click="emit('close')" variant="flat" size="small" class="custom-close-btn"
            aria-label="关闭"
            style="min-width: auto !important; padding: 0 10px !important; height: 28px !important; line-height: 28px !important;">
            <v-icon size="small">mdi-close</v-icon>
          </v-btn>
        </div>
      </v-card-actions>
    </v-card>
  </div>

  <!-- 分享同步对话框 -->
  <v-dialog v-model="shareDialog.show" max-width="900" scrollable>
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-1 dialog-title-surface">
        <v-icon icon="mdi-share-variant" class="mr-2" color="primary" size="small" />
        <span>115网盘分享同步</span>
        <v-spacer></v-spacer>
        <v-btn icon="mdi-close" variant="text" size="small" @click="closeShareDialog"></v-btn>
      </v-card-title>

      <v-card-text class="px-3 py-2">
        <v-alert v-if="shareDialog.error" type="error" density="compact" class="mb-3" variant="tonal">
          {{ shareDialog.error }}
        </v-alert>

        <!-- 全局配置 -->
        <v-card variant="outlined" class="mb-4">
          <v-card-title class="text-subtitle-2 px-3 py-2 section-title-surface">
            <v-icon icon="mdi-cog" size="small" class="mr-2"></v-icon>
            全局配置
          </v-card-title>
          <v-card-text class="pa-3">
            <v-row>
              <v-col cols="12">
                <v-select v-model="shareDialog.globalMediaservers" label="刷新媒体服务器" hint="应用于所有分享配置的媒体服务器刷新设置"
                  persistent-hint :items="mediaservers" multiple chips closable-chips variant="outlined"
                  density="compact"></v-select>
              </v-col>
            </v-row>
            <v-row class="mt-2">
              <v-col cols="12" md="6">
                <v-text-field v-model.number="shareDialog.globalMediaServerRefreshDelay" label="媒体库延迟刷新(秒)" type="number"
                  min="0" density="compact" hint="0 表示不延迟，立即刷新" persistent-hint variant="outlined"></v-text-field>
              </v-col>
            </v-row>
            <v-row class="mt-2">
              <v-col cols="12">
                <v-textarea v-model="shareDialog.globalMpMediaserverPaths" label="MP-媒体库 目录转换"
                  hint="格式：媒体库路径#MP路径，多个用换行分隔。应用于所有分享配置" persistent-hint variant="outlined" density="compact" rows="3"
                  auto-grow placeholder="例如:&#10;/media#/mp&#10;/nas#/movie"></v-textarea>
              </v-col>
            </v-row>
            <v-divider class="my-4"></v-divider>
            <v-row>
              <v-col cols="12">
                <v-switch v-model="shareDialog.auditQueueEnabled" label="启用分享文件审核等待队列" color="primary"
                  density="compact" hint="分享文件仍在审核时转入后台队列，审核通过后自动下载" persistent-hint />
              </v-col>
            </v-row>
            <v-expand-transition>
              <v-row v-if="shareDialog.auditQueueEnabled" class="mt-2">
                <v-col cols="12" md="6">
                  <v-text-field v-model.number="shareDialog.auditMaxWaitHours" label="最长审核等待时间(小时)" type="number"
                    min="1" max="168" density="compact" hint="超过该时间后终止等待并记录失败" persistent-hint
                    variant="outlined" />
                </v-col>
                <v-col cols="12" md="6">
                  <v-text-field v-model.number="shareDialog.auditRetryIntervalMinutes" label="审核检查间隔(分钟)" type="number"
                    min="1" max="360" density="compact" hint="默认每 30 分钟检查一次" persistent-hint
                    variant="outlined" />
                </v-col>
              </v-row>
            </v-expand-transition>
          </v-card-text>
        </v-card>

        <!-- 分享交互生成 STRM（二级折叠） -->
        <v-expansion-panels v-model="shareDialog.shareInteractiveGenStrmExpanded" variant="tonal" class="mb-4" multiple>
          <v-expansion-panel value="share-interactive-gen-strm" class="rounded border" eager>
            <v-expansion-panel-title class="text-subtitle-2 d-flex align-center px-3 py-2 section-title-surface">
              <v-icon icon="mdi-chat-processing" size="small" class="mr-2"></v-icon>
              <span>分享交互生成 STRM</span>
              <v-chip size="x-small" class="ml-2" variant="tonal" color="primary">/p115_share_strm</v-chip>
            </v-expansion-panel-title>
            <v-expansion-panel-text class="pa-3" eager>
              <div class="command-hint mb-4">
                <v-icon icon="mdi-information-outline" size="small" color="info"></v-icon>
                <div>
                  <div class="text-body-2">发送 <code>/p115_share_strm</code> + 115 分享链接，或直接转发资源消息</div>
                  <div class="text-caption text-medium-emphasis">任务会加入独立队列串行执行</div>
                </div>
              </div>
              <v-row>
                <v-col cols="12" md="6">
                  <v-text-field v-model="shareDialog.interactiveGenStrm.minFileSizeFormatted" label="最小生成文件大小"
                    hint="小于此值不生成 STRM，留空不限制；如 500M、1G" persistent-hint variant="outlined" density="compact" />
                </v-col>
                <v-col cols="12" md="6">
                  <v-select v-model="shareDialog.interactiveGenStrm.iterFunction" label="迭代函数" :items="shareIteratorItems"
                    item-title="title" item-value="value" variant="outlined" density="compact" persistent-hint
                    :hint="shareDialog.interactiveGenStrm.iterFunction === 'share_iter_files'
                      ? '高速，仅生成 STRM；不上传共享数据'
                      : '详细数据，支持元数据下载与共享'" />
                </v-col>
              </v-row>
              <v-row v-if="shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path'">
                <v-col cols="12" md="6">
                  <v-select v-model="shareDialog.interactiveGenStrm.speedMode" label="运行速度模式" :items="speedModeItems"
                    item-title="title" item-value="value" variant="outlined" density="compact" />
                </v-col>
              </v-row>
              <v-row>
                <v-col cols="12">
                  <div class="d-flex align-center flex-wrap ga-2">
                    <v-text-field v-model="shareDialog.interactiveGenStrm.localPath" label="本地生成目录" class="flex-grow-1"
                      density="compact" variant="outlined" clearable hide-details style="min-width: 200px;" />
                    <v-btn size="small" color="primary" variant="tonal" prepend-icon="mdi-folder"
                      @click="openInteractiveGenStrmDirSelector">选择目录</v-btn>
                  </div>
                </v-col>
              </v-row>
              <v-row class="mt-2">
                <v-col v-if="shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path'" cols="12" md="6">
                  <v-switch v-model="shareDialog.interactiveGenStrm.autoDownloadMediainfo" label="自动下载网盘元数据"
                    color="primary" density="compact" hide-details
                    :disabled="shareDialog.interactiveGenStrm.moviepilotTransfer" />
                </v-col>
                <v-col cols="12" :md="shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path' ? 6 : 12">
                  <v-switch v-model="shareDialog.interactiveGenStrm.moviepilotTransfer" label="交由 MoviePilot 整理"
                    color="info" density="compact" hide-details />
                </v-col>
              </v-row>
              <v-expand-transition>
                <div v-if="shareDialog.interactiveGenStrm.moviepilotTransfer
                  && shareDialog.interactiveGenStrm.iterFunction === 'iter_share_files_with_path'" class="mt-2">
                  <v-switch v-model="shareDialog.interactiveGenStrm.moviepilotTransferDownloadRmtAudioSub"
                    label="下载 MoviePilot 可整理的音轨与字幕" color="primary" density="compact" hide-details />
                  <div class="text-caption text-medium-emphasis mt-1 ml-1">
                    仅下载 MoviePilot 允许的音轨和字幕，保存后与 STRM 一并整理
                  </div>
                </div>
              </v-expand-transition>
              <v-expand-transition>
                <div v-if="shareDialog.interactiveGenStrm.moviepilotTransfer">
                  <details class="mp-config-help mt-3">
                    <summary>MoviePilot 整理配置说明</summary>
                    <div class="text-caption mb-2">开启 MP 整理时，「本地生成目录」为临时待整理目录，请在 MoviePilot <strong>设定 → 目录</strong>
                      中配置
                    </div>
                    <ol class="text-caption mb-0 pl-5">
                      <li class="mb-1">资源存储选择<strong>本地</strong>，资源目录填写本插件的<strong>本地生成目录</strong></li>
                      <li>自动整理选择<strong>手动整理</strong>，媒体库存储选择<strong>本地</strong>，整理方式选择<strong>移动</strong></li>
                    </ol>
                  </details>
                </div>
              </v-expand-transition>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>

        <!-- 无效分享 STRM 清理 -->
        <v-expansion-panels v-model="shareDialog.shareStrmCleanupExpanded" variant="tonal" class="mb-4" multiple>
          <v-expansion-panel value="share-strm-cleanup" class="rounded border" eager>
            <v-expansion-panel-title class="text-subtitle-2 d-flex align-center px-3 py-2 section-title-surface">
              <v-icon icon="mdi-broom" size="small" class="mr-2"></v-icon>
              <span>无效分享 STRM 清理</span>
            </v-expansion-panel-title>
            <v-expansion-panel-text class="pa-3" eager>
              <v-alert type="info" density="compact" variant="tonal" class="mb-3">
                <div class="text-caption">仅在下方配置的本地根目录下扫描；与「分享配置列表」中的本地路径无关</div>
              </v-alert>
              <div class="text-subtitle-2 mb-1">清理扫描根目录</div>
              <div class="text-caption text-medium-emphasis mb-2">本地目录，可添加多项；点击右侧文件夹图标浏览选择，亦可手动修改路径</div>
              <div v-if="shareDialog.cleanupPaths.length === 0" class="text-caption text-medium-emphasis mb-2">尚未添加目录
              </div>
              <div v-for="(_p, idx) in shareDialog.cleanupPaths" :key="'share-strm-cleanup-path-' + idx"
                class="d-flex align-start gap-2 mb-2">
                <v-text-field v-model="shareDialog.cleanupPaths[idx]" class="flex-grow-1" label="本地路径"
                  variant="outlined" density="compact" hide-details prepend-inner-icon="mdi-folder"
                  append-inner-icon="mdi-folder-search" @click:append-inner="openShareStrmCleanupDirSelector(idx)" />
                <v-btn icon size="small" variant="text" color="error" class="mt-1" title="移除此路径"
                  @click="removeShareStrmCleanupPath(idx)">
                  <v-icon size="small">mdi-close</v-icon>
                </v-btn>
              </div>
              <div class="d-flex flex-wrap align-center gap-2 mb-3">
                <v-btn size="small" variant="tonal" color="primary" prepend-icon="mdi-plus"
                  @click="addShareStrmCleanupPath">
                  添加目录
                </v-btn>
                <v-btn color="primary" variant="flat" size="small" prepend-icon="mdi-play"
                  :loading="shareStrmCleanupScanLoading" @click="runShareStrmCleanupScan">
                  立即扫描
                </v-btn>
                <span class="text-caption text-medium-emphasis">扫描前会先保存本页清理配置</span>
              </div>
              <v-row class="mt-1" align="center">
                <v-col cols="12" sm="6" lg="3">
                  <v-switch v-model="shareDialog.timingShareStrmCleanup" label="定时运行" color="primary" density="compact"
                    hide-details />
                </v-col>
                <v-col cols="12" sm="6" lg="5">
                  <VCronField v-model="shareDialog.cronShareStrmCleanup" label="定时清理周期" density="compact" />
                </v-col>
                <v-col cols="12" lg="4">
                  <v-select v-model="shareDialog.deleteMode" label="删除策略" variant="outlined" density="compact" :items="[
                    { title: '立即删除', value: 'immediate' },
                    { title: '插件内待确认', value: 'plugin_ui' },
                  ]" />
                </v-col>
              </v-row>
              <v-row class="mt-1">
                <v-col cols="12" md="6">
                  <v-switch v-model="shareDialog.removeRelatedMediainfo" label="清理无效STRM文件关联的媒体信息文件" color="primary"
                    density="compact" hide-details />
                </v-col>
                <v-col cols="12" md="6">
                  <v-switch v-model="shareDialog.removeEmptyParentDirs" label="清理无效STRM目录" color="primary"
                    density="compact" hide-details />
                </v-col>
                <v-col cols="12" md="6">
                  <v-switch v-model="shareDialog.removeStaleTransferHistory" label="删除 MoviePilot 整理记录" color="primary"
                    density="compact" hide-details />
                </v-col>
                <v-col cols="12" md="6">
                  <v-switch v-model="shareDialog.recordMissingMediaFromHistory" label="采集缺失媒体信息" color="primary"
                    density="compact" hide-details />
                </v-col>
              </v-row>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>

        <!-- 分享配置列表 -->
        <v-card variant="outlined">
          <v-card-title class="text-subtitle-2 px-3 py-2 section-title-surface d-flex align-center">
            <v-icon icon="mdi-share-variant" size="small" class="mr-2"></v-icon>
            <span class="flex-grow-1">分享配置列表</span>
            <v-btn size="small" prepend-icon="mdi-delete-sweep" variant="text" color="error" @click="clearShareConfigs"
              :disabled="shareDialog.configs.length === 0" title="清空所有分享配置">
              清空
            </v-btn>
            <v-btn size="small" prepend-icon="mdi-plus" variant="tonal" color="primary" @click="addShareConfig"
              class="ml-2">
              添加分享
            </v-btn>
          </v-card-title>
          <v-card-text class="pa-0">
            <v-list v-if="shareDialog.configs.length > 0" class="pa-0">
              <template v-for="(config, index) in shareDialog.configs" :key="index">
                <v-list-item class="px-3 py-2">
                  <template v-slot:prepend>
                    <v-icon icon="mdi-share-variant" color="primary" size="small" class="mr-2"></v-icon>
                  </template>
                  <v-list-item-title class="text-body-2 font-weight-medium d-flex align-center">
                    <v-icon v-if="!config.enabled" icon="mdi-power-off" size="small" color="grey" class="mr-1"></v-icon>
                    <v-icon v-else icon="mdi-power" size="small" color="success" class="mr-1"></v-icon>
                    <span>{{ config.comment || config.share_link || config.share_code || `分享配置 ${index + 1}` }}</span>
                  </v-list-item-title>
                  <v-list-item-subtitle class="text-caption mt-1">
                    <div class="d-flex flex-column">
                      <div v-if="config.comment && (config.share_link || config.share_code)" class="mb-1 text-grey">
                        {{ config.share_link || config.share_code }}
                      </div>
                      <span v-if="config.local_path" class="mb-1">
                        <v-icon icon="mdi-folder" size="x-small" class="mr-1"></v-icon>
                        本地路径: {{ config.local_path }}
                      </span>
                      <span v-else class="text-grey">未配置本地路径</span>
                      <div class="d-flex flex-wrap ga-2 mt-1">
                        <span v-if="config.share_path && config.share_path !== '/'">
                          <v-icon icon="mdi-folder-network" size="x-small" class="mr-1"></v-icon>
                          分享路径: {{ config.share_path }}
                        </span>
                        <span v-if="config.min_file_size">
                          <v-icon icon="mdi-file-size" size="x-small" class="mr-1"></v-icon>
                          最小文件: {{ formatBytes(config.min_file_size) }}
                        </span>
                        <v-chip size="x-small" variant="tonal" color="info">
                          {{ config.iter_function === 'iter_share_files_with_path' ? '详细迭代' : '高速简略' }}
                        </v-chip>
                        <span v-if="config.iter_function === 'iter_share_files_with_path' && config.speed_mode !== undefined">
                          <v-icon icon="mdi-speedometer" size="x-small" class="mr-1"></v-icon>
                          速度: {{ ['最快', '快', '慢', '最慢'][config.speed_mode] }}
                        </span>
                        <v-chip v-if="config.moviepilot_transfer" size="x-small" color="primary" variant="tonal">
                          MP整理
                        </v-chip>
                      </div>
                    </div>
                  </v-list-item-subtitle>
                  <template v-slot:append>
                    <div class="d-flex align-center">
                      <v-btn icon="mdi-pencil" size="small" variant="text" color="primary"
                        @click="editShareConfig(index)" title="编辑"></v-btn>
                      <v-btn icon="mdi-delete" size="small" variant="text" color="error"
                        @click="removeShareConfig(index)" title="删除"></v-btn>
                    </div>
                  </template>
                </v-list-item>
                <v-divider v-if="index < shareDialog.configs.length - 1" class="my-0"></v-divider>
              </template>
            </v-list>
            <v-alert v-else type="info" density="compact" variant="tonal" class="ma-3">
              <div class="d-flex align-center">
                <span>暂无分享配置，请点击"添加分享"按钮添加</span>
              </div>
            </v-alert>
          </v-card-text>
        </v-card>
      </v-card-text>

      <v-divider></v-divider>
      <v-card-actions class="px-3 py-1">
        <v-btn color="grey" variant="text" @click="closeShareDialog" size="small">取消</v-btn>
        <v-spacer></v-spacer>
        <v-tooltip location="top">
          <template v-slot:activator="{ props }">
            <v-btn color="info" variant="text" @click="saveShareConfigs" :loading="shareConfigSaving" size="small"
              v-bind="props">
              保存配置
            </v-btn>
          </template>
          <span>仅保存配置到系统，不执行同步任务</span>
        </v-tooltip>
        <v-tooltip location="top">
          <template v-slot:activator="{ props }">
            <v-btn color="primary" variant="text" @click="executeShareSync" :loading="shareSyncLoading"
              :disabled="!isShareDialogValid" size="small" class="ml-2" v-bind="props">
              保存并同步
            </v-btn>
          </template>
          <span>保存配置并立即执行分享同步任务（需要至少一个有效配置）</span>
        </v-tooltip>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 分享配置编辑对话框 -->
  <v-dialog v-model="shareConfigDialog.show" max-width="700" scrollable>
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-1 dialog-title-surface">
        <v-icon icon="mdi-share-variant" class="mr-2" color="primary" size="small" />
        <span>{{ shareConfigDialog.editingIndex >= 0 ? '编辑分享配置' : '添加分享配置' }}</span>
        <v-spacer></v-spacer>
        <v-btn icon="mdi-close" variant="text" size="small" @click="closeShareConfigDialog"></v-btn>
      </v-card-title>

      <v-card-text class="px-3 py-3">
        <v-alert v-if="shareConfigDialog.error" type="error" density="compact" class="mb-3" variant="tonal" closable>
          {{ shareConfigDialog.error }}
        </v-alert>

        <v-row class="mb-2">
          <v-col cols="12">
            <v-switch v-model="shareConfigDialog.enabled" label="启用此配置" color="primary" density="compact" hide-details>
              <template v-slot:label>
                <div class="d-flex align-center">
                  <v-icon icon="mdi-power" size="small" class="mr-2"></v-icon>
                  <span>启用此配置</span>
                </div>
              </template>
            </v-switch>
          </v-col>
        </v-row>

        <v-row class="mb-2">
          <v-col cols="12">
            <v-text-field v-model="shareConfigDialog.comment" label="备注" hint="为此配置添加备注说明，方便识别" persistent-hint
              variant="outlined" density="compact" prepend-inner-icon="mdi-note-text" clearable></v-text-field>
          </v-col>
        </v-row>

        <v-divider class="my-3"></v-divider>

        <v-row class="mb-2">
          <v-col cols="12">
            <v-text-field v-model="shareConfigDialog.shareLink" label="分享链接" hint="115网盘分享链接" persistent-hint
              variant="outlined" density="compact" prepend-inner-icon="mdi-link"></v-text-field>
          </v-col>
        </v-row>

        <v-row class="mb-2">
          <v-col cols="12" md="6">
            <v-text-field v-model="shareConfigDialog.shareCode" label="分享码" hint="分享码，和分享链接选填一项" persistent-hint
              variant="outlined" density="compact" prepend-inner-icon="mdi-key"></v-text-field>
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field v-model="shareConfigDialog.shareReceive" label="分享密码" hint="分享密码，和分享链接选填一项" persistent-hint
              variant="outlined" density="compact" prepend-inner-icon="mdi-lock" type="password"></v-text-field>
          </v-col>
        </v-row>

        <v-row class="mb-2">
          <v-col cols="12" md="6">
            <v-text-field v-model="shareConfigDialog.sharePath" label="分享路径" hint="分享内容列表中的相对路径，默认为根目录 /"
              persistent-hint variant="outlined" density="compact"
              prepend-inner-icon="mdi-folder-network"></v-text-field>
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field v-model="shareConfigDialog.localPath" label="本地路径" hint="本地生成STRM文件的路径" persistent-hint
              variant="outlined" density="compact" prepend-inner-icon="mdi-folder" append-icon="mdi-folder-search"
              @click:append="openShareConfigDirSelector('local')"></v-text-field>
          </v-col>
        </v-row>

        <v-row class="mb-2">
          <v-col cols="12" md="6">
            <v-text-field v-model="shareConfigDialog.minFileSizeFormatted" label="分享生成最小文件大小" hint="小于此值不生成STRM(K,M,G)"
              persistent-hint variant="outlined" density="compact" placeholder="例如: 100M" clearable
              prepend-inner-icon="mdi-file-document"></v-text-field>
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="shareConfigDialog.iterFunction" label="迭代函数" :hint="shareConfigDialog.iterFunction === 'share_iter_files'
              ? '高速，仅生成 STRM；不上传共享数据'
              : '详细数据，支持元数据下载与共享'" persistent-hint
              variant="outlined" density="compact" :items="shareIteratorItems" prepend-inner-icon="mdi-file-tree"
              item-title="title" item-value="value"></v-select>
          </v-col>
        </v-row>

        <v-row v-if="shareConfigDialog.iterFunction === 'iter_share_files_with_path'" class="mb-2">
          <v-col cols="12" md="6">
            <v-select v-model="shareConfigDialog.speedMode" label="运行速度模式" hint="控制API调用速率，避免触发风控" persistent-hint
              variant="outlined" density="compact" :items="speedModeItems" prepend-inner-icon="mdi-speedometer">
              <template v-slot:item="{ props, item }">
                <v-list-item v-bind="props" :title="item.raw.title" :subtitle="item.raw.subtitle"></v-list-item>
              </template>
              <template v-slot:selection="{ item }">
                <span>{{ item.raw.title }}</span>
              </template>
            </v-select>
          </v-col>
        </v-row>

        <v-divider class="my-3"></v-divider>

        <v-row class="mb-2">
          <v-col cols="12">
            <v-switch v-model="shareConfigDialog.moviepilotTransfer" label="STRM 交由 MoviePilot 整理" color="primary"
              density="compact" hide-details>
              <template v-slot:label>
                <div class="d-flex align-center">
                  <v-icon icon="mdi-transfer" size="small" class="mr-2"></v-icon>
                  <span>STRM 交由 MoviePilot 整理</span>
                </div>
              </template>
            </v-switch>
          </v-col>
        </v-row>

        <v-expand-transition>
          <div v-if="shareConfigDialog.moviepilotTransfer" class="mb-2">
            <v-row>
              <v-col v-if="shareConfigDialog.iterFunction === 'iter_share_files_with_path'" cols="12">
                <v-switch v-model="shareConfigDialog.moviepilotTransferDownloadRmtAudioSub" color="primary"
                  density="compact" hide-details>
                  <template v-slot:label>
                    <div class="d-flex align-center flex-wrap">
                      <v-icon icon="mdi-subtitles-outline" size="small" class="mr-2"></v-icon>
                      <span>下载 MoviePilot 可整理的音轨与字幕</span>
                    </div>
                  </template>
                </v-switch>
                <div class="text-caption text-medium-emphasis mt-1 ml-1">
                  仅下载 MoviePilot 允许的音轨和字幕，保存后与 STRM 一并整理
                </div>
              </v-col>
            </v-row>
          </div>
        </v-expand-transition>

        <v-expand-transition>
          <div v-if="!shareConfigDialog.moviepilotTransfer">
            <v-row class="mb-2">
              <v-col v-if="shareConfigDialog.iterFunction === 'iter_share_files_with_path'" cols="12" md="4"
                class="d-flex align-center">
                <v-switch v-model="shareConfigDialog.autoDownloadMediainfo" color="primary" density="compact"
                  hide-details class="flex-grow-1">
                  <template v-slot:label>
                    <div class="d-flex align-center">
                      <v-icon icon="mdi-download" size="small" class="mr-2"></v-icon>
                      <span>自动下载网盘元数据</span>
                    </div>
                  </template>
                </v-switch>
              </v-col>
              <v-col cols="12" :md="shareConfigDialog.iterFunction === 'iter_share_files_with_path' ? 4 : 6"
                class="d-flex align-center">
                <v-switch v-model="shareConfigDialog.mediaServerRefresh" color="primary" density="compact" hide-details
                  class="flex-grow-1">
                  <template v-slot:label>
                    <div class="d-flex align-center">
                      <v-icon icon="mdi-refresh" size="small" class="mr-2"></v-icon>
                      <span>刷新媒体服务器</span>
                    </div>
                  </template>
                </v-switch>
              </v-col>
              <v-col cols="12" :md="shareConfigDialog.iterFunction === 'iter_share_files_with_path' ? 4 : 6"
                class="d-flex align-center">
                <v-switch v-model="shareConfigDialog.scrapeMetadata" color="primary" density="compact" hide-details
                  class="flex-grow-1">
                  <template v-slot:label>
                    <div class="d-flex align-center">
                      <v-icon icon="mdi-file-search" size="small" class="mr-2"></v-icon>
                      <span>是否刮削元数据</span>
                    </div>
                  </template>
                </v-switch>
              </v-col>
            </v-row>
          </div>
        </v-expand-transition>

        <details class="mp-config-help mt-3">
          <summary>配置提示</summary>
          <ul class="text-caption ma-0 pl-5">
            <li class="mb-1">分享链接/分享码和分享密码只需要二选一配置，同时填写时优先读取分享链接</li>
            <li>关闭 MoviePilot 整理后，才能配置自动下载网盘元数据、刷新媒体服务器和刮削元数据</li>
          </ul>
        </details>
      </v-card-text>

      <v-divider></v-divider>
      <v-card-actions class="px-3 py-1">
        <v-btn color="grey" variant="text" @click="closeShareConfigDialog" size="small">取消</v-btn>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="saveShareConfig" :disabled="!isShareConfigDialogValid"
          size="small">
          保存
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 离线下载对话框 -->
  <v-dialog v-model="offlineDownloadDialog.show" max-width="800" persistent>
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-1 dialog-title-surface">
        <v-icon icon="mdi-cloud-download-outline" class="mr-2" color="primary" size="small" />
        <span>115离线下载</span>
        <v-spacer></v-spacer>
        <v-btn icon="mdi-close" variant="text" size="small" @click="closeOfflineDownloadDialog"></v-btn>
      </v-card-title>

      <v-card-text class="pa-0">
        <v-tabs v-model="offlineDownloadDialog.activeTab" bg-color="primary-gradient" grow>
          <v-tab value="add">添加任务</v-tab>
          <v-tab value="tasks">任务列表</v-tab>
        </v-tabs>

        <v-window v-model="offlineDownloadDialog.activeTab" :touch="false">
          <!-- 添加任务 -->
          <v-window-item value="add">
            <div class="pa-3">
              <v-alert v-if="offlineDownloadDialog.addError" type="error" density="compact" class="mb-3"
                variant="tonal">
                {{ offlineDownloadDialog.addError }}
              </v-alert>
              <v-textarea v-model="offlineDownloadDialog.links" label="下载链接" hint="每行一个链接，支持 http(s)/ftp/magnet/ed2k"
                persistent-hint variant="outlined" rows="5" clearable></v-textarea>

              <!-- 路径选择：下拉列表 + 手动输入 -->
              <v-combobox v-model="offlineDownloadDialog.destPath" :items="offlineDownloadDialog.availablePathStrings"
                label="网盘保存路径 (可选)" hint="可选，默认为网盘待整理目录。可从缓存路径或配置路径中选择，也可手动输入" persistent-hint variant="outlined"
                density="compact" class="mt-3" clearable>
                <template v-slot:prepend-inner>
                  <v-icon icon="mdi-folder-network-outline" size="small"></v-icon>
                </template>
                <template v-slot:append-inner>
                  <v-btn icon="mdi-folder-network" variant="text" size="x-small"
                    @click.stop="openOfflineDestDirSelector" class="mr-n2"></v-btn>
                </template>
                <template v-slot:item="{ props: itemProps, item }">
                  <v-list-item v-bind="itemProps" :title="getPathLabel(item.raw)">
                  </v-list-item>
                </template>
              </v-combobox>

              <div class="d-flex justify-end mt-3">
                <v-btn color="primary" @click="addOfflineTask" :loading="offlineDownloadDialog.adding"
                  :disabled="!offlineDownloadDialog.links || offlineDownloadDialog.adding" prepend-icon="mdi-plus">
                  添加任务
                </v-btn>
              </div>
            </div>
          </v-window-item>

          <!-- 任务列表 -->
          <v-window-item value="tasks">
            <div style="overflow-x: auto;" @touchstart.stop @touchmove.stop @touchend.stop>
              <v-alert v-if="offlineDownloadDialog.error" type="error" density="compact" class="ma-3" variant="tonal">
                {{ offlineDownloadDialog.error }}
              </v-alert>
              <v-data-table-server :headers="offlineDownloadDialog.headers" :items="offlineDownloadDialog.tasks"
                :items-length="offlineDownloadDialog.totalTasks" :loading="offlineDownloadDialog.loading"
                :items-per-page="offlineDownloadDialog.itemsPerPage" @update:options="fetchOfflineTasks"
                density="compact" class="ma-2" no-data-text="没有离线下载任务" loading-text="正在加载任务..."
                items-per-page-text="每页条目数" style="min-width: 700px;" @touchstart.stop @touchmove.stop @touchend.stop>
                <template v-slot:item.progress="{ item }">
                  <div class="d-flex align-center">
                    <v-progress-linear :model-value="item.percent" :color="getTaskStatusColor(item.status)"
                      :stream="item.status === 0 || item.status === 3" :striped="item.status === 0 || item.status === 3"
                      height="8" rounded class="flex-grow-1 mr-3"></v-progress-linear>
                    <div class="text-no-wrap text-caption font-weight-medium"
                      style="min-width: 40px; text-align: right;">
                      {{ item.percent }}%
                    </div>
                  </div>
                </template>
                <template v-slot:item.status_text="{ item }">
                  <v-chip :color="getTaskStatusColor(item.status)" size="x-small" variant="tonal">
                    {{ item.status_text }}
                  </v-chip>
                </template>
              </v-data-table-server>
            </div>
          </v-window-item>
        </v-window>
      </v-card-text>
    </v-card>
  </v-dialog>

  <!-- 目录选择器对话框 -->
  <DirSelectorDialog :dir-dialog="dirDialog" :disable-root="true" @load-dir="loadDirContent"
    @navigate-up="navigateToParentDir" @select-dir="selectDir" @confirm="confirmDirSelection" @close="closeDirDialog" />

  <!-- 全量同步确认对话框 -->
  <FullSyncConfirmDialog v-model="fullSyncConfirmDialog" :loading="syncLoading"
    :has-media-server-refresh="initialConfig?.full_sync_media_server_refresh_enabled"
    @confirm="handleConfirmFullSync" />

  <v-dialog v-model="fullSyncDbConfirmDialog" max-width="450" persistent>
    <v-card>
      <v-card-title class="text-h6 d-flex align-center">
        <v-icon icon="mdi-alert-circle-outline" color="warning" class="mr-2"></v-icon>
        确认操作
      </v-card-title>
      <v-card-text>
        您确定要立即执行全量同步数据库吗？该操作会覆盖原有数据库数据
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="fullSyncDbConfirmDialog = false" :disabled="syncDbLoading">
          取消
        </v-btn>
        <v-btn color="warning" variant="text" @click="handleConfirmFullSyncDb" :loading="syncDbLoading">
          确认执行
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 确认删除单条历史记录对话框 -->
  <v-dialog v-model="deleteHistoryConfirmDialog.show" max-width="450" persistent>
    <v-card>
      <v-card-title class="text-h6 d-flex align-center">
        <v-icon icon="mdi-alert-circle-outline" color="error" class="mr-2"></v-icon>
        确认删除
      </v-card-title>
      <v-card-text>
        <div class="mb-2">确定要删除这条历史记录吗？</div>
        <v-card variant="outlined" class="mt-3" v-if="deleteHistoryConfirmDialog.item">
          <v-card-text class="pa-3">
            <div class="text-body-1 font-weight-medium">{{ deleteHistoryConfirmDialog.item.title }}</div>
            <div class="text-caption text-grey mt-1" v-if="deleteHistoryConfirmDialog.item.path"
              style="word-break: break-all;">
              {{ deleteHistoryConfirmDialog.item.path }}
            </div>
            <div class="text-caption text-grey mt-1">{{ deleteHistoryConfirmDialog.item.del_time }}</div>
          </v-card-text>
        </v-card>
        <v-alert type="warning" variant="tonal" density="compact" class="mt-2" icon="mdi-alert">
          <div class="text-caption">此操作不可恢复，请谨慎操作！</div>
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="deleteHistoryConfirmDialog.show = false"
          :disabled="deletingHistoryId === deleteHistoryConfirmDialog.item?.unique">
          取消
        </v-btn>
        <v-btn color="error" variant="text" @click="handleConfirmDeleteHistory"
          :loading="deletingHistoryId === deleteHistoryConfirmDialog.item?.unique">
          确认删除
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 确认删除所有历史记录对话框 -->
  <v-dialog v-model="deleteAllHistoryConfirmDialog" max-width="450" persistent>
    <v-card>
      <v-card-title class="text-h6 d-flex align-center">
        <v-icon icon="mdi-alert-circle-outline" color="error" class="mr-2"></v-icon>
        确认删除
      </v-card-title>
      <v-card-text>
        <div class="mb-2">确定要删除全部 <strong>{{ syncDelHistoryTotal }}</strong> 条历史记录吗？</div>
        <v-alert type="error" variant="tonal" density="compact" class="mt-2" icon="mdi-alert">
          <div class="text-caption">此操作不可恢复，请谨慎操作！</div>
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="deleteAllHistoryConfirmDialog = false"
          :disabled="deletingAllHistory">
          取消
        </v-btn>
        <v-btn color="error" variant="text" @click="handleConfirmDeleteAllHistory" :loading="deletingAllHistory">
          确认删除
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 同步删除历史记录对话框 -->
  <v-dialog v-model="syncDelHistoryDialog.show" max-width="900" scrollable>
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center px-3 py-2 bg-primary-gradient">
        <v-icon icon="mdi-history" class="mr-2" color="primary" size="small" />
        <span>同步删除历史记录 (共 {{ syncDelHistoryTotal }} 条)</span>
        <v-spacer></v-spacer>
        <v-btn v-if="syncDelHistoryTotal > 0" size="small" variant="text" color="error" @click="confirmDeleteAllHistory"
          :loading="deletingAllHistory" class="mr-2">
          <v-icon start>mdi-delete-sweep</v-icon>
          一键全部删除
        </v-btn>
        <v-btn icon size="x-small" variant="text" @click="loadSyncDelHistory" :loading="syncDelHistoryLoading">
          <v-icon>mdi-refresh</v-icon>
        </v-btn>
        <v-btn icon size="small" variant="text" @click="syncDelHistoryDialog.show = false">
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </v-card-title>
      <v-card-text class="pa-0 sync-del-history-content">
        <v-skeleton-loader v-if="syncDelHistoryLoading" type="list-item-avatar-three-line@5"></v-skeleton-loader>
        <div v-else-if="syncDelHistory.length === 0" class="text-center py-8">
          <v-icon icon="mdi-information-outline" size="large" color="grey" class="mb-2"></v-icon>
          <div class="text-caption text-grey">暂无删除历史</div>
        </div>
        <v-list v-else class="bg-transparent pa-0">
          <template v-for="(item, index) in syncDelHistory" :key="item.unique || index">
            <v-list-item class="px-3 py-2">
              <template v-slot:prepend>
                <v-avatar size="56" rounded class="mr-3">
                  <v-img :src="item.image" :alt="item.title" cover v-if="item.image"></v-img>
                  <v-icon icon="mdi-movie" v-else></v-icon>
                </v-avatar>
              </template>
              <v-list-item-title class="text-body-1 font-weight-medium">{{ item.title }}</v-list-item-title>
              <v-list-item-subtitle class="text-caption">
                <div class="d-flex flex-wrap align-center gap-1 mt-1">
                  <v-chip size="small" variant="tonal" color="primary">{{ item.type }}</v-chip>
                  <span v-if="item.year" class="text-grey">· {{ item.year }}</span>
                  <span v-if="item.season" class="text-grey">· S{{ String(item.season).padStart(2, '0') }}</span>
                  <span v-if="item.episode" class="text-grey">· E{{ String(item.episode).padStart(2, '0') }}</span>
                </div>
                <div v-if="item.path" class="text-grey mt-1" style="word-break: break-all;">{{ item.path }}</div>
                <div class="text-grey mt-1">{{ item.del_time }}</div>
              </v-list-item-subtitle>
              <template v-slot:append>
                <v-btn icon size="small" variant="text" color="error" @click="confirmDeleteHistory(item)"
                  :loading="deletingHistoryId === item.unique">
                  <v-icon>mdi-delete</v-icon>
                </v-btn>
              </template>
            </v-list-item>
            <v-divider v-if="index < syncDelHistory.length - 1" class="my-0"></v-divider>
          </template>
        </v-list>
      </v-card-text>
      <v-card-actions v-if="syncDelHistoryTotal > 0" class="px-4 py-3 d-flex justify-space-between align-center">
        <div class="text-caption text-grey">
          显示第 {{ (syncDelHistoryPage - 1) * syncDelHistoryLimit + 1 }} - {{ Math.min(syncDelHistoryPage *
            syncDelHistoryLimit, syncDelHistoryTotal) }} 条，共 {{ syncDelHistoryTotal }} 条
        </div>
        <v-pagination v-model="syncDelHistoryPage" :length="Math.ceil(syncDelHistoryTotal / syncDelHistoryLimit)"
          :total-visible="7" @update:model-value="loadSyncDelHistory"></v-pagination>
      </v-card-actions>
    </v-card>
  </v-dialog>

</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { P115_STRM_HELPER_PLUGIN_ID } from '../utils/pluginId.js';
import FullSyncConfirmDialog from './dialogs/FullSyncConfirmDialog.vue';
import DirSelectorDialog from './dialogs/DirSelectorDialog.vue';

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true
  },
  initialConfig: {
    type: Object,
    default: () => ({})
  }
});

const emit = defineEmits(['close', 'switch', 'update:config', 'action']);

const pluginId = P115_STRM_HELPER_PLUGIN_ID;

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

// 状态变量
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
  item: null
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

// 只显示最近5条记录
const displayedSyncDelHistory = computed(() => {
  return syncDelHistory.value.slice(0, 5);
});

// 同步删除历史记录对话框
const syncDelHistoryDialog = reactive({
  show: false
});

const status = reactive({
  enabled: false,
  has_client: false,
  running: false
});

const userInfo = reactive({
  name: null,
  is_vip: null,
  is_forever_vip: null,
  vip_expire_date: null,
  avatar: null,
  error: null,
  loading: true
});

const storageInfo = reactive({
  total: null,
  used: null,
  remaining: null,
  error: null,
  loading: true
});

// 路径缓存管理
const OFFLINE_PATH_CACHE_KEY = 'p115strmhelper_offline_paths_cache';
const MAX_CACHED_PATHS = 20; // 最多缓存20个路径

const getCachedPaths = () => {
  try {
    const cached = localStorage.getItem(OFFLINE_PATH_CACHE_KEY);
    if (cached) {
      const paths = JSON.parse(cached);
      return Array.isArray(paths) ? paths.filter(p => p && typeof p === 'string') : [];
    }
  } catch (e) {
    console.error('读取路径缓存失败:', e);
  }
  return [];
};

const addPathToCache = (path) => {
  if (!path || !path.trim()) return;
  const trimmedPath = path.trim();
  let cached = getCachedPaths();
  // 移除重复项
  cached = cached.filter(p => p !== trimmedPath);
  // 添加到开头
  cached.unshift(trimmedPath);
  // 限制数量
  cached = cached.slice(0, MAX_CACHED_PATHS);
  try {
    localStorage.setItem(OFFLINE_PATH_CACHE_KEY, JSON.stringify(cached));
  } catch (e) {
    console.error('保存路径缓存失败:', e);
  }
};

const offlineDownloadDialog = reactive({
  show: false,
  activeTab: 'add', // 默认显示添加任务标签页
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
  availablePaths: [], // 可用路径列表（缓存路径 + 配置路径）- 对象数组
  availablePathStrings: [], // 可用路径字符串数组，用于 v-combobox
});

const calculateStoragePercentage = (used, total) => {
  if (!used || !total) return 0;
  const parseSize = (sizeStr) => {
    if (!sizeStr || typeof sizeStr !== 'string') return 0;
    const value = parseFloat(sizeStr);
    if (isNaN(value)) return 0;
    if (sizeStr.toUpperCase().includes('TB')) return value * 1024 * 1024;
    if (sizeStr.toUpperCase().includes('GB')) return value * 1024;
    if (sizeStr.toUpperCase().includes('MB')) return value;
    return value;
  };
  const usedValue = parseSize(used);
  const totalValue = parseSize(total);
  if (totalValue === 0) return 0;
  return Math.min(Math.max((usedValue / totalValue) * 100, 0), 100);
};

const isProperlyCongifured = computed(() => {
  if (!props.initialConfig) return false;
  const hasBasicConfig = props.initialConfig.enabled && props.initialConfig.cookies && props.initialConfig.moviepilot_address;
  if (!hasBasicConfig) return false;
  const hasTransferPaths = getPathsCount(props.initialConfig.transfer_monitor_paths) > 0 && props.initialConfig.transfer_monitor_enabled;
  const hasFullSyncPaths = getPathsCount(props.initialConfig.full_sync_strm_paths) > 0 && (props.initialConfig.timing_full_sync_strm);
  const hasIncrementSyncPaths = getPathsCount(props.initialConfig.increment_sync_strm_paths) > 0 && (props.initialConfig.increment_sync_strm_enabled);
  const hasLifePaths = getPathsCount(props.initialConfig.monitor_life_paths) > 0 && props.initialConfig.monitor_life_enabled;
  const hasSharePaths = Array.isArray(props.initialConfig.share_strm_config) && props.initialConfig.share_strm_config.length > 0;
  return hasTransferPaths || hasFullSyncPaths || hasIncrementSyncPaths || hasLifePaths || hasSharePaths;
});

const getPathsCount = (pathString) => {
  if (!pathString) return 0;
  try {
    const paths = pathString.split('\n').filter(line => line.trim() && line.includes('#'));
    return paths.length;
  } catch (e) {
    console.error('解析路径字符串失败:', e);
    return 0;
  }
};

const getPanTransferPathsCount = (pathString) => {
  if (!pathString) return 0;
  try {
    const paths = pathString.split('\n').filter(line => line.trim());
    return paths.length;
  } catch (e) {
    console.error('解析网盘整理路径字符串失败:', e);
    return 0;
  }
};

const getStatus = async () => {
  loading.value = true;
  error.value = null;
  try {
    const result = await props.api.get(`plugin/${pluginId}/get_status`);
    // 此处 result.data 的访问方式与新模型兼容，无需修改
    if (result && result.code === 0 && result.data) {
      status.enabled = Boolean(result.data.enabled);
      status.has_client = Boolean(result.data.has_client);
      status.running = Boolean(result.data.running);
      try {
        const configData = await props.api.get(`plugin/${pluginId}/get_config`);
        if (configData) {
          Object.assign(props.initialConfig, configData);
          console.log('已获取最新配置:', props.initialConfig);
        }
      } catch (configErr) {
        console.error('获取配置失败:', configErr);
      }
      initialDataLoaded.value = true;
    } else {
      if (props.initialConfig) {
        status.enabled = Boolean(props.initialConfig.enabled);
        status.has_client = Boolean(props.initialConfig.cookies && props.initialConfig.cookies.trim() !== '');
        status.running = false;
        initialDataLoaded.value = true;
        if (Object.keys(props.initialConfig).length <= 1) {
          try {
            const configData = await props.api.get(`plugin/${pluginId}/get_config`);
            if (configData) {
              Object.assign(props.initialConfig, configData);
              console.log('从配置API获取配置:', props.initialConfig);
            }
          } catch (configErr) {
            console.error('获取配置失败:', configErr);
          }
        }
        throw new Error('状态API调用失败，使用配置数据显示状态');
      } else {
        throw new Error(result?.msg || '获取状态失败，请检查网络连接');
      }
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
      userInfo.error = "请先配置115 Cookie。";
      storageInfo.error = "请先配置115 Cookie。";
    } else if (!status.has_client) {
      userInfo.error = "115客户端未连接或Cookie无效。";
      storageInfo.error = "115客户端未连接或Cookie无效。";
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
    if (getPathsCount(props.initialConfig?.full_sync_strm_paths) === 0) throw new Error('未配置全量同步路径，请先在配置页面设置同步路径');
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
  /** 分享同步对话框内「分享交互生成 STRM」折叠面板展开项 */
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
  return shareDialog.configs.length > 0 && shareDialog.configs.every(config => {
    if (!config.local_path) return false;
    if (!config.share_link && !config.share_code) return false;
    if (config.share_code && !config.share_receive) return false;
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
  callback: null
});

const openShareDialog = () => {
  shareDialog.show = true;
  shareDialog.error = null;
  if (props.initialConfig) {
    // 加载分享配置列表
    shareDialog.configs = Array.isArray(props.initialConfig.share_strm_config)
      ? JSON.parse(JSON.stringify(props.initialConfig.share_strm_config))
      : [];

    // 加载全局配置
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
  const retryIntervalMinutes = Math.max(
    1,
    Number(shareDialog.auditRetryIntervalMinutes) || 30,
  );
  if (retryIntervalMinutes * 60 > maxWaitHours * 3600) {
    throw new Error('审核检查间隔不能超过最长审核等待时间');
  }
  props.initialConfig.share_audit_queue_enabled = shareDialog.auditQueueEnabled;
  props.initialConfig.share_audit_max_wait_seconds = maxWaitHours * 3600;
  props.initialConfig.share_audit_retry_interval_seconds = retryIntervalMinutes * 60;
};

const flushShareStrmCleanupToInitialConfig = () => {
  if (!props.initialConfig) return;
  const lines = (shareDialog.cleanupPaths || [])
    .map((s) => String(s).trim())
    .filter(Boolean);
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
  shareDialog.configs = [];
  shareDialog.error = null;
  shareDialog.interactiveGenStrm = defaultInteractiveGenStrm();
  shareDialog.shareInteractiveGenStrmExpanded = [];
  shareDialog.cleanupPaths = [];
  shareDialog.timingShareStrmCleanup = false;
  shareDialog.cronShareStrmCleanup = '0 */12 * * *';
  shareDialog.deleteMode = 'plugin_ui';
  shareDialog.removeRelatedMediainfo = true;
  shareDialog.removeEmptyParentDirs = true;
  shareDialog.removeStaleTransferHistory = false;
  shareDialog.recordMissingMediaFromHistory = true;
  shareDialog.shareStrmCleanupExpanded = [];
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

const clearShareConfigs = () => {
  if (shareDialog.configs.length === 0) return;
  if (confirm('确定要清空所有分享配置吗？此操作不可恢复。')) {
    shareDialog.configs = [];
  }
};

const saveShareConfigs = async () => {
  shareConfigSaving.value = true;
  shareDialog.error = null;
  try {
    if (props.initialConfig) {
      // 更新配置
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
  const config = {
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
    shareDialog.configs[shareConfigDialog.editingIndex] = config;
  } else {
    shareDialog.configs.push(config);
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
        const response = await props.api.post('storage/list', { path: dirDialog.currentPath || '/', type: 'share', flag: 'ROOT' });
        if (response && Array.isArray(response)) {
          dirDialog.items = response
            .filter(item => item.type === 'dir')
            .map(item => ({ name: item.name, path: item.path, is_dir: true }))
            .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
        } else {
          throw new Error('浏览目录失败：无效响应');
        }
      } catch (error) {
        console.error('浏览本地目录失败:', error);
        dirDialog.error = `浏览本地目录失败: ${error.message || '未知错误'}`;
        dirDialog.items = [];
      }
    } else {
      if (!props.initialConfig?.cookies || props.initialConfig?.cookies.trim() === '') {
        throw new Error('请先设置115 Cookie才能浏览网盘目录');
      }
      const result = await props.api.get(`plugin/${pluginId}/browse_dir?path=${encodeURIComponent(dirDialog.currentPath)}&is_local=${dirDialog.isLocal}`);
      // 修改点: 从 result.data 中获取核心数据
      if (result && result.code === 0 && result.data) {
        dirDialog.items = result.data.items.filter(item => item.is_dir);
        dirDialog.currentPath = result.data.path || dirDialog.currentPath;
      } else {
        throw new Error(result?.msg || '获取网盘目录内容失败');
      }
    }
  } catch (error) {
    console.error('加载目录内容失败:', error);
    dirDialog.error = error.message || '获取目录内容失败';
    if (error.message.includes('Cookie') || error.message.includes('cookie')) {
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
    dirDialog.currentPath = parts[0] + ':/';
  } else {
    parts.pop();
    dirDialog.currentPath = parts.length === 0 ? '/' : (normalizedPath.startsWith('/') ? '/' : '') + parts.join('/') + '/';
  }
  loadDirContent();
};

const confirmDirSelection = () => {
  if (!dirDialog.currentPath) return;
  let processedPath = dirDialog.currentPath;
  if (processedPath !== '/' && !(/^[a-zA-Z]:[\\\/]$/.test(processedPath)) && (processedPath.endsWith('/') || processedPath.endsWith('\\\\'))) {
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
    if (!props.initialConfig) {
      throw new Error('配置对象不存在');
    }
    flushShareStrmCleanupToInitialConfig();
    const saveResult = await props.api.post(
      `plugin/${pluginId}/save_config`,
      props.initialConfig,
    );
    if (!saveResult || saveResult.code !== 0) {
      throw new Error(saveResult?.msg || '保存配置失败');
    }
    const result = await props.api.post(
      `plugin/${pluginId}/share_strm_cleanup_scan`,
    );
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
    if (shareDialog.configs.length === 0) {
      throw new Error('请至少添加一个分享配置');
    }

    if (props.initialConfig) {
      // 更新配置
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

  // 1. 添加缓存的路径
  const cachedPaths = getCachedPaths();
  cachedPaths.forEach(path => {
    if (path && !pathSet.has(path)) {
      paths.push({ label: `📁 ${path}`, path: path, type: 'cached' });
      pathSet.add(path);
    }
  });

  // 2. 添加配置的离线下载路径
  if (props.initialConfig?.offline_download_paths && Array.isArray(props.initialConfig.offline_download_paths)) {
    props.initialConfig.offline_download_paths.forEach(path => {
      if (path && typeof path === 'string' && path.trim() && !pathSet.has(path.trim())) {
        paths.push({ label: `⚙️ ${path.trim()}`, path: path.trim(), type: 'config' });
        pathSet.add(path.trim());
      }
    });
  }

  offlineDownloadDialog.availablePaths = paths;
  // 同时生成字符串数组供 v-combobox 使用
  offlineDownloadDialog.availablePathStrings = paths.map(p => p.path);
};


const getPathLabel = (path) => {
  if (!path) return '';
  const found = offlineDownloadDialog.availablePaths.find(p => p.path === path);
  return found ? found.label : path;
};

const openOfflineDownloadDialog = () => {
  offlineDownloadDialog.show = true;
  offlineDownloadDialog.activeTab = 'add'; // 默认显示添加任务标签页
  offlineDownloadDialog.error = null;
  offlineDownloadDialog.addError = null;
  buildAvailablePaths(); // 构建可用路径列表
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
      page: page,
      limit: itemsPerPage
    });
    if (result && result.code === 0 && result.data) {
      offlineDownloadDialog.tasks = result.data.tasks || [];
      offlineDownloadDialog.totalTasks = result.data.total || 0;
    } else {
      throw new Error(result?.msg || '获取离线任务列表失败');
    }
  } catch (err) {
    offlineDownloadDialog.error = `获取任务失败: ${err.message || '未知错误'}`;
    console.error('获取离线任务失败:', err);
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
    const links = offlineDownloadDialog.links.split('\n').map(l => l.trim()).filter(Boolean);
    const result = await props.api.post(`plugin/${pluginId}/add_offline_task`, {
      links: links,
      path: offlineDownloadDialog.destPath || null,
    });
    if (result && result.code === 0) {
      actionMessage.value = result.msg || '离线任务添加成功';
      actionMessageType.value = 'success';
      // 缓存选择的路径
      if (offlineDownloadDialog.destPath && offlineDownloadDialog.destPath.trim()) {
        addPathToCache(offlineDownloadDialog.destPath);
        buildAvailablePaths(); // 更新可用路径列表
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
    console.error('添加离线任务失败:', err);
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

const getTaskStatusColor = (status) => {
  switch (status) {
    case 0: return 'info';
    case 1: return 'error';
    case 2: return 'success';
    case 3: return 'warning';
    default: return 'grey';
  }
};

const getParsedPaths = (pathString) => {
  if (!pathString) return [];
  try {
    const paths = pathString.split('\n').filter(line => line.trim() && line.includes('#'));
    return paths.map(path => {
      const parts = path.split('#');
      return { local: parts[0] || '', remote: parts[1] || '' };
    });
  } catch (e) {
    console.error('解析路径字符串失败:', e);
    return [];
  }
};

const getParsedPanTransferPaths = (pathString) => {
  if (!pathString) return [];
  try {
    const paths = pathString.split('\n').filter(line => line.trim());
    return paths.map(path => ({ path }));
  } catch (e) {
    console.error('解析网盘整理路径字符串失败:', e);
    return [];
  }
};

watch(() => props.initialConfig?.fuse_enabled, (enabled) => {
  if (enabled) {
    getFuseStatus();
  } else {
    fuseStatus.mounted = false;
    fuseStatus.mountpoint = null;
  }
});

watch(() => props.initialConfig, (newConfig) => {
  if (newConfig) {
    status.enabled = newConfig.enabled || false;
    status.has_client = Boolean(newConfig.cookies && newConfig.cookies.trim() !== '');
    if (newConfig.sync_del_enabled) {
      loadSyncDelHistory();
      // 清除旧的定时器
      if (syncDelHistoryRefreshTimer) {
        clearInterval(syncDelHistoryRefreshTimer);
      }
      // 设置定期刷新历史记录（每30秒刷新一次）
      syncDelHistoryRefreshTimer = setInterval(() => {
        if (props.initialConfig?.sync_del_enabled) {
          loadSyncDelHistory();
        }
      }, 30000);
    } else {
      syncDelHistory.value = [];
      // 清除定时器
      if (syncDelHistoryRefreshTimer) {
        clearInterval(syncDelHistoryRefreshTimer);
        syncDelHistoryRefreshTimer = null;
      }
    }
  }
}, { immediate: true });

// 监听对话框打开，重置分页
watch(() => syncDelHistoryDialog.show, (isOpen) => {
  if (isOpen) {
    syncDelHistoryPage.value = 1;
    loadSyncDelHistory();
  }
});

const loadSyncDelHistory = async () => {
  if (!props.initialConfig?.sync_del_enabled) {
    syncDelHistory.value = [];
    return;
  }
  syncDelHistoryLoading.value = true;
  try {
    const response = await props.api.get(
      `plugin/${pluginId}/get_sync_del_history?page=${syncDelHistoryPage.value}&limit=${syncDelHistoryLimit.value}`
    );
    if (response && response.code === 0 && response.data) {
      if (response.data.items && Array.isArray(response.data.items)) {
        syncDelHistory.value = response.data.items;
        syncDelHistoryTotal.value = response.data.total || 0;
      } else if (Array.isArray(response.data)) {
        // 兼容旧版本API（无分页）
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
    const response = await props.api.post(
      `plugin/${pluginId}/delete_sync_del_history`,
      {
        key: unique
      }
    );
    if (response && response.code === 0) {
      actionMessage.value = response.msg || '删除成功';
      actionMessageType.value = 'success';
      // 如果当前页删除后没有数据了，且不是第一页，则跳转到上一页
      if (syncDelHistory.value.length === 1 && syncDelHistoryPage.value > 1) {
        syncDelHistoryPage.value--;
      }
      await loadSyncDelHistory();
    } else {
      actionMessage.value = response?.msg || '删除失败';
      actionMessageType.value = 'error';
    }
  } catch (err) {
    console.error('删除同步删除历史失败:', err);
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
    const response = await props.api.post(
      `plugin/${pluginId}/delete_all_sync_del_history`
    );
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
    console.error('一键删除同步删除历史失败:', err);
    actionMessage.value = `删除失败: ${err.message || '未知错误'}`;
    actionMessageType.value = 'error';
  } finally {
    deletingAllHistory.value = false;
  }
};

onMounted(async () => {
  await getStatus();
  if (status.has_client && props.initialConfig?.cookies) {
    await fetchUserStorageStatus();
  } else {
    userInfo.loading = false;
    storageInfo.loading = false;
    if (!props.initialConfig?.cookies) {
      userInfo.error = "请先配置115 Cookie。";
      storageInfo.error = "请先配置115 Cookie。";
    } else if (!status.has_client) {
      userInfo.error = "115客户端未连接或Cookie无效。";
      storageInfo.error = "115客户端未连接或Cookie无效。";
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
    // 设置定期刷新历史记录（每30秒刷新一次）
    syncDelHistoryRefreshTimer = setInterval(() => {
      if (props.initialConfig?.sync_del_enabled) {
        loadSyncDelHistory();
      }
    }, 30000);
  }
});

// 清理定时器
onBeforeUnmount(() => {
  if (syncDelHistoryRefreshTimer) {
    clearInterval(syncDelHistoryRefreshTimer);
    syncDelHistoryRefreshTimer = null;
  }
});

async function fetchUserStorageStatus() {
  userInfo.loading = true;
  userInfo.error = null;
  storageInfo.loading = true;
  storageInfo.error = null;
  try {
    // 此接口未包裹在 ApiResponse 中，保持不变
    const response = await props.api.get(`plugin/${pluginId}/user_storage_status`);
    if (response && response.success) {
      if (response.user_info) {
        Object.assign(userInfo, response.user_info);
      } else {
        userInfo.error = '未能获取有效的用户信息。';
      }
      if (response.storage_info) {
        Object.assign(storageInfo, response.storage_info);
      } else {
        storageInfo.error = '未能获取有效的存储空间信息。';
      }
    } else {
      const errMsg = response?.error_message || '获取用户和存储信息失败。';
      userInfo.error = errMsg;
      storageInfo.error = errMsg;
      if (errMsg.includes("Cookie") || errMsg.includes("未配置")) {
        status.has_client = false;
      }
    }
  } catch (err) {
    console.error('获取用户/存储状态失败:', err);
    const Mgs = `请求用户/存储状态时出错: ${err.message || '未知网络错误'}`;
    userInfo.error = Mgs;
    storageInfo.error = Mgs;
  } finally {
    userInfo.loading = false;
    storageInfo.loading = false;
  }
}
</script>

<style scoped>
/* ============================================
   页面组件样式 - 镜面效果 + 蓝粉白配色
   ============================================ */

.command-hint {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-left: 3px solid rgb(var(--v-theme-info));
  border-radius: 6px;
  background: rgba(var(--v-theme-info), 0.06);
}

.mp-config-help {
  padding: 10px 12px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 6px;
  background: rgba(var(--v-theme-surface-variant), 0.2);
}

.mp-config-help summary {
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 500;
}

.mp-config-help[open] summary {
  margin-bottom: 10px;
}

/* 动画关键帧定义 */
@keyframes cardEnter {
  0% {
    opacity: 0;
    transform: translateY(20px) scale(0.95);
  }

  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes listItemEnter {
  0% {
    opacity: 0;
    transform: translateX(-15px);
  }

  100% {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes buttonPulse {

  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(91, 207, 250, 0.4);
  }

  50% {
    box-shadow: 0 0 0 8px rgba(91, 207, 250, 0);
  }
}

@keyframes iconBounce {

  0%,
  100% {
    transform: scale(1);
  }

  50% {
    transform: scale(1.2);
  }
}

@keyframes statusPulse {

  0%,
  100% {
    transform: scale(1);
    filter: drop-shadow(0 0 0 rgba(91, 207, 250, 0));
  }

  50% {
    transform: scale(1.05);
    filter: drop-shadow(0 0 8px rgba(91, 207, 250, 0.4));
  }
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

.plugin-page {
  --p115-surface-opacity: 0.92;
  --p115-raised-opacity: 0.97;
  --p115-muted-opacity: 0.06;
  --p115-control-opacity: 0.72;
  --p115-border-opacity: var(--v-border-opacity, 0.12);
  --p115-surface-blur: 18px;
  --p115-soft-shadow:
    0 8px 28px rgba(91, 207, 250, 0.16),
    0 2px 8px rgba(245, 171, 185, 0.1);
  --p115-raised-shadow:
    0 12px 32px rgba(91, 207, 250, 0.24),
    0 4px 12px rgba(245, 171, 185, 0.16);
  padding: 12px;
  width: 100%;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
}

:global(html[data-theme='transparent']) .plugin-page,
:global(.v-theme--transparent) .plugin-page {
  --p115-surface-opacity: var(--transparent-opacity, 0.3);
  --p115-raised-opacity: var(--transparent-opacity-heavy, 0.5);
  --p115-muted-opacity: var(--transparent-opacity-light, 0.2);
  --p115-control-opacity: var(--transparent-opacity-light, 0.2);
  --p115-surface-blur: var(--transparent-blur, 10px);
  --p115-soft-shadow:
    0 8px 28px rgba(91, 207, 250, 0.18),
    0 2px 8px rgba(245, 171, 185, 0.12);
  --p115-raised-shadow:
    0 12px 36px rgba(91, 207, 250, 0.26),
    0 4px 12px rgba(245, 171, 185, 0.18);
}

:global(html[data-theme='transparent']) {
  --p115-surface-opacity: var(--transparent-opacity, 0.3);
  --p115-raised-opacity: var(--transparent-opacity-heavy, 0.5);
  --p115-muted-opacity: var(--transparent-opacity-light, 0.2);
  --p115-control-opacity: var(--transparent-opacity-light, 0.2);
  --p115-surface-blur: var(--transparent-blur, 10px);
  --p115-soft-shadow:
    0 8px 28px rgba(91, 207, 250, 0.18),
    0 2px 8px rgba(245, 171, 185, 0.12);
  --p115-raised-shadow:
    0 12px 36px rgba(91, 207, 250, 0.26),
    0 4px 12px rgba(245, 171, 185, 0.18);
}

.plugin-page :deep(.v-card) {
  border-radius: 20px !important;
  overflow: hidden;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  background: rgba(var(--v-theme-surface), var(--p115-surface-opacity)) !important;
  backdrop-filter: blur(var(--p115-surface-blur)) saturate(130%) !important;
  -webkit-backdrop-filter: blur(var(--p115-surface-blur)) saturate(130%) !important;
  box-shadow: var(--p115-soft-shadow) !important;
  border: 1px solid rgba(91, 207, 250, 0.2) !important;
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  animation: cardEnter 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
  will-change: transform, box-shadow;
}

/* 主卡片高度设置：桌面用 vh，移动端填满父级由内部滚动 */
.page-main-card {
  max-height: 85vh;
}

@media (max-width: 768px) {
  .page-main-card {
    flex: 1;
    min-height: 0;
    max-height: none;
    height: 100%;
  }
}

.config-card {
  border-radius: 16px !important;
  background: rgba(var(--v-theme-surface), var(--p115-raised-opacity)) !important;
  backdrop-filter: blur(var(--p115-surface-blur)) saturate(125%) !important;
  -webkit-backdrop-filter: blur(var(--p115-surface-blur)) saturate(125%) !important;
  border: 1px solid rgba(91, 207, 250, 0.18) !important;
  box-shadow: var(--p115-soft-shadow) !important;
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  margin-bottom: 16px !important;
  overflow: hidden;
  will-change: transform, box-shadow;
}

.config-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--p115-raised-shadow) !important;
  border-color: rgba(91, 207, 250, 0.5) !important;
  background: rgba(var(--v-theme-surface), var(--p115-raised-opacity)) !important;
}

/* 现代字体栈 */
:deep(.v-card-title),
:deep(.v-card-text),
:deep(.v-list-item-title),
:deep(.v-list-item-subtitle),
:deep(.v-alert),
:deep(.v-btn),
:deep(.text-caption),
:deep(.text-subtitle-1),
:deep(.text-body-1),
:deep(.text-body-2) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 标题字体优化 */
:deep(.v-card-title) {
  font-weight: 700 !important;
  font-size: 1.1rem !important;
  letter-spacing: -0.02em !important;
  line-height: 1.3 !important;
}

:deep(.text-subtitle-1) {
  font-weight: 600 !important;
  font-size: 1rem !important;
  letter-spacing: -0.01em !important;
  line-height: 1.4 !important;
}

:deep(.text-subtitle-2) {
  font-weight: 600 !important;
  font-size: 0.9rem !important;
  letter-spacing: 0 !important;
  line-height: 1.35 !important;
}

/* 正文字体优化 */
:deep(.text-body-1) {
  font-weight: 400 !important;
  font-size: 1rem !important;
  line-height: 1.6 !important;
  letter-spacing: 0 !important;
}

:deep(.text-body-2) {
  font-weight: 400 !important;
  font-size: 0.9rem !important;
  line-height: 1.5 !important;
  letter-spacing: 0 !important;
}

/* 小字字体优化 */
:deep(.text-caption) {
  font-weight: 400 !important;
  font-size: 0.8rem !important;
  line-height: 1.4 !important;
  letter-spacing: 0.01em !important;
}

/* 列表项字体优化 */
:deep(.v-list-item-title) {
  font-weight: 500 !important;
  font-size: 0.9rem !important;
  line-height: 1.4 !important;
}

:deep(.v-list-item-subtitle) {
  font-weight: 400 !important;
  font-size: 0.8rem !important;
  line-height: 1.4 !important;
  letter-spacing: 0.01em !important;
}

/* 按钮字体优化 */
:deep(.v-btn) {
  font-weight: 500 !important;
  font-size: 0.875rem !important;
  letter-spacing: 0.02em !important;
  text-transform: none !important;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  will-change: transform, box-shadow;
}

:deep(.v-btn:hover) {
  transform: translateY(-3px) scale(1.05);
  box-shadow: 0 8px 20px rgba(91, 207, 250, 0.35) !important;
}

:deep(.v-btn:active) {
  transform: scale(0.98) translateY(-1px);
  transition: all 0.1s ease !important;
}

/* 主要按钮脉冲效果 */
:deep(.v-btn.color-primary:not(:hover)) {
  animation: buttonPulse 2s ease-in-out infinite;
}

/* 图标动画优化 */
:deep(.v-icon) {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  will-change: transform;
}

:deep(.v-btn:hover .v-icon) {
  transform: scale(1.15) rotate(5deg);
}

/* 列表项动画优化 */
:deep(.v-list-item) {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  will-change: transform, background;
  opacity: 0;
  animation: listItemEnter 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}

:deep(.v-list-item:nth-child(1)) {
  animation-delay: 0.1s;
}

:deep(.v-list-item:nth-child(2)) {
  animation-delay: 0.15s;
}

:deep(.v-list-item:nth-child(3)) {
  animation-delay: 0.2s;
}

:deep(.v-list-item:nth-child(4)) {
  animation-delay: 0.25s;
}

:deep(.v-list-item:nth-child(5)) {
  animation-delay: 0.3s;
}

:deep(.v-list-item:nth-child(6)) {
  animation-delay: 0.35s;
}

:deep(.v-list-item:nth-child(7)) {
  animation-delay: 0.4s;
}

:deep(.v-list-item:nth-child(8)) {
  animation-delay: 0.45s;
}

:deep(.v-list-item:hover) {
  transform: translateX(6px);
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.15) 0%,
      rgba(245, 171, 185, 0.1) 100%) !important;
}

:deep(.v-list-item:hover .v-icon) {
  transform: scale(1.2);
}

/* 状态芯片动画 */
:deep(.v-chip) {
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  will-change: transform, box-shadow;
}

:deep(.v-chip:hover) {
  transform: scale(1.08) translateY(-2px);
  box-shadow: 0 4px 12px rgba(91, 207, 250, 0.25) !important;
}

/* 状态图标脉冲效果 */
:deep(.v-icon.text-success),
:deep(.v-icon.text-error) {
  animation: statusPulse 2s ease-in-out infinite;
}

/* 刷新按钮旋转动画 */
:deep(.v-btn[loading] .v-icon),
:deep(.icon-spin-animation) {
  animation: spin 1s linear infinite;
}

/* 进度条动画优化 */
:deep(.v-progress-linear) {
  transition: all 0.3s ease !important;
}

:deep(.v-progress-linear__determinate) {
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
}

/* 路径映射项动画 */
.path-mapping-item {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  will-change: transform, box-shadow;
}

.path-mapping-item:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(91, 207, 250, 0.15) !important;
}

/* 对话框动画优化 */
:deep(.v-dialog .v-overlay__content) {
  animation: cardEnter 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}

/* 警告框动画优化 */
:deep(.v-alert) {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
}

:deep(.v-alert:hover) {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(91, 207, 250, 0.2) !important;
}

/* 输入框动画优化 */
:deep(.v-field) {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
  will-change: box-shadow, border-color;
}

:deep(.v-field--focused) {
  box-shadow: 0 0 0 3px rgba(91, 207, 250, 0.2) !important;
}

/* 菜单动画优化 */
:deep(.v-menu .v-overlay__content) {
  animation: cardEnter 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}

/* 头像动画优化 */
:deep(.v-avatar) {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
}

:deep(.v-avatar:hover) {
  transform: scale(1.1);
  box-shadow: 0 4px 12px rgba(91, 207, 250, 0.3) !important;
}

/* 文字大小 */
:deep(.text-caption) {
  font-size: 0.8rem !important;
}

:deep(.text-body-2) {
  font-size: 0.85rem !important;
}

/* 美化卡片标题 - 蓝粉渐变镜面效果 */
.bg-primary-gradient {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 50%,
      rgba(255, 184, 201, 0.15) 100%) !important;
  backdrop-filter: blur(20px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.3) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4) !important;
}

.plugin-page :deep(.v-card-title) {
  border-radius: 12px 12px 0 0;
}

/* 美化芯片 - 镜面效果 */
:deep(.v-chip) {
  font-weight: 500;
  border-radius: 10px !important;
  background: rgba(255, 255, 255, 0.6) !important;
  backdrop-filter: blur(10px) !important;
  border: 1px solid rgba(255, 255, 255, 0.4) !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
  box-shadow:
    0 2px 6px rgba(91, 207, 250, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.4) !important;
}

:deep(.v-chip--selected),
:deep(.v-chip:hover) {
  transform: translateY(-2px) scale(1.05);
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.35),
    0 2px 6px rgba(245, 171, 185, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 100%) !important;
  backdrop-filter: blur(10px) !important;
  color: rgba(var(--v-theme-on-surface), 0.87) !important;
}

/* 暗色模式下的芯片选中状态 */
:deep(.v-theme--dark) .v-chip--selected,
:deep(.v-theme--dark) .v-chip:hover,
:deep([data-theme="dark"]) .v-chip--selected,
:deep([data-theme="dark"]) .v-chip:hover {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.35) 0%,
      rgba(245, 171, 185, 0.3) 100%) !important;
  color: rgba(255, 255, 255, 0.9) !important;
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.4),
    0 2px 6px rgba(245, 171, 185, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.2) !important;
}

:deep(.v-list-item) {
  min-height: 36px;
  /* More compact list items */
}

:deep(.v-list-item--density-default:not(.v-list-item--nav).v-list-item--one-line) {
  padding-inline-start: 12px !important;
  /* Reduced from 16px */
  padding-inline-end: 12px !important;
  /* Reduced from 16px */
}

/* Ensure py-0 on list items takes effect with Vuetify's defaults if used specifically */
.py-0 {
  padding-top: 0 !important;
  padding-bottom: 0 !important;
}

.my-0 {
  margin-top: 0 !important;
  margin-bottom: 0 !important;
}

/* Reduce margin for subtitles in path display if they have mt-1 */
.mt-1 {
  margin-top: 2px !important;
  /* Reduced from default 4px of Vuetify's mt-1 */
}

/* Reduce margin for subtitles in path display if they have mb-1 */
.mb-1 {
  margin-bottom: 2px !important;
  /* Reduced from default 4px of Vuetify's mb-1 */
}

.sticky-actions {
  position: sticky;
  bottom: 0;
  /* 动态适配暗色模式 */
  background: linear-gradient(to top,
      rgba(var(--v-theme-surface), 0.95) 0%,
      rgba(var(--v-theme-surface), 0.9) 100%) !important;
  backdrop-filter: blur(20px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
  z-index: 2;
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  border-radius: 0 0 20px 20px;
  box-shadow:
    0 -4px 16px rgba(91, 207, 250, 0.25),
    0 -2px 8px rgba(245, 171, 185, 0.2),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

/* 暗色模式下的特殊处理 */
:deep(.v-theme--dark) .sticky-actions,
:deep([data-theme="dark"]) .sticky-actions {
  background: linear-gradient(to top,
      rgba(var(--v-theme-surface), 0.95) 0%,
      rgba(var(--v-theme-surface), 0.9) 100%) !important;
  border-top: 1px solid rgba(var(--v-theme-on-surface), 0.2) !important;
  box-shadow:
    0 -4px 16px rgba(91, 207, 250, 0.3),
    0 -2px 8px rgba(245, 171, 185, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

/* 优化按钮样式 - 镜面效果 */
:deep(.v-btn) {
  border-radius: 12px !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
  font-weight: 500 !important;
  backdrop-filter: blur(10px) !important;
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.3) !important;
}

:deep(.v-btn:hover) {
  transform: translateY(-2px) scale(1.02);
  box-shadow:
    0 6px 16px rgba(91, 207, 250, 0.35),
    0 2px 8px rgba(245, 171, 185, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
}

:deep(.v-btn--variant-elevated),
:deep(.v-btn--variant-flat) {
  background: rgba(255, 255, 255, 0.7) !important;
  backdrop-filter: blur(10px) !important;
}

/* 优化警告框样式 - 镜面效果 */
:deep(.v-alert) {
  border-radius: 16px !important;
  border-left-width: 4px !important;
  background: rgba(255, 255, 255, 0.7) !important;
  backdrop-filter: blur(15px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(15px) saturate(180%) !important;
  border: 1px solid rgba(255, 255, 255, 0.3) !important;
  box-shadow:
    0 4px 12px rgba(91, 207, 250, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

/* 优化列表项样式 */
:deep(.v-list-item) {
  border-radius: 8px;
  margin: 2px 4px;
  transition: all 0.2s ease !important;
}

:deep(.v-list-item:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2) 0%,
      rgba(245, 171, 185, 0.15) 100%) !important;
  backdrop-filter: blur(10px) !important;
  transform: translateX(4px);
  box-shadow:
    0 2px 8px rgba(91, 207, 250, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.4) !important;
}

/* Colorful Switches */
:deep(.v-switch .v-selection-control--dirty .v-track) {
  opacity: 0.8 !important;
  /* Ensure high opacity for color visibility */
}

:deep(.v-switch .v-selection-control--dirty .v-selection-control__input > .v-icon) {
  color: white !important;
}

/* Primary Color Switch */
:deep(v-switch[color="primary"] .v-selection-control--dirty .v-track),
:deep(v-switch[color="primary"] .v-selection-control--dirty .v-switch__track) {
  /* track */
  background-color: rgb(var(--v-theme-primary)) !important;
  border-color: rgb(var(--v-theme-primary)) !important;
}

/* Success Color Switch */
:deep(v-switch[color="success"] .v-selection-control--dirty .v-track),
:deep(v-switch[color="success"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-success)) !important;
  border-color: rgb(var(--v-theme-success)) !important;
}

/* Info Color Switch */
:deep(v-switch[color="info"] .v-selection-control--dirty .v-track),
:deep(v-switch[color="info"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-info)) !important;
  border-color: rgb(var(--v-theme-info)) !important;
}

/* Warning Color Switch */
:deep(v-switch[color="warning"] .v-selection-control--dirty .v-track),
:deep(v-switch[color="warning"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-warning)) !important;
  border-color: rgb(var(--v-theme-warning)) !important;
}

/* Error Color Switch */
:deep(v-switch[color="error"] .v-selection-control--dirty .v-track),
:deep(v-switch[color="error"] .v-selection-control--dirty .v-switch__track) {
  background-color: rgb(var(--v-theme-error)) !important;
  border-color: rgb(var(--v-theme-error)) !important;
}

.icon-spin-animation {
  animation: spin 2s linear infinite;
}

@keyframes spin {
  0% {
    transform: rotate(0deg);
  }

  100% {
    transform: rotate(360deg);
  }
}

/* 手机端优化 - 保持镜面效果 */
@media (max-width: 768px) {
  .plugin-page {
    padding: 8px;
    width: 100%;
    max-width: 100vw;
    box-sizing: border-box;
  }

  /* 移动端减小圆角但保持镜面效果 */
  .plugin-page :deep(.v-card) {
    border-radius: 16px !important;
    backdrop-filter: blur(15px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(15px) saturate(180%) !important;
  }

  .config-card {
    border-radius: 14px !important;
    margin-bottom: 12px !important;
    backdrop-filter: blur(12px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(12px) saturate(180%) !important;
  }

  .plugin-page :deep(.v-card-title) {
    border-radius: 10px 10px 0 0;
    padding: 12px !important;
  }

  /* 优化触摸目标大小 */
  :deep(.v-btn) {
    min-height: 44px !important;
    min-width: 44px !important;
    padding: 8px 16px !important;
    font-size: 0.875rem !important;
  }

  :deep(.v-btn--icon) {
    min-width: 44px !important;
    min-height: 44px !important;
  }

  /* 优化列表项触摸区域 */
  :deep(.v-list-item) {
    min-height: 48px !important;
    padding: 8px 12px !important;
  }

  /* 优化输入框 */
  :deep(.v-field) {
    border-radius: 8px !important;
  }

  :deep(.v-text-field .v-field),
  :deep(.v-select .v-field),
  :deep(.v-textarea .v-field) {
    min-height: 48px !important;
  }

  /* 优化对话框在移动端 - 镜面效果 */
  :deep(.v-dialog > .v-card) {
    margin: 16px !important;
    max-height: calc(100vh - 32px) !important;
    border-radius: 20px !important;
    background: rgba(255, 255, 255, 0.85) !important;
    backdrop-filter: blur(25px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(25px) saturate(180%) !important;
    border: 1px solid rgba(255, 255, 255, 0.4) !important;
    box-shadow:
      0 12px 48px rgba(91, 207, 250, 0.3),
      0 4px 16px rgba(245, 171, 185, 0.25),
      inset 0 1px 0 rgba(255, 255, 255, 0.6) !important;
  }

  /* 离线下载表格优化 */
  :deep(.v-data-table) {
    font-size: 0.8rem;
  }

  :deep(.v-data-table .v-data-table__td) {
    padding: 10px 6px !important;
    min-height: 44px !important;
  }

  :deep(.v-data-table .v-data-table__th) {
    padding: 10px 6px !important;
    font-size: 0.75rem;
    min-height: 44px !important;
  }

  /* 防止表格在手机上的触摸滑动触发标签页切换 */
  :deep(.v-data-table) {
    touch-action: pan-x;
  }

  /* 禁用 v-window 的触摸滑动 */
  :deep(.v-window) {
    touch-action: pan-y !important;
  }

  :deep(.v-window__container) {
    touch-action: pan-y !important;
  }

  /* 优化进度条在手机上的显示 */
  :deep(.v-progress-linear) {
    height: 8px !important;
  }

  /* 优化芯片在手机上的显示 */
  :deep(.v-chip) {
    font-size: 0.75rem !important;
    height: 28px !important;
    padding: 0 10px !important;
    min-height: 28px !important;
  }

  /* 优化警告框 */
  :deep(.v-alert) {
    border-radius: 10px !important;
    padding: 12px !important;
  }

  /* 优化卡片间距 */
  :deep(.v-card-text) {
    padding: 12px !important;
  }

  /* 优化图标大小 */
  :deep(.v-icon) {
    font-size: 20px !important;
  }

  :deep(.v-icon--size-small) {
    font-size: 18px !important;
  }

  /* 同步删除历史对话框在移动端的滚动优化 */
  :deep(.sync-del-history-content) {
    max-height: calc(100vh - 120px) !important;
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch !important;
  }

  :deep(.sync-del-history-content .v-list) {
    max-height: none !important;
    overflow-y: visible !important;
  }
}

.dialog-title-surface,
.section-title-surface {
  color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity)) !important;
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.14),
      rgba(245, 171, 185, 0.1)),
    rgba(var(--v-theme-surface), var(--p115-surface-opacity)) !important;
  border-bottom: 1px solid rgba(91, 207, 250, 0.22);
}

.bg-primary-gradient {
  color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity)) !important;
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2),
      rgba(245, 171, 185, 0.16)),
    rgba(var(--v-theme-surface), var(--p115-surface-opacity)) !important;
  border-bottom-color: rgba(91, 207, 250, 0.24) !important;
  box-shadow: inset 0 1px 0 rgba(245, 171, 185, 0.12) !important;
}

.command-hint,
.mp-config-help {
  color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity));
  background: rgba(var(--v-theme-surface), var(--p115-control-opacity));
  border-color: rgba(91, 207, 250, 0.22);
  backdrop-filter: blur(var(--p115-surface-blur));
  -webkit-backdrop-filter: blur(var(--p115-surface-blur));
}

.command-hint {
  border-left-color: rgb(91, 207, 250);
}

.plugin-page :deep(.v-expansion-panel),
.plugin-page :deep(.v-list),
.plugin-page :deep(.v-table),
.plugin-page :deep(.v-data-table) {
  color: rgb(var(--v-theme-on-surface));
  background: rgba(var(--v-theme-surface), var(--p115-surface-opacity)) !important;
}

.plugin-page :deep(.v-field) {
  background: rgba(var(--v-theme-surface), var(--p115-control-opacity));
}

.plugin-page :deep(.v-field--focused) {
  box-shadow:
    0 0 0 3px rgba(91, 207, 250, 0.18),
    0 2px 8px rgba(245, 171, 185, 0.1) !important;
}

.plugin-page :deep(.v-chip) {
  color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity)) !important;
  background: rgba(var(--v-theme-surface), var(--p115-control-opacity)) !important;
  border-color: rgba(var(--v-border-color), var(--p115-border-opacity)) !important;
  box-shadow: none !important;
}

.plugin-page :deep(.v-chip--selected),
.plugin-page :deep(.v-chip:hover) {
  color: rgba(var(--v-theme-on-surface), var(--v-high-emphasis-opacity)) !important;
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2),
      rgba(245, 171, 185, 0.16)) !important;
  border-color: rgba(91, 207, 250, 0.36) !important;
  box-shadow: 0 4px 12px rgba(91, 207, 250, 0.18) !important;
}

.plugin-page :deep(.v-list-item:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.14),
      rgba(245, 171, 185, 0.1)) !important;
  box-shadow: inset 2px 0 0 rgba(91, 207, 250, 0.42) !important;
}

.plugin-page :deep(.v-btn) {
  box-shadow: none !important;
}

.plugin-page :deep(.v-btn:hover) {
  box-shadow:
    0 6px 16px rgba(91, 207, 250, 0.22),
    0 2px 8px rgba(245, 171, 185, 0.14) !important;
}

.plugin-page :deep(.v-btn--variant-elevated),
.plugin-page :deep(.v-btn--variant-flat) {
  background: rgba(var(--v-theme-surface), var(--p115-raised-opacity)) !important;
}

.plugin-page :deep(.v-alert) {
  background: rgba(var(--v-theme-surface), var(--p115-raised-opacity)) !important;
  border-color: rgba(91, 207, 250, 0.2) !important;
  border-inline-start: 3px solid currentColor !important;
  box-shadow: none !important;
}

.plugin-page :deep(.v-alert:hover) {
  box-shadow: var(--p115-soft-shadow) !important;
}

.sticky-actions {
  background: rgba(var(--v-theme-surface), var(--p115-raised-opacity)) !important;
  border-top-color: rgba(91, 207, 250, 0.22) !important;
  box-shadow:
    0 -8px 24px rgba(91, 207, 250, 0.16),
    0 -2px 8px rgba(245, 171, 185, 0.1) !important;
  backdrop-filter: blur(var(--p115-surface-blur)) saturate(130%) !important;
  -webkit-backdrop-filter: blur(var(--p115-surface-blur)) saturate(130%) !important;
}

@media (max-width: 768px) {
  .plugin-page :deep(.v-dialog > .v-card) {
    color: rgb(var(--v-theme-on-surface));
    background: rgba(var(--v-theme-surface), var(--p115-raised-opacity)) !important;
    border-color: rgba(var(--v-border-color), var(--p115-border-opacity)) !important;
    box-shadow: var(--p115-raised-shadow) !important;
  }
}

:global(html[data-theme='light']) .plugin-page :deep(.v-card) {
  background: rgba(255, 255, 255, 0.75) !important;
  border-color: rgba(255, 255, 255, 0.45) !important;
  box-shadow:
    0 8px 32px rgba(91, 207, 250, 0.2),
    0 2px 8px rgba(245, 171, 185, 0.15),
    inset 0 1px 0 rgba(255, 255, 255, 0.55) !important;
}

:global(html[data-theme='light']) .config-card {
  background: rgba(255, 255, 255, 0.7) !important;
  border-color: rgba(255, 255, 255, 0.5) !important;
  box-shadow:
    0 4px 16px rgba(91, 207, 250, 0.18),
    0 1px 4px rgba(245, 171, 185, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.55) !important;
}

:global(html[data-theme='light']) .config-card:hover {
  background: rgba(255, 255, 255, 0.82) !important;
  border-color: rgba(91, 207, 250, 0.5) !important;
  box-shadow:
    0 14px 36px rgba(91, 207, 250, 0.3),
    0 5px 14px rgba(245, 171, 185, 0.22) !important;
}

:global(html[data-theme='light']) .bg-primary-gradient,
:global(html[data-theme='light']) .dialog-title-surface {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25),
      rgba(245, 171, 185, 0.2) 55%,
      rgba(255, 184, 201, 0.15)) !important;
  border-bottom-color: rgba(255, 255, 255, 0.45) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
}

:global(html[data-theme='light']) .section-title-surface {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.12),
      rgba(245, 171, 185, 0.09)),
    rgba(255, 255, 255, 0.62) !important;
  border-bottom-color: rgba(91, 207, 250, 0.18) !important;
}

:global(html[data-theme='light']) .command-hint,
:global(html[data-theme='light']) .mp-config-help {
  background: rgba(255, 255, 255, 0.66);
  border-color: rgba(91, 207, 250, 0.22);
}

:global(html[data-theme='light']) .command-hint {
  border-left-color: rgb(91, 207, 250);
}

:global(html[data-theme='light']) .plugin-page :deep(.v-expansion-panel),
:global(html[data-theme='light']) .plugin-page :deep(.v-list),
:global(html[data-theme='light']) .plugin-page :deep(.v-table),
:global(html[data-theme='light']) .plugin-page :deep(.v-data-table) {
  background: rgba(255, 255, 255, 0.68) !important;
}

:global(html[data-theme='light']) .plugin-page :deep(.v-field) {
  background: rgba(255, 255, 255, 0.58);
}

:global(html[data-theme='light']) .plugin-page :deep(.v-field--focused) {
  box-shadow: 0 0 0 3px rgba(91, 207, 250, 0.2) !important;
}

:global(html[data-theme='light']) .plugin-page :deep(.v-chip) {
  background: rgba(255, 255, 255, 0.62) !important;
  border-color: rgba(255, 255, 255, 0.48) !important;
  box-shadow:
    0 2px 6px rgba(91, 207, 250, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.45) !important;
}

:global(html[data-theme='light']) .plugin-page :deep(.v-chip--selected),
:global(html[data-theme='light']) .plugin-page :deep(.v-chip:hover) {
  color: rgba(var(--v-theme-on-surface), 0.87) !important;
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25),
      rgba(245, 171, 185, 0.2)) !important;
  border-color: rgba(91, 207, 250, 0.32) !important;
  box-shadow: 0 4px 12px rgba(91, 207, 250, 0.25) !important;
}

:global(html[data-theme='light']) .plugin-page :deep(.v-list-item:hover) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.16),
      rgba(245, 171, 185, 0.11)) !important;
}

:global(html[data-theme='light']) .plugin-page :deep(.v-btn:hover) {
  box-shadow:
    0 6px 16px rgba(91, 207, 250, 0.3),
    0 2px 8px rgba(245, 171, 185, 0.24) !important;
}

:global(html[data-theme='light']) .plugin-page :deep(.v-btn--variant-elevated),
:global(html[data-theme='light']) .plugin-page :deep(.v-btn--variant-flat),
:global(html[data-theme='light']) .plugin-page :deep(.v-alert) {
  background: rgba(255, 255, 255, 0.7) !important;
}

:global(html[data-theme='light']) .sticky-actions {
  background: rgba(255, 255, 255, 0.9) !important;
  border-top-color: rgba(91, 207, 250, 0.2) !important;
  box-shadow:
    0 -4px 16px rgba(91, 207, 250, 0.22),
    0 -2px 8px rgba(245, 171, 185, 0.16) !important;
}

@media (max-width: 768px) {
  :global(html[data-theme='light']) .plugin-page :deep(.v-dialog > .v-card) {
    background: rgba(255, 255, 255, 0.86) !important;
    border-color: rgba(255, 255, 255, 0.5) !important;
    box-shadow:
      0 12px 48px rgba(91, 207, 250, 0.28),
      0 4px 16px rgba(245, 171, 185, 0.22) !important;
  }
}
</style>
