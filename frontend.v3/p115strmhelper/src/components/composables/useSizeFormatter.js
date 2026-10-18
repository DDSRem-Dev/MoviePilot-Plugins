/**
 * 文件大小格式化 Composable
 * 提供字节大小的解析与格式化工具函数
 */
export function useSizeFormatter() {
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
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'K', 'M', 'G', 'T'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const formattedNum = parseFloat((bytes / Math.pow(k, i)).toFixed(dm));
    return `${formattedNum} ${sizes[i]}`;
  };

  return { parseSize, formatBytes };
}
