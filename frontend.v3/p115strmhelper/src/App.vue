<template>
  <v-app>
    <div class="plugin-app">
      <component
        :is="currentComponent"
        :api="api"
        @switch="switchComponent"
        @close="closeModal"
        @save="saveConfig"
      />
    </div>
  </v-app>
</template>

<script>
import { defineComponent, ref, shallowRef, onMounted, onBeforeUnmount, onErrorCaptured } from 'vue';
import Page from './components/Page.vue';
import Config from './components/Config.vue';
import './styles/apple-theme.css';

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
      saveConfig,
    };
  },
});
</script>

<style>
.plugin-app {
  width: 100%;
  max-width: 100%;
  height: 100dvh;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, #eef6fc 0%, #fdf2f5 52%, #f8fafc 100%);
  position: relative;
  box-sizing: border-box;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "PingFang SC", system-ui, sans-serif;
}

.plugin-app > * {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
