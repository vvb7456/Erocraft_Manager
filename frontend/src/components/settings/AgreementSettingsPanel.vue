<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import BaseCard from '@/components/ui/BaseCard.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import FormField from '@/components/form/FormField.vue'
import ToggleSwitch from '@/components/ui/ToggleSwitch.vue'
import HelpTip from '@/components/ui/HelpTip.vue'
import MsIcon from '@/components/ui/MsIcon.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'
import AgreementEditModal from './AgreementEditModal.vue'
import { FIXED_AGREEMENT_SLUGS, type FixedAgreementSlug } from '@/utils/agreements'

defineOptions({ name: 'AgreementSettingsPanel' })

interface AgreementAdminOut {
  id: number
  slug: string
  current_version: number
  version_count: number
  current_title_zh: string
  current_title_en: string
}

const props = defineProps<{
  settings: Record<string, any>
}>()

const emit = defineEmits<{
  'update:settings': [value: Record<string, any>]
}>()

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

const loading = ref(false)
const agreements = ref<AgreementAdminOut[]>([])
const editState = ref<{ slug: FixedAgreementSlug; lang: 'zh' | 'en' } | null>(null)

function getBool(key: string): boolean {
  const v = props.settings[key]
  return v === true || v === 'true' || v === '1'
}

function setBool(key: string, val: boolean) {
  emit('update:settings', { ...props.settings, [key]: val })
}

async function loadAgreements() {
  loading.value = true
  const data = await get<AgreementAdminOut[]>('/api/admin/agreements')
  if (data) agreements.value = data
  loading.value = false
}

function openEdit(slug: FixedAgreementSlug, lang: 'zh' | 'en') {
  editState.value = { slug, lang }
}

function agreementName(slug: FixedAgreementSlug): string {
  return slug === 'tos'
    ? t('agreements.checkbox.open_tos')
    : t('agreements.checkbox.open_privacy')
}

function agreementIcon(slug: FixedAgreementSlug): string {
  return slug === 'tos' ? 'gavel' : 'lock'
}

function agreementSubtitle(slug: FixedAgreementSlug): string {
  return slug === 'tos'
    ? t('settings.agreements.subtitle_tos')
    : t('settings.agreements.subtitle_privacy')
}

function findAgreement(slug: FixedAgreementSlug): AgreementAdminOut | null {
  return agreements.value.find(a => a.slug === slug) ?? null
}

async function onEditSaved() {
  await loadAgreements()
}

onMounted(loadAgreements)
</script>

<template>
  <div class="st-panel">
    <div v-if="loading" class="panel-loading"><LoadingCenter size="sm" /></div>

    <template v-else>
      <BaseCard variant="bg2" class="settings-card">
        <SectionHeader icon="check_box" flush>
          {{ t('settings.agreements.title') }}
        </SectionHeader>
        <p class="section-note">{{ t('settings.agreements.desc') }}</p>
        <FormField layout="horizontal">
          <template #label>
            {{ t('settings.agreements.default_checked') }}
            <HelpTip :text="t('settings.agreements.default_checked_tip')" />
          </template>
          <ToggleSwitch
            :modelValue="getBool('AGREEMENTS_DEFAULT_CHECKED')"
            @update:modelValue="setBool('AGREEMENTS_DEFAULT_CHECKED', $event)"
            size="sm"
          />
        </FormField>
      </BaseCard>

      <BaseCard
        v-for="slug in FIXED_AGREEMENT_SLUGS"
        :key="slug"
        variant="bg2"
        class="settings-card"
      >
        <SectionHeader :icon="agreementIcon(slug)" flush>
          {{ agreementName(slug) }}
        </SectionHeader>
        <p class="section-note">{{ agreementSubtitle(slug) }}</p>
        <div class="doc-actions">
          <BaseButton size="md" variant="primary" @click="openEdit(slug, 'zh')">
            <MsIcon name="edit" size="sm" />
            {{ t('settings.agreements.edit_zh') }}
          </BaseButton>
          <BaseButton size="md" variant="primary" @click="openEdit(slug, 'en')">
            <MsIcon name="edit" size="sm" />
            {{ t('settings.agreements.edit_en') }}
          </BaseButton>
        </div>
      </BaseCard>
    </template>

    <AgreementEditModal
      v-if="editState"
      v-model="editState"
      :slug="editState.slug"
      :lang="editState.lang"
      :agreement="findAgreement(editState.slug)"
      @saved="onEditSaved"
    />
  </div>
</template>

<style scoped>
.st-panel {
  margin-top: var(--sp-4);
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.settings-card {
  padding: var(--sp-2);
}

.section-note {
  font-size: .84rem;
  font-weight: 400;
  line-height: 1.55;
  color: var(--t2);
  margin: 0 0 var(--sp-3);
  max-width: 56ch;
}

.doc-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
}

.panel-loading {
  display: flex;
  justify-content: center;
  padding: var(--sp-6) 0;
  color: var(--t3);
}
</style>
