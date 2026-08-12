import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { shallowMount } from '@vue/test-utils'
import Navbar from '@/components/Navbar.vue'
import navbarSource from '@/components/Navbar.vue?raw'

const localLoginMock = vi.hoisted(() => vi.fn())
const logoutMock = vi.hoisted(() => vi.fn())
const loginRedirectMock = vi.hoisted(() => vi.fn())
const nthuLoginMock = vi.hoisted(() => vi.fn())
const createSystemIssueMock = vi.hoisted(() => vi.fn())
const trackEventMock = vi.hoisted(() => vi.fn())
const setTokenMock = vi.hoisted(() => vi.fn())
const getCurrentUserMock = vi.hoisted(() => vi.fn())
const isAuthenticatedMock = vi.hoisted(() => vi.fn())
const toastAddMock = vi.hoisted(() => vi.fn())
const confirmRequireMock = vi.hoisted(() => vi.fn())
const notificationStoreMock = vi.hoisted(() => ({
  state: {
    modalVisible: false,
    centerVisible: false,
    all: [],
    active: [],
    initialized: false,
    loadingAll: false,
  },
  initNotifications: vi.fn(),
  openCenter: vi.fn(),
  deletePersonalNotification: vi.fn(),
  deleteAllPersonalNotifications: vi.fn(),
  markNotificationAsSeen: vi.fn(),
  latestUnseenNotification: null,
}))

let consoleErrorSpy

vi.mock('@/api', () => ({
  authService: {
    localLogin: localLoginMock,
    logout: logoutMock,
    login: loginRedirectMock,
    nthuLogin: nthuLoginMock,
  },
  reportService: {
    createSystemIssue: createSystemIssueMock,
  },
}))

vi.mock('@/utils/auth.js', () => ({
  getCurrentUser: getCurrentUserMock,
  isAuthenticated: isAuthenticatedMock,
  setToken: setTokenMock,
}))

vi.mock('@/utils/useTheme', () => {
  const themeState = { value: false }
  return {
    useTheme: () => ({
      isDarkTheme: themeState,
      toggleTheme: vi.fn(),
    }),
  }
})

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('primevue/usetoast', () => ({
  useToast: () => ({
    add: toastAddMock,
  }),
}))

vi.mock('primevue/useconfirm', () => ({
  useConfirm: () => ({ require: confirmRequireMock }),
}))

vi.mock('@/utils/analytics', () => ({
  trackEvent: trackEventMock,
  EVENTS: {
    TOGGLE_THEME: 'toggle-theme',
    LOGIN: 'login',
    LOGIN_LOCAL: 'login-local',
    LOGOUT: 'logout',
    NAVIGATE_ARCHIVE: 'navigate-archive',
    NAVIGATE_ADMIN: 'navigate-admin',
    OPEN_NOTIFICATION_CENTER: 'open-notification-center',
    OPEN_ISSUE_REPORT: 'open-issue-report',
    SUBMIT_ISSUE_REPORT: 'submit-issue-report',
    OPEN_MORE_ACTIONS_MENU: 'open-more-actions-menu',
  },
}))

vi.mock('@/utils/useNotifications', () => ({
  useNotifications: () => notificationStoreMock,
}))

vi.mock('@/components/NotificationModal.vue', () => ({
  default: {
    name: 'NotificationModal',
    props: ['visible', 'notification'],
    template: '<div class="notification-modal"></div>',
  },
}))
vi.mock('@/components/NotificationCenterModal.vue', () => ({
  default: {
    name: 'NotificationCenterModal',
    props: ['visible', 'notifications'],
    template: '<div class="notification-center"></div>',
  },
}))

