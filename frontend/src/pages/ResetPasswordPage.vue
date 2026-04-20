<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthForm from '@/components/auth/AuthForm.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'ResetPasswordPage' })

const route = useRoute()
const router = useRouter()
const { t, te } = useI18n({ useScope: 'global' })

const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')

let redirectTimer: ReturnType<typeof setTimeout> | null = null

function translateApiText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return ''
  if (/^[a-z_]+\.[a-z_]+$/.test(value)) {
    const key = `common.apiErrors.${value}`
    if (te(key)) return t(key)
  }
  return value
}

const email = computed(() =>
  typeof route.query.email === 'string' ? route.query.email.trim() : '',
)
const token = computed(() =>
  typeof route.query.token === 'string' ? route.query.token.trim() : '',
)
const linkError = computed(() =>
  !email.value || !token.value ? t('resetPassword.error.invalidLink') : '',
)
const passwordLengthError = computed(() => {
  if (!newPassword.value) return ''
  if (newPassword.value.length < 8) return t('resetPassword.error.length')
  return ''
})
const confirmPasswordError = computed(() => {
  if (!confirmPassword.value) return ''
  if (confirmPassword.value !== newPassword.value) return t('resetPassword.error.mismatch')
  return ''
})
const canSubmit = computed(() =>
  !linkError.value
  && !success.value
  && !!newPassword.value
  && !!confirmPassword.value
  && !passwordLengthError.value
  && !confirmPasswordError.value
  && !loading.value,
)

watch([newPassword, confirmPassword], () => {
  if (!success.value) error.value = ''
})

function queueRedirect() {
  if (redirectTimer) clearTimeout(redirectTimer)
  redirectTimer = setTimeout(() => {
    router.replace({ name: 'login' })
  }, 3000)
}

async function handleSubmit() {
  error.value = ''

  if (linkError.value) {
    error.value = linkError.value
    return
  }
  if (!newPassword.value || !confirmPassword.value) {
    error.value = t('resetPassword.error.required')
    return
  }
  if (passwordLengthError.value) {
    error.value = passwordLengthError.value
    return
  }
  if (confirmPasswordError.value) {
    error.value = confirmPasswordError.value
    return
  }

  loading.value = true
  try {
    const res = await fetch('/api/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value,
        token: token.value,
        newPassword: newPassword.value,
      }),
    })

    let data: { message?: string; error?: string; detail?: string } | null = null
    try {
      data = await res.json() as { message?: string; error?: string; detail?: string }
    } catch {
      data = null
    }

    if (res.ok) {
      success.value = t('resetPassword.success')
      newPassword.value = ''
      confirmPassword.value = ''
      queueRedirect()
      return
    }

    error.value = translateApiText(data?.detail || data?.error || data?.message) || t('resetPassword.error.failed')
  } catch {
    error.value = t('resetPassword.error.network')
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
})
</script>

<template>
  <AuthForm icon="key" :subtitle="t('resetPassword.subtitle')" footer-align="center" @submit="handleSubmit">
    <AlertBanner v-if="linkError || error" tone="danger" icon="error" dense>
      {{ error || linkError }}
    </AlertBanner>

    <AlertBanner v-if="success" tone="success" icon="check_circle" dense>
      {{ success }}
    </AlertBanner>

    <template v-if="!linkError && !success">
      <FormField
        :label="t('resetPassword.newPassword')"
        :error="passwordLengthError || undefined"
      >
        <SecretInput
          v-model="newPassword"
          :placeholder="t('resetPassword.newPassword_placeholder')"
          :is-password="true"
          autocomplete="new-password"
        />
      </FormField>

      <FormField
        :label="t('resetPassword.confirmPassword')"
        :error="confirmPasswordError || undefined"
      >
        <SecretInput
          v-model="confirmPassword"
          :placeholder="t('resetPassword.confirmPassword_placeholder')"
          :is-password="true"
          autocomplete="new-password"
          @keyup.enter="handleSubmit"
        />
      </FormField>
    </template>

    <p v-if="success" class="reset-hint">{{ t('resetPassword.redirecting') }}</p>

    <template v-if="!linkError && !success" #submit>
      <BaseButton
        type="submit"
        variant="primary"
        size="lg"
        :disabled="!canSubmit"
        style="width: 100%; justify-content: center"
      >
        <Spinner v-if="loading" size="sm" />
        <template v-else>
          <MsIcon name="key" size="sm" />
          {{ t('resetPassword.submit') }}
        </template>
      </BaseButton>
    </template>

    <template #footer>
      <RouterLink class="reset-link" :to="{ name: 'login' }">
        {{ t('resetPassword.back') }}
      </RouterLink>
    </template>
  </AuthForm>
</template>

<style scoped>
.reset-link {
  color: var(--t2);
  font-size: .82rem;
  text-decoration: none;
  transition: color .15s ease;
}

.reset-link:hover {
  color: var(--t1);
}

.reset-hint {
  color: var(--t3);
  font-size: .78rem;
  text-align: center;
  margin-top: calc(var(--sp-2) * -1);
}
</style>
