<script setup lang="ts">
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import AuthShell from '@/components/auth/AuthShell.vue'
import AuthStatusView from '@/components/auth/AuthStatusView.vue'
import BaseButton from '@/components/ui/BaseButton.vue'

defineOptions({ name: 'VerifyEmailPage' })

const route = useRoute()
const router = useRouter()
const { t } = useI18n({ useScope: 'global' })
const app = useAppStore()

const loading = ref(true)
const error = ref('')
const success = ref('')
const autoLogin = ref(false)

let redirectTimer: ReturnType<typeof setTimeout> | null = null

const token = computed(() =>
  typeof route.query.token === 'string' ? route.query.token.trim() : '',
)

function queueRedirect(target: { name: string } = { name: 'login' }) {
  if (redirectTimer) clearTimeout(redirectTimer)
  redirectTimer = setTimeout(() => {
    void router.replace(target)
  }, 2500)
}

function goNext() {
  if (redirectTimer) {
    clearTimeout(redirectTimer)
    redirectTimer = null
  }
  void router.replace(autoLogin.value ? { name: 'home' } : { name: 'login' })
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
      if (data?.auto_login) {
        autoLogin.value = true
        app.clearSessionUser()
        queueRedirect({ name: 'home' })
      } else {
        queueRedirect({ name: 'login' })
      }
      return
    }
    error.value = t('verifyEmail.error.failed')
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
  <AuthShell icon="mark_email_read">
    <AuthStatusView
      v-if="loading"
      tone="loading"
      :title="t('verifyEmail.subtitle')"
      :description="t('verifyEmail.verifying')"
    />

    <AuthStatusView
      v-else-if="success"
      tone="success"
      icon="mark_email_read"
      :title="t('verifyEmail.success_title')"
      :description="success"
      :hint="autoLogin ? t('verifyEmail.redirecting_home') : t('verifyEmail.redirecting')"
    >
      <template #actions>
        <BaseButton variant="primary" size="lg" @click="goNext">
          {{ autoLogin ? t('verifyEmail.enter') : t('verifyEmail.back') }}
        </BaseButton>
      </template>
    </AuthStatusView>

    <AuthStatusView
      v-else
      tone="danger"
      icon="error_outline"
      :title="t('verifyEmail.error_title')"
      :description="error"
    >
      <template #actions>
        <BaseButton variant="default" size="lg" @click="goNext">
          {{ t('verifyEmail.back') }}
        </BaseButton>
      </template>
    </AuthStatusView>
  </AuthShell>
</template>
