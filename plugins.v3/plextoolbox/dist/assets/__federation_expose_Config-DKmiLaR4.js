import { importShared } from './__federation_fn_import-JrT3xvdd.js';

function unwrapResponse(response) {
  const data = response?.data ?? response;
  if (data && typeof data === 'object' && 'data' in data) return data.data
  return data
}

async function getPluginApi(api, path) {
  if (!api?.get) throw new Error('缺少 MoviePilot 注入的 api.get')
  return unwrapResponse(await api.get(`plugin/PlexToolbox/${path}`))
}

async function postPluginApi(api, path, payload = {}) {
  if (!api?.post) throw new Error('缺少 MoviePilot 注入的 api.post')
  return unwrapResponse(await api.post(`plugin/PlexToolbox/${path}`, payload))
}

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,withCtx:_withCtx,createTextVNode:_createTextVNode,toDisplayString:_toDisplayString,createElementVNode:_createElementVNode,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode,createBlock:_createBlock,renderList:_renderList,Fragment:_Fragment,createSlots:_createSlots,vShow:_vShow,withDirectives:_withDirectives,withModifiers:_withModifiers,unref:_unref,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1 = { class: "ptb-config" };
const _hoisted_2 = { class: "d-flex align-center ga-2" };
const _hoisted_3 = {
  key: 0,
  class: "ptb-dirty-hint"
};
const _hoisted_4 = { class: "text-caption text-warning" };
const _hoisted_5 = { class: "ptb-body" };
const _hoisted_6 = { class: "ptb-nav" };
const _hoisted_7 = { class: "ptb-content" };
const _hoisted_8 = { class: "ptb-mobile-tabbar" };
const _hoisted_9 = { class: "ptb-mobile-tabinfo" };
const _hoisted_10 = { class: "font-weight-medium" };
const _hoisted_11 = { class: "text-caption text-medium-emphasis" };
const _hoisted_12 = { class: "ptb-workspace" };
const _hoisted_13 = { class: "ptb-window" };
const _hoisted_14 = { class: "ptb-pane" };
const _hoisted_15 = { class: "ptb-pane" };
const _hoisted_16 = { class: "ptb-pane" };
const _hoisted_17 = { class: "d-flex align-center flex-wrap ga-1 mb-3" };
const _hoisted_18 = { class: "d-flex align-center mb-2" };
const _hoisted_19 = {
  key: 0,
  class: "text-body-2 font-weight-medium mb-2"
};
const _hoisted_20 = { class: "ptb-stat-grid mb-3" };
const _hoisted_21 = { class: "text-caption" };
const _hoisted_22 = {
  key: 0,
  class: "text-caption text-error ml-2"
};
const _hoisted_23 = { class: "d-flex align-center mb-2" };
const _hoisted_24 = { class: "ptb-block-title" };
const _hoisted_25 = ["onClick"];
const _hoisted_26 = { key: 0 };
const _hoisted_27 = {
  colspan: "3",
  class: "ptb-detail-cell"
};
const _hoisted_28 = { class: "text-caption ml-2" };
const _hoisted_29 = { class: "ptb-pane" };
const _hoisted_30 = { class: "d-flex ga-2 flex-wrap mt-4" };
const _hoisted_31 = { class: "ptb-pane" };
const _hoisted_32 = { class: "d-flex ga-2 flex-wrap" };
const _hoisted_33 = { class: "d-flex ga-2 flex-wrap" };
const _hoisted_34 = { class: "ptb-pane" };
const _hoisted_35 = { class: "d-flex ga-2 flex-wrap mb-3" };
const _hoisted_36 = { class: "text-caption text-medium-emphasis mb-2" };
const _hoisted_37 = { class: "text-caption" };
const _hoisted_38 = { class: "text-caption" };
const _hoisted_39 = { class: "text-caption" };
const _hoisted_40 = {
  class: "ptb-dashboard",
  "aria-label": "运行表盘"
};
const _hoisted_41 = { class: "ptb-dashboard-title" };
const _hoisted_42 = { class: "ptb-dashboard-title" };

const {computed,defineComponent,h,onMounted,reactive,ref,resolveComponent,watch} = await importShared('vue');

const helperDocUrl = 'https://github.com/ranzhigg/MoviePilot-Plugins/blob/main/plugins.v3/plextoolbox/helper/README.md';

