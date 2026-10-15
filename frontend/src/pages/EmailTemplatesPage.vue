<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useDirtyFormSection, useParentDirtyForm } from '@/composables/useDirtyForm'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import FormField from '@/components/form/FormField.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import { useClipboard } from '@/composables/useClipboard'
import { emailTemplateKeys as KEYS, type EmailTemplateKey as TemplateKey } from '@/types/emailTemplates'

defineOptions({ name: 'EmailTemplatesPage' })
const props = defineProps<{ templateKey: TemplateKey }>()

interface TemplateData { subject: string; body: string }


const TEMPLATE_VARIABLES: Record<TemplateKey, string[]> = {
  bulk: ['brand_name', 'username', 'email', 'server_name', 'server_id', 'expiration_date'],
  reminder: ['brand_name', 'username', 'server_count', 'expiration_date', 'server_list'],
  expired: ['brand_name', 'username', 'server_count', 'expiration_date', 'server_list', 'grace_days', 'deletion_date'],
  preDelete: ['brand_name', 'username', 'server_name', 'server_id', 'deletion_date'],
  createUser: ['brand_name', 'username', 'email', 'password', 'reset_url'],
  passwordReset: ['brand_name', 'username', 'email', 'reset_url'],
  emailChange: ['brand_name', 'username', 'new_email', 'confirm_url'],
  registerVerify: ['brand_name', 'username', 'email', 'verify_url'],
  alertFired: ['brand_name', 'node_name', 'node_id', 'alert_type', 'alert_type_label', 'severity', 'severity_label', 'message', 'fired_at'],
  alertResolved: ['brand_name', 'node_name', 'node_id', 'alert_type', 'alert_type_label', 'message', 'fired_at', 'resolved_at'],
  orderPaid: ['brand_name', 'order_no', 'plan_name', 'period_count', 'total_days', 'total_yuan', 'currency_code', 'paid_at', 'applied_at', 'server_uuid'],
  orderApplyFailed: ['brand_name', 'order_no', 'plan_name', 'total_yuan', 'currency_code', 'paid_at', 'apply_error'],
  orderApplyAlert: ['brand_name', 'order_no', 'username', 'email', 'plan_name', 'total_yuan', 'currency_code', 'apply_retry_count', 'apply_error'],
  orderRefunded: ['brand_name', 'order_no', 'refund_no', 'refund_amount_yuan', 'currency_code', 'refund_reason', 'refunded_at'],
  serverInstalled: ['brand_name', 'username', 'server_name', 'server_id', 'server_uuid', 'installed_at'],
  referralInviterRewarded: ['brand_name', 'username', 'invitee_username', 'coupon_code', 'coupon_name', 'discount_yuan', 'min_order_yuan', 'min_order_text', 'expires_at'],
  referralInviteeRewarded: ['brand_name', 'username', 'coupon_code', 'coupon_name', 'discount_yuan', 'min_order_yuan', 'min_order_text', 'expires_at'],
}

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()
const { copy } = useClipboard()
const bodyInput = ref<InstanceType<typeof BaseTextarea> | null>(null)

const loading = ref(true)
const previewHtml = ref('')
const previewSubject = ref('')
const previewLoading = ref(false)
let previewReqId = 0

const empty = (): TemplateData => ({ subject: '', body: '' })
const all = ref<Record<TemplateKey, TemplateData>>(
  Object.fromEntries(KEYS.map(k => [k, empty()])) as Record<TemplateKey, TemplateData>,
)
const savedAll = ref<Record<TemplateKey, TemplateData>>(
  Object.fromEntries(KEYS.map(k => [k, empty()])) as Record<TemplateKey, TemplateData>,
)

const isDirty = computed(() => KEYS.some(key => JSON.stringify(all.value[key]) !== JSON.stringify(savedAll.value[key])))
const vars = computed(() => TEMPLATE_VARIABLES[props.templateKey])

// ── Variable chip actions ──
function insertVar(key: string) {
  const ta = bodyInput.value?.element
  if (!ta) return
  const s = ta.selectionStart; const e = ta.selectionEnd
  const c = all.value[props.templateKey]
  c.body = c.body.slice(0, s) + `{{${key}}}` + c.body.slice(e)
  void nextTick(() => { ta.focus(); ta.selectionStart = ta.selectionEnd = s + key.length + 4 })
}

async function copyVar(key: string) {
  await copy(`{{${key}}}`, { successMessage: t('emailTemplates.varCopied', { key }) })
}

// ── Preview ──
async function loadPreview() {
  previewLoading.value = true
  const rid = ++previewReqId
  let html = ''
  let subject = ''
  try {
    const res = await fetch('/api/admin/email-templates/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: props.templateKey, subject: all.value[props.templateKey].subject, body: all.value[props.templateKey].body, theme: 'dark' }),
    })
    if (res.ok) {
      const data = await res.json() as { renderedSubject: string; html: string }
      subject = data.renderedSubject
      html = data.html
    }
  } catch { /* ignore */ }
  if (rid !== previewReqId) return
  previewSubject.value = subject
  previewHtml.value = html
  previewLoading.value = false
}

let previewTimer: ReturnType<typeof setTimeout> | null = null
function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(loadPreview, 300)
}

