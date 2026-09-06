<template>
  <div
    id="app"
    class="flex flex-column"
    :class="{ 'app-christmas-frosted-window': effectiveTheme === 'christmas' }"
  >
    <div v-if="effectiveTheme === 'christmas'" class="christmas-snowfall" aria-hidden="true">
      <span
        v-for="snowflake in CHRISTMAS_BACKGROUND_SNOWFLAKES"
        :key="snowflake.id"
        class="christmas-background-snowflake"
        :style="snowflake.style"
      ></span>
      <span
        v-for="snowflake in CHRISTMAS_DECORATIVE_SNOWFLAKES"
        :key="snowflake.id"
        class="christmas-decorative-snowflake"
        :style="snowflake.style"
      >
        {{ snowflake.glyph }}
      </span>
    </div>
    <Toast position="bottom-right" />
    <ConfirmDialog class="app-global-confirm-dialog" />
    <Navbar class="navbar px-1" @toggle-sidebar="toggleSidebar" />
    <div class="content-container">
      <router-view :key="locale" />
    </div>
  </div>
</template>

<script>
import Navbar from './components/Navbar.vue'
import { onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import Toast from 'primevue/toast'
import ConfirmDialog from 'primevue/confirmdialog'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { setGlobalToast } from './utils/toast'
import { applyFontSizePreference } from './utils/fontSizePreference'
import { useI18n } from 'vue-i18n'
import { useTheme } from './utils/useTheme'
import { createChristmasButtonSnowEngine } from './utils/christmasButtonSnow'

const CHRISTMAS_BACKGROUND_SNOWFLAKES = Object.freeze(
  Array.from({ length: 72 }, (_, index) => {
    const duration = 12 + ((index * 11 + 3) % 17) + (index % 3) * 0.35
    const driftDirection = index % 2 === 0 ? 1 : -1
    const driftMid = driftDirection * (1.5 + ((index * 7) % 9) * 0.42)
    const driftEnd = -driftDirection * (2.5 + ((index * 13) % 11) * 0.48)
    const rotation = 180 + ((index * 41) % 360)

    return Object.freeze({
      id: index,
      style: Object.freeze({
        '--snow-left': `${((index * 37 + index * index * 3 + 11) % 103) - 1}%`,
        '--snow-size': `${(0.08 + ((index * 7) % 11) * 0.018).toFixed(3)}rem`,
        '--snow-duration': `${duration.toFixed(2)}s`,
        '--snow-delay': `-${(((index * 29 + 7) % 101) * duration * 0.01).toFixed(2)}s`,
        '--snow-drift-mid': `${driftMid.toFixed(2)}vw`,
        '--snow-drift-return': `${(driftMid * -0.35).toFixed(2)}vw`,
        '--snow-drift-end': `${driftEnd.toFixed(2)}vw`,
        '--snow-opacity': (0.42 + ((index * 17) % 43) * 0.012).toFixed(2),
        '--snow-blur': `${(((index * 5) % 4) * 0.24).toFixed(2)}px`,
        '--snow-rotation-mid': `${(rotation * 0.42).toFixed(2)}deg`,
        '--snow-rotation-late': `${(rotation * 0.76).toFixed(2)}deg`,
        '--snow-rotation': `${rotation}deg`,
      }),
    })
  })
)

const CHRISTMAS_DECORATIVE_SNOWFLAKES = Object.freeze(
  Array.from({ length: 18 }, (_, index) => {
    const duration = 17 + ((index * 7 + 5) % 13) + (index % 4) * 0.45
    const driftDirection = index % 2 === 0 ? 1 : -1
    const driftMid = driftDirection * (2.8 + ((index * 5) % 8) * 0.64)
    const driftEnd = -driftDirection * (4.2 + ((index * 11) % 9) * 0.72)
    const rotation = driftDirection * (240 + ((index * 73) % 420))
    const sizeTier = index % 3

    return Object.freeze({
      id: `decorative-${index}`,
      glyph: ['❄︎', '❅', '❆'][index % 3],
      style: Object.freeze({
        '--flake-left': `${((index * 43 + index * index * 7 + 17) % 101) - 0.5}%`,
        '--flake-size': `${[0.64, 0.86, 1.12][sizeTier]}rem`,
        '--flake-duration': `${duration.toFixed(2)}s`,
        '--flake-delay': `-${(((index * 31 + 13) % 97) * duration * 0.01).toFixed(2)}s`,
        '--flake-flicker-duration': `${(2.8 + ((index * 17) % 9) * 0.31).toFixed(2)}s`,
        '--flake-flicker-delay': `-${(index * 0.47 + 0.21).toFixed(2)}s`,
        '--flake-drift-mid': `${driftMid.toFixed(2)}vw`,
        '--flake-drift-return': `${(driftMid * -0.42).toFixed(2)}vw`,
        '--flake-drift-end': `${driftEnd.toFixed(2)}vw`,
        '--flake-rotation-mid': `${(rotation * 0.43).toFixed(2)}deg`,
        '--flake-rotation-late': `${(rotation * 0.78).toFixed(2)}deg`,
        '--flake-rotation': `${rotation}deg`,
        '--flake-opacity-low': (0.38 + ((index * 7) % 4) * 0.06).toFixed(2),
        '--flake-opacity-high': (0.7 + ((index * 11) % 4) * 0.07).toFixed(2),
        '--flake-blur': `${[0, 0.16, 0.34][sizeTier]}px`,
      }),
    })
  })
)

export default {
  components: {
    Navbar,
    Toast,
    ConfirmDialog,
  },
  setup() {
    const sidebarVisible = ref(true)
    const toast = useToast()
    const confirm = useConfirm()
    const { locale } = useI18n()
    const { effectiveTheme, refreshActiveSiteTheme } = useTheme()
    let christmasButtonSnowEngine = null
    let stopThemeWatch = null

    setGlobalToast(toast)
    applyFontSizePreference()
    void refreshActiveSiteTheme()
    provide('sidebarVisible', sidebarVisible)
    provide('toast', toast)
    provide('confirm', confirm)

    const syncChristmasButtonSnow = (theme) => {
      if (theme === 'christmas') christmasButtonSnowEngine?.start()
      else christmasButtonSnowEngine?.stop()
    }

    onMounted(() => {
      // PrimeVue dialogs teleport into body, so body is the bounded host for app UI and overlays.
      christmasButtonSnowEngine = createChristmasButtonSnowEngine({ root: document.body })
      syncChristmasButtonSnow(effectiveTheme.value)
      stopThemeWatch = watch(effectiveTheme, syncChristmasButtonSnow, { flush: 'post' })
    })

    onBeforeUnmount(() => {
      stopThemeWatch?.()
      christmasButtonSnowEngine?.stop()
      stopThemeWatch = null
      christmasButtonSnowEngine = null
    })

    const toggleSidebar = () => {
      sidebarVisible.value = !sidebarVisible.value
    }

    return {
      toggleSidebar,
      locale,
      effectiveTheme,
      CHRISTMAS_BACKGROUND_SNOWFLAKES,
      CHRISTMAS_DECORATIVE_SNOWFLAKES,
    }
  },
}
</script>

<style>
:root {
  --navbar-height: 60px;
}

html,
body,
#app {
  height: 100%;
  margin: 0;
  padding: 0;
  max-width: 100%;
  min-width: 0;
  overflow-x: hidden;
}

