<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { provideDirtyForm, useDirtyFormSection } from '@/composables/useDirtyForm'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import Spinner from '@/components/ui/Spinner.vue'
import FormField from '@/components/form/FormField.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import ChipSelect, { type ChipOption } from '@/components/ui/ChipSelect.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Badge from '@/components/ui/Badge.vue'
import DirtyBar from '@/components/ui/DirtyBar.vue'
import { useTheme } from '@/composables/useTheme'

defineOptions({ name: 'EmailTemplatesPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const theme = useTheme()

type TemplateKey =
  | 'bulk'
  | 'reminder'
  | 'preDelete'
  | 'createUser'
  | 'passwordReset'
  | 'emailChange'
  | 'registerVerify'
  | 'alertFired'
  | 'alertResolved'

interface TemplateData {
  subject: string
  body: string
}

interface PreviewResponse {
  renderedSubject: string
  html: string
}

const TEMPLATE_KEYS: TemplateKey[] = [
  'bulk',
  'reminder',
  'preDelete',
  'createUser',
  'passwordReset',
  'emailChange',
  'registerVerify',
  'alertFired',
  'alertResolved',
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
}

const templates = ref<Record<TemplateKey, TemplateData>>({
  bulk: { subject: '', body: '' },
  reminder: { subject: '', body: '' },
  preDelete: { subject: '', body: '' },
  createUser: { subject: '', body: '' },
  passwordReset: { subject: '', body: '' },
  emailChange: { subject: '', body: '' },
  registerVerify: { subject: '', body: '' },
  alertFired: { subject: '', body: '' },
  alertResolved: { subject: '', body: '' },
})

// Snapshot of saved server-side values; updated after each successful
// save() / saveAllDirty(). Used to compute per-template dirty flags.
const orig = ref<Record<TemplateKey, TemplateData>>({
  bulk: { subject: '', body: '' },
  reminder: { subject: '', body: '' },
  preDelete: { subject: '', body: '' },
  createUser: { subject: '', body: '' },
  passwordReset: { subject: '', body: '' },
  emailChange: { subject: '', body: '' },
  registerVerify: { subject: '', body: '' },
  alertFired: { subject: '', body: '' },
  alertResolved: { subject: '', body: '' },
})

function isTemplateDirty(key: TemplateKey): boolean {
  const cur = templates.value[key]
  const o = orig.value[key]
  return cur.subject !== o.subject || cur.body !== o.body
}
const dirtyKeys = computed<TemplateKey[]>(() =>
  TEMPLATE_KEYS.filter(isTemplateDirty),
)
const isDirty = computed(() => dirtyKeys.value.length > 0)

const activeTemplate = ref<TemplateKey>('bulk')
const initialLoading = ref(true)
const saveLoading = ref(false)
const previewLoading = ref(false)
const previewHtml = ref('')
const previewSubject = ref('')
const prefersDarkQuery = ref<MediaQueryList | null>(null)

let previewTimer: ReturnType<typeof setTimeout> | null = null
let previewRequestId = 0

const currentTemplate = computed(() => templates.value[activeTemplate.value])
const currentVariables = computed(() => TEMPLATE_VARIABLES[activeTemplate.value])
const chipOptions = computed<ChipOption[]>(() =>
  TEMPLATE_KEYS.map((key) => ({
    value: key,
    label: t(`emailTemplates.${key}.title`),
    title: t(`emailTemplates.${key}.desc`),
  })),
)
const sanitizedPreviewHtml = computed(() => sanitizePreviewHtml(previewHtml.value))
const previewTheme = computed<'dark' | 'light'>(() => {
  if (theme.mode.value === 'dark') return 'dark'
  if (theme.mode.value === 'light') return 'light'
  return prefersDarkQuery.value?.matches ? 'dark' : 'light'
})

function tokenLabel(key: string): string {
  return `{{${key}}}`
}

function sanitizePreviewHtml(html: string): string {
  if (!html || typeof window === 'undefined') return html
  const doc = new DOMParser().parseFromString(html, 'text/html')

  doc.querySelectorAll('script, iframe, object, embed').forEach((node) => node.remove())
  doc.querySelectorAll('*').forEach((el) => {
    for (const attr of [...el.attributes]) {
      const name = attr.name.toLowerCase()
      const value = attr.value.trim().toLowerCase()
      if (name.startsWith('on') || value.startsWith('javascript:')) {
        el.removeAttribute(attr.name)
      }
    }
  })

  return '<!doctype html>\n' + doc.documentElement.outerHTML
}

async function fetchPreview() {
  const requestId = ++previewRequestId
  previewLoading.value = true

  try {
    const res = await fetch('/api/email-templates/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: activeTemplate.value,
        subject: currentTemplate.value.subject,
        body: currentTemplate.value.body,
        theme: previewTheme.value,
      }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)

    const data = await res.json() as PreviewResponse
    if (requestId !== previewRequestId) return
    previewSubject.value = data.renderedSubject
    previewHtml.value = data.html
  } catch {
    if (requestId !== previewRequestId) return
    previewSubject.value = ''
    previewHtml.value = ''
  } finally {
    if (requestId === previewRequestId) previewLoading.value = false
  }
}

function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    void fetchPreview()
  }, 220)
}

