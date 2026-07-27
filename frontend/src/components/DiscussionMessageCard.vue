<template>
  <article
    class="discussion-card"
    :class="{
      'is-reply': isReply,
      'is-pinned': message.is_pinned,
      'is-deleted': message.is_deleted,
    }"
  >
    <div class="discussion-card__author-block">
      <div class="discussion-card__author-line">
        <span class="discussion-card__author-name">{{ message.user_name }}</span>
        <ContributorLevelBadge
          v-if="shouldShowLevelTitle"
          :level="messageLevel.level"
          :title="messageLevel.name"
          size="compact"
          show-title
        />
        <Tag
          v-if="message.is_pinned"
          value="置頂"
          severity="warning"
          class="discussion-card__pin-tag"
        />
      </div>
      <time class="discussion-card__time" :datetime="message.created_at">
        {{ formattedTime }}
      </time>
    </div>

    <div v-if="!message.is_deleted" class="discussion-card__action-stack">
      <div class="discussion-card__actions is-primary">
        <Button
          icon="pi pi-reply"
          severity="secondary"
          text
          rounded
          size="small"
          aria-label="回覆留言"
          title="回覆"
          class="discussion-card__icon-button"
          @click="$emit('reply', message)"
        />
        <Button
          :icon="message.liked_by_current_user ? 'pi pi-heart-fill' : 'pi pi-heart'"
          :label="formattedLikeCount"
          :severity="message.liked_by_current_user ? 'danger' : 'secondary'"
          text
          rounded
          size="small"
          :loading="likeLoading"
          :disabled="likeLoading"
          :aria-label="message.liked_by_current_user ? '取消愛心' : '按愛心'"
          :aria-pressed="Boolean(message.liked_by_current_user)"
          :title="message.liked_by_current_user ? '取消愛心' : '按愛心'"
          class="discussion-card__icon-button discussion-card__like-button"
          :class="{ 'is-active': message.liked_by_current_user }"
          @click="$emit('like', message)"
        />
        <Button
          icon="pi pi-flag"
          severity="secondary"
          text
          rounded
          size="small"
          aria-label="回報留言"
          title="回報"
          class="discussion-card__icon-button"
          @click="$emit('report', message)"
        />
      </div>

      <div v-if="(canPin && !isReply) || canDelete" class="discussion-card__actions is-secondary">
        <Button
          v-if="canPin && !isReply"
          :icon="message.is_pinned ? 'pi pi-bookmark-fill' : 'pi pi-bookmark'"
          severity="warning"
          text
          rounded
          size="small"
          :aria-label="message.is_pinned ? '取消置頂' : '置頂留言'"
          :title="message.is_pinned ? '取消置頂' : '置頂'"
          class="discussion-card__icon-button"
          @click="$emit('pin', message)"
        />
        <Button
          v-if="canDelete"
          icon="pi pi-trash"
          severity="danger"
          text
          rounded
          size="small"
          aria-label="刪除留言"
          title="刪除"
          class="discussion-card__icon-button"
          @click="$emit('delete', message)"
        />
      </div>
    </div>

    <div v-if="message.is_deleted" class="discussion-card__deleted-text">此留言已刪除</div>
    <div v-else class="discussion-card__body">
      <div v-if="isReply && message.reply_to_user_name" class="discussion-card__reply-context">
        回覆 @{{ message.reply_to_user_name }}
      </div>
      <div class="discussion-card__content">{{ displayedContent }}</div>
      <div v-if="shouldShowToggle" class="discussion-card__more-row">
        <button
          type="button"
          class="discussion-card__more-button"
          :aria-expanded="expanded"
          :aria-label="expanded ? '收合訊息' : '顯示完整訊息'"
          @click="$emit('toggle-expanded', message.id)"
        >
          {{ expanded ? '顯示較少' : '顯示更多' }}
          <i :class="`pi ${expanded ? 'pi-angle-up' : 'pi-angle-down'}`" aria-hidden="true" />
        </button>
      </div>
    </div>

    <InlineCommentReport
      v-if="reportOpen && !message.is_deleted"
      class="discussion-card__inline-panel"
      :message="message"
      :reason="reportReason"
      :customMessage="reportCustomMessage"
      :loading="reportLoading"
      @update:reason="$emit('update:reportReason', $event)"
      @update:customMessage="$emit('update:reportCustomMessage', $event)"
      @cancel="$emit('cancel-report')"
      @submit="$emit('submit-report', $event)"
    />
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { formatRelativeTime } from '../utils/time'
import { resolveSubmissionLevel } from '../utils/submissionLevel'
import ContributorLevelBadge from './ContributorLevelBadge.vue'
import InlineCommentReport from './InlineCommentReport.vue'

const MESSAGE_PREVIEW_LENGTH = 100

