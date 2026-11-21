<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { switchLanguage } from '@/i18n/vue-i18n'
import { backendToFrontendLocale } from '@/i18n/locale-map'
import { useAppStore } from '@/stores/app'
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import { useToast } from '@/composables/useToast'
import { useCodeCooldown } from '@/composables/useCodeCooldown'
import {
  isValidEmail,
  isValidUsername,
  isValidVerificationCode,
  passwordErrorKey,
} from '@/utils/username'
import {
  resolvePostAuthRoute,
  resolveSafeRedirect,
  useAuthModal,
  type AuthMode,
} from '@/composables/useAuthModal'
import { lockBodyScroll, unlockBodyScroll } from '@/components/ui/BaseModal.vue'
import AuthBrandHeader from '@/components/auth/AuthBrandHeader.vue'
import AuthStatusView from '@/components/auth/AuthStatusView.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import VerificationCodeInput from '@/components/form/VerificationCodeInput.vue'
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
const { toast } = useToast()
const app = useAppStore()
const { open, mode, inviteCode, switchMode, closeAuth, consumeSuccessHandler } = useAuthModal()

const modalOpen = computed({
  get: () => open.value,
  set: (v) => {
    if (!v) closeAuth()
    else open.value = true
  },
})

const dialogRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const inviteFieldRef = ref<HTMLElement | null>(null)
const hasBodyLock = ref(false)
const mouseDownOnOverlay = ref(false)
const bodyScrolled = ref(false)

const loading = ref(false)
const sendingCode = ref(false)
const codeCooldown = useCodeCooldown(60)
let codeRequestSeq = 0

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
const regCode = ref('')
const regPassword = ref('')
const regConfirmPassword = ref('')
const inviteExpanded = ref(false)
const inviteState = ref<'idle' | 'checking' | 'valid' | 'invalid'>('idle')
let inviteTimer: ReturnType<typeof setTimeout> | null = null
let inviteAbort: AbortController | null = null
const regError = ref('')
const acceptedAgreements = ref<{ agreement_id: number; version: number }[]>([])
const allAgreementsAccepted = ref(false)

// Forgot-password state (same-page reset with 6-digit code)
const forgotEmail = ref('')
const forgotCode = ref('')
const forgotNewPassword = ref('')
const forgotConfirmPassword = ref('')
const forgotError = ref('')
const forgotDone = ref(false)

const isStatusOnly = computed(
  () => (mode.value === 'register' && registrationDisabled.value)
    || (mode.value === 'forgot-password' && forgotDone.value),
)

const showTopBack = computed(
  () => !isStatusOnly.value && mode.value === 'forgot-password',
)

const brandIcon = computed(() => {
  if (mode.value === 'register') return 'person_add'
  if (mode.value === 'forgot-password') return 'key'
  return 'dns'
})

const headerSubtitle = computed(() => {
  if (isStatusOnly.value) return ''
  if (mode.value === 'register') return t('register.subtitle')
  if (mode.value === 'forgot-password') return t('forgotPassword.subtitle')
  return ''
})

const dialogAriaLabel = computed(() => {
  if (mode.value === 'register') return t('register.submit')
  if (mode.value === 'forgot-password') return t('forgotPassword.subtitle')
  return t('login.submit')
})

const usernameError = computed(() => {
  const v = regUsername.value.trim()
  if (!v) return ''
  return isValidUsername(v) ? '' : t('register.error.username_format')
})
const emailError = computed(() => {
  const v = regEmail.value.trim()
  if (!v) return ''
  return isValidEmail(v) ? '' : t('register.error.email_format')
})
const regCodeError = computed(() => {
  const v = regCode.value.trim()
  if (!v) return ''
  return isValidVerificationCode(v) ? '' : t('common.verificationCode.invalid')
})
const passwordError = computed(() => {
  const kind = passwordErrorKey(regPassword.value)
  return kind ? t(`common.passwordValidation.${kind}`) : ''
})
const confirmPasswordError = computed(() => {
  if (!regConfirmPassword.value) return ''
  if (regConfirmPassword.value !== regPassword.value) return t('register.error.mismatch')
  return ''
})

