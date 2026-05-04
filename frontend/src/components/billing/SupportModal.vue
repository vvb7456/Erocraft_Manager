<script setup lang="ts">
/**
 * SupportModal — contact-support info dialog launched from payment flow.
 *
 * Shows admin-configured contact channels (email, QQ, QQ group, WeChat).
 * Reads from /public/branding which includes SUPPORT_* keys.
 * Empty fields are hidden automatically.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@/composables/useToast'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'SupportModal' })

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>()

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const supportEmail = ref('')
const supportQQGroup = ref('')
const supportQQ = ref('')
const supportWechat = ref('')
const supportFooterNote = ref('')

onMounted(async () => {
  try {
    const res = await fetch('/api/public/branding')
    if (res.ok) {
      const data = await res.json()
      supportEmail.value = data.support_email || ''
      supportQQGroup.value = data.support_qq_group || ''
      supportQQ.value = data.support_qq || ''
      supportWechat.value = data.support_wechat || ''
      supportFooterNote.value = data.support_footer_note || ''
    }
  } catch { /* ignore */ }
})

interface ContactRow { icon: string; label: string; value: string }
const rows = computed<ContactRow[]>(() => [
  { icon: 'mail', label: t('billing.support.email'), value: supportEmail.value },
  { icon: 'forum', label: t('billing.support.qqGroup'), value: supportQQGroup.value },
  { icon: 'account_circle', label: t('billing.support.qq'), value: supportQQ.value },
  { icon: 'chat', label: t('billing.support.wechat'), value: supportWechat.value },
].filter(r => r.value.trim() !== ''))

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast(t('billing.support.copied'), 'success')
  } catch {
    toast(t('billing.support.copyFailed'), 'error')
  }
}
</script>

<template>
  <BaseModal v-model="open" :title="t('billing.support.title')" icon="support_agent" size="sm">
    <p class="intro">{{ t('billing.support.intro') }}</p>

    <ul class="contact-list">
      <li v-for="row in rows" :key="row.icon" class="contact-row">
        <MsIcon :name="row.icon" size="sm" />
        <span class="contact-label">{{ row.label }}</span>
        <span class="contact-value mono">{{ row.value }}</span>
        <BaseButton size="sm" variant="ghost" @click="copy(row.value)">
          <MsIcon name="content_copy" size="sm" />
        </BaseButton>
      </li>
    </ul>

    <p v-if="supportFooterNote.trim()" class="footer-note">{{ supportFooterNote }}</p>

    <template #footer>
      <BaseButton variant="primary" @click="open = false">
        {{ t('billing.support.btnOk') }}
      </BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
.intro {
  margin: 0 0 var(--sp-3);
  color: var(--t2);
  font-size: var(--text-sm);
  line-height: 1.6;
}
.contact-list {
  list-style: none;
  margin: 0 0 var(--sp-3);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.contact-row {
  display: grid;
  grid-template-columns: auto auto 1fr auto;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-md);
}
.contact-label {
  color: var(--t2);
  font-size: var(--text-sm);
  min-width: 4em;
}
.contact-value {
  color: var(--t1);
  font-size: var(--text-sm);
}
.mono {
  font-family: 'IBM Plex Mono', monospace;
}
.footer-note {
  margin: 0;
  color: var(--t3);
  font-size: var(--text-xs);
  text-align: center;
}
</style>

