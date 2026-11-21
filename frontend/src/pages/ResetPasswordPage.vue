<script setup lang="ts">
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import { passwordErrorKey } from '@/utils/username'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthShell from '@/components/auth/AuthShell.vue'
import AuthStatusView from '@/components/auth/AuthStatusView.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'ResetPasswordPage' })

const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: 'global' })

const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')

let redirectTimer: ReturnType<typeof setTimeout> | null = null

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
  const kind = passwordErrorKey(newPassword.value)
  return kind ? t(`common.passwordValidation.${kind}`) : ''
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
    void router.replace({ name: 'login' })
  }, 3000)
}

function goLogin() {
  if (redirectTimer) {
    clearTimeout(redirectTimer)
    redirectTimer = null
  }
  void router.replace({ name: 'login' })
}

async function handleSubmit() {
  // Guard against double-dispatch when Enter triggers both native submit and key handlers.
  if (loading.value) return
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
    await fetchApi('/api/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value,
        token: token.value,
        newPassword: newPassword.value,
      }),
    })

    success.value = t('resetPassword.success')
    newPassword.value = ''
    confirmPassword.value = ''
    queueRedirect()
  } catch (failure) {
    error.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
})
</script>

<template>
  <AuthShell
    icon="key"
    :subtitle="!linkError && !success ? t('resetPassword.subtitle') : undefined"
  >
    <AuthStatusView
      v-if="linkError"
      tone="danger"
      icon="error_outline"
      :title="t('resetPassword.invalid_title')"
      :description="linkError"
    >
      <template #actions>
        <BaseButton variant="default" size="lg" @click="goLogin">
          {{ t('resetPassword.back') }}
        </BaseButton>
      </template>
    </AuthStatusView>

    <AuthStatusView
      v-else-if="success"
      tone="success"
      icon="check_circle"
      :title="t('resetPassword.success_title')"
      :email="email"
      :description="success"
      :hint="t('resetPassword.redirecting')"
    >
      <template #actions>
        <BaseButton variant="primary" size="lg" @click="goLogin">
          {{ t('resetPassword.back') }}
        </BaseButton>
      </template>
    </AuthStatusView>

    <form v-else class="reset-form" @submit.prevent="handleSubmit">
      <div v-if="email" class="reset-account">
        <MsIcon name="mail" size="xs" color="var(--t2)" />
        <span>{{ email }}</span>
      </div>

      <AlertBanner v-if="error" tone="danger" icon="error" dense>
        {{ error }}
      </AlertBanner>

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
        />
      </FormField>

      <BaseButton
        type="submit"
        variant="primary"
        size="lg"
        :disabled="!canSubmit"
        class="reset-submit-btn"
      >
        <Spinner v-if="loading" size="sm" />
        <template v-else>
          <MsIcon name="key" size="sm" />
          {{ t('resetPassword.submit') }}
        </template>
      </BaseButton>

      <div class="reset-footer">
        <RouterLink class="reset-link" :to="{ name: 'login' }">
          {{ t('resetPassword.back') }}
        </RouterLink>
      </div>
    </form>
  </AuthShell>
</template>

<style scoped>
.reset-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.reset-form :deep(.form-field) {
  margin-bottom: 0;
}

.reset-account {
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  margin-top: calc(var(--sp-2) * -1);
  padding: 5px 12px;
  background: var(--bg-in);
  border: 1px solid var(--bd);
  border-radius: var(--r-sm);
  color: var(--t1);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.reset-account span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reset-submit-btn {
  width: 100%;
  justify-content: center;
}

.reset-footer {
  display: flex;
  justify-content: center;
  margin-top: calc(var(--sp-1) * -1);
}

.reset-link {
  color: var(--t2);
  font-size: var(--text-sm);
  text-decoration: none;
  transition: color .15s ease;
}

.reset-link:hover {
  color: var(--t1);
}
</style>
