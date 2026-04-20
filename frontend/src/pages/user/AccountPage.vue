<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import PageHeader from '@/components/layout/PageHeader.vue'
import AccountSettingsPanel from '@/components/account/AccountSettingsPanel.vue'

defineOptions({ name: 'AccountPage' })

const { t } = useI18n({ useScope: 'global' })
</script>

<template>
  <PageHeader icon="person" :title="t('account.title')" />

  <div class="page-body">
    <AccountSettingsPanel />
  </div>
</template>
