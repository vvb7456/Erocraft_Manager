<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import { renderMarkdown } from '@/utils/markdown'
import {
  resolveAgreementBody,
  type FixedAgreementSlug,
} from '@/utils/agreements'

defineOptions({ name: 'AgreementEditModal' })

interface AgreementAdminOut {
  id: number
  slug: string
  current_version: number
  version_count: number
  current_title_zh: string
  current_title_en: string
}

interface AgreementVersionOut {
  id: number
  version: number
  title_zh: string
  title_en: string
  body_zh: string
  body_en: string
  published_at: string
  published_by: string
}

const props = defineProps<{
  modelValue: { slug: FixedAgreementSlug; lang: 'zh' | 'en' } | null
  slug: FixedAgreementSlug
  lang: 'zh' | 'en'
  agreement: AgreementAdminOut | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: { slug: FixedAgreementSlug; lang: 'zh' | 'en' } | null]
  saved: []
}>()

const { t } = useI18n({ useScope: 'global' })
const { get, raw } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

const bodyZh = ref('')
const bodyEn = ref('')
const submitLoading = ref(false)
const initLoading = ref(false)
const snapshot = ref('')

const show = computed({
  get: () => props.modelValue !== null,
  set: (v) => emit('update:modelValue', v ? { slug: props.slug, lang: props.lang } : null),
})

const docName = computed(() =>
  props.slug === 'tos'
    ? t('agreements.checkbox.open_tos')
    : t('agreements.checkbox.open_privacy'),
)

const editorTitle = computed(() =>
  t('settings.agreements.editor_title', { name: `${docName.value} · ${langLabel.value}` }),
)

const langLabel = computed(() =>
  props.lang === 'zh'
    ? t('settings.agreements.lang_zh')
    : t('settings.agreements.lang_en'),
)

const currentBody = computed(() =>
  props.lang === 'zh' ? bodyZh.value : bodyEn.value,
)

function setCurrentBody(v: string) {
  if (props.lang === 'zh') bodyZh.value = v
  else bodyEn.value = v
}

const previewHtml = computed(() => {
  const body = resolveAgreementBody(props.slug, currentBody.value, props.lang)
  return renderMarkdown(body)
})

const canSave = computed(() => !submitLoading.value && !initLoading.value)

function isDirty(): boolean {
  return JSON.stringify({
    bodyZh: bodyZh.value,
    bodyEn: bodyEn.value,
  }) !== snapshot.value
}

async function loadInitial() {
  initLoading.value = true
  let bzh = resolveAgreementBody(props.slug, '', 'zh')
  let ben = resolveAgreementBody(props.slug, '', 'en')

  const a = props.agreement
  if (a && a.current_version > 0) {
    const data = await get<AgreementVersionOut[]>(`/api/admin/agreements/${a.id}/versions`)
    if (data) {
      const cur = data.find(v => v.version === a.current_version)
      if (cur) {
        if (cur.body_zh && cur.body_zh.trim()) bzh = cur.body_zh
        if (cur.body_en && cur.body_en.trim()) ben = cur.body_en
      }
    }
  }
  bodyZh.value = bzh
  bodyEn.value = ben
  snapshot.value = JSON.stringify({
    bodyZh: bzh,
    bodyEn: ben,
  })
  initLoading.value = false
}

async function onCloseAttempt() {
  if (!isDirty()) { show.value = false; return }
  const ok = await confirm({
    title: t('settings.unsavedTitle'),
    message: t('settings.unsavedMessage'),
    confirmText: t('settings.unsavedDiscard'),
    cancelText: t('settings.unsavedStay'),
    variant: 'danger',
  })
  if (ok) show.value = false
}

