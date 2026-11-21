<script setup lang="ts">
import { computed } from 'vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'AuthStatusView' })

const props = withDefaults(defineProps<{
  tone?: 'success' | 'warning' | 'danger'
  icon?: string
  title: string
  email?: string
  description?: string
  hint?: string
}>(), {
  tone: 'success',
})

const defaultIcons: Record<string, string> = {
  success: 'check_circle',
  warning: 'block',
  danger: 'error_outline',
}

const resolvedIcon = computed(() => props.icon || defaultIcons[props.tone] || 'info')
</script>

<template>
  <div class="auth-status-wrap" role="status" aria-live="polite">
    <div class="auth-status-panel" :class="`auth-status-panel--${tone}`">
      <div class="auth-status-panel__icon">
        <MsIcon :name="resolvedIcon" size="lg" color="none" />
      </div>

      <h3 class="auth-status-panel__title">{{ title }}</h3>

      <div v-if="email" class="auth-status-panel__email">
        <MsIcon name="mail" size="xs" color="var(--t2)" />
        <span>{{ email }}</span>
      </div>

      <p v-if="description" class="auth-status-panel__desc">{{ description }}</p>
      <p v-if="hint" class="auth-status-panel__hint">{{ hint }}</p>
    </div>

    <div v-if="$slots.actions" class="auth-status-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.auth-status-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.auth-status-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--sp-6) var(--sp-5);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--rs);
}

.auth-status-panel--success {
  border-color: color-mix(in srgb, var(--c-positive) 28%, var(--bd));
}

.auth-status-panel--warning {
  border-color: color-mix(in srgb, var(--c-caution) 28%, var(--bd));
}

.auth-status-panel--danger {
  border-color: color-mix(in srgb, var(--c-negative) 28%, var(--bd));
}

.auth-status-panel__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  margin-bottom: var(--sp-3);
  color: var(--t2);
}

.auth-status-panel--success .auth-status-panel__icon {
  color: var(--c-positive);
}

.auth-status-panel--warning .auth-status-panel__icon {
  color: var(--c-caution);
}

.auth-status-panel--danger .auth-status-panel__icon {
  color: var(--c-negative);
}

.auth-status-panel__icon :deep(.ms) {
  font-size: 36px;
  vertical-align: 0;
}

.auth-status-panel__title {
  margin: 0;
  color: var(--t1);
  font-size: var(--text-lg);
  font-weight: 600;
  line-height: 1.35;
}

.auth-status-panel__email {
  margin-top: var(--sp-3);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 5px 12px;
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  color: var(--t1);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.auth-status-panel__email span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.auth-status-panel__desc {
  margin: var(--sp-3) 0 0;
  max-width: 320px;
  color: var(--t2);
  font-size: var(--text-base);
  line-height: 1.65;
}

.auth-status-panel__hint {
  margin: var(--sp-2) 0 0;
  color: var(--t3);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.auth-status-actions {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.auth-status-actions :deep(.base-btn) {
  width: 100%;
  justify-content: center;
}
</style>
