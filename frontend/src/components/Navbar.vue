<template>
  <div class="card" :class="{ 'navbar-dark': isDarkTheme }">
    <Menubar :model="menuItems">
      <template #start>
        <div class="nav-brand-cluster">
          <Button
            v-if="$route.path === '/archive'"
            :icon="'pi pi-bars'"
            severity="secondary"
            size="small"
            text
            class="sidebar-toggle"
            @click="$emit('toggle-sidebar')"
          />
          <button class="brand-lockup clickable-title" type="button" @click="handleTitleClick">
            <span class="brand-mark-frame">
              <img src="/physics-symbol.png" alt="清大物理考古系統" class="brand-mark" />
            </span>
            <span class="brand-wordmark">
              <span class="brand-title-main">清大物理考古系統</span>
              <span class="brand-title-sub">Physics Archive · NTHU</span>
            </span>
          </button>
        </div>
      </template>
      <template #end>
        <div class="nav-control-cluster">
          <div class="hidden md:flex align-items-center gap-2 nav-action-group">
            <span v-if="isAuthenticated" class="user-name flex align-items-center">{{
              userData?.name || 'User'
            }}</span>
            <Button
              v-if="canAccessAdmin"
              icon="pi pi-cog"
              label="管理中心"
              severity="secondary"
              size="small"
              text
              @click="handleNavigateAdmin"
              aria-label="管理中心"
            />
            <Button
              v-if="moreActions.length"
              icon="pi pi-list"
              label="功能列表"
              severity="secondary"
              size="small"
              text
              @click="toggleMoreActions($event)"
              aria-label="More actions"
            />
            <Button
              v-if="isAuthenticated"
              icon="pi pi-sign-out"
              label="登出"
              @click="handleLogout"
              severity="secondary"
              size="small"
              text
              aria-label="Logout"
            />
            <Button
              v-else
              icon="pi pi-sign-in"
              label="登入"
              @click="openLoginDialog"
              severity="secondary"
              size="small"
              text
              aria-label="Login"
              aria-haspopup="dialog"
              :aria-expanded="loginVisible"
            />
          </div>

          <div class="flex md:hidden align-items-center gap-2 nav-action-group">
            <Button
              v-if="canAccessAdmin"
              icon="pi pi-cog"
              @click="handleNavigateAdmin"
              severity="secondary"
              size="small"
              text
              aria-label="管理中心"
              title="管理中心"
            />
            <Button
              v-if="moreActions.length"
              icon="pi pi-list"
              @click="toggleMoreActions($event)"
              severity="secondary"
              size="small"
              text
              aria-label="More actions"
            />
            <Button
              v-else
              icon="pi pi-sign-in"
              @click="openLoginDialog"
              severity="secondary"
              size="small"
              text
              aria-label="Login"
              aria-haspopup="dialog"
              :aria-expanded="loginVisible"
            />
          </div>

          <Button
            :icon="isDarkTheme ? 'pi pi-sun' : 'pi pi-moon'"
            :aria-label="isDarkTheme ? '切換至淺色模式' : '切換至深色模式'"
            severity="secondary"
            size="small"
            text
            class="theme-toggle-button"
            @click="handleToggleTheme"
          />
        </div>
        <Menu ref="moreActionsMenu" :model="moreActions" :popup="true">
          <template #item="{ item, props }">
            <a v-bind="props.action" class="flex align-items-center gap-2">
              <span :class="item.icon" />
              <span class="flex-1">{{ item.label }}</span>
              <Badge v-if="item.badge" :value="item.badge" severity="danger" />
            </a>
          </template>
        </Menu>
      </template>
    </Menubar>

    <NotificationModal
      v-if="isAuthenticated"
      :visible="notificationStore.state.modalVisible"
      :summary="notificationStore.state.unreadSummary"
      @update:visible="handleNotificationModalVisible"
      @open-center="() => openNotificationCenter('notification-modal')"
      @mark-all-read="handleMarkAllRead"
      @view-announcement="handleSummaryAnnouncement"
      @view-personal="handleSummaryPersonal"
    />
    <NotificationCenterModal
      v-if="isAuthenticated"
      :visible="notificationStore.state.centerVisible"
      :announcements="notificationStore.state.announcements"
      :personal-notifications="notificationStore.state.personalNotifications"
      :counts="notificationStore.state.counts"
      :loading="notificationStore.state.loadingCenter"
      :focus-type="notificationFocusType"
      :focus-id="notificationFocusId"
      :deleting-personal-id="deletingPersonalNotificationId"
      :deleting-all-personal="deletingAllPersonalNotifications"
      @update:visible="handleNotificationCenterVisible"
      @mark-announcement-read="notificationStore.markAnnouncementRead"
      @mark-personal-read="notificationStore.markPersonalRead"
      @mark-all-personal-read="notificationStore.markAllPersonalRead"
      @delete-personal="handleDeletePersonalNotification"
      @delete-all-personal="handleDeleteAllPersonalNotifications"
      @open-personal-source="handlePersonalNotificationSource"
    />

    <Dialog
      :visible="loginVisible"
      @update:visible="loginVisible = $event"
      header="登入"
      :modal="true"
      :draggable="false"
      :closeOnEscape="false"
      :style="{ width: '350px', maxWidth: '85vw' }"
      :autoFocus="false"
    >
      <div class="p-fluid w-full">
        <div class="field mt-2 w-full">
          <FloatLabel variant="on" class="w-full">
            <InputText
              id="username"
              name="username"
              v-model="username"
              class="w-full"
              @keyup.enter="handleLocalLogin"
            />
            <label for="username">帳號</label>
          </FloatLabel>
        </div>
        <div class="field mt-3 w-full">
          <FloatLabel variant="on" class="w-full">
            <Password
              inputId="password"
              name="password"
              v-model="password"
              toggleMask
              :feedback="false"
              class="w-full"
              inputClass="w-full"
              @keyup.enter="handleLocalLogin"
            />
            <label for="password">密碼</label>
          </FloatLabel>
        </div>
        <div class="field mt-4">
          <Button
            label="登入"
            type="submit"
            class="p-button-primary w-full"
            @click="handleLocalLogin"
            :loading="loading"
          />
        </div>
      </div>
    </Dialog>

    <Dialog
      :visible="issueReportVisible"
      @update:visible="handleIssueReportDialogClose"
      :modal="true"
      :draggable="false"
      :closeOnEscape="true"
      :style="{ width: '700px', maxWidth: '90vw' }"
      class="issue-report-dialog"
      :pt="{ root: { 'aria-label': '系統問題回報', 'aria-labelledby': null } }"
    >
      <template #header>
        <div class="flex align-items-center gap-2.5">
          <i class="pi pi-comments text-2xl" />
          <div class="text-xl leading-tight font-semibold">系統問題回報</div>
        </div>
      </template>
      <div class="p-fluid w-full">
        <div class="field">
          <label for="issue-type" class="font-semibold">問題類型</label>
          <Select
            inputId="issue-type"
            name="issue-type"
            v-model="issueForm.type"
            :options="issueTypes"
            optionLabel="label"
            optionValue="value"
            placeholder="選擇問題類型"
            class="w-full mt-2"
          />
        </div>

        <div class="field mt-3">
          <label for="issue-title" class="font-semibold">問題標題</label>
          <InputText
            id="issue-title"
            name="issue-title"
            v-model="issueForm.title"
            placeholder="簡短描述遇到的問題"
            class="w-full mt-2"
            :maxlength="100"
          />
          <small class="text-gray-500">{{ issueForm.title.length }}/100</small>
        </div>

        <div class="field mt-3">
          <label for="issue-description" class="font-semibold">詳細描述</label>
          <Textarea
            id="issue-description"
            name="issue-description"
            v-model="issueForm.description"
            placeholder="請詳細描述遇到的問題，包括：&#10;1. 操作步驟&#10;2. 預期結果&#10;3. 實際結果"
            class="w-full mt-2"
            rows="8"
            :maxlength="2000"
          />
          <small class="text-gray-500">{{ issueForm.description.length }}/2000</small>
        </div>

        <div class="field mt-3">
          <label for="user-info" class="font-semibold">聯絡方式 (選填)</label>
          <InputText
            id="user-info"
            name="user-info"
            v-model="issueForm.contact"
            placeholder="Email 或其他聯絡方式，方便我們回覆"
            class="w-full mt-2"
          />
        </div>

        <div class="flex justify-between gap-3 mt-4">
          <Button
            label="取消"
            icon="pi pi-times"
            severity="secondary"
            outlined
            @click="closeIssueReportDialog"
            class="flex-1"
          />
          <Button
            label="建立回報並前往 GitHub"
            icon="pi pi-external-link"
            @click="submitIssueReport"
            :disabled="!canSubmitIssue"
            :loading="issueSubmitting"
            class="flex-1"
          />
        </div>

        <div class="mt-3 p-3 bg-blue-50 border-round text-sm flex align-items-start">
          <i class="pi pi-info-circle text-blue-600 mr-2 mt-1"></i>
          <span class="text-blue-800 line-height-3" style="overflow-wrap: anywhere">
            系統會先保存本地回報摘要，再開啟 GitHub 預填 Issue 頁面。<br />
            請先在目前瀏覽器登入 GitHub，否則登入後可能無法正確返回預填頁面。<br />
            GitHub Issue 仍需由您在 GitHub 頁面確認送出後才會正式建立。
          </span>
        </div>
      </div>
    </Dialog>
  </div>
