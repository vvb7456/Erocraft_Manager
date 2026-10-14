<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useSupportEvents } from '@/composables/useSupportEvents'
import { useSupportStore } from '@/stores/support'
import SupportChat from '@/components/support/SupportChat.vue'
import SupportConnectionBadge from '@/components/support/SupportConnectionBadge.vue'
import SupportContactMenu from '@/components/support/SupportContactMenu.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import FilterInput from '@/components/ui/FilterInput.vue'
import TabSwitcher from '@/components/ui/TabSwitcher.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'SupportPage' })

const route = useRoute()
const support = useSupportStore()
const admin = computed(() => !!route.meta.admin)
const { t, locale } = useI18n()
const { get, post } = useApiFetch()
type ConversationCategory = 'pre_sales' | 'after_sales'
type ConversationFilter = 'all' | 'unread' | ConversationCategory
interface Conversation { id: number; username: string; user_id: number; unread: number; preview: string; has_image: boolean; updated_at: string; category: ConversationCategory }
const conversations = ref<Conversation[]>([])
const selected = ref<number | null>(null)
const selectedContact = ref<Conversation | null>(null)
const search = ref('')
const filter = ref<ConversationFilter>('all')
const filterOptions = computed(() => [
  { key: 'all', label: t('support.all') },
  { key: 'unread', label: t('support.unread'), badge: support.unread > 99 ? '99+' : support.unread || undefined },
  { key: 'pre_sales', label: t('support.preSales') },
  { key: 'after_sales', label: t('support.afterSales') },
])
const hasFilters = computed(() => !!search.value.trim() || filter.value !== 'all')
const hasMore = ref(false)
const failed = ref(false)
const loading = ref(false)
const viewportHeight = ref(window.visualViewport?.height || window.innerHeight)
const chatHeading = ref<HTMLElement | null>(null)
const searchInput = ref<InstanceType<typeof FilterInput> | null>(null)
const filterKey = computed(() => JSON.stringify([search.value.trim(), filter.value]))
let pendingRefresh = false
let alive = true
let linkedRequest = 0
let searchTimer: ReturnType<typeof setTimeout> | null = null
function updateViewport() { viewportHeight.value = window.visualViewport?.height || window.innerHeight }
async function select(item: Conversation) {
  linkedRequest++
  selected.value = item.id
  selectedContact.value = item
  if (window.matchMedia('(max-width: 900px)').matches) {
    await nextTick()
    if (alive && selected.value === item.id) chatHeading.value?.focus({ preventScroll: true })
  }
}
async function backToList() {
  linkedRequest++
  const id = selected.value
  selected.value = null
  await nextTick()
  if (alive) (document.getElementById(`support-conversation-${id}`) || searchInput.value)?.focus({ preventScroll: true })
}
function clearFilters() { search.value = ''; filter.value = 'all' }
function time(value: string) {
  const date = new Date(value)
  return date.toDateString() === new Date().toDateString()
    ? date.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString(locale.value, { month: 'numeric', day: 'numeric' })
}
async function load(more = false) {
  if (!alive) return
  if (loading.value) { pendingRefresh = true; return }
  loading.value = true
  const currentFilter = filterKey.value
  const isAdmin = admin.value
  try {
    if (isAdmin) {
      const params = new URLSearchParams({ offset: String(more ? conversations.value.length : 0), limit: String(more ? 50 : Math.min(500, Math.max(50, conversations.value.length))), q: search.value.trim(), unread_only: String(filter.value === 'unread'), category: filter.value === 'pre_sales' || filter.value === 'after_sales' ? filter.value : 'all' })
      const res = await get<{ items: Conversation[]; has_more: boolean }>(`/api/support/conversations?${params}`, { silent: true })
      if (!alive || isAdmin !== admin.value || currentFilter !== filterKey.value) return
      failed.value = !res
      if (res) {
        conversations.value = more ? [...conversations.value, ...res.items.filter(c => !conversations.value.some(old => old.id === c.id))] : res.items
        hasMore.value = res.has_more
        const current = res.items.find(c => c.id === selected.value)
        if (current) selectedContact.value = current
      }
    } else {
      const res = await post<{ id: number }>('/api/support/conversation')
      if (!alive || isAdmin !== admin.value) return
      failed.value = !res
      if (res) selected.value = res.id
    }
  } finally {
    loading.value = false
    if (pendingRefresh) { pendingRefresh = false; void load() }
  }
}
watch(filterKey, () => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!admin.value) return
  searchTimer = setTimeout(() => { conversations.value = []; hasMore.value = false; void load() }, 250)
})
watch(admin, () => {
  selected.value = null
  selectedContact.value = null
  conversations.value = []
  hasMore.value = false
  failed.value = false
  clearFilters()
  void load()
})
watch(() => [admin.value, route.query?.conversation], async () => {
  const request = ++linkedRequest
  const id = Number(route.query?.conversation)
  if (!admin.value || !Number.isSafeInteger(id) || id <= 0) return
  const result = await get<{ items: Conversation[] }>(`/api/support/conversations?conversation_id=${id}`)
  if (alive && request === linkedRequest && admin.value && result?.items[0]) await select(result.items[0])
}, { immediate: true })
useSupportEvents(() => { if (admin.value && document.visibilityState === 'visible') void load() })
onMounted(() => {
  void load()
  window.addEventListener('resize', updateViewport)
  window.visualViewport?.addEventListener('resize', updateViewport)
})
onBeforeUnmount(() => {
  alive = false
  if (searchTimer) clearTimeout(searchTimer)
  window.removeEventListener('resize', updateViewport)
  window.visualViewport?.removeEventListener('resize', updateViewport)
})
</script>

