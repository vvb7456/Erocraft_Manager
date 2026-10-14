<script setup lang="ts">
withDefaults(defineProps<{ contained?: boolean }>(), { contained: true })
</script>

<template>
  <div class="workspace-page" :class="{ 'workspace-page--contained': contained }">
    <slot name="header" />
    <div class="page-body workspace-page-body"><slot /></div>
  </div>
</template>

<style scoped>
.workspace-page, .workspace-page-body { min-width: 0; }
@media (min-width: 1101px) {
  .workspace-page--contained { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .workspace-page--contained > .workspace-page-body { flex: 1; min-height: 0; overflow: hidden; }
}
</style>