*,
*::before,
*::after {
  box-sizing: border-box;
}

#app {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.navbar {
  height: var(--navbar-height);
  z-index: 100;
}

.content-container {
  height: calc(100vh - var(--navbar-height));
  overflow-y: auto;
  overflow-x: hidden;
  min-width: 0;
  max-width: 100%;
}

@supports (height: 100svh) {
  .content-container {
    height: calc(100svh - var(--navbar-height));
  }
}

/*
 * The global ConfirmDialog teleports to body, so its owner identity must live
 * on the teleported root instead of relying on a route container.
 */
html[data-effective-theme='christmas'] body .p-dialog.app-global-confirm-dialog {
  --bg-primary: #3e5f72;
  --bg-secondary: #293f52;
  --surface-card: #3e5f72;
  --surface-ground: #293f52;
  --border-color: rgba(222, 199, 142, 0.32);
  --text-color: #f5eedc;
  --text-color-secondary: #c5d5d2;
  --text-primary: #f8f2e8;
  --text-secondary: #c5d5d2;
  overflow: hidden;
  border: 1px solid rgba(222, 199, 142, 0.36);
  color: #f5eedc;
  background: #3e5f72 !important;
  background-image: none !important;
  color-scheme: dark;
}

html[data-effective-theme='christmas'] body .p-dialog.app-global-confirm-dialog .p-dialog-header {
  border-bottom: 1px solid rgba(222, 199, 142, 0.32);
  color: #f8f2e8;
  background: #293f52 !important;
  background-image: none !important;
}

html[data-effective-theme='christmas'] body .p-dialog.app-global-confirm-dialog .p-dialog-title,
html[data-effective-theme='christmas']
  body
  .p-dialog.app-global-confirm-dialog
  .p-dialog-close-button {
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] body .p-dialog.app-global-confirm-dialog .p-dialog-content,
html[data-effective-theme='christmas'] body .p-dialog.app-global-confirm-dialog .p-dialog-footer {
  border-color: rgba(222, 199, 142, 0.24);
  color: #f5eedc;
  background: #3e5f72 !important;
  background-image: none !important;
}
</style>