async function loadData() {
  const templateData = await get<Record<string, TemplateData>>('/api/email-templates')
  if (templateData) {
    for (const key of TEMPLATE_KEYS) {
      const data = {
        subject: templateData[key]?.subject ?? '',
        body: templateData[key]?.body ?? '',
      }
      templates.value[key] = { ...data }
      orig.value[key] = { ...data }
    }
  }

  initialLoading.value = false
  schedulePreview()
}

async function save(): Promise<boolean> {
  saveLoading.value = true
  const res = await post<{ message: string }>('/api/email-templates', {
    type: activeTemplate.value,
    subject: currentTemplate.value.subject,
    body: currentTemplate.value.body,
  })
  saveLoading.value = false
  if (res) {
    orig.value[activeTemplate.value] = { ...currentTemplate.value }
    toast(t('emailTemplates.saved'), 'success')
    return true
  }
  return false
}

async function saveAllDirty(): Promise<boolean> {
  if (!isDirty.value) return true
  saveLoading.value = true
  let allOk = true
  const failed: string[] = []
  for (const key of dirtyKeys.value.slice()) {
    const cur = templates.value[key]
    const res = await post<{ message: string }>('/api/email-templates', {
      type: key,
      subject: cur.subject,
      body: cur.body,
    })
    if (res) {
      orig.value[key] = { ...cur }
    } else {
      allOk = false
      failed.push(key)
    }
  }
  saveLoading.value = false
  if (allOk) {
    toast(t('emailTemplates.savedAll', { n: TEMPLATE_KEYS.length }), 'success')
  } else {
    toast(t('emailTemplates.saveSomeFailed', { n: failed.length }), 'error')
  }
  return allOk
}

function discardAll() {
  for (const key of TEMPLATE_KEYS) {
    templates.value[key] = { ...orig.value[key] }
  }
}

// Page-wide dirty-form orchestration. The leave-guard reuses the email
// templates' specialised "{n} unsaved" message via a custom prompt.
const dirtyForm = provideDirtyForm({
  prompt: async () => {
    const result = await confirm({
      title: t('emailTemplates.unsavedTitle'),
      message: t('emailTemplates.unsavedMessage', { n: dirtyKeys.value.length }),
      confirmText: t('emailTemplates.unsavedSave'),
      cancelText: t('emailTemplates.unsavedDiscard'),
      altText: t('emailTemplates.unsavedStay'),
    })
    if (result === 'alt') return 'stay'
    return result === true ? 'save' : 'discard'
  },
})
dirtyForm.attachLeaveGuard()
useDirtyFormSection({
  name: 'email-templates',
  isDirty,
  save: saveAllDirty,
  discard: discardAll,
}, dirtyForm)

function tplLabel(key: TemplateKey): string {
  return t(`emailTemplates.${key}.title`)
}

watch(
  () => [
    activeTemplate.value,
    currentTemplate.value.subject,
    currentTemplate.value.body,
    previewTheme.value,
  ],
  () => {
    if (!initialLoading.value) schedulePreview()
  },
)

function onSystemThemeChange() {
  schedulePreview()
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    prefersDarkQuery.value = window.matchMedia('(prefers-color-scheme: dark)')
    prefersDarkQuery.value.addEventListener('change', onSystemThemeChange)
  }
  void loadData()
})

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer)
  prefersDarkQuery.value?.removeEventListener('change', onSystemThemeChange)
})
</script>

