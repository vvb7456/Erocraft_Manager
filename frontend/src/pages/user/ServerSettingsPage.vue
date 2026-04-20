<script setup lang="ts">
import { ref, inject, computed, onMounted, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect, { type SelectOption } from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ServerSettingsPage' })

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get, put, post, loading } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()

interface ServerDetail {
  id: number; uuid: string; nodeId: number; isSuspended: boolean
}

interface StartupVar {
  envVariable: string; name: string; description: string
  defaultValue: string; value: string; isEditable: boolean; rules: string
}

const server = inject<Ref<ServerDetail | null>>('server')!
const reloadServer = inject<() => Promise<void>>('reloadServer')!

const loaded = ref(false)
const saving = ref(false)
const updating = ref(false)
const reinstalling = ref(false)

const authMode = ref<'basic' | 'multi'>('basic')
const username = ref('admin')
const password = ref('')
const proxyEnabled = ref(true)
const gitBranch = ref('release')

const origAuthMode = ref<'basic' | 'multi'>('basic')
const origUsername = ref('')
const origPassword = ref('')
const origProxyEnabled = ref(true)
const origGitBranch = ref('release')

// GitHub branches
const branches = ref<SelectOption[]>([
  { value: 'release', label: 'release' },
  { value: 'staging', label: 'staging' },
])
const branchesLoading = ref(false)

const isDirty = computed(() =>
  authMode.value !== origAuthMode.value
  || username.value !== origUsername.value
  || password.value !== origPassword.value
  || proxyEnabled.value !== origProxyEnabled.value
  || gitBranch.value !== origGitBranch.value
)

const isMultiUser = computed(() => authMode.value === 'multi')

function snapshot() {
  origAuthMode.value = authMode.value
  origUsername.value = username.value
  origPassword.value = password.value
  origProxyEnabled.value = proxyEnabled.value
  origGitBranch.value = gitBranch.value
}

async function fetchBranches() {
  branchesLoading.value = true
  try {
    const [branchRes, tagRes] = await Promise.all([
      fetch('https://api.github.com/repos/SillyTavern/SillyTavern/branches?per_page=100'),
      fetch('https://api.github.com/repos/SillyTavern/SillyTavern/tags?per_page=50'),
    ])
    const opts: SelectOption[] = []

    // Add main branches first
    if (branchRes.ok) {
      const data = await branchRes.json() as { name: string }[]
      const mainBranches = ['release', 'staging']
      for (const name of mainBranches) {
        if (data.some(b => b.name === name)) {
          opts.push({ value: name, label: name })
        }
      }
    }

    // Add version tags
    if (tagRes.ok) {
      const tags = await tagRes.json() as { name: string }[]
      for (const tag of tags) {
        opts.push({ value: tag.name, label: tag.name })
      }
    }

    if (opts.length) {
      // Ensure current value is in the list
      if (gitBranch.value && !opts.some(o => o.value === gitBranch.value)) {
        opts.push({ value: gitBranch.value, label: gitBranch.value })
      }
      branches.value = opts
    }
  } catch {
    // fallback to defaults
  } finally {
    branchesLoading.value = false
  }
}

async function loadSettings() {
  if (!server.value) return
  const vars = await get<StartupVar[]>(`/api/user/servers/${server.value.id}/startup`)
  if (vars) {
    const m = Object.fromEntries(vars.map(v => [v.envVariable, v.value]))
    authMode.value = m['ENABLE_ACCOUNTS'] === 'true' ? 'multi' : 'basic'
    username.value = m['USERNAME'] ?? 'admin'
    password.value = m['PASSWORD'] ?? ''
    proxyEnabled.value = (m['PROXY_ENABLE'] ?? 'true') === 'true'
    gitBranch.value = m['GIT_BRANCH'] ?? 'release'
    snapshot()
  }
  loaded.value = true
}

onMounted(() => {
  loadSettings()
  fetchBranches()
})

