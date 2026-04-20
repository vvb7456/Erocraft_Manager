<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AuthShell from '@/components/auth/AuthShell.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'ConfirmEmailPage' })

const route = useRoute()
const router = useRouter()
const { t, te } = useI18n({ useScope: 'global' })

const loading = ref(false)
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

function queueRedirect() {
  if (redirectTimer) clearTimeout(redirectTimer)
  redirectTimer = setTimeout(() => {
    router.replace({ name: 'account' })
  }, 3000)
}

function readErrorMessage(data: unknown) {
  if (!data || typeof data !== 'object') return ''
  const record = data as Record<string, unknown>
  for (const key of ['detail', 'error', 'message']) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return ''
}

function translateApiText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return ''
  if (/^[a-z_]+\.[a-z_]+$/.test(value)) {
    const key = `common.apiErrors.${value}`
    if (te(key)) return t(key)
  }
  return value
}

async function confirmEmail() {
  if (linkError.value) {
    error.value = linkError.value
    return
  }

  loading.value = true
  error.value = ''
  success.value = ''

  try {
    const res = await fetch('/api/user/account/confirm-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: token.value,
        uid: uid.value,
      }),
    })

    let data: unknown = null
    try {
      data = await res.json()
    } catch {
      data = null
    }

    if (res.ok) {
      success.value = t('confirmEmail.success')
      queueRedirect()
      return
    }

    error.value = translateApiText(readErrorMessage(data)) || t('confirmEmail.error.failed')
  } catch {
    error.value = t('confirmEmail.error.network')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  confirmEmail()
})

onBeforeUnmount(() => {
  if (redirectTimer) clearTimeout(redirectTimer)
})
</script>

<template>
  <AuthShell icon="mail" :subtitle="t('confirmEmail.subtitle')">
    <div class="confirm-email">
      <div v-if="loading" class="confirm-email__status">
        <Spinner size="sm" />
        <span>{{ t('confirmEmail.loading') }}</span>
      </div>

      <AlertBanner v-if="error || linkError" tone="danger" icon="error" dense>
        {{ error || linkError }}
      </AlertBanner>

      <AlertBanner v-if="success" tone="success" icon="check_circle" dense>
        {{ success }}
      </AlertBanner>

      <p v-if="success" class="confirm-email__hint">
        {{ t('confirmEmail.redirecting') }}
      </p>

      <div v-if="success" class="confirm-email__actions">
        <BaseButton
          variant="primary"
          size="lg"
          style="width: 100%; justify-content: center"
          @click="router.replace({ name: 'account' })"
        >
          <MsIcon name="person" size="sm" />
          {{ t('confirmEmail.account') }}
        </BaseButton>
      </div>

      <div class="confirm-email__footer">
        <RouterLink class="confirm-email__link" :to="{ name: 'login' }">
          {{ t('confirmEmail.back') }}
        </RouterLink>
      </div>
    </div>
  </AuthShell>
</template>

<style scoped>
.confirm-email {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.confirm-email__status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--t2);
  font-size: .84rem;
}

.confirm-email__hint {
  color: var(--t3);
  font-size: .78rem;
  text-align: center;
  margin: calc(var(--sp-2) * -1) 0 0;
}

.confirm-email__actions {
  display: flex;
}

.confirm-email__footer {
  display: flex;
  justify-content: center;
  margin-top: calc(var(--sp-1) * -1);
}

.confirm-email__link {
  color: var(--t2);
  font-size: .82rem;
  text-decoration: none;
  transition: color .15s ease;
}

.confirm-email__link:hover {
  color: var(--t1);
}
</style>
