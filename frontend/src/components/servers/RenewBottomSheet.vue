<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useToday } from '@/composables/useToday'
import BottomSheet from '@/components/ui/BottomSheet.vue'
import BaseButton from '@/components/ui/BaseButton.vue'

import RenewConfirmModal from '@/components/servers/RenewConfirmModal.vue'

defineOptions({ name: 'RenewBottomSheet' })

interface ServerItem {
  pteroId: number
  name: string
  expirationDate: string | null
  daysLeft: number | null
  statusLabel: string
  isSuspended: boolean
  planId?: number | null
  isTrial?: boolean
}

const props = defineProps<{
  modelValue: boolean
  server: ServerItem | null
}>()

const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  renewed: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { post } = useApiFetch()
const { toast } = useToast()
const today = useToday()

const renewDate = ref('')
const quickDays = ref<number | null>(null)
const confirmModalOpen = ref(false)

// Reset state when opening
watch(() => props.modelValue, (open) => {
  if (open && props.server) {
    renewDate.value = calcDefaultRenewDate(props.server)
    quickDays.value = null
  }
})

function addDays(base: string, n: number): string {
  const d = new Date(base + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function calcDefaultRenewDate(s: ServerItem): string {
  if (!s.expirationDate || (s.daysLeft !== null && s.daysLeft < 0)) {
    return addDays(today.value, 30)
  }
  return addDays(s.expirationDate, 30)
}

function quickRenew(days: number) {
  if (!props.server) return
  quickDays.value = days
  const isExpired = !props.server.expirationDate || (props.server.daysLeft !== null && props.server.daysLeft < 0)
  const base = isExpired ? today.value : props.server.expirationDate!
  renewDate.value = addDays(base, days)
}

function doRenew() {
  if (!props.server) return
  emit('update:modelValue', false)
  confirmModalOpen.value = true
}

function onRenewed() {
  emit('update:modelValue', false)
  emit('renewed')
}

function statusColor(s: ServerItem): string {
  if (s.daysLeft !== null && s.daysLeft < 0) return 'var(--red)'
  if (s.daysLeft !== null && s.daysLeft <= 7) return 'var(--amber)'
  return 'var(--green)'
}

function expirationText(s: ServerItem): string {
  if (!s.expirationDate) return t('servers.status.permanent')
  if (s.daysLeft !== null && s.daysLeft < 0) return `${s.expirationDate} (${t('servers.status.expired')})`
  if (s.daysLeft === 0) return `${s.expirationDate} (${t('servers.status.today')})`
  if (s.daysLeft !== null) return `${s.expirationDate} (${t('servers.status.days_left', { n: s.daysLeft })})`
  return s.expirationDate
}
</script>

<template>
  <BottomSheet
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    :title="server?.isTrial ? t('servers.renew_modal.convert_title') : t('servers.action.renew')"
  >
    <div v-if="server" class="renew-sheet">
      <div class="renew-sheet__name">{{ server.name }}</div>
      <div class="renew-sheet__current">
        {{ t('servers.table.expiration') }}: <span :style="{ color: statusColor(server) }">{{ expirationText(server) }}</span>
      </div>
      <div class="renew-sheet__label">{{ t('servers.action.quick_renew') }}</div>
      <div class="renew-sheet__quick">
        <button class="quick-btn" :class="{ active: quickDays === 7 }" @click="quickRenew(7)">+7天</button>
        <button class="quick-btn" :class="{ active: quickDays === 30 }" @click="quickRenew(30)">+30天</button>
        <button class="quick-btn" :class="{ active: quickDays === 365 }" @click="quickRenew(365)">+365天</button>
      </div>
      <div class="renew-sheet__label">{{ t('servers.action.custom_date') }}</div>
      <input type="date" class="renew-sheet__date" v-model="renewDate" @input="quickDays = null" />
      <BaseButton variant="primary" block @click="doRenew">
        {{ server?.isTrial ? t('servers.renew_modal.convert_action') : t('servers.action.renew') }}
      </BaseButton>
    </div>
  </BottomSheet>

  <RenewConfirmModal
    v-if="server"
    v-model="confirmModalOpen"
    :server-id="server.pteroId"
    :server-name="server.name"
    :current-expiration-date="server.expirationDate"
    :target-date="renewDate"
    :plan-id="server.planId ?? null"
    :is-trial="server.isTrial ?? false"
    @renewed="onRenewed"
  />
</template>

<style scoped>
.renew-sheet {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.renew-sheet__name {
  font-weight: 600;
}
.renew-sheet__current {
  font-size: .85rem;
  color: var(--t2);
}
.renew-sheet__label {
  font-size: .78rem;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .04em;
  margin-top: var(--sp-1);
}
.renew-sheet__quick {
  display: flex;
  gap: var(--sp-2);
}
.quick-btn {
  flex: 1;
  padding: var(--sp-3) var(--sp-2);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  color: var(--t1);
  font-size: .88rem;
  font-weight: 500;
  cursor: pointer;
  transition: background .15s;
}
.quick-btn:active,
.quick-btn.active {
  background: var(--acg);
  border-color: var(--ac);
  color: var(--ac);
}
.renew-sheet__date {
  width: 100%;
  padding: var(--sp-3);
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  color: var(--t1);
  font-size: .88rem;
  -webkit-appearance: none;
}
.renew-sheet__date:focus {
  border-color: var(--bd-f);
  outline: none;
}
</style>