const _sfc_main = {
  __name: 'Config',
  props: { initialConfig: { type: Object, default: () => ({}) }, api: { type: [Object, Function], default: null } },
  emits: ['save', 'close', 'layout'],
  setup(__props, { emit: __emit }) {

const props = __props;
const emit = __emit;
const layoutRequest = { maxWidth: '70rem' };
emit('layout', layoutRequest);
const VIconComponent = resolveComponent('VIcon');
const VSelectComponent = resolveComponent('VSelect');
const VTextFieldComponent = resolveComponent('VTextField');

const tabs = [
  { key: 'proxy', title: '反向代理', icon: 'mdi-swap-horizontal-bold', desc: 'Plex 播放流 302 直链跳转' },
  { key: 'mediainfo', title: '媒体信息补全', icon: 'mdi-information-outline', desc: '为 STRM 条目补全媒体流信息' },
  { key: 'records', title: '补全记录', icon: 'mdi-history', desc: '最近一次补全与历史执行记录' },
  { key: 'matching', title: '目录匹配', icon: 'mdi-link-variant-off', desc: '预览并执行取消匹配重读 NFO' },
  { key: 'scraping', title: '刮削与海报', icon: 'mdi-image-search-outline', desc: '缺封面扫描、刮削和 poster 补全' },
  { key: 'merge', title: '合并重复', icon: 'mdi-call-merge', desc: '扫描并合并 tmdb id 相同的重复条目' },
];
const activeTab = ref('proxy');
const currentTab = computed(() => tabs.find(item => item.key === activeTab.value) || tabs[0]);
const mobileTabSheet = ref(false);
const error = ref('');
const checking = ref(false);
const loadingSections = ref(false);
const loadingRuntime = ref(false);
const saving = ref(false);
const saveMessage = ref('');
const saveSnackbar = ref(false);
const helperInfo = ref('');
const sectionOptions = ref([]);
const status = ref({});
const lastPlay = ref(null);
const history = ref([]);
const expanded = ref(-1);
const clearing = ref('');
const scrapeSection = ref('');
const scrapeLimit = ref(0);
const busyKey = ref('');
const matchingResult = ref(null);
const scrapingResult = ref(null);
const mergeGroups = ref([]);
const mergeScanned = ref(false);
const mergeResult = ref(null);

const defaults = { enabled: false, proxy_enabled: false, plex_host: '', plex_token: '', host: '0.0.0.0', port: 32401, pin_rules: '', force_direct_play: true, mediainfo_enabled: false, plex_direct_host: '', helper_url: '', helper_token: '', emby_url: '', emby_apikey: '', use_emby: true, use_ffprobe: true, ffprobe_path_map: '/Volumes/data=/media', ffprobe_timeout: 40, overwrite_streams: true, only_missing: true, concurrency: 3, sections: '', webhook_enabled: false, dedup_window: 300, forward_episodes: 5 };
const config = reactive({ ...defaults, ...props.initialConfig });
const savedBaseline = ref(JSON.parse(JSON.stringify(defaults)));

watch(() => props.initialConfig, value => { if (!value || typeof value !== 'object' || !Object.keys(value).length) return; Object.assign(config, value); snapshotBaseline(); }, { deep: true });
watch(activeTab, () => emit('layout', layoutRequest));

const selectedSections = computed({ get: () => config.sections ? String(config.sections).split(',').map(item => item.trim()).filter(Boolean) : [], set: value => { config.sections = (value || []).join(','); } });
function normalizeValue(value) { if (Array.isArray(value)) return JSON.stringify([...value].sort()); if (value === undefined || value === null) return ''; return String(value) }
const changedCount = computed(() => Object.keys(defaults).filter(key => normalizeValue(config[key]) !== normalizeValue(savedBaseline.value[key])).length);
const triggerText = computed(() => !config.mediainfo_enabled ? '未启用' : '当前条目 + 后续集');
const helperStatusText = computed(() => { if (helperInfo.value || status.value.helper_health_ok === true) return '正常'; if (status.value.helper_health_ok === false) return `异常（连续 ${status.value.helper_health_failures || 1} 次）`; return config.helper_url ? '等待检查' : '未配置' });
const lastRunText = computed(() => lastPlay.value ? fmtTime(lastPlay.value.ts || lastPlay.value.time || lastPlay.value.created_at) : '暂无');
const lastWriteText = computed(() => lastPlay.value ? `${lastPlay.value.written_ok || 0} 成功 / ${lastPlay.value.write_failed || 0} 失败` : '暂无');

const DashboardRow = defineComponent({ props: { icon: String, label: String, value: [String, Number] }, setup(rowProps) { return () => h('div', { class: 'ptb-dashboard-row' }, [h(VIconComponent, { icon: rowProps.icon, size: 18 }), h('span', rowProps.label), h('strong', String(rowProps.value ?? '-'))]) } });
const StatCard = defineComponent({ props: { label: String, value: [String, Number] }, setup(cardProps) { return () => h('div', { class: 'ptb-stat' }, [h('div', { class: 'ptb-stat-value' }, String(cardProps.value ?? '-')), h('div', { class: 'ptb-stat-label' }, cardProps.label)]) } });
const TargetFields = defineComponent({ setup() { return () => h('div', { class: 'ptb-target-grid' }, [h(VSelectComponent, { modelValue: scrapeSection.value, 'onUpdate:modelValue': value => { scrapeSection.value = value; }, items: sectionOptions.value, itemTitle: 'title', itemValue: 'value', label: '目标 Plex 媒体库', variant: 'outlined', density: 'compact', hideDetails: 'auto', loading: loadingSections.value }), h(VTextFieldComponent, { modelValue: scrapeLimit.value, 'onUpdate:modelValue': value => { scrapeLimit.value = Number(value) || 0; }, type: 'number', min: 0, label: '限制条数（0=不限）', variant: 'outlined', density: 'compact', hideDetails: 'auto' })]) } });

function statusLabel(value) { return ({ written: '已写入', resolved: '已解析', unresolved: '未命中', write_failed: '写入失败', busy: 'Plex忙' })[value] || (value || '-') }
function statusColor(value) { return ({ written: 'success', resolved: 'teal', unresolved: 'orange', write_failed: 'error', busy: 'warning' })[value] || 'grey' }
function fmtTime(value) { if (!value) return '-'; const numeric = Number(value); const date = Number.isFinite(numeric) ? new Date(numeric > 100000000000 ? numeric : numeric * 1000) : new Date(value); if (Number.isNaN(date.getTime())) return String(value); const pad = item => String(item).padStart(2, '0'); return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}` }
function showMatching(type, text) { matchingResult.value = { type, text }; }
function showScraping(type, text) { scrapingResult.value = { type, text }; }

async function loadSections() { loadingSections.value = true; try { const response = await getPluginApi(props.api, 'sections'); if (!response?.success) throw new Error(response?.error || '获取媒体库失败'); sectionOptions.value = (response.sections || []).map(item => ({ title: `${item.title}（${item.type}）`, value: String(item.key) })); } catch (exception) { error.value = String(exception); } finally { loadingSections.value = false; } }
async function loadRuntimeData() { loadingRuntime.value = true; try { const [runtimeStatus, result] = await Promise.all([getPluginApi(props.api, 'status'), getPluginApi(props.api, 'result')]); status.value = runtimeStatus || {}; lastPlay.value = result?.last_play_result || null; history.value = Array.isArray(result?.play_history) ? result.play_history : []; } catch (exception) { error.value = String(exception); } finally { loadingRuntime.value = false; } }
function snapshotBaseline() { savedBaseline.value = JSON.parse(JSON.stringify({ ...defaults, ...config })); }
async function loadConfig() { try { const response = await getPluginApi(props.api, 'config'); const persisted = response?.data || response; if (persisted && typeof persisted === 'object') Object.assign(config, persisted); snapshotBaseline(); } catch (exception) { error.value = String(exception); } }
async function checkHelper() { checking.value = true; helperInfo.value = ''; try { const response = await getPluginApi(props.api, 'helper_check'); if (!response?.success) throw new Error(response?.error || 'helper 检查失败'); helperInfo.value = response?.dbinfo?.db_path || '已连接'; } catch (exception) { error.value = String(exception); } finally { checking.value = false; } }
async function clearData(target) { clearing.value = target === 'play_history' ? 'history' : 'last'; try { const response = await postPluginApi(props.api, 'clear_completion_data', { target }); if (!response?.success) throw new Error(response?.error || '清理失败'); if (target === 'play_history') history.value = []; else lastPlay.value = null; expanded.value = -1; } catch (exception) { error.value = String(exception); } finally { clearing.value = ''; } }

async function doUnmatch(dryRun) { if (!scrapeSection.value) return showMatching('warning', '请先选择目标媒体库'); if (!dryRun && !window.confirm('确认对该媒体库执行取消匹配？条目将被打回未匹配并按当前 NFO 代理重读。')) return; busyKey.value = dryRun ? 'unmatch_preview' : 'unmatch_run'; matchingResult.value = null; try { const response = await postPluginApi(props.api, 'unmatch', { section: scrapeSection.value, dry_run: dryRun, rematch: true, limit: Number(scrapeLimit.value) || 0 }); if (!response?.success) throw new Error(response?.error || '操作失败'); showMatching(dryRun ? 'info' : 'success', dryRun ? `预览：该库共 ${response.total_items} 个条目，将影响 ${response.will_affect} 个` : `已取消匹配 ${response.unmatched} 个，刷新重读 ${response.refreshed} 个，失败 ${response.failed} 个`); } catch (exception) { showMatching('error', String(exception)); } finally { busyKey.value = ''; } }
async function doScanCover() { if (!scrapeSection.value) return showScraping('warning', '请先选择目标媒体库'); busyKey.value = 'scan_cover'; try { const response = await postPluginApi(props.api, 'scan_cover', { section: scrapeSection.value }); if (!response?.success) throw new Error(response?.error || '扫描失败'); const list = (response.missing || []).slice(0, 20).map(item => `· ${item.title}（${item.reason}）`).join('\n'); showScraping('info', `已检查 ${response.checked} 个条目，缺封面 ${response.total} 个${list ? '：\n' + list : ''}`); } catch (exception) { showScraping('error', String(exception)); } finally { busyKey.value = ''; } }
async function doScrape(dryRun) { if (!scrapeSection.value) return showScraping('warning', '请先选择目标媒体库'); if (!dryRun && !window.confirm('确认对缺封面条目执行 MoviePilot 刮削？将生成 NFO+封面文件。')) return; busyKey.value = dryRun ? 'scrape_preview' : 'scrape_run'; try { const response = await postPluginApi(props.api, 'scrape', { section: scrapeSection.value, dry_run: dryRun, limit: Number(scrapeLimit.value) || 0, unmatch_after: false }); if (!response?.success) throw new Error(response?.error || '刮削失败'); const list = (response.targets || []).slice(0, 20).map(item => `· ${item.title} → ${item.dir}`).join('\n'); showScraping(dryRun ? 'info' : 'success', dryRun ? `待刮削 ${response.candidates} 个目录${list ? '：\n' + list : ''}` : `刮削成功 ${response.scraped} 个，已刷新 ${response.refreshed || 0} 个，失败 ${response.failed} 个`); } catch (exception) { showScraping('error', String(exception)); } finally { busyKey.value = ''; } }
async function doFixPoster(dryRun) { if (!scrapeSection.value) return showScraping('warning', '请先选择目标媒体库'); if (!dryRun && !window.confirm('确认为缺 poster.jpg 的条目执行补全？剧集优先复制季内海报，其余从 TMDB 下载。')) return; busyKey.value = dryRun ? 'poster_preview' : 'poster_run'; try { const response = await postPluginApi(props.api, 'fix_poster', { section: scrapeSection.value, dry_run: dryRun, limit: Number(scrapeLimit.value) || 0 }); if (!response?.success) throw new Error(response?.error || '操作失败'); const list = (response.targets || []).slice(0, 20).map(item => `· ${item.title} → ${item.dir}`).join('\n'); showScraping(dryRun ? 'info' : (response.failed ? 'warning' : 'success'), dryRun ? `已检查 ${response.checked} 个条目，缺 poster ${response.candidates} 个${list ? '：\n' + list : ''}` : `补全成功 ${response.fixed} 个（已刷新 ${response.refreshed}），失败 ${response.failed} 个`); } catch (exception) { showScraping('error', String(exception)); } finally { busyKey.value = ''; } }

async function doMergeScan() { busyKey.value = 'merge_scan'; mergeResult.value = null; mergeGroups.value = []; mergeScanned.value = false; try { const response = await getPluginApi(props.api, 'merge_scan'); if (!response?.success) throw new Error(response?.error || '扫描失败'); mergeGroups.value = response.groups || []; mergeScanned.value = true; if (!mergeGroups.value.length) mergeResult.value = { type: 'success', text: '未发现重复条目' }; } catch (exception) { mergeResult.value = { type: 'error', text: String(exception) }; } finally { busyKey.value = ''; } }
async function doMergeExecute() { if (!mergeGroups.value.length) return; if (!window.confirm(`确认合并 ${mergeGroups.value.length} 组重复条目？每组保留集数最多的条目，其余并入。`)) return; busyKey.value = 'merge_run'; mergeResult.value = null; try { const merges = mergeGroups.value.map(group => { const sorted = [...group.items].sort((a, b) => (Number(b.leaf_count) || 0) - (Number(a.leaf_count) || 0)); return { primary: sorted[0].rating_key, others: sorted.slice(1).map(item => item.rating_key) } }); const response = await postPluginApi(props.api, 'merge_execute', { merges }); if (!response?.success) throw new Error(response?.error || '合并失败'); const msg = `合并成功 ${response.merged} 组${response.failed?.length ? '，失败 ' + response.failed.length + ' 组' : ''}`; busyKey.value = ''; await doMergeScan(); mergeResult.value = { type: 'success', text: msg + '（已重新扫描）' }; } catch (exception) { mergeResult.value = { type: 'error', text: String(exception) }; } finally { busyKey.value = ''; } }

async function saveConfig() { const payload = { ...config }; error.value = ''; saving.value = true; try { const response = await postPluginApi(props.api, 'config', payload); if (!response?.success) throw new Error(response?.message || response?.error || '配置保存失败'); const verify = await getPluginApi(props.api, 'config'); const persisted = verify?.data || verify; if (persisted && typeof persisted === 'object') Object.assign(config, persisted); snapshotBaseline(); saveMessage.value = '配置已保存并生效'; saveSnackbar.value = true; } catch (exception) { error.value = exception?.message || String(exception); } finally { saving.value = false; } }
onMounted(async () => { emit('layout', layoutRequest); await loadConfig(); await loadRuntimeData(); if (config.plex_token && (config.plex_direct_host || config.plex_host)) loadSections(); });

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VAvatar = _resolveComponent("VAvatar");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VCardSubtitle = _resolveComponent("VCardSubtitle");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VCardItem = _resolveComponent("VCardItem");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VListItemTitle = _resolveComponent("VListItemTitle");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VListItem = _resolveComponent("VListItem");
  const _component_VList = _resolveComponent("VList");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VTextarea = _resolveComponent("VTextarea");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VTable = _resolveComponent("VTable");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VBottomSheet = _resolveComponent("VBottomSheet");
  const _component_VSnackbar = _resolveComponent("VSnackbar");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VCard, {
      flat: "",
      class: "ptb-card"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCardItem, { class: "ptb-header" }, {
          prepend: _withCtx(() => [
            _createVNode(_component_VAvatar, {
              color: "primary",
              variant: "tonal",
              size: "44",
              rounded: "lg"
            }, {
              default: _withCtx(() => [
                _createVNode(_component_VIcon, {
                  icon: "mdi-plex",
                  size: "24"
                })
              ]),
              _: 1
            })
          ]),
          append: _withCtx(() => [
            _createElementVNode("div", _hoisted_2, [
              (changedCount.value)
                ? (_openBlock(), _createElementBlock("div", _hoisted_3, [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-circle-medium",
                      color: "warning",
                      size: "18"
                    }),
                    _createElementVNode("span", _hoisted_4, _toDisplayString(changedCount.value) + " 项待保存", 1)
                  ]))
                : _createCommentVNode("", true),
              (changedCount.value)
                ? (_openBlock(), _createBlock(_component_VBtn, {
                    key: 1,
                    color: "primary",
                    variant: "flat",
                    size: "small",
                    "prepend-icon": "mdi-content-save",
                    rounded: "lg",
                    loading: saving.value,
                    onClick: saveConfig
                  }, {
                    default: _withCtx(() => [...(_cache[38] || (_cache[38] = [
                      _createTextVNode("保存修改", -1)
                    ]))]),
                    _: 1
                  }, 8, ["loading"]))
                : _createCommentVNode("", true),
              _createVNode(_component_VBtn, {
                icon: "mdi-close",
                variant: "text",
                size: "small",
                onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
              })
            ])
          ]),
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-h6 ptb-header-title" }, {
              default: _withCtx(() => [...(_cache[37] || (_cache[37] = [
                _createTextVNode("PLEX 工具箱", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VCardSubtitle, { class: "text-caption ptb-header-subtitle" }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(currentTab.value.desc), 1)
              ]),
              _: 1
            })
          ]),
          _: 1
        }),
        _createVNode(_component_VDivider),
        _createElementVNode("div", _hoisted_5, [
          _createElementVNode("nav", _hoisted_6, [
            _createVNode(_component_VList, {
              density: "comfortable",
              nav: "",
              class: "py-2"
            }, {
              default: _withCtx(() => [
                (_openBlock(), _createElementBlock(_Fragment, null, _renderList(tabs, (item) => {
                  return _createVNode(_component_VListItem, {
                    key: item.key,
                    active: activeTab.value === item.key,
                    color: "primary",
                    rounded: "lg",
                    class: "ptb-nav-item",
                    onClick: $event => (activeTab.value = item.key)
                  }, _createSlots({
                    prepend: _withCtx(() => [
                      _createVNode(_component_VIcon, {
                        icon: item.icon
                      }, null, 8, ["icon"])
                    ]),
                    default: _withCtx(() => [
                      _createVNode(_component_VListItemTitle, null, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(item.title), 1)
                        ]),
                        _: 2
                      }, 1024)
                    ]),
                    _: 2
                  }, [
                    (item.key === 'records' && history.value.length)
                      ? {
                          name: "append",
                          fn: _withCtx(() => [
                            _createVNode(_component_VChip, {
                              size: "x-small",
                              variant: "tonal"
                            }, {
                              default: _withCtx(() => [
                                _createTextVNode(_toDisplayString(history.value.length), 1)
                              ]),
                              _: 1
                            })
                          ]),
                          key: "0"
                        }
                      : undefined
                  ]), 1032, ["active", "onClick"])
                }), 64))
              ]),
              _: 1
            })
          ]),
          _createElementVNode("section", _hoisted_7, [
            _createElementVNode("div", _hoisted_8, [
              _createElementVNode("div", _hoisted_9, [
                _createElementVNode("div", _hoisted_10, _toDisplayString(currentTab.value.title), 1),
                _createElementVNode("div", _hoisted_11, _toDisplayString(currentTab.value.desc), 1)
              ]),
              _createVNode(_component_VBtn, {
                icon: "mdi-menu-down",
                variant: "tonal",
                size: "small",
                onClick: _cache[1] || (_cache[1] = $event => (mobileTabSheet.value = true))
              })
            ]),
            (error.value)
              ? (_openBlock(), _createBlock(_component_VAlert, {
                  key: 0,
                  type: "error",
                  variant: "tonal",
                  density: "compact",
                  class: "ptb-error-alert ma-3 mb-0 text-caption",
                  closable: "",
                  "onClick:close": _cache[2] || (_cache[2] = $event => (error.value = ''))
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(error.value), 1)
                  ]),
                  _: 1
                }))
              : _createCommentVNode("", true),
            _createElementVNode("div", _hoisted_12, [
              _createElementVNode("div", _hoisted_13, [
                _withDirectives(_createElementVNode("div", _hoisted_14, [
                  _cache[39] || (_cache[39] = _createElementVNode("div", { class: "ptb-section-title" }, "302 反向代理", -1)),
                  _createVNode(_component_VRow, null, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCol, { cols: "12" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.proxy_enabled,
                            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((config.proxy_enabled) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "启用 302 反向代理"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "8"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.plex_host,
                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((config.plex_host) = $event)),
                            label: "Plex 服务器地址",
                            placeholder: "http://192.168.0.122:32400",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.plex_token,
                            "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((config.plex_token) = $event)),
                            label: "X-Plex-Token",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.host,
                            "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((config.host) = $event)),
                            label: "代理监听地址",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.port,
                            "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((config.port) = $event)),
                            modelModifiers: { number: true },
                            type: "number",
                            label: "代理监听端口",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, { cols: "12" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.force_direct_play,
                            "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((config.force_direct_play) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "强制 DirectPlay（避免转码使直链失效）"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, { cols: "12" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextarea, {
                            modelValue: config.pin_rules,
                            "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((config.pin_rules) = $event)),
                            label: "顶置路径规则（每行：路径前缀 => 目标URL）",
                            variant: "outlined",
                            density: "compact",
                            rows: "3",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  })
                ], 512), [
                  [_vShow, activeTab.value === 'proxy']
                ]),
                _withDirectives(_createElementVNode("div", _hoisted_15, [
                  _cache[42] || (_cache[42] = _createElementVNode("div", { class: "ptb-section-title" }, "STRM 媒体流信息补全", -1)),
                  _createVNode(_component_VAlert, {
                    type: "info",
                    variant: "tonal",
                    density: "compact",
                    class: "mb-3 text-caption"
                  }, {
                    default: _withCtx(() => [
                      _cache[40] || (_cache[40] = _createTextVNode("点击播放时先补全当前条目及设置的后续集，最多等待 3 秒后自动放行播放。需先在 Plex 主机部署 helper 写库服务；没有 Emby 时可直接用 ffprobe 探测 STRM 内的 302 直链。", -1)),
                      _createElementVNode("a", {
                        href: helperDocUrl,
                        target: "_blank",
                        rel: "noopener",
                        class: "ptb-doc-link"
                      }, "查看部署说明")
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VRow, null, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCol, { cols: "12" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.mediainfo_enabled,
                            "onUpdate:modelValue": _cache[10] || (_cache[10] = $event => ((config.mediainfo_enabled) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "启用媒体信息补全"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "8"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.plex_direct_host,
                            "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((config.plex_direct_host) = $event)),
                            label: "Plex 直连地址（写库/枚举用）",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VBtn, {
                            color: "info",
                            variant: "tonal",
                            size: "small",
                            loading: checking.value,
                            "prepend-icon": "mdi-lan-connect",
                            onClick: checkHelper
                          }, {
                            default: _withCtx(() => [...(_cache[41] || (_cache[41] = [
                              _createTextVNode("检查 helper", -1)
                            ]))]),
                            _: 1
                          }, 8, ["loading"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "8"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.helper_url,
                            "onUpdate:modelValue": _cache[12] || (_cache[12] = $event => ((config.helper_url) = $event)),
                            label: "helper 地址",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.helper_token,
                            "onUpdate:modelValue": _cache[13] || (_cache[13] = $event => ((config.helper_token) = $event)),
                            label: "helper Token",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.use_emby,
                            "onUpdate:modelValue": _cache[14] || (_cache[14] = $event => ((config.use_emby) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "数据源 Emby MediaStreams"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "8"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.emby_url,
                            "onUpdate:modelValue": _cache[15] || (_cache[15] = $event => ((config.emby_url) = $event)),
                            label: "Emby 地址",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.emby_apikey,
                            "onUpdate:modelValue": _cache[16] || (_cache[16] = $event => ((config.emby_apikey) = $event)),
                            label: "Emby API Key",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, { cols: "12" }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.use_ffprobe,
                            "onUpdate:modelValue": _cache[17] || (_cache[17] = $event => ((config.use_ffprobe) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "启用 ffprobe（无 Emby 或 Emby 未命中时读取 STRM 302 直链）"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "8"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.ffprobe_path_map,
                            "onUpdate:modelValue": _cache[18] || (_cache[18] = $event => ((config.ffprobe_path_map) = $event)),
                            label: "Plex 路径 → MoviePilot 容器路径映射",
                            placeholder: "/Volumes/data=/media",
                            hint: "每行一条，支持 =、=> 或分号分隔；Plex 主机路径在左，MP 容器路径在右",
                            "persistent-hint": "",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.ffprobe_timeout,
                            "onUpdate:modelValue": _cache[19] || (_cache[19] = $event => ((config.ffprobe_timeout) = $event)),
                            modelModifiers: { number: true },
                            type: "number",
                            min: "1",
                            max: "300",
                            label: "ffprobe 超时（秒）",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "8"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSelect, {
                            modelValue: selectedSections.value,
                            "onUpdate:modelValue": _cache[20] || (_cache[20] = $event => ((selectedSections).value = $event)),
                            items: sectionOptions.value,
                            "item-title": "title",
                            "item-value": "value",
                            label: "要补全的 Plex 媒体库",
                            variant: "outlined",
                            density: "compact",
                            multiple: "",
                            chips: "",
                            "closable-chips": "",
                            "hide-details": "auto",
                            loading: loadingSections.value
                          }, {
                            "append-inner": _withCtx(() => [
                              _createVNode(_component_VBtn, {
                                icon: "mdi-refresh",
                                size: "x-small",
                                variant: "text",
                                onClick: _withModifiers(loadSections, ["stop"])
                              })
                            ]),
                            _: 1
                          }, 8, ["modelValue", "items", "loading"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "4"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.concurrency,
                            "onUpdate:modelValue": _cache[21] || (_cache[21] = $event => ((config.concurrency) = $event)),
                            modelModifiers: { number: true },
                            type: "number",
                            min: "1",
                            max: "10",
                            label: "探测并发数",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.only_missing,
                            "onUpdate:modelValue": _cache[22] || (_cache[22] = $event => ((config.only_missing) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "仅处理缺失媒体信息的条目"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.overwrite_streams,
                            "onUpdate:modelValue": _cache[23] || (_cache[23] = $event => ((config.overwrite_streams) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "写入前清空旧流"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSwitch, {
                            modelValue: config.webhook_enabled,
                            "onUpdate:modelValue": _cache[24] || (_cache[24] = $event => ((config.webhook_enabled) = $event)),
                            color: "primary",
                            "hide-details": "",
                            inset: "",
                            label: "启用 Plex Webhook 触发"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.dedup_window,
                            "onUpdate:modelValue": _cache[25] || (_cache[25] = $event => ((config.dedup_window) = $event)),
                            modelModifiers: { number: true },
                            type: "number",
                            min: "0",
                            label: "播前同条目去重窗口（秒）",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: config.forward_episodes,
                            "onUpdate:modelValue": _cache[26] || (_cache[26] = $event => ((config.forward_episodes) = $event)),
                            modelModifiers: { number: true },
                            type: "number",
                            min: "0",
                            label: "剧集向后预取集数",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      })
                    ]),
                    _: 1
                  }),
                  (helperInfo.value)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 0,
                        type: "success",
                        variant: "tonal",
                        density: "compact",
                        class: "mt-2 text-caption"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode("helper 正常，数据库：" + _toDisplayString(helperInfo.value), 1)
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true)
                ], 512), [
                  [_vShow, activeTab.value === 'mediainfo']
                ]),
                _withDirectives(_createElementVNode("div", _hoisted_16, [
                  _createElementVNode("div", _hoisted_17, [
                    _cache[43] || (_cache[43] = _createElementVNode("div", { class: "ptb-section-title mb-0" }, "补全记录", -1)),
                    _createVNode(_component_VSpacer),
                    _createVNode(_component_VBtn, {
                      icon: "mdi-refresh",
                      variant: "text",
                      size: "small",
                      loading: loadingRuntime.value,
                      onClick: loadRuntimeData
                    }, null, 8, ["loading"])
                  ]),
                  _createElementVNode("div", _hoisted_18, [
                    _cache[45] || (_cache[45] = _createElementVNode("div", { class: "ptb-block-title" }, "最近一次补全", -1)),
                    _createVNode(_component_VSpacer),
                    (lastPlay.value)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 0,
                          color: "grey",
                          variant: "text",
                          size: "x-small",
                          "prepend-icon": "mdi-broom",
                          loading: clearing.value === 'last',
                          onClick: _cache[27] || (_cache[27] = $event => (clearData('last_play_result')))
                        }, {
                          default: _withCtx(() => [...(_cache[44] || (_cache[44] = [
                            _createTextVNode("清理", -1)
                          ]))]),
                          _: 1
                        }, 8, ["loading"]))
                      : _createCommentVNode("", true)
                  ]),
                  (lastPlay.value)
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                        (lastPlay.value.label)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_19, _toDisplayString(lastPlay.value.label), 1))
                          : _createCommentVNode("", true),
                        _createElementVNode("div", _hoisted_20, [
                          _createVNode(_unref(StatCard), {
                            label: "本次条目",
                            value: lastPlay.value.strm_parts
                          }, null, 8, ["value"]),
                          _createVNode(_unref(StatCard), {
                            label: "已解析",
                            value: lastPlay.value.resolved
                          }, null, 8, ["value"]),
                          _createVNode(_unref(StatCard), {
                            label: "Emby 命中",
                            value: lastPlay.value.emby_hits
                          }, null, 8, ["value"]),
                          _createVNode(_unref(StatCard), {
                            label: "ffprobe 命中",
                            value: lastPlay.value.ffprobe_hits
                          }, null, 8, ["value"]),
                          _createVNode(_unref(StatCard), {
                            label: "写入成功",
                            value: lastPlay.value.written_ok
                          }, null, 8, ["value"]),
                          _createVNode(_unref(StatCard), {
                            label: "写入失败",
                            value: lastPlay.value.write_failed
                          }, null, 8, ["value"])
                        ]),
                        (lastPlay.value.items?.length)
                          ? (_openBlock(), _createBlock(_component_VTable, {
                              key: 1,
                              density: "compact",
                              class: "ptb-history"
                            }, {
                              default: _withCtx(() => [
                                _cache[46] || (_cache[46] = _createElementVNode("thead", null, [
                                  _createElementVNode("tr", null, [
                                    _createElementVNode("th", null, "条目"),
                                    _createElementVNode("th", null, "状态")
                                  ])
                                ], -1)),
                                _createElementVNode("tbody", null, [
                                  (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(lastPlay.value.items, (item, index) => {
                                    return (_openBlock(), _createElementBlock("tr", { key: index }, [
                                      _createElementVNode("td", _hoisted_21, _toDisplayString(item.label || ('part ' + item.part_id)), 1),
                                      _createElementVNode("td", null, [
                                        _createVNode(_component_VChip, {
                                          color: statusColor(item.status),
                                          size: "x-small",
                                          variant: "tonal"
                                        }, {
                                          default: _withCtx(() => [
                                            _createTextVNode(_toDisplayString(statusLabel(item.status)), 1)
                                          ]),
                                          _: 2
                                        }, 1032, ["color"]),
                                        (item.error)
                                          ? (_openBlock(), _createElementBlock("span", _hoisted_22, _toDisplayString(item.error), 1))
                                          : _createCommentVNode("", true)
                                      ])
                                    ]))
                                  }), 128))
                                ])
                              ]),
                              _: 1
                            }))
                          : _createCommentVNode("", true)
                      ], 64))
                    : (_openBlock(), _createBlock(_component_VAlert, {
                        key: 1,
                        type: "info",
                        variant: "tonal",
                        density: "compact",
                        class: "text-caption"
                      }, {
                        default: _withCtx(() => [...(_cache[47] || (_cache[47] = [
                          _createTextVNode("暂无补全记录。", -1)
                        ]))]),
                        _: 1
                      })),
                  (lastPlay.value?.helper_busy)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 2,
                        type: "warning",
                        variant: "tonal",
                        density: "compact",
                        class: "mt-3 text-caption"
                      }, {
                        default: _withCtx(() => [...(_cache[48] || (_cache[48] = [
                          _createTextVNode("Plex 当前繁忙，本次未写入。", -1)
                        ]))]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  _createVNode(_component_VDivider, { class: "my-4" }),
                  _createElementVNode("div", _hoisted_23, [
                    _createElementVNode("div", _hoisted_24, "补全历史（最近 " + _toDisplayString(history.value.length) + " 条）", 1),
                    _createVNode(_component_VSpacer),
                    (history.value.length)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 0,
                          color: "grey",
                          variant: "text",
                          size: "x-small",
                          "prepend-icon": "mdi-broom",
                          loading: clearing.value === 'history',
                          onClick: _cache[28] || (_cache[28] = $event => (clearData('play_history')))
                        }, {
                          default: _withCtx(() => [...(_cache[49] || (_cache[49] = [
                            _createTextVNode("清空历史", -1)
                          ]))]),
                          _: 1
                        }, 8, ["loading"]))
                      : _createCommentVNode("", true)
                  ]),
                  (history.value.length)
                    ? (_openBlock(), _createBlock(_component_VTable, {
                        key: 3,
                        density: "compact",
                        class: "ptb-history"
                      }, {
                        default: _withCtx(() => [
                          _cache[50] || (_cache[50] = _createElementVNode("thead", null, [
                            _createElementVNode("tr", null, [
                              _createElementVNode("th", null, "时间"),
                              _createElementVNode("th", null, "条目"),
                              _createElementVNode("th", null, "结果")
                            ])
                          ], -1)),
                          _createElementVNode("tbody", null, [
                            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(history.value, (row, index) => {
                              return (_openBlock(), _createElementBlock(_Fragment, { key: index }, [
                                _createElementVNode("tr", {
                                  class: "ptb-row",
                                  onClick: $event => (expanded.value = expanded.value === index ? -1 : index)
                                }, [
                                  _createElementVNode("td", null, _toDisplayString(fmtTime(row.ts || row.time || row.created_at)), 1),
                                  _createElementVNode("td", null, _toDisplayString(row.label || '-'), 1),
                                  _createElementVNode("td", null, _toDisplayString(row.written_ok || 0) + " 成功 / " + _toDisplayString(row.write_failed || 0) + " 失败", 1)
                                ], 8, _hoisted_25),
                                (expanded.value === index)
                                  ? (_openBlock(), _createElementBlock("tr", _hoisted_26, [
                                      _createElementVNode("td", _hoisted_27, [
                                        (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(row.items || [], (item, itemIndex) => {
                                          return (_openBlock(), _createElementBlock("div", {
                                            key: itemIndex,
                                            class: "py-1"
                                          }, [
                                            _createVNode(_component_VChip, {
                                              color: statusColor(item.status),
                                              size: "x-small",
                                              variant: "tonal"
                                            }, {
                                              default: _withCtx(() => [
                                                _createTextVNode(_toDisplayString(statusLabel(item.status)), 1)
                                              ]),
                                              _: 2
                                            }, 1032, ["color"]),
                                            _createElementVNode("span", _hoisted_28, _toDisplayString(item.label || item.part_id), 1)
                                          ]))
                                        }), 128))
                                      ])
                                    ]))
                                  : _createCommentVNode("", true)
                              ], 64))
                            }), 128))
                          ])
                        ]),
                        _: 1
                      }))
                    : (_openBlock(), _createBlock(_component_VAlert, {
                        key: 4,
                        type: "info",
                        variant: "tonal",
                        density: "compact",
                        class: "text-caption"
                      }, {
                        default: _withCtx(() => [...(_cache[51] || (_cache[51] = [
                          _createTextVNode("暂无历史记录。", -1)
                        ]))]),
                        _: 1
                      }))
                ], 512), [
                  [_vShow, activeTab.value === 'records']
                ]),
                _withDirectives(_createElementVNode("div", _hoisted_29, [
                  _cache[55] || (_cache[55] = _createElementVNode("div", { class: "ptb-section-title" }, "目录匹配", -1)),
                  _createVNode(_component_VAlert, {
                    type: "info",
                    variant: "tonal",
                    density: "compact",
                    class: "mb-3 text-caption"
                  }, {
                    default: _withCtx(() => [...(_cache[52] || (_cache[52] = [
                      _createTextVNode("取消匹配后，条目会按当前 NFO 代理重读。建议先预览影响。", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_unref(TargetFields)),
                  _createElementVNode("div", _hoisted_30, [
                    _createVNode(_component_VBtn, {
                      color: "info",
                      variant: "tonal",
                      size: "small",
                      loading: busyKey.value === 'unmatch_preview',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-magnify",
                      onClick: _cache[29] || (_cache[29] = $event => (doUnmatch(true)))
                    }, {
                      default: _withCtx(() => [...(_cache[53] || (_cache[53] = [
                        _createTextVNode("预览影响", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"]),
                    _createVNode(_component_VBtn, {
                      color: "warning",
                      variant: "flat",
                      size: "small",
                      loading: busyKey.value === 'unmatch_run',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-link-off",
                      onClick: _cache[30] || (_cache[30] = $event => (doUnmatch(false)))
                    }, {
                      default: _withCtx(() => [...(_cache[54] || (_cache[54] = [
                        _createTextVNode("执行取消匹配", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"])
                  ]),
                  (matchingResult.value)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 0,
                        type: matchingResult.value.type,
                        variant: "tonal",
                        density: "compact",
                        class: "mt-4 text-caption",
                        style: {"white-space":"pre-wrap"}
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(matchingResult.value.text), 1)
                        ]),
                        _: 1
                      }, 8, ["type"]))
                    : _createCommentVNode("", true)
                ], 512), [
                  [_vShow, activeTab.value === 'matching']
                ]),
                _withDirectives(_createElementVNode("div", _hoisted_31, [
                  _cache[62] || (_cache[62] = _createElementVNode("div", { class: "ptb-section-title" }, "刮削与海报", -1)),
                  _createVNode(_component_VAlert, {
                    type: "info",
                    variant: "tonal",
                    density: "compact",
                    class: "mb-3 text-caption"
                  }, {
                    default: _withCtx(() => [...(_cache[56] || (_cache[56] = [
                      _createTextVNode("扫描缺封面条目并交给 MoviePilot 生成 NFO/封面，或精准补全缺失 poster.jpg。", -1)
                    ]))]),
                    _: 1
                  }),
                  _createVNode(_unref(TargetFields)),
                  _cache[63] || (_cache[63] = _createElementVNode("div", { class: "ptb-subsection-title mt-4" }, "缺封面刮削", -1)),
                  _createElementVNode("div", _hoisted_32, [
                    _createVNode(_component_VBtn, {
                      color: "info",
                      variant: "tonal",
                      size: "small",
                      loading: busyKey.value === 'scan_cover',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-image-off-outline",
                      onClick: doScanCover
                    }, {
                      default: _withCtx(() => [...(_cache[57] || (_cache[57] = [
                        _createTextVNode("扫描缺封面", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"]),
                    _createVNode(_component_VBtn, {
                      color: "info",
                      variant: "tonal",
                      size: "small",
                      loading: busyKey.value === 'scrape_preview',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-magnify",
                      onClick: _cache[31] || (_cache[31] = $event => (doScrape(true)))
                    }, {
                      default: _withCtx(() => [...(_cache[58] || (_cache[58] = [
                        _createTextVNode("预览刮削目录", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"]),
                    _createVNode(_component_VBtn, {
                      color: "success",
                      variant: "flat",
                      size: "small",
                      loading: busyKey.value === 'scrape_run',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-auto-fix",
                      onClick: _cache[32] || (_cache[32] = $event => (doScrape(false)))
                    }, {
                      default: _withCtx(() => [...(_cache[59] || (_cache[59] = [
                        _createTextVNode("执行刮削", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"])
                  ]),
                  _createVNode(_component_VDivider, { class: "my-4" }),
                  _cache[64] || (_cache[64] = _createElementVNode("div", { class: "ptb-subsection-title" }, "缺 poster.jpg 精准补全", -1)),
                  _createElementVNode("div", _hoisted_33, [
                    _createVNode(_component_VBtn, {
                      color: "info",
                      variant: "tonal",
                      size: "small",
                      loading: busyKey.value === 'poster_preview',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-magnify",
                      onClick: _cache[33] || (_cache[33] = $event => (doFixPoster(true)))
                    }, {
                      default: _withCtx(() => [...(_cache[60] || (_cache[60] = [
                        _createTextVNode("预览缺 poster", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"]),
                    _createVNode(_component_VBtn, {
                      color: "success",
                      variant: "flat",
                      size: "small",
                      loading: busyKey.value === 'poster_run',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-image-plus",
                      onClick: _cache[34] || (_cache[34] = $event => (doFixPoster(false)))
                    }, {
                      default: _withCtx(() => [...(_cache[61] || (_cache[61] = [
                        _createTextVNode("执行补全", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"])
                  ]),
                  (scrapingResult.value)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 0,
                        type: scrapingResult.value.type,
                        variant: "tonal",
                        density: "compact",
                        class: "mt-4 text-caption",
                        style: {"white-space":"pre-wrap"}
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(scrapingResult.value.text), 1)
                        ]),
                        _: 1
                      }, 8, ["type"]))
                    : _createCommentVNode("", true)
                ], 512), [
                  [_vShow, activeTab.value === 'scraping']
                ]),
                _withDirectives(_createElementVNode("div", _hoisted_34, [
                  _cache[69] || (_cache[69] = _createElementVNode("div", { class: "ptb-section-title" }, "合并重复条目", -1)),
                  _createVNode(_component_VAlert, {
                    type: "info",
                    variant: "tonal",
                    density: "compact",
                    class: "mb-3 text-caption"
                  }, {
                    default: _withCtx(() => [...(_cache[65] || (_cache[65] = [
                      _createTextVNode("扫描 Plex 全部剧集/电影库中 tmdb id 相同的重复条目，合并为一个（保留集数最多的条目作主）。", -1)
                    ]))]),
                    _: 1
                  }),
                  _createElementVNode("div", _hoisted_35, [
                    _createVNode(_component_VBtn, {
                      color: "info",
                      variant: "tonal",
                      size: "small",
                      loading: busyKey.value === 'merge_scan',
                      disabled: !!busyKey.value,
                      "prepend-icon": "mdi-magnify",
                      onClick: doMergeScan
                    }, {
                      default: _withCtx(() => [...(_cache[66] || (_cache[66] = [
                        _createTextVNode("扫描重复", -1)
                      ]))]),
                      _: 1
                    }, 8, ["loading", "disabled"]),
                    (mergeGroups.value.length)
                      ? (_openBlock(), _createBlock(_component_VBtn, {
                          key: 0,
                          color: "success",
                          variant: "flat",
                          size: "small",
                          loading: busyKey.value === 'merge_run',
                          disabled: !!busyKey.value,
                          "prepend-icon": "mdi-call-merge",
                          onClick: doMergeExecute
                        }, {
                          default: _withCtx(() => [
                            _createTextVNode("合并全部（" + _toDisplayString(mergeGroups.value.length) + " 组）", 1)
                          ]),
                          _: 1
                        }, 8, ["loading", "disabled"]))
                      : _createCommentVNode("", true)
                  ]),
                  (mergeGroups.value.length)
                    ? (_openBlock(), _createElementBlock(_Fragment, { key: 0 }, [
                        _createElementVNode("div", _hoisted_36, "共 " + _toDisplayString(mergeGroups.value.length) + " 组重复", 1),
                        _createVNode(_component_VTable, {
                          density: "compact",
                          class: "ptb-history"
                        }, {
                          default: _withCtx(() => [
                            _cache[67] || (_cache[67] = _createElementVNode("thead", null, [
                              _createElementVNode("tr", null, [
                                _createElementVNode("th", null, "剧集 / 电影"),
                                _createElementVNode("th", null, "TMDB"),
                                _createElementVNode("th", null, "重复条目")
                              ])
                            ], -1)),
                            _createElementVNode("tbody", null, [
                              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(mergeGroups.value, (group, gi) => {
                                return (_openBlock(), _createElementBlock("tr", { key: gi }, [
                                  _createElementVNode("td", _hoisted_37, _toDisplayString(group.title), 1),
                                  _createElementVNode("td", _hoisted_38, _toDisplayString(group.guid_id), 1),
                                  _createElementVNode("td", _hoisted_39, [
                                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(group.items, (item, ii) => {
                                      return (_openBlock(), _createElementBlock("div", {
                                        key: ii,
                                        class: _normalizeClass({ 'font-weight-bold': ii === 0 })
                                      }, " [" + _toDisplayString(item.section_title) + "] " + _toDisplayString(item.title) + "（" + _toDisplayString(item.year) + "）— " + _toDisplayString(item.leaf_count) + " 集 ", 3))
                                    }), 128))
                                  ])
                                ]))
                              }), 128))
                            ])
                          ]),
                          _: 1
                        })
                      ], 64))
                    : (mergeScanned.value)
                      ? (_openBlock(), _createBlock(_component_VAlert, {
                          key: 1,
                          type: "success",
                          variant: "tonal",
                          density: "compact",
                          class: "mt-2 text-caption"
                        }, {
                          default: _withCtx(() => [...(_cache[68] || (_cache[68] = [
                            _createTextVNode("未发现重复条目。", -1)
                          ]))]),
                          _: 1
                        }))
                      : _createCommentVNode("", true),
                  (mergeResult.value)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 2,
                        type: mergeResult.value.type,
                        variant: "tonal",
                        density: "compact",
                        class: "mt-4 text-caption",
                        style: {"white-space":"pre-wrap"}
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(mergeResult.value.text), 1)
                        ]),
                        _: 1
                      }, 8, ["type"]))
                    : _createCommentVNode("", true)
                ], 512), [
                  [_vShow, activeTab.value === 'merge']
                ])
              ]),
              _createElementVNode("aside", _hoisted_40, [
                _createElementVNode("section", null, [
                  _createElementVNode("div", _hoisted_41, [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-clock-outline",
                      color: "primary",
                      size: "20"
                    }),
                    _cache[70] || (_cache[70] = _createTextVNode("运行节奏", -1))
                  ]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-motion-play-outline",
                    label: "播前补全",
                    value: triggerText.value
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-skip-forward-outline",
                    label: "播前追加",
                    value: `后 ${config.forward_episodes || 0} 集`
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-timer-outline",
                    label: "去重窗口",
                    value: `${config.dedup_window || 0} 秒`
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-heart-pulse",
                    label: "Helper 检查",
                    value: "每 5 分钟"
                  })
                ]),
                _createVNode(_component_VDivider, { class: "my-3" }),
                _createElementVNode("section", null, [
                  _createElementVNode("div", _hoisted_42, [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-chart-box-outline",
                      color: "primary",
                      size: "20"
                    }),
                    _cache[71] || (_cache[71] = _createTextVNode("运行概况", -1))
                  ]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-swap-horizontal-bold",
                    label: "代理服务",
                    value: status.value.proxy_running ? '运行中' : '未运行'
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-lan-connect",
                    label: "Helper",
                    value: helperStatusText.value
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-database-search-outline",
                    label: "媒体数据源",
                    value: config.use_emby && config.emby_url && config.emby_apikey && config.use_ffprobe ? 'Emby → ffprobe' : (config.use_emby && config.emby_url && config.emby_apikey ? 'Emby' : (config.use_ffprobe ? 'ffprobe' : '未启用'))
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-history",
                    label: "最近补全",
                    value: lastRunText.value
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-database-check-outline",
                    label: "最近写入",
                    value: lastWriteText.value
                  }, null, 8, ["value"]),
                  _createVNode(_unref(DashboardRow), {
                    icon: "mdi-folder-multiple-outline",
                    label: "补全媒体库",
                    value: `${selectedSections.value.length} 个`
                  }, null, 8, ["value"])
                ])
              ])
            ])
          ])
        ])
      ]),
      _: 1
    }),
    _createVNode(_component_VBottomSheet, {
      modelValue: mobileTabSheet.value,
      "onUpdate:modelValue": _cache[35] || (_cache[35] = $event => ((mobileTabSheet).value = $event))
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, null, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
              default: _withCtx(() => [...(_cache[72] || (_cache[72] = [
                _createTextVNode("选择功能", -1)
              ]))]),
              _: 1
            }),
            _createVNode(_component_VList, { nav: "" }, {
              default: _withCtx(() => [
                (_openBlock(), _createElementBlock(_Fragment, null, _renderList(tabs, (item) => {
                  return _createVNode(_component_VListItem, {
                    key: item.key,
                    active: activeTab.value === item.key,
                    title: item.title,
                    subtitle: item.desc,
                    onClick: $event => {activeTab.value = item.key; mobileTabSheet.value = false;}
                  }, {
                    prepend: _withCtx(() => [
                      _createVNode(_component_VIcon, {
                        icon: item.icon
                      }, null, 8, ["icon"])
                    ]),
                    _: 2
                  }, 1032, ["active", "title", "subtitle", "onClick"])
                }), 64))
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue"]),
    _createVNode(_component_VSnackbar, {
      modelValue: saveSnackbar.value,
      "onUpdate:modelValue": _cache[36] || (_cache[36] = $event => ((saveSnackbar).value = $event)),
      color: "success",
      location: "top",
      timeout: 2200
    }, {
      default: _withCtx(() => [
        _createTextVNode(_toDisplayString(saveMessage.value), 1)
      ]),
      _: 1
    }, 8, ["modelValue"])
  ]))
}
}

};
const Config = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-d649379b"]]);

export { Config as default };
