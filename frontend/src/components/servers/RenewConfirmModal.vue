<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import FormField from '@/components/form/FormField.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'

defineOptions({ name: 'RenewConfirmModal' })

const props = defineProps<{
  modelValue: boolean
  serverId: number
  serverName: string
  currentExpirationDate?: string | null
  targetDate: string | null
  planId?: number | null
  isTrial?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [val: boolean]
  renewed: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()

const loading = ref(false)
const planPriceFen = ref<number | null>(null)
const planName = ref<string | null>(null)

const form = ref({
  channel: 'taobao' as 'taobao' | 'xianyu' | 'other',
  external_order_id: '',
  amount_yuan: 0,
  channel_note: '',
})

const channelOptions = computed(() => [
  { value: 'taobao', label: t('servers.channel.taobao') },
  { value: 'xianyu', label: t('servers.channel.xianyu') },
  { value: 'other', label: t('servers.channel.other') },
])

const isEcommerce = computed(() => form.value.channel === 'taobao' || form.value.channel === 'xianyu')

watch(() => form.value.channel, (ch) => {
  if (ch === 'other') {
    form.value.external_order_id = ''
    form.value.amount_yuan = 0
    form.value.channel_note = ''
  } else if (planPriceFen.value !== null && (!form.value.amount_yuan || form.value.amount_yuan === 0)) {
    form.value.amount_yuan = planPriceFen.value / 100
  }
})

// Load plan details to get monthly price if server is bound to a plan
watch(() => props.modelValue, async (open) => {
  if (!open) return
  form.value = {
    channel: props.planId ? 'taobao' : 'other',
    external_order_id: '',
    amount_yuan: 0,
    channel_note: '',
  }
  planPriceFen.value = null
  planName.value = null

  if (props.planId) {
    const p = await get<{ display_name: string; price_fen: number; plan_type?: string; linked_plan_id?: number | null }>(`/api/admin/billing/plans/${props.planId}`)
    if (p) {
      if (props.isTrial && p.plan_type === 'trial' && p.linked_plan_id) {
        const linked = await get<{ display_name: string; price_fen: number }>(`/api/admin/billing/plans/${p.linked_plan_id}`)
        if (linked) {
          planPriceFen.value = linked.price_fen
          planName.value = `${linked.display_name} (${t('servers.renew_modal.convert_badge')})`
          if (form.value.channel !== 'other') {
            form.value.amount_yuan = linked.price_fen / 100
          }
          return
        }
      }
      planPriceFen.value = p.price_fen
      planName.value = p.display_name
      if (form.value.channel !== 'other') {
        form.value.amount_yuan = p.price_fen / 100
      }
    }
  }
})

async function submit() {
  const f = form.value
  if (isEcommerce.value) {
    if (!props.planId) {
      toast(t('servers.renew_modal.validation_plan_required'), 'error')
      return
    }
    if (!f.external_order_id.trim()) {
      toast(t('servers.renew_modal.validation_order_required'), 'error')
      return
    }
    if (f.amount_yuan === undefined || isNaN(f.amount_yuan) || f.amount_yuan <= 0) {
      toast(t('servers.renew_modal.validation_amount_required'), 'error')
      return
    }
  }

  loading.value = true
  const res = await post<{ message: string }>(`/api/admin/servers/${props.serverId}/renew`, {
    date: props.targetDate || null,
    channel: f.channel,
    external_order_id: isEcommerce.value ? f.external_order_id.trim() : null,
    amount_yuan: isEcommerce.value && f.amount_yuan !== undefined ? Number(f.amount_yuan) : null,
    channel_note: isEcommerce.value && f.channel_note.trim() ? f.channel_note.trim() : null,
  })
  loading.value = false

  if (res) {
    toast(res.message, 'success')
    emit('update:modelValue', false)
    emit('renewed')
  }
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    :title="isTrial ? t('servers.renew_modal.convert_title') : t('servers.renew_modal.title')"
    :icon="isTrial ? 'autorenew' : 'update'"
    size="lg"
  >
    <div class="renew-confirm-form">
      <!-- Convert warning banner for trial servers -->
      <div v-if="isTrial" class="convert-notice-wrap">
        <AlertBanner tone="warning" dense>
          {{ t('servers.renew_modal.convert_notice') }}
        </AlertBanner>
      </div>

      <!-- Target info summary card -->
      <div class="summary-card">
        <div class="summary-row">
          <span class="summary-label">{{ t('servers.renew_modal.server_name') }}:</span>
          <span class="summary-val highlight">{{ serverName }}</span>
        </div>
        <div class="summary-row">
          <span class="summary-label">{{ t('servers.renew_modal.current_expiration') }}:</span>
          <span class="summary-val">{{ currentExpirationDate || t('servers.status.permanent') }}</span>
        </div>
        <div class="summary-row">
          <span class="summary-label">{{ t('servers.renew_modal.new_expiration') }}:</span>
          <span class="summary-val highlight">{{ targetDate || t('servers.status.permanent') }}</span>
        </div>
        <div v-if="planName" class="summary-row">
          <span class="summary-label">{{ isTrial ? t('servers.renew_modal.target_plan') : t('servers.table.plan') }}:</span>
          <span class="summary-val">{{ planName }}</span>
        </div>
      </div>

      <!-- Channel & Order ID -->
      <div class="form-row">
        <FormField :label="t('servers.channel.label')" required density="compact" class="form-col">
          <BaseSelect v-model="form.channel" :options="channelOptions" />
        </FormField>
        <FormField :label="t('servers.channel.order_id')" :required="isEcommerce" density="compact" class="form-col">
          <BaseInput
            v-model="form.external_order_id"
            :placeholder="t('servers.channel.order_id_placeholder')"
            :disabled="!isEcommerce"
          />
        </FormField>
      </div>

      <!-- Amount & Note -->
      <div class="form-row">
        <FormField :label="t('servers.channel.amount')" :required="isEcommerce" density="compact" class="form-col">
          <NumberInput
            v-model="form.amount_yuan"
            :min="0"
            :step="0.01"
            :placeholder="t('servers.channel.amount_placeholder')"
            :disabled="!isEcommerce"
          />
        </FormField>
        <FormField :label="t('servers.channel.note')" density="compact" class="form-col">
          <BaseInput
            v-model="form.channel_note"
            :placeholder="t('servers.channel.note_placeholder')"
            :disabled="!isEcommerce"
          />
        </FormField>
      </div>
    </div>

    <template #footer>
      <div class="modal-actions">
        <BaseButton @click="close">{{ t('common.btn.cancel') }}</BaseButton>
        <BaseButton variant="primary" :loading="loading" @click="submit">
          {{ t('servers.renew_modal.confirm_btn') }}
        </BaseButton>
      </div>
    </template>
  </BaseModal>
</template>

<style scoped>
.renew-confirm-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4, 16px);
}

.convert-notice-wrap {
  margin-bottom: var(--sp-3, 12px);
}
.summary-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2, 8px);
  padding: var(--sp-3, 12px) var(--sp-4, 16px);
  background: var(--bg3, #1e293b);
  border: 1px solid var(--bd, #334155);
  border-radius: var(--radius-md, 8px);
  font-size: 0.875rem;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.summary-label {
  color: var(--t3, #94a3b8);
}

.summary-val {
  color: var(--t1, #f8fafc);
  font-weight: 500;
}

.summary-val.highlight {
  color: var(--ac, #14b8a6);
  font-weight: 600;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4, 16px);
}

@media (max-width: 640px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2, 8px);
}
</style>
