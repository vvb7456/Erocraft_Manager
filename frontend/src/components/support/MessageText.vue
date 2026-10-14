<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { chatTextParts } from '@/utils/chatLinks'

const props = defineProps<{ text: string }>()
const emit = defineEmits<{ navigate: [] }>()
const router = useRouter()
const parts = computed(() => chatTextParts(props.text, window.location.origin, path => router.resolve(path).matched.length > 0))
</script>

<template>
  <p class="message-text"><template v-for="(part, index) in parts" :key="index"><RouterLink v-if="part.route" :to="part.route" @click="emit('navigate')">{{ part.text }}</RouterLink><a v-else-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer">{{ part.text }}</a><template v-else>{{ part.text }}</template></template></p>
</template>

<style scoped>
.message-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-base); line-height: 1.75; }
.message-text a { color: inherit; text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; }
.message-text a:hover { text-decoration-thickness: 2px; }
.message-text a:focus-visible { outline: 2px solid currentColor; outline-offset: 3px; border-radius: 2px; }
</style>