const props = defineProps({
  message: { type: Object, required: true },
  isReply: { type: Boolean, default: false },
  canPin: { type: Boolean, default: false },
  canDelete: { type: Boolean, default: false },
  likeLoading: { type: Boolean, default: false },
  expanded: { type: Boolean, default: false },
  reportOpen: { type: Boolean, default: false },
  reportReason: { type: String, default: null },
  reportCustomMessage: { type: String, default: '' },
  reportLoading: { type: Boolean, default: false },
})

defineEmits([
  'reply',
  'like',
  'pin',
  'report',
  'delete',
  'toggle-expanded',
  'update:reportReason',
  'update:reportCustomMessage',
  'cancel-report',
  'submit-report',
])

const shouldShowLevelTitle = computed(
  () =>
    props.message?.author_show_level_title === true &&
    Number.isFinite(props.message?.author_experience)
)
const messageLevel = computed(() => resolveSubmissionLevel(props.message?.author_experience))
const formattedTime = computed(() => formatRelativeTime(props.message?.created_at))
const content = computed(() => String(props.message?.content ?? ''))
const shouldShowToggle = computed(() => content.value.length > MESSAGE_PREVIEW_LENGTH)
const displayedContent = computed(() => {
  if (props.expanded || !shouldShowToggle.value) return content.value
  return `${content.value.slice(0, MESSAGE_PREVIEW_LENGTH)}…`
})
const formattedLikeCount = computed(() =>
  String(Math.max(0, Number(props.message?.like_count) || 0))
)
</script>

<style scoped>
.discussion-card {
  container-type: inline-size;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'author primary-actions'
    'time secondary-actions'
    'content content'
    'inline-panel inline-panel';
  align-items: center;
  gap: 0.08rem 0.45rem;
  min-width: 0;
  padding: 0.65rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.discussion-card.is-pinned {
  border-color: color-mix(in srgb, var(--brand-gold) 58%, var(--border-color));
  background: color-mix(in srgb, var(--brand-gold) 10%, var(--bg-secondary));
}

.discussion-card.is-reply {
  background: color-mix(in srgb, var(--bg-primary) 55%, var(--bg-secondary));
}

.discussion-card__author-block,
.discussion-card__author-line {
  min-width: 0;
}

.discussion-card__author-block {
  display: contents;
}

.discussion-card__author-line {
  grid-area: author;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  align-self: center;
  gap: 0.3rem 0.45rem;
}

.discussion-card__author-name {
  color: var(--text-primary);
  font-size: var(--app-font-size-sm);
  font-weight: 700;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.discussion-card__time {
  grid-area: time;
  align-self: center;
  width: fit-content;
  max-width: 100%;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.discussion-card__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  gap: 0.2rem;
}

.discussion-card__action-stack {
  display: contents;
}

.discussion-card__action-stack .discussion-card__actions {
  align-self: center;
  justify-self: end;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.discussion-card__actions.is-primary {
  grid-area: primary-actions;
}

.discussion-card__actions.is-secondary {
  grid-area: secondary-actions;
}

.discussion-card__body {
  grid-area: content;
  min-width: 0;
  margin-top: 0.3rem;
}

.discussion-card__reply-context {
  margin-bottom: 0.3rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.discussion-card__content,
.discussion-card__deleted-text {
  grid-area: content;
  color: var(--text-primary);
  font-size: var(--app-font-size-sm);
  line-height: 1.55;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.discussion-card__deleted-text {
  margin-top: 0.3rem;
  color: var(--text-secondary);
  font-style: italic;
}

.discussion-card__inline-panel {
  grid-area: inline-panel;
  min-width: 0;
  margin-top: 0.55rem;
}

:deep(.discussion-card__icon-button.p-button) {
  min-width: 2rem;
  width: auto;
  height: 2rem;
  padding: 0 0.42rem;
  flex: 0 0 auto;
}

:deep(.discussion-card__icon-button.p-button .p-button-icon) {
  font-size: 0.82rem;
}

:deep(.discussion-card__like-button.p-button .p-button-label) {
  min-width: 1ch;
  font-size: var(--app-font-size-xs);
  font-variant-numeric: tabular-nums;
}

:deep(.discussion-card__like-button.is-active.p-button) {
  color: var(--p-red-500, var(--text-primary));
}

:deep(.discussion-card__pin-tag.p-tag) {
  padding: 0.08rem 0.38rem;
  font-size: var(--app-font-size-xs);
  line-height: 1.2;
}

.discussion-card__more-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.35rem;
}

.discussion-card__more-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--bg-primary);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
}

.discussion-card__more-button:hover,
.discussion-card__more-button:focus-visible {
  background: var(--bg-secondary);
}

@media (pointer: coarse) {
  :deep(.discussion-card__icon-button.p-button) {
    min-width: 2.5rem;
    height: 2.5rem;
  }
}
</style>
