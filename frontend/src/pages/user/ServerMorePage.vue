<script setup lang="ts">
import { computed, inject, ref, onMounted, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from '@/composables/useToast'
import { useAppStore } from '@/stores/app'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ServerMorePage' })

const { t } = useI18n({ useScope: 'global' })
const { toast } = useToast()
const app = useAppStore()

interface ServerCtx {
  id: number
  uuid: string
  uuidShort: string
  nodeId: number
  node: { fqdn: string | null; name: string | null; sftpPort: number | null }
}

const server = inject<Ref<ServerCtx | null>>('server')!

// SFTP username format used by Wings: "<panel-username>.<uuidShort>"
const panelUsername = ref('')

onMounted(async () => {
  try {
    const data = await app.fetchSessionUser()
    if (data) {
      panelUsername.value = String(data?.username || '')
    }
  } catch { /* ignore */ }
})

const sftpHost = computed(() => server.value?.node?.fqdn || '')
const sftpPort = computed(() => String(server.value?.node?.sftpPort ?? ''))
const sftpUser = computed(() => {
  const u = panelUsername.value
  const s = server.value?.uuidShort || ''
  return u && s ? `${u}.${s}` : ''
})

const debugServerId = computed(() => String(server.value?.id ?? ''))
const debugUuid = computed(() => server.value?.uuid || '')
const debugShort = computed(() => server.value?.uuidShort || '')
const debugNode = computed(() => {
  const n = server.value?.node
  if (!n) return ''
  const parts: string[] = []
  if (n.name) parts.push(n.name)
  if (n.fqdn) parts.push(`(${n.fqdn})`)
  if (server.value?.nodeId != null) parts.push(`#${server.value.nodeId}`)
  return parts.join(' ')
})

interface ClientLink {
  platform: string
  name: string
  url: string
}

const clients = computed<ClientLink[]>(() => [
  { platform: t('userServers.connectPage.clientDesktop'), name: 'FileZilla', url: 'https://filezilla-project.org/' },
  { platform: t('userServers.connectPage.clientIos'), name: 'Documents by Readdle', url: 'https://apps.apple.com/cn/app/id364901807' },
  { platform: t('userServers.connectPage.clientAndroid'), name: 'Material Files', url: 'https://play.google.com/store/apps/details?id=me.zhanghai.android.files' },
])

async function copyValue(value: string) {
  if (!value) return
  let ok = false
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value)
      ok = true
    }
  } catch { /* fall through to legacy path */ }
  if (!ok) {
    try {
      const ta = document.createElement('textarea')
      ta.value = value
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    } catch { /* ignore */ }
  }
  toast(t('userServers.connectPage.copied'), 'success')
}
</script>

<template>
  <div class="more-panel" v-if="server">
    <div class="m-sub">
      {{ t('userServers.connectPage.debugSection') }}
      <HelpTip :text="t('userServers.connectPage.debugTip')" />
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.serverId') }}</span>
      <span class="kv-row__value">{{ debugServerId }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(debugServerId)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.serverUuid') }}</span>
      <span class="kv-row__value kv-row__value--mono">{{ debugUuid }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(debugUuid)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.shortId') }}</span>
      <span class="kv-row__value kv-row__value--mono">{{ debugShort }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(debugShort)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.node') }}</span>
      <span class="kv-row__value">{{ debugNode }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(debugNode)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="m-sub">
      {{ t('userServers.connectPage.sftpSection') }}
      <HelpTip :text="t('userServers.connectPage.sftpTip')" />
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.host') }}</span>
      <span class="kv-row__value kv-row__value--mono">{{ sftpHost }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(sftpHost)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.port') }}</span>
      <span class="kv-row__value kv-row__value--mono">{{ sftpPort }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(sftpPort)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.username') }}</span>
      <span class="kv-row__value kv-row__value--mono">{{ sftpUser }}</span>
      <button type="button" class="kv-row__copy" :title="t('common.btn.copy')" @click="copyValue(sftpUser)">
        <MsIcon name="content_copy" size="sm" />
      </button>
    </div>

    <div class="kv-row">
      <span class="kv-row__label">{{ t('userServers.connectPage.password') }}</span>
      <span class="kv-row__value kv-row__value--hint">{{ t('userServers.connectPage.passwordHint') }}</span>
    </div>

    <div class="m-sub">
      {{ t('userServers.connectPage.clientSection') }}
    </div>

    <div v-for="c in clients" :key="c.platform" class="kv-row">
      <span class="kv-row__label">{{ c.platform }}</span>
      <a class="kv-row__value kv-row__link kv-row__link--right" :href="c.url" target="_blank" rel="noopener">
        {{ c.name }}
        <MsIcon name="open_in_new" size="sm" />
      </a>
    </div>
  </div>
</template>

<style scoped>
.more-panel {
  margin-top: var(--sp-4);
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

.m-sub {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: .92rem;
  font-weight: 600;
  color: var(--t1);
  padding: var(--sp-5) 0 var(--sp-2);
  margin-top: var(--sp-2);
  border-top: 1px solid color-mix(in srgb, var(--bd) 50%, transparent);
}

.m-sub:first-of-type {
  border-top: none;
  margin-top: 0;
  padding-top: var(--sp-2);
}

.kv-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  min-height: 36px;
}

.kv-row__label {
  flex-shrink: 0;
  width: 110px;
  font-size: var(--text-sm);
  color: var(--t3);
}

.kv-row__value {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  color: var(--t1);
  overflow-wrap: anywhere;
}

.kv-row__value--mono {
  font-family: var(--font-mono, monospace);
}

.kv-row__value--hint {
  color: var(--t2);
}

.kv-row__copy {
  flex-shrink: 0;
  background: none;
  border: none;
  color: var(--t3);
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  opacity: .7;
  border-radius: var(--r-xs);
}

.kv-row__copy:hover {
  color: var(--ac);
  background: color-mix(in srgb, var(--ac) 10%, transparent);
  opacity: 1;
}

.kv-row__link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ac);
  text-decoration: none;
}

.kv-row__link--right {
  justify-content: flex-end;
  text-align: right;
}

.kv-row__link:hover {
  text-decoration: underline;
}
</style>