const forgotEmailError = computed(() => {
  const v = forgotEmail.value.trim()
  if (!v) return ''
  return isValidEmail(v) ? '' : t('register.error.email_format')
})
const forgotCodeError = computed(() => {
  const v = forgotCode.value.trim()
  if (!v) return ''
  return isValidVerificationCode(v) ? '' : t('common.verificationCode.invalid')
})
const forgotPasswordError = computed(() => {
  const kind = passwordErrorKey(forgotNewPassword.value)
  return kind ? t(`common.passwordValidation.${kind}`) : ''
})
const forgotConfirmPasswordError = computed(() => {
  if (!forgotConfirmPassword.value) return ''
  if (forgotConfirmPassword.value !== forgotNewPassword.value) return t('forgotPassword.error.mismatch')
  return ''
})

const canSendRegCode = computed(() =>
  !loading.value
  && !sendingCode.value
  && codeCooldown.remaining.value === 0
  && !registrationDisabled.value
  && !!regEmail.value.trim()
  && !emailError.value,
)

const canSendForgotCode = computed(() =>
  !loading.value
  && !sendingCode.value
  && codeCooldown.remaining.value === 0
  && !!forgotEmail.value.trim()
  && !forgotEmailError.value,
)

const canSubmitRegister = computed(() =>
  !registrationDisabled.value
  && !!regUsername.value.trim()
  && !!regEmail.value.trim()
  && !!regCode.value.trim()
  && !!regPassword.value
  && !!regConfirmPassword.value
  && !usernameError.value
  && !emailError.value
  && !regCodeError.value
  && !passwordError.value
  && !confirmPasswordError.value
  && allAgreementsAccepted.value
  && !loading.value,
)

const canSubmitForgot = computed(() =>
  !forgotDone.value
  && !!forgotEmail.value.trim()
  && !!forgotCode.value.trim()
  && !!forgotNewPassword.value
  && !!forgotConfirmPassword.value
  && !forgotEmailError.value
  && !forgotCodeError.value
  && !forgotPasswordError.value
  && !forgotConfirmPasswordError.value
  && !loading.value,
)

function resetCodeState() {
  codeRequestSeq += 1
  sendingCode.value = false
  codeCooldown.reset()
}

function clearMessages() {
  loginError.value = ''
  regError.value = ''
  forgotError.value = ''
  forgotDone.value = false
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

function expandInvite() {
  inviteExpanded.value = true
  nextTick(() => {
    inviteFieldRef.value?.querySelector<HTMLInputElement>('input')?.focus()
  })
}

function closeModal() {
  if (loading.value) return
  modalOpen.value = false
}

function onOverlayMousedown(e: MouseEvent) {
  mouseDownOnOverlay.value = e.target === e.currentTarget
}

function onOverlayClick(e: MouseEvent) {
  if (e.target === e.currentTarget && mouseDownOnOverlay.value && !loading.value) {
    closeModal()
  }
  mouseDownOnOverlay.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !loading.value) {
    e.stopPropagation()
    closeModal()
  }
}

function onBodyScroll() {
  bodyScrolled.value = (bodyRef.value?.scrollTop ?? 0) > 2
}

