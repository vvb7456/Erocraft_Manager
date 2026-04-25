<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BottomSheet from '@/components/ui/BottomSheet.vue'
import BaseButton from '@/components/ui/BaseButton.vue'

defineOptions({ name: 'RenewBottomSheet' })

interface ServerItem {
  pteroId: number
  name: string
  expirationDate: string | null
  daysLeft: number | null
  statusLabel: string
  isSuspended: boolean
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

const renewDate = ref('')
const quickDays = ref<number | null>(null)

// Reset state when opening
watch(() => props.modelValue, (open) => {
  if (open && props.server) {
    renewDate.value = calcDefaultRenewDate(props.server)
    quickDays.value = null
  }
})

function calcDefaultRenewDate(s: ServerItem): string {
  const addDays = (base: Date, n: number) => {
    const d = new Date(base)
    d.setDate(d.getDate() + n)
    return d.toISOString().slice(0, 10)
  }
  const today = new Date()
  if (!s.expirationDate || (s.daysLeft !== null && s.daysLeft < 0)) {
    return addDays(today, 30)
  }
  return addDays(new Date(s.expirationDate + 'T00:00:00'), 30)
}

function quickRenew(days: number) {
  if (!props.server) return
  quickDays.value = days
  const today = new Date()
  const isExpired = !props.server.expirationDate || (props.server.daysLeft !== null && props.server.daysLeft < 0)
  const base = isExpired ? today : new Date(props.server.expirationDate! + 'T00:00:00')
  base.setDate(base.getDate() + days)
  renewDate.value = base.toISOString().slice(0, 10)
}

async function doRenew() {
  if (!props.server) return
  const res = await post<{ message: string }>(`/api/admin/servers/${props.server.pteroId}/renew`, { date: renewDate.value })
  if (res) {
    toast(res.message, 'success')
    emit('update:modelValue', false)
    emit('renewed')
  }
}

function statusColor(s: ServerItem): string {
  if (s.isSuspended) return 'var(--red)'
  switch (s.statusLabel) {
    case 'normal': return 'var(--green)'
    case 'expiring_soon': return 'var(--amber)'
    case 'expired': return 'var(--red)'
    default: return 'var(--t3)'
  }
}

function expirationText(s: ServerItem): string {
  if (s.expirationDate === null) return t('servers.status.permanent')
  if (s.daysLeft !== null && s.daysLeft < 0) return `${s.expirationDate} (${t('servers.status.expired')})`
  if (s.daysLeft === 0) return `${s.expirationDate} (${t('servers.status.today')})`
  if (s.daysLeft !== null) return `${s.expirationDate} (${t('servers.status.days_left', { n: s.daysLeft })})`
  return s.expirationDate
}
</script>

<template>
  <BottomSheet :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)" :title="t('servers.action.renew')">
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
      <BaseButton variant="primary" block @click="doRenew">{{ t('servers.action.renew') }}</BaseButton>
    </div>
  </BottomSheet>
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
