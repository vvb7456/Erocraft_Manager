<script setup lang="ts">
import { usePageHeaderActions } from '@/composables/usePageHeader'

const target = usePageHeaderActions()
</script>

<template>
  <Teleport v-if="target" :to="target"><slot /></Teleport>
</template>
