<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '@/components/ui/BaseModal.vue'
import Spinner from '@/components/ui/Spinner.vue'
import { renderMarkdown } from '@/utils/markdown'
import { resolveAgreementBody } from '@/utils/agreements'

defineOptions({ name: 'AgreementViewer' })

const props = defineProps<{
  /** v-model: modelValue controls visibility */
  modelValue: boolean
  /** Agreement slug (e.g. 'tos' | 'privacy') */
  slug: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const { t, locale } = useI18n({ useScope: 'global' })

const loading = ref(false)
const bodyHtml = ref('')

const title = computed(() =>
  props.slug === 'privacy'
    ? t('agreements.checkbox.open_privacy')
    : t('agreements.checkbox.open_tos'),
)

const localeKey = computed<'zh' | 'en'>(() =>
  locale.value.startsWith('zh') ? 'zh' : 'en',
)

async function load() {
  if (!props.slug) return
  loading.value = true
  try {
    const res = await fetch(
      `/api/public/agreements/${encodeURIComponent(props.slug)}?locale=${encodeURIComponent(locale.value)}`,
    )
    let body = ''
    if (res.ok) {
      const data = await res.json() as { body_md?: string }
      body = data.body_md || ''
    }
    // Fall back to default placeholder when the backend has no
    // published version or returned an empty body. The agreement is
    // always considered present — never show an empty/error state.
    bodyHtml.value = renderMarkdown(
      resolveAgreementBody(props.slug, body, localeKey.value),
    )
  } catch {
    bodyHtml.value = renderMarkdown(
      resolveAgreementBody(props.slug, '', localeKey.value),
    )
  } finally {
    loading.value = false
  }
}

watch(() => [props.modelValue, props.slug] as const, ([open, slug]) => {
  if (open && slug) load()
})

onMounted(() => {
  if (props.modelValue && props.slug) load()
})
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    :title="title"
    size="xl"
    scroll="content"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="loading" class="viewer-loading">
      <Spinner size="md" />
      <span>{{ t('agreements.viewer.loading') }}</span>
    </div>
    <!-- eslint-disable-next-line vue/no-v-html -- markdown body is sanitized via DOMPurify in renderMarkdown -->
    <div v-else class="agreement-markdown" v-html="bodyHtml" />
    <template #footer>
      <button class="viewer-close" @click="emit('update:modelValue', false)">
        {{ t('agreements.viewer.close') }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.viewer-loading {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-6) 0;
  justify-content: center;
  color: var(--t3);
  font-size: .85rem;
}

.viewer-close {
  background: var(--bg3);
  border: 1px solid var(--bd);
  border-radius: var(--rs);
  color: var(--t1);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--text-sm);
  font-weight: 500;
  padding: 8px 18px;
  transition: background .15s ease, border-color .15s ease;
}

.viewer-close:hover {
  background: var(--bg4);
  border-color: var(--ac);
}

/* Markdown body styling — mirrors plan description rendering */
.agreement-markdown {
  color: var(--t2);
  font-size: .88rem;
  line-height: 1.7;
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

.agreement-markdown :deep(h1) { font-size: 1.25rem; }
.agreement-markdown :deep(h2) { font-size: 1.1rem; }
.agreement-markdown :deep(h3) { font-size: 1rem; }
.agreement-markdown :deep(h4) { font-size: .9rem; }

.agreement-markdown :deep(p) {
  margin: .6em 0;
}

.agreement-markdown :deep(ul),
.agreement-markdown :deep(ol) {
  margin: .6em 0;
  padding-left: 1.5em;
}

.agreement-markdown :deep(li) {
  margin: .3em 0;
}

.agreement-markdown :deep(strong) {
  color: var(--t1);
  font-weight: 600;
}

.agreement-markdown :deep(a) {
  color: var(--ac);
  text-decoration: none;
}

.agreement-markdown :deep(a:hover) {
  text-decoration: underline;
}

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
  background: var(--bg);
  border-radius: var(--rs);
  padding: 1px 5px;
  font-size: .85em;
}

.agreement-markdown :deep(pre) {
  background: var(--bg);
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
</style>
