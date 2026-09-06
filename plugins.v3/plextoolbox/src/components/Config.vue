<template>
  <div class="ptb-config">
    <VCard flat class="ptb-card">
      <VCardItem class="ptb-header">
        <template #prepend>
          <VAvatar color="primary" variant="tonal" size="44" rounded="lg"><VIcon icon="mdi-plex" size="24" /></VAvatar>
        </template>
        <VCardTitle class="text-h6 ptb-header-title">PLEX 工具箱</VCardTitle>
        <VCardSubtitle class="text-caption ptb-header-subtitle">{{ currentTab.desc }}</VCardSubtitle>
        <template #append>
          <div class="d-flex align-center ga-2">
            <div v-if="changedCount" class="ptb-dirty-hint"><VIcon icon="mdi-circle-medium" color="warning" size="18" /><span class="text-caption text-warning">{{ changedCount }} 项待保存</span></div>
            <VBtn v-if="changedCount" color="primary" variant="flat" size="small" prepend-icon="mdi-content-save" rounded="lg" :loading="saving" @click="saveConfig">保存修改</VBtn>
            <VBtn icon="mdi-close" variant="text" size="small" @click="emit('close')" />
          </div>
        </template>
      </VCardItem>
      <VDivider />

      <div class="ptb-body">
        <nav class="ptb-nav">
          <VList density="comfortable" nav class="py-2">
            <VListItem v-for="item in tabs" :key="item.key" :active="activeTab === item.key" color="primary" rounded="lg" class="ptb-nav-item" @click="activeTab = item.key">
              <template #prepend><VIcon :icon="item.icon" /></template>
              <VListItemTitle>{{ item.title }}</VListItemTitle>
              <template v-if="item.key === 'records' && history.length" #append><VChip size="x-small" variant="tonal">{{ history.length }}</VChip></template>
            </VListItem>
          </VList>
        </nav>

        <section class="ptb-content">
          <div class="ptb-mobile-tabbar">
            <div class="ptb-mobile-tabinfo"><div class="font-weight-medium">{{ currentTab.title }}</div><div class="text-caption text-medium-emphasis">{{ currentTab.desc }}</div></div>
            <VBtn icon="mdi-menu-down" variant="tonal" size="small" @click="mobileTabSheet = true" />
          </div>

          <VAlert v-if="error" type="error" variant="tonal" density="compact" class="ptb-error-alert ma-3 mb-0 text-caption" closable @click:close="error = ''">{{ error }}</VAlert>

          <div class="ptb-workspace">
            <div class="ptb-window">
              <div v-show="activeTab === 'proxy'" class="ptb-pane">
                <div class="ptb-section-title">302 反向代理</div>
                <VRow>
                  <VCol cols="12"><VSwitch v-model="config.proxy_enabled" color="primary" hide-details inset label="启用 302 反向代理" /></VCol>
                  <VCol cols="12" md="8"><VTextField v-model="config.plex_host" label="Plex 服务器地址" placeholder="http://192.168.0.122:32400" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="4"><VTextField v-model="config.plex_token" label="X-Plex-Token" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="6"><VTextField v-model="config.host" label="代理监听地址" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="6"><VTextField v-model.number="config.port" type="number" label="代理监听端口" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12"><VSwitch v-model="config.force_direct_play" color="primary" hide-details inset label="强制 DirectPlay（避免转码使直链失效）" /></VCol>
                  <VCol cols="12"><VTextarea v-model="config.pin_rules" label="顶置路径规则（每行：路径前缀 => 目标URL）" variant="outlined" density="compact" rows="3" hide-details="auto" /></VCol>
                </VRow>
              </div>

              <div v-show="activeTab === 'mediainfo'" class="ptb-pane">
                <div class="ptb-section-title">STRM 媒体流信息补全</div>
                <VAlert type="info" variant="tonal" density="compact" class="mb-3 text-caption">点击播放时先补全当前条目及设置的后续集，最多等待 3 秒后自动放行播放。需先在 Plex 主机部署 helper 写库服务；没有 Emby 时可直接用 ffprobe 探测 STRM 内的 302 直链。<a :href="helperDocUrl" target="_blank" rel="noopener" class="ptb-doc-link">查看部署说明</a></VAlert>
                <VRow>
                  <VCol cols="12"><VSwitch v-model="config.mediainfo_enabled" color="primary" hide-details inset label="启用媒体信息补全" /></VCol>
                  <VCol cols="12" md="8"><VTextField v-model="config.plex_direct_host" label="Plex 直连地址（写库/枚举用）" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="4"><VBtn color="info" variant="tonal" size="small" :loading="checking" prepend-icon="mdi-lan-connect" @click="checkHelper">检查 helper</VBtn></VCol>
                  <VCol cols="12" md="8"><VTextField v-model="config.helper_url" label="helper 地址" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="4"><VTextField v-model="config.helper_token" label="helper Token" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="6"><VSwitch v-model="config.use_emby" color="primary" hide-details inset label="数据源 Emby MediaStreams" /></VCol>
                  <VCol cols="12" md="8"><VTextField v-model="config.emby_url" label="Emby 地址" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="4"><VTextField v-model="config.emby_apikey" label="Emby API Key" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12"><VSwitch v-model="config.use_ffprobe" color="primary" hide-details inset label="启用 ffprobe（无 Emby 或 Emby 未命中时读取 STRM 302 直链）" /></VCol>
                  <VCol cols="12" md="8"><VTextField v-model="config.ffprobe_path_map" label="Plex 路径 → MoviePilot 容器路径映射" placeholder="/Volumes/data=/media" hint="每行一条，支持 =、=> 或分号分隔；Plex 主机路径在左，MP 容器路径在右" persistent-hint variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="4"><VTextField v-model.number="config.ffprobe_timeout" type="number" min="1" max="300" label="ffprobe 超时（秒）" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="8"><VSelect v-model="selectedSections" :items="sectionOptions" item-title="title" item-value="value" label="要补全的 Plex 媒体库" variant="outlined" density="compact" multiple chips closable-chips hide-details="auto" :loading="loadingSections"><template #append-inner><VBtn icon="mdi-refresh" size="x-small" variant="text" @click.stop="loadSections" /></template></VSelect></VCol>
                  <VCol cols="12" md="4"><VTextField v-model.number="config.concurrency" type="number" min="1" max="10" label="探测并发数" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="6"><VSwitch v-model="config.only_missing" color="primary" hide-details inset label="仅处理缺失媒体信息的条目" /></VCol>
                  <VCol cols="12" md="6"><VSwitch v-model="config.overwrite_streams" color="primary" hide-details inset label="写入前清空旧流" /></VCol>
                  <VCol cols="12" md="6"><VSwitch v-model="config.webhook_enabled" color="primary" hide-details inset label="启用 Plex Webhook 触发" /></VCol>
                  <VCol cols="12" md="6"><VTextField v-model.number="config.dedup_window" type="number" min="0" label="播前同条目去重窗口（秒）" variant="outlined" density="compact" hide-details="auto" /></VCol>
                  <VCol cols="12" md="6"><VTextField v-model.number="config.forward_episodes" type="number" min="0" label="剧集向后预取集数" variant="outlined" density="compact" hide-details="auto" /></VCol>
                </VRow>
                <VAlert v-if="helperInfo" type="success" variant="tonal" density="compact" class="mt-2 text-caption">helper 正常，数据库：{{ helperInfo }}</VAlert>
              </div>

              <div v-show="activeTab === 'records'" class="ptb-pane">
                <div class="d-flex align-center flex-wrap ga-1 mb-3"><div class="ptb-section-title mb-0">补全记录</div><VSpacer /><VBtn icon="mdi-refresh" variant="text" size="small" :loading="loadingRuntime" @click="loadRuntimeData" /></div>
                <div class="d-flex align-center mb-2"><div class="ptb-block-title">最近一次补全</div><VSpacer /><VBtn v-if="lastPlay" color="grey" variant="text" size="x-small" prepend-icon="mdi-broom" :loading="clearing === 'last'" @click="clearData('last_play_result')">清理</VBtn></div>
                <template v-if="lastPlay">
                  <div v-if="lastPlay.label" class="text-body-2 font-weight-medium mb-2">{{ lastPlay.label }}</div>
                  <div class="ptb-stat-grid mb-3"><StatCard label="本次条目" :value="lastPlay.strm_parts" /><StatCard label="已解析" :value="lastPlay.resolved" /><StatCard label="Emby 命中" :value="lastPlay.emby_hits" /><StatCard label="ffprobe 命中" :value="lastPlay.ffprobe_hits" /><StatCard label="写入成功" :value="lastPlay.written_ok" /><StatCard label="写入失败" :value="lastPlay.write_failed" /></div>
                  <VTable v-if="lastPlay.items?.length" density="compact" class="ptb-history"><thead><tr><th>条目</th><th>状态</th></tr></thead><tbody><tr v-for="(item, index) in lastPlay.items" :key="index"><td class="text-caption">{{ item.label || ('part ' + item.part_id) }}</td><td><VChip :color="statusColor(item.status)" size="x-small" variant="tonal">{{ statusLabel(item.status) }}</VChip><span v-if="item.error" class="text-caption text-error ml-2">{{ item.error }}</span></td></tr></tbody></VTable>
                </template>
                <VAlert v-else type="info" variant="tonal" density="compact" class="text-caption">暂无补全记录。</VAlert>
                <VAlert v-if="lastPlay?.helper_busy" type="warning" variant="tonal" density="compact" class="mt-3 text-caption">Plex 当前繁忙，本次未写入。</VAlert>
                <VDivider class="my-4" />
                <div class="d-flex align-center mb-2"><div class="ptb-block-title">补全历史（最近 {{ history.length }} 条）</div><VSpacer /><VBtn v-if="history.length" color="grey" variant="text" size="x-small" prepend-icon="mdi-broom" :loading="clearing === 'history'" @click="clearData('play_history')">清空历史</VBtn></div>
                <VTable v-if="history.length" density="compact" class="ptb-history"><thead><tr><th>时间</th><th>条目</th><th>结果</th></tr></thead><tbody><template v-for="(row, index) in history" :key="index"><tr class="ptb-row" @click="expanded = expanded === index ? -1 : index"><td>{{ fmtTime(row.ts || row.time || row.created_at) }}</td><td>{{ row.label || '-' }}</td><td>{{ row.written_ok || 0 }} 成功 / {{ row.write_failed || 0 }} 失败</td></tr><tr v-if="expanded === index"><td colspan="3" class="ptb-detail-cell"><div v-for="(item, itemIndex) in row.items || []" :key="itemIndex" class="py-1"><VChip :color="statusColor(item.status)" size="x-small" variant="tonal">{{ statusLabel(item.status) }}</VChip><span class="text-caption ml-2">{{ item.label || item.part_id }}</span></div></td></tr></template></tbody></VTable>
                <VAlert v-else type="info" variant="tonal" density="compact" class="text-caption">暂无历史记录。</VAlert>
              </div>

              <div v-show="activeTab === 'matching'" class="ptb-pane">
                <div class="ptb-section-title">目录匹配</div>
                <VAlert type="info" variant="tonal" density="compact" class="mb-3 text-caption">取消匹配后，条目会按当前 NFO 代理重读。建议先预览影响。</VAlert>
                <TargetFields />
                <div class="d-flex ga-2 flex-wrap mt-4"><VBtn color="info" variant="tonal" size="small" :loading="busyKey === 'unmatch_preview'" :disabled="!!busyKey" prepend-icon="mdi-magnify" @click="doUnmatch(true)">预览影响</VBtn><VBtn color="warning" variant="flat" size="small" :loading="busyKey === 'unmatch_run'" :disabled="!!busyKey" prepend-icon="mdi-link-off" @click="doUnmatch(false)">执行取消匹配</VBtn></div>
                <VAlert v-if="matchingResult" :type="matchingResult.type" variant="tonal" density="compact" class="mt-4 text-caption" style="white-space:pre-wrap">{{ matchingResult.text }}</VAlert>
              </div>

              <div v-show="activeTab === 'scraping'" class="ptb-pane">
                <div class="ptb-section-title">刮削与海报</div>
                <VAlert type="info" variant="tonal" density="compact" class="mb-3 text-caption">扫描缺封面条目并交给 MoviePilot 生成 NFO/封面，或精准补全缺失 poster.jpg。</VAlert>
                <TargetFields />
                <div class="ptb-subsection-title mt-4">缺封面刮削</div><div class="d-flex ga-2 flex-wrap"><VBtn color="info" variant="tonal" size="small" :loading="busyKey === 'scan_cover'" :disabled="!!busyKey" prepend-icon="mdi-image-off-outline" @click="doScanCover">扫描缺封面</VBtn><VBtn color="info" variant="tonal" size="small" :loading="busyKey === 'scrape_preview'" :disabled="!!busyKey" prepend-icon="mdi-magnify" @click="doScrape(true)">预览刮削目录</VBtn><VBtn color="success" variant="flat" size="small" :loading="busyKey === 'scrape_run'" :disabled="!!busyKey" prepend-icon="mdi-auto-fix" @click="doScrape(false)">执行刮削</VBtn></div>
                <VDivider class="my-4" /><div class="ptb-subsection-title">缺 poster.jpg 精准补全</div><div class="d-flex ga-2 flex-wrap"><VBtn color="info" variant="tonal" size="small" :loading="busyKey === 'poster_preview'" :disabled="!!busyKey" prepend-icon="mdi-magnify" @click="doFixPoster(true)">预览缺 poster</VBtn><VBtn color="success" variant="flat" size="small" :loading="busyKey === 'poster_run'" :disabled="!!busyKey" prepend-icon="mdi-image-plus" @click="doFixPoster(false)">执行补全</VBtn></div>
                <VAlert v-if="scrapingResult" :type="scrapingResult.type" variant="tonal" density="compact" class="mt-4 text-caption" style="white-space:pre-wrap">{{ scrapingResult.text }}</VAlert>
              </div>

              <div v-show="activeTab === 'merge'" class="ptb-pane">
                <div class="ptb-section-title">合并重复条目</div>
                <VAlert type="info" variant="tonal" density="compact" class="mb-3 text-caption">扫描 Plex 全部剧集/电影库中 tmdb id 相同的重复条目，合并为一个（保留集数最多的条目作主）。</VAlert>
                <div class="d-flex ga-2 flex-wrap mb-3">
                  <VBtn color="info" variant="tonal" size="small" :loading="busyKey === 'merge_scan'" :disabled="!!busyKey" prepend-icon="mdi-magnify" @click="doMergeScan">扫描重复</VBtn>
                  <VBtn v-if="mergeGroups.length" color="success" variant="flat" size="small" :loading="busyKey === 'merge_run'" :disabled="!!busyKey" prepend-icon="mdi-call-merge" @click="doMergeExecute">合并全部（{{ mergeGroups.length }} 组）</VBtn>
                </div>
                <template v-if="mergeGroups.length">
                  <div class="text-caption text-medium-emphasis mb-2">共 {{ mergeGroups.length }} 组重复</div>
                  <VTable density="compact" class="ptb-history">
                    <thead><tr><th>剧集 / 电影</th><th>TMDB</th><th>重复条目</th></tr></thead>
                    <tbody>
                      <tr v-for="(group, gi) in mergeGroups" :key="gi">
                        <td class="text-caption">{{ group.title }}</td>
                        <td class="text-caption">{{ group.guid_id }}</td>
                        <td class="text-caption">
                          <div v-for="(item, ii) in group.items" :key="ii" :class="{ 'font-weight-bold': ii === 0 }">
                            [{{ item.section_title }}] {{ item.title }}（{{ item.year }}）— {{ item.leaf_count }} 集
                          </div>
                        </td>
                      </tr>
                    </tbody>
                  </VTable>
                </template>
                <VAlert v-else-if="mergeScanned" type="success" variant="tonal" density="compact" class="mt-2 text-caption">未发现重复条目。</VAlert>
                <VAlert v-if="mergeResult" :type="mergeResult.type" variant="tonal" density="compact" class="mt-4 text-caption" style="white-space:pre-wrap">{{ mergeResult.text }}</VAlert>
              </div>
            </div>

            <aside class="ptb-dashboard" aria-label="运行表盘">
              <section><div class="ptb-dashboard-title"><VIcon icon="mdi-clock-outline" color="primary" size="20" />运行节奏</div><DashboardRow icon="mdi-motion-play-outline" label="播前补全" :value="triggerText" /><DashboardRow icon="mdi-skip-forward-outline" label="播前追加" :value="`后 ${config.forward_episodes || 0} 集`" /><DashboardRow icon="mdi-timer-outline" label="去重窗口" :value="`${config.dedup_window || 0} 秒`" /><DashboardRow icon="mdi-heart-pulse" label="Helper 检查" value="每 5 分钟" /></section>
              <VDivider class="my-3" />
              <section><div class="ptb-dashboard-title"><VIcon icon="mdi-chart-box-outline" color="primary" size="20" />运行概况</div><DashboardRow icon="mdi-swap-horizontal-bold" label="代理服务" :value="status.proxy_running ? '运行中' : '未运行'" /><DashboardRow icon="mdi-lan-connect" label="Helper" :value="helperStatusText" /><DashboardRow icon="mdi-database-search-outline" label="媒体数据源" :value="config.use_emby && config.emby_url && config.emby_apikey && config.use_ffprobe ? 'Emby → ffprobe' : (config.use_emby && config.emby_url && config.emby_apikey ? 'Emby' : (config.use_ffprobe ? 'ffprobe' : '未启用'))" /><DashboardRow icon="mdi-history" label="最近补全" :value="lastRunText" /><DashboardRow icon="mdi-database-check-outline" label="最近写入" :value="lastWriteText" /><DashboardRow icon="mdi-folder-multiple-outline" label="补全媒体库" :value="`${selectedSections.length} 个`" /></section>
            </aside>
          </div>

        </section>
      </div>
    </VCard>

    <VBottomSheet v-model="mobileTabSheet"><VCard><VCardTitle class="text-subtitle-1">选择功能</VCardTitle><VList nav><VListItem v-for="item in tabs" :key="item.key" :active="activeTab === item.key" :title="item.title" :subtitle="item.desc" @click="activeTab = item.key; mobileTabSheet = false"><template #prepend><VIcon :icon="item.icon" /></template></VListItem></VList></VCard></VBottomSheet>
    <VSnackbar v-model="saveSnackbar" color="success" location="top" :timeout="2200">{{ saveMessage }}</VSnackbar>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref, resolveComponent, watch } from 'vue'