<template>
  <PageHeader icon="support_agent" :title="admin ? t('support.inbox') : t('support.title')" />
  <div class="page-body support-workspace" :class="{ 'with-list': admin, 'has-selection': !!selected, compact: viewportHeight < 500 }" :style="{ '--support-height': `${viewportHeight}px` }">
    <aside v-if="admin" class="conversation-list" :aria-label="t('support.back')">
      <FilterInput ref="searchInput" v-model="search" class="list-search" maxlength="100" :placeholder="t('support.search')" />
      <TabSwitcher class="list-filters" :tabs="filterOptions" :model-value="filter" @update:model-value="filter = $event as ConversationFilter" />
      <p class="list-caption">{{ t('support.recentMessages') }}</p>
      <div class="conversation-scroll" :aria-busy="loading">
        <LoadingCenter v-if="loading && !conversations.length" size="sm" />
        <div v-else-if="!conversations.length && !failed" class="list-empty">
          <MsIcon :name="hasFilters ? 'search' : 'forum'" size="lg" />
          <p>{{ hasFilters ? t('support.noResults') : t('support.noConversations') }}</p>
          <BaseButton v-if="hasFilters" size="sm" variant="ghost" @click="clearFilters">{{ t('support.clearFilters') }}</BaseButton>
        </div>
        <ul v-else-if="conversations.length" class="conversation-items">
          <li v-for="c in conversations" :key="c.id">
            <button :id="`support-conversation-${c.id}`" type="button" class="conversation" :class="{ active: c.id === selected, unread: c.unread > 0 }" :aria-pressed="c.id === selected" @click="select(c)">
              <span class="customer-avatar">{{ c.username.slice(0, 1).toLocaleUpperCase() }}</span>
              <span class="conversation-summary">
                <span class="conversation-top"><span class="conversation-name">{{ c.username }}</span><time :datetime="c.updated_at" :title="new Date(c.updated_at).toLocaleString(locale)">{{ time(c.updated_at) }}</time></span>
                <span class="conversation-bottom"><span class="conversation-preview"><MsIcon v-if="c.has_image" name="image" size="xs" /><span>{{ c.preview || (c.has_image ? t('support.image') : '') }}</span></span><span v-if="c.unread" class="unread-badge" :aria-label="t('support.unreadMessages', { count: c.unread })">{{ c.unread > 99 ? '99+' : c.unread }}</span></span>
              </span>
            </button>
          </li>
        </ul>
        <div v-if="hasMore" class="list-more"><BaseButton size="sm" variant="ghost" :loading="loading" @click="load(true)">{{ t('support.more') }}</BaseButton></div>
        <div v-if="failed" class="list-more"><BaseButton size="sm" variant="ghost" @click="load()">{{ t('support.retry') }}</BaseButton></div>
      </div>
    </aside>

    <section class="chat-pane" :class="{ 'is-empty': admin && !selected }" :aria-label="t('support.history')">
      <header v-if="selected || !admin" ref="chatHeading" class="conversation-heading" tabindex="-1">
        <BaseButton v-if="admin" variant="ghost" size="sm" square class="back-to-list" :aria-label="t('support.back')" @click="backToList"><MsIcon name="arrow_back" size="sm" /></BaseButton>
        <span v-if="admin" class="customer-avatar">{{ selectedContact?.username.slice(0, 1).toLocaleUpperCase() }}</span><span v-else class="support-avatar"><MsIcon name="support_agent" size="sm" /></span>
        <div class="heading-text"><SupportContactMenu v-if="admin && selectedContact" :key="selectedContact.id" :username="selectedContact.username" /><h3 v-else>{{ t('support.title') }}</h3><span v-if="admin && selectedContact" class="contact-id">{{ t('support.userId', { id: selectedContact.user_id }) }}</span></div>
        <SupportConnectionBadge />
      </header>
      <SupportChat v-if="selected" :key="`${admin}:${selected}`" :conversation-id="selected" :admin="admin" :customer-name="selectedContact?.username" layout="workspace" :compact="viewportHeight < 500" />
      <LoadingCenter v-else-if="!admin && loading" />
      <div v-else class="chat-empty">
        <SupportConnectionBadge v-if="admin" class="empty-status" />
        <span class="empty-avatar"><MsIcon name="forum" size="lg" /></span>
        <h3>{{ admin ? t('support.selectConversation') : t('support.title') }}</h3>
        <p v-if="admin">{{ t('support.selectConversationHint') }}</p>
        <BaseButton v-if="failed && !admin" size="sm" @click="load()">{{ t('support.retry') }}</BaseButton>
      </div>
    </section>
  </div>
