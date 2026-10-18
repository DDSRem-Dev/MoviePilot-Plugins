import { ref, watch } from 'vue';

/**
 * 路径管理 Composable
 * 管理所有路径数组的状态、双向同步监听和增删操作
 * @param {object} config - 插件配置的 reactive 对象
 */
export function usePathManagement(config) {
  // 路径管理 refs
  const transferPaths = ref([{ local: '', remote: '', cd2Prefix: '' }]);
  const transferMpPaths = ref([{ local: '', remote: '' }]);
  const fullSyncPaths = ref([{ local: '', remote: '', enabled: true }]);
  const incrementSyncPaths = ref([{ local: '', remote: '' }]);
  const incrementSyncMPPaths = ref([{ local: '', remote: '' }]);
  const monitorLifePaths = ref([{ local: '', remote: '' }]);
  const monitorLifeMpPaths = ref([{ local: '', remote: '' }]);
  const apiStrmPaths = ref([{ local: '', remote: '' }]);
  const apiStrmMPPaths = ref([{ local: '', remote: '' }]);
  const panTransferPaths = ref([{ path: '' }]);
  const shareReceivePaths = ref([{ path: '' }]);
  const offlineDownloadPaths = ref([{ path: '' }]);
  const transferExcludePaths = ref([{ path: '' }]);
  const incrementSyncExcludePaths = ref([{ local: '', remote: '' }]);
  const monitorLifeExcludePaths = ref([{ path: '' }]);
  const directoryUploadPaths = ref([{ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }]);
  const syncDelLibraryPaths = ref([{ mediaserver: '', moviepilot: '', p115: '' }]);
  const fuseStrmTakeoverRules = ref([{ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }]);

  // ============================================================
  // 工具函数
  // ============================================================

  /** 规范化路径拼接，避免双斜杠，保留前缀的绝对路径（前导 /） */
  const normalizePathJoin = (prefix, rest) => {
    const a = (prefix || '').trim().replace(/\/+$/, '');
    const b = (rest || '').trim().replace(/^\/+/, '').replace(/\/+$/, '');
    if (!b) return a || '';
    return a ? `${a}/${b}` : b;
  };

  const generatePathsConfig = (paths, key) => {
    const configText = paths.map(p => {
      if (key === 'panTransfer') {
        return p.path?.trim();
      }
      if (key === 'fullSync') {
        return `${p.local?.trim()}#${p.remote?.trim()}#${p.enabled !== false ? '1' : '0'}`;
      }
      if (key === 'transfer') {
        const local = p.local?.trim() ?? '';
        const remote = p.remote?.trim() ?? '';
        const cd2 = (p.cd2Prefix || '').trim();
        const effectiveRemote = cd2 ? normalizePathJoin(cd2, remote) : remote;
        return `${local}#${effectiveRemote}#${cd2}`;
      }
      return `${p.local?.trim()}#${p.remote?.trim()}`;
    }).filter(p => {
      if (key === 'panTransfer') {
        return p && p !== '';
      }
      if (key === 'fullSync') {
        const parts = p.split('#');
        return parts.length >= 2 && (parts[0]?.trim() || parts[1]?.trim());
      }
      if (key === 'transfer') {
        const parts = p.split('#');
        return parts.length >= 2 && (parts[0]?.trim() || parts[1]?.trim());
      }
      return p !== '#' && p !== '';
    }).join('\n');

    return configText;
  };

  // ============================================================
  // config 字符串 → 路径数组 (immediate watchers)
  // ============================================================

  watch(() => config.transfer_monitor_paths, (newVal) => {
    if (!newVal) {
      transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      transferPaths.value = paths.map(path => {
        const parts = path.split('#');
        const local = parts[0] || '';
        const fullRemote = parts[1] || '';
        const prefix = parts[2]?.trim() || '';
        let remote = fullRemote;
        if (prefix) {
          const normPrefix = prefix.replace(/^\/+/, '').replace(/\/+$/, '');
          const normFull = fullRemote.replace(/^\/+/, '').replace(/\/+$/, '');
          if (normFull === normPrefix || normFull.startsWith(normPrefix + '/')) {
            const rest = normFull.slice(normPrefix.length);
            remote = (rest.startsWith('/') ? rest : '/' + rest) || '';
          }
        }
        return { local, remote, cd2Prefix: prefix };
      });
      if (transferPaths.value.length === 0) {
        transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
      }
    } catch (e) {
      console.error('解析transfer_monitor_paths出错:', e);
      transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
    }
  }, { immediate: true });

  watch(() => config.transfer_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      transferMpPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      transferMpPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (transferMpPaths.value.length === 0) {
        transferMpPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析transfer_mp_mediaserver_paths出错:', e);
      transferMpPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.full_sync_strm_paths, (newVal) => {
    if (!newVal) {
      fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      fullSyncPaths.value = paths.map(path => {
        const parts = path.split('#');
        // 无第三段（旧格式）或第三段非 '0' 时均为开启；仅第三段为 '0' 时为关闭
        const enabled = parts.length < 3 || parts[2].trim() !== '0';
        return { local: parts[0] || '', remote: parts[1] || '', enabled };
      });
      if (fullSyncPaths.value.length === 0) {
        fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
      }
    } catch (e) {
      console.error('解析full_sync_strm_paths出错:', e);
      fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
    }
  }, { immediate: true });

  watch(() => config.increment_sync_strm_paths, (newVal) => {
    if (!newVal) {
      incrementSyncPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      incrementSyncPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (incrementSyncPaths.value.length === 0) {
        incrementSyncPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析increment_sync_strm_paths出错:', e);
      incrementSyncPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.increment_sync_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      incrementSyncMPPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      incrementSyncMPPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (incrementSyncMPPaths.value.length === 0) {
        incrementSyncMPPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析increment_sync_mp_mediaserver_paths出错:', e);
      incrementSyncMPPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.monitor_life_paths, (newVal) => {
    if (!newVal) {
      monitorLifePaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      monitorLifePaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (monitorLifePaths.value.length === 0) {
        monitorLifePaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析monitor_life_paths出错:', e);
      monitorLifePaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.monitor_life_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      monitorLifeMpPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      monitorLifeMpPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (monitorLifeMpPaths.value.length === 0) {
        monitorLifeMpPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析monitor_life_mp_mediaserver_paths出错:', e);
      monitorLifeMpPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.pan_transfer_paths, (newVal) => {
    if (!newVal) {
      panTransferPaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      panTransferPaths.value = paths.map(path => {
        return { path };
      });
      if (panTransferPaths.value.length === 0) {
        panTransferPaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析pan_transfer_paths出错:', e);
      panTransferPaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(() => config.api_strm_config, (newVal) => {
    if (!newVal || !Array.isArray(newVal)) {
      apiStrmPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      apiStrmPaths.value = newVal.map(item => ({
        local: item.local_path || '',
        remote: item.pan_path || ''
      }));
      if (apiStrmPaths.value.length === 0) {
        apiStrmPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析api_strm_config出错:', e);
      apiStrmPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.sync_del_p115_library_path, (newVal) => {
    if (!newVal) {
      syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      syncDelLibraryPaths.value = paths.map(path => {
        const parts = path.split('#');
        return {
          mediaserver: parts[0] || '',
          moviepilot: parts[1] || '',
          p115: parts[2] || ''
        };
      });
      if (syncDelLibraryPaths.value.length === 0) {
        syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
      }
    } catch (e) {
      console.error('解析sync_del_p115_library_path出错:', e);
      syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
    }
  }, { immediate: true });

  watch(() => config.api_strm_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      apiStrmMPPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      apiStrmMPPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (apiStrmMPPaths.value.length === 0) {
        apiStrmMPPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析api_strm_mp_mediaserver_paths出错:', e);
      apiStrmMPPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.share_recieve_paths, (newVal) => {
    if (!newVal || !Array.isArray(newVal)) {
      shareReceivePaths.value = [{ path: '' }];
      return;
    }
    try {
      shareReceivePaths.value = newVal.map(path => {
        return { path: typeof path === 'string' ? path : '' };
      });
      if (shareReceivePaths.value.length === 0) {
        shareReceivePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析share_recieve_paths出错:', e);
      shareReceivePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(() => config.offline_download_paths, (newVal) => {
    if (!newVal || !Array.isArray(newVal)) {
      offlineDownloadPaths.value = [{ path: '' }];
      return;
    }
    try {
      offlineDownloadPaths.value = newVal.map(path => {
        return { path: typeof path === 'string' ? path : '' };
      });
      if (offlineDownloadPaths.value.length === 0) {
        offlineDownloadPaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析offline_download_paths出错:', e);
      offlineDownloadPaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(() => config.transfer_monitor_scrape_metadata_exclude_paths, (newVal) => {
    if (typeof newVal !== 'string' || !newVal.trim()) {
      transferExcludePaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      transferExcludePaths.value = paths.map(p => ({ path: p }));
      if (transferExcludePaths.value.length === 0) {
        transferExcludePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析 transfer_monitor_scrape_metadata_exclude_paths 出错:', e);
      transferExcludePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(transferExcludePaths, (newVal) => {
    if (!Array.isArray(newVal)) return;
    const pathsString = newVal
      .map(item => item.path?.trim())
      .filter(p => p)
      .join('\n');
    if (config.transfer_monitor_scrape_metadata_exclude_paths !== pathsString) {
      config.transfer_monitor_scrape_metadata_exclude_paths = pathsString;
    }
  }, { deep: true });

  watch(() => config.increment_sync_scrape_metadata_exclude_paths, (newVal) => {
    if (typeof newVal !== 'string' || !newVal.trim()) {
      incrementSyncExcludePaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      incrementSyncExcludePaths.value = paths.map(p => ({ path: p }));
      if (incrementSyncExcludePaths.value.length === 0) {
        incrementSyncExcludePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析 increment_sync_scrape_metadata_exclude_paths 出错:', e);
      incrementSyncExcludePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(incrementSyncExcludePaths, (newVal) => {
    if (!Array.isArray(newVal)) return;
    const pathsString = newVal
      .map(item => item.path?.trim())
      .filter(p => p)
      .join('\n');
    if (config.increment_sync_scrape_metadata_exclude_paths !== pathsString) {
      config.increment_sync_scrape_metadata_exclude_paths = pathsString;
    }
  }, { deep: true });

  watch(() => config.monitor_life_scrape_metadata_exclude_paths, (newVal) => {
    if (typeof newVal !== 'string' || !newVal.trim()) {
      monitorLifeExcludePaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      monitorLifeExcludePaths.value = paths.map(p => ({ path: p }));
      if (monitorLifeExcludePaths.value.length === 0) {
        monitorLifeExcludePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析 monitor_life_scrape_metadata_exclude_paths 出错:', e);
      monitorLifeExcludePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(monitorLifeExcludePaths, (newVal) => {
    if (!Array.isArray(newVal)) return;
    const pathsString = newVal
      .map(item => item.path?.trim())
      .filter(p => p)
      .join('\n');
    if (config.monitor_life_scrape_metadata_exclude_paths !== pathsString) {
      config.monitor_life_scrape_metadata_exclude_paths = pathsString;
    }
  }, { deep: true });

  // 监听 full_sync_remove_unless_strm 变化，当禁用时自动禁用依赖的配置项
  watch(() => config.full_sync_remove_unless_strm, (newVal) => {
    if (!newVal) {
      config.full_sync_remove_unless_dir = false;
      config.full_sync_remove_unless_file = false;
      config.full_sync_cleanup_confirm_mode = "none";
    }
  });

  // 监听 increment_sync_remove_unless_strm 变化，当禁用时自动禁用依赖的配置项
  watch(() => config.increment_sync_remove_unless_strm, (newVal) => {
    if (!newVal) {
      config.increment_sync_remove_unless_dir = false;
      config.increment_sync_remove_unless_file = false;
    }
  });

  // ============================================================
  // 路径增删函数
  // ============================================================

  const addPath = (type) => {
    switch (type) {
      case 'transfer': transferPaths.value.push({ local: '', remote: '', cd2Prefix: '' }); break;
      case 'mp': transferMpPaths.value.push({ local: '', remote: '' }); break;
      case 'fullSync': fullSyncPaths.value.push({ local: '', remote: '', enabled: true }); break;
      case 'incrementSync': incrementSyncPaths.value.push({ local: '', remote: '' }); break;
      case 'increment-mp': incrementSyncMPPaths.value.push({ local: '', remote: '' }); break;
      case 'monitorLife': monitorLifePaths.value.push({ local: '', remote: '' }); break;
      case 'monitorLifeMp': monitorLifeMpPaths.value.push({ local: '', remote: '' }); break;
      case 'apiStrm': apiStrmPaths.value.push({ local: '', remote: '' }); break;
      case 'apiStrm-mp': apiStrmMPPaths.value.push({ local: '', remote: '' }); break;
      case 'syncDelLibrary': syncDelLibraryPaths.value.push({ mediaserver: '', moviepilot: '', p115: '' }); break;
      case 'directoryUpload': directoryUploadPaths.value.push({ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }); break;
      case 'fuseStrmTakeover': fuseStrmTakeoverRules.value.push({ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }); break;
    }
  };

  const removePath = (index, type) => {
    switch (type) {
      case 'transfer':
        transferPaths.value.splice(index, 1);
        if (transferPaths.value.length === 0) transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
        break;
      case 'mp':
        transferMpPaths.value.splice(index, 1);
        if (transferMpPaths.value.length === 0) transferMpPaths.value = [{ local: '', remote: '' }];
        break;
      case 'fullSync':
        fullSyncPaths.value.splice(index, 1);
        if (fullSyncPaths.value.length === 0) fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
        break;
      case 'incrementSync':
        incrementSyncPaths.value.splice(index, 1);
        if (incrementSyncPaths.value.length === 0) incrementSyncPaths.value = [{ local: '', remote: '' }];
        break;
      case 'increment-mp':
        incrementSyncMPPaths.value.splice(index, 1);
        if (incrementSyncMPPaths.value.length === 0) incrementSyncMPPaths.value = [{ local: '', remote: '' }];
        break;
      case 'monitorLife':
        monitorLifePaths.value.splice(index, 1);
        if (monitorLifePaths.value.length === 0) monitorLifePaths.value = [{ local: '', remote: '' }];
        break;
      case 'monitorLifeMp':
        monitorLifeMpPaths.value.splice(index, 1);
        if (monitorLifeMpPaths.value.length === 0) monitorLifeMpPaths.value = [{ local: '', remote: '' }];
        break;
      case 'apiStrm':
        apiStrmPaths.value.splice(index, 1);
        if (apiStrmPaths.value.length === 0) apiStrmPaths.value = [{ local: '', remote: '' }];
        break;
      case 'apiStrm-mp':
        apiStrmMPPaths.value.splice(index, 1);
        if (apiStrmMPPaths.value.length === 0) apiStrmMPPaths.value = [{ local: '', remote: '' }];
        break;
      case 'syncDelLibrary':
        syncDelLibraryPaths.value.splice(index, 1);
        if (syncDelLibraryPaths.value.length === 0) syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
        break;
      case 'directoryUpload':
        directoryUploadPaths.value.splice(index, 1);
        if (directoryUploadPaths.value.length === 0) directoryUploadPaths.value = [{ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }];
        break;
      case 'fuseStrmTakeover':
        fuseStrmTakeoverRules.value.splice(index, 1);
        if (fuseStrmTakeoverRules.value.length === 0) fuseStrmTakeoverRules.value = [{ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }];
        break;
    }
  };

  const addPanTransferPath = () => { panTransferPaths.value.push({ path: '' }); };
  const removePanTransferPath = (index) => {
    panTransferPaths.value.splice(index, 1);
    if (panTransferPaths.value.length === 0) panTransferPaths.value = [{ path: '' }];
  };

  const addShareReceivePath = () => { shareReceivePaths.value.push({ path: '' }); };
  const removeShareReceivePath = (index) => {
    shareReceivePaths.value.splice(index, 1);
    if (shareReceivePaths.value.length === 0) shareReceivePaths.value = [{ path: '' }];
  };

  const addOfflineDownloadPath = () => { offlineDownloadPaths.value.push({ path: '' }); };
  const removeOfflineDownloadPath = (index) => {
    offlineDownloadPaths.value.splice(index, 1);
    if (offlineDownloadPaths.value.length === 0) offlineDownloadPaths.value = [{ path: '' }];
  };

  return {
    // Path refs
    transferPaths,
    transferMpPaths,
    fullSyncPaths,
    incrementSyncPaths,
    incrementSyncMPPaths,
    monitorLifePaths,
    monitorLifeMpPaths,
    apiStrmPaths,
    apiStrmMPPaths,
    panTransferPaths,
    shareReceivePaths,
    offlineDownloadPaths,
    transferExcludePaths,
    incrementSyncExcludePaths,
    monitorLifeExcludePaths,
    directoryUploadPaths,
    syncDelLibraryPaths,
    fuseStrmTakeoverRules,
    // Utility functions
    normalizePathJoin,
    generatePathsConfig,
    // Add/remove functions
    addPath,
    removePath,
    addPanTransferPath,
    removePanTransferPath,
    addShareReceivePath,
    removeShareReceivePath,
    addOfflineDownloadPath,
    removeOfflineDownloadPath,
  };
}