watch(open, (isOpen) => {
  if (isOpen) {
    if (!hasBodyLock.value) {
      lockBodyScroll()
      hasBodyLock.value = true
    }
    bodyScrolled.value = false
    clearMessages()
    void app.loadBranding()
    if (inviteCode.value.trim()) {
      inviteExpanded.value = true
    }
    if (mode.value === 'register' && inviteCode.value) {
      scheduleInviteCheck(inviteCode.value)
    }
    nextTick(() => {
      dialogRef.value?.focus()
    })
  } else {
    if (hasBodyLock.value) {
      unlockBodyScroll()
      hasBodyLock.value = false
    }
    bodyScrolled.value = false
    resetCodeState()
    loginPassword.value = ''
    regCode.value = ''
    regPassword.value = ''
    regConfirmPassword.value = ''
    forgotCode.value = ''
    forgotNewPassword.value = ''
    forgotConfirmPassword.value = ''
    acceptedAgreements.value = []
    allAgreementsAccepted.value = false
    if (!inviteCode.value.trim()) {
      inviteExpanded.value = false
    }
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
  resetCodeState()
  clearMessages()
  regCode.value = ''
  forgotCode.value = ''
  forgotNewPassword.value = ''
  forgotConfirmPassword.value = ''
  if (open.value && nextMode === 'register') {
    if (inviteCode.value.trim()) inviteExpanded.value = true
    scheduleInviteCheck(inviteCode.value)
  }
})

watch(inviteCode, (value) => {
  if (value.trim()) inviteExpanded.value = true
  if (!open.value || mode.value !== 'register') return
  scheduleInviteCheck(value)
})

watch([regUsername, regEmail, regCode, regPassword, regConfirmPassword], () => {
  regError.value = ''
})

watch([forgotEmail, forgotCode, forgotNewPassword, forgotConfirmPassword], () => {
  if (!forgotDone.value) forgotError.value = ''
})

onBeforeUnmount(() => {
  if (hasBodyLock.value) {
    unlockBodyScroll()
    hasBodyLock.value = false
  }
  clearInviteCheck()
})

function goMode(target: AuthMode) {
  if (loading.value || mode.value === target) return
  if (mode.value === 'login') {
    const typed = loginUsername.value.trim()
    if (typed.includes('@')) {
      if (target === 'register' && !regEmail.value.trim()) regEmail.value = typed
      if (target === 'forgot-password' && !forgotEmail.value.trim()) forgotEmail.value = typed
    }
  }
  switchMode(target)
  bodyScrolled.value = false
  nextTick(() => {
    bodyRef.value?.scrollTo({ top: 0 })
  })
}

async function finishAuthSuccess(data: {
  ok: boolean
  username: string
  is_admin: boolean
  has_owned_server: boolean
  language: string
}) {
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
}

async function sendRegisterCode() {
  if (!canSendRegCode.value) return
  const seq = ++codeRequestSeq
  const cleanEmail = regEmail.value.trim().toLowerCase()
  sendingCode.value = true
  regError.value = ''
  try {
    await fetchApi('/api/register/code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: cleanEmail }),
    })
    if (seq !== codeRequestSeq) return
    codeCooldown.start(60)
    toast(t('common.verificationCode.sent'), 'success')
  } catch (failure) {
    if (seq !== codeRequestSeq) return
    regError.value = apiErrorMessage(failure)
  } finally {
    if (seq === codeRequestSeq) {
      sendingCode.value = false
    }
  }
}

async function sendForgotCode() {
  if (!canSendForgotCode.value) return
  const seq = ++codeRequestSeq
  const cleanEmail = forgotEmail.value.trim().toLowerCase()
  sendingCode.value = true
  forgotError.value = ''
  try {
    await fetchApi('/api/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: cleanEmail }),
    })
    if (seq !== codeRequestSeq) return
    codeCooldown.start(60)
    toast(t('common.verificationCode.resetSent'), 'success')
  } catch (failure) {
    if (seq !== codeRequestSeq) return
    forgotError.value = apiErrorMessage(failure)
  } finally {
    if (seq === codeRequestSeq) {
      sendingCode.value = false
    }
  }
}

