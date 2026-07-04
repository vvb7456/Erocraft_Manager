<script setup lang="ts">
import { ref, inject, computed, watch, onMounted, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { useConfirm } from '@/composables/useConfirm'
import { useAppStore } from '@/stores/app'
import type { StartupVar, EggSettingsProps, EggSettingsExpose } from './types'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect, { type SelectOption } from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import UsageBar from '@/components/ui/UsageBar.vue'
import Spinner from '@/components/ui/Spinner.vue'

const props = defineProps<EggSettingsProps>()
const emit = defineEmits<{
  (e: 'update:dirty', dirty: boolean): void
}>()

const { t } = useI18n({ useScope: 'global' })
const router = useRouter()
const { get, put, post, error: apiError } = useApiFetch()
const { toast } = useToast()
const { confirm } = useConfirm()
const appStore = useAppStore()

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { timeZone: appStore.timezone, hour12: false })
  } catch { return iso }
}

const reloadServer = inject<() => Promise<void>>('reloadServer')!

// ─── LLM free quota (optional; only shown when provisioned) ───
interface ServerCtx {
  llmEnabled: boolean
}
const server = inject<Ref<ServerCtx | null>>('server', ref(null))

interface LlmUsage {
  status: string | null
  quotaGrant: number
  quotaUsed: number
  quotaAvailable: number
  nextResetAt: string | null
  enabled: boolean
  apiKey: string | null
  apiBaseUrl: string
  usageQueryFailed: boolean
}

const llmUsage = ref<LlmUsage | null>(null)
const llmLoading = ref(false)
const llmLoadFailed = ref(false)
const llmUsedPercent = computed(() => {
  const u = llmUsage.value
  if (!u || u.quotaGrant <= 0) return 0
  return Math.round((u.quotaUsed / u.quotaGrant) * 100)
})

async function loadLlmUsage() {
  if (!server.value?.llmEnabled) return
  llmLoading.value = true
  llmLoadFailed.value = false
  try {
    const data = await get<LlmUsage>(`/api/user/servers/${props.serverId}/llm/usage`)
    if (data) llmUsage.value = data
    else llmLoadFailed.value = true
  } finally {
    llmLoading.value = false
  }
}

const updating = ref(false)
const switchingVersion = ref(false)
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

// Password validation
const passwordError = computed(() => {
  const p = password.value
  if (!p) return t('serverSettings.passwordRequired')
  if (p.length < 8) return t('serverSettings.passwordMinLength')
  if (/\s/.test(p)) return t('serverSettings.passwordNoSpaces')
  if (!/[a-zA-Z]/.test(p)) return t('serverSettings.passwordNeedLetter')
  if (!/\d/.test(p)) return t('serverSettings.passwordNeedDigit')
  return ''
})
const passwordValid = computed(() => !passwordError.value)

// Username validation (basic auth mode only). Requiring at least one letter
// avoids YAML type-coercion in /home/container/config.yaml: a purely numeric
// username like `123456` is parsed as integer by Wings' yaml writer, and ST's
// strict `===` compare against the string from the HTTP Basic header always
// fails -> infinite 401 loop.
const usernameError = computed(() => {
  if (isMultiUser.value) return ''
  const u = username.value
  if (!u) return t('serverSettings.usernameRequired')
  if (/\s/.test(u)) return t('serverSettings.usernameNoSpaces')
  if (u.includes(':')) return t('serverSettings.usernameNoColon')
  if (!/[a-zA-Z]/.test(u)) return t('serverSettings.usernameNeedLetter')
  return ''
})
const usernameValid = computed(() => !usernameError.value)

// GitHub tags only — release/staging are reachable via the dedicated
// "更新到最新 release" button, no need to mix them into the version dropdown.
const branches = ref<SelectOption[]>([])
const branchesLoading = ref(false)

// gitBranch is intentionally excluded from isDirty: switching version is its
// own explicit action with a dedicated button, not something the DirtyBar
// should silently "save" (which would only restart, not actually re-pull code).
const isDirty = computed(() =>
  authMode.value !== origAuthMode.value
  || username.value !== origUsername.value
  || password.value !== origPassword.value
  || proxyEnabled.value !== origProxyEnabled.value
)

const versionChanged = computed(() => gitBranch.value !== origGitBranch.value)

watch(isDirty, (v) => emit('update:dirty', v))

