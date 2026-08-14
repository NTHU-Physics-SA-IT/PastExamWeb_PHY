import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import NotificationCenterModal from '@/components/NotificationCenterModal.vue'

const slotStub = { template: '<div><slot /><slot name="header" /></div>' }
const tabsStub = { template: '<div><slot /></div>' }
const buttonStub = {
  inheritAttrs: false,
  props: ['label'],
  template: '<button v-bind="$attrs">{{ label }}</button>',
}
const announcements = [
  {
    id: 1,
    title: '公告一',
    body: '內容',
    severity: 'info',
    is_read: false,
    updated_at: '2026-01-01T00:00:00Z',
  },
]
const personal = [
  {
    id: 2,
    title: '回覆通知',
    message: '內容',
    read_at: null,
    source_available: true,
    created_at: '2026-01-02T00:00:00Z',
  },
]

describe('NotificationCenterModal', () => {
  it('uses the report warning severity for unread tags and keeps read tags secondary', () => {
    const wrapper = mount(NotificationCenterModal, {
      props: {
        visible: true,
        announcements: [
          announcements[0],
          { ...announcements[0], id: 3, title: '已讀公告', is_read: true },
        ],
        personalNotifications: [
          personal[0],
          { ...personal[0], id: 4, title: '已讀通知', read_at: '2026-01-03T00:00:00Z' },
        ],
      },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })

    const assertionGroups = [
      ['.notification-announcement-groups', '公告一', '已讀公告'],
      ['.notification-personal-groups', '回覆通知', '已讀通知'],
    ]
    for (const [selector, unreadTitle, readTitle] of assertionGroups) {
      const cards = wrapper.find(selector).findAll('.notification-card')
      const unreadCard = cards.find((card) => card.text().includes(unreadTitle))
      const readCard = cards.find((card) => card.text().includes(readTitle))

      expect(unreadCard.get('tag-stub').attributes('severity')).toBe('warn')
      expect(readCard.get('tag-stub').attributes('severity')).toBe('secondary')
    }
  })

  it('separates announcements and personal notifications and marks detail read', async () => {
    const wrapper = mount(NotificationCenterModal, {
      props: {
        visible: true,
        announcements,
        personalNotifications: personal,
        counts: { total: 2, personal_notifications: 1 },
      },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })
    expect(wrapper.text()).toContain('公告與通知')
    expect(wrapper.text()).toContain('公告')
    expect(wrapper.text()).toContain('個人通知')
    expect(wrapper.findComponent({ name: 'DataTable' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'Paginator' }).exists()).toBe(false)
    expect(wrapper.get('.notification-announcement-groups .notification-card').text()).toContain(
      '公告一'
    )
    expect(wrapper.get('.notification-announcement-groups .notification-card').text()).toContain(
      '最近更新'
    )
    expect(wrapper.get('.notification-announcement-groups .notification-card').text()).toContain(
      '2026/01/01 08:00'
    )
    expect(wrapper.get('.notification-personal-groups .notification-card').text()).toContain(
      '回覆通知'
    )
    expect(wrapper.get('.notification-personal-groups .notification-card').text()).toContain(
      '2026/01/02 08:00'
    )
    expect(wrapper.text()).not.toMatch(/上午|下午|凌晨|晚上|AM|PM|剛剛|分鐘前/)
    const viewButtons = wrapper.findAll('.notification-view-button')
    expect(viewButtons).toHaveLength(2)
    expect(viewButtons.every((button) => button.text() === '檢視')).toBe(true)
    expect(wrapper.findAll('.notification-delete-button')).toHaveLength(1)
    expect(wrapper.get('.notification-delete-button').attributes('aria-label')).toBe('刪除通知')
    expect(
      wrapper.find('.notification-announcement-groups .notification-delete-button').exists()
    ).toBe(false)
    await wrapper.get('.notification-delete-button').trigger('click')
    expect(wrapper.emitted('delete-personal')).toEqual([[personal[0]]])
    await wrapper.get('.personal-delete-all-button').trigger('click')
    expect(wrapper.emitted('delete-all-personal')).toHaveLength(1)
    wrapper.vm.openAnnouncement(announcements[0])
    expect(wrapper.emitted('mark-announcement-read')).toEqual([[1]])
    wrapper.vm.openPersonal(personal[0])
    expect(wrapper.emitted('mark-personal-read')).toEqual([[2]])
  })

  it('emits safe internal navigation for an available discussion source', () => {
    const item = {
      ...personal[0],
      source_type: 'archive_discussion_thread',
      source_id: 3,
      source_message_id: 4,
      metadata: { course_id: 1, archive_id: 2 },
    }
    const wrapper = mount(NotificationCenterModal, {
      props: { visible: true, personalNotifications: [item] },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
        },
      },
    })
    wrapper.vm.openPersonal(item)
    expect(wrapper.emitted('open-personal-source')).toEqual([[item]])
  })

  it('keeps unavailable notification detail readable with neutral wording', async () => {
    const item = {
      ...personal[0],
      source_available: false,
    }
    const wrapper = mount(NotificationCenterModal, {
      props: { visible: true, personalNotifications: [item] },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })

    wrapper.vm.openPersonal(item)
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('來源目前無法開啟')
    expect(wrapper.text()).toContain('來源目前無法開啟，但通知內容仍可查看。')
    expect(wrapper.text()).not.toContain('來源已不存在')
    expect(wrapper.emitted('open-personal-source')).toBeUndefined()
    expect(wrapper.emitted('mark-personal-read')).toEqual([[item.id]])
  })

  it('opens readable detail for a recognized source with malformed route metadata', async () => {
    const item = {
      ...personal[0],
      source_type: 'archive_report',
      metadata: { course_id: 1 },
    }
    const wrapper = mount(NotificationCenterModal, {
      props: { visible: true, personalNotifications: [item] },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })

    wrapper.vm.openPersonal(item)
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain(item.message)
    expect(wrapper.text()).toContain('來源目前無法開啟')
    expect(wrapper.emitted('open-personal-source')).toBeUndefined()
  })

  it('uses a visible icon for republished archive submission notifications', () => {
    const wrapper = mount(NotificationCenterModal, {
      props: { visible: true },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
        },
      },
    })

    expect(wrapper.vm.notificationIcon('archive_submission_republished')).toContain('pi-eye')
  })

  it('groups each card list by month and sorts groups and items newest first', () => {
    const wrapper = mount(NotificationCenterModal, {
      props: {
        visible: true,
        announcements: [
          { ...announcements[0], id: 1, title: '七月較早', updated_at: '2026-07-02T00:00:00Z' },
          { ...announcements[0], id: 2, title: '六月公告', updated_at: '2026-06-30T00:00:00Z' },
          { ...announcements[0], id: 3, title: '七月較新', updated_at: '2026-07-20T00:00:00Z' },
        ],
        personalNotifications: [
          { ...personal[0], id: 4, title: '五月通知', created_at: '2026-05-01T00:00:00Z' },
          { ...personal[0], id: 5, title: '七月通知', created_at: '2026-07-01T00:00:00Z' },
          { ...personal[0], id: 6, title: '日期未明通知', created_at: 'invalid-date' },
        ],
      },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })

    const announcementGroups = wrapper.findAll(
      '.notification-announcement-groups .notification-month-group'
    )
    expect(announcementGroups).toHaveLength(2)
    expect(announcementGroups[0].get('.notification-month-heading').text()).toBe('2026年7月')
    expect(announcementGroups[1].get('.notification-month-heading').text()).toBe('2026年6月')
    expect(
      announcementGroups[0].findAll('.notification-card__title').map((title) => title.text())
    ).toEqual(['七月較新', '七月較早'])

    const personalGroups = wrapper.findAll(
      '.notification-personal-groups .notification-month-group'
    )
    expect(personalGroups.map((group) => group.get('.notification-month-heading').text())).toEqual([
      '2026年7月',
      '2026年5月',
      '日期未明',
    ])
    expect(wrapper.text()).not.toContain('2026年4月')
  })

  it('adds a full-card divider from the second message in each month', () => {
    const wrapper = mount(NotificationCenterModal, {
      props: {
        visible: true,
        announcements: [
          { ...announcements[0], id: 1, updated_at: '2026-07-20T00:00:00Z' },
          { ...announcements[0], id: 2, updated_at: '2026-07-10T00:00:00Z' },
          { ...announcements[0], id: 5, updated_at: '2026-06-20T00:00:00Z' },
        ],
        personalNotifications: [
          { ...personal[0], id: 3, created_at: '2026-07-20T00:00:00Z' },
          { ...personal[0], id: 4, created_at: '2026-07-10T00:00:00Z' },
          { ...personal[0], id: 6, created_at: '2026-06-20T00:00:00Z' },
        ],
      },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })

    for (const selector of ['.notification-announcement-groups', '.notification-personal-groups']) {
      const groups = wrapper.find(selector).findAll('.notification-month-group')
      const julyCards = groups[0].findAll('.notification-card')
      const juneCards = groups[1].findAll('.notification-card')

      expect(julyCards).toHaveLength(2)
      expect(julyCards[0].classes()).not.toContain('notification-card--divided')
      expect(julyCards[1].classes()).toContain('notification-card--divided')
      expect(julyCards[1].find('.notification-card__footer').exists()).toBe(true)
      expect(julyCards[1].find('.notification-view-button').exists()).toBe(true)
      expect(juneCards).toHaveLength(1)
      expect(juneCards[0].classes()).not.toContain('notification-card--divided')
    }

    expect(
      wrapper
        .get('.notification-personal-groups .notification-card--divided')
        .find('.notification-card__actions')
        .exists()
    ).toBe(true)
  })

  it('shows empty states without rendering month groups', () => {
    const wrapper = mount(NotificationCenterModal, {
      props: { visible: true, announcements: [], personalNotifications: [] },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Badge: true,
        },
      },
    })

    expect(wrapper.text()).toContain('目前沒有公告')
    expect(wrapper.text()).toContain('目前沒有個人通知')
    expect(wrapper.find('.notification-month-group').exists()).toBe(false)
    expect(wrapper.find('.notification-card').exists()).toBe(false)
  })

  it('removes an empty month group when the last notification is deleted', async () => {
    const wrapper = mount(NotificationCenterModal, {
      props: { visible: true, personalNotifications: personal },
      global: {
        stubs: {
          Dialog: slotStub,
          Tabs: tabsStub,
          TabList: tabsStub,
          Tab: tabsStub,
          TabPanels: tabsStub,
          TabPanel: tabsStub,
          Button: buttonStub,
          Tag: true,
          Badge: true,
        },
      },
    })

    expect(wrapper.find('.notification-personal-groups .notification-month-group').exists()).toBe(
      true
    )
    await wrapper.setProps({ personalNotifications: [] })
    expect(wrapper.find('.notification-personal-groups').exists()).toBe(false)
    expect(wrapper.text()).toContain('目前沒有個人通知')
  })
})
