<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import Spinner from '@/components/ui/Spinner.vue'
import FormField from '@/components/form/FormField.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import ChipSelect, { type ChipOption } from '@/components/ui/ChipSelect.vue'
import { useTheme } from '@/composables/useTheme'

defineOptions({ name: 'EmailTemplatesPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()
const theme = useTheme()

type TemplateKey =
  | 'bulk'
  | 'reminder'
  | 'preDelete'
  | 'createUser'
  | 'passwordReset'
  | 'emailChange'

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
]

const TEMPLATE_VARIABLES: Record<TemplateKey, string[]> = {
  bulk: ['brand_name', 'username', 'email', 'server_name', 'server_id', 'expiration_date'],
  reminder: ['brand_name', 'username', 'server_count', 'expiration_date', 'server_list'],
  preDelete: ['brand_name', 'username', 'server_name', 'server_id', 'deletion_date'],
  createUser: ['brand_name', 'username', 'email', 'password', 'reset_url'],
  passwordReset: ['brand_name', 'username', 'email', 'reset_url'],
  emailChange: ['brand_name', 'username', 'new_email', 'confirm_url'],
}

const templates = ref<Record<TemplateKey, TemplateData>>({
  bulk: { subject: '', body: '' },
  reminder: { subject: '', body: '' },
  preDelete: { subject: '', body: '' },
  createUser: { subject: '', body: '' },
  passwordReset: { subject: '', body: '' },
  emailChange: { subject: '', body: '' },
})

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
      templates.value[key] = {
        subject: templateData[key]?.subject ?? '',
        body: templateData[key]?.body ?? '',
      }
    }
  }

  initialLoading.value = false
  schedulePreview()
}

async function save() {
  saveLoading.value = true
  const res = await post<{ message: string }>('/api/email-templates', {
    type: activeTemplate.value,
    subject: currentTemplate.value.subject,
    body: currentTemplate.value.body,
  })
  saveLoading.value = false
  if (res) toast(t('emailTemplates.saved'), 'success')
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

          <div class="tpl-actions">
            <BaseButton variant="primary" :loading="saveLoading" @click="save">
              {{ t('emailTemplates.save') }}
            </BaseButton>
          </div>
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
</template>

<style scoped>
.center-loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-8);
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
