import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config from './__federation_expose_Config-DKmiLaR4.js';

const {openBlock:_openBlock,createBlock:_createBlock} = await importShared('vue');


const {onMounted,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'Page',
  props: {
  api: { type: Object, default: () => ({}) },
},
  emits: ['action', 'close', 'layout'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
const initialConfig = ref({});

function unwrap(response) {
  const body = response?.data ?? response ?? {};
  return body?.data ?? body
}

async function onSave(payload) {
  await props.api.post('plugin/PlexToolbox/config', payload);
  emit('action');
}

onMounted(async () => {
  try {
    const response = await props.api.get('plugin/PlexToolbox/config');
    initialConfig.value = unwrap(response) || {};
  } catch (error) {
    console.error('读取 PLEX 工具箱配置失败', error);
  }
});

return (_ctx, _cache) => {
  return (_openBlock(), _createBlock(Config, {
    "initial-config": initialConfig.value,
    api: __props.api,
    onSave: onSave,
    onClose: _cache[0] || (_cache[0] = $event => (emit('close'))),
    onLayout: _cache[1] || (_cache[1] = payload => emit('layout', payload))
  }, null, 8, ["initial-config", "api"]))
}
}

};

export { _sfc_main as default };
