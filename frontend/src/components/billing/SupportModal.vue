<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useClipboard } from '@/composables/useClipboard'
import { useApiFetch } from '@/composables/useApiFetch'
import { useAppStore } from '@/stores/app'
import { useSupportStore } from '@/stores/support'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import MessageText from '@/components/support/MessageText.vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>()
const { t } = useI18n()
const { copy } = useClipboard()
const { get } = useApiFetch()
const router = useRouter()
const app = useAppStore()
const support = useSupportStore()
const branding = ref<Record<string, string>>({})
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const rows = computed(() => [
  { icon: 'mail', label: t('billing.support.email'), value: branding.value.support_email },
  { icon: 'forum', label: t('billing.support.qqGroup'), value: branding.value.support_qq_group },
  { icon: 'account_circle', label: t('billing.support.qq'), value: branding.value.support_qq },
  { icon: 'chat', label: t('billing.support.wechat'), value: branding.value.support_wechat },
].filter(row => row.value?.trim()))
watch(open, async value => {
  if (value) {
    const data = await get<Record<string, string>>('/api/public/branding', { silent: true })
    if (data) branding.value = data
  }
}, { immediate: true })
async function openChat() {
  open.value = false
  await nextTick()
  if (app.isAdmin) await router.push({ name: 'admin-support' })
  else if (!app.sessionUser) await router.push({ name: 'login', query: { redirect: '/support' } })
  else support.open = true
}
</script>

<template>
  <BaseModal v-model="open" :title="t('billing.support.title')" icon="support_agent" size="sm">
    <ul class="contact-list">
      <li>
        <button type="button" class="contact-row contact-row--online" @click="openChat">
          <MsIcon name="chat_bubble" size="sm" />
          <span class="contact-info"><span class="contact-value">{{ t('support.title') }}</span></span>
          <span class="contact-action">{{ t('billing.support.startChat') }}<MsIcon name="arrow_forward" size="sm" /></span>
        </button>
      </li>
      <li v-for="row in rows" :key="row.icon"><div class="contact-row"><MsIcon :name="row.icon" size="sm" /><div class="contact-info"><span class="contact-label">{{ row.label }}</span><span class="contact-value">{{ row.value }}</span></div><BaseButton size="sm" variant="ghost" square :aria-label="t('support.copyContact', { name: row.label })" @click="copy(row.value!)"><MsIcon name="content_copy" size="sm" /></BaseButton></div></li>
    </ul>
    <MessageText v-if="branding.support_footer_note?.trim()" class="footer-note" :text="branding.support_footer_note" @navigate="open = false" />
  </BaseModal>
</template>

<style scoped>
.contact-list { list-style: none; margin: 0; padding: 0; }
.contact-row { display: flex; align-items: center; gap: var(--sp-3); width: 100%; min-height: 64px; padding: var(--sp-3) var(--sp-2); color: var(--t3); }
.contact-list > li + li { border-top: 1px solid var(--bd); }
.contact-row--online { border: 0; border-radius: var(--r-sm); background: transparent; color: var(--ac); font: inherit; text-align: left; cursor: pointer; transition: background .15s; }
.contact-row--online .contact-value { color: var(--ac); font-weight: 500; }
.contact-row--online:hover { background: color-mix(in srgb, var(--ac) 7%, transparent); }
.contact-row--online:focus-visible { outline: 2px solid var(--ac); outline-offset: -2px; }
.contact-action { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--text-xs); white-space: nowrap; }
.contact-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.contact-label { font-size: var(--text-xs); color: var(--t3); }
.contact-value { font-size: var(--text-sm); color: var(--t1); overflow-wrap: anywhere; }
.footer-note { margin-top: var(--sp-4); color: var(--t3); font-size: var(--text-xs); }
@media (prefers-reduced-motion: reduce) { .contact-row--online { transition: none; } }
</style>