import { getPluginApi, postPluginApi } from './api.js'

const props = defineProps({ initialConfig: { type: Object, default: () => ({}) }, api: { type: [Object, Function], default: null } })
const emit = defineEmits(['save', 'close', 'layout'])
const layoutRequest = { maxWidth: '70rem' }
emit('layout', layoutRequest)
const VIconComponent = resolveComponent('VIcon')
const VSelectComponent = resolveComponent('VSelect')
const VTextFieldComponent = resolveComponent('VTextField')

const tabs = [
  { key: 'proxy', title: '反向代理', icon: 'mdi-swap-horizontal-bold', desc: 'Plex 播放流 302 直链跳转' },
  { key: 'mediainfo', title: '媒体信息补全', icon: 'mdi-information-outline', desc: '为 STRM 条目补全媒体流信息' },
  { key: 'records', title: '补全记录', icon: 'mdi-history', desc: '最近一次补全与历史执行记录' },
  { key: 'matching', title: '目录匹配', icon: 'mdi-link-variant-off', desc: '预览并执行取消匹配重读 NFO' },
  { key: 'scraping', title: '刮削与海报', icon: 'mdi-image-search-outline', desc: '缺封面扫描、刮削和 poster 补全' },
  { key: 'merge', title: '合并重复', icon: 'mdi-call-merge', desc: '扫描并合并 tmdb id 相同的重复条目' },
]
const activeTab = ref('proxy')
const currentTab = computed(() => tabs.find(item => item.key === activeTab.value) || tabs[0])
const mobileTabSheet = ref(false)
const error = ref('')
const checking = ref(false)
const loadingSections = ref(false)
const loadingRuntime = ref(false)
const saving = ref(false)
const saveMessage = ref('')
const saveSnackbar = ref(false)
const helperInfo = ref('')
const sectionOptions = ref([])
const status = ref({})
const lastPlay = ref(null)
const history = ref([])
const expanded = ref(-1)
const clearing = ref('')
const scrapeSection = ref('')
const scrapeLimit = ref(0)
const busyKey = ref('')
const matchingResult = ref(null)
const scrapingResult = ref(null)
const mergeGroups = ref([])
const mergeScanned = ref(false)
const mergeResult = ref(null)

