<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useClipboard } from '@/composables/useClipboard'
import { useDirtyFormSection, useParentDirtyForm } from '@/composables/useDirtyForm'
import { useToast } from '@/composables/useToast'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import FormField from '@/components/form/FormField.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import { wecomTemplateKeys as KEYS, type WecomTemplateKey } from '@/types/wecomTemplates'

const props = defineProps<{ templateKey: WecomTemplateKey }>()
interface TemplateData { title: string; body: string; variables: string[] }
type Templates = Record<WecomTemplateKey, TemplateData>

const { t } = useI18n()
const { get, post } = useApiFetch()
const { copy } = useClipboard()
const { toast } = useToast()
const dirtyForm = useParentDirtyForm()
const all = ref<Templates | null>(null)
const savedAll = ref<Templates | null>(null)
const current = computed(() => all.value?.[props.templateKey])
const loading = ref(true)
const bodyInput = ref<InstanceType<typeof BaseTextarea> | null>(null)
const previewContent = ref('')
const previewError = ref('')
const previewLoading = ref(false)
let previewReqId = 0
let previewTimer: ReturnType<typeof setTimeout> | undefined

const isDirty = computed(() => JSON.stringify(all.value) !== JSON.stringify(savedAll.value))

function insertVar(key: string) {
  const ta = bodyInput.value?.element
  if (!ta || !current.value) return
  const start = ta.selectionStart
  current.value.body = current.value.body.slice(0, start) + `{{${key}}}` + current.value.body.slice(ta.selectionEnd)
  void nextTick(() => { ta.focus(); ta.selectionStart = ta.selectionEnd = start + key.length + 4 })
}

async function loadPreview(rid: number) {
  if (!current.value) return
  let content = ''
  let error = ''
  try {
    const res = await fetch('/api/admin/notifications/wecom-templates/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: props.templateKey, title: current.value.title, body: current.value.body }),
    })
    const data = await res.json()
    if (res.ok) content = data.content
    else error = typeof data.detail === 'string' ? data.detail : t('notifications.wecomTemplates.previewFailed')
  } catch {
    error = t('notifications.wecomTemplates.previewFailed')
  }
  if (rid !== previewReqId) return
  previewContent.value = content
  previewError.value = error
  previewLoading.value = false
}

function schedulePreview() {
  clearTimeout(previewTimer)
  const rid = ++previewReqId
  previewLoading.value = true
  previewTimer = setTimeout(() => void loadPreview(rid), 300)
}

async function save(): Promise<boolean> {
  if (!all.value || !savedAll.value) return false
  for (const key of KEYS) {
    const submitted = { ...all.value[key] }
    if (JSON.stringify(submitted) === JSON.stringify(savedAll.value[key])) continue
    if (!await post('/api/admin/notifications/wecom-templates', { type: key, title: submitted.title, body: submitted.body })) return false
    savedAll.value[key] = submitted
  }
  toast(t('notifications.wecomTemplates.saved'), 'success')
  return !isDirty.value
}

function discard() {
  if (!all.value || !savedAll.value) return
  for (const key of KEYS) all.value[key] = { ...savedAll.value[key] }
}

useDirtyFormSection({ name: 'wecom-templates', isDirty, save, discard }, dirtyForm)

async function load() {
  loading.value = true
  const data = await get<Templates>('/api/admin/notifications/wecom-templates')
  if (data) {
    all.value = data
    savedAll.value = structuredClone(data)
    schedulePreview()
  }
  loading.value = false
}

watch([() => props.templateKey, () => current.value?.title, () => current.value?.body], () => {
  if (all.value) schedulePreview()
})
onMounted(load)
onBeforeUnmount(() => { previewReqId++; clearTimeout(previewTimer) })
</script>

<template>
  <LoadingCenter v-if="loading" />
  <BaseButton v-else-if="!current" @click="load">{{ t('notifications.reload') }}</BaseButton>
  <div v-else>
    <h3 class="template-title">{{ t(`notifications.wecomTemplates.types.${templateKey}`) }}</h3>
    <div class="tpl-workspace" :inert="dirtyForm.saving.value">
      <BaseCard>
        <div class="tpl-vars">
          <span class="tpl-vars-label">{{ t('emailTemplates.placeholders') }}</span>
          <button v-for="variable in current.variables" :key="variable" class="tpl-var-chip" type="button"
            :title="t(`notifications.wecomTemplates.variables.${variable}`)"
            @click="copy(`{{${variable}}}`, { successMessage: t('emailTemplates.varCopied', { key: variable }) })"
            @dblclick="insertVar(variable)" v-text="'{{' + variable + '}}'" />
        </div>
        <FormField :label="t('notifications.wecomTemplates.heading')">
          <BaseInput v-model="current.title" :maxlength="200" />
        </FormField>
        <FormField :label="t('notifications.wecomTemplates.body')">
          <BaseTextarea ref="bodyInput" v-model="current.body" :rows="18" :maxlength="8000" mono />
        </FormField>
      </BaseCard>
      <BaseCard class="tpl-preview">
        <template #header>{{ t('emailTemplates.preview') }}</template>
        <div class="tpl-preview-shell">
          <LoadingCenter v-if="previewLoading" />
          <p v-else-if="previewError" class="tpl-error">{{ previewError }}</p>
          <div v-else class="tpl-message">{{ previewContent }}</div>
        </div>
      </BaseCard>
    </div>
  </div>
</template>

<style scoped>
.template-title { margin: 0; font-size: var(--text-md); font-weight: 600; }
.tpl-workspace { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--sp-6); align-items: start; margin-top: var(--sp-4); }
.tpl-vars { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); margin-bottom: var(--sp-3); padding-bottom: var(--sp-3); border-bottom: 1px solid var(--bd); }
.tpl-vars-label { color: var(--t3); font-size: var(--text-sm); }
.tpl-var-chip { padding: 2px 8px; border: 1px solid var(--bd); border-radius: var(--r-xs); background: var(--bg-in); color: var(--t2); font-family: var(--font-mono); font-size: var(--text-xs); cursor: pointer; }
.tpl-var-chip:hover { border-color: var(--ac); color: var(--ac); }
.tpl-preview { position: sticky; top: 0; min-width: 0; }
.tpl-preview-shell { min-height: 300px; padding: var(--sp-4); border: 1px solid var(--bd); border-radius: var(--r-sm); background: var(--bg3); }
.tpl-message { white-space: pre-wrap; overflow-wrap: anywhere; color: var(--t1); line-height: 1.8; }
.tpl-error { color: var(--red); overflow-wrap: anywhere; }
@media (max-width: 1100px) {
  .tpl-workspace { grid-template-columns: 1fr; }
  .tpl-preview { position: static; }
}
</style>
