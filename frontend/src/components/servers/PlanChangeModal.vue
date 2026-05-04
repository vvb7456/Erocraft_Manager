<script setup lang="ts">
/**
 * PlanChangeModal — admin-only modal for rebinding a server to a billing plan.
 *
 * IMPORTANT: This modal ONLY rebinds the plan reference. It does NOT change
 * server resources, image, startup command, or expiration date.
 *
 * Used in:
 *   - ServersPage row actions (single-server mode)
 *   - ServersPage batch action "update_plan" (batchMode = true)
 *   - AdminServerDetailPage lifecycle tab (single-server mode)
 */
import { computed, ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import FormField from '@/components/form/FormField.vue'

defineOptions({ name: 'PlanChangeModal' })

interface AdminPlanLite {
  id: number
  code: string
  display_name: string
  is_active: boolean
}

const props = defineProps<{
  modelValue: boolean
  serverName?: string
  currentPlanId?: number | null
  currentPlanName?: string | null
  batchMode?: boolean
  batchCount?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [v: boolean]
  'confirmed': [planId: number | null]
}>()

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

const plans = ref<AdminPlanLite[]>([])
const loaded = ref(false)
const selectedPlanId = ref<string>('')  // BaseSelect uses string values; '' = unbind
const submitting = ref(false)

async function loadPlans() {
  if (loaded.value) return
  const data = await get<AdminPlanLite[]>('/api/admin/billing/plans?include_inactive=true', { silent: true })
  if (data) {
    plans.value = data
    loaded.value = true
  }
}

const planOptions = computed(() => {
  const opts: { value: string; label: string }[] = [
    { value: '', label: t('servers.modal.updatePlan.unbindOption') },
  ]
  for (const p of plans.value) {
    const suffix = p.is_active ? '' : ` (${t('servers.modal.updatePlan.inactiveTag')})`
    opts.push({ value: String(p.id), label: `${p.display_name} · ${p.code}${suffix}` })
  }
  return opts
})

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      await loadPlans()
      // Initialize selection: in single mode default to current; in batch mode start empty
      if (props.batchMode) {
        selectedPlanId.value = ''
      } else {
        selectedPlanId.value =
          props.currentPlanId !== null && props.currentPlanId !== undefined
            ? String(props.currentPlanId)
            : ''
      }
    }
  },
)

onMounted(() => {
  if (props.modelValue) loadPlans()
})

function close() {
  emit('update:modelValue', false)
}

async function onConfirm() {
  submitting.value = true
  try {
    const planId = selectedPlanId.value === '' ? null : Number(selectedPlanId.value)
    emit('confirmed', planId)
  } finally {
    submitting.value = false
  }
}

const title = computed(() =>
  props.batchMode
    ? t('servers.modal.updatePlan.batchTitle', { n: props.batchCount ?? 0 })
    : t('servers.modal.updatePlan.title'),
)
</script>

<template>
  <BaseModal :model-value="modelValue" :title="title" @update:model-value="emit('update:modelValue', $event)">
    <div class="plan-change">
      <div v-if="!batchMode" class="current-line">
        <span class="cb-label">{{ t('servers.modal.updatePlan.currentBinding') }}</span>
        <span class="cb-plan" :class="{ 'cb-plan--none': !currentPlanName }">
          {{ currentPlanName ?? '—' }}
        </span>
      </div>
      <div v-else class="current-line">
        <span class="cb-label">{{ t('servers.modal.updatePlan.batchSubject', { n: batchCount ?? 0 }) }}</span>
      </div>

      <FormField :label="t('servers.modal.updatePlan.targetPlan')">
        <BaseSelect v-model="selectedPlanId" :options="planOptions" :placeholder="t('servers.modal.updatePlan.unbindOption')" teleport />
      </FormField>
    </div>

    <template #footer>
      <BaseButton variant="ghost" @click="close">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="submitting" @click="onConfirm">
        {{ t('common.btn.confirm') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.plan-change {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.current-line {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  font-size: var(--text-sm);
}

.cb-label {
  color: var(--t2);
}

.cb-plan {
  color: var(--ac2);
  font-weight: 500;
}

.cb-plan--none {
  color: var(--t3);
  font-weight: 400;
}
</style>
