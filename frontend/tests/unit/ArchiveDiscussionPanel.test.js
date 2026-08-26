import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ArchiveDiscussionPanel from '@/components/ArchiveDiscussionPanel.vue'
import { setLocale } from '@/i18n'

const mocks = vi.hoisted(() => ({
  like: vi.fn(),
  unlike: vi.fn(),
  remove: vi.fn(),
  pin: vi.fn(),
  report: vi.fn(),
  openSocket: vi.fn(),
  getMe: vi.fn(),
  updateSettings: vi.fn(),
  toastAdd: vi.fn(),
}))

vi.mock('@/api', () => ({
  discussionService: {
    likeArchiveMessage: mocks.like,
    unlikeArchiveMessage: mocks.unlike,
    deleteArchiveMessage: mocks.remove,
    pinArchiveMessage: mocks.pin,
    reportArchiveMessage: mocks.report,
    openArchiveDiscussionWebSocket: mocks.openSocket,
  },
  userService: {
    getMe: mocks.getMe,
    updateMyDiscussionSettings: mocks.updateSettings,
  },
}))

vi.mock('@/utils/auth', () => ({
  getCurrentUser: () => ({ id: 7, is_admin: true, name: 'Current User' }),
}))
vi.mock('@/utils/analytics', () => ({
  trackEvent: vi.fn(),
  EVENTS: {
    DISCUSSION_SEND_MESSAGE: 'send',
    DISCUSSION_UPDATE_NICKNAME: 'nickname',
    DISCUSSION_SET_DEFAULT_OPEN: 'default-open',
  },
}))
vi.mock('@/utils/usePreferences', () => ({
  getBooleanPreference: () => true,
  setBooleanPreference: vi.fn(),
}))
vi.mock('@/utils/storage', () => ({
  STORAGE_KEYS: { local: { DISCUSSION_DESKTOP_DEFAULT_OPEN: 'discussion-open' } },
}))
vi.mock('@/utils/submissionLevel', () => ({
  loadContributorLevelSettings: vi.fn(),
  localizedSubmissionLevelName: vi.fn(() => '投稿者'),
  resolveSubmissionLevel: vi.fn(() => ({ level: 1, name: '投稿者' })),
}))
function makeSocket() {
  return {
    readyState: 1,
    send: vi.fn(),
    close: vi.fn(),
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
  }
}

function mountPanel(socket, confirm = { require: ({ accept }) => accept() }) {
  mocks.openSocket.mockReturnValue(socket)
  return mount(ArchiveDiscussionPanel, {
    props: { courseId: 1, archiveId: 2 },
    global: {
      provide: {
        toast: { add: mocks.toastAdd },
        confirm,
      },
      stubs: {
        DiscussionMessageCard: { template: '<article />' },
        Button: { template: '<button><slot /></button>' },
        Textarea: { template: '<textarea />' },
        Dialog: { template: '<div><slot /><slot name="footer" /></div>' },
        InputText: { template: '<input />' },
        Checkbox: { template: '<input type="checkbox" />' },
        ProgressSpinner: { template: '<div />' },
      },
    },
  })
}