/** Save startup variables (no confirmation / no restart). Returns true on success. */
async function saveVariablesQuiet(): Promise<boolean> {
  if (!server.value) return false
  const variables: Record<string, string> = {
    BASIC_AUTH: authMode.value === 'basic' ? 'true' : 'false',
    ENABLE_ACCOUNTS: authMode.value === 'multi' ? 'true' : 'false',
    USERNAME: authMode.value === 'basic' ? username.value : 'admin',
    PASSWORD: password.value,
    PROXY_ENABLE: proxyEnabled.value ? 'true' : 'false',
    GIT_BRANCH: gitBranch.value || 'release',
  }
  await put(`/api/user/servers/${server.value.id}/startup`, { variables })

  if (authMode.value === 'multi' && password.value) {
    await put(`/api/user/servers/${server.value.id}/st-default-password`, {
      password: password.value,
    })
  }

  snapshot()
  return true
}

async function saveSettings() {
  if (!server.value || saving.value) return
  if (authMode.value === 'multi' && !password.value) {
    toast(t('serverSettings.passwordRequired'), 'warning')
    return
  }
  const ok = await confirm({
    title: t('serverSettings.saveConfirmTitle'),
    message: t('serverSettings.saveConfirmMessage'),
    confirmText: t('serverSettings.saveConfirmBtn'),
  })
  if (!ok) return

  saving.value = true
  try {
    await saveVariablesQuiet()

    // Auto-restart server after save
    try {
      await post(`/api/user/servers/${server.value.id}/power`, { action: 'restart' })
    } catch {
      // ignore restart failure
    }

    toast(t('serverSettings.saveSuccess'), 'success')
  } catch {
    toast(t('serverSettings.saveFailed'), 'error')
  } finally {
    saving.value = false
  }
}

async function doUpdate() {
  if (!server.value || updating.value) return
  const ok = await confirm({
    title: t('serverSettings.updateTitle'),
    message: t('serverSettings.updateMessage'),
    confirmText: t('serverSettings.updateConfirm'),
  })
  if (!ok) return
  updating.value = true
  try {
    if (isDirty.value) {
      await saveVariablesQuiet()
    }
    await post(`/api/user/servers/${server.value.id}/reinstall`, { force: false })
    toast(t('serverSettings.updateStarted'), 'success')
    await reloadServer()
    router.push({ name: 'server-console', params: { id: server.value.id } })
  } catch {
    toast(t('serverSettings.updateFailed'), 'error')
  } finally {
    updating.value = false
  }
}

async function doReinstall() {
  if (!server.value || reinstalling.value) return
  const ok = await confirm({
    title: t('serverSettings.reinstallTitle'),
    message: t('serverSettings.reinstallMessage'),
    variant: 'danger',
    confirmText: t('serverSettings.reinstallConfirm'),
  })
  if (!ok) return
  reinstalling.value = true
  try {
    if (isDirty.value) {
      await saveVariablesQuiet()
    }
    await post(`/api/user/servers/${server.value.id}/reinstall`, { force: true })
    toast(t('serverSettings.reinstallStarted'), 'success')
    await reloadServer()
    router.push({ name: 'server-console', params: { id: server.value.id } })
  } catch {
    toast(t('serverSettings.reinstallFailed'), 'error')
  } finally {
    reinstalling.value = false
  }
}
</script>

