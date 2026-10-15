<script setup lang="ts">
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AuthForm from '@/components/auth/AuthForm.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'ForgotPasswordPage' })

const { t } = useI18n({ useScope: 'global' })

const email = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')

watch(email, () => {
  error.value = ''
  success.value = ''
})

async function handleSubmit() {
  // Reentrancy guard — see RegisterPage.vue handleSubmit for rationale.
  if (loading.value) return
  error.value = ''
  success.value = ''

  if (!email.value.trim()) {
    error.value = t('forgotPassword.error.empty')
    return
  }

  loading.value = true
  try {
    await fetchApi('/api/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.value.trim(),
      }),
    })

    success.value = t('forgotPassword.success')
  } catch (failure) {
    error.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthForm icon="mail" :subtitle="t('forgotPassword.subtitle')" footer-align="center" @submit="handleSubmit">
    <AlertBanner v-if="error" tone="danger" icon="error" dense>
      {{ error }}
    </AlertBanner>

    <AlertBanner v-if="success" tone="success" icon="check_circle" dense>
      {{ success }}
    </AlertBanner>

    <FormField :label="t('forgotPassword.email')">
      <BaseInput
        v-model="email"
        type="email"
        :placeholder="t('forgotPassword.email_placeholder')"
        autocomplete="email"
      />
    </FormField>

    <template #submit>
      <BaseButton
        type="submit"
        variant="primary"
        size="lg"
        :disabled="loading"
        style="width: 100%; justify-content: center"
      >
        <Spinner v-if="loading" size="sm" />
        <template v-else>
          <MsIcon name="mail" size="sm" />
          {{ t('forgotPassword.submit') }}
        </template>
      </BaseButton>
    </template>

    <template #footer>
      <RouterLink class="forgot-link" :to="{ name: 'login' }">
        {{ t('forgotPassword.back') }}
      </RouterLink>
    </template>
  </AuthForm>
</template>

<style scoped>
.forgot-link {
  color: var(--t2);
  font-size: .82rem;
  text-decoration: none;
  transition: color .15s ease;
}

.forgot-link:hover {
  color: var(--t1);
}
</style>