async function handleLogin() {
  if (loading.value) return
  loginError.value = ''
  const username = loginUsername.value.trim()
  if (!username || !loginPassword.value) {
    loginError.value = t('login.error.empty')
    return
  }

  loading.value = true
  try {
    const res = await fetchApi('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        password: loginPassword.value,
      }),
    })
    const data = await res.json()

    if (res.ok && data.ok) {
      await finishAuthSuccess(data)
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
  const username = regUsername.value.trim()
  const email = regEmail.value.trim().toLowerCase()
  const code = regCode.value.trim()
  if (!username || !email || !code || !regPassword.value || !regConfirmPassword.value) {
    regError.value = t('register.error.empty')
    return
  }
  if (usernameError.value) { regError.value = usernameError.value; return }
  if (emailError.value) { regError.value = emailError.value; return }
  if (regCodeError.value) { regError.value = regCodeError.value; return }
  if (passwordError.value) { regError.value = passwordError.value; return }
  if (confirmPasswordError.value) { regError.value = confirmPasswordError.value; return }

  loading.value = true
  try {
    const res = await fetchApi('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        username,
        code,
        password: regPassword.value,
        ...(inviteCode.value.trim() ? { invite_code: inviteCode.value.trim().toUpperCase() } : {}),
        accepted_agreements: acceptedAgreements.value,
      }),
    })
    const result = await res.json() as { auto_login?: boolean; username?: string; is_admin?: boolean }
    regCode.value = ''
    regPassword.value = ''
    regConfirmPassword.value = ''
    resetCodeState()

    if (result.auto_login) {
      const meRes = await fetchApi('/api/me')
      const meData = await meRes.json()
      toast(t('register.success_toast'), 'success')
      await finishAuthSuccess(meData)
      return
    }
    goMode('login')
  } catch (failure) {
    regError.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

async function handleForgotPassword() {
  if (loading.value) return
  forgotError.value = ''

  const email = forgotEmail.value.trim().toLowerCase()
  const code = forgotCode.value.trim()
  if (!email || !code || !forgotNewPassword.value || !forgotConfirmPassword.value) {
    forgotError.value = t('forgotPassword.error.empty')
    return
  }
  if (forgotEmailError.value) { forgotError.value = forgotEmailError.value; return }
  if (forgotCodeError.value) { forgotError.value = forgotCodeError.value; return }
  if (forgotPasswordError.value) { forgotError.value = forgotPasswordError.value; return }
  if (forgotConfirmPasswordError.value) { forgotError.value = forgotConfirmPasswordError.value; return }

  loading.value = true
  try {
    await fetchApi('/api/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        code,
        newPassword: forgotNewPassword.value,
      }),
    })
    forgotCode.value = ''
    forgotNewPassword.value = ''
    forgotConfirmPassword.value = ''
    resetCodeState()
    forgotDone.value = true
    bodyScrolled.value = false
    nextTick(() => { bodyRef.value?.scrollTo({ top: 0 }) })
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
  <Teleport to="body">
    <Transition name="auth-dialog">
      <div
        v-if="modalOpen"
        class="auth-overlay"
        tabindex="-1"
        @mousedown="onOverlayMousedown"
        @click="onOverlayClick"
        @keydown="onKeydown"
      >
        <div
          ref="dialogRef"
          class="auth-dialog"
          role="dialog"
          aria-modal="true"
          :aria-label="dialogAriaLabel"
          tabindex="-1"
        >
          <div class="auth-dialog__bar" :class="{ 'auth-dialog__bar--scrolled': bodyScrolled }">
            <button
              v-if="showTopBack"
              type="button"
              class="auth-nav-back"
              :disabled="loading"
              @click="goMode('login')"
            >
              <MsIcon name="arrow_back" size="sm" />
              <span>{{ t('forgotPassword.back') }}</span>
            </button>
            <button
              type="button"
              class="auth-close-btn"
              :disabled="loading"
              :aria-label="t('common.btn.close')"
              @click="closeModal"
            >
              <MsIcon name="close" />
            </button>
          </div>

          <div ref="bodyRef" class="auth-dialog__body" @scroll.passive="onBodyScroll">
            <div class="auth-dialog__inner">
              <AuthBrandHeader
                :icon="brandIcon"
                :subtitle="headerSubtitle || undefined"
                heading-tag="h2"
              />

              <!-- ── Status Views (Registration Closed / Password Reset Done) ── -->
              <AuthStatusView
                v-if="mode === 'register' && registrationDisabled"
                tone="warning"
                icon="block"
                :title="t('register.disabled_title')"
                :description="t('common.apiErrors.register.disabled')"
              >
                <template #actions>
                  <BaseButton variant="default" size="lg" @click="goMode('login')">
                    {{ t('register.back_link') }}
                  </BaseButton>
                </template>
              </AuthStatusView>

              <AuthStatusView
                v-else-if="mode === 'forgot-password' && forgotDone"
                tone="success"
                icon="check_circle"
                :title="t('forgotPassword.success_title')"
                :description="t('forgotPassword.success')"
              >
                <template #actions>
                  <BaseButton variant="primary" size="lg" @click="goMode('login')">
                    {{ t('forgotPassword.back') }}
                  </BaseButton>
                </template>
              </AuthStatusView>

              <!-- ── Interactive Forms ── -->
              <form v-else class="auth-modal-form" @submit.prevent="handleSubmit">
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

                  <template v-if="allowRegistration">
                    <div class="auth-divider">
                      <span>{{ t('login.register_prefix') }}</span>
                    </div>

                    <button
                      type="button"
                      class="auth-register-cta"
                      :disabled="loading"
                      @click="goMode('register')"
                    >
                      <MsIcon name="person_add" size="sm" color="none" />
                      <span>{{ t('login.register_link') }}</span>
                    </button>
                  </template>
                </template>

                <!-- ── Register ── -->
                <template v-else-if="mode === 'register'">
                  <AlertBanner v-if="regError" tone="danger" icon="error" dense>
                    {{ regError }}
                  </AlertBanner>

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
                      :disabled="loading || sendingCode"
                    />
                  </FormField>

                  <FormField :label="t('common.verificationCode.label')" :error="regCodeError || undefined">
                    <VerificationCodeInput
                      v-model="regCode"
                      :disabled="loading"
                      :sending="sendingCode"
                      :can-send="canSendRegCode"
                      :cooldown-seconds="codeCooldown.remaining.value"
                      @send="sendRegisterCode"
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

                  <div v-if="!inviteExpanded" class="invite-disclosure">
                    <button
                      type="button"
                      class="invite-toggle"
                      @click="expandInvite"
                    >
                      <span>{{ t('billing.register.inviteCodeLabel') }}</span>
                      <MsIcon name="expand_more" size="xs" color="none" />
                    </button>
                  </div>

                  <div v-else ref="inviteFieldRef">
                    <FormField :label="t('billing.register.inviteCodeLabel')">
                      <template #label-right>
                        <span v-if="inviteState !== 'idle'" class="invite-hint" :class="`invite-${inviteState}`">
                          <Spinner v-if="inviteState === 'checking'" size="sm" />
                          <MsIcon v-else-if="inviteState === 'valid'" name="check_circle" size="sm" />
                          <MsIcon v-else name="error" size="sm" />
                          <span v-if="inviteState === 'valid'">{{ t('billing.register.inviteValid') }}</span>
                          <span v-else-if="inviteState === 'invalid'">{{ t('billing.register.inviteInvalid') }}</span>
                        </span>
                        <button
                          v-else
                          type="button"
                          class="invite-collapse-btn"
                          :aria-label="t('common.btn.close')"
                          @click="inviteExpanded = false"
                        >
                          <MsIcon name="expand_less" size="xs" color="none" />
                        </button>
                      </template>
                      <BaseInput
                        v-model="inviteCode"
                        :placeholder="t('billing.register.inviteCodePlaceholder')"
                        autocomplete="off"
                        @input="inviteCode = inviteCode.toUpperCase()"
                      />
                    </FormField>
                  </div>

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

                  <div class="auth-divider">
                    <span>{{ t('register.back_prefix') }}</span>
                  </div>

                  <BaseButton
                    type="button"
                    variant="default"
                    size="lg"
                    :disabled="loading"
                    class="auth-submit-btn"
                    @click="goMode('login')"
                  >
                    {{ t('register.back_link') }}
                  </BaseButton>
                </template>

                <!-- ── Forgot password ── -->
                <template v-else>
                  <AlertBanner v-if="forgotError" tone="danger" icon="error" dense>
                    {{ forgotError }}
                  </AlertBanner>

                  <FormField :label="t('forgotPassword.email')" :error="forgotEmailError || undefined">
                    <BaseInput
                      v-model="forgotEmail"
                      type="email"
                      :placeholder="t('forgotPassword.email_placeholder')"
                      autocomplete="email"
                      :disabled="loading || sendingCode"
                    />
                  </FormField>

                  <FormField :label="t('common.verificationCode.label')" :error="forgotCodeError || undefined">
                    <VerificationCodeInput
                      v-model="forgotCode"
                      :disabled="loading"
                      :sending="sendingCode"
                      :can-send="canSendForgotCode"
                      :cooldown-seconds="codeCooldown.remaining.value"
                      @send="sendForgotCode"
                    />
                  </FormField>

                  <FormField :label="t('forgotPassword.newPassword')" :error="forgotPasswordError || undefined">
                    <SecretInput
                      v-model="forgotNewPassword"
                      :placeholder="t('forgotPassword.newPassword_placeholder')"
                      :is-password="true"
                      autocomplete="new-password"
                    />
                  </FormField>

                  <FormField :label="t('forgotPassword.confirmPassword')" :error="forgotConfirmPasswordError || undefined">
                    <SecretInput
                      v-model="forgotConfirmPassword"
                      :placeholder="t('forgotPassword.confirmPassword_placeholder')"
                      :is-password="true"
                      autocomplete="new-password"
                    />
                  </FormField>

                  <BaseButton
                    type="submit"
                    variant="primary"
                    size="lg"
                    :disabled="!canSubmitForgot"
                    class="auth-submit-btn"
                  >
                    <Spinner v-if="loading" size="sm" />
                    <template v-else>
                      <MsIcon name="key" size="sm" />
                      {{ t('forgotPassword.submit') }}
                    </template>
                  </BaseButton>
                </template>
              </form>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* z-index 950 sits above AppSidebar (50) & PageHeader (40),
   and below BaseModal (1000, used by AgreementViewer) & ToastContainer (10000). */
