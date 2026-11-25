<template>
  <div ref="trackRef" class="p115-seg-scroll">
    <div ref="innerRef" class="p115-seg-track" :class="{ 'p115-seg-track--block': block }">
      <div
        v-if="pillStyle.ready"
        class="p115-seg-indicator"
        :style="{
          width: `${pillStyle.width}px`,
          transform: `translate3d(${pillStyle.x}px, 0, 0)`,
        }"
      />
      <button
        v-for="item in items"
        :key="String(item.value)"
        :ref="(el) => setBtnRef(item.value, el)"
        type="button"
        class="p115-seg-item"
        :class="{ 'p115-seg-item--active': modelValue === item.value }"
        :disabled="item.disabled"
        @click="selectItem(item)"
      >
        <v-icon v-if="item.icon" :icon="item.icon" size="16" class="p115-seg-icon" />
        <span>{{ item.label || item.title }}</span>
        <span v-if="item.badge != null && item.badge !== ''" class="p115-seg-count p115-tabular">
          {{ item.badge }}
        </span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted, onBeforeUnmount, nextTick } from 'vue';

const props = defineProps({
  modelValue: {
    type: [String, Number, Boolean],
    required: true,
  },
  items: {
    type: Array,
    required: true,
  },
  block: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['update:modelValue', 'change']);

const trackRef = ref(null);
const innerRef = ref(null);
const btnMap = new Map();

const pillStyle = reactive({
  x: 0,
  width: 0,
  ready: false,
});

const setBtnRef = (val, el) => {
  if (el) btnMap.set(val, el);
  else btnMap.delete(val);
};

const syncPill = () => {
  const activeEl = btnMap.get(props.modelValue);
  if (!activeEl || !innerRef.value) {
    pillStyle.ready = false;
    return;
  }
  pillStyle.width = activeEl.offsetWidth;
  pillStyle.x = activeEl.offsetLeft - 3;
  pillStyle.ready = pillStyle.width > 0;

  if (trackRef.value && trackRef.value.scrollWidth > trackRef.value.clientWidth) {
    const targetLeft = activeEl.offsetLeft - (trackRef.value.clientWidth - activeEl.offsetWidth) / 2;
    trackRef.value.scrollTo({ left: Math.max(0, targetLeft), behavior: 'smooth' });
  }
};

const selectItem = (item) => {
  if (item.disabled || item.value === props.modelValue) return;
  emit('update:modelValue', item.value);
  emit('change', item.value);
};

let ro = null;

watch(
  () => [props.modelValue, props.items.length],
  async () => {
    await nextTick();
    syncPill();
  },
);

onMounted(() => {
  nextTick(syncPill);
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => syncPill());
    if (innerRef.value) ro.observe(innerRef.value);
  }
});

onBeforeUnmount(() => {
  if (ro) {
    ro.disconnect();
    ro = null;
  }
});
</script>

<style scoped>
.p115-seg-scroll {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  box-sizing: border-box;
}

.p115-seg-scroll::-webkit-scrollbar {
  display: none;
}

.p115-seg-track {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 3px;
  border-radius: var(--p115-r-pill, 999px);
  background: var(--p115-bg-seg-track, rgba(15, 23, 42, 0.06));
  border: 1px solid var(--p115-border-hairline, rgba(15, 23, 42, 0.06));
  min-width: max-content;
}

.p115-seg-track--block {
  display: flex;
  width: 100%;
}

.p115-seg-track--block .p115-seg-item {
  flex: 1 1 0;
}

.p115-seg-indicator {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  border-radius: var(--p115-r-pill, 999px);
  background: var(--p115-bg-seg-pill, #ffffff);
  box-shadow: var(--p115-shadow-pill, 0 2px 6px rgba(15, 23, 42, 0.08));
  transition:
    transform 0.32s var(--p115-spring, cubic-bezier(0.32, 0.72, 0, 1)),
    width 0.32s var(--p115-spring, cubic-bezier(0.32, 0.72, 0, 1));
  pointer-events: none;
  z-index: 0;
}

.p115-seg-item {
  position: relative;
  z-index: 1;
  appearance: none;
  border: none;
  background: transparent;
  color: var(--p115-text-secondary);
  font-family: var(--p115-font-sans);
  font-size: 0.81rem;
  font-weight: 540;
  padding: 6px 14px;
  min-height: 32px;
  border-radius: var(--p115-r-pill, 999px);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  transition: color 0.18s ease, transform 0.1s var(--p115-press);
}

.p115-seg-item:active:not(:disabled) {
  transform: scale(0.96);
}

.p115-seg-item:hover:not(:disabled):not(.p115-seg-item--active) {
  color: var(--p115-text-primary);
}

.p115-seg-item--active {
  color: var(--p115-text-primary);
  font-weight: 630;
}

.p115-seg-item--active .p115-seg-icon {
  color: var(--p115-blue);
}

.p115-seg-count {
  padding: 0 6px;
  border-radius: 999px;
  font-size: 0.7rem;
  background: rgba(91, 207, 250, 0.18);
  color: var(--p115-blue-ink);
}

@media (max-width: 768px) {
  .p115-seg-item {
    min-height: 36px;
    padding: 7px 12px;
    font-size: 0.79rem;
  }
}
</style>
