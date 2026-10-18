<template>
  <v-app>
    <div class="plugin-app">
      <component :is="currentComponent" :api="api" @switch="switchComponent" @close="closeModal" @save="saveConfig">
      </component>
    </div>
  </v-app>
</template>

<script>
import { defineComponent, ref, shallowRef, onMounted, onBeforeUnmount, onErrorCaptured } from 'vue';
import Page from './components/Page.vue';
import Config from './components/Config.vue';

export default defineComponent({
  name: 'App',

  setup() {
    const currentComponent = shallowRef(Page);
    const api = ref(null);

    const handleMessage = (event) => {
      if (event.data && event.data.type === 'api') {
        api.value = event.data.data;
      }

      if (event.data && event.data.type === 'showConfig') {
        currentComponent.value = Config;
      }
    };

    const switchComponent = () => {
      currentComponent.value = currentComponent.value === Page ? Config : Page;
    };

    const closeModal = () => {
      if (window.parent && window.parent.postMessage) {
        window.parent.postMessage({ type: 'close' }, '*');
      }
    };

    const saveConfig = (config) => {
      if (window.parent && window.parent.postMessage) {
        window.parent.postMessage({ type: 'save', data: config }, '*');
      }
      currentComponent.value = Page;
    };

    onErrorCaptured((err, instance, info) => {
      console.error('[Error]', err, info);
      return true;
    });

    onMounted(() => {
      window.addEventListener('message', handleMessage);

      if (window.parent && window.parent.postMessage) {
        window.parent.postMessage({ type: 'ready' }, '*');
      }
    });

    onBeforeUnmount(() => {
      window.removeEventListener('message', handleMessage);
    });

    return {
      currentComponent,
      api,
      switchComponent,
      closeModal,
      saveConfig
    };
  }
});
</script>

<style>
/* ============================================
   全局样式 - 镜面效果 + 蓝粉白配色
   主题色: #5bcffa (蓝) / #f5abb9 (粉) / #ffb8c9 (粉强调)
   ============================================ */

/* 全局字体定义 */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* 全局背景渐变 - 蓝粉白配色（增强对比度）；外层锁定视口高度，避免 iOS 整体滚动 */
:deep(.v-application) {
  background: linear-gradient(135deg, #D0EFFF 0%, #FFE5EB 50%, #FFFFFF 100%) !important;
  background-attachment: fixed;
  height: 100% !important;
  min-height: 0 !important;
  max-height: 100% !important;
  width: 100%;
  max-width: 100vw;
  box-sizing: border-box;
  overflow: hidden !important;
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

.plugin-app {
  width: 100%;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: transparent;
  position: relative;
  box-sizing: border-box;
  overflow: hidden;
}

/* 子组件根节点填满并传递高度约束，仅内部区域滚动 */
.plugin-app>* {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 添加动态背景装饰 */
.plugin-app::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(circle at 20% 50%, rgba(91, 207, 250, 0.2) 0%, transparent 50%),
    radial-gradient(circle at 80% 80%, rgba(245, 171, 185, 0.2) 0%, transparent 50%),
    radial-gradient(circle at 40% 20%, rgba(255, 184, 201, 0.15) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
  animation: backgroundPulse 8s ease-in-out infinite;
}

/* 背景装饰动画 */
@keyframes backgroundPulse {

  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.8;
    transform: scale(1.02);
  }
}

/* 全局平滑过渡效果 - 使用弹性缓动函数 */
* {
  transition-timing-function: cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* 全局字体优化 */
:deep(.v-application) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}

/* 全局标题字体 */
:deep(h1),
:deep(h2),
:deep(h3),
:deep(h4),
:deep(h5),
:deep(h6) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
  font-weight: 600 !important;
  letter-spacing: -0.02em !important;
  line-height: 1.3 !important;
}

/* 全局正文字体 */
:deep(p),
:deep(span),
:deep(div) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局按钮字体 */
:deep(.v-btn) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
  font-weight: 500 !important;
  letter-spacing: 0.02em !important;
}

