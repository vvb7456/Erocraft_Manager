<script setup lang="ts">
defineOptions({ name: 'CardKV' })

defineProps<{
  label: string
}>()
</script>

<template>
  <div class="card-kv">
    <span class="card-kv__label">{{ label }}</span>
    <span class="card-kv__value"><slot /></span>
  </div>
</template>

<style scoped>
.card-kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-kv__label {
  font-size: .72rem;
  color: var(--t3);
  text-transform: uppercase;
  letter-spacing: .03em;
}

.card-kv__value {
  font-size: .82rem;
  color: var(--t1);
}

:slotted(.card-kv-sub) {
  display: block;
  color: var(--t3);
  font-size: .72rem;
}
</style>
