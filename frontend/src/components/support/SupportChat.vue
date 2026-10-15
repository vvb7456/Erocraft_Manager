<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useSupportEvents } from '@/composables/useSupportEvents'
import { useSupportStore } from '@/stores/support'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import BaseModal from '@/components/ui/BaseModal.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import SplitButton from '@/components/ui/SplitButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import MessageText from './MessageText.vue'

defineOptions({ name: 'SupportChat' })

const props = withDefaults(defineProps<{ conversationId: number; admin?: boolean; active?: boolean; customerName?: string; layout?: 'widget' | 'workspace'; compact?: boolean }>(), { active: true, layout: 'widget' })
const emit = defineEmits<{ navigate: [] }>()
const { t, locale } = useI18n()
const { get, post, raw, handleError } = useApiFetch()
const { toast } = useToast()
const support = useSupportStore()
interface Message { id: number; content: string; is_admin: boolean; automated?: boolean; image_url: string | null; created_at: string }
interface Result { items: Message[]; has_more: boolean; user_read_id: number; admin_read_id: number }
const messages = ref<Message[]>([])
const draft = ref(support.draftFor(props.conversationId))
const content = computed({ get: () => draft.value.text, set: value => { draft.value.text = value; draft.value.clientId = ''; sendFailed.value = false } })
const imagePreview = ref('')
const imageOpen = ref(false)
const selectedImage = ref('')
const loading = ref(false)
const failed = ref(false)
const sendFailed = ref(false)
const loadingOlder = ref(false)
const hasOlder = ref(false)
const otherRead = ref(0)
const ownRead = ref(0)
const newMessages = ref(0)
const following = ref(true)
const viewport = ref<HTMLElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
const input = ref<InstanceType<typeof BaseTextarea> | null>(null)
let generation = 0
let busy = false
let rerun = false
let alive = true
let reading = false
let receiveCursor = 0
let observer: ResizeObserver | null = null
const canSend = computed(() => !!(content.value.trim() || draft.value.file) && !draft.value.sending)
const mine = (message: Message) => message.is_admin === !!props.admin
const sameGroup = (a?: Message, b?: Message) => !!a && !!b && a.is_admin === b.is_admin && !!a.automated === !!b.automated
  && new Date(a.created_at).toDateString() === new Date(b.created_at).toDateString()
  && Math.abs(Date.parse(a.created_at) - Date.parse(b.created_at)) < 120_000