/* 全局输入框字体 */
:deep(.v-field__input),
:deep(.v-label) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局列表字体 */
:deep(.v-list-item-title),
:deep(.v-list-item-subtitle) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局卡片字体 */
:deep(.v-card-title),
:deep(.v-card-text) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局标签字体 */
:deep(.v-tab) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
  font-weight: 500 !important;
  letter-spacing: 0.01em !important;
}

/* 全局芯片字体 */
:deep(.v-chip) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
  font-weight: 500 !important;
}

/* 全局警告字体 */
:deep(.v-alert) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局菜单字体 */
:deep(.v-menu),
:deep(.v-list) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局对话框字体 */
:deep(.v-dialog) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局表格字体 */
:deep(.v-data-table) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局工具提示字体 */
:deep(.v-tooltip) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局展开面板字体 */
:deep(.v-expansion-panel-title),
:deep(.v-expansion-panel-text) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局选择器字体 */
:deep(.v-select),
:deep(.v-autocomplete),
:deep(.v-combobox) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局文本域字体 */
:deep(.v-textarea) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局开关字体 */
:deep(.v-switch__label) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局单选框/复选框字体 */
:deep(.v-radio),
:deep(.v-checkbox) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局分页字体 */
:deep(.v-pagination) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局进度条字体 */
:deep(.v-progress-linear__content) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局骨架屏字体 */
:deep(.v-skeleton-loader) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局时间线字体 */
:deep(.v-timeline) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局滑块字体 */
:deep(.v-slider) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局文件输入字体 */
:deep(.v-file-input) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局颜色输入字体 */
:deep(.v-color-picker) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局日期选择器字体 */
:deep(.v-date-picker) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局时间选择器字体 */
:deep(.v-time-picker) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局评分字体 */
:deep(.v-rating) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局轮播字体 */
:deep(.v-carousel) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局步进器字体 */
:deep(.v-stepper) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局底部导航字体 */
:deep(.v-bottom-navigation) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局应用栏字体 */
:deep(.v-app-bar) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局导航抽屉字体 */
:deep(.v-navigation-drawer) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局系统栏字体 */
:deep(.v-system-bar) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局工具栏字体 */
:deep(.v-toolbar) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局浮动操作按钮字体 */
:deep(.v-btn--fab) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局图标字体 */
:deep(.v-icon) {
  font-family: 'Material Design Icons' !important;
}

/* 全局徽章字体 */
:deep(.v-badge__badge) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
  font-weight: 600 !important;
}

/* 全局横幅字体 */
:deep(.v-banner) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局分割线字体 */
:deep(.v-divider) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局图片字体 */
:deep(.v-img__placeholder) {
  font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif !important;
}

/* 全局响应式字体大小 */
@media (max-width: 768px) {
  :deep(.v-application) {
    font-size: 14px !important;
  }
}

@media (max-width: 480px) {
  :deep(.v-application) {
    font-size: 13px !important;
  }
}

/* 优化滚动条样式 - 蓝粉配色 */
:deep(::-webkit-scrollbar) {
  width: 8px;
  height: 8px;
}

:deep(::-webkit-scrollbar-track) {
  background: rgba(91, 207, 250, 0.05);
  border-radius: 4px;
}

:deep(::-webkit-scrollbar-thumb) {
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.7), rgba(245, 171, 185, 0.7));
  border-radius: 4px;
  transition: background 0.2s ease;
}

:deep(::-webkit-scrollbar-thumb:hover) {
  background: linear-gradient(135deg, rgba(91, 207, 250, 0.9), rgba(245, 171, 185, 0.9));
}