// ── Save / discard ──
async function save(): Promise<boolean> {
  for (const key of KEYS) {
    const submitted = { ...all.value[key] }
    if (JSON.stringify(submitted) === JSON.stringify(savedAll.value[key])) continue
    if (!await post('/api/admin/email-templates', { type: key, ...submitted })) return false
    savedAll.value[key] = submitted
  }
  toast(t('emailTemplates.saved'), 'success')
  return !isDirty.value
}

function discard() {
  for (const key of KEYS) all.value[key] = { ...savedAll.value[key] }
}

const dirtyForm = useParentDirtyForm()
useDirtyFormSection({ name: 'email-templates', isDirty, save, discard }, dirtyForm)

async function loadData() {
  const data = await get<Record<string, TemplateData>>('/api/admin/email-templates').finally(() => { loading.value = false })
  if (data) {
    for (const k of KEYS) {
      const d = { subject: data[k]?.subject ?? '', body: data[k]?.body ?? '' }
      all.value[k] = { ...d }; savedAll.value[k] = { ...d }
    }
  }
  schedulePreview()
}

watch([() => props.templateKey, () => all.value[props.templateKey].subject, () => all.value[props.templateKey].body], () => {
  if (!loading.value) schedulePreview()
})

onMounted(loadData)
onBeforeUnmount(() => { previewReqId++; if (previewTimer) clearTimeout(previewTimer) })
</script>

<template>
  <div>
    <LoadingCenter v-if="loading" />

    <div v-else>
      <h3 class="template-title">{{ t(`emailTemplates.${templateKey}.title`) }}</h3>
      <div class="tpl-workspace" :inert="dirtyForm.saving.value">
        <!-- Left: editor -->
        <section class="tpl-col">
          <BaseCard>
            <div class="tpl-vars">
              <span class="tpl-vars-label">{{ t('emailTemplates.placeholders') }}</span>
              <button
                v-for="v in vars" :key="v"
                class="tpl-var-chip"
                :title="t(`emailTemplates.var.${v}`)"
                @click="copyVar(v)"
                @dblclick="insertVar(v)"
                v-text="'{{' + v + '}}'"
              />
            </div>

            <FormField :label="t('emailTemplates.subject')">
              <BaseInput v-model="all[templateKey].subject" />
            </FormField>

            <FormField :label="t('emailTemplates.body')">
              <BaseTextarea
                ref="bodyInput"
                v-model="all[templateKey].body"
                :rows="18"
                mono
              />
            </FormField>
          </BaseCard>
        </section>

        <!-- Right: preview -->
        <section class="tpl-col tpl-col--preview">
          <BaseCard>
            <template #header>
              <span class="tpl-preview-label">{{ t('emailTemplates.preview') }}</span>
            </template>
            <div v-if="previewSubject" class="tpl-preview-subject">{{ previewSubject }}</div>
            <div class="tpl-preview-shell" :class="{ 'tpl-preview-shell--loading': previewLoading }">
              <LoadingCenter v-if="previewLoading" />
              <iframe
                v-else-if="previewHtml"
                class="tpl-preview-frame"
                :srcdoc="previewHtml"
                sandbox=""
                :title="t('emailTemplates.preview')"
              />
              <div v-else class="tpl-preview-empty">{{ t('emailTemplates.previewEmpty') }}</div>
            </div>
          </BaseCard>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.template-title { font-size: var(--text-md); font-weight: 600; margin: 0; }
/* Two-column workspace */
.tpl-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-6);
  align-items: start;
  margin-top: var(--sp-4);
}
.tpl-col { display: flex; flex-direction: column; gap: var(--sp-4); min-width: 0; }
.tpl-col--preview { position: sticky; top: 0; }

/* Variable tokens */
.tpl-vars {
  display: flex; align-items: center; gap: var(--sp-2);
  flex-wrap: wrap; margin-bottom: var(--sp-3); padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--bd);
}
.tpl-vars-label { color: var(--t3); font-size: var(--text-sm); white-space: nowrap; }
.tpl-var-chip {
  display: inline-flex; align-items: center;
  padding: 2px 8px; border: 1px solid var(--bd);
  border-radius: var(--r-xs); background: var(--bg-in);
  color: var(--t2); font-family: var(--font-mono);
  font-size: var(--text-xs); cursor: pointer; transition: border-color .15s, color .15s;
}
.tpl-var-chip:hover { border-color: var(--ac); color: var(--ac); }

/* Preview */
.tpl-preview-label { font-weight: 600; }
.tpl-preview-subject {
  padding: var(--sp-2) 0; margin-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
  font-size: var(--text-sm); font-weight: 600; color: var(--t1);
}
.tpl-preview-shell {
  min-height: 720px; border: 1px solid var(--bd);
  border-radius: var(--r-sm); overflow: hidden; background: var(--bg3);
}
.tpl-preview-shell--loading { display: flex; align-items: center; justify-content: center; }
.tpl-preview-frame { width: 100%; min-height: 720px; border: 0; background: var(--bg3); }
.tpl-preview-empty {
  display: flex; align-items: center; justify-content: center;
  min-height: 720px; color: var(--t2); font-size: var(--text-sm);
}

@media (max-width: 1100px) {
  .tpl-workspace { grid-template-columns: 1fr; }
  .tpl-col--preview { position: static; }
}
</style>
