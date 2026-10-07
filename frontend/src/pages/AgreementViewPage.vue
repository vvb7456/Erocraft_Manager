<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AuthShell from '@/components/auth/AuthShell.vue'
import Spinner from '@/components/ui/Spinner.vue'
import { renderMarkdown } from '@/utils/markdown'
import { resolveAgreementBody } from '@/utils/agreements'

defineOptions({ name: 'AgreementViewPage' })

const props = defineProps<{ slug: string }>()
const { t, locale } = useI18n({ useScope: 'global' })

const loading = ref(false)
const bodyHtml = ref('')

const localeKey = computed<'zh' | 'en'>(() =>
  locale.value.startsWith('zh') ? 'zh' : 'en',
)

const title = computed(() => {
  if (props.slug === 'privacy') return t('agreements.checkbox.open_privacy')
  return t('agreements.checkbox.open_tos')
})

watch([() => props.slug, locale], async ([slug, language], _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  loading.value = true
  const bodyLocale = localeKey.value
  let body = ''
  try {
    const res = await fetch(
      `/api/public/agreements/${encodeURIComponent(slug)}?locale=${encodeURIComponent(language)}`,
      { signal: controller.signal },
    )
    if (res.ok) {
      const data = await res.json() as { body_md?: string }
      body = data.body_md || ''
    }
  } catch {
    // Match the registration viewer's placeholder fallback when unavailable.
  }
  if (controller.signal.aborted) return
  bodyHtml.value = renderMarkdown(resolveAgreementBody(slug, body, bodyLocale))
  loading.value = false
}, { immediate: true })

</script>

<template>
  <AuthShell class="agreement-page" icon="gavel" :subtitle="title">
    <div class="agreement-view">
      <div v-if="loading" class="agreement-view__loading">
        <Spinner size="md" />
        <span>{{ t('agreements.viewer.loading') }}</span>
      </div>
      <div v-else class="agreement-markdown" v-html="bodyHtml" />
    </div>
  </AuthShell>
</template>

<style scoped>
.agreement-page :deep(.auth-main) {
  padding-top: 64px;
  align-items: flex-start;
}

.agreement-page :deep(.auth-card) {
  max-width: 800px;
  min-width: 0;
}

.agreement-view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.agreement-view__loading {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-6) 0;
  justify-content: center;
  color: var(--t3);
  font-size: .85rem;
}

.agreement-markdown {
  overflow-wrap: anywhere;
  color: var(--t2);
  font-size: .85rem;
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

.agreement-markdown :deep(h1) { font-size: 1.2rem; }
.agreement-markdown :deep(h2) { font-size: 1.05rem; }
.agreement-markdown :deep(h3) { font-size: .95rem; }
.agreement-markdown :deep(h4) { font-size: .88rem; }

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

.agreement-markdown :deep(img) {
  max-width: 100%;
  height: auto;
}

.agreement-markdown :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
</style>
