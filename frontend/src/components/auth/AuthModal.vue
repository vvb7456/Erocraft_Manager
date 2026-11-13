<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { switchLanguage } from '@/i18n/vue-i18n'
import { backendToFrontendLocale } from '@/i18n/locale-map'
import { useAppStore } from '@/stores/app'
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import {
  resolvePostAuthRoute,
  resolveSafeRedirect,
  useAuthModal,
  type AuthMode,
} from '@/composables/useAuthModal'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AgreementCheckboxGroup from '@/components/agreements/AgreementCheckboxGroup.vue'

defineOptions({ name: 'AuthModal' })

const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: 'global' })
const app = useAppStore()
const { open, mode, inviteCode, switchMode, closeAuth, consumeSuccessHandler } = useAuthModal()

const modalOpen = computed({
  get: () => open.value,
  set: (v) => {
    if (!v) closeAuth()
    else open.value = true
  },
})

const loading = ref(false)
const allowRegistration = computed(() => app.branding.allowRegistration)
const registrationDisabled = computed(() => app.brandingLoaded && !app.branding.allowRegistration)
const agreementsDefaultChecked = computed(() => app.branding.agreementsDefaultChecked)

// Login state
const loginUsername = ref('')
const loginPassword = ref('')
const loginError = ref('')

// Register state
const regUsername = ref('')
const regEmail = ref('')
const regPassword = ref('')
const regConfirmPassword = ref('')
const inviteState = ref<'idle' | 'checking' | 'valid' | 'invalid'>('idle')
let inviteTimer: ReturnType<typeof setTimeout> | null = null
let inviteAbort: AbortController | null = null
const regError = ref('')
const regSuccess = ref('')
const acceptedAgreements = ref<{ agreement_id: number; version: number }[]>([])
const allAgreementsAccepted = ref(false)

// Forgot-password state
const forgotEmail = ref('')
const forgotError = ref('')
const forgotSuccess = ref('')

const modalTitle = computed(() => {
  if (mode.value === 'register') return t('register.subtitle')
  if (mode.value === 'forgot-password') return t('forgotPassword.subtitle')
  return t('login.submit')
})

const modalIcon = computed(() => {
  if (mode.value === 'register') return 'person_add'
  if (mode.value === 'forgot-password') return 'mail'
  return 'login'
})

const usernameError = computed(() => {
  if (!regUsername.value) return ''
  if (!/^[A-Za-z0-9_.\-]{3,32}$/.test(regUsername.value)) {
    return t('register.error.username_format')
  }
  return ''
})
const emailError = computed(() => {
  if (!regEmail.value) return ''
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(regEmail.value)) {
    return t('register.error.email_format')
  }
  return ''
})
const passwordError = computed(() => {
  if (!regPassword.value) return ''
  if (regPassword.value.length < 8) return t('register.error.length')
  return ''
})
const confirmPasswordError = computed(() => {
  if (!regConfirmPassword.value) return ''
  if (regConfirmPassword.value !== regPassword.value) return t('register.error.mismatch')
  return ''
})

const canSubmitRegister = computed(() =>
  !registrationDisabled.value
  && !regSuccess.value
  && !!regUsername.value
  && !!regEmail.value
  && !!regPassword.value
  && !!regConfirmPassword.value
  && !usernameError.value
  && !emailError.value
  && !passwordError.value
  && !confirmPasswordError.value
  && allAgreementsAccepted.value
  && !loading.value,
)

function clearMessages() {
  loginError.value = ''
  regError.value = ''
  regSuccess.value = ''
  forgotError.value = ''
  forgotSuccess.value = ''
}

function clearInviteCheck() {
  if (inviteTimer) { clearTimeout(inviteTimer); inviteTimer = null }
  if (inviteAbort) { inviteAbort.abort(); inviteAbort = null }
}