const isMultiUser = computed(() => authMode.value === 'multi')

function snapshot() {
  origAuthMode.value = authMode.value
  origUsername.value = username.value
  origPassword.value = password.value
  origProxyEnabled.value = proxyEnabled.value
  origGitBranch.value = gitBranch.value
}

function initFromVars(vars: StartupVar[]) {
  const m = Object.fromEntries(vars.map(v => [v.envVariable, v.value]))
  authMode.value = m['ENABLE_ACCOUNTS'] === 'true' ? 'multi' : 'basic'
  username.value = m['USERNAME'] ?? 'admin'
  password.value = m['PASSWORD'] ?? ''
  proxyEnabled.value = (m['PROXY_ENABLE'] ?? 'true') === 'true'
  gitBranch.value = m['GIT_BRANCH'] ?? 'release'
  snapshot()
}

watch(() => props.variables, (vars) => {
  if (vars.length) initFromVars(vars)
}, { immediate: true })

async function fetchBranches() {
  branchesLoading.value = true
  try {
    // Proxied through our backend (1-hour cache) to avoid GitHub's
    // unauthenticated 60-req/hour-per-IP limit hitting end users.
    const data = await get<{ tags: string[]; stale: boolean }>('/api/integrations/sillytavern/tags')
    const opts: SelectOption[] = (data?.tags ?? []).map(name => ({ value: name, label: name }))

    // Always keep the current value selectable, even if it's release/staging
    // or a tag that has fallen off the page-1 listing.
    if (gitBranch.value && !opts.some(o => o.value === gitBranch.value)) {
      opts.unshift({ value: gitBranch.value, label: gitBranch.value })
    }

    if (opts.length) branches.value = opts
  } catch {
    // fallback: just expose the current value
    if (gitBranch.value) {
      branches.value = [{ value: gitBranch.value, label: gitBranch.value }]
    }
  } finally {
    branchesLoading.value = false
  }
}

onMounted(() => {
  fetchBranches()
  loadLlmUsage()
})

/** Save startup variables (no confirmation / no restart). Returns true on success. */
async function save(): Promise<boolean> {
  if (!usernameValid.value) {
    toast(usernameError.value, 'warning')
    return false
  }
  if (!passwordValid.value) {
    toast(passwordError.value, 'warning')
    return false
  }
  const variables: Record<string, string> = {
    BASIC_AUTH: authMode.value === 'basic' ? 'true' : 'false',
    ENABLE_ACCOUNTS: authMode.value === 'multi' ? 'true' : 'false',
    USERNAME: authMode.value === 'basic' ? username.value : 'admin',
    PASSWORD: password.value,
    PROXY_ENABLE: proxyEnabled.value ? 'true' : 'false',
    GIT_BRANCH: gitBranch.value || 'release',
  }
  await put(`/api/user/servers/${props.serverId}/startup`, { variables })
  if (apiError.value) return false

  if (authMode.value === 'multi' && password.value) {
    await put(`/api/user/servers/${props.serverId}/st-default-password`, {
      password: password.value,
    })
    if (apiError.value) return false
  }

  snapshot()
  return true
}

function discard() {
  authMode.value = origAuthMode.value
  username.value = origUsername.value
  password.value = origPassword.value
  proxyEnabled.value = origProxyEnabled.value
  gitBranch.value = origGitBranch.value
}

async function doSwitchVersion() {
  if (switchingVersion.value || !versionChanged.value) return
  const ok = await confirm({
    title: t('serverSettings.switchVersionTitle'),
    message: t('serverSettings.switchVersionMessage', { version: gitBranch.value }),
    confirmText: t('serverSettings.switchVersionConfirm'),
  })
  if (!ok) return
  switchingVersion.value = true
  try {
    if (!(await save())) return
    await post(`/api/user/servers/${props.serverId}/reinstall`, { force: false })
    if (apiError.value) return
    toast(t('serverSettings.switchVersionStarted'), 'success')
    await reloadServer()
    router.push({ name: 'server-console', params: { id: props.serverId } })
  } catch {
    toast(t('serverSettings.switchVersionFailed'), 'error')
  } finally {
    switchingVersion.value = false
  }
}

