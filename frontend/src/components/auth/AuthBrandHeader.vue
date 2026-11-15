<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'AuthBrandHeader' })

withDefaults(defineProps<{
  icon?: string
  subtitle?: string
  headingTag?: 'h1' | 'h2'
}>(), {
  icon: 'dns',
  headingTag: 'h1',
})

const app = useAppStore()
</script>

<template>
  <div class="auth-header">
    <img
      v-if="app.authBannerUrl"
      class="auth-banner"
      :src="app.authBannerUrl"
      :alt="app.displayName"
    />
    <MsIcon v-else :name="icon" size="lg" color="var(--ac)" />
    <component
      :is="headingTag"
      class="auth-title"
      :class="{ 'auth-title--fallback': !app.hasSystemName }"
    >
      {{ app.displayName }}
    </component>
    <p v-if="subtitle" class="auth-subtitle">{{ subtitle }}</p>
  </div>
</template>

<style scoped>
.auth-header {
  text-align: center;
  margin-bottom: var(--sp-5);
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
  margin: var(--sp-3) 0 0;
  font-family: var(--font-sans);
  font-size: 1.56rem;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.028em;
  background-image: linear-gradient(
    92deg,
    var(--brand-title-frost-from) 0%,
    var(--brand-title-frost-mid) 44%,
    var(--brand-title-frost-to) 100%
  );
  background-size: 118% 100%;
  background-position: left center;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
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
  font-size: var(--text-base);
  line-height: 1.55;
  margin: var(--sp-2) 0 0;
}
</style>
