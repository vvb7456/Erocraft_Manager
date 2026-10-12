<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import BaseModal from '@/components/ui/BaseModal.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import SupportChat from '@/components/support/SupportChat.vue'
import LoadingCenter from '@/components/ui/LoadingCenter.vue'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>()
const { t } = useI18n()
const { post, loading } = useApiFetch()
const cid = ref<number | null>(null)
const open = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
async function load() {
  const data = await post<{ id: number }>('/api/support/conversation')
  if (data) cid.value = data.id
}
watch(open, value => { if (value && !cid.value) void load() }, { immediate: true })
</script>

<template>
  <BaseModal v-model="open" :title="t('support.title')" icon="support_agent" size="lg">
    <div v-if="open && cid" class="support-modal-content"><SupportChat :conversation-id="cid" /></div>
    <LoadingCenter v-else-if="loading" size="sm" />
    <BaseButton v-else @click="load">{{ t('support.retry') }}</BaseButton>
  </BaseModal>
</template>

<style scoped>
.support-modal-content { display: flex; height: min(600px, 65dvh); min-height: 280px; }
</style>