async function doUpdate() {
  if (updating.value) return
  const ok = await confirm({
    title: t('serverSettings.updateTitle'),
    message: t('serverSettings.updateMessage'),
    confirmText: t('serverSettings.updateConfirm'),
  })
  if (!ok) return
  updating.value = true
  try {
    // "更新到最新 release" 始终拉 release，无论下拉当前选什么。
    gitBranch.value = 'release'
    if (!(await save())) return
    await post(`/api/user/servers/${props.serverId}/reinstall`, { force: false })
    if (apiError.value) return
    toast(t('serverSettings.updateStarted'), 'success')
    await reloadServer()
    router.push({ name: 'server-console', params: { id: props.serverId } })
  } catch {
    toast(t('serverSettings.updateFailed'), 'error')
  } finally {
    updating.value = false
  }
}

async function doReinstall() {
  if (reinstalling.value) return
  const ok = await confirm({
    title: t('serverSettings.reinstallTitle'),
    message: t('serverSettings.reinstallMessage'),
    variant: 'danger',
    confirmText: t('serverSettings.reinstallConfirm'),
  })
  if (!ok) return
  reinstalling.value = true
  try {
    if (isDirty.value && !(await save())) return
    await post(`/api/user/servers/${props.serverId}/reinstall`, { force: true })
    if (apiError.value) return
    toast(t('serverSettings.reinstallStarted'), 'success')
    await reloadServer()
    router.push({ name: 'server-console', params: { id: props.serverId } })
  } catch {
    toast(t('serverSettings.reinstallFailed'), 'error')
  } finally {
    reinstalling.value = false
  }
}

// Short, already-localised error labels for the parent DirtyBar. Reactive;
// auto-unwraps to string[] when accessed via a template ref.
const validationErrors = computed<string[]>(() =>
  [usernameError.value, passwordError.value].filter((s): s is string => !!s),
)

// Drop the generic on defineExpose: the EggSettingsExpose contract declares
// `validationErrors?: string[]` (Vue template refs auto-unwrap), but we pass
// the underlying ComputedRef here so reactivity survives the boundary.
defineExpose({ save, discard, validationErrors })
</script>

