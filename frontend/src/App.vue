<template>
  <div id="app" class="flex flex-column" :class="{ 'recovery-review-mode': isRecoveryReview }">
    <Toast position="bottom-right" />
    <ConfirmDialog />
    <div
      v-if="isRecoveryReview"
      class="recovery-review-banner"
      role="status"
      aria-label="Recovery Review 唯讀環境"
    >
      <strong>{{ recoveryReviewLabel }}</strong>
      <span>此環境不會修改原資料，也不是正式網站</span>
    </div>
    <Navbar class="navbar px-1" @toggle-sidebar="toggleSidebar" />
    <div class="content-container">
      <router-view />
    </div>
  </div>
</template>

<script>
import Navbar from './components/Navbar.vue'
import { provide, ref } from 'vue'
import Toast from 'primevue/toast'
import ConfirmDialog from 'primevue/confirmdialog'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { setGlobalToast } from './utils/toast'
import { applyFontSizePreference } from './utils/fontSizePreference'
import { isRecoveryReview, recoveryReviewLabel } from './utils/environment'

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

    setGlobalToast(toast)
    applyFontSizePreference()
    if (isRecoveryReview && typeof document !== 'undefined') {
      document.title = 'Recovery Review｜清大物理考古系統'
    }

    provide('sidebarVisible', sidebarVisible)
    provide('toast', toast)
    provide('confirm', confirm)

    const toggleSidebar = () => {
      sidebarVisible.value = !sidebarVisible.value
    }

    return {
      isRecoveryReview,
      recoveryReviewLabel,
      toggleSidebar,
    }
  },
}
</script>

<style>
:root {
  --navbar-height: 60px;
  --environment-banner-height: 0px;
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

.recovery-review-mode {
  --environment-banner-height: 52px;
}

.recovery-review-mode .content-container {
  height: calc(100vh - var(--navbar-height) - var(--environment-banner-height));
}

.recovery-review-banner {
  display: flex;
  min-height: var(--environment-banner-height);
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.25rem 0.8rem;
  padding: 0.55rem 1rem;
  border-bottom: 1px solid color-mix(in srgb, #b7791f 45%, var(--border-color));
  background: color-mix(in srgb, #f7c948 20%, var(--bg-primary));
  color: var(--text-primary);
  font-size: var(--app-font-size-sm);
  text-align: center;
  z-index: 110;
}

.recovery-review-banner strong {
  color: color-mix(in srgb, #8a5a00 82%, var(--text-primary));
}

.dark .recovery-review-banner strong {
  color: #ffd166;
}

@supports (height: 100svh) {
  .content-container {
    height: calc(100svh - var(--navbar-height));
  }

  .recovery-review-mode .content-container {
    height: calc(100svh - var(--navbar-height) - var(--environment-banner-height));
  }
}

@media (max-width: 640px) {
  .recovery-review-mode {
    --environment-banner-height: 68px;
  }

  .recovery-review-banner {
    flex-direction: column;
  }
}
</style>
