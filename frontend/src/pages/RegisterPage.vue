<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthForm from '@/components/auth/AuthForm.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'RegisterPage' })

const router = useRouter()
const { t, te } = useI18n({ useScope: 'global' })

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')
const allowRegistration = ref(true)

let redirectTimer: ReturnType<typeof setTimeout> | null = null

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
  && !loading.value,
)

watch([username, email, password, confirmPassword], () => {
  if (!success.value) error.value = ''
})

onMounted(async () => {
  try {
    const res = await fetch('/api/public/branding')
    if (res.ok) {
      const data = await res.json() as { allow_registration?: boolean }
      if (data && data.allow_registration === false) {
        allowRegistration.value = false
      }
    }
  } catch { /* ignore */ }
})

onBeforeUnmount(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
})

function queueRedirect() {
  if (redirectTimer) clearTimeout(redirectTimer)
  redirectTimer = setTimeout(() => {
    router.replace({ name: 'login' })
  }, 5000)
}

async function handleSubmit() {
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
      }),
    })
    let data: { message?: string; detail?: string; error?: string } | null = null
    try { data = await res.json() } catch { data = null }

    if (res.ok) {
      success.value = t('register.success')
      password.value = ''
      confirmPassword.value = ''
      queueRedirect()
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
          @keyup.enter="handleSubmit"
        />
      </FormField>
    </template>

    <p v-if="success" class="register-hint">{{ t('register.redirecting') }}</p>

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
      <RouterLink class="register-link" :to="{ name: 'login' }">
        {{ t('register.back') }}
      </RouterLink>
    </template>
  </AuthForm>
</template>

<style scoped>
.register-link {
  color: var(--t2);
  font-size: .82rem;
  text-decoration: none;
  transition: color .15s ease;
}

.register-link:hover {
  color: var(--t1);
}

.register-hint {
  color: var(--t3);
  font-size: .78rem;
  text-align: center;
  margin-top: calc(var(--sp-2) * -1);
}
</style>