const helperDocUrl = 'https://github.com/ranzhigg/MoviePilot-Plugins/blob/main/plugins.v3/plextoolbox/helper/README.md'
const defaults = { enabled: false, proxy_enabled: false, plex_host: '', plex_token: '', host: '0.0.0.0', port: 32401, pin_rules: '', force_direct_play: true, mediainfo_enabled: false, plex_direct_host: '', helper_url: '', helper_token: '', emby_url: '', emby_apikey: '', use_emby: true, use_ffprobe: true, ffprobe_path_map: '/Volumes/data=/media', ffprobe_timeout: 40, overwrite_streams: true, only_missing: true, concurrency: 3, sections: '', webhook_enabled: false, dedup_window: 300, forward_episodes: 5 }
const config = reactive({ ...defaults, ...props.initialConfig })
const savedBaseline = ref(JSON.parse(JSON.stringify(defaults)))

watch(() => props.initialConfig, value => { if (!value || typeof value !== 'object' || !Object.keys(value).length) return; Object.assign(config, value); snapshotBaseline() }, { deep: true })
watch(activeTab, () => emit('layout', layoutRequest))

const selectedSections = computed({ get: () => config.sections ? String(config.sections).split(',').map(item => item.trim()).filter(Boolean) : [], set: value => { config.sections = (value || []).join(',') } })
function normalizeValue(value) { if (Array.isArray(value)) return JSON.stringify([...value].sort()); if (value === undefined || value === null) return ''; return String(value) }
const changedCount = computed(() => Object.keys(defaults).filter(key => normalizeValue(config[key]) !== normalizeValue(savedBaseline.value[key])).length)
const triggerText = computed(() => !config.mediainfo_enabled ? '未启用' : '当前条目 + 后续集')
const helperStatusText = computed(() => { if (helperInfo.value || status.value.helper_health_ok === true) return '正常'; if (status.value.helper_health_ok === false) return `异常（连续 ${status.value.helper_health_failures || 1} 次）`; return config.helper_url ? '等待检查' : '未配置' })
const lastRunText = computed(() => lastPlay.value ? fmtTime(lastPlay.value.ts || lastPlay.value.time || lastPlay.value.created_at) : '暂无')
const lastWriteText = computed(() => lastPlay.value ? `${lastPlay.value.written_ok || 0} 成功 / ${lastPlay.value.write_failed || 0} 失败` : '暂无')

