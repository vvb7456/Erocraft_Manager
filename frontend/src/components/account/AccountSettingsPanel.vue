<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { switchLanguage } from '@/i18n/vue-i18n'
import { backendToFrontendLocale, type BackendLocale } from '@/i18n/locale-map'
import { useAppStore } from '@/stores/app'
import { useSupportStore } from '@/stores/support'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import BaseCard from '@/components/ui/BaseCard.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'

defineOptions({ name: 'AccountSettingsPanel' })

interface UserProfile {
  id: number
  username: string
  email: string
  is_admin: boolean
  language: string
}

interface MessageResponse {
  message: string
}

const { t, locale } = useI18n({ useScope: 'global' })
const { get, post, patch, raw } = useApiFetch()
const { toast } = useToast()
const app = useAppStore()
const support = useSupportStore()

const initialLoading = ref(true)
const profile = ref<UserProfile | null>(null)

const emailLoading = ref(false)
const passwordLoading = ref(false)
const languageLoading = ref(false)

const newEmail = ref('')
const emailBanner = ref('')

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const passwordBanner = ref('')

const selectedLanguage = ref<BackendLocale>('zh')

const languageOptions = computed(() => [
  { value: 'zh', label: t('account.language.options.zh') },
  { value: 'en', label: t('account.language.options.en') },
])

const normalizedCurrentEmail = computed(() => profile.value?.email.trim().toLowerCase() ?? '')
const normalizedNewEmail = computed(() => newEmail.value.trim().toLowerCase())
const accountTypeLabel = computed(() => {
  if (!profile.value) return ''
  return profile.value.is_admin
    ? t('account.profile.types.admin')
    : t('account.profile.types.user')
})

const emailError = computed(() => {
  if (!newEmail.value) return ''
  if (!normalizedNewEmail.value) return t('account.email.validation.required')
  if (normalizedNewEmail.value === normalizedCurrentEmail.value) {
    return t('account.email.validation.same')
  }
  return ''
})

const passwordLengthError = computed(() => {
  if (!newPassword.value) return ''
  if (newPassword.value.length < 8) return t('account.password.validation.length')
  return ''
})

const confirmPasswordError = computed(() => {
  if (!confirmPassword.value) return ''
  if (confirmPassword.value !== newPassword.value) {
    return t('account.password.validation.mismatch')
  }
  return ''
})

const canSubmitEmail = computed(() =>
  !!profile.value
  && !!normalizedNewEmail.value
  && !emailError.value
  && !emailLoading.value,
)

const canSubmitPassword = computed(() =>
  !!currentPassword.value.trim()
  && !!newPassword.value
  && !!confirmPassword.value
  && !passwordLengthError.value
  && !confirmPasswordError.value
  && !passwordLoading.value,
)

watch(newEmail, () => {
  emailBanner.value = ''
})

watch([currentPassword, newPassword, confirmPassword], () => {
  passwordBanner.value = ''
})

async function loadProfile() {
  initialLoading.value = true
  const data = await get<UserProfile>('/api/user/me').finally(() => { initialLoading.value = false })
  if (data) {
    profile.value = data
    selectedLanguage.value = data.language === 'zh' ? 'zh' : 'en'
    app.setSessionUser({
      ok: true,
      username: data.username,
      is_admin: data.is_admin,
      has_owned_server: app.hasOwnedServer,
      language: data.language,
    })
  }
}

async function submitEmailChange() {
  if (emailLoading.value) return
  if (!profile.value) return
  if (!normalizedNewEmail.value) {
    toast(t('account.email.validation.required'), 'warning')
    return
  }
  if (emailError.value) {
    toast(emailError.value, 'warning')
    return
  }

  emailLoading.value = true
  try {
    const data = await post<MessageResponse>('/api/user/account/change-email', {
      newEmail: normalizedNewEmail.value,
    })
    if (!data) return

    emailBanner.value = t('account.email.success')
    toast(emailBanner.value, 'success')
    newEmail.value = ''
  } finally {
    emailLoading.value = false
  }
}

async function submitPasswordChange() {
  if (passwordLoading.value) return
  const validationMessage = passwordLengthError.value
    || confirmPasswordError.value
    || t('account.password.validation.required')

  if (!canSubmitPassword.value) {
    toast(validationMessage, 'warning')
    return
  }

  passwordLoading.value = true
  try {
    await raw('/api/user/account', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        currentPassword: currentPassword.value,
        newPassword: newPassword.value,
      }),
    })
    passwordBanner.value = t('account.password.success')
    toast(passwordBanner.value, 'success')
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } finally {
    passwordLoading.value = false
  }
}

async function changeLanguage(value: unknown) {
  if (!profile.value || languageLoading.value || (value !== 'zh' && value !== 'en') || value === selectedLanguage.value) return
  const username = profile.value.username
  const previousLanguage = selectedLanguage.value
  const previousLocale = locale.value
  const nextLocale = backendToFrontendLocale(value)
  selectedLanguage.value = value
  languageLoading.value = true
  switchLanguage(nextLocale)
  try {
    const data = await patch<UserProfile>('/api/user/account/language', { language: value })
    if (app.sessionUser?.username !== username) return
    profile.value = data
    selectedLanguage.value = data.language === 'zh' ? 'zh' : 'en'
    app.setSessionUser({
      ok: true,
      username: data.username,
      is_admin: data.is_admin,
      has_owned_server: app.hasOwnedServer,
      language: data.language,
    })
    if (locale.value === nextLocale) switchLanguage(backendToFrontendLocale(data.language))
  } catch (failure) {
    selectedLanguage.value = previousLanguage
    if (locale.value === nextLocale) switchLanguage(previousLocale)
    throw failure
  } finally {
    languageLoading.value = false
  }
}

