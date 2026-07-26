import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ArchiveReportPanel from '@/components/ArchiveReportPanel.vue'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  toast: vi.fn(),
  authenticated: true,
}))

vi.mock('@/api', () => ({
  reportService: {
    createArchiveReport: mocks.create,
  },
}))
vi.mock('@/utils/auth', () => ({
  isAuthenticated: () => mocks.authenticated,
}))
vi.mock('primevue/usetoast', () => ({
  useToast: () => ({ add: mocks.toast }),
}))

const slotStub = { template: '<div><slot /></div>' }

function mountPanel() {
  return mount(ArchiveReportPanel, {
    props: {
      courseId: 4,
      archiveId: 9,
      courseName: '電磁學',
      title: '期末考',
      academicYear: 2025,
      professorName: '陳老師',
    },
    global: {
      stubs: {
        Message: slotStub,
        Select: true,
        Textarea: true,
        Button: { template: '<button><slot /></button>' },
      },
    },
  })
}

describe('ArchiveReportPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.authenticated = true
    mocks.create.mockResolvedValue({ data: { id: 71, status: 'pending' } })
  })

  it('requires a reason and details for other, then submits a trimmed report once', async () => {
    const wrapper = mountPanel()
    expect(wrapper.vm.canSubmit).toBe(false)

    wrapper.vm.reason = 'other'
    wrapper.vm.customMessage = '   '
    expect(wrapper.vm.canSubmit).toBe(false)

    wrapper.vm.customMessage = '  題目頁面缺漏  '
    expect(wrapper.vm.canSubmit).toBe(true)
    await wrapper.vm.submitReport()
    await flushPromises()

    expect(mocks.create).toHaveBeenCalledWith(4, 9, {
      report_reason: 'other',
      custom_message: '題目頁面缺漏',
    })
    expect(wrapper.emitted('submitted')[0][0]).toMatchObject({ id: 71 })
    expect(wrapper.emitted('back')).toBeTruthy()
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'success', detail: '回報編號 #71，目前為待審核' })
    )
  })

  it('blocks unauthenticated submission and reports duplicate requests clearly', async () => {
    mocks.authenticated = false
    const unauthenticated = mountPanel()
    unauthenticated.vm.reason = 'file_unavailable'
    expect(unauthenticated.vm.canSubmit).toBe(false)
    await unauthenticated.vm.submitReport()
    expect(mocks.create).not.toHaveBeenCalled()
    unauthenticated.unmount()

    mocks.authenticated = true
    mocks.create.mockRejectedValue({ response: { status: 409 } })
    const duplicate = mountPanel()
    duplicate.vm.reason = 'file_unavailable'
    await duplicate.vm.submitReport()
    await flushPromises()
    expect(mocks.toast).toHaveBeenCalledWith(
      expect.objectContaining({ severity: 'warn', summary: '已有待審核回報' })
    )
  })
})
