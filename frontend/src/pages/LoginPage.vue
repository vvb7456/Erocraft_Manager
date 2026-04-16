<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import BaseButton from '@/components/ui/BaseButton.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import Spinner from '@/components/ui/Spinner.vue'

defineOptions({ name: 'LoginPage' })

const router = useRouter()
const { t } = useI18n({ useScope: 'global' })

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

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
      router.replace({ name: 'dashboard' })
    } else {
      error.value = data.error || t('login.error.invalid')
    }
  } catch {
    error.value = t('login.error.network')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <MsIcon name="dns" size="lg" color="var(--ac)" />
        <h1 class="login-title">Ptero Manager</h1>
        <p class="login-subtitle">{{ t('login.subtitle') }}</p>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <div v-if="error" class="login-error">
          <MsIcon name="error" size="sm" />
          <span>{{ error }}</span>
        </div>

        <div class="field">
          <label for="username">{{ t('login.username') }}</label>
          <input
            id="username"
            v-model="username"
            type="text"
            class="form-input"
            :placeholder="t('login.username_placeholder')"
            autocomplete="username"
            autofocus
          />
        </div>

        <div class="field">
          <label for="password">{{ t('login.password') }}</label>
          <SecretInput
            v-model="password"
            :placeholder="t('login.password_placeholder')"
            :is-password="true"
            autocomplete="current-password"
            @keyup.enter="handleLogin"
          />
        </div>

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
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  width: 100%;
  background: var(--bg);
  padding: var(--sp-4);
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg2);
  border: 1px solid var(--bd);
  border-radius: var(--r);
  padding: var(--sp-8) var(--sp-6);
}

.login-header {
  text-align: center;
  margin-bottom: var(--sp-6);
}

.login-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--t1);
  margin: var(--sp-3) 0 var(--sp-1);
}

.login-subtitle {
  color: var(--t2);
  font-size: .88rem;
  margin: 0;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.field label {
  font-size: .82rem;
  font-weight: 500;
  color: var(--t2);
}

.login-error {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--rs);
  color: var(--red);
  font-size: .85rem;
}
</style>