<template>
  <div class="st-panel">
    <BaseCard variant="bg2" class="st-card">
      <SectionHeader icon="lock" flush>{{ t('serverSettings.authSection') }}</SectionHeader>
      <p class="section-note">{{ t('serverSettings.pageDesc') }}</p>

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

      <FormField
        :label="t('serverSettings.username')"
        layout="horizontal"
        :error="!isMultiUser && username ? usernameError : ''"
      >
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

      <FormField layout="horizontal" :error="password ? passwordError : ''">
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
    </BaseCard>

    <!-- ─── LLM free quota (only when provisioned) ─── -->
    <BaseCard v-if="server?.llmEnabled" variant="bg2" class="st-card">
      <SectionHeader icon="smart_toy" flush>{{ t('serverSettings.llm.section') }}</SectionHeader>
      <p class="section-note">{{ t('serverSettings.llm.desc') }}</p>

      <!-- How-to hint (static, shown immediately) -->
      <div class="llm-hint">
        <MsIcon name="info" class="llm-hint__icon" />
        <div class="llm-hint__body">
          <p class="llm-hint__title">{{ t('serverSettings.llm.howtoTitle') }}</p>
          <ol class="llm-hint__steps">
            <li>{{ t('serverSettings.llm.step1') }}</li>
            <li>{{ t('serverSettings.llm.step2') }}</li>
            <li>{{ t('serverSettings.llm.step3') }}</li>
          </ol>
        </div>
      </div>

      <!-- Loading spinner while usage/connection data is fetched -->
      <div v-if="llmLoading" class="llm-loading">
        <Spinner size="md" />
      </div>

      <!-- Load failed -->
      <p v-else-if="llmLoadFailed" class="section-note section-note--danger">
        {{ t('serverSettings.llm.loadFailed') }}
      </p>

      <template v-else-if="llmUsage">
        <!-- Usage bar -->
        <div class="llm-usage">
          <div class="llm-usage__top">
            <span class="llm-usage__label">{{ t('serverSettings.llm.used') }}</span>
            <span class="llm-usage__val">{{ llmUsedPercent }}%</span>
          </div>
          <UsageBar :percent="llmUsedPercent" :height="8" />
          <span v-if="llmUsage.usageQueryFailed" class="llm-usage__stale">{{ t('serverSettings.llm.usageStale') }}</span>
          <span v-else class="llm-usage__reset">{{ t('serverSettings.llm.nextReset') }}: {{ fmtTime(llmUsage.nextResetAt) }}</span>
        </div>

        <!-- Connection details -->
        <FormField :label="t('serverSettings.llm.apiBaseUrl')" layout="horizontal">
          <SecretInput
            :modelValue="llmUsage.apiBaseUrl"
            :revealed="true"
            readonly
            copyable
            :toggleable="false"
          />
        </FormField>

        <FormField :label="t('serverSettings.llm.apiKey')" layout="horizontal">
          <SecretInput :modelValue="llmUsage.apiKey || ''" readonly copyable :toggleable="true" :masked-length="36" />
        </FormField>
      </template>
    </BaseCard>

    <BaseCard variant="bg2" class="st-card">
      <SectionHeader icon="compare_arrows" flush>{{ t('serverSettings.networkSection') }}</SectionHeader>
      <FormField layout="horizontal" keep-horizontal>
        <template #label>
          {{ t('serverSettings.apiProxy') }}
          <HelpTip :text="t('serverSettings.apiProxyTip')" />
        </template>
        <ToggleSwitch v-model="proxyEnabled" />
      </FormField>
    </BaseCard>

    <BaseCard variant="bg2" class="st-card">
      <SectionHeader icon="update" flush>{{ t('serverSettings.versionSection') }}</SectionHeader>
      <p class="section-note">{{ t('serverSettings.versionSectionDesc') }}</p>

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
          <BaseButton
            :loading="switchingVersion"
            :disabled="!versionChanged || updating"
            @click="doSwitchVersion"
          >
            <MsIcon name="swap_horiz" />
            {{ versionChanged ? t('serverSettings.switchVersionBtnTo', { version: gitBranch }) : t('serverSettings.switchVersionBtn') }}
          </BaseButton>
          <BaseButton
            :loading="updating"
            :disabled="switchingVersion"
            @click="doUpdate"
          >
            <MsIcon name="update" />
            {{ t('serverSettings.updateBtn') }}
          </BaseButton>
        </div>
      </FormField>
    </BaseCard>

    <BaseCard variant="bg2" class="st-card">
      <SectionHeader icon="warning" flush>{{ t('serverSettings.reinstallSection') }}</SectionHeader>
      <p class="section-note section-note--danger">{{ t('serverSettings.reinstallSectionDesc') }}</p>

      <FormField layout="horizontal">
        <template #label>&nbsp;</template>
        <div class="action-row">
          <BaseButton variant="danger" :loading="reinstalling" :disabled="updating || switchingVersion" @click="doReinstall">
            <MsIcon name="delete_forever" />
            {{ t('serverSettings.reinstallBtn') }}
          </BaseButton>
        </div>
      </FormField>
    </BaseCard>
  </div>
</template>

<style scoped>
.st-panel {
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.st-card {
  padding: var(--sp-2);
}

.section-note {
  margin: 0 0 var(--sp-3);
  font-size: .84rem;
  line-height: 1.5;
  color: var(--t2);
}

.section-note--danger {
  color: var(--red);
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

/* ─── LLM quota card ─── */
.llm-hint {
  display: flex;
  gap: var(--sp-2);
  padding: var(--sp-3);
  margin-bottom: var(--sp-3);
  background: color-mix(in srgb, var(--ac) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--ac) 25%, transparent);
  border-radius: var(--r-sm);
}

.llm-hint__icon {
  flex-shrink: 0;
  color: var(--ac);
  font-size: 1.1rem;
  margin-top: 1px;
}

.llm-hint__body {
  min-width: 0;
}

.llm-hint__title {
  margin: 0 0 var(--sp-1);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t1);
}

.llm-hint__steps {
  margin: 0;
  padding-left: 1.2em;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: .84rem;
  line-height: 1.5;
  color: var(--t2);
}

.llm-usage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}
.llm-loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-4) 0;
}.llm-usage__top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.llm-usage__label {
  font-size: var(--text-sm);
  color: var(--t3);
}

.llm-usage__val {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--t1);
  font-variant-numeric: tabular-nums;
}

.llm-usage__reset {
  font-size: .8rem;
  color: var(--t3);
}

.llm-usage__stale {
  font-size: .8rem;
  color: var(--amber, #f59e0b);
}
</style>