function mountPanelWithRealMessageCard(socket) {
  mocks.openSocket.mockReturnValue(socket)
  return mount(ArchiveDiscussionPanel, {
    props: { courseId: 1, archiveId: 2 },
    global: {
      provide: {
        toast: { add: mocks.toastAdd },
        confirm: { require: ({ accept }) => accept() },
      },
      stubs: {
        Button: {
          props: ['label'],
          template: '<button><slot />{{ label }}</button>',
        },
        Textarea: {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template:
            '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        Dialog: { template: '<div><slot /><slot name="footer" /></div>' },
        InputText: { template: '<input />' },
        Checkbox: { template: '<input type="checkbox" />' },
        ProgressSpinner: { template: '<div />' },
        ContributorLevelBadge: true,
        InlineCommentReport: true,
      },
    },
  })
}

async function loadDiscussionHistory(socket, messages) {
  socket.onopen()
  socket.onmessage({
    data: JSON.stringify({ type: 'history', messages }),
  })
  await flushPromises()
}

describe('ArchiveDiscussionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    globalThis.WebSocket = { OPEN: 1 }
    mocks.getMe.mockResolvedValue({
      data: { name: 'Current User', nickname: 'Current', show_level_title: true },
    })
    mocks.like.mockResolvedValue({ data: { liked: true, like_count: 10 } })
    mocks.unlike.mockResolvedValue({ data: { liked: false, like_count: 9 } })
    mocks.report.mockResolvedValue({ data: { id: 88 } })
    mocks.remove.mockResolvedValue({ data: { preserve_thread: false } })
  })

  it('opens the reply editor from the real message-card reply button', async () => {
    const socket = makeSocket()
    const wrapper = mountPanelWithRealMessageCard(socket)
    await loadDiscussionHistory(socket, [
      {
        id: 10,
        user_id: 2,
        user_name: '使用者',
        content: 'Root message',
        created_at: '2026-01-01T00:00:00Z',
        replies: [],
      },
    ])

    const replyButton = wrapper.get('[aria-label="回覆留言"]')
    expect(replyButton.attributes('type')).toBe('button')
    await replyButton.trigger('click')

    expect(wrapper.get('.discussion-reply-editor').text()).toContain('回覆 @使用者')
    expect(wrapper.get('textarea[name="discussion-reply"]').attributes('placeholder')).toBe(
      '回覆 @使用者'
    )
    expect(wrapper.get('[aria-label="取消回覆"]').attributes('type')).toBe('button')

    setLocale('en')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.discussion-reply-editor').text()).toContain('Reply to @使用者')
    expect(wrapper.get('textarea[name="discussion-reply"]').attributes('placeholder')).toBe(
      'Reply to @使用者'
    )
  })

  it('sends a reply to the clicked message through the WebSocket payload', async () => {
    const socket = makeSocket()
    const wrapper = mountPanelWithRealMessageCard(socket)
    await loadDiscussionHistory(socket, [
      {
        id: 10,
        user_id: 2,
        user_name: '使用者',
        content: 'Root message',
        created_at: '2026-01-01T00:00:00Z',
        replies: [],
      },
    ])
    await wrapper.get('[aria-label="回覆留言"]').trigger('click')
    await wrapper.get('textarea[name="discussion-reply"]').setValue('test reply')

    await wrapper.get('.discussion-reply-editor').trigger('submit')

    expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual({
      type: 'send',
      content: 'test reply',
      reply_to_message_id: 10,
    })
  })

  it('renders an existing reply context after expanding the thread', async () => {
    const socket = makeSocket()
    const wrapper = mountPanelWithRealMessageCard(socket)
    await loadDiscussionHistory(socket, [
      {
        id: 10,
        user_id: 2,
        user_name: 'Root User',
        content: 'Root message',
        created_at: '2026-01-01T00:00:00Z',
        replies: [
          {
            id: 11,
            parent_id: 10,
            reply_to_message_id: 10,
            reply_to_user_name: '使用者',
            user_id: 3,
            user_name: 'Reply User',
            content: 'Existing reply',
            created_at: '2026-01-02T00:00:00Z',
          },
        ],
      },
    ])

    await wrapper.get('.discussion-thread-toggle__button').trigger('click')

    expect(wrapper.get('.discussion-card__reply-context').text()).toBe('回覆 @使用者')
    expect(wrapper.get('.discussion-replies').text()).toContain('Existing reply')
  })

  it('sorts roots and appends a reply to the existing thread without reloading', async () => {
    const socket = makeSocket()
    const wrapper = mountPanel(socket)
    socket.onopen()
    socket.onmessage({
      data: JSON.stringify({
        type: 'history',
        messages: [
          {
            id: 1,
            user_id: 1,
            user_name: 'Pinned',
            is_pinned: true,
            like_count: 0,
            created_at: '2026-01-01T00:00:00Z',
            replies: [],
          },
          {
            id: 2,
            user_id: 2,
            user_name: 'Popular',
            is_pinned: false,
            like_count: 8,
            created_at: '2026-01-02T00:00:00Z',
            replies: [],
          },
          {
            id: 3,
            user_id: 3,
            user_name: 'Newest',
            is_pinned: false,
            like_count: 0,
            created_at: '2026-01-03T00:00:00Z',
            replies: [],
          },
        ],
      }),
    })
    await flushPromises()

    expect(wrapper.vm.sortedMessages.map((message) => message.id)).toEqual([1, 2, 3])
    wrapper.vm.startReply(wrapper.vm.messages[1])
    wrapper.vm.replyDraft = 'thread reply'
    wrapper.vm.sendReply()
    expect(JSON.parse(socket.send.mock.calls[0][0])).toMatchObject({
      type: 'send',
      content: 'thread reply',
      reply_to_message_id: 2,
    })

    socket.onmessage({
      data: JSON.stringify({
        type: 'message',
        message: {
          id: 20,
          parent_id: 2,
          reply_to_message_id: 2,
          user_id: 7,
          user_name: 'Current',
          content: 'thread reply',
          like_count: 0,
          created_at: '2026-01-04T00:00:00Z',
        },
      }),
    })
    expect(wrapper.vm.messages[1].replies).toHaveLength(1)
    expect(wrapper.vm.isThreadExpanded(2)).toBe(true)
    expect(mocks.openSocket).toHaveBeenCalledTimes(1)
  })

  it('keeps replies collapsed by default and clears the toggle after the final reply is deleted', async () => {
    const socket = makeSocket()
    const wrapper = mountPanel(socket)
    socket.onopen()
    socket.onmessage({
      data: JSON.stringify({
        type: 'history',
        messages: [
          {
            id: 10,
            user_id: 2,
            user_name: 'Root',
            content: 'Root message',
            created_at: '2026-01-01T00:00:00Z',
            replies: [
              {
                id: 11,
                parent_id: 10,
                user_id: 3,
                user_name: 'Reply',
                content: 'Reply message',
                created_at: '2026-01-02T00:00:00Z',
              },
            ],
          },
        ],
      }),
    })
    await flushPromises()

    const toggle = wrapper.get('.discussion-thread-toggle__button')
    expect(toggle.text()).toContain('查看 1 則回覆')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-controls')).toBe('discussion-replies-10')
    expect(wrapper.find('#discussion-replies-10').exists()).toBe(false)

    await toggle.trigger('click')
    expect(wrapper.get('.discussion-thread-toggle__button').text()).toContain('收起 1 則回覆')
    expect(wrapper.get('.discussion-thread-toggle__button').attributes('aria-expanded')).toBe(
      'true'
    )
    expect(wrapper.find('#discussion-replies-10').exists()).toBe(true)

    wrapper.vm.applyDelete(11, false)
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.messages[0].replies).toHaveLength(0)
    expect(wrapper.vm.isThreadExpanded(10)).toBe(false)
    expect(wrapper.find('.discussion-thread-toggle__button').exists()).toBe(false)
  })

  it('rolls back optimistic like state and reports an error when the API fails', async () => {
    const socket = makeSocket()
    const wrapper = mountPanel(socket)
    const message = { id: 5, liked_by_current_user: false, like_count: 4 }
    mocks.like.mockRejectedValueOnce(new Error('network'))

    await wrapper.vm.toggleLike(message)

    expect(message.liked_by_current_user).toBe(false)
    expect(message.like_count).toBe(4)
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: '愛心更新失敗' })
    )
    expect(wrapper.vm.isLikeLoading(5)).toBe(false)
  })

  it('keeps one inline reply or report composer open and resets report state predictably', () => {
    const wrapper = mountPanel(makeSocket())
    const root = { id: 10, user_name: 'Root' }
    const reply = { id: 11, parent_id: 10, user_name: 'Reply' }
    wrapper.vm.draft = '保留一般留言草稿'

    wrapper.vm.startReply(root)
    wrapper.vm.replyDraft = '尚未送出的回覆'
    wrapper.vm.toggleReport(reply)

    expect(wrapper.vm.replyTarget).toBeNull()
    expect(wrapper.vm.replyDraft).toBe('')
    expect(wrapper.vm.reportTarget.id).toBe(reply.id)
    expect(wrapper.vm.draft).toBe('保留一般留言草稿')

    wrapper.vm.reportReason = 'other'
    wrapper.vm.reportCustomMessage = '自訂原因'
    wrapper.vm.startReply(root)

    expect(wrapper.vm.reportTarget).toBeNull()
    expect(wrapper.vm.reportReason).toBeNull()
    expect(wrapper.vm.reportCustomMessage).toBe('')
    expect(wrapper.vm.replyTarget.message.id).toBe(root.id)

    wrapper.vm.toggleReport(reply)
    wrapper.vm.toggleReport(reply)
    expect(wrapper.vm.reportTarget).toBeNull()
    expect(wrapper.vm.reportReason).toBeNull()
  })

  it('submits an inline report to the backend and clears only the report composer', async () => {
    const wrapper = mountPanel(makeSocket())
    wrapper.vm.reportTarget = { id: 10 }
    wrapper.vm.reportReason = 'misinformation'

    await wrapper.vm.handleReportSubmit({
      comment_id: 10,
      report_reason: 'misinformation',
      custom_message: null,
    })

    expect(mocks.report).toHaveBeenCalledWith(1, 2, 10, {
      report_reason: 'misinformation',
      custom_message: null,
    })
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        summary: '回報已送出',
        detail: '留言回報已送出，請等待管理員審核',
      })
    )
    expect(wrapper.vm.reportTarget).toBeNull()
    expect(wrapper.vm.reportSubmitting).toBe(false)
  })

  it('requires the localized irreversible-delete confirmation before deleting a comment', async () => {
    const require = vi.fn()
    const wrapper = mountPanel(makeSocket(), { require })
    const message = { id: 10, parent_id: null, replies: [{ id: 11, parent_id: 10 }] }

    wrapper.vm.confirmDelete(message)

    expect(require).toHaveBeenCalledTimes(1)
    const confirmation = require.mock.calls[0][0]
    expect(confirmation).toMatchObject({
      header: '刪除這則留言？',
      message: '留言刪除後無法復原，也不會進入垃圾桶。已有的回覆會依目前討論串規則保留。',
      rejectLabel: '取消',
      acceptLabel: '刪除',
      acceptClass: 'p-button-danger',
    })
    expect(mocks.remove).not.toHaveBeenCalled()

    confirmation.accept()
    confirmation.accept()
    await flushPromises()

    expect(mocks.remove).toHaveBeenCalledTimes(1)
    expect(mocks.remove).toHaveBeenCalledWith(1, 2, 10)
  })
})
