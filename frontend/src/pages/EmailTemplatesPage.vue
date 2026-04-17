<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import { useToast } from '@/composables/useToast'
import PageHeader from '@/components/layout/PageHeader.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/form/BaseInput.vue'
import BaseTextarea from '@/components/form/BaseTextarea.vue'
import TabSwitcher, { type TabItem } from '@/components/ui/TabSwitcher.vue'
import Spinner from '@/components/ui/Spinner.vue'
import FormField from '@/components/form/FormField.vue'

defineOptions({ name: 'EmailTemplatesPage' })

const { t } = useI18n({ useScope: 'global' })
const { get, post } = useApiFetch()
const { toast } = useToast()

const initialLoading = ref(true)

type TemplateKey = 'bulk' | 'reminder' | 'preDelete' | 'createUser'

interface TemplateData {
  subject: string
  body: string
}

const activeTab = ref<TemplateKey>('bulk')

const tabs = computed<TabItem[]>(() => [
  { key: 'bulk', label: t('emailTemplates.bulk.title'), icon: 'campaign' },
  { key: 'reminder', label: t('emailTemplates.reminder.title'), icon: 'notifications_active' },
  { key: 'preDelete', label: t('emailTemplates.preDelete.title'), icon: 'warning' },
  { key: 'createUser', label: t('emailTemplates.createUser.title'), icon: 'person_add' },
])

const templates = ref<Record<TemplateKey, TemplateData>>({
  bulk: { subject: '', body: '' },
  reminder: { subject: '', body: '' },
  preDelete: { subject: '', body: '' },
  createUser: { subject: '', body: '' },
})

// Variables available per template type
const templateVars: Record<TemplateKey, string[]> = {
  bulk: ['brand_name', 'username', 'email', 'server_name', 'server_id', 'expiration_date'],
  reminder: ['brand_name', 'server_count', 'expiration_date', 'server_list'],
  preDelete: ['server_name', 'deletion_date'],
  createUser: ['username', 'password'],
}

const currentVars = computed(() => templateVars[activeTab.value])
const currentDesc = computed(() => t(`emailTemplates.${activeTab.value}.desc`))

const saveLoading = ref(false)

async function loadTemplates() {
  const data = await get<Record<string, any>>('/api/email-templates')
  if (data) {
    for (const key of ['bulk', 'reminder', 'preDelete', 'createUser'] as TemplateKey[]) {
      templates.value[key] = {
        subject: data[key]?.subject ?? '',
        body: data[key]?.body ?? '',
      }
    }
  }
  initialLoading.value = false
}

onMounted(loadTemplates)

async function save() {
  saveLoading.value = true
  const tpl = templates.value[activeTab.value]
  const res = await post<{ message: string }>('/api/email-templates', {
    type: activeTab.value,
    subject: tpl.subject,
    body: tpl.body,
  })
  saveLoading.value = false
  if (res) toast(t('emailTemplates.saved'), 'success')
}
</script>

<template>
  <PageHeader :title="t('emailTemplates.title')" icon="mail" />

  <div class="page-body">
    <div v-if="initialLoading" class="center-loading">
      <Spinner size="lg" />
    </div>

    <template v-else>
      <TabSwitcher :tabs="tabs" v-model="activeTab" />

      <div class="tpl-form">
        <p class="tpl-desc">{{ currentDesc }}</p>

        <div class="tpl-vars-section">
          <span class="s-label">{{ t('emailTemplates.placeholders') }}</span>
          <div class="tpl-vars">
            <span v-for="v in currentVars" :key="v" class="tpl-var-badge">
              <code v-text="'{{' + v + '}}'"></code>
              <span class="tpl-var-desc">{{ t(`emailTemplates.var.${v}`) }}</span>
            </span>
          </div>
        </div>

        <FormField :label="t('emailTemplates.subject')">
          <BaseInput v-model="templates[activeTab].subject" />
        </FormField>

        <FormField :label="t('emailTemplates.body')">
          <BaseTextarea v-model="templates[activeTab].body" :rows="12" mono />
        </FormField>

        <div class="form-actions">
          <BaseButton variant="primary" :loading="saveLoading" @click="save">
            {{ t('emailTemplates.save') }}
          </BaseButton>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.center-loading { display: flex; justify-content: center; padding: var(--sp-8); }

.tpl-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-top: var(--sp-4);
}

.tpl-desc {
  color: var(--t2);
  font-size: .85rem;
}

.tpl-vars-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.tpl-vars {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.tpl-var-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--r);
  background: var(--bg2);
  border: 1px solid var(--bd);
  font-size: .8rem;
}

.tpl-var-badge code {
  font-family: var(--font-mono);
  color: var(--ac);
  font-size: .78rem;
}

.tpl-var-desc {
  color: var(--t3);
}

.s-label {
  font-size: .82rem;
  color: var(--t2);
  font-weight: 500;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
