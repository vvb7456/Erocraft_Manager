<script setup lang="ts">
// HostWingsPane (parent-level "Wings" tab) — only mounted for wings_node hosts.
// The route guard in HostDetailPage hides this tab when host.kind !== 'wings_node',
// but we double-check defensively here.
import { computed, inject, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { provideDirtyForm } from '@/composables/useDirtyForm'
import HostWingsSection from './sections/HostWingsSection.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import type { HostDetail } from '@/types/host'

defineOptions({ name: 'HostWingsPane' })

const { t } = useI18n({ useScope: 'global' })
const host = inject<Ref<HostDetail | null>>('hostDetail')!

const nodeId = computed(() => host.value?.pterodactyl_node_id ?? null)
const isWings = computed(() => host.value?.kind === 'wings_node')

// Page-wide dirty-form orchestration. HostWingsSection registers itself.
const dirtyForm = provideDirtyForm()
dirtyForm.attachLeaveGuard()
</script>

<template>
  <div v-if="!host" class="muted">{{ t('hosts.detail.loading') }}</div>
  <div v-else-if="!isWings || !nodeId" class="muted">{{ t('hosts.setting.wings.notWings') }}</div>
  <div v-else class="wings-panel">
    <HostWingsSection :nodeId="nodeId" />
  </div>
  <DirtyBar
    :dirty="dirtyForm.isDirty.value"
    :saving="dirtyForm.saving.value"
    @save="dirtyForm.save"
    @discard="dirtyForm.discard"
  />
</template>

<style scoped>
.muted {
  color: var(--t3);
  font-size: var(--text-sm);
  padding: var(--sp-4);
}
.wings-panel {
  margin-top: var(--sp-4);
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}
</style>
