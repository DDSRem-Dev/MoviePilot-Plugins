import { ref, computed } from 'vue';

/**
 * 全局配置快速检索索引（支持 ⌘K 搜索直达全量 5 大分区与 17 个子模块）
 */
export const CONFIG_SEARCH_INDEX = [
  {
    id: 'basic-enable',
    category: 'category-basic',
    categoryLabel: '基础设置',
    subTab: '',
    subLabel: '连接与全局参数',
    title: '启用插件 / 通知语言 / STRM URL 格式 / 直链模式',
    keywords: 'enabled notify language pickcode pickname cookie openapi 猫娘 粤语 通知',
  },
  {
    id: 'basic-auth',
    category: 'category-basic',
    categoryLabel: '基础设置',
    subTab: '',
    subLabel: '账号凭证与站点地址',
    title: '115 Cookie · 阿里云盘 Token · STRM 站点链接地址 · 媒体扩展名',
    keywords: 'cookies aliyundrive_token moviepilot_address 扫码 二维码 扩展名 mkv mp4 srt ass',
  },
  {
    id: 'strm-transfer',
    category: 'category-strm',
    categoryLabel: 'STRM同步',
    subTab: 'tab-transfer',
    subLabel: '监控MP整理',
    title: '监控 MoviePilot 整理事件 · 自动刮削 · CloudDrive2 前缀 · 后处理恢复',
    keywords: 'transfer_monitor_enabled clouddrive2 cd2 神医助手 emby 刮削排除 重新整理 清理失效 恢复',
  },
  {
    id: 'strm-full',
    category: 'category-strm',
    categoryLabel: 'STRM同步',
    subTab: 'tab-sync',
    subLabel: '全量同步',
    title: '定期全量同步 · 覆盖模式 · 失效 STRM 二次验证 · Rust 模式 · 批处理进程数',
    keywords: 'timing_full_sync_strm full_sync_overwrite_mode cron rust iter_files_with_path_skim 阈值 稳定性',
  },
  {
    id: 'strm-inc',
    category: 'category-strm',
    categoryLabel: 'STRM同步',
    subTab: 'tab-increment-sync',
    subLabel: '增量同步',
    title: '定期增量同步 · 二级目录扫描目录树 · 目录树导出超时 · 增量刮削与清理',
    keywords: 'increment_sync_strm_enabled increment_sync_cron itertree 二级目录 增量',
  },
  {
    id: 'strm-life',
    category: 'category-strm',
    categoryLabel: 'STRM同步',
    subTab: 'tab-life',
    subLabel: '监控115生活事件',
    title: '115 生活事件实时监控 · 移动事件策略矩阵 · 重命名同步 · 故障检查',
    keywords: 'monitor_life_enabled recreate local_move 生活事件 上传 删除 移动 重命名 故障检查',
  },
  {
    id: 'strm-api',
    category: 'category-strm',
    categoryLabel: 'STRM同步',
    subTab: 'tab-api-strm',
    subLabel: 'API STRM生成',
    title: '第三方 HTTP API 批量生成 STRM · 路径自动匹配与媒体库刷新',
    keywords: 'api_strm_config api http 第三方 映射',
  },
  {
    id: 'pan-transfer',
    category: 'category-pan',
    categoryLabel: '网盘管理',
    subTab: 'tab-pan-transfer',
    subLabel: '网盘整理',
    title: '网盘待整理目录 · 未识别目录 · 分享转存目录 · 离线下载目录 · 手动整理',
    keywords: 'pan_transfer_enabled pan_transfer_unrecognized_path share_recieve_paths offline_download_paths 秒传',
  },
  {
    id: 'pan-mount',
    category: 'category-pan',
    categoryLabel: '网盘管理',
    subTab: 'tab-pan-mount',
    subLabel: '网盘挂载 (FUSE)',
    title: 'FUSE 本地文件系统挂载 · UID/GID · 接管 STRM 内容 · Emby 反代 302 配置生成',
    keywords: 'fuse_enabled fuse_mountpoint readdir_ttl emby2alist 302 反代 接管规则',
  },
  {
    id: 'pan-upload',
    category: 'category-pan',
    categoryLabel: '网盘管理',
    subTab: 'tab-directory-upload',
    subLabel: '目录上传',
    title: '本地目录监控自动上传 115 · 漏传巡检 · 跳过 BDMV STREAM · 删除源文件',
    keywords: 'directory_upload_enabled compatibility fast bdmv 漏传巡检 上传',
  },
  {
    id: 'other-syncdel',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-sync-del',
    subLabel: '同步删除',
    title: 'Emby 媒体库同步删除 · 删除源文件 · 强制删除 · 多版本安全删除',
    keywords: 'sync_del_enabled sync_del_source 多版本 神医助手 emby 删除',
  },
  {
    id: 'other-search',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-tg-search',
    subLabel: '频道搜索',
    title: '自定义 Telegram 资源频道 · JSON 一键导入 · RE0 搜索 (/sh)',
    keywords: 'tg_search_channels hdhive_search_enabled telegram tg /sh 频道 搜索',
  },
  {
    id: 'other-cleanup',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-cleanup',
    subLabel: '定期清理',
    title: '定时清空 115 回收站与最近接收目录 · 115 安全访问密码',
    keywords: 'clear_recyclebin_enabled clear_receive_path_enabled password 回收站 最近接收',
  },
  {
    id: 'other-playback',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-same-playback',
    subLabel: '多端播放',
    title: '多设备双 IP 同步播放同一影片',
    keywords: 'same_playback 多端 多设备 双IP 播放',
  },
  {
    id: 'other-hdhive',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-hdhive-checkin',
    subLabel: 'RE0 签到',
    title: 'RE0 (原 HDHive) 每日签到与赌狗签到 · 随机时间段 (/hdhivechin)',
    keywords: 'hdhive_checkin re0 签到 赌狗 /hdhivechin',
  },
  {
    id: 'other-p115checkin',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-p115-checkin',
    subLabel: '115 签到',
    title: '115 网盘每日自动随机签到 (/p115_checkin)',
    keywords: 'p115_checkin_enabled 115签到 /p115_checkin',
  },
  {
    id: 'other-utility',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-utility',
    subLabel: '实用工具',
    title: '分享 STRM 覆盖大小检查 · 自动删除低质量源文件 · 媒体库已存在时拦截整理',
    keywords: 'share_strm_overwrite_check auto_delete_inferior_source transfer_intercept_exists ffprobe 拦截 低质量',
  },
  {
    id: 'other-backup',
    category: 'category-other',
    categoryLabel: '其他功能',
    subTab: 'tab-strm-backup',
    subLabel: '本地 STRM 备份',
    title: '本地 STRM 目录打包 tar.gz 备份至本地或 115 网盘 · 定时备份与一键恢复',
    keywords: 'strm_backup_enabled backup tar.gz 备份 恢复',
  },
  {
    id: 'sys-cache',
    category: 'category-system',
    categoryLabel: '系统配置',
    subTab: 'tab-cache-config',
    subLabel: '缓存配置',
    title: '清理文件路径 ID 缓存 · 增量跳过路径缓存 · 302 跳转缓存 · P115Client 缓存',
    keywords: 'cache 缓存 302 id p115client 清理',
  },
  {
    id: 'sys-enhance',
    category: 'category-system',
    categoryLabel: '系统配置',
    subTab: 'tab-data-enhancement',
    subLabel: '数据增强',
    title: '上传模块增强 (秒传等待/复判) · 接管网盘整理 (115网盘Plus) · 媒体元数据补充 · 设备 ID',
    keywords: 'upload_module_enhancement pan_transfer_takeover rename_dict_supplement 115网盘Plus 秒传 ffprobe machine_id sentry',
  },
  {
    id: 'sys-advanced',
    category: 'category-system',
    categoryLabel: '系统配置',
    subTab: 'tab-advanced-configuration',
    subLabel: '高级配置',
    title: '侧栏页面入口 · 原生 Emby 提取 · Jinja2 URL/文件名模板 · 黑白名单 · 请求超时控制',
    keywords: 'sidebar_nav_keys native_emby_mediainfo jinja2 strm_url_template 黑名单 白名单 timeout 超时 编码',
  },
];

export function useConfigSearch() {
  const searchQuery = ref('');

  const searchResults = computed(() => {
    const q = searchQuery.value.trim().toLowerCase();
    if (!q) return [];
    const terms = q.split(/\s+/).filter(Boolean);
    return CONFIG_SEARCH_INDEX.filter((item) => {
      const hay = `${item.categoryLabel} ${item.subLabel} ${item.title} ${item.keywords}`.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  });

  return {
    searchQuery,
    searchResults,
  };
}