function scheduleInviteCheck(raw: string) {
  clearInviteCheck()
  const code = raw.trim().toUpperCase()
  if (!code) {
    inviteState.value = 'idle'
    return
  }
  inviteState.value = 'checking'
  inviteTimer = setTimeout(async () => {
    inviteAbort = new AbortController()
    try {
      const res = await fetch(`/api/invite/check?code=${encodeURIComponent(code)}`, {
        signal: inviteAbort.signal,
      })
      if (!res.ok) { inviteState.value = 'invalid'; return }
      const data = await res.json().catch(() => null) as { valid?: boolean } | null
      inviteState.value = data?.valid ? 'valid' : 'invalid'
    } catch (err) {
      if ((err as DOMException)?.name === 'AbortError') return
      inviteState.value = 'invalid'
    }
  }, 350)
}

watch(open, (isOpen) => {
  if (isOpen) {
    clearMessages()
    void app.loadBranding()
    if (mode.value === 'register' && inviteCode.value) {
      scheduleInviteCheck(inviteCode.value)
    }
  } else {
    loginPassword.value = ''
    regPassword.value = ''
    regConfirmPassword.value = ''
    acceptedAgreements.value = []
    allAgreementsAccepted.value = false
    clearInviteCheck()
  }
}, { immediate: true })

watch(
  () => [Boolean(route.meta.public), Boolean(app.sessionUser)] as const,
  ([isPublic, isLoggedIn]) => {
    if ((isPublic || isLoggedIn) && open.value) {
      closeAuth()
    }
  },
)

watch(mode, (nextMode) => {
  clearMessages()
  if (open.value && nextMode === 'register') {
    scheduleInviteCheck(inviteCode.value)
  }
})

watch(inviteCode, (value) => {
  if (!open.value || mode.value !== 'register') return
  scheduleInviteCheck(value)
})

watch([regUsername, regEmail, regPassword, regConfirmPassword], () => {
  if (!regSuccess.value) regError.value = ''
})

watch(forgotEmail, () => {
  forgotError.value = ''
  forgotSuccess.value = ''
})

onBeforeUnmount(clearInviteCheck)

function goMode(target: AuthMode) {
  if (loading.value) return
  switchMode(target)
}

