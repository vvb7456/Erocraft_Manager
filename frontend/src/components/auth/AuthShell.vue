<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import AuthBrandHeader from '@/components/auth/AuthBrandHeader.vue'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
import LanguageToggle from '@/components/ui/LanguageToggle.vue'

defineOptions({ name: 'AuthShell' })

defineProps<{
  icon: string
  subtitle?: string
}>()

const app = useAppStore()
</script>

<template>
  <div class="auth-page">
    <div class="auth-toolbar">
      <div class="auth-toolbar__controls">
        <LanguageToggle variant="ghost" />
        <ThemeToggle />
      </div>
    </div>
    <div class="auth-main">
      <div class="auth-card">
        <AuthBrandHeader :icon="icon" :subtitle="subtitle" />
        <slot />
      </div>
    </div>
    <div class="auth-footer">
      {{ app.footerText }}
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  min-height: 100dvh;
  width: 100%;
  background: var(--bg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
}

.auth-toolbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  min-height: 64px;
  padding: 0 clamp(28px, 2.5vw, 42px);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  z-index: 10;
  pointer-events: none;
}

.auth-toolbar__controls {
  display: flex;
  align-items: center;
  gap: 6px;
  pointer-events: auto;
}

.auth-main {
  display: flex;
  justify-content: center;
  align-items: center;
  flex: 1;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r);
  padding: var(--sp-8) var(--sp-6);
}

.auth-footer {
  text-align: center;
  color: var(--t3);
  font-size: .74rem;
  line-height: 1.6;
  padding-top: var(--sp-4);
}

@media (max-width: 768px) {
  .auth-page {
    background: var(--bg2);
    padding: 0;
  }

  .auth-toolbar {
    position: sticky;
    min-height: calc(52px + env(safe-area-inset-top, 0px));
    padding: env(safe-area-inset-top, 0px) var(--sp-4) 0;
    background: var(--bg2);
    pointer-events: auto;
  }

  .auth-main {
    align-items: flex-start;
    padding: var(--sp-2) var(--sp-5) var(--sp-6);
  }

  .auth-card {
    max-width: 400px;
    margin: 0 auto;
    background: none;
    border: 0;
    border-radius: 0;
    padding: 0;
  }

  .auth-footer {
    padding: var(--sp-3) var(--sp-4) calc(var(--sp-4) + env(safe-area-inset-bottom, 0px));
  }
}
</style>