.auth-overlay {
  position: fixed;
  inset: 0;
  z-index: 950;
  background: var(--overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
}

:global([data-theme="light"]) .auth-overlay {
  background: var(--overlay-light);
}

.auth-dialog {
  width: 100%;
  max-width: 420px;
  max-height: min(90dvh, 780px);
  display: flex;
  flex-direction: column;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r);
  box-shadow: var(--sh);
  outline: none;
  overflow: hidden;
}

.auth-dialog__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 46px;
  padding: 10px 14px 6px;
  border-bottom: 1px solid transparent;
  flex-shrink: 0;
  transition: border-color .15s ease;
}

.auth-dialog__bar--scrolled {
  border-bottom-color: var(--bd);
}

.auth-nav-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--t2);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
  transition: color .15s ease, background .15s ease;
}

.auth-nav-back:hover:not(:disabled) {
  color: var(--t1);
  background: color-mix(in srgb, var(--t1) 6%, transparent);
}

.auth-nav-back:disabled,
.auth-close-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.auth-close-btn {
  margin-left: auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--t2);
  cursor: pointer;
  transition: color .15s ease, background .15s ease;
}

.auth-close-btn:hover:not(:disabled) {
  color: var(--t1);
  background: color-mix(in srgb, var(--t1) 6%, transparent);
}

