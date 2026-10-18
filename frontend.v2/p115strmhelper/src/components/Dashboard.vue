<template>
  <div class="p115-dashboard-widget d-flex flex-column h-100 w-100" style="min-block-size: 0">
    <DashboardStrmPanel v-if="panelKey === 'strm'" :api="api" :config="config" :allow-refresh="allowRefresh"
      :refresh-interval="refreshInterval" />
    <DashboardStatusPanel v-else-if="panelKey === 'status'" :api="api" :config="config" :allow-refresh="allowRefresh"
      :refresh-interval="refreshInterval" />
    <DashboardSyncDelPanel v-else-if="panelKey === 'sync_del'" :api="api" :config="config" :allow-refresh="allowRefresh"
      :refresh-interval="refreshInterval" />
    <DashboardManualTransferPanel v-else-if="panelKey === 'manual_transfer'" :api="api" :config="config"
      :allow-refresh="allowRefresh" />
    <DashboardFullSyncPanel v-else-if="panelKey === 'full_sync_actions'" :api="api" :config="config"
      :allow-refresh="allowRefresh" />
  </div>
</template>

<script setup>
import { computed, onMounted } from "vue";
import DashboardStrmPanel from "./dashboard/DashboardStrmPanel.vue";
import DashboardStatusPanel from "./dashboard/DashboardStatusPanel.vue";
import DashboardSyncDelPanel from "./dashboard/DashboardSyncDelPanel.vue";
import DashboardManualTransferPanel from "./dashboard/DashboardManualTransferPanel.vue";
import DashboardFullSyncPanel from "./dashboard/DashboardFullSyncPanel.vue";

const props = defineProps({
  api: {
    type: [Object, Function],
    required: true,
  },
  config: {
    type: Object,
    default: () => ({ attrs: {} }),
  },
  allowRefresh: {
    type: Boolean,
    default: false,
  },
  refreshInterval: {
    type: Number,
    default: 0,
  },
});

/** 与后端 get_dashboard_meta 的 key 一致 */
const panelKey = computed(() => {
  const k = (props.config?.key ?? "").trim();
  if (k === "status") return "status";
  if (k === "sync_del") return "sync_del";
  if (k === "manual_transfer") return "manual_transfer";
  if (k === "full_sync_actions") return "full_sync_actions";
  return "strm";
});

onMounted(() => {
});
</script>

<style>
@import "./dashboard/dashboard-panels.css";
</style>
