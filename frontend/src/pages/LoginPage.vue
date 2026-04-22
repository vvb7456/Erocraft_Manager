<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { switchLanguage } from '@/i18n/vue-i18n'
import { backendToFrontendLocale } from '@/i18n/locale-map'
import AuthForm from '@/components/auth/AuthForm.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import FormField from '@/components/form/FormField.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'LoginPage' })

const router = useRouter()
const { t, te } = useI18n({ useScope: 'global' })

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const allowRegistration = ref(false)

onMounted(async () => {
  try {
    const res = await fetch('/api/public/branding')
    if (res.ok) {
      const data = await res.json() as { allow_registration?: boolean }
      allowRegistration.value = data?.allow_registration === true
    }
  } catch { /* ignore */ }
})

function translateApiText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return ''
  if (/^[a-z_]+\.[a-z_]+$/.test(value)) {
    const key = `common.apiErrors.${value}`
    if (te(key)) return t(key)
  }
  return value
}

async function handleLogin() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = t('login.error.empty')
    return
  }

  loading.value = true
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: username.value,
        password: password.value,
      }),
    })
    const data = await res.json()

    if (res.ok && data.ok) {
      // Apply user-preferred language before redirecting so the
      // destination view renders in the right locale.
      switchLanguage(backendToFrontendLocale(data.language))
      if (data.is_admin) {
        router.replace({ name: 'dashboard' })
      } else {
        router.replace({ name: 'user-servers' })
      }
    } else {
      error.value = translateApiText(data.error) || t('login.error.invalid')
    }
  } catch {
    error.value = t('login.error.network')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthForm icon="dns" footer-align="between" @submit="handleLogin">
    <AlertBanner v-if="error" tone="danger" icon="error" dense>
      {{ error }}
    </AlertBanner>

    <FormField :label="t('login.username')">
      <BaseInput
        v-model="username"
        :placeholder="t('login.username_placeholder')"
        autocomplete="username"
      />
    </FormField>

    <FormField :label="t('login.password')">
      <SecretInput
        v-model="password"
        :placeholder="t('login.password_placeholder')"
        :is-password="true"
        autocomplete="current-password"
        @keyup.enter="handleLogin"
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
          <MsIcon name="login" size="sm" />
          {{ t('login.submit') }}
        </template>
      </BaseButton>
    </template>

    <template #footer>
      <RouterLink class="login-link" :to="{ name: 'forgot-password' }">
        {{ t('login.forgot') }}
      </RouterLink>
      <RouterLink v-if="allowRegistration" class="login-link" :to="{ name: 'register' }">
        {{ t('login.register') }}
      </RouterLink>
      <span v-else />
    </template>
  </AuthForm>
</template>

<style scoped>
.login-link {
  color: var(--t2);
  font-size: .82rem;
  text-decoration: none;
  transition: color .15s ease;
}

.login-link:hover {
  color: var(--t1);
}
</style>
