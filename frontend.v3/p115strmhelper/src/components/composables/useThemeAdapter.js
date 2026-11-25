import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { useTheme } from 'vuetify';

/**
 * 宿主多主题自适应 Composable
 * 兼容 MoviePilot V3 浅色 (light)、深色 (dark)、紫色暗色 (purple) 与透明毛玻璃 (transparent) 主题
 * 输出无 `.v-` 前缀的属性与类名，避免被生产环境 federation postcss 插件剔除
 */
export function useThemeAdapter() {
  let vuetifyTheme = null;
  try {
    vuetifyTheme = useTheme();
  } catch {
    vuetifyTheme = null;
  }

  const domDark = ref(false);
  const domTransparent = ref(false);
  let observer = null;

  const syncFromDom = () => {
    if (typeof document === 'undefined') return;
    const html = document.documentElement;
    const body = document.body;
    const dataTheme = (html?.getAttribute('data-theme') || body?.getAttribute('data-theme') || '').toLowerCase();
    const classStr = `${html?.className || ''} ${body?.className || ''}`.toLowerCase();

    domTransparent.value =
      dataTheme === 'transparent' ||
      classStr.includes('theme--transparent');

    domDark.value =
      dataTheme === 'dark' ||
      dataTheme === 'purple' ||
      classStr.includes('theme--dark') ||
      classStr.includes('theme--purple');
  };

  onMounted(() => {
    syncFromDom();
    if (typeof MutationObserver !== 'undefined' && typeof document !== 'undefined') {
      observer = new MutationObserver(syncFromDom);
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme', 'class', 'style'],
      });
      if (document.body) {
        observer.observe(document.body, {
          attributes: true,
          attributeFilter: ['data-theme', 'class'],
        });
      }
    }
  });

  onBeforeUnmount(() => {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  });

  const isDark = computed(() => {
    if (vuetifyTheme?.global?.current?.value) {
      if (vuetifyTheme.global.current.value.dark) return true;
    }
    return domDark.value;
  });

  const isTransparent = computed(() => {
    const name = String(vuetifyTheme?.global?.name?.value || '').toLowerCase();
    return domTransparent.value || name.includes('transparent');
  });

  const themeMode = computed(() => (isDark.value ? 'dark' : 'light'));

  const dialogContentClass = computed(() => {
    const classes = ['p115-dialog-overlay'];
    classes.push(isDark.value ? 'p115-mode-dark' : 'p115-mode-light');
    if (isTransparent.value) {
      classes.push('p115-mode-transparent');
    }
    return classes.join(' ');
  });

  return {
    isDark,
    isTransparent,
    themeMode,
    dialogContentClass,
  };
}
