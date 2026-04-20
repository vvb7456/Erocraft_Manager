<script setup lang="ts">
import AuthShell from '@/components/auth/AuthShell.vue'

defineOptions({ name: 'AuthForm' })

withDefaults(defineProps<{
  icon: string
  subtitle?: string
  actionsAlign?: 'start' | 'center' | 'end'
  footerAlign?: 'start' | 'center' | 'end'
}>(), {
  actionsAlign: 'end',
  footerAlign: 'center',
})

defineEmits<{
  submit: []
}>()
</script>

<template>
  <AuthShell :icon="icon" :subtitle="subtitle">
    <form class="auth-form" @submit.prevent="$emit('submit')">
      <slot />

      <div v-if="$slots.actions" class="auth-form__actions" :class="`auth-form__actions--${actionsAlign}`">
        <slot name="actions" />
      </div>

      <slot name="submit" />

      <div v-if="$slots.footer" class="auth-form__footer" :class="`auth-form__footer--${footerAlign}`">
        <slot name="footer" />
      </div>
    </form>
  </AuthShell>
</template>

<style scoped>
.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.auth-form__actions,
.auth-form__footer {
  display: flex;
  margin-top: calc(var(--sp-1) * -1);
}

.auth-form__actions--start,
.auth-form__footer--start {
  justify-content: flex-start;
}

.auth-form__actions--center,
.auth-form__footer--center {
  justify-content: center;
}

.auth-form__actions--end,
.auth-form__footer--end {
  justify-content: flex-end;
}
</style>
