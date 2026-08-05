import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ArchiveReportPanel from '@/components/ArchiveReportPanel.vue'
import archiveReportPanelSource from '@/components/ArchiveReportPanel.vue?raw'

const mocks = vi.hoisted(() => ({
  pending: vi.fn(),
  create: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/api', () => ({
  reportService: {
    getPendingArchiveReport: mocks.pending,
    createArchiveReport: mocks.create,
  },
}))
vi.mock('@/utils/auth', () => ({ getCurrentUser: () => ({ id: 7 }) }))
vi.mock('primevue/usetoast', () => ({
  useToast: () => ({ add: mocks.toast }),
}))

const SelectStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template:
    '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\')"><option value=""></option><option value="other">其他問題</option><option value="duplicate_archive">重複</option></select>',
}
const TextareaStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'blur'],
  template:
    '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @blur="$emit(\'blur\')" />',
}

function mountPanel() {
  return mount(ArchiveReportPanel, {
    props: {
      courseId: 1,
      archiveId: 2,
      courseName: '量子力學',
      archiveName: '期末考',
    },
    global: {
      stubs: {
        Button: {
          inheritAttrs: false,
          props: ['label', 'type', 'disabled'],
          template:
            '<button :type="type || \'button\'" :disabled="disabled" v-bind="$attrs">{{ label }}</button>',
        },
        Select: SelectStub,
        Textarea: TextareaStub,
        Message: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('ArchiveReportPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.pending.mockRejectedValue({ response: { status: 404 } })
  })

  it('validates other reason and preserves input after API failure', async () => {
    mocks.create.mockRejectedValueOnce(new Error('network'))
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('select').setValue('other')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('必須填寫補充說明')
    expect(mocks.create).not.toHaveBeenCalled()

    await wrapper.find('textarea').setValue('  檔案有個資  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(mocks.create).toHaveBeenCalledWith(1, 2, {
      report_reason: 'other',
      supplementary_detail: '檔案有個資',
    })
    expect(wrapper.find('textarea').element.value).toBe('  檔案有個資  ')
    expect(wrapper.text()).toContain('目前輸入已保留')
  })

  it('submits once and emits success without closing the preview', async () => {
    mocks.create.mockResolvedValueOnce({
      data: { id: 9, status: 'pending' },
    })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('select').setValue('duplicate_archive')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(mocks.create).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('submitted')?.[0]?.[0]).toEqual({
      id: 9,
      status: 'pending',
    })
    expect(mocks.toast).toHaveBeenCalled()
    expect(wrapper.emitted('back')).toBeUndefined()
  })

  it('shows a duplicate pending message and disables submission', async () => {
    mocks.pending.mockResolvedValueOnce({ data: { id: 8, status: 'pending' } })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('已有待審核回報')
    await wrapper.find('form').trigger('submit')
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('uses the discussion panel visual hierarchy and theme-aware tokens', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.get('.archive-report-panel__header').text()).toContain('回報考古題')
    expect(wrapper.get('.archive-report-panel__header').text()).toContain('量子力學 · 期末考')
    expect(wrapper.get('.archive-report-panel__content').find('form').exists()).toBe(true)
    expect(archiveReportPanelSource).toContain('border: 1px solid var(--border-color)')
    expect(archiveReportPanelSource).toContain('background: var(--bg-primary)')
    expect(archiveReportPanelSource).toContain('border-bottom: 1px solid var(--border-color)')
    expect(archiveReportPanelSource).toContain('font-size: var(--app-font-size-lg)')
    expect(archiveReportPanelSource).toContain('font-size: var(--app-control-font-size)')
    expect(archiveReportPanelSource).not.toMatch(/safari|webkit|chrome/i)
  })
})
