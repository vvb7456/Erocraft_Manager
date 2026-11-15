<script setup lang="ts">
import { apiErrorMessage, fetchApi } from '@/composables/apiClient'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthShell from '@/components/auth/AuthShell.vue'
import AuthStatusView from '@/components/auth/AuthStatusView.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'

defineOptions({ name: 'ConfirmEmailPage' })

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
const uid = computed(() => {
  const raw = typeof route.query.uid === 'string' ? route.query.uid.trim() : ''
  const parsed = Number(raw)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
})
const linkError = computed(() =>
  !token.value || uid.value === null ? t('confirmEmail.error.invalidLink') : '',
)

function clearRedirect() {
  if (redirectTimer) {
    clearTimeout(redirectTimer)
    redirectTimer = null
  }
}

function queueRedirect() {
  clearRedirect()
  redirectTimer = setTimeout(() => {
    void router.replace({ name: 'account' })
  }, 3000)
}

function goAccount() {
  clearRedirect()
  void router.replace({ name: 'account' })
}

function goLogin() {
  clearRedirect()
  void router.replace({ name: 'login' })
}

async function confirmEmail() {
  if (linkError.value) {
    error.value = linkError.value
    loading.value = false
    return
  }

  loading.value = true
  error.value = ''
  success.value = ''

  try {
    await fetchApi('/api/user/account/confirm-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: token.value,
        uid: uid.value,
      }),
    })

    success.value = t('confirmEmail.success')
    queueRedirect()
  } catch (failure) {
    error.value = apiErrorMessage(failure)
  } finally {
    loading.value = false
  }
}

onMounted(confirmEmail)
onBeforeUnmount(clearRedirect)
</script>

<template>
  <AuthShell icon="mail">
    <AuthStatusView
      v-if="loading"
      tone="loading"
      :title="t('confirmEmail.subtitle')"
      :description="t('confirmEmail.loading')"
    />

    <AuthStatusView
      v-else-if="success"
      tone="success"
      icon="mark_email_read"
      :title="t('confirmEmail.success_title')"
      :description="success"
      :hint="t('confirmEmail.redirecting')"
    >
      <template #actions>
        <BaseButton variant="primary" size="lg" @click="goAccount">
          <MsIcon name="person" size="sm" />
          {{ t('confirmEmail.account') }}
        </BaseButton>
      </template>
    </AuthStatusView>

    <AuthStatusView
      v-else
      tone="danger"
      icon="error_outline"
      :title="t('confirmEmail.error_title')"
      :description="error || linkError"
    >
      <template #actions>
        <BaseButton variant="default" size="lg" @click="goLogin">
          {{ t('confirmEmail.back') }}
        </BaseButton>
      </template>
    </AuthStatusView>
  </AuthShell>
</template>