/* 移动端优化 */
@media (max-width: 768px) {

  /* 优化滚动条在移动端（更细） */
  :deep(::-webkit-scrollbar) {
    width: 4px;
    height: 4px;
  }

  /* 确保触摸事件正常工作 */
  * {
    -webkit-tap-highlight-color: rgba(91, 207, 250, 0.1);
    tap-highlight-color: rgba(91, 207, 250, 0.1);
  }

  /* 优化文本选择 - 动态适配主题 */
  ::selection {
    background: rgba(91, 207, 250, 0.3);
    color: inherit;
  }

  ::-moz-selection {
    background: rgba(91, 207, 250, 0.3);
    color: inherit;
  }

  /* 防止文本在移动端被放大 */
  input[type="text"],
  input[type="password"],
  input[type="email"],
  input[type="number"],
  textarea,
  select {
    font-size: 16px !important;
  }

  /* 移动端背景优化 */
  :deep(.v-application) {
    background: linear-gradient(135deg, #D0EFFF 0%, #FFE5EB 50%, #FFFFFF 100%) !important;
  }
}

/* 小屏幕优化 */
@media (max-width: 600px) {

  /* 进一步优化 */
  .plugin-app {
    overflow-x: hidden;
  }
}

/* 全局菜单和弹出层镜面效果 - 动态适配主题 */
:deep(.v-menu .v-overlay__content),
:deep(.v-dialog .v-overlay__content),
:deep(.v-navigation-drawer),
:deep(.v-sheet.v-menu) {
  background: rgba(var(--v-theme-surface), 0.85) !important;
  backdrop-filter: blur(20px) saturate(180%) !important;
  -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12) !important;
  box-shadow:
    0 8px 32px rgba(91, 207, 250, 0.25),
    0 2px 8px rgba(245, 171, 185, 0.2),
    inset 0 1px 0 rgba(var(--v-theme-on-surface), 0.05) !important;
  border-radius: 16px !important;
}

/* 暗色模式下的菜单和弹出层 - 使用CSS变量简化 */
@media (prefers-color-scheme: dark) {

  :deep(.v-menu .v-overlay__content),
  :deep(.v-dialog .v-overlay__content),
  :deep(.v-navigation-drawer),
  :deep(.v-sheet.v-menu) {
    background: rgba(var(--v-theme-surface), 0.9) !important;
    border: 1px solid rgba(255, 255, 255, 0.15) !important;
    box-shadow:
      0 8px 32px rgba(91, 207, 250, 0.3),
      0 2px 8px rgba(245, 171, 185, 0.2),
      inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
  }
}

:deep(.v-theme--dark) .v-menu .v-overlay__content,
:deep(.v-theme--dark) .v-dialog .v-overlay__content,
:deep(.v-theme--dark) .v-navigation-drawer,
:deep(.v-theme--dark) .v-sheet.v-menu,
:deep([data-theme="dark"]) .v-menu .v-overlay__content,
:deep([data-theme="dark"]) .v-dialog .v-overlay__content,
:deep([data-theme="dark"]) .v-navigation-drawer,
:deep([data-theme="dark"]) .v-sheet.v-menu {
  background: rgba(var(--v-theme-surface), 0.9) !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  box-shadow:
    0 8px 32px rgba(91, 207, 250, 0.3),
    0 2px 8px rgba(245, 171, 185, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

/* 优化数据表格的镜面效果 - 动态适配主题 */
:deep(.v-data-table) {
  background: rgba(var(--v-theme-surface), 0.5) !important;
  backdrop-filter: blur(10px) !important;
  border-radius: 12px !important;
}

/* 暗色模式下的数据表格 */
:deep(.v-theme--dark) .v-data-table,
:deep([data-theme="dark"]) .v-data-table {
  background: rgba(var(--v-theme-surface), 0.6) !important;
}

:deep(.v-data-table__thead th) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2) 0%,
      rgba(245, 171, 185, 0.15) 100%) !important;
  backdrop-filter: blur(10px) !important;
}

/* 优化进度条的镜面效果 - 动态适配主题 */
:deep(.v-progress-linear) {
  border-radius: 10px !important;
  overflow: hidden;
  background: rgba(var(--v-theme-surface), 0.3) !important;
  backdrop-filter: blur(5px) !important;
}

/* 优化芯片组 - 动态适配主题 */
:deep(.v-chip-group) {
  gap: 8px;
}

:deep(.v-chip-group .v-chip) {
  background: rgba(var(--v-theme-surface), 0.6) !important;
  backdrop-filter: blur(10px) !important;
}