</template>

<script>
import { getCurrentUser, isAuthenticated, setToken } from '../utils/auth.js'
import { useTheme } from '../utils/useTheme'
import { authService, reportService } from '../api'
import { useRouter } from 'vue-router'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { trackEvent, EVENTS } from '../utils/analytics'
import { useNotifications } from '../utils/useNotifications'
import NotificationModal from './NotificationModal.vue'
import NotificationCenterModal from './NotificationCenterModal.vue'
import {
  STORAGE_KEYS,
  removeLocalItem,
  removeSessionItem,
  getLocalJson,
  getLocalItem,
  getSessionJson,
} from '../utils/storage'

export default {
  name: 'AppNavbar',
  components: {
    NotificationModal,
    NotificationCenterModal,
  },
  emits: ['toggle-sidebar'],
  data() {
    return {
      loginVisible: false,
      username: '',
      password: '',
      isAuthenticated: false,
      userData: null,
      loading: false,
      issueReportVisible: false,
      issueSubmitting: false,
      issueForm: {
        type: '',
        title: '',
        description: '',
        contact: '',
      },
      viewportWidth: typeof window === 'undefined' ? 1024 : window.innerWidth,
      heartbeatIntervalMs: 60000,
      heartbeatTimer: null,
      notificationFocusType: null,
      notificationFocusId: null,
      deletingPersonalNotificationId: null,
      deletingAllPersonalNotifications: false,
      issueTypes: [
        { label: 'Bug / 程式錯誤', value: 'bug' },
        { label: '功能建議', value: 'enhancement' },
        { label: '效能問題', value: 'performance' },
        { label: 'UI/UX 問題', value: 'ui-ux' },
        { label: '其他問題', value: 'question' },
      ],
    }
  },
  setup() {
    const { isDarkTheme, toggleTheme } = useTheme()
    const router = useRouter()
    const toast = useToast()
    const confirm = useConfirm()
    const notificationStore = useNotifications()

    return {
      isDarkTheme,
      toggleTheme,
      router,
      toast,
      confirm,
      notificationStore,
    }
  },
  mounted() {
    if (typeof window !== 'undefined') {
      this.updateViewportWidth()
      window.addEventListener('resize', this.updateViewportWidth, { passive: true })
    }
    this.checkAuthentication()
    if (this.isAuthenticated) {
      void this.initializeNotifications()
      void this.startHeartbeat()
    }

    setInterval(() => {
      const focusedElements = document.querySelectorAll(
        '.p-menubar .p-focus, .p-menubar .p-highlight, .p-menubar [tabindex="0"]'
      )
      focusedElements.forEach((el) => {
        el.classList.remove('p-focus', 'p-highlight')
        if (el.tabIndex >= 0) {
          el.blur()
        }
      })
    }, 500)

    if (typeof window !== 'undefined') {
      const namespaceKey = '__pastexam'
      const namespace = (window[namespaceKey] = window[namespaceKey] || {})
      Object.defineProperty(namespace, 'openLoginModal', {
        value: () => {
          this.openLoginDialog()
        },
        configurable: true,
      })
    }
  },

  beforeUnmount() {
    if (typeof window !== 'undefined') {
      window.removeEventListener('resize', this.updateViewportWidth)
    }
    this.stopHeartbeat()

    if (typeof window !== 'undefined' && window.__pastexam) {
      delete window.__pastexam.openLoginModal
    }
  },

  watch: {
    $route: {
      immediate: true,
      handler() {
        this.checkAuthentication()
        this.$nextTick(() => {
          const focusedElements = document.querySelectorAll(
            '.p-menubar .p-menuitem-content, .p-menubar .p-menuitem-link, .p-menubar .p-focus, .p-menubar .p-highlight'
          )
          focusedElements.forEach((el) => {
            el.blur()
            el.classList.remove('p-focus', 'p-highlight')
          })
        })
      },
    },
    isAuthenticated(newValue) {
      if (newValue) {
        void this.initializeNotifications()
        void this.startHeartbeat()
      } else {
        this.stopHeartbeat()
        this.notificationStore.state.modalVisible = false
        this.notificationStore.state.centerVisible = false
        this.notificationStore.state.active = []
        this.notificationStore.state.all = []
        this.notificationStore.state.initialized = false
        this.notificationStore.resetForLogout?.()
      }
    },
  },
  methods: {
    updateViewportWidth() {
      if (typeof window !== 'undefined') this.viewportWidth = window.innerWidth
    },

    toggleMoreActions(event) {
      if (!this.moreActions.length) {
        return
      }

      trackEvent(EVENTS.OPEN_MORE_ACTIONS_MENU, {
        items: this.moreActions.length,
        viewport: this.isDesktopView ? 'desktop' : 'mobile',
      })

      if (this.$refs.moreActionsMenu?.toggle) {
        this.$refs.moreActionsMenu.toggle(event)
      }
    },

    invokeMenuAction(action) {
      if (this.$refs.moreActionsMenu?.hide) {
        this.$refs.moreActionsMenu.hide()
      }

      if (typeof action === 'function') {
        action()
      }
    },

    handleNotificationModalVisible(value) {
      this.notificationStore.state.modalVisible = value
    },

    handleNotificationDismiss(notification) {
      this.notificationStore.markNotificationAsSeen?.(notification)
      this.notificationStore.state.modalVisible = false
    },

    handleNotificationDetailSeen(notification) {
      this.notificationStore.markNotificationAsSeen?.(notification)
    },

    handleNotificationCenterVisible(value) {
      this.notificationStore.state.centerVisible = value
      if (!value) {
        this.notificationFocusType = null
        this.notificationFocusId = null
      }
    },

    async initializeNotifications() {
      await this.notificationStore.initNotifications()
    },

    async openNotificationCenter(source = 'navbar') {
      if (!this.isAuthenticated) {
        this.toast.add({
          severity: 'warn',
          summary: '請先登入',
          detail: '登入後即可檢視公告與個人通知',
          life: 3000,
        })
        return
      }

      this.notificationStore.state.modalVisible = false
      this.notificationFocusType = null
      this.notificationFocusId = null
      trackEvent(EVENTS.OPEN_NOTIFICATION_CENTER, { from: source })
      await this.notificationStore.openCenter()
    },

    async handleMarkAllRead() {
      await this.notificationStore.markAllRead()
    },

    async handleSummaryAnnouncement(id) {
      await this.notificationStore.markAnnouncementRead(id)
      this.notificationFocusType = 'announcement'
      this.notificationFocusId = id
      this.notificationStore.state.modalVisible = false
      this.notificationStore.state.centerVisible = true
      trackEvent(EVENTS.OPEN_NOTIFICATION_CENTER, { from: 'summary-announcement' })
    },

    async handleSummaryPersonal(id) {
      await this.notificationStore.markPersonalRead(id)
      this.notificationFocusType = 'personal'
      this.notificationFocusId = id
      this.notificationStore.state.modalVisible = false
      this.notificationStore.state.centerVisible = true
      trackEvent(EVENTS.OPEN_NOTIFICATION_CENTER, { from: 'summary-personal' })
    },

    async handlePersonalNotificationSource(item) {
      const metadata = item?.metadata || {}
      this.notificationStore.state.centerVisible = false
      if (item?.source_type === 'archive_submission') {
        await this.$router.push({
          path: '/archive',
          query: {
            showSubmissionStatus: '1',
            submissionId: metadata.submission_id || item.source_id,
          },
        })
        return
      }
      if (item?.source_type === 'archive_discussion_thread') {
        await this.$router.push({
          path: '/archive',
          query: {
            courseId: metadata.course_id,
            archiveId: metadata.archive_id,
            threadId: metadata.thread_id || item.source_id,
            messageId: metadata.message_id || metadata.reply_message_id || item.source_message_id,
          },
        })
      }
    },

    async deletePersonalNotification(item) {
      if (!item?.id || this.deletingPersonalNotificationId) return
      this.deletingPersonalNotificationId = item.id
      try {
        await this.notificationStore.deletePersonalNotification(item.id)
        this.toast.add({
          severity: 'success',
          summary: '通知已刪除',
          detail: '這則個人通知已永久刪除',
          life: 3000,
        })
      } catch (error) {
        console.error('Delete personal notification error:', error)
        this.toast.add({
          severity: 'error',
          summary: '刪除失敗',
          detail: '無法刪除通知，請稍後再試',
          life: 3000,
        })
      } finally {
        this.deletingPersonalNotificationId = null
      }
    },

    handleDeletePersonalNotification(item) {
      this.confirm.require({
        header: '刪除這則通知？',
        message: '通知刪除後無法復原，也不會進入垃圾桶。',
        icon: 'pi pi-exclamation-triangle',
        rejectLabel: '取消',
        acceptLabel: '刪除',
        acceptClass: 'p-button-danger',
        accept: () => this.deletePersonalNotification(item),
      })
    },

    async deleteAllPersonalNotifications() {
      if (this.deletingAllPersonalNotifications) return
      this.deletingAllPersonalNotifications = true
      try {
        await this.notificationStore.deleteAllPersonalNotifications()
        this.toast.add({
          severity: 'success',
          summary: '已刪除全部個人通知',
          detail: '所有個人通知已永久刪除',
          life: 3000,
        })
      } catch (error) {
        console.error('Delete all personal notifications error:', error)
        this.toast.add({
          severity: 'error',
          summary: '刪除失敗',
          detail: '無法刪除全部個人通知，請稍後再試',
          life: 3000,
        })
      } finally {
        this.deletingAllPersonalNotifications = false
      }
    },

    handleDeleteAllPersonalNotifications() {
      this.confirm.require({
        header: '刪除全部個人通知？',
        message: '這會永久刪除你的所有個人通知，刪除後無法復原，也不會進入垃圾桶。',
        icon: 'pi pi-exclamation-triangle',
        rejectLabel: '取消',
        acceptLabel: '全部刪除',
        acceptClass: 'p-button-danger',
        accept: () => this.deleteAllPersonalNotifications(),
      })
    },

    handleToggleTheme() {
      trackEvent(EVENTS.TOGGLE_THEME, {
        from: this.isDarkTheme ? 'dark' : 'light',
        to: this.isDarkTheme ? 'light' : 'dark',
      })
      this.toggleTheme()
    },

    openLoginDialog() {
      this.loginVisible = true
      trackEvent(EVENTS.LOGIN, { type: 'dialog-open' })
    },

    async handleLocalLogin() {
      if (!this.username || !this.password) {
        this.toast.add({
          severity: 'error',
          summary: '錯誤',
          detail: '請輸入帳號和密碼',
          life: 3000,
        })
        return
      }

      this.loading = true
      try {
        const response = await authService.localLogin(this.username, this.password)
        this.notificationStore?.beginLoginSession?.()
        setToken(response.access_token)
        this.loginVisible = false
        this.checkAuthentication()
        this.username = ''
        this.password = ''

        trackEvent(EVENTS.LOGIN_LOCAL, { success: true })

        await this.router.push('/archive')
      } catch (error) {
        console.error('Login failed:', error)
        trackEvent(EVENTS.LOGIN_LOCAL, { success: false })
        this.toast.add({
          severity: 'error',
          summary: '登入失敗',
          detail: '帳號或密碼錯誤',
          life: 3000,
        })
      } finally {
        this.loading = false
      }
    },

    checkAuthentication() {
      this.isAuthenticated = isAuthenticated()
      if (this.isAuthenticated) {
        const user = getCurrentUser()
        if (user) {
          this.userData = user
        } else {
          this.isAuthenticated = false
          this.userData = null
        }
      } else {
        this.isAuthenticated = false
        this.userData = null
      }
    },

    async handleLogout() {
      try {
        await authService.logout()
        trackEvent(EVENTS.LOGOUT, { success: true })
      } catch (error) {
        console.error('Logout API failed:', error)
        trackEvent(EVENTS.LOGOUT, { success: false })
      }

      removeSessionItem(STORAGE_KEYS.session.AUTH_TOKEN)
      removeLocalItem(STORAGE_KEYS.local.SELECTED_SUBJECT)
      removeLocalItem(STORAGE_KEYS.local.ADMIN_CURRENT_TAB)
      this.notificationStore.resetForLogout?.()
      this.isAuthenticated = false
      this.userData = null

      await this.$router.push('/')
    },

    handleTitleClick() {
      if (this.isAuthenticated) {
        trackEvent(EVENTS.NAVIGATE_ARCHIVE, { from: 'title-click' })
        this.$router.push('/archive')
      }
    },

    handleNavigateAdmin() {
      trackEvent(EVENTS.NAVIGATE_ADMIN, { from: 'navbar' })
      this.$router.push('/admin')
    },

    handleNavigatePersonalSettings() {
      this.$router.push('/personal-settings')
    },

    openIssueReportDialog() {
      this.issueReportVisible = true
      trackEvent(EVENTS.OPEN_ISSUE_REPORT)
    },

    closeIssueReportDialog() {
      this.issueReportVisible = false
      this.issueForm = {
        type: '',
        title: '',
        description: '',
        contact: '',
      }
    },

    handleIssueReportDialogClose(visible) {
      this.issueReportVisible = visible
      if (!visible) {
        this.issueForm = {
          type: '',
          title: '',
          description: '',
          contact: '',
        }
      }
    },

    async startHeartbeat() {
      if (this.heartbeatTimer || !this.isAuthenticated) {
        return
      }

      await this.sendHeartbeat(false)
      this.heartbeatTimer = setInterval(() => {
        void this.sendHeartbeat(true)
      }, this.heartbeatIntervalMs)
    },

    stopHeartbeat() {
      if (this.heartbeatTimer) {
        clearInterval(this.heartbeatTimer)
        this.heartbeatTimer = null
      }
    },

    async sendHeartbeat(refreshNotificationCounts = false) {
      if (!this.isAuthenticated) {
        return
      }

      try {
        await authService.heartbeat()
        if (refreshNotificationCounts) {
          await this.notificationStore.refreshCounts?.()
        }
      } catch (error) {
        if (error?.response?.status !== 401) {
          console.debug('Heartbeat failed:', error?.message || error)
        }
      }
    },

    async submitIssueReport() {
      const { type, title, description, contact } = this.issueForm
      if (!this.canSubmitIssue || this.issueSubmitting) return

      trackEvent(EVENTS.SUBMIT_ISSUE_REPORT, {
        type,
        hasContact: !!contact,
        titleLength: title.length,
        descriptionLength: description.length,
      })

      this.issueSubmitting = true
      try {
        const systemInfo = this.getSystemInfo()
        await reportService.createSystemIssue({
          report_type: type,
          title: title.trim(),
          description: description.trim(),
          contact: contact.trim() || null,
          metadata: systemInfo,
        })
        const issueBody = this.formatIssueBody(description, contact, systemInfo, type)
        const githubUrl =
          'https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/issues/new?' +
          `title=${encodeURIComponent(title)}&body=${encodeURIComponent(issueBody)}`
        window.open(githubUrl, '_blank', 'noopener,noreferrer')
        this.closeIssueReportDialog()
        this.toast.add({
          severity: 'success',
          summary: '回報摘要已保存',
          detail: '已開啟 GitHub 預填頁面，請在 GitHub 完成送出',
          life: 4000,
        })
      } catch (error) {
        console.error('Submit system issue report error:', error)
        this.toast.add({
          severity: 'error',
          summary: '回報建立失敗',
          detail: '尚未開啟 GitHub，請稍後再試',
          life: 3500,
        })
      } finally {
        this.issueSubmitting = false
      }
    },

    getSystemInfo() {
      const nav = navigator
      return {
        userAgent: nav.userAgent,
        platform: nav.platform,
        language: nav.language,
        url: window.location.href,
        route: {
          path: this.$route?.path || null,
          name: this.$route?.name || null,
          fullPath: this.$route?.fullPath || null,
        },
        pageContext: this.getIssuePageContext?.() ?? null,
        timestamp: new Date().toISOString(),
      }
    },

    getIssuePageContext() {
      const context = {
        selectedSubject: null,
        adminCurrentTab: null,
        archiveContext: null,
      }

      try {
        context.selectedSubject = getLocalJson(STORAGE_KEYS.local.SELECTED_SUBJECT)
      } catch {
        context.selectedSubject = null
      }

      try {
        context.adminCurrentTab = getLocalItem(STORAGE_KEYS.local.ADMIN_CURRENT_TAB)
      } catch {
        context.adminCurrentTab = null
      }

      try {
        context.archiveContext = getSessionJson(STORAGE_KEYS.session.ISSUE_CONTEXT)
      } catch {
        context.archiveContext = null
      }

      return context
    },

    getBrowserInfo(userAgent) {
      if (userAgent.includes('Chrome') && !userAgent.includes('Edge')) {
        const chromeMatch = userAgent.match(/Chrome\/(\d+\.\d+)/)
        return chromeMatch ? `Chrome ${chromeMatch[1]}` : 'Chrome'
      } else if (userAgent.includes('Firefox')) {
        const firefoxMatch = userAgent.match(/Firefox\/(\d+\.\d+)/)
        return firefoxMatch ? `Firefox ${firefoxMatch[1]}` : 'Firefox'
      } else if (userAgent.includes('Safari') && !userAgent.includes('Chrome')) {
        const safariMatch = userAgent.match(/Safari\/(\d+\.\d+)/)
        return safariMatch ? `Safari ${safariMatch[1]}` : 'Safari'
      } else if (userAgent.includes('Edge')) {
        const edgeMatch = userAgent.match(/Edge\/(\d+\.\d+)/)
        return edgeMatch ? `Edge ${edgeMatch[1]}` : 'Edge'
      }
      return 'Unknown Browser'
    },

    getOSInfo(platform, userAgent) {
      if (userAgent.includes('Mac OS X')) {
        const macMatch = userAgent.match(/Mac OS X (\d+_\d+)/)
        if (macMatch) {
          const version = macMatch[1].replace('_', '.')
          return `macOS ${version}`
        }
        return 'macOS'
      } else if (userAgent.includes('Windows')) {
        if (userAgent.includes('Windows NT 10.0')) return 'Windows 10/11'
        if (userAgent.includes('Windows NT 6.3')) return 'Windows 8.1'
        if (userAgent.includes('Windows NT 6.1')) return 'Windows 7'
        return 'Windows'
      } else if (userAgent.includes('Linux')) {
        return 'Linux'
      } else if (userAgent.includes('Android')) {
        const androidMatch = userAgent.match(/Android (\d+\.\d+)/)
        return androidMatch ? `Android ${androidMatch[1]}` : 'Android'
      } else if (userAgent.includes('iPhone') || userAgent.includes('iPad')) {
        const iosMatch = userAgent.match(/OS (\d+_\d+)/)
        if (iosMatch) {
          const version = iosMatch[1].replace('_', '.')
          return `iOS ${version}`
        }
        return 'iOS'
      }
      return platform || 'Unknown System'
    },

    formatTimestamp(timestamp) {
      const date = new Date(timestamp)
      const options = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: 'Asia/Taipei',
        hour12: false,
      }
      return date.toLocaleString('zh-TW', options) + ' (UTC+8)'
    },

    formatIssueBody(description, contact, systemInfo, type) {
      let body = ''

      body += `<!-- type: ${type || 'question'} -->\n\n`

      body += '## 問題描述\n\n' + description + '\n\n'

      if (contact) {
        body += '## 聯絡方式\n\n' + contact + '\n\n'
      }

      const browserInfo = this.getBrowserInfo(systemInfo.userAgent)
      const osInfo = this.getOSInfo(systemInfo.platform, systemInfo.userAgent)
      const formattedTime = this.formatTimestamp(systemInfo.timestamp)

      const ctx = systemInfo.pageContext || {}
      const archiveCtx = ctx.archiveContext || {}
      const course = archiveCtx.course || {}
      const preview = archiveCtx.preview || {}
      const filters = archiveCtx.filters || {}

      body += '## 頁面資訊\n\n'
      body += `| 項目 | 資訊 |\n`
      body += `|------|------|\n`
      body += `| 目前頁面 | ${systemInfo.route?.fullPath || systemInfo.url} |\n`
      if (course?.name || ctx.selectedSubject?.label) {
        body += `| 課程 | ${(course?.name || ctx.selectedSubject?.label || '').trim()} |\n`
      }
      if (course?.id || ctx.selectedSubject?.id) {
        body += `| 課程 ID | ${course?.id ?? ctx.selectedSubject?.id} |\n`
      }
      if (filters?.year || filters?.professor || filters?.type || filters?.hasAnswers) {
        body += `| 篩選 | year=${filters?.year || '-'}, professor=${filters?.professor || '-'}, type=${filters?.type || '-'}, hasAnswers=${filters?.hasAnswers ? 'Y' : 'N'} |\n`
      }
      if (filters?.searchQuery) {
        body += `| 搜尋 | ${filters.searchQuery} |\n`
      }
      if (preview?.open) {
        body += `| 預覽 | open=true, archiveId=${preview.archiveId || '-'}, name=${preview.name || '-'} |\n`
      }
      if (systemInfo.route?.path === '/admin' && ctx.adminCurrentTab !== null) {
        body += `| 管理頁籤 | ${ctx.adminCurrentTab} |\n`
      }
      body += '\n'

      body += '## 環境資訊\n\n'
      body += `| 項目 | 資訊 |\n`
      body += `|------|------|\n`
      body += `| 瀏覽器 | ${browserInfo} |\n`
      body += `| 作業系統 | ${osInfo} |\n`
      body += `| 語言設定 | ${systemInfo.language} |\n`
      body += `| 回報時間 | ${formattedTime} |\n\n`

      body += '<details>\n<summary>詳細系統資訊</summary>\n\n'
      body += '```\n'
      body += `User Agent: ${systemInfo.userAgent}\n`
      body += `Platform: ${systemInfo.platform}\n`
      body += `Timestamp: ${systemInfo.timestamp}\n`
      body += `Route: ${JSON.stringify(systemInfo.route || {})}\n`
      body += `Page Context: ${JSON.stringify(systemInfo.pageContext || {})}\n`
      body += '```\n'
      body += '</details>\n\n'

      body += '---\n*此問題由物理系考古題系統自動產生*'

      return body
    },
  },

  computed: {
    isDesktopView() {
      return this.viewportWidth >= 768
    },

    menuItems() {
      return []
    },

    pendingNotification() {
      return this.notificationStore.latestUnseenNotification?.value || null
    },

    canAccessAdmin() {
      return Boolean(this.userData?.is_admin)
    },

    moreActions() {
      if (!this.isAuthenticated) {
        return []
      }

      const items = [
        {
          label: '個人化設定',
          icon: 'pi pi-sliders-h',
          command: () => this.invokeMenuAction(() => this.handleNavigatePersonalSettings()),
        },
        {
          label: '公告與通知',
          icon: 'pi pi-bell',
          badge: this.notificationStore?.unreadTotal?.value || null,
          command: () => this.invokeMenuAction(() => this.openNotificationCenter('navbar-menu')),
        },
        {
          label: '系統問題回報',
          icon: 'pi pi-comments',
          command: () => this.invokeMenuAction(() => this.openIssueReportDialog()),
        },
      ]

      if (this.isAuthenticated && !this.isDesktopView) {
        items.push({ separator: true })
        items.push({
          label: '登出',
          icon: 'pi pi-sign-out',
          command: () => this.invokeMenuAction(() => this.handleLogout()),
        })
      }

      return items
    },

    canSubmitIssue() {
      return this.issueForm.type && this.issueForm.title.trim() && this.issueForm.description.trim()
    },
  },
}
</script>

