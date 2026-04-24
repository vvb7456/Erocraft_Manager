<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import { usePowerPendingStore, type PowerAction } from '@/stores/powerPending'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

const props = defineProps<{
  serverId: number
  state: string
  isSuspended: boolean
  isInstalling: boolean
  /** 'column' (sidebar) or 'row' (mobile) */
  layout?: 'column' | 'row'
  /** External disable (e.g. WS disconnected on console page) */
  disabled?: boolean
  disabledReason?: string
  /** Egg name for context-sensitive messages */
  eggName?: string
}>()

const { t, te } = useI18n({ useScope: 'global' })
const router = useRouter()
const { confirm } = useConfirm()
const { toast } = useToast()
const pendingStore = usePowerPendingStore()

const CREDENTIALS_ERROR = 'server.startup_credentials_required'

const pendingAction = computed(() => pendingStore.get(props.serverId))
const btnSize = computed(() => props.layout === 'row' ? 'sm' as const : undefined)
const btnClass = computed(() => ({ 'power-btn': props.layout !== 'row' }))

async function sendPower(action: PowerAction) {
  // Check if this action is allowed given current pending state
  if (!pendingStore.isActionAllowed(props.serverId, action)) return

  if (action === 'stop') {
    const ok = await confirm({
      title: t('common.confirm.title'),
      message: t('userServers.power.confirmStop'),
      confirmText: t('userServers.power.stop'),
    })
    if (!ok) return
  } else if (action === 'kill') {
    const ok = await confirm({
      title: t('common.confirm.dangerTitle'),
      message: t('userServers.power.confirmKill'),
      confirmText: t('userServers.power.kill'),
      variant: 'danger',
    })
    if (!ok) return
  }

  const err = await pendingStore.sendPower(props.serverId, action, toast, [CREDENTIALS_ERROR])
  if (err && err.code === CREDENTIALS_ERROR) {
    // Translate each missing env-var key (e.g. PASSWORD) via the
    // userServers.power.credField map; fall back to the raw key when
    // we don't have a label for it. The dialog message lists the actual
    // fields so the wording matches what the user must change.
    const fields = err.missing.length
      ? err.missing.map((k) => {
          const lk = `userServers.power.credField.${k}`
          return te(lk) ? t(lk) : k
        }).join(t('common.listSep'))
      : ''
    const goSettings = await confirm({
      title: t('userServers.power.credentialsRequiredTitle'),
      message: t('userServers.power.credentialsRequiredMessage', { fields }),
      confirmText: t('userServers.power.goToSettings'),
    })
    if (goSettings) {
      router.push({ name: 'server-settings', params: { id: props.serverId } })
    }
  }
}
</script>

<template>
  <div class="power-controls" :class="['power-controls--' + (layout ?? 'column'), { 'power-controls--disabled': disabled }]">
    <!-- External disabled overlay -->
    <template v-if="disabled">
      <BaseButton :size="btnSize" :class="btnClass" disabled>
        <MsIcon name="power_settings_new" /> {{ disabledReason || t('userServers.power.title') }}
      </BaseButton>
    </template>

    <!-- Installing -->
    <BaseButton v-else-if="isInstalling" variant="primary" :size="btnSize" :class="btnClass" disabled>
      <Spinner size="xs" /> {{ t('userServers.status.installing') }}
    </BaseButton>

    <!-- Suspended -->
    <BaseButton v-else-if="isSuspended" variant="primary" :size="btnSize" :class="btnClass" disabled>
      <MsIcon name="play_arrow" /> {{ t('userServers.power.start') }}
    </BaseButton>

    <!-- ═══ Pending states (override real state) ═══ -->

    <!-- pending=restart: show "重启中..." until server enters 'starting' (staged clear) -->
    <BaseButton v-else-if="pendingAction === 'restart'" :size="btnSize" :class="btnClass" disabled>
      <Spinner size="xs" /> {{ t('userServers.status.restarting') }}
    </BaseButton>

    <!-- pending=start: show "启动中..." -->
    <BaseButton v-else-if="pendingAction === 'start'" :size="btnSize" :class="btnClass" disabled>
      <Spinner size="xs" /> {{ t('userServers.status.starting') }}
    </BaseButton>

    <!-- pending=stop: show "关闭中..." + kill allowed -->
    <template v-else-if="pendingAction === 'stop'">
      <BaseButton :size="btnSize" :class="btnClass" disabled>
        <Spinner size="xs" /> {{ t('userServers.status.stopping') }}
      </BaseButton>
      <BaseButton :size="btnSize" :class="btnClass" variant="danger" @click="sendPower('kill')">
        <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
      </BaseButton>
    </template>

    <!-- pending=kill: show "关闭电源中..." -->
    <BaseButton v-else-if="pendingAction === 'kill'" :size="btnSize" :class="btnClass" disabled>
      <Spinner size="xs" /> {{ t('userServers.status.killingPower') }}
    </BaseButton>

    <!-- ═══ Normal states (no pending) ═══ -->

    <!-- Offline / Stopped -->
    <BaseButton
      v-else-if="state === 'offline' || state === 'stopped'"
      variant="primary" :size="btnSize" :class="btnClass"
      @click="sendPower('start')"
    >
      <MsIcon name="play_arrow" /> {{ t('userServers.power.start') }}
    </BaseButton>

    <!-- Starting (no pending — e.g. page loaded while server is starting) -->
    <!-- Wings ignores all power commands during starting phase, so no buttons -->
    <BaseButton v-else-if="state === 'starting'" :size="btnSize" :class="btnClass" disabled>
      <Spinner size="xs" /> {{ t('userServers.status.starting') }}
    </BaseButton>

    <!-- Running -->
    <template v-else-if="state === 'running'">
      <BaseButton :size="btnSize" :class="btnClass" @click="sendPower('restart')">
        <MsIcon name="refresh" /> {{ t('userServers.power.restart') }}
      </BaseButton>
      <BaseButton :size="btnSize" :class="btnClass" variant="warning" @click="sendPower('stop')">
        <MsIcon name="power_settings_new" /> {{ t('userServers.power.stop') }}
      </BaseButton>
      <BaseButton :size="btnSize" :class="btnClass" variant="danger" @click="sendPower('kill')">
        <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
      </BaseButton>
    </template>

    <!-- Stopping (no pending — e.g. page loaded while server is stopping) -->
    <template v-else-if="state === 'stopping'">
      <BaseButton :size="btnSize" :class="btnClass" disabled>
        <Spinner size="xs" /> {{ t('userServers.status.stopping') }}
      </BaseButton>
      <BaseButton :size="btnSize" :class="btnClass" variant="danger" @click="sendPower('kill')">
        <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
      </BaseButton>
    </template>
  </div>
</template>

<style scoped>
.power-controls--column {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.power-controls--row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.power-controls--row > * {
  flex: 1;
  min-width: 0;
}

.power-btn {
  width: 100%;
}
</style>