function dayLabel(date: Date) {
  const today = new Date()
  if (date.toDateString() === today.toDateString()) return t('support.today')
  today.setDate(today.getDate() - 1)
  if (date.toDateString() === today.toDateString()) return t('support.yesterday')
  return date.toLocaleDateString(locale.value, { month: 'long', day: 'numeric', ...(date.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' as const } : {}) })
}
const timeline = computed(() => messages.value.map((message, index, all) => {
  const date = new Date(message.created_at)
  return {
    ...message,
    day: index === 0 || date.toDateString() !== new Date(all[index - 1]!.created_at).toDateString() ? dayLabel(date) : '',
    groupStart: !sameGroup(all[index - 1], message),
    groupEnd: !sameGroup(message, all[index + 1]),
    time: date.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' }),
    fullTime: date.toLocaleString(locale.value),
  }
}))

function atBottom() {
  const el = viewport.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 64
}
async function markRead() {
  if (!alive || !props.active || reading || document.visibilityState !== 'visible' || !document.hasFocus() || !atBottom()) return
  const id = Math.min(messages.value[messages.value.length - 1]?.id || 0, receiveCursor)
  if (id <= ownRead.value) return
  const version = generation
  reading = true
  try {
    if (await post(`/api/support/conversations/${props.conversationId}/read`, { message_id: id }) && version === generation) ownRead.value = id
  } catch (failure) { handleError(failure) } finally { reading = false }
}
function onScroll() {
  following.value = atBottom()
  if (following.value) { newMessages.value = 0; void markRead() }
}
async function scrollDown() {
  await nextTick()
  if (!alive || !props.active || document.visibilityState !== 'visible') return
  following.value = true
  newMessages.value = 0
  if (viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight
  await markRead()
}
function onImageLoad() {
  if (following.value) void scrollDown()
}
function merge(items: Message[]) {
  const all = new Map(messages.value.map(m => [m.id, m]))
  items.forEach(m => all.set(m.id, m))
  messages.value = [...all.values()].sort((a, b) => a.id - b.id)
}
async function refresh() {
  if (!alive || !props.active || document.visibilityState !== 'visible') return
  if (busy) { rerun = true; return }
  busy = true
  const version = generation
  loading.value = !messages.value.length
  try {
    let more = true
    while (more && version === generation) {
      const after = receiveCursor
      const data = await get<Result>(`/api/support/conversations/${props.conversationId}/messages?after=${after}`, { silent: true })
      if (version !== generation) return
      if (!data) { failed.value = true; return }
      failed.value = false
      if (after && !following.value) newMessages.value += data.items.filter(m => !mine(m) && !messages.value.some(old => old.id === m.id)).length
      merge(data.items)
      receiveCursor = data.items[data.items.length - 1]?.id || receiveCursor
      otherRead.value = props.admin ? data.user_read_id : data.admin_read_id
      ownRead.value = props.admin ? data.admin_read_id : data.user_read_id
      if (!after) hasOlder.value = data.has_more
      more = !!after && data.has_more && data.items.length > 0
    }
    if (following.value) await scrollDown()
  } catch {
    if (version === generation) failed.value = true
  } finally {
    busy = false
    loading.value = false
    if (rerun) { rerun = false; void refresh() }
  }
}
async function older() {
  if (loadingOlder.value) return
  loadingOlder.value = true
  const el = viewport.value
  const height = el?.scrollHeight || 0
  const version = generation
  following.value = false
  try {
    const data = await get<Result>(`/api/support/conversations/${props.conversationId}/messages?before=${messages.value[0]?.id || 0}`)
    if (!data || version !== generation) return
    merge(data.items)
    hasOlder.value = data.has_more
    await nextTick()
    if (el) el.scrollTop += el.scrollHeight - height
  } finally { loadingOlder.value = false }
}
function setFile(file: File | null) {
  if (draft.value.sending) return
  if (file && (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 4 * 1024 * 1024)) {
    toast(t('support.imageLimit'), 'error'); return
  }
  draft.value.file = file
  draft.value.clientId = ''
  sendFailed.value = false
  if (picker.value) picker.value.value = ''
}
function paste(event: ClipboardEvent) {
  const file = [...(event.clipboardData?.files || [])].find(f => f.type.startsWith('image/'))
  if (file) { event.preventDefault(); setFile(file) }
}
function keydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  if (!event.repeat) void send()
}
function resizeInput() {
  const el = input.value?.element
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(144, el.scrollHeight)}px`
}
async function send() {
  if (!canSend.value) return
  const current = draft.value
  current.sending = true
  current.clientId ||= crypto.randomUUID()
  sendFailed.value = false
  const version = generation
  const cid = props.conversationId
  try {
    let result: Message | null
    if (current.file) {
      const form = new FormData()
      form.append('client_id', current.clientId)
      form.append('content', current.text.trim())
      form.append('image', current.file)
      const res = await raw(`/api/support/conversations/${cid}/messages`, { method: 'POST', body: form })
      result = res?.ok ? await res.json() : null
    } else {
      result = await post<Message>(`/api/support/conversations/${cid}/messages`, { client_id: current.clientId, content: current.text.trim() })
    }
    if (result) {
      current.text = ''
      current.file = null
      current.clientId = ''
      if (version === generation) {
        // The receive cursor only advances through fetched history, never through our own reply.
        merge([result])
        await refresh()
        await scrollDown()
      }
    } else if (version === generation) sendFailed.value = true
  } finally {
    current.sending = false
    if (alive && version === generation) {
      await nextTick()
       if (props.active && window.matchMedia('(pointer: fine)').matches) input.value?.focus()
    }
  }
}
function showImage(url: string) { selectedImage.value = url; imageOpen.value = true }
useSupportEvents(() => void refresh())
watch(() => props.conversationId, () => {
  draft.value = support.draftFor(props.conversationId)
  generation++
  receiveCursor = 0
  messages.value = []
  ownRead.value = otherRead.value = 0
  hasOlder.value = false
  sendFailed.value = false
  following.value = true
  newMessages.value = 0
  void refresh()
}, { immediate: true })
watch(() => props.active, value => { if (value) { void refresh(); nextTick(resizeInput) } })
watch(content, () => nextTick(resizeInput), { immediate: true })
watch(() => draft.value.file, file => {
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  imagePreview.value = file ? URL.createObjectURL(file) : ''
}, { immediate: true })
onMounted(() => {
  observer = new ResizeObserver(() => { if (following.value && props.active) void scrollDown() })
  if (viewport.value) observer.observe(viewport.value)
  resizeInput()
})
onBeforeUnmount(() => {
  alive = false
  generation++
  observer?.disconnect()
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
})
</script>

<template>
  <section class="chat" :class="{ 'chat--workspace': layout === 'workspace', 'chat--compact': compact }">
    <div class="history">
      <div ref="viewport" class="messages" role="log" :aria-label="t('support.history')" :aria-live="active ? 'polite' : 'off'" @scroll="onScroll">
        <div v-if="hasOlder" class="older"><BaseButton size="sm" variant="ghost" :loading="loadingOlder" @click="older"><MsIcon name="history" size="sm" />{{ t('support.older') }}</BaseButton></div>
        <LoadingCenter v-if="loading && !messages.length" size="sm" />
        <div v-else-if="!messages.length && !failed" class="empty-chat"><span class="empty-icon"><MsIcon name="chat_bubble" size="lg" /></span><p>{{ admin ? t('support.empty') : t('support.startConversation') }}</p></div>
        <template v-for="message in timeline" :key="message.id">
          <div v-if="message.day" class="day-divider"><span>{{ message.day }}</span></div>
          <article class="message" :class="{ mine: mine(message), grouped: !message.groupStart }">
            <span v-if="!mine(message)" class="message-avatar" :class="{ invisible: !message.groupStart }"><MsIcon :name="message.is_admin ? 'support_agent' : 'person'" size="sm" /></span>
            <div class="message-main">
              <span v-if="message.groupStart && !mine(message)" class="sender"><span class="sender-name" :title="message.is_admin ? t('support.agent') : customerName">{{ message.is_admin ? t('support.agent') : (customerName || t('support.customer')) }}</span><span v-if="message.automated" class="automated">{{ t('support.automated') }}</span></span>
              <div class="bubble" :class="{ 'image-only': !message.content && message.image_url }">
                <MessageText v-if="message.content" class="message-copy" :text="message.content" @navigate="emit('navigate')" />
                <button v-if="message.image_url" type="button" class="message-image" :aria-label="t('support.viewImage')" @click="showImage(message.image_url)"><img :src="message.image_url" :alt="t('support.image')" @load="onImageLoad" /></button>
              </div>
              <div v-if="message.groupEnd" class="message-meta"><time :datetime="message.created_at" :title="message.fullTime">{{ message.time }}</time><span v-if="mine(message) && !message.automated" class="receipt" :class="{ read: message.id <= otherRead }"><MsIcon :name="message.id <= otherRead ? 'done_all' : 'check'" size="xs" />{{ message.id <= otherRead ? t('support.read') : t('support.sent') }}</span><span v-if="mine(message) && message.automated">{{ t('support.automated') }}</span></div>
            </div>
          </article>
        </template>
      </div>
      <button v-if="newMessages" type="button" class="new-messages" @click="scrollDown"><MsIcon name="arrow_downward" size="sm" />{{ t('support.newMessages', { count: newMessages }) }}</button>
    </div>
    <div v-if="failed" class="retry"><BaseButton size="sm" variant="ghost" @click="refresh">{{ t('support.retry') }}</BaseButton></div>
    <form class="compose-area" @submit.prevent="send">
      <div class="composer" :class="{ 'send-failed': sendFailed }">
        <div v-if="imagePreview" class="attachment"><img :src="imagePreview" :alt="t('support.image')" /><span>{{ draft.file?.name || t('support.image') }}</span><BaseButton type="button" size="sm" variant="ghost" square :aria-label="t('support.remove')" :disabled="draft.sending" @click="setFile(null)"><MsIcon name="close" size="sm" /></BaseButton></div>
        <BaseTextarea ref="input" v-model="content" class="message-input" :disabled="draft.sending" :rows="2" maxlength="4000" enterkeyhint="send" :placeholder="t('support.placeholder')" :aria-label="t('support.placeholder')" @paste="paste" @keydown="keydown" />
        <div class="compose-actions">
          <input ref="picker" type="file" accept="image/png,image/jpeg,image/webp" hidden @change="setFile(($event.target as HTMLInputElement).files?.[0] || null)" />
          <SplitButton :label="draft.sending ? t('support.sending') : t('support.send')" icon="arrow_upward" :loading="draft.sending" :main-disabled="!canSend" :menu-label="t('support.attach')" :options="[{ key: 'attach', label: t('support.attach'), icon: 'image' }]" placement="top" @click="send" @select="picker?.click()" />
        </div>
      </div>
      <p v-if="sendFailed" class="send-error" role="alert">{{ t('support.sendFailed') }}</p>
    </form>
    <BaseModal v-model="imageOpen" :title="t('support.image')" size="lg"><img class="image-lightbox" :src="selectedImage" :alt="t('support.image')" /></BaseModal>
  </section>
</template>

<style scoped>
.chat { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; width: 100%; background: var(--bg2); }
.history { flex: 1; min-height: 0; position: relative; }
.messages { height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--bd) transparent; padding: 8px 20px 20px; }
.older { display: flex; justify-content: center; padding: 8px 0; }
.empty-chat { display: flex; height: 100%; min-height: 140px; flex-direction: column; align-items: center; justify-content: center; gap: 16px; text-align: center; color: var(--t2); }
.empty-icon { display: grid; place-items: center; width: 64px; height: 64px; color: var(--ac); background: color-mix(in srgb, var(--ac) 9%, var(--bg2)); border-radius: 24px; }
.empty-chat p { margin: 0; font-size: var(--text-sm); }
.day-divider { display: flex; justify-content: center; padding: var(--sp-5) 0; color: var(--t3); font-size: var(--text-xs); letter-spacing: .02em; }
.day-divider span { padding: 4px 12px; border-radius: 20px; background: var(--bg3); }
.message { display: flex; align-items: flex-start; gap: 9px; margin-top: 18px; }
.message.grouped { margin-top: 4px; }
.day-divider + .message { margin-top: 0; }
.message.mine { justify-content: flex-end; }
.message-avatar { flex-shrink: 0; display: grid; place-items: center; height: 28px; width: 28px; margin-top: 23px; border-radius: 10px; background: color-mix(in srgb, var(--ac) 12%, var(--bg2)); color: var(--ac); }
.invisible { visibility: hidden; }
.grouped .message-avatar { margin-top: 0; }
.message-main { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; max-width: min(85%, 560px); }
.mine .message-main { align-items: flex-end; }
.sender { display: flex; align-items: center; max-width: 100%; gap: var(--sp-2); margin: 0 2px 6px; font-size: var(--text-xs); color: var(--t3); }
.sender-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.automated { font-size: var(--text-xs); color: var(--t3); }
.bubble { min-width: 0; max-width: 100%; background: var(--ac-solid); color: var(--t-inv); padding: 10px 14px; border-radius: var(--r-xs) var(--r-lg) var(--r-lg) var(--r-lg); }
.mine .bubble { color: var(--t1); background: var(--bg3); border-radius: 16px 4px 16px 16px; }
.grouped .bubble { border-radius: 16px; }
.message-meta { display: flex; align-items: center; gap: var(--sp-2); margin: 6px 2px 0; font-size: var(--text-xs); color: var(--t3); }
.receipt { display: inline-flex; align-items: center; gap: 3px; }
.receipt.read { color: var(--ac); }
.message-image { display: block; max-width: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; border-radius: 10px; overflow: hidden; }
.message-image img { display: block; max-width: 100%; max-height: 240px; min-height: 40px; object-fit: contain; }
.message-copy + .message-image { margin-top: var(--sp-3); }
.image-only { padding: 4px; }
.new-messages { position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%); display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; white-space: nowrap; border: 1px solid var(--bd); border-radius: 24px; background: var(--bg2); color: var(--ac); font: inherit; font-size: var(--text-xs); box-shadow: 0 4px 20px #0002; cursor: pointer; }
.retry { display: flex; justify-content: center; padding: 4px 12px; }
.compose-area { flex-shrink: 0; padding: 0 16px 16px; }
.composer { border: 1px solid var(--bd); border-radius: 18px; background: var(--bg); transition: border-color .18s; }
.composer:focus-within { border-color: color-mix(in srgb, var(--ac) 65%, var(--bd)); }
.composer.send-failed { border-color: var(--red); }
.message-input { display: block; width: 100%; min-height: 72px; max-height: 144px; resize: none; padding: 14px 14px 8px; border: 0; border-radius: 18px 18px 0 0; background: transparent; line-height: 1.6; scrollbar-width: thin; }
.message-input:focus { box-shadow: none; }
.compose-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; padding: 0 10px 10px 14px; }
.attachment { display: flex; gap: 10px; align-items: center; margin: 10px 10px 0; padding: 8px; background: var(--bg3); border-radius: 12px; }
.attachment img { height: 44px; width: 52px; object-fit: cover; border-radius: 6px; }
.attachment span { flex: 1; min-width: 0; font-size: var(--text-xs); color: var(--t2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.send-error { margin: 8px 4px 0; font-size: var(--text-xs); color: var(--red); }
.image-lightbox { display: block; max-width: 100%; max-height: 72dvh; margin: auto; object-fit: contain; border-radius: 8px; }
.message-image:focus-visible, .new-messages:focus-visible { outline: 2px solid var(--ac); outline-offset: 3px; }
@media (pointer: coarse) { .message-input { font-size: 16px; } }
@media (max-width: 600px) { .messages { padding-inline: 16px; } .compose-area { padding: 0 12px 12px; } .message-main { max-width: 85%; } }
.chat--workspace .messages { padding-inline: max(var(--sp-6), calc((100% - 880px) / 2)); }
.chat--workspace .compose-area { width: 100%; max-width: 928px; margin-inline: auto; padding: var(--sp-3) var(--sp-6) var(--sp-5); }
.chat--workspace .composer { border-radius: var(--r-lg); }
@media (max-width: 900px) {
  .chat--workspace .messages { padding-inline: var(--sp-4); }
  .chat--workspace .compose-area { padding: var(--sp-2) var(--sp-3) var(--sp-3); }
}
.chat--compact .message-input { min-height: 48px; max-height: 96px; }
.chat--compact .compose-area { padding-bottom: var(--sp-2); }
@media (prefers-reduced-motion: reduce) { .composer { transition: none; } }
</style>
