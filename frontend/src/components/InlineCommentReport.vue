<template>
  <form class="comment-inline-report" :aria-label="reportHeading" @submit.prevent="submitReport">
    <div class="comment-inline-report__heading">
      <i class="pi pi-flag" aria-hidden="true" />
      <span>{{ reportHeading }}</span>
    </div>

    <blockquote class="comment-inline-report__target">
      <div class="comment-inline-report__target-meta">
        <span>{{ message.user_name }}</span>
        <span aria-hidden="true">·</span>
        <time :datetime="message.created_at">{{ formattedTime }}</time>
      </div>
      <div class="comment-inline-report__target-content">「{{ contentPreview }}」</div>
    </blockquote>

    <div class="comment-inline-report__field">
      <label :for="reasonInputId">{{ $t('回報原因') }}</label>
      <Select
        :inputId="reasonInputId"
        :modelValue="reason"
        :options="commentReportReasons"
        optionLabel="label"
        optionValue="value"
        :placeholder="$t('請選擇回報原因')"
        class="w-full"
        @update:modelValue="updateReason"
      />
    </div>

    <div v-if="isOtherReason" class="comment-inline-report__field">
      <label :for="customMessageInputId">{{ $t('請描述回報原因') }}</label>
      <Textarea
        :id="customMessageInputId"
        :modelValue="customMessage"
        rows="3"
        class="w-full"
        :placeholder="$t('請具體描述需要回報的原因')"
        :maxlength="COMMENT_REPORT_CUSTOM_MESSAGE_MAX_LENGTH"
        @update:modelValue="$emit('update:customMessage', $event)"
      />
      <div class="comment-inline-report__counter" :class="{ 'is-invalid': !hasValidCustomMessage }">
        {{ customMessageLength }}/{{ COMMENT_REPORT_CUSTOM_MESSAGE_MAX_LENGTH }}
      </div>
    </div>

    <div class="comment-inline-report__actions">
      <Button
        type="button"
        :label="$t('取消')"
        severity="secondary"
        text
        size="small"
        @click="$emit('cancel')"
      />
      <Button
        type="submit"
        :label="$t('送出回報')"
        icon="pi pi-send"
        severity="secondary"
        size="small"
        :loading="loading"
        :disabled="!canSubmit"
        :title="submitTitle"
      />
    </div>
  </form>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatRelativeTime } from '../utils/time'
import {
  COMMENT_REPORT_CUSTOM_MESSAGE_MAX_LENGTH,
  COMMENT_REPORT_OTHER_REASON,
  COMMENT_REPORT_REASONS,
  COMMENT_REPORT_SUBMISSION_AVAILABLE,
  buildCommentReportPayload,
} from '../constants/commentReport'

const props = defineProps({
  message: { type: Object, required: true },
  reason: { type: String, default: null },
  customMessage: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  targetType: { type: String, default: 'comment' },
})
const { t } = useI18n()
const commentReportReasons = computed(() =>
  COMMENT_REPORT_REASONS.map((option) => ({ ...option, label: t(option.label) }))
)

const emit = defineEmits(['update:reason', 'update:customMessage', 'cancel', 'submit'])

const reasonInputId = computed(() => `comment-report-reason-${props.message.id}`)
const customMessageInputId = computed(() => `comment-report-message-${props.message.id}`)
const formattedTime = computed(() => formatRelativeTime(props.message.created_at))
const reportHeading = computed(() =>
  props.targetType === 'wish' ? t('回報這筆許願') : t('回報這則留言')
)
const submitTitle = computed(() =>
  props.targetType === 'wish' ? t('送出許願回報') : t('送出留言回報')
)
const contentPreview = computed(() => {
  const content = props.message.is_deleted
    ? t('此留言已刪除')
    : String(props.message.content || '').trim()
  return content.length > 120 ? `${content.slice(0, 120)}…` : content
})
const isOtherReason = computed(() => props.reason === COMMENT_REPORT_OTHER_REASON)
const customMessageLength = computed(() => String(props.customMessage || '').length)
const hasValidCustomMessage = computed(
  () =>
    !isOtherReason.value ||
    (Boolean(String(props.customMessage || '').trim()) &&
      customMessageLength.value <= COMMENT_REPORT_CUSTOM_MESSAGE_MAX_LENGTH)
)
const isFormValid = computed(
  () =>
    commentReportReasons.value.some((option) => option.value === props.reason) &&
    hasValidCustomMessage.value
)
const reportPayload = computed(() =>
  buildCommentReportPayload(props.message.id, props.reason, props.customMessage)
)
const canSubmit = computed(
  () => COMMENT_REPORT_SUBMISSION_AVAILABLE && isFormValid.value && !props.loading
)

function updateReason(value) {
  emit('update:reason', value)
  if (value !== COMMENT_REPORT_OTHER_REASON) emit('update:customMessage', '')
}

function submitReport() {
  if (!canSubmit.value) return
  emit('submit', reportPayload.value)
}

defineExpose({ isFormValid, reportPayload })
</script>

<style scoped>
.comment-inline-report {
  display: flex;
  min-width: 0;
  padding: 0.65rem;
  flex-direction: column;
  gap: 0.6rem;
  border-left: 2px solid color-mix(in srgb, var(--border-color) 82%, transparent);
  border-radius: 0 7px 7px 0;
  background: color-mix(in srgb, var(--bg-primary) 58%, var(--bg-secondary));
}

.comment-inline-report__heading {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--text-primary);
  font-size: var(--app-font-size-sm);
  font-weight: 700;
}

.comment-inline-report__target {
  min-width: 0;
  margin: 0;
  padding: 0.45rem 0.55rem;
  border-left: 2px solid var(--border-color);
  background: color-mix(in srgb, var(--bg-secondary) 72%, transparent);
}

.comment-inline-report__target-meta {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 0.25rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
}

.comment-inline-report__target-content {
  margin-top: 0.25rem;
  color: var(--text-primary);
  font-size: var(--app-font-size-xs);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.comment-inline-report__field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.3rem;
}

.comment-inline-report__field label {
  color: var(--text-primary);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
}

:deep(.p-select),
:deep(.p-textarea) {
  min-width: 0;
  max-width: 100%;
  font-size: var(--app-font-size-sm);
}

.comment-inline-report__counter,
.comment-inline-report__notice {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.4;
}

.comment-inline-report__counter {
  align-self: flex-end;
  font-variant-numeric: tabular-nums;
}

.comment-inline-report__counter.is-invalid {
  color: var(--p-red-500, var(--text-primary));
}

.comment-inline-report__actions {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.35rem;
}
</style>
