import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import NotificationModal from '@/components/NotificationModal.vue'

const summary = {
  announcements: [
    { id: 1, title: '系統維護', body: '維護通知', updated_at: '2026-01-01T00:00:00Z' },
  ],
  personal_notifications: [
    { id: 2, title: '有人回覆', message: '回覆內容', created_at: '2026-01-02T00:00:00Z' },
  ],
  counts: { total: 2 },
}
const slotStub = { template: '<div><slot /><slot name="footer" /></div>' }

describe('NotificationModal', () => {
  it('renders separated unread summaries and clear actions', async () => {
    const wrapper = mount(NotificationModal, {
      props: { visible: true, summary },
      global: {
        stubs: {
          Dialog: slotStub,
          Button: {
            template: '<button @click="$emit(\'click\')"><slot />{{ $attrs.label }}</button>',
          },
          Badge: true,
        },
      },
    })
    expect(wrapper.text()).toContain('公告')
    expect(wrapper.text()).toContain('個人通知')
    expect(wrapper.text()).toContain('系統維護')
    expect(wrapper.text()).toContain('有人回覆')
    expect(wrapper.text()).toContain('2026/01/01 08:00')
    expect(wrapper.text()).toContain('2026/01/02 08:00')
    expect(wrapper.text()).not.toMatch(/上午|下午|凌晨|晚上|AM|PM|剛剛|分鐘前/)
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('view-announcement')[0]).toEqual([1])
  })

  it('adds dividers to complete summary item wrappers after the first message', () => {
    const announcements = [
      summary.announcements[0],
      { ...summary.announcements[0], id: 3, title: '第二則公告' },
      { ...summary.announcements[0], id: 4, title: '第三則公告' },
    ]
    const wrapper = mount(NotificationModal, {
      props: {
        visible: true,
        summary: { announcements, personal_notifications: [], counts: { total: 3 } },
      },
      global: {
        stubs: {
          Dialog: slotStub,
          Button: {
            template: '<button @click="$emit(\'click\')"><slot />{{ $attrs.label }}</button>',
          },
          Badge: true,
        },
      },
    })

    const items = wrapper.findAll('.summary-item')
    const dividedItems = wrapper.findAll('.summary-item--divided')
    expect(items).toHaveLength(3)
    expect(dividedItems).toHaveLength(2)
    expect(items[0].classes()).not.toContain('summary-item--divided')
    expect(items[1].classes()).toContain('summary-item--divided')
    expect(items[2].classes()).toContain('summary-item--divided')
    for (const item of dividedItems) {
      expect(item.find('.summary-item__body').exists()).toBe(true)
      expect(item.get('button').text()).toBe('檢視')
    }
    expect(wrapper.get('.summary-actions').findAll('button')).toHaveLength(3)
  })

  it('does not render a divider for a single summary message', () => {
    const wrapper = mount(NotificationModal, {
      props: {
        visible: true,
        summary: {
          announcements: [],
          personal_notifications: summary.personal_notifications,
          counts: { total: 1 },
        },
      },
      global: {
        stubs: {
          Dialog: slotStub,
          Button: true,
          Badge: true,
        },
      },
    })

    expect(wrapper.findAll('.summary-item')).toHaveLength(1)
    expect(wrapper.find('.summary-item--divided').exists()).toBe(false)
  })
})
