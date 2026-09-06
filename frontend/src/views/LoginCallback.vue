<template>
  <div class="login-callback h-full flex align-items-center justify-content-center">
    <div class="login-callback-panel text-center px-4 w-full max-w-md">
      <div v-if="errorMessage">
        <Card class="login-callback-card border-round shadow-2">
          <template #title>
            <div class="login-callback-error-title text-xl mb-1">
              {{ $t('登入失敗') }}
            </div>
          </template>
          <template #content>
            <p class="login-callback-message mb-4">
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
  methods: {
    goToHome() {
      this.$router.push('/')
    },
  },
  async mounted() {
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
}
</script>

<style scoped>
.login-callback {
  min-width: 0;
  overflow-x: hidden;
  background: var(--bg-primary);
}

.login-callback-panel,
.login-callback-message {
  color: var(--text-secondary);
}

.login-callback-error-title {
  color: #f87171;
}

:deep(.login-callback-card) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
}

:deep(.login-callback-card .p-card-title) {
  text-align: center;
}

:deep(.login-callback-card .p-card-content) {
  padding-bottom: 0;
  text-align: center;
}
</style>

<style>
html[data-effective-theme='christmas'] .login-callback {
  background: transparent;
}

html[data-effective-theme='christmas'] .login-callback .login-callback-panel {
  color: #f5eedc;
}

html[data-effective-theme='christmas'] .login-callback .login-callback-card {
  border: 1px solid rgba(222, 199, 142, 0.46);
  border-left: 0.25rem solid #793941;
  background: #3e5f72;
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] .login-callback .login-callback-card .p-card-title {
  padding: 0.9rem;
  border-bottom: 1px solid rgba(222, 199, 142, 0.38);
  border-radius: 0.45rem;
  background: #293f52;
}

html[data-effective-theme='christmas'] .login-callback .login-callback-error-title {
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] .login-callback .login-callback-message {
  color: #f5eedc;
}

html[data-effective-theme='christmas'] .login-callback .loading-container {
  padding: 1.5rem;
  border: 1px solid rgba(222, 199, 142, 0.46);
  border-radius: 0.75rem;
  background: #293f52;
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] .login-callback .p-progressspinner-circle {
  stroke: #dec78e;
}
</style>
