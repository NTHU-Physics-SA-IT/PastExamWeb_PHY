import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { Fragment, h } from 'vue'
import ReportManagementPanel from '@/components/admin/ReportManagementPanel.vue'
import reportManagementSource from '@/components/admin/ReportManagementPanel.vue?raw'
import { ADMIN_PAGE_SIZE_OPTIONS } from '@/constants/pagination'

const mocks = vi.hoisted(() => ({
  listSystem: vi.fn(),
  getSystem: vi.fn(),
  updateSystemReadState: vi.fn(),
  listComments: vi.fn(),
  getComment: vi.fn(),
  reviewComment: vi.fn(),
  deleteSystem: vi.fn(),
  deleteComment: vi.fn(),
  listArchives: vi.fn(),
  getArchive: vi.fn(),
  reviewArchive: vi.fn(),
  deleteArchive: vi.fn(),
  listWishReports: vi.fn(),
  getWishReport: vi.fn(),
  reviewWishReport: vi.fn(),
  deleteWishReport: vi.fn(),
  confirm: vi.fn((options) => options.accept?.()),
  toast: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/api', () => ({
  reportService: {
    listSystemIssues: mocks.listSystem,
    getSystemIssue: mocks.getSystem,
    updateSystemIssueReadState: mocks.updateSystemReadState,
    listCommentReports: mocks.listComments,
    getCommentReport: mocks.getComment,
    reviewCommentReport: mocks.reviewComment,
    deleteSystemIssue: mocks.deleteSystem,
    deleteCommentReport: mocks.deleteComment,
    listArchiveReports: mocks.listArchives,
    getArchiveReport: mocks.getArchive,
    reviewArchiveReport: mocks.reviewArchive,
    deleteArchiveReport: mocks.deleteArchive,
  },
  wishService: {
    listReports: mocks.listWishReports,
    getReport: mocks.getWishReport,
    reviewReport: mocks.reviewWishReport,
    removeReport: mocks.deleteWishReport,
  },
}))
vi.mock('@/utils/auth', () => ({ getCurrentUser: () => ({ id: 1, is_admin: true }) }))
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: mocks.toast }) }))
vi.mock('primevue/useconfirm', () => ({
  useConfirm: () => ({ require: mocks.confirm }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))

const slotStub = { template: '<div><slot /></div>' }

function flattenVNodes(nodes = []) {
  return nodes.flatMap((node) => (node.type === Fragment ? flattenVNodes(node.children) : node))
}

const rowDataTableStub = {
  inheritAttrs: false,
  props: ['value'],
  setup(props, { attrs, slots }) {
    return () => {
      const columns = flattenVNodes(slots.default?.()).filter(
        (node) => typeof node.children?.body === 'function'
      )
      return h(
        'div',
        { class: attrs.class },
        (props.value || []).map((data) =>
          h(
            'div',
            { class: 'test-report-row', 'data-report-id': data.id },
            columns.map((column) => h('div', {}, column.children.body({ data })))
          )
        )
      )
    }
  },
}

function mountPanel({ renderRows = false, cardLayout = false, mediaQuery = null } = {}) {
  if (renderRows) {
    window.matchMedia = vi.fn(
      () =>
        mediaQuery || {
          matches: cardLayout,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }
    )
  }
  return mount(ReportManagementPanel, {
    global: {
      stubs: {
        Tabs: slotStub,
        TabList: slotStub,
        Tab: slotStub,
        TabPanels: slotStub,
        TabPanel: slotStub,
        DataTable: renderRows ? rowDataTableStub : slotStub,
        Column: {
          props: {
            header: String,
            sortable: Boolean,
            sortField: String,
          },
          template:
            '<div class="column-header" :data-sortable="String(Boolean(sortable))" :data-sort-field="sortField || \'\'">{{ header }}</div>',
        },
        Dialog: slotStub,
        Button: { props: ['label'], template: '<button>{{ label }}</button>' },
        InputText: true,
        Select: true,
        Tag: { props: ['value'], template: '<span class="tag-stub">{{ value }}</span>' },
        Message: slotStub,
        Textarea: true,
        Checkbox: true,
      },
    },
  })
}

describe('ReportManagementPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listSystem.mockResolvedValue({ data: { items: [], total: 0 } })
    mocks.getSystem.mockResolvedValue({ data: { id: 1, is_read: false } })
    mocks.updateSystemReadState.mockResolvedValue({ data: { id: 1, is_read: true } })
    mocks.listComments.mockResolvedValue({ data: { items: [], total: 0 } })
    mocks.listArchives.mockResolvedValue({ data: { items: [], total: 0 } })
    mocks.listWishReports.mockResolvedValue({ data: { items: [], total: 0 } })
    mocks.deleteSystem.mockResolvedValue({ data: { success: true } })
    mocks.deleteComment.mockResolvedValue({ data: { success: true } })
    mocks.confirm.mockImplementation((options) => options.accept?.())
  })

  it('keeps the four report sources separated without per-row GitHub presentation', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('系統問題回報')
    expect(wrapper.text()).toContain('留言回報')
    expect(wrapper.text()).toContain('考古題回報')
    expect(wrapper.text()).toContain('依課程、考古題、回報者、原因與狀態搜尋')
    expect(mocks.listSystem).toHaveBeenCalled()
    expect(mocks.listComments).toHaveBeenCalled()
    expect(mocks.listArchives).toHaveBeenCalled()
    expect(wrapper.findAll('.report-section')).toHaveLength(4)
    expect(wrapper.find('.report-management__header').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('檢視系統問題摘要並審核留言回報')
    const systemHeaders = wrapper
      .find('.report-management__system-table')
      .findAll('.column-header')
      .map((header) => header.text())
    expect(systemHeaders).toEqual(['回報', '標題與內容', '類型', '說明', '狀態', '操作'])
    expect(systemHeaders).not.toContain('回報時間')
    expect(systemHeaders).not.toContain('回報者')
    const commentHeaders = wrapper
      .find('.report-management__comment-table')
      .findAll('.column-header')
      .map((header) => header.text())
    expect(commentHeaders).toEqual([
      '回報',
      '原因與留言摘要',
      '留言者',
      '課程／考古題',
      '狀態',
      '審核',
      '操作',
    ])
    const wishHeaders = wrapper
      .findAll('.report-section')[3]
      .findAll('.column-header')
      .map((header) => header.text())
    expect(wishHeaders).toEqual(['回報者', '回報原因', '許願者', '許願目標', '狀態', '操作'])
    for (const removedHeader of ['回報時間', '回報者', '留言作者', '審核人', '審核時間']) {
      expect(commentHeaders).not.toContain(removedHeader)
    }
    expect(wrapper.text()).not.toContain('回報編號')
    expect(wrapper.vm.activeTab).toBeUndefined()
    expect(wrapper.vm.archiveListState).toMatchObject({ first: 0, total: 0, loading: false })
    expect(wrapper.vm.formatDateTime('2020-07-20T13:37:00Z', true)).toBe('2020/07/20 21:37')
    expect(wrapper.vm.formatDateTime('2020-07-20T13:37:00Z', true)).not.toMatch(/上午|下午/)
    expect(wrapper.vm.formatDateTime(new Date(Date.now() - 5 * 60_000).toISOString())).toBe(
      '5 分鐘前'
    )
    expect(reportManagementSource).not.toContain('header="GitHub Issue"')
    expect(reportManagementSource).not.toContain('label="前往 GitHub"')
    expect(reportManagementSource).toContain(':label="$t(\'前往專案 Issues\')"')
    expect(reportManagementSource).toContain('rel="noopener noreferrer"')
  })

  it('keeps wish report inspect, review, and permanent-delete actions wired', async () => {
    const report = {
      id: 303,
      reporter_name: '許願回報者',
      wisher_name: '原始許願者',
      created_at: '2026-08-18T01:00:00Z',
      reason: 'misinformation',
      wish_title: '普通物理期中考',
      target_summary: '普通物理 · 王老師 · term:1141 · midterm1',
      status: 'pending',
      admin_response: null,
    }
    mocks.listWishReports.mockResolvedValueOnce({ data: { items: [report], total: 1 } })
    mocks.getWishReport.mockResolvedValueOnce({ data: report })
    mocks.reviewWishReport.mockResolvedValueOnce({
      data: { ...report, status: 'upheld', admin_response: '已確認' },
    })
    mocks.deleteWishReport.mockResolvedValueOnce({ data: { success: true } })

    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.vm.openWishReport(report.id)
    expect(mocks.getWishReport).toHaveBeenCalledWith(report.id)
    expect(wrapper.vm.wishReviewVisible).toBe(true)
    const target = wrapper
      .findAll('.report-review__meta > div')
      .find((item) => item.get('dt').text() === '許願目標')
    expect(target.get('dd').text()).toBe('普通物理 · 王老師 · 114上學期 · midterm1')
    expect(target.get('dd').text()).not.toContain(report.wish_title)
    expect(target.get('dd').text()).not.toContain('term:')

    wrapper.vm.wishReviewForm = { status: 'upheld', admin_response: '已確認' }
    wrapper.vm.confirmSaveWishReview()
    await flushPromises()
    expect(mocks.reviewWishReport).toHaveBeenCalledWith(report.id, {
      status: 'upheld',
      admin_response: '已確認',
    })

    wrapper.vm.confirmDeleteWishReport(report)
    await flushPromises()
    expect(mocks.deleteWishReport).toHaveBeenCalledWith(report.id)
  })

  it('renders a readable mobile wish report card with distinct reporter and wisher', async () => {
    mocks.listWishReports.mockResolvedValueOnce({
      data: {
        total: 1,
        items: [
          {
            id: 304,
            reporter_name: '回報者乙',
            wisher_name: '許願者甲',
            created_at: '2026-08-18T01:00:00Z',
            reason: 'misinformation',
            wish_title: '普通物理期中考',
            target_summary: '普通物理 · 王老師 · term:any · midterm1',
            status: 'pending',
            reviewer_name: null,
            reviewed_at: null,
          },
        ],
      },
    })

    const wrapper = mountPanel({ renderRows: true, cardLayout: true })
    await flushPromises()

    const row = wrapper.get('.report-management__wish-table .test-report-row')
    const card = row.get('.report-mobile-card')
    expect(row.findAll('.report-mobile-card')).toHaveLength(1)
    expect(card.text()).toContain('回報者乙')
    expect(card.text()).toContain('許願者甲')
    expect(card.text()).toContain('普通物理期中考')
    expect(card.text()).toContain('王老師')
    expect(card.text()).toContain('待審核')
    expect(card.text().match(/普通物理期中考/g)).toHaveLength(1)
    expect(card.get('.report-mobile-summary-preview__label').text()).toBe('許願標題')
    expect(card.get('.report-mobile-summary-preview__text').text()).toBe('普通物理期中考')
    const wishTarget = card
      .findAll('.report-mobile-info-item')
      .find((item) => item.get('dt').text() === '許願目標')
    expect(wishTarget.get('dd').text()).toBe('普通物理 · 王老師 · 不限學期 · midterm1')
    expect(row.findAll('.report-person-time')).toHaveLength(0)
    expect(row.findAll('.comment-report-content')).toHaveLength(0)
    expect(card.findAll('button').map((button) => button.text())).toEqual(['檢視／審核', '刪除'])
  })

  it('renders archive reports on mobile and wires optional takedown review', async () => {
    const report = {
      id: 31,
      reporter_name: '考古題回報者',
      created_at: '2026-07-28T01:00:00Z',
      reason: 'incomplete_or_low_quality',
      supplementary_detail: '第三頁模糊',
      course_name: '電磁學',
      archive_name: '期中考',
      archive_id: 88,
      archive_id_snapshot: 88,
      professor: '王老師',
      status: 'pending',
      reviewer_name: null,
      reviewed_at: null,
      source_exists: true,
      source_state: 'available',
      can_take_down: true,
      archive_taken_down: false,
    }
    mocks.listArchives.mockResolvedValue({ data: { items: [report], total: 1 } })
    mocks.getArchive.mockResolvedValue({ data: report })
    mocks.reviewArchive.mockResolvedValue({
      data: { ...report, status: 'upheld', archive_taken_down: true },
    })

    const wrapper = mountPanel({ renderRows: true, cardLayout: true })
    await flushPromises()

    expect(wrapper.text()).toContain('考古題回報者')
    expect(wrapper.text()).toContain('第三頁模糊')
    expect(wrapper.text()).toContain('電磁學')
    const archiveCard = wrapper.get('.report-management__archive-table .report-mobile-card')
    expect(archiveCard.text()).toContain('檔案模糊、缺頁或內容不完整')
    expect(archiveCard.text()).toContain('待審核')
    expect(archiveCard.text()).toContain('期中考')
    expect(archiveCard.text()).toContain('#88')
    expect(
      archiveCard
        .findAll('.report-mobile-info-item')
        .find((item) => item.text().includes('審核時間'))
        ?.text()
    ).toContain('--')
    expect(archiveCard.findAll('button').map((button) => button.text())).toEqual([
      '檢視／審核',
      '刪除',
    ])

    await wrapper.vm.openArchiveReport(report.id)
    wrapper.vm.archiveReviewForm.status = 'upheld'
    wrapper.vm.archiveReviewForm.admin_response = '已確認'
    wrapper.vm.archiveReviewForm.take_down_archive = true
    await wrapper.vm.saveArchiveReview()
    await flushPromises()

    expect(mocks.reviewArchive).toHaveBeenCalledWith(report.id, {
      status: 'upheld',
      admin_response: '已確認',
      take_down_archive: true,
    })
    expect(wrapper.vm.selectedArchiveReport.archive_taken_down).toBe(true)
  })

  it('clears archive takedown when review is dismissed or source is unavailable', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    wrapper.vm.selectedArchiveReport = {
      id: 32,
      status: 'pending',
      source_state: 'trashed',
      can_take_down: false,
    }
    wrapper.vm.archiveReviewForm.status = 'upheld'
    wrapper.vm.archiveReviewForm.take_down_archive = true
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.canSaveArchiveReview).toBe(false)

    wrapper.vm.archiveReviewForm.status = 'dismissed'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.archiveReviewForm.take_down_archive).toBe(false)
    expect(wrapper.vm.canSaveArchiveReview).toBe(true)
  })

  it('opens a full local-summary detail without unsafe HTML', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const report = {
      id: 12,
      reporter_name: '回報者',
      created_at: '2026-07-22T10:00:00Z',
      report_type: 'bug',
      title: '完整標題',
      description: '第一行\n第二行很長的完整內容',
      contact: null,
    }

    mocks.getSystem.mockResolvedValue({ data: report })
    await wrapper.vm.openSystemReport(report)
    await flushPromises()

    expect(wrapper.vm.systemDetailVisible).toBe(true)
    expect(wrapper.vm.selectedSystemReport).toEqual(report)
    expect(wrapper.text()).toContain('完整標題')
    expect(wrapper.text()).toContain('第一行\n第二行很長的完整內容')
    expect(wrapper.text()).toContain('未提供')
    expect(wrapper.text()).toContain('無法確認使用者是否已在 GitHub 正式建立 Issue')
    expect(reportManagementSource).not.toContain('v-html')
    expect(reportManagementSource).toContain(':aria-label="$t(\'檢視系統問題回報\')"')
    const fields = wrapper.findAll('.system-report-detail__content.report-review__content-field')
    expect(fields).toHaveLength(2)
    expect(fields[0].get('.report-review__content-label').text()).toBe('問題標題')
    expect(fields[0].get('.report-review__content-block').text()).toBe('完整標題')
    expect(fields[1].get('.report-review__content-label').text()).toBe('完整詳細描述')
    expect(fields[1].get('.report-review__content-block').text()).toContain(
      '第一行\n第二行很長的完整內容'
    )
    expect(reportManagementSource).toContain('overflow-wrap: anywhere')
    expect(reportManagementSource).toContain('word-break: break-word')
    expect(reportManagementSource).toContain('white-space: pre-wrap')
    expect(mocks.getSystem).toHaveBeenCalledWith(report.id)
    expect(mocks.updateSystemReadState).not.toHaveBeenCalled()
  })

  it('frames reporter-authored comment and archive content consistently', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    mocks.getComment.mockResolvedValueOnce({
      data: {
        id: 71,
        status: 'pending',
        reporter_name: 'Reporter',
        comment_author_name: 'Author',
        reason: 'misinformation',
        course_name: 'Course',
        archive_name: 'Exam',
        comment_content_snapshot: 'snapshot\nwith-a-very-long-token-abcdef',
        comment_created_at_snapshot: '2026-07-28T00:00:00Z',
        custom_message: null,
        source_exists: true,
      },
    })
    await wrapper.vm.openCommentReport(71)
    await flushPromises()

    let fields = wrapper.findAll('.report-review__content-field')
    let blocks = wrapper.findAll('.report-review__content-block')
    expect(fields).toHaveLength(2)
    expect(blocks).toHaveLength(2)
    expect(fields[0].get('.report-review__content-label').text()).toBe('留言內容快照')
    expect(blocks[0].text()).toContain('snapshot\nwith-a-very-long-token-abcdef')
    expect(fields[1].get('.report-review__content-label').text()).toBe('回報者補充')
    expect(blocks[1].text()).toContain('未提供補充')
    wrapper.vm.selectedReport = null

    mocks.getArchive.mockResolvedValueOnce({
      data: {
        id: 72,
        status: 'pending',
        reporter_name: 'Reporter',
        reason: 'metadata_mismatch',
        course_name: 'Course',
        archive_name: 'Exam',
        archive_id_snapshot: 99,
        academic_year: 2026,
        professor: 'Professor',
        source_exists: true,
        source_state: 'available',
        can_take_down: true,
        archive_taken_down: false,
        supplementary_detail: null,
      },
    })
    await wrapper.vm.openArchiveReport(72)
    await flushPromises()

    fields = wrapper.findAll('.report-review__content-field')
    blocks = wrapper.findAll('.report-review__content-block')
    expect(fields).toHaveLength(1)
    expect(blocks).toHaveLength(1)
    expect(fields[0].get('.report-review__content-label').text()).toBe('補充說明')
    expect(blocks[0].text()).toContain('未提供補充說明')
    expect(reportManagementSource).toContain('border: 1px solid var(--border-color)')
    expect(reportManagementSource).toMatch(
      /\.report-review__content-block\s*\{[^}]*background:\s*transparent;/
    )
    expect(reportManagementSource).not.toContain('var(--surface-border)')
    expect(reportManagementSource).not.toContain('var(--surface-50)')
    expect(reportManagementSource).toContain('var(--app-font-size-base)')
  })

  it('keeps metadata two-column on narrow dialogs and uses the shared Thread info pill', () => {
    expect(reportManagementSource).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.report-review__meta\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);/
    )
    expect(reportManagementSource).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.report-review__meta dd\s*\{[^}]*overflow-wrap:\s*anywhere;[^}]*word-break:\s*break-word;/
    )
    expect(reportManagementSource).toContain(
      'class="soft-badge soft-badge--info report-review__thread-hint"'
    )
    expect(reportManagementSource).toMatch(
      /report-review__thread-hint\.p-tag\)\s*\{[^}]*display:\s*inline-flex;[^}]*max-width:\s*100%;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/
    )
  })

  it('submits archive review without an admin response and renders the fallback', async () => {
    const report = {
      id: 73,
      status: 'pending',
      reporter_name: 'Reporter',
      reason: 'metadata_mismatch',
      course_name: 'Course',
      archive_name: 'Exam',
      archive_id_snapshot: 99,
      academic_year: 2026,
      professor: 'Professor',
      source_exists: true,
      source_state: 'available',
      can_take_down: true,
      archive_taken_down: false,
      supplementary_detail: 'Details',
      admin_response: null,
    }
    mocks.getArchive.mockResolvedValueOnce({ data: report })
    mocks.reviewArchive.mockResolvedValueOnce({
      data: { ...report, status: 'dismissed', admin_response: null },
    })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.vm.openArchiveReport(report.id)
    expect(wrapper.get('#archive-admin-response').attributes('placeholder')).toBe(
      '可留空；若未提供答覆，通知中將顯示「未提供答覆」。'
    )
    wrapper.vm.archiveReviewForm.status = 'dismissed'
    wrapper.vm.archiveReviewForm.admin_response = '   '
    await wrapper.vm.saveArchiveReview()
    await flushPromises()

    expect(mocks.reviewArchive).toHaveBeenCalledWith(report.id, {
      status: 'dismissed',
      admin_response: null,
      take_down_archive: false,
    })
    expect(wrapper.text()).toContain('管理員答覆：')
    expect(wrapper.text()).toContain('未提供答覆')
  })

  it('updates read state only after explicit save and supports marking unread again', async () => {
    const report = {
      id: 42,
      reporter_name: '回報者',
      report_type: 'bug',
      title: '問題',
      description: '內容',
      is_read: false,
      read_at: null,
      read_by_username: null,
    }
    mocks.getSystem.mockResolvedValue({ data: report })
    mocks.updateSystemReadState
      .mockResolvedValueOnce({
        data: {
          ...report,
          is_read: true,
          read_at: '2026-07-22T12:00:00Z',
          read_by_username: '管理員',
        },
      })
      .mockResolvedValueOnce({ data: { ...report, is_read: false } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.vm.openSystemReport(report)
    expect(mocks.updateSystemReadState).not.toHaveBeenCalled()

    wrapper.vm.systemReadForm = true
    await wrapper.vm.saveSystemReadState()
    expect(mocks.updateSystemReadState).toHaveBeenNthCalledWith(1, report.id, true)
    expect(wrapper.vm.selectedSystemReport.is_read).toBe(true)

    wrapper.vm.systemReadForm = false
    await wrapper.vm.saveSystemReadState()
    expect(mocks.updateSystemReadState).toHaveBeenNthCalledWith(2, report.id, false)
    expect(wrapper.vm.selectedSystemReport.is_read).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ summary: '閱讀狀態已更新' }))
  })

  it('keeps the previous read state when saving fails', async () => {
    const report = { id: 52, is_read: false }
    mocks.getSystem.mockResolvedValue({ data: report })
    mocks.updateSystemReadState.mockRejectedValueOnce(new Error('unavailable'))
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.vm.openSystemReport(report)

    wrapper.vm.systemReadForm = true
    await wrapper.vm.saveSystemReadState()

    expect(wrapper.vm.selectedSystemReport.is_read).toBe(false)
    expect(wrapper.vm.systemReadForm).toBe(false)
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ summary: '更新失敗' }))
  })

  it('uses compact columns and independently clamps each summary body to three lines', () => {
    expect(reportManagementSource).toContain('system-report-summary__title')
    expect(reportManagementSource).toMatch(
      /\.system-report-summary__title\s*\{[\s\S]*?white-space:\s*nowrap;/
    )
    expect(reportManagementSource).toMatch(
      /\.system-report-summary__body\s*\{[\s\S]*?white-space:\s*normal;[\s\S]*?-webkit-line-clamp:\s*3;/
    )
    expect(reportManagementSource).toMatch(
      /\.comment-report-content__summary\s*\{[\s\S]*?white-space:\s*normal;[\s\S]*?-webkit-line-clamp:\s*3;/
    )
    expect(reportManagementSource).toContain('width: clamp(15rem, 22vw, 21.25rem)')
    expect(reportManagementSource).toContain(':header="$t(\'原因與留言摘要\')"')
    expect(reportManagementSource).toContain('headerClass="report-user-column"')
    expect(reportManagementSource).toContain('headerClass="report-person-time-column"')
    expect(reportManagementSource).toContain('headerClass="report-review-column"')
    expect(reportManagementSource).toContain('headerClass="report-actions-column"')
    expect(reportManagementSource).toMatch(
      /report-person-time__name[\s\S]*?reporter_name[\s\S]*?report-person-time__time[\s\S]*?created_at/
    )
    expect(reportManagementSource).toContain("data.reviewer_name || $t('尚未審核')")
    expect(reportManagementSource).toContain(
      '<span v-else class="report-person-time__time">--</span>'
    )
  })

  it('keeps all report action groups aligned without wrapping button labels', () => {
    expect(reportManagementSource.match(/class="report-row-actions"/g)).toHaveLength(8)
    expect(
      reportManagementSource.match(/v-if="!isCardLayout" class="report-desktop-actions"/g)
    ).toHaveLength(3)
    expect(reportManagementSource.match(/class="report-mobile-card__footer"/g)).toHaveLength(4)
    expect(reportManagementSource).toContain(
      'headerClass="report-actions-column report-actions-column--system"'
    )
    expect(reportManagementSource).toContain('style="width: 12rem; min-width: 12rem"')
    expect(reportManagementSource).toContain('style="width: 17rem; min-width: 17rem"')
    expect(reportManagementSource).toMatch(
      /\.report-row-actions\s*\{[\s\S]*?display:\s*inline-flex;[\s\S]*?align-items:\s*center;[\s\S]*?justify-content:\s*flex-start;[\s\S]*?flex-wrap:\s*nowrap;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-row-actions :deep\(\.p-button\)\s*\{[\s\S]*?white-space:\s*nowrap;/
    )
    expect(reportManagementSource).not.toContain(
      ':deep(.report-management__table .p-datatable-tbody > tr > td:last-child)'
    )
    expect(reportManagementSource).not.toContain('justify-content: flex-end;\n  flex-wrap: nowrap')
    expect(reportManagementSource.match(/breakpoint="1399\.98px"/g)).toHaveLength(4)
  })

  it('keeps pagination and server sorting independent for each report list', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.vm.systemPage).toMatchObject({ sortField: 'read_state', sortOrder: 1 })
    expect(wrapper.vm.commentPage).toMatchObject({ sortField: 'status', sortOrder: 1 })
    expect(wrapper.vm.wishPage).toMatchObject({ sortField: 'created_at', sortOrder: -1 })
    expect(mocks.listSystem).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'read_state', sort_order: 'asc' })
    )
    expect(mocks.listComments).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'status', sort_order: 'asc' })
    )
    expect(mocks.listWishReports).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'created_at', sort_order: 'desc' })
    )

    mocks.listSystem.mockClear()
    mocks.listComments.mockClear()
    mocks.listWishReports.mockClear()

    await wrapper.vm.onSystemPage({ first: 10, rows: 10 })
    wrapper.vm.systemFilters.readState = 'unread'
    await wrapper.vm.applySystemFilters()
    await wrapper.vm.onSystemSort({ sortField: 'read_state', sortOrder: 1 })
    await wrapper.vm.onCommentSort({ sortField: 'reviewed_at', sortOrder: -1 })
    wrapper.vm.wishFilters = { search: '普通物理', status: 'pending' }
    await wrapper.vm.onWishSort({ sortField: 'wisher', sortOrder: 1 })
    await wrapper.vm.onWishPage({ first: 10, rows: 10 })

    expect(mocks.listSystem).toHaveBeenLastCalledWith(
      expect.objectContaining({
        offset: 0,
        limit: 10,
        read_state: 'unread',
        sort_by: 'read_state',
        sort_order: 'asc',
      })
    )
    expect(mocks.listComments).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'reviewed_at', sort_order: 'desc' })
    )
    expect(wrapper.vm.systemPage.first).toBe(0)
    expect(wrapper.vm.commentPage.first).toBe(0)
    expect(wrapper.vm.wishPage).toMatchObject({
      first: 10,
      rows: 10,
      sortField: 'wisher',
      sortOrder: 1,
    })
    expect(mocks.listWishReports).toHaveBeenLastCalledWith(
      expect.objectContaining({
        search: '普通物理',
        status: 'pending',
        offset: 10,
        limit: 10,
        sort_by: 'wisher',
        sort_order: 'asc',
      })
    )
    expect(reportManagementSource).toMatch(
      /field="read_state"[\s\S]*?sortField="read_state"[\s\S]*?:header="\$t\('狀態'\)"[\s\S]*?sortable/
    )

    await wrapper.vm.refreshAll()
    expect(wrapper.vm.systemPage).toMatchObject({ first: 0, sortField: 'read_state', sortOrder: 1 })
    expect(wrapper.vm.commentPage).toMatchObject({ first: 0, sortField: 'status', sortOrder: 1 })
    expect(mocks.listSystem).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'read_state', sort_order: 'asc' })
    )
    expect(mocks.listComments).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'status', sort_order: 'asc' })
    )
    expect(wrapper.vm.wishPage).toMatchObject({
      first: 0,
      sortField: 'created_at',
      sortOrder: -1,
    })
    expect(mocks.listWishReports).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'created_at', sort_order: 'desc' })
    )
  })

  it('marks meaningful wish report headers sortable but keeps actions static', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    const wishHeaders = wrapper.find('.report-management__wish-table').findAll('.column-header')
    expect(wishHeaders.map((header) => header.text())).toEqual([
      '回報者',
      '回報原因',
      '許願者',
      '許願目標',
      '狀態',
      '操作',
    ])
    expect(wishHeaders.slice(0, 5).map((header) => header.attributes('data-sortable'))).toEqual([
      'true',
      'true',
      'true',
      'true',
      'true',
    ])
    expect(wishHeaders[5].attributes('data-sortable')).toBe('false')
    expect(wishHeaders.map((header) => header.attributes('data-sort-field'))).toEqual([
      'created_at',
      'reason',
      'wisher',
      'wish_target',
      'status',
      '',
    ])
  })

  it('shares admin page-size options while keeping report pagination state independent', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    mocks.listSystem.mockClear()
    mocks.listComments.mockClear()

    expect(ADMIN_PAGE_SIZE_OPTIONS).toEqual([5, 10, 15, 25, 50])
    expect(
      reportManagementSource.match(/:rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"/g)
    ).toHaveLength(4)
    expect(wrapper.vm.systemPage).toMatchObject({ first: 0, rows: 10 })
    expect(wrapper.vm.commentPage).toMatchObject({ first: 0, rows: 10 })
    expect(wrapper.vm.wishPage).toMatchObject({ first: 0, rows: 10 })

    await wrapper.vm.onSystemPage({ first: 20, rows: 5 })
    expect(wrapper.vm.systemPage).toMatchObject({ first: 0, rows: 5 })
    expect(wrapper.vm.commentPage).toMatchObject({ first: 0, rows: 10 })
    expect(mocks.listSystem).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, limit: 5 })
    )

    await wrapper.vm.onCommentPage({ first: 25, rows: 25 })
    expect(wrapper.vm.commentPage).toMatchObject({ first: 0, rows: 25 })
    expect(wrapper.vm.systemPage).toMatchObject({ first: 0, rows: 5 })
    expect(mocks.listComments).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, limit: 25 })
    )
  })

  it('moves each report type to trash once and clamps an emptied last page', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    wrapper.vm.systemIssues = [{ id: 11, title: 'System' }]
    wrapper.vm.systemTotal = 11
    wrapper.vm.systemPage = { ...wrapper.vm.systemPage, first: 10, rows: 10 }
    wrapper.vm.commentReports = [{ id: 22, reason: 'misinformation' }]
    wrapper.vm.commentTotal = 11
    wrapper.vm.commentPage = { ...wrapper.vm.commentPage, first: 10, rows: 10 }

    wrapper.vm.confirmDeleteSystemIssue({ id: 11, title: 'System' })
    wrapper.vm.confirmDeleteSystemIssue({ id: 11, title: 'System' })
    wrapper.vm.confirmDeleteCommentReport({ id: 22, reason: 'misinformation' })
    wrapper.vm.confirmDeleteCommentReport({ id: 22, reason: 'misinformation' })
    await flushPromises()

    expect(mocks.deleteSystem).toHaveBeenCalledTimes(1)
    expect(mocks.deleteSystem).toHaveBeenCalledWith(11)
    expect(mocks.deleteComment).toHaveBeenCalledTimes(1)
    expect(mocks.deleteComment).toHaveBeenCalledWith(22)
    expect(wrapper.vm.systemPage.first).toBe(0)
    expect(wrapper.vm.commentPage.first).toBe(0)
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ summary: '回報已移至垃圾桶' })
    )
    expect(reportManagementSource).toContain(':aria-label="$t(\'刪除系統問題回報\')"')
    expect(reportManagementSource).toContain(':aria-label="$t(\'刪除留言回報\')"')
    expect(reportManagementSource).toContain(
      '回報會移至垃圾桶，可由管理員在垃圾桶中還原或永久刪除。'
    )
  })

  it('keeps the available section usable when another report request fails', async () => {
    mocks.listSystem.mockRejectedValueOnce(new Error('system unavailable'))
    mocks.listComments.mockResolvedValueOnce({ data: { items: [{ id: 9 }], total: 1 } })

    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.vm.systemError).toContain('無法載入系統問題回報')
    expect(wrapper.vm.commentError).toBe('')
    expect(wrapper.vm.commentReports).toEqual([{ id: 9 }])
  })

  it('loads and saves a comment review through the admin API', async () => {
    const report = {
      id: 8,
      status: 'pending',
      admin_response: null,
      source_exists: false,
      reporter_name: 'Reporter',
      comment_author_name: 'Author',
      reason: 'misinformation',
      course_name: 'Course',
      archive_name: 'Exam',
      comment_content_snapshot: 'content',
      thread_id: 31,
    }
    mocks.getComment.mockResolvedValue({ data: report })
    mocks.reviewComment.mockResolvedValue({ data: { ...report, status: 'upheld' } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.vm.openCommentReport(8)
    expect(wrapper.text()).toContain('Thread')
    expect(wrapper.text()).toContain('#31')
    expect(wrapper.text()).toContain('此識別碼代表該回覆串的第一則留言，用於定位討論串。')
    expect(wrapper.text()).toContain('來源留言已不存在')
    expect(wrapper.get('.report-review__message').text()).toContain(
      '來源留言已不存在；仍可根據快照完成審核。'
    )
    expect(reportManagementSource).not.toContain('討論串起始留言')
    expect(reportManagementSource).not.toContain('留言 #${selectedReport.thread_id}')
    expect(reportManagementSource).toContain(
      'class="soft-badge soft-badge--info report-review__thread-hint"'
    )
    expect(reportManagementSource).toContain('threadId: item.thread_id')
    expect(reportManagementSource).toContain('messageId: item.comment_id')
    expect(wrapper.get('textarea-stub').attributes('placeholder')).toBe(
      '可留空；若未提供答覆，通知中將顯示「未提供答覆」。'
    )
    expect(wrapper.vm.reviewForm.admin_response).toBe('')
    wrapper.vm.reviewForm.status = 'upheld'
    wrapper.vm.reviewForm.admin_response = '   '
    await wrapper.vm.saveReview()

    expect(mocks.reviewComment).toHaveBeenCalledWith(8, {
      status: 'upheld',
      admin_response: null,
      delete_comment: false,
    })
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ summary: '審核已更新' }))
    expect(wrapper.vm.statusLabel('pending')).toBe('待審核')
    expect(wrapper.vm.statusLabel('upheld')).toBe('回報成立')
    expect(wrapper.vm.statusLabel('dismissed')).toBe('回報不成立')
    expect(wrapper.vm.statusSeverity('pending')).toBe('warn')
    expect(wrapper.vm.statusSeverity('upheld')).toBe('success')
    expect(wrapper.vm.statusSeverity('dismissed')).toBe('danger')
    expect(reportManagementSource).not.toContain('in_review')
    expect(reportManagementSource).toContain("selectedReport.admin_response || $t('未提供答覆')")
  })

  it('keeps one secondary Thread hint structure across review and source states', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const scenarios = [
      { id: 81, status: 'pending', source_exists: false },
      { id: 82, status: 'upheld', source_exists: true },
      { id: 83, status: 'dismissed', source_exists: false },
    ]

    for (const scenario of scenarios) {
      mocks.getComment.mockResolvedValueOnce({
        data: {
          ...scenario,
          thread_id: 31,
          reporter_name: 'Reporter',
          comment_author_name: 'Author',
          reason: 'misinformation',
          course_name: 'Course',
          archive_name: 'Exam',
          comment_content_snapshot: 'content',
        },
      })
      await wrapper.vm.openCommentReport(scenario.id)
      await flushPromises()

      const thread = wrapper.get('.report-review__thread')
      const threadId = thread.get('.report-review__thread-id')
      const hint = thread.get('.report-review__thread-hint')
      expect(thread.get('dt').text()).toBe('Thread')
      expect(threadId.text()).toBe('#31')
      expect(hint.text()).toBe('此識別碼代表該回覆串的第一則留言，用於定位討論串。')
      expect(hint.element.tagName).toBe('SPAN')
      expect(hint.classes()).toContain('soft-badge')
      expect(hint.classes()).toContain('soft-badge--info')
      expect(threadId.classes()).not.toContain('report-review__thread-hint')
      expect(hint.classes()).not.toContain('report-review__thread-id')
    }

    expect(
      reportManagementSource.match(
        /class="soft-badge soft-badge--info report-review__thread-hint"/g
      )
    ).toHaveLength(1)
    expect(reportManagementSource).toMatch(
      /report-review__thread-hint\.p-tag\)\s*\{[^}]*display:\s*inline-flex;[^}]*max-width:\s*100%;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/
    )
    expect(reportManagementSource).not.toContain('<small class="report-review__thread-hint"')
    expect(reportManagementSource).not.toMatch(
      /\.report-review__thread-content > \.report-review__thread-hint\s*\{[^}]*font-size:\s*var\(--app-font-size-xs\)/
    )
    expect(reportManagementSource).not.toContain('討論串起始留言')
  })

  it('uses a localized final-review confirmation and sends at most one request', async () => {
    const report = {
      id: 18,
      status: 'pending',
      admin_response: null,
      source_exists: true,
      reporter_name: 'Reporter',
      comment_author_name: 'Author',
      reason: 'misinformation',
      course_name: 'Course',
      archive_name: 'Exam',
      comment_content_snapshot: 'content',
    }
    mocks.getComment.mockResolvedValue({ data: report })
    mocks.reviewComment.mockResolvedValue({ data: { ...report, status: 'upheld' } })
    mocks.confirm.mockImplementation((options) => {
      options.accept?.()
      options.accept?.()
    })
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.vm.openCommentReport(report.id)
    wrapper.vm.reviewForm.status = 'upheld'

    wrapper.vm.confirmSaveReview()
    await flushPromises()

    expect(mocks.confirm).toHaveBeenCalledWith(
      expect.objectContaining({
        header: '確認送出審核結果',
        message: expect.stringContaining('送出後將通知回報者。'),
        rejectLabel: '取消',
        acceptLabel: '確認送出',
        defaultFocus: 'reject',
      })
    )
    expect(mocks.confirm.mock.calls[0][0].message).toContain(
      '審核結果與管理員答覆送出後將無法修改。'
    )
    expect(mocks.reviewComment).toHaveBeenCalledTimes(1)
  })

  it('cancels without an API call and warns when the source comment will be deleted', async () => {
    const report = {
      id: 28,
      status: 'pending',
      admin_response: null,
      source_exists: true,
      reporter_name: 'Reporter',
      comment_author_name: 'Author',
      reason: 'misinformation',
      course_name: 'Course',
      archive_name: 'Exam',
      comment_content_snapshot: 'content',
    }
    mocks.getComment.mockResolvedValue({ data: report })
    mocks.confirm.mockImplementation(() => {})
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.vm.openCommentReport(report.id)
    wrapper.vm.reviewForm.status = 'upheld'
    wrapper.vm.reviewForm.delete_comment = true

    wrapper.vm.confirmSaveReview()

    const options = mocks.confirm.mock.calls[0][0]
    expect(options.message).toContain('被回報留言將永久刪除，無法復原，也不會進入垃圾桶。')
    expect(options.acceptClass).toBe('p-button-danger')
    expect(mocks.reviewComment).not.toHaveBeenCalled()
  })

  it('keeps finalized reports read-only in the dialog and API handler', async () => {
    const finalized = {
      id: 38,
      status: 'dismissed',
      admin_response: '審核完成',
      source_exists: true,
    }
    mocks.getComment.mockResolvedValue({ data: finalized })
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.vm.openCommentReport(finalized.id)

    await wrapper.vm.saveReview()

    expect(mocks.reviewComment).not.toHaveBeenCalled()
    expect(wrapper.get('.report-review__message').text()).toContain('審核結果已送出，無法修改。')
    expect(reportManagementSource).toContain('審核結果已送出，無法修改。')
    expect(reportManagementSource).toContain("isFinal(data.status) ? $t('檢視') : $t('檢視／審核')")
    expect(reportManagementSource).toContain('v-if="!isFinal(selectedReport.status)"')
  })

  it('scopes personalized font tokens across report lists, controls, and dialogs', () => {
    expect(reportManagementSource.match(/class="report-management-dialog"/g)).toHaveLength(4)
    expect(reportManagementSource).toMatch(
      /\.report-management :deep\(\.p-inputtext\)[\s\S]*?font-size:\s*var\(--app-font-size-sm\) !important;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-management :deep\(\.p-button\)[\s\S]*?font-size:\s*var\(--app-font-size-sm\) !important;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-management :deep\(\.p-tag\)[\s\S]*?font-size:\s*var\(--app-badge-font-size\) !important;/
    )
    expect(reportManagementSource).toContain(':global(.report-management-dialog .p-dialog-title)')
    expect(reportManagementSource).toContain('font-size: var(--app-control-font-size) !important;')
    expect(reportManagementSource).toContain('font-size: var(--app-font-size-xs) !important;')
    expect(reportManagementSource).not.toMatch(/font-size:\s*(?:0\.\d+|1\.05|2)rem/)
  })

  it('keeps system report header actions inline until its section is narrow', () => {
    expect(reportManagementSource).toContain(
      'class="report-section__header report-section__header--system"'
    )
    expect(reportManagementSource).toContain('class="report-section__copy"')
    expect(reportManagementSource).toMatch(
      /\.report-section__header--system\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto;[^}]*align-items:\s*center;[^}]*width:\s*100%;[^}]*min-width:\s*0;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-section__header--system \.report-section__actions\s*\{[^}]*justify-self:\s*end;[^}]*width:\s*auto;[^}]*min-width:\s*max-content;[^}]*flex-wrap:\s*nowrap;/
    )
    expect(reportManagementSource).toMatch(
      /@container report-section \(max-width: 42rem\)\s*\{[\s\S]*?\.report-section__header--system\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);[^}]*align-items:\s*start;/
    )
    expect(reportManagementSource).toMatch(
      /@container report-section \(max-width: 42rem\)\s*\{[\s\S]*?\.report-section__header--system \.report-section__actions\s*\{[^}]*justify-self:\s*start;/
    )
    expect(reportManagementSource).toContain('@container report-section (max-width: 25rem)')
    expect(reportManagementSource).toContain('@click="refreshAll"')
    expect(reportManagementSource).toContain(
      'href="https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/issues"'
    )
  })

  it('scales source and finalized review messages through their PrimeVue text nodes', () => {
    expect(reportManagementSource.match(/class="report-review__message"/g)).toHaveLength(3)
    expect(reportManagementSource).toMatch(
      /:global\(\.report-management-dialog \.report-review__message \.p-message-text\)\s*\{[^}]*font-size:\s*var\(--app-font-size-sm\) !important;[^}]*line-height:\s*1\.4;/
    )
    expect(reportManagementSource).not.toMatch(
      /:global\(\.report-management-dialog \.report-review__message \.p-message-text\)\s*\{[^}]*font-size:\s*(?:\d+(?:\.\d+)?px|1rem)/
    )
    expect(reportManagementSource).not.toMatch(
      /:global\(\.report-management-dialog \.report-review__message \.p-message-text\)\s*\{[^}]*(?:^|[;{]\s*)(?:height|min-height):/
    )
  })

  it('uses responsive filter grids and dedicated full-width mobile summaries', () => {
    expect(reportManagementSource.match(/breakpoint="1399\.98px"/g)).toHaveLength(4)
    expect(reportManagementSource).toContain('@media (max-width: 1399.98px)')
    expect(reportManagementSource).toContain(
      "const REPORT_CARD_MEDIA_QUERY = '(max-width: 1399.98px)'"
    )
    expect(reportManagementSource).not.toContain('@media (max-width: 899px)')
    expect(reportManagementSource.match(/class="report-filter-search"/g)).toHaveLength(4)
    expect(
      reportManagementSource.match(/class="report-filter-select report-filter-select--primary"/g)
    ).toHaveLength(4)
    expect(
      reportManagementSource.match(/class="report-filter-select report-filter-select--secondary"/g)
    ).toHaveLength(3)
    expect(reportManagementSource.match(/class="report-filter-submit"/g)).toHaveLength(4)
    expect(reportManagementSource).toContain('container-name: report-section;')
    expect(reportManagementSource).toContain(
      "grid-template-areas: 'search primary secondary submit';"
    )
    expect(reportManagementSource).toContain('@container report-section (max-width: 62rem)')
    expect(reportManagementSource).toContain('@container report-section (max-width: 34rem)')
    expect(reportManagementSource).toContain('@container report-section (max-width: 20rem)')
    expect(reportManagementSource).toMatch(
      /\.report-filter-submit\.p-button\)[\s\S]*?justify-self:\s*end;[\s\S]*?width:\s*auto;/
    )
    expect(
      reportManagementSource.match(/class="report-mobile-card report-mobile-card-content"/g)
    ).toHaveLength(4)
    expect(
      reportManagementSource.match(/class="report-mobile-card__header report-mobile-card-header"/g)
    ).toHaveLength(4)
    expect(reportManagementSource).toContain('class="report-mobile-card-badges"')
    expect(
      reportManagementSource.match(
        /class="report-mobile-card__summary report-mobile-summary-preview"/g
      )
    ).toHaveLength(4)
    expect(reportManagementSource).toContain('class="report-mobile-summary-preview__label"')
    expect(reportManagementSource).toContain("data.description || $t('未提供詳細描述')")
    expect(reportManagementSource).toContain("data.comment_content_snapshot || $t('無留言摘要')")
    expect(reportManagementSource).toMatch(
      /\.report-mobile-summary-preview\s*\{[\s\S]*?width:\s*100%;[\s\S]*?min-width:\s*0;[\s\S]*?background:/
    )
    expect(reportManagementSource).toContain('max-height: calc(1.4em * 3)')
    expect(reportManagementSource).toMatch(
      /\.report-mobile-summary-preview__text\s*\{[\s\S]*?overflow-wrap:\s*anywhere;[\s\S]*?-webkit-line-clamp:\s*3;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card\s*\{[^}]*display:\s*grid;[^}]*grid-template-areas:[^}]*'header'[^}]*'body'[^}]*'footer';[^}]*grid-template-columns:\s*minmax\(0, 1fr\);[^}]*grid-template-rows:\s*auto auto auto;[^}]*align-content:\s*start;[^}]*justify-items:\s*stretch;[^}]*width:\s*100%;[^}]*min-height:\s*0;[^}]*height:\s*auto;[^}]*container-name:\s*report-card;[^}]*container-type:\s*inline-size;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card-content,[\s\S]*?\.report-mobile-card__header,[\s\S]*?\.report-mobile-card__body,[\s\S]*?\.report-mobile-card__footer\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*max-width:\s*none;[^}]*justify-self:\s*stretch;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card__body\s*\{[^}]*grid-area:\s*body;[^}]*grid-template-areas:[^}]*'summary'[^}]*'metadata';[^}]*grid-template-columns:\s*minmax\(0, 1fr\);[^}]*grid-template-rows:\s*auto auto;[^}]*align-content:\s*start;[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*min-height:\s*0;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card__summary,[\s\S]*?\.report-mobile-card__metadata\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;/
    )
    expect(reportManagementSource).toMatch(
      /@container report-card \(min-width: 42rem\)\s*\{[\s\S]*?grid-template-areas:\s*'summary metadata';[\s\S]*?grid-template-columns:\s*minmax\(15rem, 0\.72fr\) minmax\(0, 1\.28fr\);[\s\S]*?grid-template-rows:\s*auto;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-management__table \.p-datatable-tbody > tr > td\)\s*\{[^}]*display:\s*none !important;[^}]*min-height:\s*0;/
    )
    expect(reportManagementSource).toContain(
      ':deep(.report-management__comment-table .p-datatable-tbody > tr > td:nth-child(2)),'
    )
    expect(reportManagementSource).toContain(
      ':deep(.report-management__archive-table .p-datatable-tbody > tr > td:nth-child(2)) {'
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card__header\s*\{[^}]*grid-area:\s*header;[^}]*min-height:\s*0;[^}]*margin-top:\s*0;[^}]*align-self:\s*start;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card__footer\s*\{[^}]*grid-area:\s*footer;/
    )
    expect(reportManagementSource).not.toMatch(/grid-template-rows:\s*1fr/)
    expect(reportManagementSource).toMatch(
      /\.report-management__system-table \.p-datatable-tbody > tr > td:nth-child\(2\)[\s\S]*?width:\s*100% !important;[\s\S]*?max-width:\s*none !important;/
    )
    expect(reportManagementSource).toContain('@container report-card (max-width: 25rem)')
    expect(reportManagementSource).not.toMatch(
      /\.report-mobile-summary-preview\s*\{[^}]*max-width:/
    )
    expect(reportManagementSource).not.toContain('class="report-mobile-card-summary"')
    expect(reportManagementSource).toContain(
      'class="report-mobile-card__metadata report-mobile-info-grid report-mobile-info-grid--comment"'
    )
    expect(reportManagementSource).not.toContain('@container report-section (min-width: 56rem)')
    expect(reportManagementSource).toContain('@container report-section (max-width: 25rem)')
    expect(reportManagementSource).toContain("<dt>{{ $t('回報者') }}</dt>")
    expect(reportManagementSource).toContain("<dt>{{ $t('留言者') }}</dt>")
    expect(reportManagementSource).toContain("<dt>{{ $t('審核時間') }}</dt>")
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card__footer\s*\{[\s\S]*?border-top:\s*1px solid/
    )
    expect(reportManagementSource).toMatch(
      /\.report-row-actions\s*\{[\s\S]*?justify-content:\s*flex-end;/
    )
    expect(reportManagementSource).not.toContain('GitHub Issue</')
  })

  it('updates all report layouts when the shared media query changes', async () => {
    let changeListener
    const mediaQuery = {
      matches: false,
      addEventListener: vi.fn((event, listener) => {
        if (event === 'change') changeListener = listener
      }),
      removeEventListener: vi.fn(),
    }
    const wrapper = mountPanel({ renderRows: true, mediaQuery })
    await flushPromises()

    expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 1399.98px)')
    expect(wrapper.vm.isCardLayout).toBe(false)

    mediaQuery.matches = true
    changeListener?.({ matches: true })
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.isCardLayout).toBe(true)

    mediaQuery.matches = false
    changeListener?.({ matches: false })
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.isCardLayout).toBe(false)
  })

  it('renders each system and comment report field exactly once in card layout', async () => {
    mocks.listSystem.mockResolvedValueOnce({
      data: {
        total: 1,
        items: [
          {
            id: 101,
            reporter_name: '系統回報者甲',
            created_at: '2026-07-22T13:23:00Z',
            report_type: 'bug',
            title: '唯一系統問題標題',
            description: '唯一系統問題摘要',
            is_read: false,
          },
        ],
      },
    })
    mocks.listComments.mockResolvedValueOnce({
      data: {
        total: 1,
        items: [
          {
            id: 202,
            reporter_name: '留言回報者乙',
            created_at: '2026-07-20T05:36:00Z',
            reason: 'harassment_or_hostility',
            comment_content_snapshot: '唯一留言摘要',
            comment_author_name: '留言作者丙',
            course_name: '普通物理甲',
            archive_name: '期末考乙',
            status: 'pending',
            reviewer_name: null,
            reviewed_at: null,
          },
        ],
      },
    })

    const wrapper = mountPanel({ renderRows: true, cardLayout: true })
    await flushPromises()

    const systemRow = wrapper.get('.report-management__system-table .test-report-row')
    const systemCard = systemRow.get('.report-mobile-card')
    const systemHeader = systemCard.get('.report-mobile-card__header')
    const systemBody = systemCard.get('.report-mobile-card__body')
    const systemSummary = systemBody.get('.report-mobile-card__summary')
    const systemMetadata = systemBody.get('.report-mobile-card__metadata')
    const systemFooter = systemCard.get('.report-mobile-card__footer')
    expect(systemRow.findAll('.report-mobile-card')).toHaveLength(1)
    expect(systemRow.findAll('.report-mobile-card-title')).toHaveLength(1)
    expect(systemRow.findAll('.report-mobile-card-status')).toHaveLength(1)
    expect(systemRow.findAll('.report-mobile-summary-preview')).toHaveLength(1)
    expect(systemRow.findAll('.report-mobile-card__footer')).toHaveLength(1)
    expect(systemHeader.element.parentElement).toBe(systemCard.element)
    expect(systemBody.element.parentElement).toBe(systemCard.element)
    expect(systemSummary.element.parentElement).toBe(systemBody.element)
    expect(systemMetadata.element.parentElement).toBe(systemBody.element)
    expect(systemFooter.element.parentElement).toBe(systemCard.element)
    expect(Array.from(systemBody.element.children)).toEqual([
      systemSummary.element,
      systemMetadata.element,
    ])
    expect(systemRow.findAll('.report-person-time')).toHaveLength(0)
    expect(systemRow.text().match(/唯一系統問題標題/g)).toHaveLength(1)
    expect(systemRow.text().match(/未讀/g)).toHaveLength(1)
    expect(systemRow.text().match(/程式錯誤/g)).toHaveLength(1)
    expect(systemRow.text().match(/本地摘要/g)).toHaveLength(1)
    expect(systemRow.text().match(/系統回報者甲/g)).toHaveLength(1)
    expect(systemRow.findAll('dt').filter((item) => item.text() === '回報時間')).toHaveLength(1)
    expect(systemRow.findAll('button').map((item) => item.text())).toEqual(['檢視', '刪除'])

    const commentRow = wrapper.get('.report-management__comment-table .test-report-row')
    const commentCard = commentRow.get('.report-mobile-card')
    const commentHeader = commentCard.get('.report-mobile-card__header')
    const commentBody = commentCard.get('.report-mobile-card__body')
    const commentSummary = commentBody.get('.report-mobile-card__summary')
    const commentMetadata = commentBody.get('.report-mobile-card__metadata')
    const commentFooter = commentCard.get('.report-mobile-card__footer')
    expect(commentRow.findAll('.report-mobile-card')).toHaveLength(1)
    expect(commentRow.findAll('.report-mobile-card-title')).toHaveLength(1)
    expect(commentRow.findAll('.report-mobile-card-status')).toHaveLength(1)
    expect(commentRow.findAll('.report-mobile-summary-preview')).toHaveLength(1)
    expect(commentRow.findAll('.report-mobile-card__footer')).toHaveLength(1)
    expect(commentHeader.element.parentElement).toBe(commentCard.element)
    expect(commentBody.element.parentElement).toBe(commentCard.element)
    expect(commentSummary.element.parentElement).toBe(commentBody.element)
    expect(commentMetadata.element.parentElement).toBe(commentBody.element)
    expect(commentFooter.element.parentElement).toBe(commentCard.element)
    expect(Array.from(commentBody.element.children)).toEqual([
      commentSummary.element,
      commentMetadata.element,
    ])
    expect(commentRow.findAll('.report-person-time')).toHaveLength(0)
    expect(commentRow.findAll('.comment-report-content')).toHaveLength(0)
    expect(commentRow.findAll('.report-user-cell__text')).toHaveLength(0)
    expect(commentRow.text().match(/攻擊、騷擾或不友善內容/g)).toHaveLength(1)
    expect(commentRow.text().match(/待審核/g)).toHaveLength(1)
    expect(commentRow.text().match(/留言回報者乙/g)).toHaveLength(1)
    expect(commentRow.text().match(/留言作者丙/g)).toHaveLength(1)
    expect(commentRow.text().match(/普通物理甲/g)).toHaveLength(1)
    expect(commentRow.text().match(/期末考乙/g)).toHaveLength(1)
    expect(commentRow.findAll('dt').filter((item) => item.text() === '審核')).toHaveLength(1)
    expect(commentRow.findAll('button').map((item) => item.text())).toEqual(['檢視／審核', '刪除'])

    expect(reportManagementSource).toMatch(
      /\.report-mobile-card-header\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) max-content;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card-status\s*\{[\s\S]*?display:\s*inline-flex;[\s\S]*?flex:\s*0 0 auto;[\s\S]*?justify-self:\s*end;[\s\S]*?width:\s*auto;[\s\S]*?min-width:\s*max-content;[\s\S]*?max-width:\s*none;[\s\S]*?white-space:\s*nowrap;/
    )
    expect(reportManagementSource).toMatch(
      /\.report-mobile-card-status :deep\(\.p-tag-label\)\s*\{[\s\S]*?overflow:\s*visible;[\s\S]*?white-space:\s*nowrap;/
    )
    expect(reportManagementSource).not.toContain('max-width: 42%')
  })
})