async function submit() {
  if (!canSave.value) return
  const a = props.agreement
  if (!a) {
    toast('agreement not found', 'error')
    return
  }
  submitLoading.value = true
  const bump = a.current_version === 0
  const payload = {
    title_zh: docName.value,
    title_en: docName.value,
    body_zh: bodyZh.value,
    body_en: bodyEn.value,
    bump,
  }
  const res = await raw(`/api/admin/agreements/${a.id}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    silent: true,
  })
  submitLoading.value = false
  if (res == null) return
  if (res.status === 201) {
    toast(t('settings.agreements.save_ok'), 'success')
    emit('saved')
    show.value = false
  } else {
    let msg = `HTTP ${res.status}`
    try {
      const body = await res.json()
      msg = body.error || body.message || msg
    } catch { /* ignore */ }
    toast(msg, 'error')
  }
}

watch(() => props.modelValue, (open) => {
  if (open) loadInitial()
}, { immediate: true })
</script>

<template>
  <BaseModal
    v-model="show"
    :title="editorTitle"
    icon="edit"
    size="xxl"
    :close-on-overlay="false"
    scroll="content"
  >
    <template #footer>
      <BaseButton @click="onCloseAttempt">{{ t('common.btn.cancel') }}</BaseButton>
      <BaseButton variant="primary" :loading="submitLoading" :disabled="!canSave" @click="submit">
        <MsIcon name="check" size="sm" />
        {{ t('settings.agreements.save') }}
      </BaseButton>
    </template>

    <div v-if="initLoading" class="modal-loading">{{ t('common.loading') }}</div>

    <div v-else class="edit-split">
      <div class="pane-box">
        <div class="pane-header">
          <MsIcon name="edit" size="sm" />
          {{ t('settings.agreements.field_body') }}
        </div>
        <div class="pane-content pane-content--edit">
          <BaseTextarea
            :model-value="currentBody"
            @update:model-value="setCurrentBody"
            :rows="24"
            mono
            class="edit-textarea"
          />
        </div>
      </div>

      <div class="pane-box">
        <div class="pane-header">
          <MsIcon name="visibility" size="sm" />
          {{ t('settings.agreements.preview') }}
        </div>
        <div class="pane-content pane-content--preview">
          <!-- eslint-disable-next-line vue/no-v-html -- markdown body is sanitized via DOMPurify in renderMarkdown -->
          <div class="agreement-markdown" v-html="previewHtml" />
        </div>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.modal-loading {
  padding: var(--sp-6) 0;
  text-align: center;
  color: var(--t3);
  font-size: var(--text-sm);
}

.edit-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-3);
  align-items: stretch;
}

.pane-box {
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg);
  overflow: hidden;
}

.pane-header {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: var(--sp-2) var(--sp-3);
  font-size: .8rem;
  font-weight: 500;
  color: var(--t3);
  border-bottom: 1px solid var(--bd);
  background: var(--bg2);
  flex-shrink: 0;
}

.pane-content {
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  max-height: 640px;
}

.pane-content--edit {
  padding: var(--sp-2) var(--sp-3);
  display: flex;
}

.pane-content--preview {
  padding: var(--sp-3);
}

.edit-textarea {
  flex: 1;
}

.agreement-markdown {
  color: var(--t2);
  font-size: .86rem;
  line-height: 1.7;
  overflow-x: auto;
}

.agreement-markdown :deep(h1),
.agreement-markdown :deep(h2),
.agreement-markdown :deep(h3),
.agreement-markdown :deep(h4) {
  color: var(--t1);
  font-weight: 600;
  margin: 1.4em 0 .6em;
  line-height: 1.3;
}
.agreement-markdown :deep(h1) { font-size: 1.2rem; }
.agreement-markdown :deep(h2) { font-size: 1.05rem; }
.agreement-markdown :deep(h3) { font-size: .95rem; }
.agreement-markdown :deep(h4) { font-size: .88rem; }

.agreement-markdown :deep(p) { margin: .6em 0; }

.agreement-markdown :deep(ul),
.agreement-markdown :deep(ol) {
  margin: .6em 0;
  padding-left: 1.5em;
}
.agreement-markdown :deep(li) { margin: .3em 0; }

.agreement-markdown :deep(strong) {
  color: var(--t1);
  font-weight: 600;
}

.agreement-markdown :deep(a) {
  color: var(--ac);
  text-decoration: none;
}
.agreement-markdown :deep(a:hover) { text-decoration: underline; }

.agreement-markdown :deep(blockquote) {
  border-left: 3px solid var(--bd);
  margin: .8em 0;
  padding: .2em 0 .2em 1em;
  color: var(--t3);
}

.agreement-markdown :deep(hr) {
  border: none;
  border-top: 1px solid var(--bd);
  margin: 1.2em 0;
}

.agreement-markdown :deep(code) {
  background: var(--bg2);
  border-radius: var(--rs);
  padding: 1px 5px;
  font-size: .85em;
}

.agreement-markdown :deep(pre) {
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--rs);
  padding: var(--sp-2) var(--sp-3);
  overflow-x: auto;
  font-size: .82em;
}

.agreement-markdown :deep(pre code) {
  background: none;
  padding: 0;
}

@media (max-width: 768px) {
  .edit-split {
    grid-template-columns: 1fr;
  }
  .pane-content {
    max-height: 320px;
  }
}
</style>
