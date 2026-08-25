import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import HomepageSloganManagementPanel from '@/components/admin/HomepageSloganManagementPanel.vue'
import source from '@/components/admin/HomepageSloganManagementPanel.vue?raw'

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
  })

  it('loads lazily and saves a reviewed state with a canonical occurrence level', async () => {
    const wrapper = shallowMount(HomepageSloganManagementPanel)
    await flushPromises()
    expect(mocks.list).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 10, offset: 0, sort_by: 'created_at' })
    )
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