<style scoped>
.p-dialog .p-dialog-content {
  padding: 1.5rem;
}

.clickable-title {
  cursor: pointer;
  transform: scale(1);
  transform-origin: center center;
  will-change: transform;
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    background 180ms ease !important;
}

.clickable-title:hover {
  transform: translateY(-1px);
}

.card {
  height: var(--navbar-height);
  display: flex;
  align-items: center;
  background: #e4eee9;
  border-bottom: 1px solid #c7d8d0;
  backdrop-filter: none;
}

.card.navbar-dark {
  background: #101614;
  border-bottom-color: #24342f;
}

.nav-brand-cluster,
.nav-control-cluster {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
  min-height: 3rem;
  padding: 0.2rem 0.45rem 0.2rem 0;
  border: 0;
  border-radius: 0;
  color: inherit;
  background: transparent;
  font: inherit;
}

.brand-lockup:hover {
  background: transparent;
}

.brand-mark-frame {
  display: grid;
  place-items: center;
  width: 2.4rem;
  aspect-ratio: 1;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.82);
  border-radius: 8px;
  background: #ffffff;
}

.brand-mark {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.brand-wordmark {
  display: grid;
  gap: 0.12rem;
  min-width: 0;
}

.brand-title-main {
  color: #172522;
  font-size: clamp(1rem, 1.2vw, 1.18rem);
  font-weight: 780;
  letter-spacing: 0.08em;
  line-height: 1;
  text-shadow: none;
  white-space: nowrap;
}

.navbar-dark .brand-title-main {
  color: #eef6ed;
}

.brand-title-sub {
  color: rgba(199, 176, 107, 0.82);
  font-size: 0.58rem;
  font-weight: 760;
  letter-spacing: 0.22em;
  line-height: 1;
  text-transform: uppercase;
}

.nav-control-cluster {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: var(--app-font-size-sm);
}

.nav-action-group {
  padding-right: 0.55rem;
  border-right: 1px solid rgba(23, 37, 34, 0.22);
}

.navbar-dark .nav-action-group {
  border-right-color: rgba(229, 235, 226, 0.22);
}

.sidebar-toggle {
  border-radius: 999px;
}

.theme-toggle-button {
  border-radius: 999px;
}

.user-name {
  display: flex;
  align-items: center;
  line-height: 1;
  margin: auto 0;
  color: rgba(23, 37, 34, 0.78);
  font-size: var(--app-font-size-base);
}

.navbar-dark .user-name {
  color: rgba(229, 235, 226, 0.84);
}

:deep(.p-menubar-end) > div {
  display: flex;
  align-items: center;
  height: 100%;
}

:deep(.p-menubar) {
  width: 100%;
  min-width: 0;
  padding: 0.42rem clamp(0.75rem, 1.6vw, 1.25rem);
  border: 0;
  background: transparent;
}

:deep(.p-button.p-button-text) {
  color: rgba(23, 37, 34, 0.72);
  font-size: var(--app-font-size-sm);
  border-radius: 7px;
}

:deep(.p-button.p-button-text:hover) {
  color: #172522;
  background: rgba(23, 37, 34, 0.08);
}

.navbar-dark :deep(.p-button.p-button-text) {
  color: rgba(229, 235, 226, 0.78);
}

.navbar-dark :deep(.p-button.p-button-text:hover) {
  color: #eef6ed;
  background: rgba(255, 255, 255, 0.08);
}

:deep(.p-password) {
  width: 100%;
}

:deep(.p-password-input) {
  width: 100%;
}

:deep(.p-inputtext) {
  width: 100%;
}

:deep(.p-float-label) {
  width: 100%;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem > .p-menuitem-content) {
  background: transparent !important;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem > .p-menuitem-content:hover) {
  background: var(--highlight-bg) !important;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem > .p-menuitem-content:focus) {
  outline: none !important;
  box-shadow: none !important;
  background: transparent !important;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem > .p-menuitem-content:active) {
  background: transparent !important;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem > .p-menuitem-content.p-focus) {
  background: transparent !important;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem-link) {
  background: transparent !important;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem-link) {
  font-size: var(--app-font-size-sm);
  line-height: 1;
}

:deep(.p-menubar .p-menubar-root-list > .p-menuitem-link:focus) {
  background: transparent !important;
  box-shadow: none !important;
}

:deep(.p-menubar .p-menuitem-icon) {
  font-size: var(--app-icon-size);
}

:deep(.p-menubar .p-menuitem) {
  outline: none !important;
  background: transparent !important;
}

:deep(.p-menubar .p-menuitem:focus) {
  background: transparent !important;
  outline: none !important;
}

:deep(.p-menubar .p-menuitem:focus-visible) {
  background: transparent !important;
  outline: none !important;
  box-shadow: none !important;
}

:deep(.p-menubar .p-menuitem.p-focus) {
  background: transparent !important;
}

:deep(.p-menubar .p-menuitem.p-highlight) {
  background: transparent !important;
}

:deep(.p-menubar) {
  outline: none;
}

:deep(.p-menubar *:focus) {
  background: transparent !important;
  outline: none !important;
  box-shadow: none !important;
}

:deep(.p-menubar *.p-focus) {
  background: transparent !important;
}

:deep(.p-menubar *.p-highlight) {
  background: transparent !important;
}

@media (max-width: 640px) {
  .nav-brand-cluster,
  .nav-control-cluster {
    gap: 0.4rem;
  }

  .brand-lockup {
    gap: 0.55rem;
    padding-right: 0;
  }

  .brand-mark-frame {
    width: 2.15rem;
    border-radius: 7px;
  }

  .brand-title-main {
    max-width: 9.5rem;
    overflow: hidden;
    font-size: 0.92rem;
    letter-spacing: 0.03em;
    text-overflow: ellipsis;
  }

  .brand-title-sub {
    max-width: 9.5rem;
    overflow: hidden;
    font-size: 0.48rem;
    letter-spacing: 0.18em;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .nav-action-group {
    gap: 0.2rem !important;
    padding-right: 0.35rem;
  }

  :deep(.p-menubar) {
    padding: 0.35rem 0.55rem;
  }

  :deep(.p-button.p-button-text) {
    width: 2.35rem;
    min-width: 2.35rem;
    height: 2.35rem;
    padding: 0;
  }
}

@media (max-width: 380px) {
  .brand-title-main,
  .brand-title-sub {
    max-width: 7.5rem;
  }
}
</style>
