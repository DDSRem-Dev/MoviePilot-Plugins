import { reactive } from 'vue';

/**
 * 目录选择器 Composable
 * 管理本地/网盘目录选择对话框的状态和操作
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
    originalIndexBackup: -1,
  });

  const loadDirContent = async () => {
    dirDialog.loading = true;
    dirDialog.error = null;
    dirDialog.items = [];
    try {
      if (dirDialog.isLocal) {
        try {
          const response = await api.post('storage/list', {
            path: dirDialog.currentPath || '/',
            type: 'share',
            flag: 'ROOT',
          });
          const items = Array.isArray(response) ? response : response?.data;
          if (Array.isArray(items)) {
            dirDialog.items = items
              .filter((item) => item.type === 'dir')
              .map((item) => ({ name: item.name, path: item.path, is_dir: true }))
              .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
          } else {
            throw new Error(response?.message || '浏览目录失败：无效响应');
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
        const result = await api.get(
          `plugin/${PLUGIN_ID}/browse_dir?path=${encodeURIComponent(dirDialog.currentPath)}&is_local=${dirDialog.isLocal}`,
        );

        if (result && result.code === 0 && result.data) {
          dirDialog.items = result.data.items
            .filter((item) => item.is_dir)
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

  const resolveInitialDirPath = (index, isLocal, pathType, fieldKey) => {
    const sideKey = isLocal ? 'local' : 'remote';
    if (pathType === 'transfer' && transferPaths.value?.[index]?.[sideKey]) {
      return transferPaths.value[index][sideKey];
    }
    if (pathType === 'fullSync' && fullSyncPaths.value?.[index]?.[sideKey]) {
      return fullSyncPaths.value[index][sideKey];
    }
    if (pathType === 'incrementSync' && incrementSyncPaths.value?.[index]?.[sideKey]) {
      return incrementSyncPaths.value[index][sideKey];
    }
    if (pathType === 'monitorLife' && monitorLifePaths.value?.[index]?.[sideKey]) {
      return monitorLifePaths.value[index][sideKey];
    }
    if (pathType === 'apiStrm' && apiStrmPaths.value?.[index]?.[sideKey]) {
      return apiStrmPaths.value[index][sideKey];
    }
    if (pathType === 'panTransfer' && panTransferPaths.value?.[index]?.path) {
      return panTransferPaths.value[index].path;
    }
    if (pathType === 'shareReceive' && shareReceivePaths.value?.[index]?.path) {
      return shareReceivePaths.value[index].path;
    }
    if (pathType === 'offlineDownload' && offlineDownloadPaths.value?.[index]?.path) {
      return offlineDownloadPaths.value[index].path;
    }
    if (pathType === 'panTransferUnrecognized' && config.pan_transfer_unrecognized_path) {
      return config.pan_transfer_unrecognized_path;
    }
    if (pathType === 'directoryUpload' && fieldKey && directoryUploadPaths.value?.[index]?.[fieldKey]) {
      return directoryUploadPaths.value[index][fieldKey];
    }
    if (pathType === 'syncDelLibrary' && index >= 0 && syncDelLibraryPaths.value?.[index] && fieldKey) {
      return syncDelLibraryPaths.value[index][fieldKey] || '/';
    }
    if (pathType === 'backupItems' && index >= 0 && fieldKey) {
      const backupItems = config.strm_backup_items;
      return (backupItems && backupItems[index] && backupItems[index][fieldKey]) || '/';
    }
    if (pathType === 'backupSourcePath' && index >= 0 && fieldKey) {
      const backupItems = config.strm_backup_items;
      const srcIndex = parseInt(fieldKey, 10);
      if (backupItems?.[index]?.source_paths && !Number.isNaN(srcIndex)) {
        return backupItems[index].source_paths[srcIndex] || '/';
      }
    }
    return '/';
  };

  const openDirSelector = (index, locationType, pathType, fieldKey = null) => {
    const isLocal = locationType === 'local';
    dirDialog.show = true;
    dirDialog.isLocal = isLocal;
    dirDialog.loading = false;
    dirDialog.error = null;
    dirDialog.items = [];
    dirDialog.index = index;
    dirDialog.type = pathType;
    dirDialog.fieldKey = fieldKey;
    dirDialog.targetConfigKeyForExclusion = null;
    dirDialog.originalPathTypeBackup = '';
    dirDialog.originalIndexBackup = -1;
    dirDialog.currentPath = String(resolveInitialDirPath(index, isLocal, pathType, fieldKey) || '/').trim() || '/';
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
      dirDialog.currentPath = `${parts[0]}:/`;
    } else {
      parts.pop();
      dirDialog.currentPath = parts.length === 0 ? '/' : `${normalizedPath.startsWith('/') ? '/' : ''}${parts.join('/')}/`;
    }
    loadDirContent();
  };

  const confirmDirSelection = () => {
    if (!dirDialog.currentPath) return;
    let processedPath = dirDialog.currentPath;
    if (
      processedPath !== '/' &&
      !/^[a-zA-Z]:[\\\/]$/.test(processedPath) &&
      (processedPath.endsWith('/') || processedPath.endsWith('\\'))
    ) {
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
        } else if (!targetArrayRef.value.some((item) => item.path === processedPath)) {
          targetArrayRef.value.push({ path: processedPath });
        } else {
          message.text = '该排除路径已存在。';
          message.type = 'warning';
          setTimeout(() => { message.text = ''; }, 3000);
        }
      }
      dirDialog.type = dirDialog.originalPathTypeBackup;
      dirDialog.index = dirDialog.originalIndexBackup;
      dirDialog.targetConfigKeyForExclusion = null;
      dirDialog.originalPathTypeBackup = '';
      dirDialog.originalIndexBackup = -1;
    } else if (dirDialog.index >= 0 && dirDialog.type !== 'excludePath') {
      switch (dirDialog.type) {
        case 'transfer':
          if (dirDialog.isLocal) transferPaths.value[dirDialog.index].local = processedPath;
          else transferPaths.value[dirDialog.index].remote = processedPath;
          break;
        case 'fullSync':
          if (dirDialog.isLocal) fullSyncPaths.value[dirDialog.index].local = processedPath;
          else fullSyncPaths.value[dirDialog.index].remote = processedPath;
          break;
        case 'incrementSync':
          if (dirDialog.isLocal) incrementSyncPaths.value[dirDialog.index].local = processedPath;
          else incrementSyncPaths.value[dirDialog.index].remote = processedPath;
          break;
        case 'monitorLife':
          if (dirDialog.isLocal) monitorLifePaths.value[dirDialog.index].local = processedPath;
          else monitorLifePaths.value[dirDialog.index].remote = processedPath;
          break;
        case 'apiStrm':
          if (dirDialog.isLocal) apiStrmPaths.value[dirDialog.index].local = processedPath;
          else apiStrmPaths.value[dirDialog.index].remote = processedPath;
          break;
        case 'panTransfer':
          panTransferPaths.value[dirDialog.index].path = processedPath;
          break;
        case 'shareReceive':
          shareReceivePaths.value[dirDialog.index].path = processedPath;
          break;
        case 'offlineDownload':
          offlineDownloadPaths.value[dirDialog.index].path = processedPath;
          break;
        case 'syncDelLibrary':
          if (dirDialog.index >= 0 && syncDelLibraryPaths.value[dirDialog.index] && dirDialog.fieldKey) {
            syncDelLibraryPaths.value[dirDialog.index][dirDialog.fieldKey] = processedPath;
          }
          break;
        case 'directoryUpload':
          if (dirDialog.fieldKey && directoryUploadPaths.value[dirDialog.index]) {
            directoryUploadPaths.value[dirDialog.index][dirDialog.fieldKey] = processedPath;
          }
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
              if (!Number.isNaN(srcIndex) && srcIndex < item.source_paths.length) {
                item.source_paths[srcIndex] = processedPath;
              }
            }
          }
          break;
      }
    } else if (dirDialog.type === 'panTransferUnrecognized') {
      config.pan_transfer_unrecognized_path = processedPath;
    }
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
