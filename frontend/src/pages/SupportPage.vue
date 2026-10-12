<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useSupportEvents } from '@/composables/useSupportEvents'
import SupportChat from '@/components/support/SupportChat.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'

defineOptions({ name: 'SupportPage' })

const route = useRoute()
const admin = computed(() => !!route.meta.admin)
const { t } = useI18n()
const { get, post } = useApiFetch()
interface Conversation { id: number; username: string; unread: number; preview: string; has_image: boolean; updated_at: string }
const conversations = ref<Conversation[]>([])
const selected = ref<number | null>(null)
const hasMore = ref(false)
const failed = ref(false)
const selectedName = computed(() => conversations.value.find(c => c.id === selected.value)?.username || '')
const loading = ref(false)
let pendingRefresh = false
let alive = true
async function load(more = false) {
  if (!alive) return
  if (loading.value) { pendingRefresh = true; return }
  loading.value = true
  try {
    if (admin.value) {
      const res = await get<{ items: Conversation[]; has_more: boolean }>(`/api/support/conversations?offset=${more ? conversations.value.length : 0}&limit=${more ? 50 : Math.min(500, Math.max(50, conversations.value.length))}`, { silent: true })
      failed.value = !res
      if (res) {
        conversations.value = more ? [...conversations.value, ...res.items.filter(c => !conversations.value.some(old => old.id === c.id))] : res.items
        hasMore.value = res.has_more
      }
    } else {
      const res = await post<{ id: number }>('/api/support/conversation')
      failed.value = !res
      if (res) selected.value = res.id
    }
  } finally {
    loading.value = false
    if (pendingRefresh) { pendingRefresh = false; void load() }
  }
}
if (admin.value) useSupportEvents(() => void load())
onMounted(() => void load())
onBeforeUnmount(() => { alive = false })
</script>

<template>
  <PageHeader icon="support_agent" :title="admin ? t('support.inbox') : t('support.title')" />

  <div class="page-body support-body">
    <BaseCard variant="bg2" :padding="false" class="support-workspace" :class="{ 'with-list': admin, 'has-selection': !!selected }">
      <aside v-if="admin" class="conversation-list" :aria-label="t('support.back')">
        <LoadingCenter v-if="loading && !conversations.length" size="sm" />
        <EmptyState v-else-if="!conversations.length" icon="support_agent" :message="t('support.noConversations')" />
        <template v-else>
          <button v-for="c in conversations" :key="c.id" type="button" class="conversation" :class="{ active: c.id === selected }" :aria-pressed="c.id === selected" @click="selected = c.id">
            <span class="conversation-title">
              <span class="conversation-name">{{ c.username }}</span>
              <Badge v-if="c.unread" color="var(--ac)">{{ c.unread }}</Badge>
            </span>
            <span class="conversation-preview">{{ c.preview || (c.has_image ? t('support.image') : '') }}</span>
          </button>
          <div v-if="hasMore" class="list-more"><BaseButton size="sm" variant="ghost" :disabled="loading" @click="load(true)">{{ t('support.more') }}</BaseButton></div>
        </template>
        <div v-if="failed" class="list-more"><BaseButton size="sm" variant="ghost" @click="load()">{{ t('support.retry') }}</BaseButton></div>
      </aside>
      <section class="chat-pane">
        <div v-if="admin && selected" class="conversation-heading">
          <BaseButton size="sm" variant="ghost" class="back-to-list" @click="selected = null">{{ t('support.back') }}</BaseButton>
          <span class="conversation-name">{{ selectedName }}</span>
        </div>
        <SupportChat v-if="selected" :key="selected" :conversation-id="selected" :admin="admin" />
        <LoadingCenter v-else-if="!admin && loading" />
        <EmptyState v-else class="chat-empty" icon="support_agent" :title="t(admin ? 'support.selectConversation' : 'support.title')">
          <BaseButton v-if="failed && !admin" size="sm" @click="load()">{{ t('support.retry') }}</BaseButton>
        </EmptyState>
      </section>
    </BaseCard>
  </div>
</template>

<style scoped>
.support-body {
  height: calc(100dvh - var(--app-header-h, 64px));
  min-height: 440px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.support-workspace { flex: 1; min-height: 0; display: grid; overflow: hidden; }
.with-list { grid-template-columns: 280px minmax(0, 1fr); }
.conversation-list { min-height: 0; overflow-y: auto; border-right: 1px solid var(--bd); }
.conversation {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-4);
  border: 0;
  border-bottom: 1px solid var(--bd);
  background: transparent;
  color: var(--t1);
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: background .15s, color .15s;
}
.conversation:hover { background: var(--bg3); }
.conversation.active { background: var(--acg); box-shadow: inset 3px 0 var(--ac); }
.conversation:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
.conversation-title { display: flex; align-items: center; gap: var(--sp-2); width: 100%; }
.conversation-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-base); font-weight: 500; }
.conversation-preview { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--t3); font-size: var(--text-sm); }
.list-more { display: flex; justify-content: center; padding: var(--sp-3); }
.chat-pane { display: flex; flex-direction: column; gap: var(--sp-3); min-width: 0; min-height: 0; padding: var(--sp-4); }
.chat-empty { flex: 1; }
.conversation-heading { display: flex; align-items: center; gap: var(--sp-3); padding-bottom: var(--sp-3); border-bottom: 1px solid var(--bd); }
.back-to-list { display: none; }
@media (max-width: 768px) {
  .support-body { min-height: 360px; }
  .with-list { grid-template-columns: minmax(0, 1fr); }
  .with-list.has-selection .conversation-list { display: none; }
  .with-list:not(.has-selection) .chat-pane { display: none; }
  .conversation-list { border-right: 0; }
  .chat-pane { padding: var(--sp-3); }
  .back-to-list { display: inline-flex; }
}
</style>
