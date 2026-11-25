<template>
  <div class="p115-bezel">
    <div class="p115-bezel-core">
      <div v-if="title || $slots.header || $slots.actions || $slots.action" class="p115-card-head">
        <div class="p115-card-head-title">
          <v-icon v-if="icon" :icon="icon" :color="iconColor" size="18" />
          <slot name="header">
            <span>{{ title }}</span>
          </slot>
          <slot name="badge" />
        </div>
        <div v-if="$slots.actions || $slots.action" class="p115-card-head-actions">
          <slot name="actions" />
          <slot name="action" />
        </div>
      </div>
      <div :class="flush ? 'p115-card-body--flush' : 'p115-card-body'">
        <slot />
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '',
  },
  icon: {
    type: String,
    default: '',
  },
  iconColor: {
    type: String,
    default: 'primary',
  },
  flush: {
    type: Boolean,
    default: false,
  },
});
</script>

<style scoped>
.p115-card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
</style>
