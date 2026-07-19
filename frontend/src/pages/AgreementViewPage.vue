<script setup lang="ts">
import { onMounted, ref, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthShell from '@/components/auth/AuthShell.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import { renderMarkdown } from '@/utils/markdown'
import { resolveAgreementBody } from '@/utils/agreements'

defineOptions({ name: 'AgreementViewPage' })

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n({ useScope: 'global' })

const loading = ref(false)
const bodyHtml = ref('')

const slug = computed(() => String(route.params.slug || ''))

const localeKey = computed<'zh' | 'en'>(() =>
  locale.value.startsWith('zh') ? 'zh' : 'en',
)

const title = computed(() => {
  if (slug.value === 'privacy') return t('agreements.checkbox.open_privacy')
  return t('agreements.checkbox.open_tos')
})

async function load() {
  if (!slug.value) return
  loading.value = true
  try {
    const res = await fetch(
      `/api/public/agreements/${encodeURIComponent(slug.value)}?locale=${encodeURIComponent(locale.value)}`,
    )
    let body = ''
    if (res.ok) {
      const data = await res.json() as { body_md?: string }
      body = data.body_md || ''
    }
    bodyHtml.value = renderMarkdown(
      resolveAgreementBody(slug.value, body, localeKey.value),
    )
  } catch {
    bodyHtml.value = renderMarkdown(
      resolveAgreementBody(slug.value, '', localeKey.value),
    )
  } finally {
    loading.value = false
  }
}

watch(slug, load)
onMounted(load)

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push({ name: 'login' })
}
</script>

<template>
  <AuthShell icon="gavel" :subtitle="title">
    <div class="agreement-view">
      <div v-if="loading" class="agreement-view__loading">
        <Spinner size="md" />
        <span>{{ t('agreements.viewer.loading') }}</span>
      </div>
      <!-- eslint-disable-next-line vue/no-v-html -- markdown body is sanitized via DOMPurify in renderMarkdown -->
      <div v-else class="agreement-markdown" v-html="bodyHtml" />

      <div class="agreement-view__footer">
        <BaseButton variant="ghost" size="md" @click="goBack">
          <MsIcon name="arrow_back" size="sm" />
          {{ t('agreements.view_page.back') }}
        </BaseButton>
      </div>
    </div>
  </AuthShell>
</template>

<style scoped>
.agreement-view {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  max-height: 70vh;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior: contain;
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

.agreement-view__footer {
  display: flex;
  justify-content: flex-start;
  padding-top: var(--sp-2);
  border-top: 1px solid var(--bd);
}

.agreement-markdown {
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
</style>
