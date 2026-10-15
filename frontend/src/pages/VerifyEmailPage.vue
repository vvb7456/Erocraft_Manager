<script setup lang="ts">
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthForm from '@/components/auth/AuthForm.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'VerifyEmailPage' })

const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: 'global' })

const loading = ref(true)
const error = ref('')
const success = ref('')

let redirectTimer: ReturnType<typeof setTimeout> | null = null

const token = computed(() =>
  typeof route.query.token === 'string' ? route.query.token.trim() : '',
)

function queueRedirect(target: { name: string } = { name: 'login' }) {
  if (redirectTimer) clearTimeout(redirectTimer)
  redirectTimer = setTimeout(() => {
    router.replace(target)
  }, 1500)
}

async function verify() {
  if (!token.value) {
    error.value = t('verifyEmail.error.invalidLink')
    loading.value = false
    return
  }
  try {
    const res = await fetchApi('/api/register/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token.value }),
    })
    let data: {
      message?: string
      detail?: string
      error?: string
      auto_login?: boolean
      is_admin?: boolean
    } | null = null
    try { data = await res.json() } catch { data = null }
    if (res.ok) {
      success.value = t('verifyEmail.success')
      const target = data?.auto_login
        ? (data?.is_admin ? { name: 'dashboard' } : { name: 'user-home' })
        : { name: 'login' }
      queueRedirect(target)
      return
    }
  } catch (failure) {
    error.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

onMounted(verify)
onBeforeUnmount(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
})
</script>

<template>
  <AuthForm icon="mark_email_read" :subtitle="t('verifyEmail.subtitle')" footer-align="center">
    <AlertBanner v-if="loading" tone="info" icon="hourglass_empty" dense>
      <Spinner size="sm" />
      &nbsp;{{ t('verifyEmail.verifying') }}
    </AlertBanner>

    <AlertBanner v-if="error && !loading" tone="danger" icon="error" dense>
      {{ error }}
    </AlertBanner>

    <AlertBanner v-if="success && !loading" tone="success" icon="check_circle" dense>
      {{ success }}
    </AlertBanner>

    <p v-if="success && !loading" class="verify-hint">{{ t('verifyEmail.redirecting') }}</p>

    <template #footer>
      <RouterLink class="verify-link" :to="{ name: 'login' }">
        {{ t('verifyEmail.back') }}
      </RouterLink>
    </template>
  </AuthForm>
</template>

<style scoped>
.verify-link {
  color: var(--t2);
  font-size: .82rem;
  text-decoration: none;
  transition: color .15s ease;
}

.verify-link:hover {
  color: var(--t1);
}

.verify-hint {
  color: var(--t3);
  font-size: .78rem;
  text-align: center;
  margin-top: calc(var(--sp-2) * -1);
}
</style>
