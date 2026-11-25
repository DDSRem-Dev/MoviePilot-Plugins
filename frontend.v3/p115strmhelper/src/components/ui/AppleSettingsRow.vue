<template>
  <div class="p115-srow-wrap" :class="{ 'p115-srow-wrap--no-border': noBorder }">
    <div class="p115-srow" :class="{ 'p115-srow--vertical': vertical, 'p115-srow--wide-control': wideControl }">
      <div v-if="title || description || $slots.label" class="p115-srow-meta">
        <div class="p115-srow-title">
          <slot name="label">
            <span>{{ title }}</span>
          </slot>
          <slot name="badge" />
        </div>
        <div v-if="description || $slots.description" class="p115-srow-desc">
          <slot name="description">{{ description }}</slot>
        </div>
      </div>

      <div class="p115-srow-control" :class="{ 'p115-srow-control--full': vertical }">
        <slot />
      </div>
    </div>

    <!-- Smooth Spring Expandable Child Sub-Tray -->
    <div v-if="$slots.subtray" class="p115-subtray" :class="{ 'p115-subtray--open': subtrayOpen }">
      <div class="p115-subtray-inner">
        <div class="p115-subtray-content">
          <slot name="subtray" />
        </div>
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
  description: {
    type: String,
    default: '',
  },
  vertical: {
    type: Boolean,
    default: false,
  },
  wideControl: {
    type: Boolean,
    default: false,
  },
  subtrayOpen: {
    type: Boolean,
    default: false,
  },
  noBorder: {
    type: Boolean,
    default: false,
  },
});
</script>

<style scoped>
.p115-srow-wrap {
  min-width: 0;
  max-width: 100%;
  border-bottom: 1px solid var(--p115-border-hairline);
}

.p115-srow-wrap:last-child,
.p115-srow-wrap--no-border {
  border-bottom: none;
}

.p115-srow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  min-height: 52px;
}

.p115-srow--vertical {
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  gap: 10px;
}

.p115-srow-meta {
  flex: 1 1 0%;
  min-width: 0;
}

.p115-srow--vertical .p115-srow-meta {
  flex: 0 0 auto;
  width: 100%;
}

.p115-srow-title {
  font-size: 0.875rem;
  font-weight: 560;
  color: var(--p115-text-primary);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  line-height: 1.35;
}

.p115-srow-desc {
  font-size: 0.76rem;
  color: var(--p115-text-secondary);
  margin-top: 3px;
  line-height: 1.45;
}

.p115-srow-control {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.p115-srow--wide-control .p115-srow-control {
  flex: 0 1 340px;
  min-width: 220px;
}

.p115-srow--wide-control .p115-srow-control > * {
  width: 100%;
}

.p115-srow-control--full {
  flex: 0 0 auto;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  width: 100%;
  min-width: 0;
  gap: 10px;
}

.p115-srow-control--full > * {
  width: 100%;
}

/* Smooth CSS Grid 0fr -> 1fr Spring Sub-Tray */
.p115-subtray {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.32s var(--p115-spring);
  background: var(--p115-bg-inset);
}

.p115-subtray--open {
  grid-template-rows: 1fr;
  border-top: 1px solid var(--p115-border-hairline);
}

.p115-subtray-inner {
  overflow: hidden;
}

.p115-subtray-content {
  padding: 13px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

@media (max-width: 680px) {
  .p115-srow {
    padding: 11px 13px;
    gap: 10px;
  }

  .p115-srow--wide-control {
    flex-direction: column;
    align-items: stretch;
  }

  .p115-srow--wide-control .p115-srow-meta {
    flex: 0 0 auto;
  }

  .p115-srow--wide-control .p115-srow-control {
    flex: 0 0 auto;
    min-width: 0;
    width: 100%;
  }

  .p115-subtray-content {
    padding: 11px 13px;
  }
}
</style>
