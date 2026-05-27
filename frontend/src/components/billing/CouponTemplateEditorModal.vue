<script lang="ts">
/**
 * CouponTemplateEditorModal — admin coupon-template create/edit.
 *
 * Mirrors the small-form pattern used elsewhere in `components/billing/`:
 * a single-tab BaseModal with FormField rows. Save POSTs (create) or
 * PATCHes (edit) to `/api/admin/billing/coupon-templates`.
 */
export type CouponTemplateEditorMode = 'create' | 'edit'

export interface CouponTemplate {
  id: number
  code: string
  name: string
  description: string | null
  discount_fen: number
  min_order_fen: number
  valid_days: number
  applicable_plan_ids: number[] | null
  applicable_order_kinds: string[] | null
  is_active: boolean
  is_builtin: boolean
  created_at: string
  updated_at: string
}
</script>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import type { AdminPlan } from '@/components/billing/PlanEditorModal.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import FormField from '@/components/form/FormField.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import NumberInput from '@/components/form/NumberInput.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'

defineOptions({ name: 'CouponTemplateEditorModal' })

const props = defineProps<{
  modelValue: boolean
  mode: CouponTemplateEditorMode
  template: CouponTemplate | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [tpl: CouponTemplate]
}>()

const { t } = useI18n({ useScope: 'global' })
const { raw } = useApiFetch()
const { toast } = useToast()

interface FormState {
  code: string
  name: string
  description: string
  discount_yuan: number
  min_order_yuan: number
  valid_days: number
  applicable_plan_ids: number[]   // empty = all plans
  applicable_order_kinds: string[]   // multi-select; empty = all kinds
  is_active: boolean
}

const empty: FormState = {
  code: '', name: '', description: '',
  discount_yuan: 5, min_order_yuan: 0,
  valid_days: 30,
  applicable_plan_ids: [],
  applicable_order_kinds: [],
  is_active: true,
}

const form = ref<FormState>({ ...empty })
const saving = ref(false)
const saveError = ref<string | null>(null)

const orderKindOptions = computed(() => [
  { value: 'new_purchase', label: t('billing.coupons.kinds.newPurchase') },
  { value: 'renew',        label: t('billing.coupons.kinds.renew') },
  { value: 'upgrade',      label: t('billing.coupons.kinds.upgrade') },
])

const plans = ref<AdminPlan[]>([])
const planOptions = computed(() =>
  plans.value.map((p) => ({
    value: p.id,
    label: `${p.code} · ${p.display_name}`,
  })),
)

async function loadPlans() {
  if (plans.value.length) return
  const data = await raw('/api/admin/billing/plans?include_inactive=true', { silent: true })
  if (data && data.ok) {
    try { plans.value = await data.json() as AdminPlan[] } catch { /* ignore */ }
  }
}

watch(() => props.modelValue, (open) => {
  if (!open) return
  saveError.value = null
  void loadPlans()
  if (props.mode === 'edit' && props.template) {
    const tpl = props.template
    form.value = {
      code: tpl.code,
      name: tpl.name,
      description: tpl.description ?? '',
      discount_yuan: tpl.discount_fen / 100,
      min_order_yuan: tpl.min_order_fen / 100,
      valid_days: tpl.valid_days,
      applicable_plan_ids: [...(tpl.applicable_plan_ids ?? [])],
      applicable_order_kinds: [...(tpl.applicable_order_kinds ?? [])],
      is_active: tpl.is_active,
    }
  } else {
    form.value = { ...empty, applicable_plan_ids: [], applicable_order_kinds: [] }
  }
})

const modalTitle = computed(() =>
  props.mode === 'edit'
    ? t('billing.admin.couponTemplates.editTitle', { code: props.template?.code ?? '' })
    : t('billing.admin.couponTemplates.createTitle'),
)

function yuanToFen(n: number): number {
  return Number.isFinite(n) ? Math.round(n * 100) : 0
}

const canSave = computed(() => {
  if (saving.value) return false
  if (!form.value.code.trim() || !form.value.name.trim()) return false
  if (yuanToFen(form.value.discount_yuan) <= 0) return false
  if (yuanToFen(form.value.min_order_yuan) < 0) return false
  if (form.value.valid_days <= 0) return false
  return true
})

