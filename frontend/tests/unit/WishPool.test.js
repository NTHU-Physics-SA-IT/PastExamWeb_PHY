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

  it('centers the naturally sized cloud in a responsive breathing-space stage', () => {
    expect(wishPoolSource).toContain('class="wish-cloud-stage"')
    expect(wishPoolSource).toMatch(
      /\.wish-cloud-stage\s*\{[^}]*display:\s*flex;[^}]*min-height:\s*clamp\([^)]*\);[^}]*align-items:\s*center;[^}]*justify-content:\s*center;/
    )
    expect(wishPoolSource).toMatch(
      /@container \(max-width:\s*720px\)[\s\S]*?\.wish-cloud-stage\s*\{[^}]*min-height:\s*clamp\(/
    )
    expect(wishPoolSource).toContain('densityFontBoost')
    expect(wishPoolSource).toContain('Math.min(2.5')
  })

  it('keeps each title and heart together and fits oversized tokens before packing', () => {
    expect(wishPoolSource).toContain('class="wish-word__title"')
    expect(wishPoolSource).toMatch(
      /\.wish-word\s*\{[^}]*display:\s*inline-flex;[^}]*width:\s*max-content;[^}]*align-items:\s*baseline;[^}]*white-space:\s*nowrap;/
    )
    expect(wishPoolSource).toMatch(
      /\.wish-word small,[\s\S]*?\.fulfilled-label\s*\{[^}]*flex:\s*0 0 auto;/
    )
    expect(wishPoolSource).toContain('element.offsetWidth <= maxTokenWidth')
    expect(wishPoolSource).toContain('(maxTokenWidth / element.offsetWidth) * 0.98')
    expect(wishPoolSource).toContain("font-family: 'Huninn', 'Noto Sans TC', system-ui, sans-serif")
    expect(wishPoolSource).not.toMatch(/\.wish-cloud(?:-stage)?\s*\{[^}]*font-family:/)
  })

  it('reuses discussion icon actions in the Wish detail header', () => {
    expect(wishPoolSource).toContain(
      'class="discussion-action-button discussion-action-like-button"'
    )
    expect(wishPoolSource).toContain('class="discussion-action-button"')
    expect(wishPoolSource).toContain(':class="{ \'is-active\': selected.hearted_by_me }"')
    expect(wishPoolSource).toContain(':aria-pressed="selected.hearted_by_me"')
    expect(wishPoolSource).toContain('@click="toggleHeart"')
    expect(wishPoolSource).toContain('@click="toggleReport"')
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

  it('presents Any Semester and paginates the server-filtered pool', async () => {
    const anySemesterWish = { ...sampleWish, id: 8, title: '不限學期願望', academic_year: null }
    wishServiceMock.list
      .mockReset()
      .mockResolvedValueOnce({ data: { items: [sampleWish], total: 2 } })
      .mockResolvedValueOnce({ data: { items: [anySemesterWish], total: 2 } })

    const wrapper = await mountPool()
    expect(wrapper.vm.semesterLabel(sampleWish)).toBe('114上學期')
    expect(wrapper.vm.semesterLabel(anySemesterWish)).toBe('不限學期')

    await wrapper.vm.loadMore()
    expect(wishServiceMock.list).toHaveBeenNthCalledWith(2, { limit: 60, offset: 1 })
    expect(wrapper.vm.wishes.map((wish) => wish.id)).toEqual([7, 8])
  })
})
