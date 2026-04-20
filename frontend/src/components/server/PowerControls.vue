<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useConfirm } from '@/composables/useConfirm'
import { useApiFetch } from '@/composables/useApiFetch'
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
}>()

const { t } = useI18n({ useScope: 'global' })
const { confirm } = useConfirm()
const { post } = useApiFetch()

async function sendPower(action: string) {
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

  await post(`/api/user/servers/${props.serverId}/power`, { action })
}
</script>

<template>
  <div class="power-controls" :class="['power-controls--' + (layout ?? 'column'), { 'power-controls--disabled': disabled }]">
    <!-- External disabled overlay -->
    <template v-if="disabled">
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        disabled
      >
        <MsIcon name="power_settings_new" /> {{ disabledReason || t('userServers.power.title') }}
      </BaseButton>
    </template>

    <!-- Installing -->
    <BaseButton
      v-else-if="isInstalling"
      variant="primary"
      :size="layout === 'row' ? 'sm' : undefined"
      :class="{ 'power-btn': layout !== 'row' }"
      disabled
    >
      <Spinner size="xs" /> {{ t('userServers.status.installing') }}
    </BaseButton>

    <!-- Suspended -->
    <BaseButton
      v-else-if="isSuspended"
      variant="primary"
      :size="layout === 'row' ? 'sm' : undefined"
      :class="{ 'power-btn': layout !== 'row' }"
      disabled
    >
      <MsIcon name="play_arrow" /> {{ t('userServers.power.start') }}
    </BaseButton>

    <!-- Offline / Stopped -->
    <BaseButton
      v-else-if="state === 'offline' || state === 'stopped'"
      variant="primary"
      :size="layout === 'row' ? 'sm' : undefined"
      :class="{ 'power-btn': layout !== 'row' }"
      @click="sendPower('start')"
    >
      <MsIcon name="play_arrow" /> {{ t('userServers.power.start') }}
    </BaseButton>

    <!-- Starting -->
    <template v-else-if="state === 'starting'">
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        disabled
      >
        <Spinner size="xs" /> {{ t('userServers.status.starting') }}
      </BaseButton>
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        variant="danger"
        @click="sendPower('kill')"
      >
        <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
      </BaseButton>
    </template>

    <!-- Running -->
    <template v-else-if="state === 'running'">
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        @click="sendPower('restart')"
      >
        <MsIcon name="refresh" /> {{ t('userServers.power.restart') }}
      </BaseButton>
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        variant="warning"
        @click="sendPower('stop')"
      >
        <MsIcon name="power_settings_new" /> {{ t('userServers.power.stop') }}
      </BaseButton>
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        variant="danger"
        @click="sendPower('kill')"
      >
        <MsIcon name="power_off" /> {{ t('userServers.power.kill') }}
      </BaseButton>
    </template>

    <!-- Stopping -->
    <template v-else-if="state === 'stopping'">
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        disabled
      >
        <Spinner size="xs" /> {{ t('userServers.status.stopping') }}
      </BaseButton>
      <BaseButton
        :size="layout === 'row' ? 'sm' : undefined"
        :class="{ 'power-btn': layout !== 'row' }"
        variant="danger"
        @click="sendPower('kill')"
      >
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
