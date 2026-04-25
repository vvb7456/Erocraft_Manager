<script setup lang="ts">
// UserSearchSelect — wraps BaseSelect with the simple users list endpoint.
// Used by the admin server "owner" section. Emits the selected user id.
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useApiFetch } from '@/composables/useApiFetch'
import BaseSelect from '@/components/form/BaseSelect.vue'

defineOptions({ name: 'UserSearchSelect' })

interface SimpleUser {
  id: number
  username: string
  email: string
}

const props = defineProps<{
  modelValue: number | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

const { t } = useI18n({ useScope: 'global' })
const { get } = useApiFetch()

const users = ref<SimpleUser[]>([])
const value = ref<number>(props.modelValue ?? 0)

watch(() => props.modelValue, v => { value.value = v ?? 0 })

onMounted(async () => {
  const res = await get<{ users: SimpleUser[] }>('/api/admin/resources/users')
  if (res?.users) users.value = res.users
})

function handle(v: string | number | boolean | (string | number | boolean)[]) {
  if (typeof v === 'number') emit('update:modelValue', v)
  else if (typeof v === 'string') emit('update:modelValue', Number(v))
}
</script>

<template>
  <BaseSelect
    :modelValue="value"
    :options="users.map(u => ({ value: u.id, label: `${u.username} · ${u.email}` }))"
    :placeholder="t('adminServer.settings.owner.placeholder')"
    :emptyText="t('adminServer.settings.owner.noUsers')"
    :searchPlaceholder="t('adminServer.settings.owner.placeholder')"
    :disabled="disabled"
    searchable
    teleport
    @update:modelValue="handle"
  />
</template>
