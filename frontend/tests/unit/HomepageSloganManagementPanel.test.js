import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import HomepageSloganManagementPanel from '@/components/admin/HomepageSloganManagementPanel.vue'
import source from '@/components/admin/HomepageSloganManagementPanel.vue?raw'
import { messages } from '@/i18n/messages'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  confirm: vi.fn(),
  toast: vi.fn(),
}))

vi.mock('@/api', () => ({
  homepageSloganService: {
    listAdmin: mocks.list,
    updateAdmin: mocks.update,
    removeAdmin: mocks.remove,
  },
}))
vi.mock('primevue/useconfirm', () => ({ useConfirm: () => ({ require: mocks.confirm }) }))
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: mocks.toast }) }))

const item = {
  id: 1,
  content: '量子不確定，考古很確定',
  submitter_name: 'Alice',
  created_at: '2026-08-26T01:00:00Z',
  reviewer_name: null,
  reviewed_at: null,
  status: 'pending',
  occurrence_level: 'normal',
}

describe('HomepageSloganManagementPanel', () => {
  beforeEach(() => {
    mocks.list.mockReset().mockResolvedValue({
      data: {
        items: [item],
        total: 1,
        status_counts: { pending: 1, enabled: 0, disabled: 0 },
      },
    })
    mocks.update.mockReset().mockResolvedValue({ data: { ...item, status: 'enabled' } })
    mocks.remove.mockReset().mockResolvedValue({ data: null })
    mocks.confirm.mockReset()
    mocks.toast.mockReset()
  })

  it('owns the responsive table/card metadata, overview, review dialog, and permanent delete copy', () => {
    for (const label of ['投稿', '投稿內容', '審核', '審核狀態', '出現等級', '操作']) {
      expect(source).toContain(`$t('${label}')`)
    }
    expect(source).not.toContain('class="slogan-mobile-card"')
    for (const className of [
      'report-mobile-card report-mobile-card-content admin-responsive-card-surface',
      'report-mobile-card__header report-mobile-card-header',
      'report-mobile-card-title',
      'report-mobile-card-status',
      'report-mobile-card-status-group',
      'report-mobile-card__body',
      'report-mobile-card__metadata report-mobile-info-grid',
      'report-mobile-info-item',
      'report-mobile-card__footer',
    ]) {
      expect(source).toContain(className)
    }
    expect(source).toContain('class="slogan-filters report-management__filters"')
    expect(source).toContain('@media (max-width: 1399.98px)')
    expect(source.match(/class="report-row-actions"/g)).toHaveLength(2)
    expect(source.match(/\$t\('首頁 slogan 永久刪除按鈕'\)/g)).toHaveLength(2)
    expect(
      source.match(
        /:label="\$t\('查看\/審核'\)"[\s\S]{0,220}?icon="pi pi-search"[\s\S]{0,220}?outlined/g
      )
    ).toHaveLength(2)
    expect(source).toContain('class="slogan-overview__list"')
    expect(source).toContain('class="slogan-overview__grid slogan-overview__header"')
    expect(source).toContain('class="slogan-overview__grid slogan-overview__row"')
    expect(source).toContain('class="slogan-overview__mobile-label"')
    expect(source).toContain(
      'grid-template-columns: minmax(0, 1fr) minmax(7rem, 10rem) minmax(6rem, 8rem)'
    )
    expect(source).toContain("{ label: t('超級少'), value: 'super_rare' }")
    expect(source).toContain("{ label: t('超級常'), value: 'super_frequent' }")
    expect(source).toContain("$t('查看/審核首頁 slogan')")
    expect(source).toContain('無法復原，也不會進入垃圾桶')
    expect(source).toContain("acceptLabel: t('永久刪除')")
    expect(messages.en['審核狀態']).toBe('Status')
    expect(messages.en['出現等級']).toBe('Occurrence')
    expect(messages['zh-TW']['審核狀態']).toBe('審核狀態')
    expect(messages['zh-TW']['出現等級']).toBe('出現等級')
  })

  it('maps both filter actions and row actions to the approved Christmas button roles', () => {
    expect(source.match(/slogan-refresh-action/g)).toHaveLength(2)
    expect(source.match(/slogan-preview-action/g)).toHaveLength(2)
    expect(source.match(/slogan-admin-delete-action/g)).toHaveLength(2)
  })

  it('maps the review dialog save action to the archive download treatment', () => {
    expect(source).toMatch(
      /class="slogan-dialog-save-action review-action-republish"[\s\S]{0,220}?severity="success"[\s\S]{0,160}?size="small"/
    )
  })

  it('keeps the desktop table fluid while retaining the existing responsive card surface', async () => {
    const wrapper = shallowMount(HomepageSloganManagementPanel)
    await flushPromises()

    const table = wrapper.findComponent({ name: 'DataTable' })
    expect(table.exists()).toBe(true)
    expect(table.attributes('tablestyle')).toBe('width: 100%; table-layout: fixed')
    expect(table.attributes('tablestyle')).not.toContain('min-width')
    expect(wrapper.find('.slogan-mobile-list').exists()).toBe(true)
    expect(wrapper.find('.admin-responsive-card-surface').exists()).toBe(true)
  })

  it('uses the shared report-review anatomy with one top-right status and boxed slogan content', async () => {
    const wrapper = shallowMount(HomepageSloganManagementPanel, {
      global: {
        stubs: {
          Dialog: { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()
    wrapper.vm.openReview(item)
    await wrapper.vm.$nextTick()

    const review = wrapper.get('.report-review')
    const title = review.get('.report-review__title')
    expect(title.findComponent({ name: 'Tag' }).exists()).toBe(true)
    expect(review.findAllComponents({ name: 'Tag' })).toHaveLength(1)
    expect(review.findAll('.report-review__meta dt').map((label) => label.text())).toEqual([
      '投稿人',
      '投稿時間',
      '審核人',
      '審核時間',
    ])
    expect(review.text()).not.toContain('目前狀態')
    expect(review.get('.report-review__content-label').text()).toBe('slogan 內容')
    expect(review.get('.report-review__content-block').text()).toBe(item.content)
    expect(review.findAll('.report-review__field')).toHaveLength(2)
    expect(
      review
        .get('.report-review__actions')
        .findAllComponents({ name: 'Button' })
        .map((button) => button.attributes('label'))
    ).toEqual(['取消', '儲存'])
  })

  it('defaults and resets to status-first sorting while preserving manual sorting', async () => {
    const wrapper = shallowMount(HomepageSloganManagementPanel)
    await flushPromises()
    expect(mocks.list).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 10, offset: 0, sort_by: 'status', sort_order: 'asc' })
    )

    mocks.list.mockClear()
    await wrapper.vm.onSort({ sortField: 'content', sortOrder: -1 })
    await flushPromises()
    expect(mocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'content', sort_order: 'desc' })
    )

    mocks.list.mockClear()
    await wrapper.vm.onSort({})
    await flushPromises()
    expect(wrapper.vm.page).toMatchObject({ first: 0, sortField: 'status', sortOrder: 1 })
    expect(mocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'status', sort_order: 'asc' })
    )

    Object.assign(wrapper.vm.page, { first: 10, rows: 10, sortField: 'content', sortOrder: -1 })
    mocks.list.mockClear()
    await wrapper.vm.refreshAll()
    expect(wrapper.vm.page).toMatchObject({ first: 0, sortField: 'status', sortOrder: 1 })
    expect(mocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'status', sort_order: 'asc' })
    )
  })

  it('loads lazily and saves a reviewed state with a canonical occurrence level', async () => {
    const wrapper = shallowMount(HomepageSloganManagementPanel)
    await flushPromises()
    wrapper.vm.openReview(item)
    expect(wrapper.vm.reviewForm).toEqual({ status: 'disabled', occurrence_level: 'normal' })
    wrapper.vm.reviewForm.status = 'enabled'
    wrapper.vm.reviewForm.occurrence_level = 'frequent'
    await wrapper.vm.saveReview()
    expect(mocks.update).toHaveBeenCalledWith(1, {
      status: 'enabled',
      occurrence_level: 'frequent',
    })
  })
})
