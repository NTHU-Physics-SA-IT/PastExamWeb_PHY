<template>
  <div id="app" class="flex flex-column">
    <Toast position="bottom-right" />
    <ConfirmDialog />
    <Navbar class="navbar px-1" @toggle-sidebar="toggleSidebar" />
    <div class="content-container">
      <router-view :key="locale" />
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
import { useI18n } from 'vue-i18n'

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

    setGlobalToast(toast)
    applyFontSizePreference()
    provide('sidebarVisible', sidebarVisible)
    provide('toast', toast)
    provide('confirm', confirm)

    const toggleSidebar = () => {
      sidebarVisible.value = !sidebarVisible.value
    }

    return {
      toggleSidebar,
      locale,
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
</style>