<template>
  <LoadingCenter v-if="!loaded && loading" />

  <div v-else class="st-panel">
    <p class="st-desc">{{ t('serverSettings.pageDesc') }}</p>

    <!-- Auth -->
    <div class="st-sub">{{ t('serverSettings.authSection') }}</div>

    <FormField layout="horizontal">
      <template #label>
        {{ t('serverSettings.authMode') }}
        <HelpTip :text="t('serverSettings.authModeTip')" />
      </template>
      <div class="auth-mode-switch">
        <button
          class="mode-btn"
          :class="{ active: authMode === 'basic' }"
          @click="authMode = 'basic'"
        >
          <MsIcon name="lock" />
          {{ t('serverSettings.basicAuthLabel') }}
        </button>
        <button
          class="mode-btn"
          :class="{ active: authMode === 'multi' }"
          @click="authMode = 'multi'"
        >
          <MsIcon name="group" />
          {{ t('serverSettings.multiUserMode') }}
        </button>
      </div>
      <template #hint>
        {{ isMultiUser ? t('serverSettings.multiUserHint') : t('serverSettings.basicAuthHint') }}
      </template>
    </FormField>

    <FormField :label="t('serverSettings.username')" layout="horizontal">
      <BaseInput
        v-if="!isMultiUser"
        v-model="username"
      />
      <BaseInput
        v-else
        model-value="default-user"
        disabled
      />
      <template v-if="isMultiUser" #hint>
        {{ t('serverSettings.defaultUserHint') }}
      </template>
    </FormField>

    <FormField layout="horizontal">
      <template #label>
        {{ t('serverSettings.password') }}
        <HelpTip :text="isMultiUser ? t('serverSettings.passwordHintMulti') : t('serverSettings.passwordHintBasic')" />
      </template>
      <SecretInput
        v-model="password"
        :placeholder="t('serverSettings.passwordPlaceholder')"
        toggleable
      />
    </FormField>

    <!-- Network -->
    <div class="st-sub">{{ t('serverSettings.networkSection') }}</div>

    <FormField layout="horizontal" keep-horizontal>
      <template #label>
        {{ t('serverSettings.apiProxy') }}
        <HelpTip :text="t('serverSettings.apiProxyTip')" />
      </template>
      <ToggleSwitch v-model="proxyEnabled" />
    </FormField>

    <!-- Version & Updates -->
    <div class="st-sub">{{ t('serverSettings.versionSection') }}</div>

    <FormField layout="horizontal">
      <template #label>
        {{ t('serverSettings.gitBranch') }}
        <HelpTip :text="t('serverSettings.gitBranchTip')" />
      </template>
      <BaseSelect v-model="gitBranch" :options="branches" />
    </FormField>

    <FormField layout="horizontal">
      <template #label>&nbsp;</template>
      <div class="action-row">
        <BaseButton :loading="updating" :disabled="saving || reinstalling" @click="doUpdate">
          <MsIcon name="update" />
          {{ t('serverSettings.updateBtn') }}
        </BaseButton>
        <BaseButton variant="danger" :loading="reinstalling" :disabled="saving || updating" @click="doReinstall">
          <MsIcon name="delete_forever" />
          {{ t('serverSettings.reinstallBtn') }}
        </BaseButton>
      </div>
    </FormField>

    <!-- Save -->
    <div class="st-save">
      <BaseButton
        variant="primary"
        :loading="saving"
        :disabled="!isDirty || updating || reinstalling"
        @click="saveSettings"
      >
        {{ t('serverSettings.saveBtn') }}
      </BaseButton>
    </div>
  </div>
</template>

<style scoped>
.st-panel {
  margin-top: var(--sp-4);
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}

.st-desc {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--t1);
  margin: 0 0 var(--sp-4);
}

.st-sub {
  font-size: .92rem;
  font-weight: 600;
  color: var(--t1);
  padding: var(--sp-5) 0 var(--sp-2);
  margin-top: var(--sp-2);
  border-top: 1px solid color-mix(in srgb, var(--bd) 50%, transparent);
}

.st-sub:first-of-type {
  border-top: none;
  margin-top: 0;
  padding-top: var(--sp-2);
}

.auth-mode-switch {
  display: flex;
  gap: var(--sp-2);
  width: 100%;
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-1);
  flex: 1;
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  background: var(--bg-in);
  color: var(--t2);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.mode-btn:hover {
  border-color: var(--t3);
  color: var(--t1);
}

.mode-btn.active {
  border-color: var(--ac);
  background: rgba(20, 184, 166, 0.1);
  color: var(--ac);
}

.mode-btn .ms-icon {
  font-size: 1rem;
}

.action-row {
  display: flex;
  gap: var(--sp-2);
  width: 100%;
}

.action-row :deep(.base-btn) {
  flex: 1;
}

.st-save {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-4) 0;
}
</style>