describe('Navbar methods', () => {
  it('hides guest login only on Home and the public course catalog', () => {
    const guest = { isAuthenticated: false }

    expect(Navbar.computed.showGuestLogin.call({ ...guest, $route: { path: '/' } })).toBe(false)
    expect(Navbar.computed.showGuestLogin.call({ ...guest, $route: { path: '/courses' } })).toBe(
      false
    )
    expect(
      Navbar.computed.showGuestLogin.call({ ...guest, $route: { path: '/courses/42' } })
    ).toBe(false)
    expect(
      Navbar.computed.showGuestLogin.call({ ...guest, $route: { path: '/personal-settings' } })
    ).toBe(true)
    expect(
      Navbar.computed.showGuestLogin.call({ isAuthenticated: true, $route: { path: '/archive' } })
    ).toBe(false)
  })

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    trackEventMock.mockReset()
    localLoginMock.mockReset()
    logoutMock.mockReset()
    loginRedirectMock.mockReset()
    nthuLoginMock.mockReset()
    createSystemIssueMock.mockReset()
    createSystemIssueMock.mockResolvedValue({ data: { id: 1 } })
    toastAddMock.mockReset()
    confirmRequireMock.mockReset()
    notificationStoreMock.state.modalVisible = false
    notificationStoreMock.state.centerVisible = false
    notificationStoreMock.state.all = []
    notificationStoreMock.state.active = []
    notificationStoreMock.state.initialized = false
    notificationStoreMock.state.loadingAll = false
    notificationStoreMock.initNotifications.mockReset()
    notificationStoreMock.openCenter.mockReset()
    notificationStoreMock.deletePersonalNotification.mockReset()
    notificationStoreMock.deleteAllPersonalNotifications.mockReset()
    notificationStoreMock.markNotificationAsSeen.mockReset()
    notificationStoreMock.latestUnseenNotification = null
    getCurrentUserMock.mockReset()
    isAuthenticatedMock.mockReset()
    setTokenMock.mockReset()
    sessionStorage.clear()
    globalThis.localStorage?.clear?.()
  })

  afterEach(() => {
    if (consoleErrorSpy) {
      consoleErrorSpy.mockRestore()
    }
    delete window.__pastexam
  })

  it('toggles theme and tracks event', () => {
    const ctx = {
      isDarkTheme: true,
      toggleTheme: vi.fn(),
      toast: { add: toastAddMock },
      notificationStore: notificationStoreMock,
    }
    Navbar.methods.handleToggleTheme.call(ctx)
    expect(trackEventMock).toHaveBeenCalledWith('toggle-theme', expect.any(Object))
    expect(ctx.toggleTheme).toHaveBeenCalled()
  })

  it('handles local login success and failure', async () => {
    const routerPush = vi.fn()
    const ctx = {
      username: 'user',
      password: 'pass',
      toast: { add: toastAddMock },
      router: { push: routerPush },
      loginVisible: true,
      loading: false,
      checkAuthentication: vi.fn(),
    }

    localLoginMock.mockResolvedValue({ access_token: 'token123' })
    await Navbar.methods.handleLocalLogin.call(ctx)
    expect(localLoginMock).toHaveBeenCalledWith('user', 'pass')
    expect(setTokenMock).toHaveBeenCalledWith('token123')
    expect(routerPush).toHaveBeenCalledWith('/archive')
    expect(trackEventMock).toHaveBeenCalledWith('login-local', { success: true })

    ctx.username = ''
    ctx.password = ''
    await Navbar.methods.handleLocalLogin.call(ctx)
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'error', summary: '錯誤' })
    )
  })

  it('handles local login rejection with error toast', async () => {
    const routerPush = vi.fn()
    const ctx = {
      username: 'user',
      password: 'pass',
      toast: { add: toastAddMock },
      router: { push: routerPush },
      loginVisible: true,
      loading: false,
      checkAuthentication: vi.fn(),
    }

    toastAddMock.mockClear()
    localLoginMock.mockRejectedValueOnce(new Error('fail'))

    await Navbar.methods.handleLocalLogin.call(ctx)

    expect(trackEventMock).toHaveBeenCalledWith('login-local', { success: false })
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ summary: '登入失敗' }))
    expect(ctx.loading).toBe(false)
  })

  it.each([
    [{ isInvalidCredentials: true, response: { status: 401 } }, '帳號或密碼錯誤'],
    [{ code: 'ECONNABORTED' }, '伺服器回應逾時，請稍後再試'],
    [{ response: { status: 500 } }, '伺服器發生錯誤，請稍後再試'],
    [{ code: 'ERR_NETWORK' }, '無法連線至後端，請確認服務是否正常'],
  ])('describes local login failures without leaving loading active', async (error, detail) => {
    const ctx = {
      username: 'user',
      password: 'pass',
      toast: { add: toastAddMock },
      router: { push: vi.fn() },
      loginVisible: true,
      loading: false,
      checkAuthentication: vi.fn(),
    }

    localLoginMock.mockRejectedValueOnce(error)
    await Navbar.methods.handleLocalLogin.call(ctx)

    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ detail }))
    expect(ctx.loading).toBe(false)
  })

  it('opens login dialog and tracks dialog event', () => {
    const ctx = {
      loginVisible: false,
    }

    Navbar.methods.openLoginDialog.call(ctx)

    expect(ctx.loginVisible).toBe(true)
    expect(trackEventMock).toHaveBeenCalledWith('login', { type: 'dialog-open' })
  })

  it('starts NTHU login from the existing login dialog', () => {
    const ctx = {
      loginVisible: true,
    }

    Navbar.methods.handleNthuLogin.call(ctx)

    expect(ctx.loginVisible).toBe(false)
    expect(nthuLoginMock).toHaveBeenCalledOnce()
    expect(trackEventMock).toHaveBeenCalledWith('login', { type: 'nthu' })
  })

  it('handles logout flow and cleans storage', async () => {
    const routerPush = vi.fn()
    const ctx = {
      toast: { add: toastAddMock },
      notificationStore: notificationStoreMock,
      $router: { push: routerPush },
      isAuthenticated: true,
      userData: { name: 'Alice' },
    }
    sessionStorage.setItem('auth-token', 'abc')

    await Navbar.methods.handleLogout.call(ctx)
    expect(logoutMock).toHaveBeenCalled()
    expect(trackEventMock).toHaveBeenCalledWith('logout', { success: true })
    expect(sessionStorage.getItem('auth-token')).toBeNull()
    expect(routerPush).toHaveBeenCalledWith('/')
  })

  it('tracks logout failure when API errors', async () => {
    const routerPush = vi.fn()
    const ctx = {
      toast: { add: toastAddMock },
      notificationStore: notificationStoreMock,
      $router: { push: routerPush },
      isAuthenticated: true,
      userData: { name: 'Alice' },
    }

    logoutMock.mockRejectedValueOnce(new Error('fail'))

    await Navbar.methods.handleLogout.call(ctx)

    expect(trackEventMock).toHaveBeenCalledWith('logout', { success: false })
    expect(routerPush).toHaveBeenCalledWith('/')
    expect(sessionStorage.getItem('auth-token')).toBeNull()
  })

  it('opens notification center with auth guard', async () => {
    const ctx = {
      toast: { add: toastAddMock },
      notificationStore: notificationStoreMock,
      isAuthenticated: false,
    }
    await Navbar.methods.openNotificationCenter.call(ctx, 'navbar')
    expect(toastAddMock).toHaveBeenCalled()

    ctx.isAuthenticated = true
    await Navbar.methods.openNotificationCenter.call(ctx, 'navbar')
    expect(notificationStoreMock.openCenter).toHaveBeenCalled()
    expect(trackEventMock).toHaveBeenCalledWith('open-notification-center', { from: 'navbar' })
  })

  it('handles notification modal visibility helpers', () => {
    const ctx = {
      notificationStore: notificationStoreMock,
    }
    Navbar.methods.handleNotificationModalVisible.call(ctx, true)
    expect(notificationStoreMock.state.modalVisible).toBe(true)

    Navbar.methods.handleNotificationDismiss.call(ctx, { id: 1 })
    expect(notificationStoreMock.markNotificationAsSeen).toHaveBeenCalledWith({ id: 1 })

    Navbar.methods.handleNotificationCenterVisible.call(ctx, true)
    expect(notificationStoreMock.state.centerVisible).toBe(true)

    Navbar.methods.handleNotificationDetailSeen.call(ctx, { id: 2 })
    expect(notificationStoreMock.markNotificationAsSeen).toHaveBeenCalledWith({ id: 2 })
  })

  it('routes persistent notification sources through internal archive queries', async () => {
    const push = vi.fn().mockResolvedValue()
    const ctx = {
      notificationStore: notificationStoreMock,
      $router: { push },
    }

    await Navbar.methods.handlePersonalNotificationSource.call(ctx, {
      source_type: 'archive_submission',
      source_id: 42,
      metadata: { submission_id: 42 },
    })
    expect(push).toHaveBeenLastCalledWith({
      path: '/archive',
      query: { showSubmissionStatus: '1', submissionId: 42 },
    })

    await Navbar.methods.handlePersonalNotificationSource.call(ctx, {
      source_type: 'archive_discussion_thread',
      source_id: 7,
      metadata: { course_id: 2, archive_id: 3, thread_id: 7, message_id: 9 },
    })
    expect(push).toHaveBeenLastCalledWith({
      path: '/archive',
      query: { courseId: 2, archiveId: 3, threadId: 7, messageId: 9 },
    })
    expect(notificationStoreMock.state.centerVisible).toBe(false)
  })

  it('confirms personal notification deletion before calling the store', async () => {
    const item = { id: 7 }
    const ctx = {
      confirm: { require: confirmRequireMock },
      notificationStore: notificationStoreMock,
      toast: { add: toastAddMock },
      deletingPersonalNotificationId: null,
    }

    Navbar.methods.handleDeletePersonalNotification.call(ctx, item)
    expect(notificationStoreMock.deletePersonalNotification).not.toHaveBeenCalled()
    const options = confirmRequireMock.mock.calls[0][0]
    expect(options.message).toContain('不會進入垃圾桶')
    await Navbar.methods.deletePersonalNotification.call(ctx, item)
    expect(notificationStoreMock.deletePersonalNotification).toHaveBeenCalledWith(7)
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ summary: '通知已刪除' }))
  })

  it('confirms and permanently deletes all personal notifications', async () => {
    const ctx = {
      confirm: { require: confirmRequireMock },
      notificationStore: notificationStoreMock,
      toast: { add: toastAddMock },
      deletingAllPersonalNotifications: false,
    }

    Navbar.methods.handleDeleteAllPersonalNotifications.call(ctx)
    expect(notificationStoreMock.deleteAllPersonalNotifications).not.toHaveBeenCalled()
    expect(confirmRequireMock.mock.calls[0][0].message).toContain('所有個人通知')
    await Navbar.methods.deleteAllPersonalNotifications.call(ctx)
    expect(notificationStoreMock.deleteAllPersonalNotifications).toHaveBeenCalledOnce()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ summary: '已刪除全部個人通知' })
    )
  })

  it('toggles more actions menu and invokes menu actions', () => {
    const toggleSpy = vi.fn()
    const hideSpy = vi.fn()
    const actionSpy = vi.fn()
    const ctx = {
      moreActions: [actionSpy],
      $refs: {
        moreActionsMenu: {
          toggle: toggleSpy,
          hide: hideSpy,
        },
      },
      isDesktopView: true,
    }
    Navbar.methods.toggleMoreActions.call(ctx, {})
    expect(toggleSpy).toHaveBeenCalled()
    expect(trackEventMock).toHaveBeenCalledWith('open-more-actions-menu', {
      items: 1,
      viewport: 'desktop',
    })

    Navbar.methods.invokeMenuAction.call(ctx, actionSpy)
    expect(hideSpy).toHaveBeenCalled()
    expect(actionSpy).toHaveBeenCalled()

    toggleSpy.mockClear()
    trackEventMock.mockClear()
    Navbar.methods.toggleMoreActions.call({
      moreActions: [],
      $refs: ctx.$refs,
      isDesktopView: false,
    })
    expect(toggleSpy).not.toHaveBeenCalled()
    expect(trackEventMock).not.toHaveBeenCalled()

    hideSpy.mockClear()
    Navbar.methods.invokeMenuAction.call(ctx, 'not-a-function')
    expect(hideSpy).toHaveBeenCalled()
  })

  it('checks authentication and updates user data', () => {
    isAuthenticatedMock.mockReturnValue(true)
    getCurrentUserMock.mockReturnValue({ name: 'Alice' })

    const ctx = {
      isAuthenticated: false,
      userData: null,
    }

    Navbar.methods.checkAuthentication.call(ctx)
    expect(ctx.isAuthenticated).toBe(true)
    expect(ctx.userData.name).toBe('Alice')
  })

  it('handles authentication fallback cases', () => {
    const ctx = {
      isAuthenticated: true,
      userData: { name: 'Bob' },
    }

    isAuthenticatedMock.mockReturnValue(true)
    getCurrentUserMock.mockReturnValueOnce(null)

    Navbar.methods.checkAuthentication.call(ctx)
    expect(ctx.isAuthenticated).toBe(false)
    expect(ctx.userData).toBeNull()

    isAuthenticatedMock.mockReturnValue(false)
    Navbar.methods.checkAuthentication.call(ctx)
    expect(ctx.isAuthenticated).toBe(false)
    expect(ctx.userData).toBeNull()
  })

  it('manages issue dialogs and navigation actions', () => {
    const routerPush = vi.fn()
    const ctx = {
      isAuthenticated: true,
      $router: { push: routerPush },
      issueReportVisible: false,
      issueForm: {
        type: 'bug',
        title: 'Issue',
        description: 'desc',
        contact: 'contact',
      },
      notificationStore: notificationStoreMock,
    }

    Navbar.methods.handleTitleClick.call(ctx)
    expect(routerPush).toHaveBeenCalledWith('/archive')

    Navbar.methods.handleNavigateAdmin.call(ctx)
    expect(routerPush).toHaveBeenCalledWith('/admin')

    Navbar.methods.openIssueReportDialog.call(ctx)
    expect(trackEventMock).toHaveBeenCalledWith('open-issue-report')
    expect(ctx.issueReportVisible).toBe(true)

    Navbar.methods.closeIssueReportDialog.call(ctx)
    expect(ctx.issueReportVisible).toBe(false)
    expect(ctx.issueForm.title).toBe('')

    Navbar.methods.handleIssueReportDialogClose.call(ctx, false)
    expect(ctx.issueForm.description).toBe('')
  })

  it('skips archive navigation when not authenticated', () => {
    const routerPush = vi.fn()
    Navbar.methods.handleTitleClick.call({
      isAuthenticated: false,
      $router: { push: routerPush },
    })

    expect(routerPush).not.toHaveBeenCalled()
  })

  it('formats issue body with system information', () => {
    const ctx = {
      getBrowserInfo: vi.fn(() => 'Chrome 120'),
      getOSInfo: vi.fn(() => 'macOS 14.0'),
      formatTimestamp: vi.fn(() => '2025/10/30 12:00:00 (UTC+8)'),
    }
    const systemInfo = {
      userAgent: 'chrome ua',
      platform: 'MacIntel',
      language: 'zh-TW',
      url: 'https://example.com',
      route: { path: '/archive', name: 'ArchiveView', fullPath: '/archive?course=1' },
      pageContext: {
        archiveContext: {
          course: { id: 101, name: '普通物理(一)' },
          filters: {
            year: '2024',
            professor: '王教授',
            type: 'final',
            hasAnswers: true,
            searchQuery: '普通物理',
          },
          preview: { open: true, archiveId: 201, name: '期末考' },
        },
      },
      timestamp: '2025-10-30T00:00:00Z',
    }

    const bodyWithContact = Navbar.methods.formatIssueBody.call(
      ctx,
      '描述內容',
      'contact@example.com',
      systemInfo,
      'bug'
    )
    expect(ctx.getBrowserInfo).toHaveBeenCalledWith('chrome ua')
    expect(bodyWithContact).toContain('contact@example.com')
    expect(bodyWithContact).toContain('## 頁面資訊')
    expect(bodyWithContact).toContain('普通物理(一)')
    expect(bodyWithContact).toContain('year=2024')
    expect(bodyWithContact).toContain('archiveId=201')

    const bodyWithoutContact = Navbar.methods.formatIssueBody.call(
      ctx,
      '描述內容',
      '',
      systemInfo,
      'question'
    )
    expect(bodyWithoutContact).not.toContain('聯絡方式')
  })

  it('detects browser and operating system variants', () => {
    const chrome = Navbar.methods.getBrowserInfo.call({}, 'Chrome/120.0')
    const firefox = Navbar.methods.getBrowserInfo.call({}, 'Firefox/118.0')
    const safari = Navbar.methods.getBrowserInfo.call({}, 'Version Safari/16.4')
    const edge = Navbar.methods.getBrowserInfo.call({}, 'Edge/118.0')
    const unknown = Navbar.methods.getBrowserInfo.call({}, 'Other UA')

    expect(chrome).toMatch(/Chrome/)
    expect(firefox).toMatch(/Firefox/)
    expect(safari).toMatch(/Safari/)
    expect(edge).toMatch(/Edge/)
    expect(unknown).toBe('Unknown Browser')

    expect(Navbar.methods.getOSInfo.call({}, 'MacIntel', 'Mac OS X 13_6')).toContain('macOS')
    expect(Navbar.methods.getOSInfo.call({}, 'Win', 'Windows NT 10.0')).toBe('Windows 10/11')
    expect(Navbar.methods.getOSInfo.call({}, 'Linux', 'Linux x86_64')).toBe('Linux')
    expect(Navbar.methods.getOSInfo.call({}, 'Android', 'Android 13.0')).toBe('Android 13.0')
    expect(Navbar.methods.getOSInfo.call({}, 'iPhone', 'Mozilla/5.0 (iPhone; CPU OS 16_4)')).toBe(
      'iOS 16.4'
    )
    expect(Navbar.methods.getOSInfo.call({}, 'Other', 'Unknown')).toBe('Other')
  })

  it('collects system info and formats timestamps', () => {
    sessionStorage.setItem(
      'pastexam-issue-context',
      JSON.stringify({
        page: 'archive',
        course: { id: 101, name: '普通物理(一)' },
        filters: {
          year: '2024',
          professor: null,
          type: null,
          hasAnswers: false,
          searchQuery: null,
        },
        preview: { open: false, archiveId: null },
      })
    )

    const info = Navbar.methods.getSystemInfo.call({})
    expect(info).toMatchObject({
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      language: navigator.language,
      url: window.location.href,
      route: { path: null, name: null, fullPath: null },
    })
    expect(info).toHaveProperty('pageContext')
    expect(typeof info.timestamp).toBe('string')

    const formatted = Navbar.methods.formatTimestamp.call({}, '2024-01-01T00:00:00Z')
    expect(formatted).toContain('(UTC+8)')
  })

  it('stores a local system issue before opening the GitHub prefill page', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => {})
    const ctx = {
      issueForm: {
        type: 'bug',
        title: '系統問題',
        description: '詳細描述',
        contact: 'contact@example.com',
      },
      canSubmitIssue: true,
      issueSubmitting: false,
      toast: { add: toastAddMock },
      closeIssueReportDialog: vi.fn(),
      getSystemInfo: vi.fn(() => ({
        userAgent: 'ua',
        platform: 'platform',
        language: 'zh-TW',
        url: 'https://example.com',
        timestamp: '2025-10-30T00:00:00Z',
      })),
      formatIssueBody: vi.fn(() => 'issue body'),
    }

    await Navbar.methods.submitIssueReport.call(ctx)
    expect(trackEventMock).toHaveBeenCalledWith(
      'submit-issue-report',
      expect.objectContaining({ type: 'bug', hasContact: true })
    )
    expect(ctx.formatIssueBody).toHaveBeenCalled()
    expect(createSystemIssueMock).toHaveBeenCalledWith(
      expect.objectContaining({ report_type: 'bug', title: '系統問題' })
    )
    expect(ctx.closeIssueReportDialog).toHaveBeenCalled()
    expect(toastAddMock).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'success', summary: '回報摘要已保存' })
    )
    expect(openSpy).toHaveBeenCalled()
    expect(navbarSource).toContain('請先在目前瀏覽器登入 GitHub')
    expect(navbarSource).toContain('GitHub Issue 仍需由您在 GitHub 頁面確認送出後才會正式建立')
    expect(navbarSource).toContain('label="建立回報並前往 GitHub"')
    openSpy.mockRestore()
  })

  it('computes menu helpers correctly', () => {
    const pendingCtx = {
      notificationStore: { latestUnseenNotification: { value: { id: 99 } } },
    }
    expect(Navbar.computed.pendingNotification.call(pendingCtx)).toEqual({ id: 99 })
    pendingCtx.notificationStore.latestUnseenNotification = null
    expect(Navbar.computed.pendingNotification.call(pendingCtx)).toBeNull()

    const actionsCtxDesktop = {
      isAuthenticated: true,
      userData: { is_admin: true },
      isDesktopView: true,
      invokeMenuAction: vi.fn((handler) => handler()),
      handleNavigatePersonalSettings: vi.fn(),
      openNotificationCenter: vi.fn(),
      openIssueReportDialog: vi.fn(),
      handleNavigateAdmin: vi.fn(),
      handleLogout: vi.fn(),
    }
    const actionsDesktop = Navbar.computed.moreActions.call(actionsCtxDesktop)
    expect(actionsDesktop).toHaveLength(3)
    actionsDesktop[0].command()
    expect(actionsCtxDesktop.invokeMenuAction).toHaveBeenCalled()
    expect(actionsCtxDesktop.handleNavigatePersonalSettings).toHaveBeenCalled()
    actionsDesktop[1].command()
    expect(actionsDesktop[1].label).toBe('公告與通知')
    expect(actionsCtxDesktop.openNotificationCenter).toHaveBeenCalledWith('navbar-menu')

    const actionsCtxMobile = {
      isAuthenticated: true,
      userData: { is_admin: true },
      isDesktopView: false,
      invokeMenuAction: vi.fn((handler) => handler()),
      handleNavigatePersonalSettings: vi.fn(),
      openNotificationCenter: vi.fn(),
      openIssueReportDialog: vi.fn(),
      handleNavigateAdmin: vi.fn(),
      handleLogout: vi.fn(),
    }
    const actionsMobile = Navbar.computed.moreActions.call(actionsCtxMobile)
    expect(actionsMobile).toHaveLength(5)
    expect(actionsMobile[3]).toHaveProperty('separator')
    expect(actionsMobile[4].label).toBe('登出')
    expect(actionsMobile[4].icon).toBe('pi pi-sign-out')
    actionsMobile[4].command()
    expect(actionsCtxMobile.invokeMenuAction).toHaveBeenCalled()
    expect(actionsCtxMobile.handleLogout).toHaveBeenCalled()

    const canSubmitCtx = {
      issueForm: { type: 'bug', title: 'Title', description: 'Desc' },
    }
    expect(Navbar.computed.canSubmitIssue.call(canSubmitCtx)).toBeTruthy()
    canSubmitCtx.issueForm.title = ' '
    expect(Navbar.computed.canSubmitIssue.call(canSubmitCtx)).toBeFalsy()
  })

  it('returns empty menu actions when unauthenticated', () => {
    const actionsCtx = {
      isAuthenticated: false,
    }

    expect(Navbar.computed.moreActions.call(actionsCtx)).toEqual([])
  })

  it('updates the responsive menu mode from reactive viewport state', () => {
    const ctx = { viewportWidth: 1024 }
    const originalWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 524 })

    Navbar.methods.updateViewportWidth.call(ctx)

    expect(ctx.viewportWidth).toBe(524)
    expect(Navbar.computed.isDesktopView.call(ctx)).toBe(false)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
  })

  it('reacts to authentication watcher changes', async () => {
    const initSpy = vi.fn()
    const ctx = {
      notificationStore: notificationStoreMock,
      initializeNotifications: initSpy,
      startHeartbeat: vi.fn(),
      stopHeartbeat: vi.fn(),
    }

    notificationStoreMock.state.modalVisible = true
    notificationStoreMock.state.centerVisible = true
    notificationStoreMock.state.active = [1]
    notificationStoreMock.state.all = [1, 2]
    notificationStoreMock.state.initialized = true

    await Navbar.watch.isAuthenticated.call(ctx, true)
    expect(initSpy).toHaveBeenCalled()

    await Navbar.watch.isAuthenticated.call(ctx, false)
    expect(notificationStoreMock.state.modalVisible).toBe(false)
    expect(notificationStoreMock.state.centerVisible).toBe(false)
    expect(notificationStoreMock.state.active).toEqual([])
    expect(notificationStoreMock.state.all).toEqual([])
    expect(notificationStoreMock.state.initialized).toBe(false)
  })

  it('renders template states for authentication transitions', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval').mockImplementation(() => 1)
    const baseData = Navbar.data ? Navbar.data.call({}) : {}
    const globalConfig = {
      stubs: {
        Menubar: {
          name: 'MenubarStub',
          template:
            '<div class="menubar"><slot name="start"></slot><slot></slot><slot name="end"></slot></div>',
        },
        Button: {
          name: 'ButtonStub',
          props: ['icon', 'label', 'ariaLabel'],
          template:
            '<button :data-icon="icon" :data-label="label" :data-testid="ariaLabel || icon" @click="$emit(\'click\', $event)"><slot /></button>',
        },
        Dialog: {
          name: 'DialogStub',
          props: ['visible'],
          emits: ['update:visible'],
          template: '<div v-if="visible" class="dialog"><slot /></div>',
        },
        Menu: {
          name: 'MenuStub',
          props: ['model', 'popup'],
          template: '<div data-testid="menu"></div>',
        },
        NotificationModal: false,
        NotificationCenterModal: false,
        Select: { name: 'SelectStub', template: '<select><slot /></select>' },
        InputText: { name: 'InputTextStub', template: '<input />' },
        Textarea: { name: 'TextareaStub', template: '<textarea></textarea>' },
        FloatLabel: {
          name: 'FloatLabelStub',
          template: '<div><slot /><slot name="label" /></div>',
        },
        Password: { name: 'PasswordStub', template: '<input type="password" />' },
      },
      mocks: {
        $route: { path: '/archive' },
        $router: { push: vi.fn() },
      },
    }

    const unauthWrapper = shallowMount(Navbar, {
      global: globalConfig,
      data() {
        return { ...baseData }
      },
    })

    await nextTick()

    expect(unauthWrapper.find('[data-icon="pi pi-sign-in"]').exists()).toBe(true)
    expect(unauthWrapper.find('[data-icon="pi pi-sign-out"]').exists()).toBe(false)

    await unauthWrapper.find('[data-icon="pi pi-sign-in"]').trigger('click')
    await nextTick()
    const loginDialog = unauthWrapper.get('.dialog')
    expect(loginDialog.find('[data-label="登入"]').exists()).toBe(true)
    expect(loginDialog.find('[data-label="清華校務系統登入"]').exists()).toBe(false)
    expect(loginDialog.text()).not.toContain('或')

    expect(window.__pastexam?.openLoginModal).toBeTypeOf('function')
    expect(window.__pastexam?.startNthuLogin).toBeTypeOf('function')

    window.__pastexam.startNthuLogin()

    expect(nthuLoginMock).toHaveBeenCalledOnce()
    expect(trackEventMock).toHaveBeenCalledWith('login', { type: 'nthu' })

    unauthWrapper.unmount()
    expect(window.__pastexam?.openLoginModal).toBeUndefined()
    expect(window.__pastexam?.startNthuLogin).toBeUndefined()

    notificationStoreMock.latestUnseenNotification = { value: { id: 1 } }
    notificationStoreMock.state.modalVisible = true
    notificationStoreMock.state.centerVisible = true

    isAuthenticatedMock.mockReturnValue(true)
    getCurrentUserMock.mockReturnValue({ name: 'Alice', is_admin: true })

    const authWrapper = shallowMount(Navbar, {
      global: globalConfig,
      data() {
        return { ...baseData }
      },
    })

    await nextTick()

    expect(authWrapper.find('[data-icon="pi pi-sign-in"]').exists()).toBe(false)
    expect(authWrapper.find('[data-icon="pi pi-sign-out"]').exists()).toBe(true)
    expect(authWrapper.find('.notification-modal').exists()).toBe(true)
    expect(authWrapper.find('.notification-center').exists()).toBe(true)

    const menuProps = authWrapper.getComponent({ name: 'MenuStub' }).props('model')
    expect(Array.isArray(menuProps)).toBe(true)
    expect(menuProps.length).toBeGreaterThan(0)

    authWrapper.unmount()
    notificationStoreMock.latestUnseenNotification = null
    setIntervalSpy.mockRestore()
  })
})
