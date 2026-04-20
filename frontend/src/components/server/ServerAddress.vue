<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { getEggMeta } from '@/config/eggRegistry'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ServerAddress' })

const props = defineProps<{
  /** Address strings to display (1-2, future cloudflare tunnel support) */
  addresses: string[]
  /** URL for the "open app" button. If omitted, no button shown */
  openUrl?: string
  /** Disable the open button (e.g. server not running) */
  openDisabled?: boolean
  /** Compact layout for mobile */
  compact?: boolean
  /** Egg name for display labels */
  eggName?: string
}>()

const { t } = useI18n({ useScope: 'global' })
const copiedIndex = ref<number | null>(null)

async function copy(address: string, index: number) {
  try {
    await navigator.clipboard.writeText(address)
    copiedIndex.value = index
    setTimeout(() => { copiedIndex.value = null }, 2000)
  } catch { /* clipboard API not available */ }
}

const openBtnLabel = computed(() => {
  const lbl = getEggMeta(props.eggName ?? '').label
  return lbl ? t('userServers.openApp', { name: lbl }) : t('userServers.openAppGeneric')
})

function openLink() {
  if (props.openUrl) window.open(props.openUrl, '_blank')
}
</script>

<template>
  <!-- Open button -->
  <BaseButton
    v-if="openUrl"
    variant="primary"
    size="sm"
    class="open-btn"
    :disabled="openDisabled"
    @click="openLink"
  >
    <MsIcon name="open_in_new" />
    {{ openBtnLabel }}
  </BaseButton>

  <!-- Address lines -->
  <div class="address-lines" :style="openUrl ? { marginTop: 'var(--sp-2)' } : undefined">
    <div
      v-for="(addr, i) in addresses"
      :key="i"
      class="address-line"
      :class="{ 'address-line--large': !openUrl && !compact }"
    >
      <span class="address-text">{{ addr }}</span>
      <button class="copy-btn" :title="t('userServers.address.copy')" @click="copy(addr, i)">
        <MsIcon :name="copiedIndex === i ? 'check' : 'content_copy'" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.open-btn {
  width: 100%;
}

.address-lines {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.address-line {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-2);
  background: var(--bg-in);
  border-radius: var(--r-sm);
  border: 1px solid var(--bd);
}

.address-line--large {
  padding: var(--sp-2);
}

.address-text {
  flex: 1;
  font-family: 'IBM Plex Mono', monospace;
  font-size: var(--text-xs);
  color: var(--t2);
  word-break: break-all;
}

.copy-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--r-xs);
  background: none;
  color: var(--t3);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.copy-btn:hover {
  color: var(--ac);
  background: var(--bg4);
}
</style>