const DashboardRow = defineComponent({ props: { icon: String, label: String, value: [String, Number] }, setup(rowProps) { return () => h('div', { class: 'ptb-dashboard-row' }, [h(VIconComponent, { icon: rowProps.icon, size: 18 }), h('span', rowProps.label), h('strong', String(rowProps.value ?? '-'))]) } })
const StatCard = defineComponent({ props: { label: String, value: [String, Number] }, setup(cardProps) { return () => h('div', { class: 'ptb-stat' }, [h('div', { class: 'ptb-stat-value' }, String(cardProps.value ?? '-')), h('div', { class: 'ptb-stat-label' }, cardProps.label)]) } })
const TargetFields = defineComponent({ setup() { return () => h('div', { class: 'ptb-target-grid' }, [h(VSelectComponent, { modelValue: scrapeSection.value, 'onUpdate:modelValue': value => { scrapeSection.value = value }, items: sectionOptions.value, itemTitle: 'title', itemValue: 'value', label: '目标 Plex 媒体库', variant: 'outlined', density: 'compact', hideDetails: 'auto', loading: loadingSections.value }), h(VTextFieldComponent, { modelValue: scrapeLimit.value, 'onUpdate:modelValue': value => { scrapeLimit.value = Number(value) || 0 }, type: 'number', min: 0, label: '限制条数（0=不限）', variant: 'outlined', density: 'compact', hideDetails: 'auto' })]) } })

