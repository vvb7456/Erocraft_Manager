<script setup lang="ts">
import { ref, inject, computed, onMounted, type Ref, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import { usePowerPendingStore } from '@/stores/powerPending'
import { getEggSettingsComponent } from '@/config/eggRegistry'
import type { StartupVar, EggSettingsExpose } from '@/components/egg-settings/types'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'

defineOptions({ name: 'ServerSettingsPage' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const pendingStore = usePowerPendingStore()

interface ServerDetail {
  id: number; uuid: string; nodeId: number; eggName: string; isSuspended: boolean
}

const server = inject<Ref<ServerDetail | null>>('server')!

const loaded = ref(false)
const saving = ref(false)
const isDirty = ref(false)
const variables = ref<StartupVar[]>([])

// Dynamic component based on egg name
const settingsComponent = computed<Component>(() =>
  getEggSettingsComponent(server.value?.eggName ?? ''),
)

const childRef = ref<EggSettingsExpose | null>(null)

async function loadSettings() {
  if (!server.value) return
  const vars = await get<StartupVar[]>(`/api/user/servers/${server.value.id}/startup`)
  if (vars) variables.value = vars
  loaded.value = true
}

onMounted(loadSettings)

function onDirtyChange(dirty: boolean) {
  isDirty.value = dirty
}

// performSave never navigates: the leave-guard path must respect the
// user's chosen destination. The DirtyBar Save click wraps this with
// onBarSave() to navigate to the console on success, mirroring the
// previous explicit-save flow.
async function performSave(): Promise<boolean> {
  if (!server.value || !childRef.value) return true
  saving.value = true
  try {
    const success = await childRef.value.save()
    if (!success) return false
    await pendingStore.sendPower(server.value.id, 'restart', toast)
    toast(t('serverSettings.saveSuccess'), 'success')
    return true
  } catch {
    toast(t('serverSettings.saveFailed'), 'error')
    return false
  } finally {
    saving.value = false
  }
}

function discardChanges() {
  childRef.value?.discard()
}

// Page-wide dirty-form orchestration. The leave-guard reuses serverSettings.*
// strings (custom prompt) so message text matches the page domain.
const dirtyForm = provideDirtyForm({
  prompt: async () => {
    const result = await confirm({
      title: t('serverSettings.unsavedTitle'),
      message: t('serverSettings.unsavedMessage'),
      confirmText: t('serverSettings.unsavedSave'),
      cancelText: t('serverSettings.unsavedDiscard'),
      altText: t('serverSettings.unsavedStay'),
    })
    if (result === 'alt') return 'stay'
    return result === true ? 'save' : 'discard'
  },
})
dirtyForm.attachLeaveGuard()

useDirtyFormSection({
  name: 'server-startup',
  isDirty,
  save: performSave,
  discard: discardChanges,
}, dirtyForm)

async function onBarSave() {
  // Bar Save is an explicit user action that triggers a server restart;
  // ask for confirmation here. The leave-guard "Save" choice skips this
  // dialog because the user has already opted in via the leave prompt.
  const ok = await confirm({
    title: t('serverSettings.saveConfirmTitle'),
    message: t('serverSettings.saveConfirmMessage'),
    confirmText: t('serverSettings.saveConfirmBtn'),
  })
  if (!ok) return
  const saved = await dirtyForm.save()
  if (saved && server.value) {
    router.push({ name: 'server-console', params: { id: server.value.id } })
  }
}
</script>

<template>
  <LoadingCenter v-if="!loaded && loading" />

  <template v-else-if="server">
    <component
      :is="settingsComponent"
      ref="childRef"
      :server-id="server.id"
      :server-uuid="server.uuid"
      :egg-name="server.eggName"
      :variables="variables"
      @update:dirty="onDirtyChange"
    />
  </template>

  <DirtyBar
    :dirty="dirtyForm.isDirty.value"
    :saving="dirtyForm.saving.value"
    :errors="childRef?.validationErrors ?? []"
    :hint="t('serverSettings.unsavedHint')"
    :save-text="t('serverSettings.saveBtn')"
    :discard-text="t('serverSettings.discardBtn')"
    @save="onBarSave"
    @discard="dirtyForm.discard"
  />
</template>

<style scoped>
/* No page-local styles: floating bar is rendered by <DirtyBar/>. */
</style>