async function doSave() {
  if (!canSave.value) return
  saving.value = true
  saveError.value = null
  try {
    const isEdit = props.mode === 'edit' && props.template
    const payload: Record<string, unknown> = {
      name: form.value.name.trim(),
      description: form.value.description.trim() || null,
      discount_fen: yuanToFen(form.value.discount_yuan),
      min_order_fen: yuanToFen(form.value.min_order_yuan),
      valid_days: form.value.valid_days,
      applicable_plan_ids: form.value.applicable_plan_ids.length
        ? form.value.applicable_plan_ids
        : null,
      applicable_order_kinds: form.value.applicable_order_kinds.length
        ? form.value.applicable_order_kinds
        : null,
      is_active: form.value.is_active,
    }
    if (!isEdit) payload.code = form.value.code.trim().toUpperCase()

    const url = isEdit
      ? `/api/admin/billing/coupon-templates/${props.template!.id}`
      : '/api/admin/billing/coupon-templates'
    const res = await raw(url, {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
      silent: true,
    })
    if (res && res.ok) {
      const saved = await res.json() as CouponTemplate
      emit('saved', saved)
      toast(t('billing.admin.couponTemplates.saveOk'), 'success')
      emit('update:modelValue', false)
    } else if (res) {
      let detail = `HTTP ${res.status}`
      try { const body = await res.json(); detail = body.detail || body.message || detail } catch { /* ignore */ }
      saveError.value = String(detail)
    } else {
      saveError.value = 'Network error'
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    @update:model-value="(v) => emit('update:modelValue', v)"
    :title="modalTitle"
    icon="confirmation_number"
    size="md"
  >
    <div class="editor">
      <AlertBanner v-if="saveError" tone="danger" class="editor__error">
        {{ saveError }}
      </AlertBanner>

      <FormField :label="t('billing.admin.couponTemplates.field.code')"
                 :hint="props.mode === 'edit' ? t('billing.admin.couponTemplates.field.codeLocked') : t('billing.admin.couponTemplates.field.codeHint')">
        <BaseInput v-model="form.code" :disabled="props.mode === 'edit'" placeholder="WELCOME10" />
      </FormField>

      <FormField :label="t('billing.admin.couponTemplates.field.name')">
        <BaseInput v-model="form.name" />
      </FormField>

      <FormField :label="t('billing.admin.couponTemplates.field.description')">
        <BaseTextarea v-model="form.description" :rows="2" />
      </FormField>

      <div class="grid-2">
        <FormField :label="t('billing.admin.couponTemplates.field.discountYuan')">
          <NumberInput v-model="form.discount_yuan" :min="0.01" :step="0.01" />
        </FormField>
        <FormField :label="t('billing.admin.couponTemplates.field.minOrderYuan')"
                   :hint="t('billing.admin.couponTemplates.field.minOrderHint')">
          <NumberInput v-model="form.min_order_yuan" :min="0" :step="0.01" />
        </FormField>
      </div>

      <FormField :label="t('billing.admin.couponTemplates.field.validDays')">
        <NumberInput v-model="form.valid_days" :min="1" :max="3650" />
      </FormField>

      <FormField :label="t('billing.admin.couponTemplates.field.applicableOrderKinds')"
                 :hint="t('billing.admin.couponTemplates.field.applicableOrderKindsHint')">
        <BaseSelect v-model="form.applicable_order_kinds"
                    :options="orderKindOptions"
                    multiple
                    teleport
                    :placeholder="t('billing.admin.couponTemplates.field.allKinds')" />
      </FormField>

      <FormField :label="t('billing.admin.couponTemplates.field.applicablePlanIds')"
                 :hint="t('billing.admin.couponTemplates.field.applicablePlanIdsHint')">
        <BaseSelect v-model="form.applicable_plan_ids"
                    :options="planOptions"
                    multiple
                    searchable
                    teleport
                    :placeholder="t('billing.admin.couponTemplates.field.allPlans')" />
      </FormField>

      <FormField :label="t('billing.admin.couponTemplates.field.isActive')" layout="horizontal">
        <ToggleSwitch v-model="form.is_active" size="sm" />
      </FormField>
    </div>

    <template #footer>
      <BaseButton @click="emit('update:modelValue', false)">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="saving" :disabled="!canSave" @click="doSave">
        {{ t('common.btn.save') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.editor__error {
  margin-bottom: var(--sp-2);
}
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}
@media (max-width: 640px) {
  .grid-2 { grid-template-columns: 1fr; }
}
</style>