/* 列表项选中状态 - 动态适配主题 */
:deep(.v-list-item--active),
:deep(.v-list-item[aria-selected="true"]),
:deep(.v-item--active) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.2) 0%,
      rgba(245, 171, 185, 0.15) 100%) !important;
  backdrop-filter: blur(10px) !important;
  color: rgba(var(--v-theme-on-surface), 0.87) !important;
}

/* 暗色模式下的列表项选中状态 */
:deep(.v-theme--dark) .v-list-item--active,
:deep(.v-theme--dark) .v-list-item[aria-selected="true"],
:deep(.v-theme--dark) .v-item--active,
:deep([data-theme="dark"]) .v-list-item--active,
:deep([data-theme="dark"]) .v-list-item[aria-selected="true"],
:deep([data-theme="dark"]) .v-item--active {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.3) 0%,
      rgba(245, 171, 185, 0.25) 100%) !important;
  color: rgba(255, 255, 255, 0.9) !important;
}

/* 芯片选中状态 - 动态适配主题 */
:deep(.v-chip--selected) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 100%) !important;
  backdrop-filter: blur(10px) !important;
  color: rgba(var(--v-theme-on-surface), 0.87) !important;
}

/* 暗色模式下的芯片选中状态 */
:deep(.v-theme--dark) .v-chip--selected,
:deep([data-theme="dark"]) .v-chip--selected {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.35) 0%,
      rgba(245, 171, 185, 0.3) 100%) !important;
  color: rgba(255, 255, 255, 0.9) !important;
}

/* Tab 选中状态 - 动态适配主题 */
:deep(.v-tab--selected) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.3) 0%,
      rgba(245, 171, 185, 0.25) 100%) !important;
  color: #5bcffa !important;
}

/* 暗色模式下的 Tab 选中状态 */
:deep(.v-theme--dark) .v-tab--selected,
:deep([data-theme="dark"]) .v-tab--selected {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.4) 0%,
      rgba(245, 171, 185, 0.35) 100%) !important;
  color: #5bcffa !important;
}

/* 输入框选中/聚焦状态 - 动态适配主题 */
:deep(.v-field--focused),
:deep(.v-field--active) {
  box-shadow:
    0 0 0 3px rgba(91, 207, 250, 0.3),
    0 4px 12px rgba(245, 171, 185, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.6) !important;
  border-color: rgba(91, 207, 250, 0.6) !important;
}

/* 暗色模式下的输入框聚焦状态 */
:deep(.v-theme--dark) .v-field--focused,
:deep(.v-theme--dark) .v-field--active,
:deep([data-theme="dark"]) .v-field--focused,
:deep([data-theme="dark"]) .v-field--active {
  box-shadow:
    0 0 0 3px rgba(91, 207, 250, 0.4),
    0 4px 12px rgba(245, 171, 185, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.2) !important;
  border-color: rgba(91, 207, 250, 0.7) !important;
}

/* 表格行选中状态 - 动态适配主题 */
:deep(.v-data-table__tr--selected),
:deep(.v-data-table__tr[aria-selected="true"]) {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.15) 0%,
      rgba(245, 171, 185, 0.1) 100%) !important;
}

/* 暗色模式下的表格行选中状态 */
:deep(.v-theme--dark) .v-data-table__tr--selected,
:deep(.v-theme--dark) .v-data-table__tr[aria-selected="true"],
:deep([data-theme="dark"]) .v-data-table__tr--selected,
:deep([data-theme="dark"]) .v-data-table__tr[aria-selected="true"] {
  background: linear-gradient(135deg,
      rgba(91, 207, 250, 0.25) 0%,
      rgba(245, 171, 185, 0.2) 100%) !important;
}

/* 复选框和单选框选中状态 - 动态适配主题 */
:deep(.v-selection-control--dirty .v-selection-control__input) {
  color: rgb(var(--v-theme-primary)) !important;
}

/* 暗色模式下的复选框和单选框 */
:deep(.v-theme--dark) .v-selection-control--dirty .v-selection-control__input,
:deep([data-theme="dark"]) .v-selection-control--dirty .v-selection-control__input {
  color: #5bcffa !important;
}
</style>