.auth-dialog__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: var(--sp-2) var(--sp-6) var(--sp-6);
}

.auth-dialog__inner {
  width: 100%;
  max-width: 400px;
  margin: 0 auto;
}

/* ── Form & Mode Guidance ── */
.auth-modal-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.auth-modal-form :deep(.form-field) {
  margin-bottom: 0;
}

.auth-submit-btn {
  width: 100%;
  justify-content: center;
}

.auth-divider {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: 2px 0 calc(var(--sp-1) * -1);
  color: var(--t3);
  font-size: var(--text-xs);
}

.auth-divider::before,
.auth-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--bd);
}

.auth-register-cta {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  box-sizing: border-box;
  padding: var(--btn-py-lg, 10px) var(--btn-px-lg, 20px);
  border-radius: var(--rs);
  border: 1px solid color-mix(in srgb, var(--ac) 42%, var(--bd));
  background: color-mix(in srgb, var(--ac) 8%, var(--bg3));
  color: var(--ac);
  font-family: inherit;
  font-size: var(--btn-font-lg, var(--text-md));
  font-weight: 600;
  cursor: pointer;
  transition: background .15s ease, border-color .15s ease, color .15s ease, opacity .15s ease;
}

.auth-register-cta:hover:not(:disabled) {
  background: color-mix(in srgb, var(--ac) 16%, var(--bg3));
  border-color: var(--ac);
}

