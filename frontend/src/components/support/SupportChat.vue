<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useSupportEvents } from '@/composables/useSupportEvents'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import SplitButton from '@/components/ui/SplitButton.vue'

defineOptions({ name: 'SupportChat' })

const props = defineProps<{ conversationId: number; admin?: boolean }>()
const { t, locale } = useI18n()
const { get, post, raw } = useApiFetch()
const { toast } = useToast()
interface Message { id: number; content: string; is_admin: boolean; image_url: string | null; created_at: string }
interface Result { items: Message[]; has_more: boolean; user_read_id: number; admin_read_id: number }
const messages = ref<Message[]>([])
const content = ref('')
const attachment = ref<File | null>(null)
const imagePreview = ref('')
const sending = ref(false)
const loading = ref(false)
const failed = ref(false)
const hasOlder = ref(false)
const otherRead = ref(0)
const ownRead = ref(0)
const viewport = ref<HTMLElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
let generation = 0
let busy = false
let rerun = false
let clientId = ''
let alive = true
let reading = false
const canSend = computed(() => !!(content.value.trim() || attachment.value) && !sending.value)

function atBottom() {
  const el = viewport.value
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 70
}
async function markRead() {
  if (!alive || reading || document.visibilityState !== 'visible' || !atBottom()) return
  const id = messages.value[messages.value.length - 1]?.id || 0
  if (id <= ownRead.value) return
  const version = generation
  reading = true
  try {
    if (await post(`/api/support/conversations/${props.conversationId}/read`, { message_id: id }) && version === generation) ownRead.value = id
  } finally { reading = false }
}
async function scrollDown() {
  await nextTick()
  if (viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight
  await markRead()
}
function merge(items: Message[]) {
  const all = new Map(messages.value.map(m => [m.id, m]))
  items.forEach(m => all.set(m.id, m))
  messages.value = [...all.values()].sort((a, b) => a.id - b.id)
}
async function refresh(initial = false) {
  if (!alive) return
  if (busy) { rerun = true; return }
  busy = true
  const version = generation
  const bottom = atBottom()
  loading.value = initial
  try {
    let more = true
    while (more && version === generation) {
      const after = initial ? 0 : (messages.value[messages.value.length - 1]?.id || 0)
      const data = await get<Result>(`/api/support/conversations/${props.conversationId}/messages?after=${after}`, { silent: true })
      if (version !== generation) return
      if (!data) { failed.value = true; return }
      failed.value = false
      merge(data.items)
      otherRead.value = props.admin ? data.user_read_id : data.admin_read_id
      ownRead.value = props.admin ? data.admin_read_id : data.user_read_id
      if (!after) hasOlder.value = data.has_more
      more = !!after && data.has_more && data.items.length > 0
      initial = false
    }
    if (bottom) await scrollDown()
  } finally {
    busy = false
    loading.value = false
    if (rerun) { rerun = false; void refresh(messages.value.length === 0) }
  }
}
async function older() {
  const el = viewport.value
  const height = el?.scrollHeight || 0
  const version = generation
  const data = await get<Result>(`/api/support/conversations/${props.conversationId}/messages?before=${messages.value[0]?.id || 0}`)
  if (!data || version !== generation) return
  merge(data.items)
  hasOlder.value = data.has_more
  await nextTick()
  if (el) el.scrollTop += el.scrollHeight - height
}
function setFile(file: File | null) {
  if (file && (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 4 * 1024 * 1024)) {
    toast(t('support.imageLimit'), 'error'); return
  }
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
  attachment.value = file
  imagePreview.value = file ? URL.createObjectURL(file) : ''
  clientId = ''
  if (picker.value) picker.value.value = ''
}
function paste(event: ClipboardEvent) {
  const file = [...(event.clipboardData?.files || [])].find(f => f.type.startsWith('image/'))
  if (file) { event.preventDefault(); setFile(file) }
}
async function send() {
  if (!canSend.value) return
  sending.value = true
  clientId ||= crypto.randomUUID()
  const version = generation
  try {
    let result: Message | null
    if (attachment.value) {
      const form = new FormData()
      form.append('client_id', clientId)
      form.append('content', content.value.trim())
      form.append('image', attachment.value)
      const res = await raw(`/api/support/conversations/${props.conversationId}/messages`, { method: 'POST', body: form })
      result = res?.ok ? await res.json() : null
    } else {
      result = await post<Message>(`/api/support/conversations/${props.conversationId}/messages`, { client_id: clientId, content: content.value.trim() })
    }
    if (result && version === generation) {
      // Fetch intervening messages before advancing the receive cursor to our reply.
      await refresh()
      content.value = ''
      setFile(null)
      await scrollDown()
    }
  } finally { sending.value = false }
}
useSupportEvents(() => void refresh(messages.value.length === 0))
watch(() => props.conversationId, () => {
  generation++
  messages.value = []
  content.value = ''
  setFile(null)
  ownRead.value = otherRead.value = 0
  hasOlder.value = false
  void refresh(true)
}, { immediate: true })
onBeforeUnmount(() => {
  alive = false
  generation++
  if (imagePreview.value) URL.revokeObjectURL(imagePreview.value)
})
</script>

<template>
  <section class="chat">
    <div ref="viewport" class="messages" role="log" aria-live="polite" @scroll="markRead">
      <BaseButton v-if="hasOlder" size="sm" variant="ghost" @click="older">{{ t('support.older') }}</BaseButton>
      <LoadingCenter v-if="loading && !messages.length" size="sm" />
      <EmptyState v-else-if="!messages.length" icon="support_agent" :message="t('support.empty')" />
      <div v-for="message in messages" :key="message.id" class="message" :class="{ mine: message.is_admin === !!admin }">
        <div class="message-meta">{{ message.is_admin ? t('support.agent') : t('support.customer') }} · {{ new Date(message.created_at).toLocaleString(locale) }}</div>
        <div class="bubble">
          <p v-if="message.content">{{ message.content }}</p>
          <a v-if="message.image_url" :href="message.image_url" target="_blank" rel="noopener noreferrer"><img :src="message.image_url" :alt="t('support.image')" @load="markRead" /></a>
        </div>
        <span v-if="message.is_admin === !!admin" class="receipt">{{ message.id <= otherRead ? t('support.read') : t('support.sent') }}</span>
      </div>
    </div>
    <div v-if="failed" class="retry"><BaseButton size="sm" variant="ghost" @click="refresh(messages.length === 0)">{{ t('support.retry') }}</BaseButton></div>
    <form class="composer" @submit.prevent="send">
      <div v-if="imagePreview" class="attachment"><img :src="imagePreview" :alt="t('support.image')" /><BaseButton type="button" size="sm" variant="ghost" :disabled="sending" @click="setFile(null)">{{ t('support.remove') }}</BaseButton></div>
      <BaseTextarea v-model="content" class="message-input" :disabled="sending" :rows="3" maxlength="4000" :placeholder="t('support.placeholder')" :aria-label="t('support.placeholder')" @update:modelValue="clientId = ''" @paste="paste" @keydown.ctrl.enter.prevent="send" @keydown.meta.enter.prevent="send" />
      <div class="compose-actions">
        <input ref="picker" type="file" accept="image/png,image/jpeg,image/webp" hidden @change="setFile(($event.target as HTMLInputElement).files?.[0] || null)" />
        <SplitButton
          :label="sending ? t('support.sending') : t('support.send')"
          :loading="sending"
          :main-disabled="!canSend"
          :menu-label="t('support.attach')"
          :options="[{ key: 'attach', label: t('support.attach'), icon: 'image' }]"
          placement="top"
          @click="send"
          @select="picker?.click()"
        />
      </div>
    </form>
  </section>
</template>

<style scoped>
.chat { flex: 1; display: flex; flex-direction: column; gap: var(--sp-3); min-height: 0; width: 100%; }
.messages { flex: 1; overflow-y: auto; min-height: 0; padding: var(--sp-3); background: var(--bg); border: 1px solid var(--bd); border-radius: var(--rs); }
.message { display: flex; flex-direction: column; align-items: flex-start; margin-bottom: var(--sp-4); }
.message:last-child { margin-bottom: 0; }
.mine { align-items: flex-end; }
.message-meta, .receipt { font-size: var(--text-xs); color: var(--t3); margin: var(--sp-1) 0; }
.bubble { max-width: min(85%, 640px); background: var(--bg3); border: 1px solid var(--bd); padding: var(--sp-2) var(--sp-3); border-radius: var(--rs); overflow-wrap: anywhere; }
.mine .bubble { background: var(--acg); border-color: color-mix(in srgb, var(--ac) 25%, var(--bd)); }
.bubble p { margin: 0; white-space: pre-wrap; color: var(--t1); font-size: var(--text-base); line-height: 1.65; }
.bubble img { display: block; max-width: 100%; max-height: 240px; object-fit: contain; border-radius: var(--r-sm); }
.bubble p + a { display: block; margin-top: var(--sp-2); }
.composer { flex-shrink: 0; border: 1px solid var(--bd); border-radius: var(--rs); background: var(--bg); transition: border-color .15s, box-shadow .15s; }
.composer:focus-within { border-color: var(--ac); box-shadow: 0 0 0 3px var(--acg); }
.message-input { display: block; resize: none; padding: var(--sp-3); border: 0; background: transparent; }
.message-input:focus { box-shadow: none; }
.compose-actions { display: flex; justify-content: flex-end; padding: 0 var(--sp-2) var(--sp-2); }
.attachment { display: flex; gap: var(--sp-3); align-items: center; padding: var(--sp-3) var(--sp-3) 0; }
.attachment img { max-height: 64px; max-width: 120px; border: 1px solid var(--bd); border-radius: var(--r-sm); }
@media (max-width: 768px) { .bubble { max-width: 94%; } }
</style>