function statusLabel(value) { return ({ written: '已写入', resolved: '已解析', unresolved: '未命中', write_failed: '写入失败', busy: 'Plex忙' })[value] || (value || '-') }
function statusColor(value) { return ({ written: 'success', resolved: 'teal', unresolved: 'orange', write_failed: 'error', busy: 'warning' })[value] || 'grey' }
function fmtTime(value) { if (!value) return '-'; const numeric = Number(value); const date = Number.isFinite(numeric) ? new Date(numeric > 100000000000 ? numeric : numeric * 1000) : new Date(value); if (Number.isNaN(date.getTime())) return String(value); const pad = item => String(item).padStart(2, '0'); return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}` }
function showMatching(type, text) { matchingResult.value = { type, text } }
function showScraping(type, text) { scrapingResult.value = { type, text } }

async function loadSections() { loadingSections.value = true; try { const response = await getPluginApi(props.api, 'sections'); if (!response?.success) throw new Error(response?.error || '获取媒体库失败'); sectionOptions.value = (response.sections || []).map(item => ({ title: `${item.title}（${item.type}）`, value: String(item.key) })) } catch (exception) { error.value = String(exception) } finally { loadingSections.value = false } }
async function loadRuntimeData() { loadingRuntime.value = true; try { const [runtimeStatus, result] = await Promise.all([getPluginApi(props.api, 'status'), getPluginApi(props.api, 'result')]); status.value = runtimeStatus || {}; lastPlay.value = result?.last_play_result || null; history.value = Array.isArray(result?.play_history) ? result.play_history : [] } catch (exception) { error.value = String(exception) } finally { loadingRuntime.value = false } }
function snapshotBaseline() { savedBaseline.value = JSON.parse(JSON.stringify({ ...defaults, ...config })) }
async function loadConfig() { try { const response = await getPluginApi(props.api, 'config'); const persisted = response?.data || response; if (persisted && typeof persisted === 'object') Object.assign(config, persisted); snapshotBaseline() } catch (exception) { error.value = String(exception) } }
async function checkHelper() { checking.value = true; helperInfo.value = ''; try { const response = await getPluginApi(props.api, 'helper_check'); if (!response?.success) throw new Error(response?.error || 'helper 检查失败'); helperInfo.value = response?.dbinfo?.db_path || '已连接' } catch (exception) { error.value = String(exception) } finally { checking.value = false } }
async function clearData(target) { clearing.value = target === 'play_history' ? 'history' : 'last'; try { const response = await postPluginApi(props.api, 'clear_completion_data', { target }); if (!response?.success) throw new Error(response?.error || '清理失败'); if (target === 'play_history') history.value = []; else lastPlay.value = null; expanded.value = -1 } catch (exception) { error.value = String(exception) } finally { clearing.value = '' } }

async function doUnmatch(dryRun) { if (!scrapeSection.value) return showMatching('warning', '请先选择目标媒体库'); if (!dryRun && !window.confirm('确认对该媒体库执行取消匹配？条目将被打回未匹配并按当前 NFO 代理重读。')) return; busyKey.value = dryRun ? 'unmatch_preview' : 'unmatch_run'; matchingResult.value = null; try { const response = await postPluginApi(props.api, 'unmatch', { section: scrapeSection.value, dry_run: dryRun, rematch: true, limit: Number(scrapeLimit.value) || 0 }); if (!response?.success) throw new Error(response?.error || '操作失败'); showMatching(dryRun ? 'info' : 'success', dryRun ? `预览：该库共 ${response.total_items} 个条目，将影响 ${response.will_affect} 个` : `已取消匹配 ${response.unmatched} 个，刷新重读 ${response.refreshed} 个，失败 ${response.failed} 个`) } catch (exception) { showMatching('error', String(exception)) } finally { busyKey.value = '' } }
async function doScanCover() { if (!scrapeSection.value) return showScraping('warning', '请先选择目标媒体库'); busyKey.value = 'scan_cover'; try { const response = await postPluginApi(props.api, 'scan_cover', { section: scrapeSection.value }); if (!response?.success) throw new Error(response?.error || '扫描失败'); const list = (response.missing || []).slice(0, 20).map(item => `· ${item.title}（${item.reason}）`).join('\n'); showScraping('info', `已检查 ${response.checked} 个条目，缺封面 ${response.total} 个${list ? '：\n' + list : ''}`) } catch (exception) { showScraping('error', String(exception)) } finally { busyKey.value = '' } }
async function doScrape(dryRun) { if (!scrapeSection.value) return showScraping('warning', '请先选择目标媒体库'); if (!dryRun && !window.confirm('确认对缺封面条目执行 MoviePilot 刮削？将生成 NFO+封面文件。')) return; busyKey.value = dryRun ? 'scrape_preview' : 'scrape_run'; try { const response = await postPluginApi(props.api, 'scrape', { section: scrapeSection.value, dry_run: dryRun, limit: Number(scrapeLimit.value) || 0, unmatch_after: false }); if (!response?.success) throw new Error(response?.error || '刮削失败'); const list = (response.targets || []).slice(0, 20).map(item => `· ${item.title} → ${item.dir}`).join('\n'); showScraping(dryRun ? 'info' : 'success', dryRun ? `待刮削 ${response.candidates} 个目录${list ? '：\n' + list : ''}` : `刮削成功 ${response.scraped} 个，已刷新 ${response.refreshed || 0} 个，失败 ${response.failed} 个`) } catch (exception) { showScraping('error', String(exception)) } finally { busyKey.value = '' } }
async function doFixPoster(dryRun) { if (!scrapeSection.value) return showScraping('warning', '请先选择目标媒体库'); if (!dryRun && !window.confirm('确认为缺 poster.jpg 的条目执行补全？剧集优先复制季内海报，其余从 TMDB 下载。')) return; busyKey.value = dryRun ? 'poster_preview' : 'poster_run'; try { const response = await postPluginApi(props.api, 'fix_poster', { section: scrapeSection.value, dry_run: dryRun, limit: Number(scrapeLimit.value) || 0 }); if (!response?.success) throw new Error(response?.error || '操作失败'); const list = (response.targets || []).slice(0, 20).map(item => `· ${item.title} → ${item.dir}`).join('\n'); showScraping(dryRun ? 'info' : (response.failed ? 'warning' : 'success'), dryRun ? `已检查 ${response.checked} 个条目，缺 poster ${response.candidates} 个${list ? '：\n' + list : ''}` : `补全成功 ${response.fixed} 个（已刷新 ${response.refreshed}），失败 ${response.failed} 个`) } catch (exception) { showScraping('error', String(exception)) } finally { busyKey.value = '' } }

async function doMergeScan() { busyKey.value = 'merge_scan'; mergeResult.value = null; mergeGroups.value = []; mergeScanned.value = false; try { const response = await getPluginApi(props.api, 'merge_scan'); if (!response?.success) throw new Error(response?.error || '扫描失败'); mergeGroups.value = response.groups || []; mergeScanned.value = true; if (!mergeGroups.value.length) mergeResult.value = { type: 'success', text: '未发现重复条目' } } catch (exception) { mergeResult.value = { type: 'error', text: String(exception) } } finally { busyKey.value = '' } }
async function doMergeExecute() { if (!mergeGroups.value.length) return; if (!window.confirm(`确认合并 ${mergeGroups.value.length} 组重复条目？每组保留集数最多的条目，其余并入。`)) return; busyKey.value = 'merge_run'; mergeResult.value = null; try { const merges = mergeGroups.value.map(group => { const sorted = [...group.items].sort((a, b) => (Number(b.leaf_count) || 0) - (Number(a.leaf_count) || 0)); return { primary: sorted[0].rating_key, others: sorted.slice(1).map(item => item.rating_key) } }); const response = await postPluginApi(props.api, 'merge_execute', { merges }); if (!response?.success) throw new Error(response?.error || '合并失败'); const msg = `合并成功 ${response.merged} 组${response.failed?.length ? '，失败 ' + response.failed.length + ' 组' : ''}`; busyKey.value = ''; await doMergeScan(); mergeResult.value = { type: 'success', text: msg + '（已重新扫描）' } } catch (exception) { mergeResult.value = { type: 'error', text: String(exception) } } finally { busyKey.value = '' } }

async function saveConfig() { const payload = { ...config }; error.value = ''; saving.value = true; try { const response = await postPluginApi(props.api, 'config', payload); if (!response?.success) throw new Error(response?.message || response?.error || '配置保存失败'); const verify = await getPluginApi(props.api, 'config'); const persisted = verify?.data || verify; if (persisted && typeof persisted === 'object') Object.assign(config, persisted); snapshotBaseline(); saveMessage.value = '配置已保存并生效'; saveSnackbar.value = true } catch (exception) { error.value = exception?.message || String(exception) } finally { saving.value = false } }
onMounted(async () => { emit('layout', layoutRequest); await loadConfig(); await loadRuntimeData(); if (config.plex_token && (config.plex_direct_host || config.plex_host)) loadSections() })
</script>

<style scoped>
.ptb-config { container-type: inline-size; width: min(1120px, calc(100vw - 48px)); max-width: 100%; height: calc(100dvh - 16px); max-height: calc(100dvh - 16px); padding: 8px; margin: 0 auto; display: flex; }
.ptb-card { width: 100%; height: 100%; min-height: 0; display: flex; flex-direction: column; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 14px; overflow: hidden; }
.ptb-header { padding: 14px 18px; }
.ptb-header-subtitle { max-width: min(560px, 52vw); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ptb-body { flex: 1 1 auto; min-height: 0; display: flex; }
.ptb-nav { width: 168px; flex: 0 0 168px; border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgba(var(--v-theme-on-surface), .02); }
.ptb-nav-item { margin: 2px 8px; }
.ptb-content { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.ptb-error-alert { flex: 0 0 auto; min-height: 44px; }
.ptb-dirty-hint { display: flex; align-items: center; }
.ptb-mobile-tabbar { display: none; }
.ptb-workspace { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow-y: auto; }
.ptb-window { flex: 0 0 auto; min-width: 0; }
.ptb-pane { padding: 18px 20px; }
.ptb-section-title { color: rgb(var(--v-theme-primary)); font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.ptb-subsection-title, .ptb-block-title { font-size: 13px; font-weight: 700; }
.ptb-doc-link { color: rgb(var(--v-theme-primary)); text-decoration: underline; font-weight: 600; }
.ptb-target-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(130px, 1fr); gap: 12px; }
.ptb-stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; }
.ptb-stat { padding: 10px 12px; border-left: 3px solid rgb(var(--v-theme-primary)); border-radius: 8px; background: rgba(var(--v-theme-on-surface), .03); }
.ptb-stat-value { font-size: 1.25rem; font-weight: 700; }
.ptb-stat-label { font-size: .75rem; opacity: .7; }
.ptb-history th { font-size: .72rem; opacity: .7; }
.ptb-row { cursor: pointer; }
.ptb-detail-cell { background: rgba(var(--v-theme-on-surface), .03); }
.ptb-dashboard { flex: 0 0 auto; margin: 0 12px 12px; padding: 14px 16px; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 8px; background: rgba(var(--v-theme-on-surface), .015); }
.ptb-dashboard-title { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 14px; font-weight: 700; }
.ptb-dashboard-row { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; gap: 8px; min-height: 38px; color: rgba(var(--v-theme-on-surface), .68); font-size: 13px; }
.ptb-dashboard-row strong { color: rgb(var(--v-theme-on-surface)); text-align: right; overflow-wrap: anywhere; }
@container (min-width: 880px) { .ptb-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 252px; overflow: hidden; } .ptb-window { min-height: 0; overflow-y: auto; } .ptb-dashboard { margin: 0; padding: 18px 16px; border-width: 0 0 0 1px; border-radius: 0; overflow-y: auto; } }
@media (max-width: 640px) { .ptb-config { width: 100%; height: 100dvh; max-height: 100dvh; padding: 0; } .ptb-card { border: 0; border-radius: 0; } .ptb-header { padding: 8px 10px; } .ptb-header-title { font-size: 15px; } .ptb-dirty-hint { display: none; } .ptb-body { flex-direction: column; } .ptb-nav { display: none; } .ptb-mobile-tabbar { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); } .ptb-mobile-tabinfo { flex: 1 1 auto; min-width: 0; } .ptb-pane { padding: 12px; } .ptb-target-grid { grid-template-columns: 1fr; } }
</style>
