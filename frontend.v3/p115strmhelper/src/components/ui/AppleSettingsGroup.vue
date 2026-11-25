<template>
  <section class="p115-settings-section">
    <header v-if="title || $slots.action" class="p115-settings-head">
      <div class="p115-settings-head-left">
        <v-icon v-if="icon" :icon="icon" size="16" color="primary" />
        <span class="p115-settings-head-title">{{ title }}</span>
        <span v-if="subtitle" class="p115-settings-head-sub">{{ subtitle }}</span>
      </div>
      <div v-if="$slots.action" class="p115-settings-head-right">
        <slot name="action" />
      </div>
    </header>

    <div class="p115-bezel">
      <div class="p115-bezel-core" :class="{ 'p115-settings-padded': padded }">
        <slot />
      </div>
    </div>

    <p v-if="footerNote" class="p115-settings-foot">
      {{ footerNote }}
    </p>
  </section>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '',
  },
  subtitle: {
    type: String,
    default: '',
  },
  icon: {
    type: String,
    default: '',
  },
  padded: {
    type: Boolean,
    default: false,
  },
  footerNote: {
    type: String,
    default: '',
  },
});
</script>

<style scoped>
.p115-settings-section {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  max-width: 100%;
}

.p115-settings-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 4px;
  flex-wrap: wrap;
}

.p115-settings-head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.p115-settings-head-title {
  font-size: 0.81rem;
  font-weight: 630;
  color: var(--p115-text-secondary);
  letter-spacing: -0.005em;
}

.p115-settings-head-sub {
  font-size: 0.75rem;
  color: var(--p115-text-tertiary);
}

.p115-settings-padded {
  padding: 14px 16px;
}

.p115-settings-foot {
  padding: 0 6px;
  margin: 0;
  font-size: 0.75rem;
  line-height: 1.45;
  color: var(--p115-text-secondary);
}
</style>
