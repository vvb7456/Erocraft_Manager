<script setup lang="ts">
defineOptions({ name: 'LoadingPage' })
</script>

<template>
  <div class="loading-shell" />
</template>

<style scoped>
.loading-shell {
  position: fixed;
  inset: 0;
  background: var(--bg);
}
</style>
