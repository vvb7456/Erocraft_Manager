<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import MsIcon from '@/components/ui/MsIcon.vue'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
import LanguageToggle from '@/components/ui/LanguageToggle.vue'

defineOptions({ name: 'AuthShell' })

defineProps<{
  icon: string
  subtitle?: string
}>()

const app = useAppStore()
const { t } = useI18n({ useScope: 'global' })
const currentYear = new Date().getFullYear()
const footerText = computed(() => {
  const parts = [`${app.brandName} © 2015 - ${currentYear}`]
  if (app.icpRecord) parts.push(app.icpRecord)
  parts.push(t('common.footer.allRightsReserved'))
  return parts.join(' | ')
})
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
        <div class="auth-header">
          <img
            v-if="app.authBannerUrl"
            class="auth-banner"
            :src="app.authBannerUrl"
            :alt="app.displayName"
          />
          <MsIcon v-else :name="icon" size="lg" color="var(--ac)" />
          <h1 class="auth-title" :class="{ 'auth-title--fallback': !app.hasSystemName }">
            {{ app.displayName }}
          </h1>
          <p v-if="subtitle" class="auth-subtitle">{{ subtitle }}</p>
        </div>

        <slot />
      </div>
    </div>
    <div class="auth-footer">
      {{ footerText }}
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
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
  max-width: 400px;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r);
  padding: var(--sp-8) var(--sp-6);
}

.auth-header {
  text-align: center;
  margin-bottom: var(--sp-6);
}

.auth-banner {
  display: block;
  max-width: 100%;
  max-height: 54px;
  margin: 0 auto;
  object-fit: contain;
  filter: drop-shadow(0 2px 8px rgba(20, 184, 166, 0.15));
}

.auth-title {
  display: inline-block;
  max-width: 100%;
  font-family: 'IBM Plex Sans', 'IBM Plex Sans SC', -apple-system, sans-serif;
  font-size: 1.56rem;
  font-weight: 700;
  line-height: 1.2;
  background-image: linear-gradient(92deg, var(--brand-title-frost-from) 0%, var(--brand-title-frost-mid) 44%, var(--brand-title-frost-to) 100%);
  background-size: 118% 100%;
  background-position: left center;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: var(--sp-3) 0 0;
  letter-spacing: -0.028em;
  color: transparent;
  filter: drop-shadow(0 0 12px var(--brand-glow));
}

.auth-title--fallback {
  font-size: 1.22rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.auth-subtitle {
  color: var(--t2);
  font-size: .88rem;
  line-height: 1.55;
  margin: var(--sp-3) 0 0;
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
    padding: 12px;
  }
}
</style>
