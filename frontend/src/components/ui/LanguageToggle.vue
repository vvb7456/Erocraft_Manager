<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { switchLanguage } from '@/i18n/vue-i18n'

defineOptions({ name: 'LanguageToggle' })

const props = withDefaults(defineProps<{
  mode?: 'toggle' | 'stacked'
  variant?: 'default' | 'ghost'
}>(), {
  mode: 'toggle',
  variant: 'default',
})

const { t, locale } = useI18n({ useScope: 'global' })
const nextLocale = computed(() => locale.value === 'zh-CN' ? 'en' : 'zh-CN')

function toggleLanguage() {
  switchLanguage(nextLocale.value)
}

function setLanguage(value: 'zh-CN' | 'en') {
  switchLanguage(value)
}
</script>

<template>
  <button
    v-if="props.mode === 'toggle'"
    type="button"
    class="language-toggle-btn"
    :class="{ 'language-toggle-btn--ghost': props.variant === 'ghost' }"
    :title="locale === 'zh-CN' ? t('common.lang.switch_en') : t('common.lang.switch_zh')"
    :aria-label="locale === 'zh-CN' ? t('common.lang.switch_en') : t('common.lang.switch_zh')"
    @click="toggleLanguage"
  >{{ locale === 'zh-CN' ? 'EN' : '中' }}</button>

  <div v-else class="language-toggle-stacked" :aria-label="t('common.lang.switch_en')">
    <button
      type="button"
      class="language-toggle-mini"
      :class="{ active: locale === 'zh-CN' }"
      :title="t('common.lang.switch_zh')"
      :aria-label="t('common.lang.switch_zh')"
      @click="setLanguage('zh-CN')"
    >中</button>
    <button
      type="button"
      class="language-toggle-mini"
      :class="{ active: locale === 'en' }"
      :title="t('common.lang.switch_en')"
      :aria-label="t('common.lang.switch_en')"
      @click="setLanguage('en')"
    >EN</button>
  </div>
</template>

<style scoped>
.language-toggle-btn {
  background: var(--bg2);
  border: 1px solid var(--bd);
  color: var(--t2);
  border-radius: 4px;
  font-size: var(--text-xs);
  font-weight: 600;
  min-width: 42px;
  padding: 0 10px;
  cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
  letter-spacing: .03em;
  white-space: nowrap;
  flex-shrink: 0;
  line-height: 1;
  min-height: 32px;
}

.language-toggle-btn:hover {
  background: var(--bg3);
  color: var(--t1);
}

.language-toggle-btn--ghost {
  background: none;
  border: none;
  min-width: 32px;
  min-height: 32px;
  padding: 4px 6px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.language-toggle-btn--ghost:hover {
  background: none;
  color: var(--ac);
}

.language-toggle-stacked {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}

.language-toggle-mini {
  background: var(--bg2);
  border: 1px solid var(--bd);
  color: var(--t2);
  border-radius: 3px;
  font-size: var(--text-xs);
  font-weight: 700;
  padding: 2px 5px;
  cursor: pointer;
  transition: background .15s, color .15s;
  line-height: 1;
}

.language-toggle-mini:hover {
  background: var(--bg3);
  color: var(--t1);
}

.language-toggle-mini.active {
  background: var(--ac);
  border-color: var(--ac);
  color: #fff;
}
</style>