async function handleLogin() {
  // Guard against double-dispatch when Enter triggers both native submit and key handlers.
  if (loading.value) return
  loginError.value = ''
  if (!loginUsername.value || !loginPassword.value) {
    loginError.value = t('login.error.empty')
    return
  }

  loading.value = true
  try {
    const res = await fetchApi('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: loginUsername.value,
        password: loginPassword.value,
      }),
    })
    const data = await res.json()

    if (res.ok && data.ok) {
      const { redirect, onSuccess } = consumeSuccessHandler()
      app.setSessionUser(data)
      switchLanguage(backendToFrontendLocale(data.language))
      if (onSuccess) {
        onSuccess()
        return
      }
      const safeRedirect = resolveSafeRedirect(router, redirect)
      if (safeRedirect) {
        await router.push(safeRedirect)
        return
      }
      const target = resolvePostAuthRoute(data)
      if (router.currentRoute.value.name !== target.name) {
        await router.push(target)
      }
    } else {
      loginError.value = t('login.error.invalid')
    }
  } catch (failure) {
    loginError.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (loading.value) return
  regError.value = ''
  if (!regUsername.value || !regEmail.value || !regPassword.value || !regConfirmPassword.value) {
    regError.value = t('register.error.empty')
    return
  }
  if (usernameError.value) { regError.value = usernameError.value; return }
  if (emailError.value) { regError.value = emailError.value; return }
  if (passwordError.value) { regError.value = passwordError.value; return }
  if (confirmPasswordError.value) { regError.value = confirmPasswordError.value; return }

  loading.value = true
  try {
    await fetchApi('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: regEmail.value.trim(),
        username: regUsername.value.trim(),
        password: regPassword.value,
        ...(inviteCode.value.trim() ? { invite_code: inviteCode.value.trim().toUpperCase() } : {}),
        accepted_agreements: acceptedAgreements.value,
      }),
    })
    regSuccess.value = t('register.success')
    regPassword.value = ''
    regConfirmPassword.value = ''
  } catch (failure) {
    regError.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

async function handleForgotPassword() {
  if (loading.value) return
  forgotError.value = ''
  forgotSuccess.value = ''

  if (!forgotEmail.value.trim()) {
    forgotError.value = t('forgotPassword.error.empty')
    return
  }

  loading.value = true
  try {
    await fetchApi('/api/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: forgotEmail.value.trim(),
      }),
    })
    forgotSuccess.value = t('forgotPassword.success')
  } catch (failure) {
    forgotError.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

function handleSubmit() {
  if (mode.value === 'register') return handleRegister()
  if (mode.value === 'forgot-password') return handleForgotPassword()
  return handleLogin()
}
</script>

<template>
  <BaseModal
    v-model="modalOpen"
    :title="modalTitle"
    :icon="modalIcon"
    width="420px"
    :persistent="loading"
  >
    <form class="auth-modal-form" @submit.prevent="handleSubmit">
      <!-- ── Login ── -->
      <template v-if="mode === 'login'">
        <AlertBanner v-if="loginError" tone="danger" icon="error" dense>
          {{ loginError }}
        </AlertBanner>

        <FormField :label="t('login.username')">
          <BaseInput
            v-model="loginUsername"
            :placeholder="t('login.username_placeholder')"
            autocomplete="username"
          />
        </FormField>

        <FormField :label="t('login.password')">
          <template #label-right>
            <button type="button" class="auth-link" @click="goMode('forgot-password')">
              {{ t('login.forgot') }}
            </button>
          </template>
          <SecretInput
            v-model="loginPassword"
            :placeholder="t('login.password_placeholder')"
            :is-password="true"
            autocomplete="current-password"
          />
        </FormField>

        <BaseButton
          type="submit"
          variant="primary"
          size="lg"
          :disabled="loading"
          class="auth-submit-btn"
        >
          <Spinner v-if="loading" size="sm" />
          <template v-else>
            <MsIcon name="login" size="sm" />
            {{ t('login.submit') }}
          </template>
        </BaseButton>

        <div v-if="allowRegistration" class="auth-switch auth-switch--center">
          <span class="auth-hint">{{ t('login.register_prefix') }}</span>
          <button type="button" class="auth-link" @click="goMode('register')">
            {{ t('login.register_link') }}
          </button>
        </div>
      </template>

      <!-- ── Register ── -->
      <template v-else-if="mode === 'register'">
        <AlertBanner v-if="registrationDisabled" tone="warning" icon="block" dense>
          {{ t('common.apiErrors.register.disabled') }}
        </AlertBanner>

        <AlertBanner v-if="regError" tone="danger" icon="error" dense>
          {{ regError }}
        </AlertBanner>

        <AlertBanner v-if="regSuccess" tone="success" icon="check_circle" dense>
          {{ regSuccess }}
        </AlertBanner>

        <template v-if="!registrationDisabled && !regSuccess">
          <FormField :label="t('register.username')" :error="usernameError || undefined">
            <BaseInput
              v-model="regUsername"
              :placeholder="t('register.username_placeholder')"
              autocomplete="username"
            />
          </FormField>

          <FormField :label="t('register.email')" :error="emailError || undefined">
            <BaseInput
              v-model="regEmail"
              type="email"
              :placeholder="t('register.email_placeholder')"
              autocomplete="email"
            />
          </FormField>

          <FormField :label="t('register.password')" :error="passwordError || undefined">
            <SecretInput
              v-model="regPassword"
              :placeholder="t('register.password_placeholder')"
              :is-password="true"
              autocomplete="new-password"
            />
          </FormField>

          <FormField :label="t('register.confirmPassword')" :error="confirmPasswordError || undefined">
            <SecretInput
              v-model="regConfirmPassword"
              :placeholder="t('register.confirmPassword_placeholder')"
              :is-password="true"
              autocomplete="new-password"
            />
          </FormField>

          <FormField :label="t('billing.register.inviteCodeLabel')">
            <template #label-right>
              <span v-if="inviteState !== 'idle'" class="invite-hint" :class="`invite-${inviteState}`">
                <Spinner v-if="inviteState === 'checking'" size="sm" />
                <MsIcon v-else-if="inviteState === 'valid'" name="check_circle" size="sm" />
                <MsIcon v-else name="error" size="sm" />
                <span v-if="inviteState === 'valid'">{{ t('billing.register.inviteValid') }}</span>
                <span v-else-if="inviteState === 'invalid'">{{ t('billing.register.inviteInvalid') }}</span>
              </span>
            </template>
            <BaseInput
              v-model="inviteCode"
              :placeholder="t('billing.register.inviteCodePlaceholder')"
              autocomplete="off"
              @input="inviteCode = inviteCode.toUpperCase()"
            />
          </FormField>

          <AgreementCheckboxGroup
            v-model="acceptedAgreements"
            context="register"
            :default-checked="agreementsDefaultChecked"
            @update:all-accepted="allAgreementsAccepted = $event"
          />

          <BaseButton
            type="submit"
            variant="primary"
            size="lg"
            :disabled="!canSubmitRegister"
            class="auth-submit-btn"
          >
            <Spinner v-if="loading" size="sm" />
            <template v-else>
              <MsIcon name="person_add" size="sm" />
              {{ t('register.submit') }}
            </template>
          </BaseButton>
        </template>

        <div class="auth-switch auth-switch--center">
          <span class="auth-hint">{{ t('register.back_prefix') }}</span>
          <button type="button" class="auth-link" @click="goMode('login')">
            {{ t('register.back_link') }}
          </button>
        </div>
      </template>

      <!-- ── Forgot password ── -->
      <template v-else>
        <AlertBanner v-if="forgotError" tone="danger" icon="error" dense>
          {{ forgotError }}
        </AlertBanner>

        <AlertBanner v-if="forgotSuccess" tone="success" icon="check_circle" dense>
          {{ forgotSuccess }}
        </AlertBanner>

        <FormField :label="t('forgotPassword.email')">
          <BaseInput
            v-model="forgotEmail"
            type="email"
            :placeholder="t('forgotPassword.email_placeholder')"
            autocomplete="email"
          />
        </FormField>

        <BaseButton
          type="submit"
          variant="primary"
          size="lg"
          :disabled="loading"
          class="auth-submit-btn"
        >
          <Spinner v-if="loading" size="sm" />
          <template v-else>
            <MsIcon name="mail" size="sm" />
            {{ t('forgotPassword.submit') }}
          </template>
        </BaseButton>

        <div class="auth-switch auth-switch--center">
          <button type="button" class="auth-link auth-link--muted" @click="goMode('login')">
            {{ t('forgotPassword.back') }}
          </button>
        </div>
      </template>
    </form>
  </BaseModal>
</template>

<style scoped>
.auth-modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.auth-submit-btn {
  width: 100%;
  justify-content: center;
}

.auth-switch {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: calc(var(--sp-1) * -1);
}

.auth-switch--center {
  justify-content: center;
}

.auth-hint {
  color: var(--t3);
  font-size: .82rem;
}

.auth-link {
  border: 0;
  padding: 0;
  background: none;
  color: var(--ac);
  font: inherit;
  font-size: .82rem;
  cursor: pointer;
}

.auth-link:hover {
  text-decoration: underline;
}

.auth-link--muted {
  color: var(--t2);
  transition: color .15s ease;
}

.auth-link--muted:hover {
  color: var(--t1);
  text-decoration: none;
}

.invite-hint {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: .78rem;
  color: var(--t3);
}

.invite-hint.invite-valid {
  color: var(--green);
}

.invite-hint.invite-invalid {
  color: var(--red);
}
</style>
