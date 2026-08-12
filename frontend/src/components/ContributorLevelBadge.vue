<template>
  <span
    v-if="validLevel"
    class="contributor-level"
    :class="[`contributor-level--${size}`, `contributor-level--tier-${colorTier}`]"
    :style="paletteStyle"
    :aria-label="accessibleLabel"
    :title="title || undefined"
  >
    <span class="contributor-level__badge">
      <span class="contributor-level__ornament" aria-hidden="true">{{ emblemMark }}</span>
      <span class="contributor-level__label">Lv. {{ validLevel }}</span>
    </span>
    <span v-if="showTitle && title" class="contributor-level__title">{{ title }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { getContributorLevelPalette } from '../utils/submissionLevel'

const props = defineProps({
  level: {
    type: [Number, String],
    default: null,
  },
  title: {
    type: String,
    default: '',
  },
  size: {
    type: String,
    default: 'regular',
    validator: (value) => ['compact', 'regular'].includes(value),
  },
  showTitle: {
    type: Boolean,
    default: false,
  },
})

const validLevel = computed(() => {
  const level = Number(props.level)
  return Number.isInteger(level) && level > 0 ? level : null
})

const colorTier = computed(() => Math.min(validLevel.value || 1, 10))
const paletteStyle = computed(() => {
  const palette = getContributorLevelPalette(validLevel.value)
  return {
    '--level-badge-bg': palette.bg,
    '--level-badge-fg': palette.fg,
    '--level-badge-border': palette.border,
    '--level-badge-accent': palette.accent,
  }
})
const emblemMark = computed(() => {
  if (colorTier.value >= 10) return '♛'
  if (colorTier.value >= 9) return '✦'
  if (colorTier.value >= 7) return '★'
  if (colorTier.value >= 4) return '◆'
  return '•'
})
const accessibleLabel = computed(() =>
  props.title
    ? `投稿者等級 Lv. ${validLevel.value} ${props.title}`
    : `投稿者等級 Lv. ${validLevel.value}`
)
</script>

<style scoped>
.contributor-level {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 0.45rem;
  vertical-align: middle;
}

.contributor-level__badge {
  position: relative;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  min-width: 4.15rem;
  padding: 0.28rem 0.65rem;
  border: 0;
  clip-path: polygon(10% 0, 90% 0, 100% 50%, 90% 100%, 10% 100%, 0 50%);
  background: var(--level-badge-bg);
  box-shadow:
    inset 0 0 0 1px var(--level-badge-border),
    inset 0 2px 0 color-mix(in srgb, var(--level-badge-accent) 45%, transparent),
    0 2px 4px color-mix(in srgb, var(--level-badge-border) 52%, transparent);
  color: var(--level-badge-fg);
  font-size: var(--app-badge-font-size);
  font-weight: 800;
  line-height: 1.1;
  white-space: nowrap;
}

.contributor-level__badge::after {
  position: absolute;
  inset: 3px;
  border: 1px solid color-mix(in srgb, var(--level-badge-accent) 62%, transparent);
  clip-path: inherit;
  content: '';
  pointer-events: none;
}

.contributor-level__ornament {
  color: var(--level-badge-accent);
  font-size: 0.62em;
  line-height: 1;
}

.contributor-level__label {
  position: relative;
  z-index: 1;
  white-space: nowrap;
}

.contributor-level__title {
  min-width: 0;
  color: var(--text-color);
  font-size: var(--app-font-size-base);
  font-weight: 700;
  line-height: 1.25;
  overflow-wrap: anywhere;
  white-space: nowrap;
}

.contributor-level--compact {
  gap: 0.3rem;
}

.contributor-level--compact .contributor-level__badge {
  min-width: 3.5rem;
  padding: 0.18rem 0.5rem;
  font-size: var(--app-font-size-xs);
  line-height: 1.25;
}

.contributor-level--compact .contributor-level__title {
  font-size: var(--app-font-size-xs);
}

.contributor-level--tier-1 .contributor-level__badge::after,
.contributor-level--tier-2 .contributor-level__badge::after,
.contributor-level--tier-3 .contributor-level__badge::after {
  opacity: 0.45;
}

.contributor-level--tier-7 .contributor-level__badge,
.contributor-level--tier-8 .contributor-level__badge,
.contributor-level--tier-9 .contributor-level__badge,
.contributor-level--tier-10 .contributor-level__badge {
  box-shadow:
    inset 0 0 0 1px var(--level-badge-border),
    inset 0 2px 0 color-mix(in srgb, var(--level-badge-accent) 62%, transparent),
    0 2px 4px color-mix(in srgb, var(--level-badge-border) 58%, transparent);
}

.contributor-level--tier-9 .contributor-level__ornament,
.contributor-level--tier-10 .contributor-level__ornament {
  font-size: 0.76em;
  text-shadow: 0 0 2px var(--level-badge-border);
}
</style>
