import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DiscussionMessageCard from '@/components/DiscussionMessageCard.vue'

const ButtonStub = {
  inheritAttrs: false,
  props: ['label'],
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')">{{ label }}</button>',
}

describe('DiscussionMessageCard', () => {
  it('keeps time below wrapping author metadata and exposes ordered accessible actions', () => {
    const wrapper = mount(DiscussionMessageCard, {
      props: {
        message: {
          id: 1,
          user_name: '這是一個非常長的留言者名稱',
          author_show_level_title: true,
          author_experience: 54,
          content: '留言內容',
          is_pinned: true,
          liked_by_current_user: true,
          like_count: 1234,
          created_at: '2026-07-20T08:00:00Z',
        },
        canPin: true,
        canDelete: true,
      },
      global: {
        stubs: {
          Button: ButtonStub,
          Tag: { template: '<span><slot /></span>' },
        },
      },
    })

    const authorBlock = wrapper.get('.discussion-card__author-block')
    expect(authorBlock.find('.discussion-card__author-line').exists()).toBe(true)
    expect(authorBlock.find('time.discussion-card__time').exists()).toBe(true)
    expect(authorBlock.element.parentElement).toBe(wrapper.get('.discussion-card').element)
    expect(wrapper.get('.discussion-card__action-stack').element.parentElement).toBe(
      wrapper.get('.discussion-card').element
    )
    expect(
      wrapper.get('.discussion-card__action-stack').findAll('.discussion-card__actions')
    ).toHaveLength(2)
    expect(wrapper.find('.discussion-card__footer').exists()).toBe(false)
    expect(wrapper.get('.discussion-card__like-button').text()).toContain('1234')

    const labels = wrapper.findAll('button').map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['回覆留言', '取消愛心', '回報留言', '取消置頂', '刪除留言'])
  })

  it('renders the inline report inside the exact reply card without reserving a pin gap', () => {
    const message = {
      id: 8,
      user_name: '回覆留言者',
      content: '這一則回覆是回報標的',
      like_count: 999,
      created_at: '2026-07-20T08:00:00Z',
      parent_id: 1,
    }
    const wrapper = mount(DiscussionMessageCard, {
      props: {
        message,
        isReply: true,
        reportOpen: true,
        reportReason: 'other',
      },
      global: {
        stubs: {
          Button: ButtonStub,
          InlineCommentReport: {
            props: ['message', 'reason'],
            template:
              '<div class="inline-report-stub">{{ message.id }}-{{ message.content }}-{{ reason }}</div>',
          },
        },
      },
    })

    expect(wrapper.get('.discussion-card__inline-panel').text()).toContain(
      '8-這一則回覆是回報標的-other'
    )
    const labels = wrapper.findAll('button').map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['回覆留言', '按愛心', '回報留言'])
    expect(wrapper.find('.discussion-card__actions.is-secondary').exists()).toBe(false)
  })

  it('hides every mutation action in Recovery Review 唯讀模式', () => {
    const wrapper = mount(DiscussionMessageCard, {
      props: {
        message: {
          id: 9,
          user_name: '舊資料使用者',
          content: '唯讀留言內容',
          is_pinned: false,
          is_deleted: false,
          like_count: 0,
          created_at: '2026-07-12T08:00:00Z',
        },
        canPin: true,
        canDelete: true,
        reportOpen: true,
        readOnly: true,
      },
      global: {
        stubs: {
          Button: ButtonStub,
          InlineCommentReport: { template: '<div class="inline-report-stub" />' },
        },
      },
    })

    expect(wrapper.find('.discussion-card__action-stack').exists()).toBe(false)
    expect(wrapper.find('.inline-report-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('唯讀留言內容')
  })
})