onMounted(loadProfile)
</script>

<template>
  <LoadingCenter v-if="initialLoading">
    {{ t('account.loading') }}
  </LoadingCenter>

  <div v-else class="account-panel">
    <BaseCard variant="bg2" density="compact" class="account-section">
      <SectionHeader icon="person" :subtitle="t('account.profile.desc')" flush>
        {{ t('account.profile.title') }}
      </SectionHeader>

      <FormField :label="t('account.profile.username')" layout="horizontal" bordered>
        <div class="account-value">{{ profile?.username ?? '' }}</div>
      </FormField>
      <FormField :label="t('account.profile.email')" layout="horizontal" bordered>
        <div class="account-value">{{ profile?.email ?? '' }}</div>
      </FormField>
      <FormField :label="t('account.profile.accountType')" layout="horizontal" bordered>
        <div class="account-value">{{ accountTypeLabel }}</div>
      </FormField>
    </BaseCard>

    <BaseCard variant="bg2" density="compact" class="account-section">
      <SectionHeader icon="mail" :subtitle="t('account.email.desc')" flush>
        {{ t('account.email.title') }}
      </SectionHeader>

      <form class="account-form" @submit.prevent="submitEmailChange">
        <AlertBanner v-if="emailBanner" tone="success" icon="check_circle">
          {{ emailBanner }}
        </AlertBanner>

        <FormField
          :label="t('account.email.new')"
          layout="horizontal"
          bordered
          :error="emailError || undefined"
        >
          <BaseInput
            v-model="newEmail"
            type="email"
            :placeholder="t('account.email.placeholder')"
            autocomplete="email"
          />
        </FormField>

        <div class="account-actions">
          <BaseButton
            type="submit"
            variant="primary"
            :loading="emailLoading"
            :disabled="!canSubmitEmail"
          >
            <MsIcon name="mail" size="sm" />
            {{ t('account.email.submit') }}
          </BaseButton>
        </div>
      </form>
    </BaseCard>

    <BaseCard variant="bg2" density="compact" class="account-section">
      <SectionHeader icon="lock" :subtitle="t('account.password.desc')" flush>
        {{ t('account.password.title') }}
      </SectionHeader>

      <form class="account-form" @submit.prevent="submitPasswordChange">
        <input
          :value="profile?.username ?? ''"
          type="text"
          name="username"
          autocomplete="username"
          class="account-form__sr-only"
          tabindex="-1"
          aria-hidden="true"
          readonly
        />

        <AlertBanner v-if="passwordBanner" tone="success" icon="check_circle">
          {{ passwordBanner }}
        </AlertBanner>

        <FormField :label="t('account.password.current')" layout="horizontal" bordered>
          <SecretInput
            v-model="currentPassword"
            :is-password="true"
            autocomplete="current-password"
          />
        </FormField>

        <FormField
          :label="t('account.password.new')"
          layout="horizontal"
          bordered
          :error="passwordLengthError || undefined"
        >
          <SecretInput
            v-model="newPassword"
            :is-password="true"
            autocomplete="new-password"
          />
        </FormField>

        <FormField
          :label="t('account.password.confirm')"
          layout="horizontal"
          bordered
          :error="confirmPasswordError || undefined"
        >
          <SecretInput
            v-model="confirmPassword"
            :is-password="true"
            autocomplete="new-password"
          />
        </FormField>

        <div class="account-actions">
          <BaseButton
            type="submit"
            variant="primary"
            :loading="passwordLoading"
            :disabled="!canSubmitPassword"
          >
            <MsIcon name="lock" size="sm" />
            {{ t('account.password.submit') }}
          </BaseButton>
        </div>
      </form>
    </BaseCard>

    <BaseCard variant="bg2" density="compact" class="account-section">
      <SectionHeader icon="settings" :subtitle="t('account.otherSettingsDesc')" flush>
        {{ t('account.otherSettings') }}
      </SectionHeader>
      <FormField :label="t('account.language.label')" layout="horizontal" keep-horizontal control-fit bordered>
        <BaseSelect
          class="language-select"
          :model-value="selectedLanguage"
          :options="languageOptions"
          :disabled="languageLoading || !profile"
          :aria-label="t('account.language.label')"
          :aria-busy="languageLoading"
          @update:model-value="changeLanguage"
        />
      </FormField>
      <FormField :label="t('account.notifications.sound')" layout="horizontal" keep-horizontal control-fit bordered>
        <ToggleSwitch
          :model-value="support.soundEnabled"
          :aria-label="t('account.notifications.sound')"
          @update:model-value="support.setSoundEnabled"
        />
      </FormField>
    </BaseCard>
  </div>
</template>

<style scoped>
.account-panel {
  --field-label-width: 172px;
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.account-section {
  display: grid;
  gap: var(--sp-3);
}

.account-form {
  display: grid;
  gap: 12px;
}

.account-form__sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.account-value {
  display: flex;
  align-items: center;
  min-height: 20px;
  color: var(--t1);
  font-size: .92rem;
  line-height: 1.2;
  word-break: break-word;
}

.account-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--sp-3);
}

.language-select { --control-width: 140px; }

@media (max-width: 768px) {
  .account-actions {
    justify-content: stretch;
  }

  .account-actions :deep(.base-btn) {
    width: 100%;
  }
}
</style>
