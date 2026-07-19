<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthForm from '@/components/auth/AuthForm.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'
import AgreementCheckboxGroup from '@/components/agreements/AgreementCheckboxGroup.vue'

defineOptions({ name: 'RegisterPage' })

const route = useRoute()
const { t, te } = useI18n({ useScope: 'global' })

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const inviteCode = ref('')
const inviteState = ref<'idle' | 'checking' | 'valid' | 'invalid'>('idle')
let inviteTimer: ReturnType<typeof setTimeout> | null = null
let inviteAbort: AbortController | null = null
const loading = ref(false)
const error = ref('')
const success = ref('')
const allowRegistration = ref(true)
const agreementsDefaultChecked = ref(false)
const acceptedAgreements = ref<{ agreement_id: number; version: number }[]>([])
const allAgreementsAccepted = ref(false)

function translateApiText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return ''
  if (/^[a-z_]+\.[a-z_]+$/.test(value)) {
    const key = `common.apiErrors.${value}`
    if (te(key)) return t(key)
  }
  return value
}

const usernameError = computed(() => {
  if (!username.value) return ''
  if (!/^[A-Za-z0-9_.\-]{3,32}$/.test(username.value))
    return t('register.error.username_format')
  return ''
})
const emailError = computed(() => {
  if (!email.value) return ''
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value))
    return t('register.error.email_format')
  return ''
})
const passwordError = computed(() => {
  if (!password.value) return ''
  if (password.value.length < 8) return t('register.error.length')
  return ''
})
const confirmPasswordError = computed(() => {
  if (!confirmPassword.value) return ''
  if (confirmPassword.value !== password.value) return t('register.error.mismatch')
  return ''
})

const canSubmit = computed(() =>
  allowRegistration.value
  && !success.value
  && !!username.value
  && !!email.value
  && !!password.value
  && !!confirmPassword.value
  && !usernameError.value
  && !emailError.value
  && !passwordError.value
  && !confirmPasswordError.value
  && allAgreementsAccepted.value
  && !loading.value,
)

watch([username, email, password, confirmPassword], () => {
  if (!success.value) error.value = ''
})

onMounted(async () => {
  // Prefill the invite code from the URL so links of the form
  // `/#/register?invite=ABCD` work without any user effort. The probe is
  // triggered automatically by the watcher below.
  const fromQuery = String(route.query.invite || '').trim().toUpperCase()
  if (fromQuery) inviteCode.value = fromQuery
  try {
    const res = await fetch('/api/public/branding')
    if (res.ok) {
      const data = await res.json() as {
        allow_registration?: boolean
        agreements_default_checked?: boolean
      }
      if (data && data.allow_registration === false) {
        allowRegistration.value = false
      }
      if (data && data.agreements_default_checked === true) {
        agreementsDefaultChecked.value = true
      }
    }
  } catch { /* ignore */ }
})

watch(inviteCode, (value) => {
  if (inviteTimer) { clearTimeout(inviteTimer); inviteTimer = null }
  if (inviteAbort) { inviteAbort.abort(); inviteAbort = null }
  const code = value.trim().toUpperCase()
  if (!code) { inviteState.value = 'idle'; return }
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
})

onBeforeUnmount(() => {
  if (inviteTimer) clearTimeout(inviteTimer)
  if (inviteAbort) inviteAbort.abort()
})

async function handleSubmit() {
  // Reentrancy guard. The submit handler can be triggered twice in the
  // same tick when the user hits Enter inside the form: once via the
  // browser's native form submission, and again via any explicit
  // ``@keyup.enter`` handler. Without this check, both calls reach the
  // `await fetch(...)` line before ``loading`` has had a chance to
  // disable the button, and two POST /api/register requests go out
  // concurrently — producing duplicate verification emails and
  // racing the backend's per-email uniqueness checks.
  if (loading.value) return
  error.value = ''
  if (!username.value || !email.value || !password.value || !confirmPassword.value) {
    error.value = t('register.error.empty')
    return
  }
  if (usernameError.value) { error.value = usernameError.value; return }
  if (emailError.value) { error.value = emailError.value; return }
  if (passwordError.value) { error.value = passwordError.value; return }
  if (confirmPasswordError.value) { error.value = confirmPasswordError.value; return }

  loading.value = true
  try {
    const res = await fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value.trim(),
        username: username.value.trim(),
        password: password.value,
        ...(inviteCode.value.trim() ? { invite_code: inviteCode.value.trim().toUpperCase() } : {}),
        accepted_agreements: acceptedAgreements.value,
      }),
    })
    let data: { message?: string; detail?: string; error?: string } | null = null
    try { data = await res.json() } catch { data = null }

    if (res.ok) {
      success.value = t('register.success')
      password.value = ''
      confirmPassword.value = ''
      return
    }
    error.value = translateApiText(data?.detail || data?.error || data?.message)
      || t('register.error.failed')
  } catch {
    error.value = t('register.error.network')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthForm icon="person_add" :subtitle="t('register.subtitle')" footer-align="center" @submit="handleSubmit">
    <AlertBanner v-if="!allowRegistration" tone="warning" icon="block" dense>
      {{ t('common.apiErrors.register.disabled') }}
    </AlertBanner>

    <AlertBanner v-if="error" tone="danger" icon="error" dense>
      {{ error }}
    </AlertBanner>

    <AlertBanner v-if="success" tone="success" icon="check_circle" dense>
      {{ success }}
    </AlertBanner>

    <template v-if="allowRegistration && !success">
      <FormField :label="t('register.username')" :error="usernameError || undefined">
        <BaseInput
          v-model="username"
          :placeholder="t('register.username_placeholder')"
          autocomplete="username"
        />
      </FormField>

      <FormField :label="t('register.email')" :error="emailError || undefined">
        <BaseInput
          v-model="email"
          type="email"
          :placeholder="t('register.email_placeholder')"
          autocomplete="email"
        />
      </FormField>

      <FormField :label="t('register.password')" :error="passwordError || undefined">
        <SecretInput
          v-model="password"
          :placeholder="t('register.password_placeholder')"
          :is-password="true"
          autocomplete="new-password"
        />
      </FormField>

      <FormField :label="t('register.confirmPassword')" :error="confirmPasswordError || undefined">
        <SecretInput
          v-model="confirmPassword"
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
    </template>

    <template v-if="allowRegistration && !success" #submit>
      <BaseButton
        type="submit"
        variant="primary"
        size="lg"
        :disabled="!canSubmit"
        style="width: 100%; justify-content: center"
      >
        <Spinner v-if="loading" size="sm" />
        <template v-else>
          <MsIcon name="person_add" size="sm" />
          {{ t('register.submit') }}
        </template>
      </BaseButton>
    </template>

    <template #footer>
      <span class="footer-hint">{{ t('register.back_prefix') }}</span>
      <RouterLink class="footer-link" :to="{ name: 'login' }">
        {{ t('register.back_link') }}
      </RouterLink>
    </template>
  </AuthForm>
</template>

<style scoped>
.footer-hint {
  color: var(--t3);
  font-size: .82rem;
}

.footer-link {
  color: var(--ac);
  font-size: .82rem;
  text-decoration: none;
  transition: text-decoration .15s ease;
}

.footer-link:hover {
  text-decoration: underline;
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
