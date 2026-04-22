<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import { switchLanguage } from '@/i18n/vue-i18n'
import { backendToFrontendLocale, type BackendLocale } from '@/i18n/locale-map'
import BaseButton from '@/components/ui/BaseButton.vue'
import AlertBanner from '@/components/ui/AlertBanner.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseSelect from '@/components/form/BaseSelect.vue'
import FormField from '@/components/form/FormField.vue'
import SecretInput from '@/components/ui/SecretInput.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'

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

const { t } = useI18n({ useScope: 'global' })
const { get, post, raw } = useApiFetch()
const { toast } = useToast()

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

const selectedLanguage = ref<BackendLocale>('en')
const languageBanner = ref('')

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
  const data = await get<UserProfile>('/api/user/me')
  if (data) {
    profile.value = data
    selectedLanguage.value = data.language === 'zh' ? 'zh' : 'en'
  }
  initialLoading.value = false
}

async function submitEmailChange() {
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
  const validationMessage = passwordLengthError.value
    || confirmPasswordError.value
    || t('account.password.validation.required')

  if (!canSubmitPassword.value) {
    toast(validationMessage, 'warning')
    return
  }

  passwordLoading.value = true
  try {
    const response = await raw('/api/user/account', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        currentPassword: currentPassword.value,
        newPassword: newPassword.value,
      }),
    })
    if (!response) return

    let payload: MessageResponse | null = null
    try {
      payload = await response.json() as MessageResponse
    } catch {
      payload = null
    }

    passwordBanner.value = t('account.password.success')
    toast(passwordBanner.value, 'success')
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } finally {
    passwordLoading.value = false
  }
}

const canSubmitLanguage = computed(() =>
  !!profile.value
  && selectedLanguage.value !== (profile.value.language === 'zh' ? 'zh' : 'en')
  && !languageLoading.value,
)

watch(selectedLanguage, () => {
  languageBanner.value = ''
})

async function submitLanguage() {
  if (!profile.value || !canSubmitLanguage.value) return
  languageLoading.value = true
  try {
    const data = await raw('/api/user/account/language', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: selectedLanguage.value }),
    })
    if (!data) return
    let payload: UserProfile | null = null
    try { payload = await data.json() as UserProfile } catch { payload = null }
    if (payload) profile.value = payload
    languageBanner.value = t('account.language.success')
    toast(languageBanner.value, 'success')
    // Apply immediately so the rest of the UI matches the new preference.
    switchLanguage(backendToFrontendLocale(selectedLanguage.value))
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
    <section class="account-section">
      <SectionHeader icon="person" flush>
        {{ t('account.profile.title') }}
      </SectionHeader>
      <p class="account-section__desc">{{ t('account.profile.desc') }}</p>

      <FormField :label="t('account.profile.username')" layout="horizontal" bordered>
        <div class="account-value">{{ profile?.username ?? '' }}</div>
      </FormField>
      <FormField :label="t('account.profile.email')" layout="horizontal" bordered>
        <div class="account-value">{{ profile?.email ?? '' }}</div>
      </FormField>
      <FormField :label="t('account.profile.accountType')" layout="horizontal" bordered>
        <div class="account-value">{{ accountTypeLabel }}</div>
      </FormField>
    </section>

    <section class="account-section">
      <SectionHeader icon="mail" flush>
        {{ t('account.email.title') }}
      </SectionHeader>
      <p class="account-section__desc">{{ t('account.email.desc') }}</p>

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
    </section>

    <section class="account-section">
      <SectionHeader icon="lock" flush>
        {{ t('account.password.title') }}
      </SectionHeader>
      <p class="account-section__desc">{{ t('account.password.desc') }}</p>

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
    </section>

    <section class="account-section">
      <SectionHeader icon="language" flush>
        {{ t('account.language.title') }}
      </SectionHeader>
      <p class="account-section__desc">{{ t('account.language.desc') }}</p>

      <form class="account-form" @submit.prevent="submitLanguage">
        <AlertBanner v-if="languageBanner" tone="success" icon="check_circle">
          {{ languageBanner }}
        </AlertBanner>

        <FormField :label="t('account.language.label')" layout="horizontal" bordered>
          <BaseSelect
            v-model="selectedLanguage"
            :options="languageOptions"
          />
        </FormField>

        <div class="account-actions">
          <BaseButton
            type="submit"
            variant="primary"
            :loading="languageLoading"
            :disabled="!canSubmitLanguage"
          >
            <MsIcon name="language" size="sm" />
            {{ t('account.language.submit') }}
          </BaseButton>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.account-panel {
  max-width: 720px;
  margin: 0 auto;
}

.account-section {
  display: grid;
  gap: 12px;
}

.account-section + .account-section {
  margin-top: var(--sp-6);
  padding-top: var(--sp-6);
  border-top: 1px solid color-mix(in srgb, var(--bd) 50%, transparent);
}

.account-section__desc {
  margin: calc(var(--sp-1) * -1) 0 var(--sp-2);
  max-width: 52ch;
  color: var(--t2);
  font-size: .84rem;
  line-height: 1.55;
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

.account-panel :deep(.form-field__h-left) {
  min-width: 172px;
}

.account-panel :deep(.field-label__text) {
  white-space: nowrap;
}

.account-section :deep(.form-field--bordered:last-of-type) {
  border-bottom: 0;
}

.account-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--sp-3);
}

@media (max-width: 768px) {
  .account-section + .account-section {
    margin-top: var(--sp-5);
    padding-top: var(--sp-5);
  }

  .account-actions {
    justify-content: stretch;
  }

  .account-actions :deep(.base-btn) {
    width: 100%;
  }
}
</style>
