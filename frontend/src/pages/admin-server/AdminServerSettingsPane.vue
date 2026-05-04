<script setup lang="ts">
// AdminServerSettingsPane — orchestrates 5 admin-side server-edit sections
// behind a single DirtyBar. Each Section* registers itself via
// useDirtyFormSection(); save runs them in registration order.
//
// Sections:
//   1. Details       (PATCH /details)
//   2. Owner         (PATCH /owner — destructive, confirm; warning toast)
//   3. Build         (PATCH /build — Wings sync, backend rolls back on fail)
//   4. Allocations   (chip-input; POST + PUT /primary + DELETE in one save)
//   5. Startup       (combined nest/egg/image/startup/skip/variables;
//                     PUT /egg if egg switched, else PATCH /startup +
//                     PATCH /variables)
//
// Validation aggregation: SectionStartup writes per-variable errors into
// the provided `settingsValidationErrors` ref. The container reads this
// ref to render the DirtyBar #hint slot in red and to short-circuit
// `save()` so users see the same count before they trigger a sectional
// toast.
import { inject, ref, provide, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { provideDirtyForm } from '@/composables/useDirtyForm'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import SectionDetails from './settings/SectionDetails.vue'
import SectionOwner from './settings/SectionOwner.vue'
import SectionBuild from './settings/SectionBuild.vue'
import SectionAllocations from './settings/SectionAllocations.vue'
import SectionStartup from './settings/SectionStartup.vue'
import type { AdminServerDetailResponse } from '@/types/adminServer'

defineOptions({ name: 'AdminServerSettingsPane' })

const { t } = useI18n({ useScope: 'global' })
const { confirm } = useConfirm()
const { toast } = useToast()
const detail = inject<Ref<AdminServerDetailResponse | null>>('adminServerDetail')!

const validationErrors = ref<string[]>([])
provide('settingsValidationErrors', validationErrors)

const dirtyForm = provideDirtyForm({
  prompt: async () => {
    const r = await confirm({
      title: t('adminServer.settings.unsavedTitle'),
      message: t('adminServer.settings.unsavedMessage'),
      confirmText: t('adminServer.settings.unsavedSave'),
      cancelText: t('adminServer.settings.unsavedDiscard'),
      altText: t('adminServer.settings.unsavedStay'),
    })
    if (r === 'alt') return 'stay'
    return r === true ? 'save' : 'discard'
  },
})
dirtyForm.attachLeaveGuard()

async function onSave() {
  if (validationErrors.value.length > 0) {
    toast(
      t('adminServer.settings.invalidHint', { n: validationErrors.value.length }),
      'error',
    )
    return
  }
  await dirtyForm.save()
}
</script>

<template>
  <LoadingCenter v-if="!detail" />

  <div v-else class="settings-panel">
    <SectionDetails />
    <SectionOwner />
    <SectionBuild />
    <SectionAllocations />
    <SectionStartup />

    <DirtyBar
      :dirty="dirtyForm.isDirty.value"
      :saving="dirtyForm.saving.value"
      :hint="t('adminServer.settings.unsavedHint')"
      :save-text="t('adminServer.settings.saveBtn')"
      :discard-text="t('adminServer.settings.discardBtn')"
      @save="onSave"
      @discard="dirtyForm.discard"
    >
      <template v-if="validationErrors.length > 0" #hint>
        <span class="va-hint">
          <MsIcon name="error" size="sm" />
          {{ t('adminServer.settings.invalidHint', { n: validationErrors.length }) }}
        </span>
      </template>
      <template v-if="validationErrors.length > 0" #extra>
        <span v-for="(e, i) in validationErrors" :key="i" class="va-chip">{{ e }}</span>
      </template>
    </DirtyBar>
  </div>
</template>

<style scoped>
.settings-panel {
  margin-top: var(--sp-4);
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
}
.settings-panel > * + * {
  margin-top: var(--sp-5);
}
.va-hint { display: inline-flex; align-items: center; gap: var(--sp-2); color: var(--red); font-size: var(--text-sm); font-weight: 500; }
.va-chip { font-size: var(--text-xs); color: var(--t2); white-space: nowrap; }
.va-chip + .va-chip::before { content: ' · '; color: var(--t3); }
</style>
