import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import InlineCommentReport from '@/components/InlineCommentReport.vue'
import { COMMENT_REPORT_REASONS, buildCommentReportPayload } from '@/constants/commentReport'

const SelectStub = {
  name: 'SelectStub',
  props: ['modelValue', 'options', 'optionLabel', 'optionValue', 'placeholder'],
  emits: ['update:modelValue'],
  template: `
    <select :value="modelValue" @change="$emit('update:modelValue', $event.target.value)">
      <option value="">{{ placeholder }}</option>
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
  `,
}

const TextareaStub = {
  props: ['modelValue', 'maxlength'],
  emits: ['update:modelValue'],
  template:
    '<textarea :value="modelValue" :maxlength="maxlength" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const ButtonStub = {
  props: ['label', 'disabled', 'type'],
  emits: ['click'],
  template:
    '<button :type="type" :disabled="disabled" @click="$emit(\'click\')">{{ label }}</button>',
}

function mountReport(props = {}) {
  return mount(InlineCommentReport, {
    props: {
      message: {
        id: 42,
        user_name: '被回報的回覆者',
        content: '這是被點擊的回覆留言本身',
        created_at: '2026-07-12T06:51:00Z',
      },
      ...props,
    },
    global: {
      stubs: {
        Select: SelectStub,
        Textarea: TextareaStub,
        Button: ButtonStub,
      },
    },
  })
}

describe('InlineCommentReport', () => {
  it('gives wish reports the same reasons and Other text contract', async () => {
    const wrapper = mountReport({ targetType: 'wish', reason: 'misinformation' })

    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('請描述回報原因')
    expect(wrapper.vm.commentReportReasons.map((option) => option.value)).toContain('other')
    expect(wrapper.vm.isFormValid).toBe(true)
    expect(wrapper.vm.reportPayload).toEqual({
      comment_id: 42,
      report_reason: 'misinformation',
      custom_message: null,
    })

    await wrapper.setProps({ reason: 'other', customMessage: '  wish details  ' })
    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.vm.reportPayload.custom_message).toBe('wish details')
  })

  it('shows the selected reply target and the centrally defined report reasons', () => {
    const wrapper = mountReport({ reason: 'spam_or_duplicate' })

    expect(wrapper.text()).toContain('被回報的回覆者')
    expect(wrapper.text()).toContain('這是被點擊的回覆留言本身')
    expect(
      wrapper
        .findAll('option')
        .slice(1)
        .map((option) => option.text().trim())
    ).toEqual(COMMENT_REPORT_REASONS.map((option) => option.label))
    expect(wrapper.vm.isFormValid).toBe(true)
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('requires trimmed custom text only for other and clears it when switching away', async () => {
    const wrapper = mountReport({ reason: 'other', customMessage: '   ' })

    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.vm.isFormValid).toBe(false)

    await wrapper.setProps({ customMessage: '  補充的回報原因  ' })
    expect(wrapper.vm.isFormValid).toBe(true)
    expect(wrapper.vm.reportPayload).toEqual({
      comment_id: 42,
      report_reason: 'other',
      custom_message: '補充的回報原因',
    })

    await wrapper.get('select').setValue('misinformation')
    expect(wrapper.emitted('update:customMessage')).toEqual([['']])
  })

  it('builds API-ready payloads without leaking hidden custom text and resets on cancel', async () => {
    const wrapper = mountReport({ reason: 'privacy_violation', customMessage: '不應送出的舊文字' })

    expect(buildCommentReportPayload(42, 'privacy_violation', '不應送出的舊文字')).toEqual({
      comment_id: 42,
      report_reason: 'privacy_violation',
      custom_message: null,
    })

    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('emits a validated API payload on submit and disables while loading', async () => {
    const wrapper = mountReport({ reason: 'misinformation' })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toEqual([
      [
        {
          comment_id: 42,
          report_reason: 'misinformation',
          custom_message: null,
        },
      ],
    ])

    await wrapper.setProps({ loading: true })
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })
})
