import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import wishPoolSource from '@/components/WishPool.vue?raw'

const wishServiceMock = vi.hoisted(() => ({
  list: vi.fn(),
  report: vi.fn(),
  remove: vi.fn(),
  toggleHeart: vi.fn(),
}))
const confirmRequireMock = vi.hoisted(() => vi.fn())
const toastAddMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({ wishService: wishServiceMock }))
vi.mock('@/utils/auth', () => ({ getCurrentUser: () => ({ id: 1, is_admin: true }) }))
vi.mock('primevue/useconfirm', () => ({ useConfirm: () => ({ require: confirmRequireMock }) }))
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toastAddMock }) }))

const sampleWish = {
  id: 7,
  title: '量子資訊期末考',
  subject: '量子資訊',
  professor: 'Prof. Lin',
  academic_year: 1141,
  name: 'final',
  creator_name: 'Alice',
  created_at: '2026-08-18T00:00:00Z',
  heart_count: 0,
  hearted_by_me: false,
  fulfilled: false,
}

const stubs = {
  Button: { template: '<button><slot /></button>' },
  Dialog: { template: '<div><slot /></div>' },
  InputNumber: { template: '<input />' },
  InputText: { template: '<input />' },
  Message: { template: '<div><slot /></div>' },
  ProgressSpinner: { template: '<div />' },
  Select: { template: '<select />' },
  Tag: { template: '<span><slot /></span>' },
  Textarea: { template: '<textarea />' },
  InlineCommentReport: {
    props: ['targetType', 'message', 'loading'],
    template: '<div data-test="shared-report">{{ targetType }}:{{ message.content }}</div>',
  },
}

describe('Wish Pool focused interactions', () => {
  beforeEach(() => {
    confirmRequireMock.mockReset()
    toastAddMock.mockReset()
    wishServiceMock.list.mockReset().mockResolvedValue({ data: { items: [sampleWish], total: 1 } })
    wishServiceMock.report.mockReset().mockResolvedValue({ data: {} })
    wishServiceMock.remove.mockReset().mockResolvedValue({ data: {} })
  })

  it('reflows the header before the add-wish button reaches the cramped middle state', () => {
    expect(wishPoolSource).toMatch(/container-type:\s*inline-size/)
    expect(wishPoolSource).toMatch(/@container \(max-width:\s*720px\)/)
    expect(wishPoolSource).toMatch(
      /@container \(max-width:\s*720px\)[\s\S]*?\.wish-header\s*\{[^}]*align-items:\s*stretch;[^}]*flex-direction:\s*column;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-header :deep\(\.p-button\)\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap[;}]/
    )
  })

  it('uses the existing fulfilled state for a theme-safe success treatment', () => {
    expect(wishPoolSource).toContain(':class="{ fulfilled: wish.fulfilled }"')
    expect(wishPoolSource).toContain('v-if="wish.fulfilled" class="fulfilled-label"')
    expect(wishPoolSource).toMatch(
      /\.wish-word\.fulfilled\s*\{[^}]*color:\s*var\(--green-600\);[^}]*font-weight:\s*600/
    )
    expect(wishPoolSource).not.toMatch(
      /\.wish-word\.fulfilled\s*\{[^}]*(?:background|box-shadow|border):/
    )
    expect(wishPoolSource).toMatch(/\.fulfilled-label\s*\{[^}]*font-weight:\s*700/)
  })

  async function mountPool() {
    const WishPool = (await import('@/components/WishPool.vue')).default
    const wrapper = mount(WishPool, {
      props: { coursesList: {}, courseCategories: [] },
      global: { stubs, mocks: { $t: (key) => key } },
    })
    await flushPromises()
    wrapper.vm.selected = sampleWish
    await flushPromises()
    return wrapper
  }

  it('uses the shared report form and canonical confirmation service', async () => {
    const wrapper = await mountPool()

    wrapper.vm.toggleReport()
    await flushPromises()
    expect(wrapper.get('[data-test="shared-report"]').text()).toContain('wish:量子資訊期末考')

    await wrapper.vm.submitReport({ report_reason: 'misinformation', custom_message: null })
    expect(wishServiceMock.report).toHaveBeenCalledWith(7, {
      report_reason: 'misinformation',
      custom_message: null,
    })
    expect(toastAddMock).toHaveBeenCalledWith(expect.objectContaining({ severity: 'success' }))

    wrapper.vm.requestRemoveWish()
    expect(confirmRequireMock).toHaveBeenCalledWith(
      expect.objectContaining({
        header: '永久刪除這筆許願？',
        acceptClass: 'p-button-danger',
        defaultFocus: 'reject',
      })
    )
    expect(wishServiceMock.remove).not.toHaveBeenCalled()

    await confirmRequireMock.mock.calls[0][0].accept()
    expect(wishServiceMock.remove).toHaveBeenCalledWith(7)
    expect(wrapper.vm.selected).toBeNull()
  })
})
