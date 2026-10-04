import { reactive } from 'vue';

/**
 * 目录选择器 Composable
 * 管理本地/网盘目录选择对话框的状态和操作
 * @param {object|Function} api - MoviePilot API 对象
 * @param {object} config - 插件配置的 reactive 对象
 * @param {object} message - 消息提示的 reactive 对象
 * @param {string} PLUGIN_ID - 插件ID
 * @param {object} pathRefs - 路径管理 composable 返回的所有路径 refs
 */
export function useDirSelector(api, config, message, PLUGIN_ID, pathRefs) {
  const {
    transferPaths,
    fullSyncPaths,
    incrementSyncPaths,
    monitorLifePaths,
    apiStrmPaths,
    panTransferPaths,
    shareReceivePaths,
    offlineDownloadPaths,
    syncDelLibraryPaths,
    directoryUploadPaths,
    transferExcludePaths,
    incrementSyncExcludePaths,
    monitorLifeExcludePaths,
  } = pathRefs;

  // 目录选择器对话框状态
  const dirDialog = reactive({
    show: false,
    isLocal: true,
    loading: false,
    error: null,
    currentPath: '/',
    items: [],
    selectedPath: '',
    callback: null,
    type: '',
    index: -1,
    fieldKey: null,
    targetConfigKeyForExclusion: null,
    originalPathTypeBackup: '',
    originalIndexBackup: -1
  });

  const loadDirContent = async () => {
    dirDialog.loading = true;
    dirDialog.error = null;
    dirDialog.items = [];
    try {
      if (dirDialog.isLocal) {
        try {
          const response = await api.post('storage/list', { path: dirDialog.currentPath || '/', type: 'share', flag: 'ROOT' });
          // MoviePilot V3 的 storage/list 返回包装结构 {success,message,data}，V2 及更早版本返回裸数组，此处统一取数组。
          // 使用 Array.isArray 逐层判定而非真值判定，避免 V3 空目录(data=[])被误判为无效响应。
          const storageList = Array.isArray(response) ? response : (response && Array.isArray(response.data) ? response.data : null);
          if (Array.isArray(storageList)) {
            dirDialog.items = storageList
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
        if (!config.cookies || config.cookies.trim() === '') {
          throw new Error('请先设置115 Cookie才能浏览网盘目录');
        }
        const result = await api.get(`plugin/${PLUGIN_ID}/browse_dir?path=${encodeURIComponent(dirDialog.currentPath)}&is_local=${dirDialog.isLocal}`);

        if (result && result.code === 0 && result.data) {
          dirDialog.items = result.data.items
            .filter(item => item.is_dir)
            .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
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

  const openDirSelector = (index, locationType, pathType, fieldKey = null) => {
    dirDialog.show = true;
    dirDialog.isLocal = locationType === 'local';
    dirDialog.loading = false;
    dirDialog.error = null;
    dirDialog.items = [];
    dirDialog.index = index;
    dirDialog.type = pathType;
    dirDialog.fieldKey = fieldKey;
    dirDialog.targetConfigKeyForExclusion = null;
    dirDialog.originalPathTypeBackup = '';
    dirDialog.originalIndexBackup = -1;

    // 设置初始路径
    if (pathType === 'syncDelLibrary' && index >= 0 && syncDelLibraryPaths.value[index] && fieldKey) {
      const currentPath = syncDelLibraryPaths.value[index][fieldKey] || '/';
      dirDialog.currentPath = currentPath;
    } else if (pathType === 'backupItems' && index >= 0 && fieldKey) {
      const backupItems = config.strm_backup_items;
      if (backupItems && backupItems[index]) {
        const currentPath = backupItems[index][fieldKey] || '/';
        dirDialog.currentPath = currentPath;
      } else {
        dirDialog.currentPath = '/';
      }
    } else if (pathType === 'backupSourcePath' && index >= 0 && fieldKey) {
      const backupItems = config.strm_backup_items;
      if (backupItems && backupItems[index] && backupItems[index].source_paths) {
        const srcIndex = parseInt(fieldKey, 10);
        if (!isNaN(srcIndex) && backupItems[index].source_paths[srcIndex]) {
          dirDialog.currentPath = backupItems[index].source_paths[srcIndex];
        } else {
          dirDialog.currentPath = '/';
        }
      } else {
        dirDialog.currentPath = '/';
      }
    } else {
      dirDialog.currentPath = '/';
    }

    loadDirContent();
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
    if (dirDialog.type === 'excludePath' && dirDialog.targetConfigKeyForExclusion) {
      const targetKey = dirDialog.targetConfigKeyForExclusion;
      let targetArrayRef;
      if (targetKey === 'transfer_monitor_scrape_metadata_exclude_paths') targetArrayRef = transferExcludePaths;
      else if (targetKey === 'monitor_life_scrape_metadata_exclude_paths') targetArrayRef = monitorLifeExcludePaths;
      else if (targetKey === 'increment_sync_scrape_metadata_exclude_paths') targetArrayRef = incrementSyncExcludePaths;
      if (targetArrayRef) {
        if (targetArrayRef.value.length === 1 && !targetArrayRef.value[0].path) {
          targetArrayRef.value[0] = { path: processedPath };
        } else {
          if (!targetArrayRef.value.some(item => item.path === processedPath)) {
            targetArrayRef.value.push({ path: processedPath });
          } else {
            message.text = '该排除路径已存在。';
            message.type = 'warning';
            setTimeout(() => { message.text = ''; }, 3000);
          }
        }
      }
      dirDialog.type = dirDialog.originalPathTypeBackup;
      dirDialog.index = dirDialog.originalIndexBackup;
      dirDialog.targetConfigKeyForExclusion = null;
      dirDialog.originalPathTypeBackup = '';
      dirDialog.originalIndexBackup = -1;
    }
    else if (dirDialog.index >= 0 && dirDialog.type !== 'excludePath') {
      switch (dirDialog.type) {
        case 'transfer': dirDialog.isLocal ? transferPaths.value[dirDialog.index].local = processedPath : transferPaths.value[dirDialog.index].remote = processedPath; break;
        case 'fullSync': dirDialog.isLocal ? fullSyncPaths.value[dirDialog.index].local = processedPath : fullSyncPaths.value[dirDialog.index].remote = processedPath; break;
        case 'incrementSync': dirDialog.isLocal ? incrementSyncPaths.value[dirDialog.index].local = processedPath : incrementSyncPaths.value[dirDialog.index].remote = processedPath; break;
        case 'monitorLife': dirDialog.isLocal ? monitorLifePaths.value[dirDialog.index].local = processedPath : monitorLifePaths.value[dirDialog.index].remote = processedPath; break;
        case 'apiStrm': dirDialog.isLocal ? apiStrmPaths.value[dirDialog.index].local = processedPath : apiStrmPaths.value[dirDialog.index].remote = processedPath; break;
        case 'panTransfer': panTransferPaths.value[dirDialog.index].path = processedPath; break;
        case 'shareReceive': shareReceivePaths.value[dirDialog.index].path = processedPath; break;
        case 'offlineDownload': offlineDownloadPaths.value[dirDialog.index].path = processedPath; break;
        case 'syncDelLibrary':
          if (dirDialog.index >= 0 && syncDelLibraryPaths.value[dirDialog.index] && dirDialog.fieldKey) {
            syncDelLibraryPaths.value[dirDialog.index][dirDialog.fieldKey] = processedPath;
          }
          break;
        case 'directoryUpload':
          if (dirDialog.fieldKey && directoryUploadPaths.value[dirDialog.index]) directoryUploadPaths.value[dirDialog.index][dirDialog.fieldKey] = processedPath;
          break;
        case 'backupItems':
          if (dirDialog.index >= 0 && dirDialog.fieldKey) {
            const backupItems = config.strm_backup_items;
            if (backupItems && backupItems[dirDialog.index]) {
              backupItems[dirDialog.index][dirDialog.fieldKey] = processedPath;
            }
          }
          break;
        case 'backupSourcePath':
          if (dirDialog.index >= 0 && dirDialog.fieldKey) {
            const backupItems = config.strm_backup_items;
            const item = backupItems && backupItems[dirDialog.index];
            if (item && item.source_paths) {
              const srcIndex = parseInt(dirDialog.fieldKey, 10);
              if (!isNaN(srcIndex) && srcIndex < item.source_paths.length) {
                item.source_paths[srcIndex] = processedPath;
              }
            }
          }
          break;
      }
    }
    else if (dirDialog.type === 'panTransferUnrecognized') config.pan_transfer_unrecognized_path = processedPath;
    closeDirDialog();
  };

  const closeDirDialog = () => {
    dirDialog.show = false;
    dirDialog.items = [];
    dirDialog.error = null;
  };

  const openExcludeDirSelector = (configKeyToUpdate) => {
    dirDialog.show = true;
    dirDialog.isLocal = true;
    dirDialog.loading = false;
    dirDialog.error = null;
    dirDialog.items = [];
    dirDialog.currentPath = '/';
    dirDialog.originalPathTypeBackup = dirDialog.type;
    dirDialog.originalIndexBackup = dirDialog.index;
    dirDialog.targetConfigKeyForExclusion = configKeyToUpdate;
    dirDialog.type = 'excludePath';
    dirDialog.index = -1;
    loadDirContent();
  };

  const removeExcludePathEntry = (index, type) => {
    let targetArrayRef;
    if (type === 'transfer_exclude') targetArrayRef = transferExcludePaths;
    else if (type === 'life_exclude') targetArrayRef = monitorLifeExcludePaths;
    else if (type === 'increment_exclude') targetArrayRef = incrementSyncExcludePaths;
    if (targetArrayRef && targetArrayRef.value && index < targetArrayRef.value.length) {
      targetArrayRef.value.splice(index, 1);
      if (targetArrayRef.value.length === 0) targetArrayRef.value = [{ path: '' }];
    }
  };

  return {
    dirDialog,
    openDirSelector,
    loadDirContent,
    selectDir,
    navigateToParentDir,
    confirmDirSelection,
    closeDirDialog,
    openExcludeDirSelector,
    removeExcludePathEntry,
  };
}