.auth-register-cta:disabled {
  opacity: .4;
  cursor: not-allowed;
}

.auth-register-cta:focus-visible {
  outline: 2px solid var(--ac);
  outline-offset: 2px;
}

.auth-nav-back:focus-visible,
.auth-close-btn:focus-visible,
.invite-toggle:focus-visible,
.invite-collapse-btn:focus-visible {
  outline: 2px solid var(--ac);
  outline-offset: -2px;
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

/* ── Collapsible Invite Code ── */
.invite-disclosure {
  display: flex;
  align-items: center;
}

.invite-toggle {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 0;
  border: 0;
  border-radius: var(--r-xs);
  background: none;
  color: var(--t2);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
  transition: color .15s ease;
}

.invite-toggle:hover {
  color: var(--ac);
}

.invite-collapse-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: 0;
  border-radius: var(--r-xs);
  background: none;
  color: var(--t3);
  cursor: pointer;
  transition: color .15s ease;
}

.invite-collapse-btn:hover {
  color: var(--t1);
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

/* ── Transitions (matches BaseModal desktop fade/scale, full-screen fade on mobile) ── */
.auth-dialog-enter-active,
.auth-dialog-leave-active {
  transition: opacity .18s ease;
}

.auth-dialog-enter-active .auth-dialog,
.auth-dialog-leave-active .auth-dialog {
  transition: transform .18s ease, opacity .18s ease;
}

.auth-dialog-enter-from,
.auth-dialog-leave-to {
  opacity: 0;
}

.auth-dialog-enter-from .auth-dialog,
.auth-dialog-leave-to .auth-dialog {
  opacity: 0;
  transform: scale(.96);
}

/* ── Mobile: Full-screen Immersive Auth View (unified with AuthShell) ── */
@media (max-width: 768px) {
  .auth-overlay,
  :global([data-theme="light"]) .auth-overlay {
    padding: 0;
    background: var(--bg2);
    align-items: stretch;
  }

  .auth-dialog {
    max-width: none;
    max-height: none;
    width: 100%;
    height: 100%;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    background: var(--bg2);
  }

  .auth-dialog__bar {
    min-height: calc(52px + env(safe-area-inset-top, 0px));
    padding: calc(10px + env(safe-area-inset-top, 0px)) var(--sp-4) var(--sp-2);
  }

  .auth-dialog__body {
    padding: var(--sp-2) var(--sp-5) calc(var(--sp-6) + env(safe-area-inset-bottom, 0px));
    -webkit-overflow-scrolling: touch;
    touch-action: pan-y;
  }

  .auth-dialog-enter-from .auth-dialog,
  .auth-dialog-leave-to .auth-dialog {
    transform: translateY(8px);
  }
}
</style>
