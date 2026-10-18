/**
 * STRM 执行历史展示用常量与解析（与 AppPageStart 保持一致，供仪表盘等复用）
 */

export const KIND_LABELS = {
  full: "全量同步",
  increment: "增量同步",
  share: "分享同步",
  share_interactive: "分享交互",
  full_partial: "全量分段",
};

export const STAT_FIELD_META = [
  { key: "strm_count", label: "STRM 生成" },
  { key: "mediainfo_count", label: "下载媒体数据文件" },
  { key: "strm_fail_count", label: "STRM 失败" },
  { key: "mediainfo_fail_count", label: "下载媒体数据失败" },
  { key: "remove_unless_strm_count", label: "清理失效 STRM" },
  { key: "strm_cleanup_deferred_count", label: "待二次确认清理" },
];

const KINDS_WITH_REMOVE_UNLESS_STRM = new Set(["full", "full_partial"]);

export const EXTRA_LABELS = {
  share_url: "分享链接",
  arg_str: "任务参数",
};

export function kindLabel(kind) {
  if (!kind) return "未知";
  return KIND_LABELS[kind] || kind;
}

export function truncateText(s, max) {
  if (s == null) return "";
  const t = String(s);
  if (t.length <= max) return t;
  return `${t.slice(0, Math.max(0, max - 1))}…`;
}

export function formatStatValue(v) {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isNaN(n)) {
    if (Number.isInteger(n)) return String(n);
    return n.toFixed(2);
  }
  return String(v);
}

export function parseStatsEntries(stats, kind) {
  if (!stats || typeof stats !== "object") return [];
  const showRemoveUnless = kind && KINDS_WITH_REMOVE_UNLESS_STRM.has(kind);
  const seen = new Set();
  const ordered = [];
  for (const { key, label } of STAT_FIELD_META) {
    if (key === "remove_unless_strm_count" && !showRemoveUnless) continue;
    if (key === "strm_cleanup_deferred_count" && !showRemoveUnless) continue;
    if (Object.prototype.hasOwnProperty.call(stats, key)) {
      seen.add(key);
      ordered.push({ key, label, value: stats[key] });
    }
  }
  for (const [key, value] of Object.entries(stats)) {
    if (seen.has(key)) continue;
    if (key === "remove_unless_strm_count" && !showRemoveUnless) continue;
    if (key === "strm_cleanup_deferred_count" && !showRemoveUnless) continue;
    ordered.push({ key, label: key, value });
  }
  return ordered;
}

export function statChipColor(s) {
  const n = Number(s.value);
  if ((s.key.includes("fail") || s.key.endsWith("_fail_count")) && !Number.isNaN(n) && n > 0) {
    return "error";
  }
  if (s.key === "remove_unless_strm_count" && !Number.isNaN(n) && n > 0) return "warning";
  if (s.key === "strm_cleanup_deferred_count" && !Number.isNaN(n) && n > 0) return "warning";
  return "primary";
}

export function parseExtraEntries(extra) {
  if (!extra || typeof extra !== "object") return [];
  const out = [];
  const used = new Set();
  if (extra.share_url) {
    used.add("share_url");
    const url = String(extra.share_url);
    const href = /^https?:\/\//i.test(url) ? url : null;
    out.push({
      label: EXTRA_LABELS.share_url || "分享链接",
      display: truncateText(url, 96),
      full: url,
      href,
    });
  }
  if (extra.arg_str != null && extra.arg_str !== "") {
    used.add("arg_str");
    const t = String(extra.arg_str);
    out.push({
      label: EXTRA_LABELS.arg_str || "任务参数",
      display: truncateText(t, 160),
      full: t,
      href: null,
    });
  }
  for (const [k, v] of Object.entries(extra)) {
    if (used.has(k)) continue;
    let str;
    if (v != null && typeof v === "object") {
      try {
        str = JSON.stringify(v);
      } catch {
        str = String(v);
      }
    } else {
      str = String(v);
    }
    out.push({
      label: EXTRA_LABELS[k] || k,
      display: truncateText(str, 160),
      full: str,
      href: null,
    });
  }
  return out;
}

export function formatNum(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const x = Number(n);
  return Number.isInteger(x) ? String(x) : x.toFixed(2);
}
