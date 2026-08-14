<template>
  <div
    class="login-callback physics-background h-full flex align-items-center justify-content-center"
  >
    <div class="text-center px-4 w-full max-w-md" :style="{ color: 'var(--text-secondary)' }">
      <div v-if="errorMessage">
        <Card class="border-round shadow-2" :style="{ backgroundColor: 'var(--bg-secondary)' }">
          <template #title>
            <div class="text-red-400 text-xl mb-1">{{ $t('登入失敗') }}</div>
          </template>
          <template #content>
            <p :style="{ color: 'var(--text-secondary)' }" class="mb-4">
              {{ errorMessage }}
            </p>
            <Button
              :label="$t('返回首頁')"
              icon="pi pi-home"
              @click="goToHome"
              class="p-button-secondary"
            />
          </template>
        </Card>
      </div>
      <div v-else class="loading-container">
        <ProgressSpinner strokeWidth="4" class="mb-4" />
        <p>{{ $t('驗證中...') }}</p>
      </div>
    </div>
  </div>
</template>

<script>
import { useTheme } from '../utils/useTheme'
import { getFieldBgSvg } from '../utils/svgBg'
import { authService } from '../api'
import { setToken } from '../utils/auth'
import { STORAGE_KEYS, removeSessionItem } from '../utils/storage'

const PROVIDER_ERROR_MESSAGES = {
  oauth_not_in_school: '目前僅限在校生登入。',
  oauth_account_link_required: '此帳號需要管理員協助連結後才能登入。',
  oauth_account_deleted: '此帳號目前無法登入，請聯絡管理員。',
  oauth_profile_conflict: '帳號資料需要管理員協助處理後才能登入。',
  oauth_identity_conflict: '帳號資料需要管理員協助處理後才能登入。',
  oauth_department_not_allowed: '目前網站僅開放指定的清大成員登入，您的身分不在開放範圍內。',
  oauth_state_invalid: '登入驗證已失效，請重新登入。',
}

export default {
  data() {
    return {
      errorMessage: '',
    }
  },
  setup() {
    const { isDarkTheme } = useTheme()
    return {
      isDarkTheme,
    }
  },
  methods: {
    goToHome() {
      this.$router.push('/')
    },
    setBg() {
      const el = document.querySelector('.physics-background')
      if (el) {
        el.style.setProperty('background-image', getFieldBgSvg())
      }
    },
  },
  async mounted() {
    this.setBg()
    const urlParams = new URLSearchParams(window.location.search)
    const code = urlParams.get('code')
    const providerError = urlParams.get('error')

    // Remove the one-time code before making any network request.
    window.history.replaceState({}, document.title, window.location.pathname)

    if (providerError) {
      this.errorMessage = this.$t(
        PROVIDER_ERROR_MESSAGES[providerError] || '驗證失敗，請重新登入或聯絡管理員。'
      )
      return
    }

    try {
      if (!code) {
        this.errorMessage = this.$t('登入驗證已失效，請重新登入。')
        return
      }

      const response = await authService.exchangeNthuCode(code)
      if (typeof response?.access_token !== 'string' || !response.access_token) {
        throw new Error('Invalid login exchange response')
      }
      removeSessionItem(STORAGE_KEYS.session.NOTIFICATION_LOGIN_CHECKED)
      setToken(response.access_token)
      this.$router.replace('/archive')
    } catch {
      this.errorMessage = this.$t('驗證失敗，請重試或聯絡管理員。')
    }
  },
  watch: {
    isDarkTheme() {
      this.setBg()
    },
  },
}
</script>

<style scoped>
.physics-background {
  position: relative;
}

.physics-background::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;

  animation: scrollBackground 120s linear infinite;
  pointer-events: none;
  z-index: 0;
}

@keyframes scrollBackground {
  from {
    background-position: 0 0;
  }
  to {
    background-position: 300% 300%;
  }
}

.physics-background > div {
  position: relative;
  z-index: 1;
}

:deep(.p-card) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

:deep(.p-card .p-card-title) {
  text-align: center;
}

:deep(.p-card .p-card-content) {
  padding-bottom: 0;
  text-align: center;
}
</style>
