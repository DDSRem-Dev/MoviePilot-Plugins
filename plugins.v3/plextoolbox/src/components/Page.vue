<template>
  <Config
    :initial-config="initialConfig"
    :api="api"
    @save="onSave"
    @close="emit('close')"
    @layout="payload => emit('layout', payload)"
  />
</template>

<script setup>
import { onMounted, ref } from 'vue'
import Config from './Config.vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['action', 'close', 'layout'])
const initialConfig = ref({})

function unwrap(response) {
  const body = response?.data ?? response ?? {}
  return body?.data ?? body
}

async function onSave(payload) {
  await props.api.post('plugin/PlexToolbox/config', payload)
  emit('action')
}

onMounted(async () => {
  try {
    const response = await props.api.get('plugin/PlexToolbox/config')
    initialConfig.value = unwrap(response) || {}
  } catch (error) {
    console.error('读取 PLEX 工具箱配置失败', error)
  }
})
</script>