<template>
  <PageHeader :title="t('emailTemplates.title')" icon="mail" />

  <div class="page-body">
    <div v-if="initialLoading" class="center-loading">
      <Spinner size="lg" />
    </div>

    <template v-else>
      <div class="tpl-workspace">
        <section class="tpl-column">
          <SectionHeader icon="edit" flush>
            {{ t('emailTemplates.editor') }}
          </SectionHeader>

          <ChipSelect v-model="activeTemplate" :options="chipOptions" />

          <div class="tpl-vars">
            <span class="tpl-vars-label">{{ t('emailTemplates.placeholders') }}</span>
            <div class="tpl-vars-list">
              <code
                v-for="key in currentVariables"
                :key="key"
                class="tpl-var-chip"
                :title="t(`emailTemplates.var.${key}`)"
                v-text="tokenLabel(key)"
              />
            </div>
          </div>

          <FormField :label="t('emailTemplates.subject')">
            <BaseInput v-model="currentTemplate.subject" />
          </FormField>

          <FormField :label="t('emailTemplates.body')">
            <BaseTextarea v-model="currentTemplate.body" :rows="16" mono />
          </FormField>
        </section>

        <section class="tpl-column tpl-column--preview">
          <SectionHeader icon="description" flush>
            {{ t('emailTemplates.preview') }}
          </SectionHeader>

          <div class="tpl-preview-subject">
            <span class="tpl-preview-label">{{ t('emailTemplates.previewSubject') }}</span>
            <span class="tpl-preview-value">{{ previewSubject || t('emailTemplates.previewEmpty') }}</span>
          </div>

          <div class="tpl-preview-frame-shell" :class="{ 'tpl-preview-frame-shell--loading': previewLoading && !previewHtml }">
            <div v-if="!previewHtml && previewLoading" class="tpl-preview-loading">
              <Spinner size="lg" />
            </div>
            <div v-else-if="!previewHtml" class="tpl-preview-empty">
              {{ t('emailTemplates.previewEmpty') }}
            </div>
            <iframe
              v-else
              class="tpl-preview-frame"
              :srcdoc="sanitizedPreviewHtml"
              sandbox="allow-scripts"
              title="email-preview"
            />
          </div>
        </section>
      </div>
    </template>
  </div>

  <DirtyBar
    :dirty="dirtyForm.isDirty.value"
    :saving="saveLoading"
    confirm-before-unload
  >
    <template #hint>
      <span class="db__text dirty-bar__text">
        <MsIcon name="edit" />
        {{ t('emailTemplates.unsavedHint', { n: dirtyKeys.length }) }}
      </span>
    </template>
    <template #extra>
      <div class="dirty-bar__chips">
        <Badge
          v-for="k in dirtyKeys"
          :key="k"
          color="#f59e0b"
          class="dirty-bar__chip"
          @click="activeTemplate = k"
        >
          {{ tplLabel(k) }}
        </Badge>
      </div>
    </template>
    <template #actions>
      <div class="dirty-bar__actions">
        <BaseButton size="sm" :disabled="saveLoading" @click="discardAll">
          {{ t('emailTemplates.discardAll') }}
        </BaseButton>
        <BaseButton
          v-if="isTemplateDirty(activeTemplate)"
          size="sm"
          :loading="saveLoading"
          @click="save"
        >
          {{ t('emailTemplates.saveCurrent') }}
        </BaseButton>
        <BaseButton
          variant="primary"
          size="sm"
          :loading="saveLoading"
          @click="saveAllDirty"
        >
          {{ t('emailTemplates.saveAll', { n: dirtyKeys.length }) }}
        </BaseButton>
      </div>
    </template>
  </DirtyBar>
</template>

<style scoped>
.center-loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-8);
}

/* DirtyBar slot overrides for the chip cluster + custom actions. The base
   bar layout (positioning / shadow / transition) lives in DirtyBar.vue. */
.dirty-bar__text {
  white-space: nowrap;
  flex-shrink: 0;
}
.dirty-bar__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  min-width: 0;
}
.dirty-bar__chip { cursor: pointer; }
.dirty-bar__actions {
  display: flex;
  gap: var(--sp-2);
  flex-shrink: 0;
}

.tpl-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-6);
  align-items: start;
}

.tpl-column {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  min-width: 0;
}

.tpl-column--preview {
  position: sticky;
  top: calc(64px + var(--sp-4));
}

.tpl-vars {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.tpl-vars-label {
  color: var(--t2);
  font-size: var(--text-sm);
  line-height: 30px;
  white-space: nowrap;
}

.tpl-vars-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.tpl-var-chip {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 var(--sp-3);
  border-radius: var(--r-sm);
  border: 1px solid color-mix(in srgb, var(--ac) 22%, var(--bd));
  background: color-mix(in srgb, var(--acg) 64%, transparent);
  color: var(--ac2);
  font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.tpl-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--sp-1);
}

.tpl-preview-subject {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--bd);
}

.tpl-preview-label {
  color: var(--t2);
  font-size: 12px;
  white-space: nowrap;
}

.tpl-preview-value {
  color: var(--t1);
  font-size: var(--text-sm);
  font-weight: 600;
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tpl-preview-frame-shell {
  min-height: 760px;
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--bg3);
}

.tpl-preview-loading,
.tpl-preview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 760px;
  color: var(--t2);
  font-size: var(--text-sm);
}

.tpl-preview-frame {
  width: 100%;
  min-height: 760px;
  border: 0;
  background: #ffffff;
}

@media (max-width: 1080px) {
  .tpl-workspace {
    grid-template-columns: 1fr;
  }

  .tpl-column--preview {
    position: static;
  }
}

@media (max-width: 720px) {
  .tpl-vars {
    flex-direction: column;
    align-items: stretch;
  }

  .tpl-vars-label {
    line-height: 1.5;
  }

  .tpl-preview-frame-shell,
  .tpl-preview-loading,
  .tpl-preview-empty,
  .tpl-preview-frame {
    min-height: 620px;
  }
}
</style>
