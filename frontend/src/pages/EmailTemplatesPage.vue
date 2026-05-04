<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import PageHeader from '@/components/layout/PageHeader.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import FormField from '@/components/form/FormField.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'EmailTemplatesPage' })

type TemplateKey =
  | 'bulk' | 'reminder' | 'preDelete' | 'createUser' | 'passwordReset'
  | 'emailChange' | 'registerVerify' | 'alertFired' | 'alertResolved'
  | 'orderPaid' | 'orderApplyFailed' | 'orderApplyAlert' | 'orderRefunded'

interface TemplateData { subject: string; body: string }

const KEYS: TemplateKey[] = [
  'bulk', 'reminder', 'preDelete', 'createUser', 'passwordReset',
  'emailChange', 'registerVerify', 'alertFired', 'alertResolved',
  'orderPaid', 'orderApplyFailed', 'orderApplyAlert', 'orderRefunded',
]

const TEMPLATE_VARIABLES: Record<TemplateKey, string[]> = {
  bulk: ['brand_name', 'username', 'email', 'server_name', 'server_id', 'expiration_date'],
  reminder: ['brand_name', 'username', 'server_count', 'expiration_date', 'server_list'],
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
}

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const activeKey = ref<TemplateKey>('bulk')
const loading = ref(true)
const saveLoading = ref(false)
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

const cur = computed(() => all.value[activeKey.value])
const saved = computed(() => savedAll.value[activeKey.value])
const isDirty = computed(() => cur.value.subject !== saved.value.subject || cur.value.body !== saved.value.body)
const vars = computed(() => TEMPLATE_VARIABLES[activeKey.value])

const tabs = KEYS.map(k => ({ key: k, label: t(`emailTemplates.${k}.title`) }))

// ── Variable chip actions ──
function insertVar(key: string) {
  const ta = document.querySelector('.tpl-body-textarea') as HTMLTextAreaElement | null
  if (!ta) return
  const s = ta.selectionStart; const e = ta.selectionEnd
  const c = all.value[activeKey.value]
  c.body = c.body.slice(0, s) + `{{${key}}}` + c.body.slice(e)
  void nextTick(() => { ta.focus(); ta.selectionStart = ta.selectionEnd = s + key.length + 4 })
}

async function copyVar(key: string) {
  await navigator.clipboard.writeText(`{{${key}}}`)
  toast(t('emailTemplates.varCopied', { key }), 'success')
}

// ── Preview ──
async function loadPreview() {
  previewLoading.value = true
  const rid = ++previewReqId
  let html = ''
  try {
    const res = await fetch('/api/admin/email-templates/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: activeKey.value, subject: all.value[activeKey.value].subject, body: all.value[activeKey.value].body, theme: 'dark' }),
    })
    if (res.ok) {
      const data = await res.json() as { renderedSubject: string; html: string }
      previewSubject.value = data.renderedSubject
      html = sanitize(data.html)
    }
  } catch { /* ignore */ }
  if (rid !== previewReqId) return
  previewHtml.value = html
  previewLoading.value = false
}

function sanitize(html: string): string {
  if (!html) return ''
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.querySelectorAll('script, iframe, object, embed').forEach(n => n.remove())
  doc.querySelectorAll('*').forEach(el => {
    for (const a of [...el.attributes]) {
      if (a.name.startsWith('on') || (a.value || '').toLowerCase().startsWith('javascript:')) el.removeAttribute(a.name)
    }
  })
  return '<!doctype html>\n' + doc.documentElement.outerHTML
}

let previewTimer: ReturnType<typeof setTimeout> | null = null
function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(loadPreview, 300)
}

// ── Save / discard ──
async function save() {
  saveLoading.value = true
  const k = activeKey.value; const c = all.value[k]
  const res = await post('/api/admin/email-templates', {
    type: k,
    subject: c.subject,
    body: c.body,
  })
  saveLoading.value = false
  if (res) {
    savedAll.value[k] = { ...c }
    toast(t('emailTemplates.saved'), 'success')
  }
}

function discard() {
  all.value[activeKey.value] = { ...savedAll.value[activeKey.value] }
}

const dirtyForm = provideDirtyForm({
  prompt: async () => {
    const result = await confirm({
      title: t('emailTemplates.unsavedTitle'),
      message: t('emailTemplates.unsavedMessage'),
      confirmText: t('emailTemplates.unsavedSave'),
      cancelText: t('emailTemplates.unsavedDiscard'),
      altText: t('emailTemplates.unsavedStay'),
    })
    if (result === 'alt') return 'stay'
    return result === true ? 'save' : 'discard'
  },
})
dirtyForm.attachLeaveGuard()
useDirtyFormSection({ name: 'email-templates', isDirty, save, discard }, dirtyForm)

async function loadData() {
  const data = await get<Record<string, TemplateData>>('/api/admin/email-templates')
  if (data) {
    for (const k of KEYS) {
      const d = { subject: data[k]?.subject ?? '', body: data[k]?.body ?? '' }
      all.value[k] = { ...d }; savedAll.value[k] = { ...d }
    }
  }
  loading.value = false
  schedulePreview()
}

watch([activeKey, () => all.value[activeKey.value].subject, () => all.value[activeKey.value].body], () => {
  if (!loading.value) schedulePreview()
})

onMounted(loadData)
</script>

<template>
  <PageHeader :title="t('emailTemplates.title')" icon="mail" />

  <div class="page-body">
    <LoadingCenter v-if="loading" />

    <template v-else>
      <TabSwitcher v-model="activeKey" :tabs="tabs" />

      <div class="tpl-workspace">
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
              <BaseInput v-model="all[activeKey].subject" />
            </FormField>

            <FormField :label="t('emailTemplates.body')">
              <BaseTextarea
                v-model="all[activeKey].body"
                :rows="18"
                mono
                input-class="tpl-body-textarea"
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
                sandbox="allow-scripts"
                title="email-preview"
              />
              <div v-else class="tpl-preview-empty">{{ t('emailTemplates.previewEmpty') }}</div>
            </div>
          </BaseCard>
        </section>
      </div>
    </template>
  </div>

  <DirtyBar :dirty="dirtyForm.isDirty.value" :saving="saveLoading" @save="dirtyForm.save" @discard="dirtyForm.discard" />
</template>

<style scoped>
/* Two-column workspace */
.tpl-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-6);
  align-items: start;
  margin-top: var(--sp-4);
}
.tpl-col { display: flex; flex-direction: column; gap: var(--sp-4); min-width: 0; }
.tpl-col--preview { position: sticky; top: calc(64px + var(--sp-4)); }

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
  color: var(--t2); font-family: var(--font-mono, 'IBM Plex Mono', monospace);
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

@media (max-width: 1080px) {
  .tpl-workspace { grid-template-columns: 1fr; }
  .tpl-col--preview { position: static; }
}
</style>
