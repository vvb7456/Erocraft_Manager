<script setup lang="ts">
import { ref, inject, computed, onMounted, type Ref, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { usePowerPendingStore } from '@/stores/powerPending'
import { getEggSettingsComponent } from '@/config/eggRegistry'
import type { StartupVar, EggSettingsExpose } from '@/components/egg-settings/types'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

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

async function saveSettings() {
  if (!server.value || saving.value || !childRef.value) return
  const ok = await confirm({
    title: t('serverSettings.saveConfirmTitle'),
    message: t('serverSettings.saveConfirmMessage'),
    confirmText: t('serverSettings.saveConfirmBtn'),
  })
  if (!ok) return

  saving.value = true
  try {
    const success = await childRef.value.save()
    if (!success) return

    await pendingStore.sendPower(server.value.id, 'restart', toast)
    toast(t('serverSettings.saveSuccess'), 'success')
    router.push({ name: 'server-console', params: { id: server.value.id } })
  } catch {
    toast(t('serverSettings.saveFailed'), 'error')
  } finally {
    saving.value = false
  }
}

function discardChanges() {
  childRef.value?.discard()
}

onBeforeRouteLeave(async () => {
  if (!isDirty.value) return true
  const result = await confirm({
    title: t('serverSettings.unsavedTitle'),
    message: t('serverSettings.unsavedMessage'),
    confirmText: t('serverSettings.unsavedSave'),
    cancelText: t('serverSettings.unsavedDiscard'),
    altText: t('serverSettings.unsavedStay'),
  })
  if (result === 'alt') return false
  if (result === true) {
    saving.value = true
    try {
      const success = await childRef.value?.save()
      if (!success) return false
      await pendingStore.sendPower(server.value!.id, 'restart', toast)
      toast(t('serverSettings.saveSuccess'), 'success')
    } catch {
      toast(t('serverSettings.saveFailed'), 'error')
      return false
    } finally {
      saving.value = false
    }
  }
  return true
})
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

  <Teleport to="body">
    <Transition name="slide-up">
      <div v-if="isDirty" class="dirty-bar">
        <span class="dirty-bar__text">
          <MsIcon name="edit" />
          {{ t('serverSettings.unsavedHint') }}
        </span>
        <div class="dirty-bar__actions">
          <BaseButton size="sm" :disabled="saving" @click="discardChanges">
            {{ t('serverSettings.discardBtn') }}
          </BaseButton>
          <BaseButton
            variant="primary"
            size="sm"
            :loading="saving"
            @click="saveSettings"
          >
            {{ t('serverSettings.saveBtn') }}
          </BaseButton>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* Floating dirty bar */
.dirty-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-5);
  background: var(--bg3);
  border-top: 1px solid var(--bd);
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.35);
}

.dirty-bar__text {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--amber);
}

.dirty-bar__text .ms-icon {
  font-size: 1.1rem;
}

.dirty-bar__actions {
  display: flex;
  gap: var(--sp-2);
  flex-shrink: 0;
}

/* slide-up transition */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.25s ease, opacity 0.25s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}
</style>