</template>

<style scoped>
.support-workspace { height: calc(var(--support-height, 100dvh) - var(--app-header-h, 64px)); min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); gap: clamp(20px, 2vw, 32px); overflow: hidden; }
.with-list { grid-template-columns: clamp(264px, 23vw, 336px) minmax(0, 1fr); }
.conversation-list { min-height: 0; min-width: 0; display: flex; flex-direction: column; }
.list-filters { margin-top: var(--sp-3); }
.list-caption { margin: var(--sp-4) var(--sp-1) var(--sp-2); color: var(--t3); font-size: var(--text-xs); letter-spacing: .03em; }
.conversation-scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--bd) transparent; padding-bottom: 8px; }
.conversation-items { list-style: none; margin: 0; padding: 0; }
.conversation-items li + li { margin-top: 5px; }
.conversation { position: relative; display: flex; align-items: center; gap: 12px; width: 100%; padding: 14px 12px; border: 1px solid transparent; border-radius: 12px; background: transparent; color: var(--t1); text-align: left; font: inherit; cursor: pointer; transition: background .15s, border-color .15s; }
.conversation::before { content: ''; position: absolute; left: -1px; top: 15px; bottom: 15px; width: 3px; border-radius: 0 3px 3px 0; background: transparent; }
.conversation:hover { background: color-mix(in srgb, var(--bg3) 65%, transparent); }
.conversation.active { background: var(--bg2); border-color: var(--bd); box-shadow: 0 2px 8px #00000008; }
.conversation.active::before { background: var(--ac); }
.customer-avatar, .support-avatar { flex-shrink: 0; display: grid; place-items: center; width: 38px; height: 38px; border-radius: 13px; background: var(--bg3); color: var(--t2); font-weight: 600; font-size: 14px; }
.conversation.unread .customer-avatar, .conversation.active .customer-avatar, .support-avatar { background: color-mix(in srgb, var(--ac) 11%, var(--bg2)); color: var(--ac); }
.conversation-summary { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 7px; }
.conversation-top, .conversation-bottom { display: flex; align-items: center; gap: 8px; min-height: 16px; }
.conversation-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-sm); font-weight: 500; }
.unread .conversation-name { font-weight: 650; }
.conversation-top time { color: var(--t3); font-size: var(--text-xs); white-space: nowrap; font-variant-numeric: tabular-nums; }
.conversation-preview { flex: 1; min-width: 0; display: flex; align-items: center; gap: 4px; color: var(--t3); font-size: var(--text-xs); }
.conversation-preview > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unread .conversation-preview { color: var(--t2); }
.unread-badge { flex-shrink: 0; min-width: 18px; height: 18px; padding: 0 5px; display: grid; place-items: center; border-radius: var(--r-sm); background: var(--ac-solid); color: var(--t-inv); font-size: var(--text-xs); font-weight: 600; }
.list-empty { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 48px 12px; color: var(--t3); text-align: center; }
.list-empty p { margin: 0; color: var(--t2); font-size: var(--text-sm); }
.list-more { display: flex; justify-content: center; padding: 12px; }
.chat-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; border: 1px solid var(--bd); border-radius: 18px; background: var(--bg2); overflow: hidden; }
.chat-pane.is-empty { border-style: dashed; background: color-mix(in srgb, var(--bg2) 45%, transparent); }
.conversation-heading { flex-shrink: 0; display: flex; align-items: center; gap: 10px; padding: 10px 20px; border-bottom: 1px solid var(--bd); outline: none; }
.conversation-heading .customer-avatar, .conversation-heading .support-avatar { width: 32px; height: 32px; border-radius: 11px; }
.heading-text { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 10px; }
.heading-text h3 { min-width: 0; margin: 0; color: var(--t1); font-size: var(--text-base); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.contact-id { flex-shrink: 0; color: var(--t3); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.chat-empty { position: relative; flex: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 14px; padding: 32px; text-align: center; }
.empty-status { position: absolute; top: 16px; right: 16px; }
.empty-avatar { display: grid; place-items: center; width: 64px; height: 64px; margin-bottom: 6px; border-radius: 22px; background: color-mix(in srgb, var(--ac) 8%, var(--bg2)); color: var(--ac); }
.chat-empty h3 { margin: 0; color: var(--t1); font-size: var(--text-base); font-weight: 550; }
.chat-empty p { max-width: 30ch; margin: 0; color: var(--t3); font-size: var(--text-sm); line-height: 1.7; }
.back-to-list { display: none; }
.conversation:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
@media (max-width: 1100px) and (min-width: 901px) { .support-workspace { padding-inline: 20px; gap: 20px; } .with-list { grid-template-columns: 260px minmax(0, 1fr); } .contact-id { display: none; } }
@media (max-width: 900px) {
  .support-workspace { padding: 12px 12px max(12px, env(safe-area-inset-bottom)); gap: 0; }
  .with-list { grid-template-columns: minmax(0, 1fr); }
  .with-list.has-selection .conversation-list { display: none; }
  .with-list:not(.has-selection) .chat-pane { display: none; }
  .conversation { padding-block: 16px; }
  .chat-pane { border-radius: 14px; }
  .conversation-heading { gap: 8px; padding: 8px 10px; }
  .contact-id { display: none; }
  .back-to-list { display: inline-flex; }
  .list-search { --filter-input-font: 16px; }
}
@media (pointer: coarse) { .back-to-list { width: 40px; height: 40px; } }
@media (prefers-reduced-motion: reduce) { .conversation { transition: none; } }
</style>
