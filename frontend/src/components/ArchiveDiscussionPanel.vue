<template>
  <section class="discussion-panel" :style="{ width }" aria-label="考古題討論區">
    <header
      v-if="showHeader"
      class="discussion-header p-3 flex align-items-center justify-content-between"
    >
      <div class="font-semibold">討論區</div>
      <Button
        v-if="showSettings"
        icon="pi pi-cog"
        severity="secondary"
        text
        rounded
        size="small"
        aria-label="開啟討論區設定"
        title="討論區設定"
        class="discussion-settings-btn"
        @click="openNicknameDialog"
      />
    </header>

    <div ref="messagesRef" class="discussion-messages">
      <div v-if="loading" class="discussion-state">
        <ProgressSpinner strokeWidth="4" />
      </div>
      <div v-else-if="sortedMessages.length === 0" class="discussion-empty">
        還沒有人發起討論，來當第一個吧！
      </div>

      <section
        v-for="message in sortedMessages"
        :key="message.id"
        class="discussion-thread"
        :aria-label="`${message.user_name} 的留言串`"
      >
        <DiscussionMessageCard
          :message="message"
          :can-pin="canPin"
          :can-delete="canDelete(message)"
          :like-loading="isLikeLoading(message.id)"
          :expanded="isExpanded(message.id)"
          :report-open="reportTarget?.id === message.id"
          :report-reason="reportReason"
          :report-custom-message="reportCustomMessage"
          :report-loading="reportSubmitting"
          @reply="startReply"
          @like="toggleLike"
          @pin="togglePin"
          @report="toggleReport"
          @delete="confirmDelete"
          @toggle-expanded="toggleExpanded"
          @update:report-reason="reportReason = $event"
          @update:report-custom-message="reportCustomMessage = $event"
          @cancel-report="cancelReport"
          @submit-report="handleReportSubmit"
        />

        <div v-if="message.replies?.length" class="discussion-thread-toggle">
          <span class="discussion-thread-toggle__line" aria-hidden="true" />
          <button
            type="button"
            class="discussion-thread-toggle__button"
            :aria-expanded="isThreadExpanded(message.id)"
            :aria-controls="replyRegionId(message.id)"
            @click="toggleThread(message.id)"
          >
            <i
              :class="`pi ${isThreadExpanded(message.id) ? 'pi-angle-up' : 'pi-angle-down'}`"
              aria-hidden="true"
            />
            {{ isThreadExpanded(message.id) ? '收起' : '查看' }}
            {{ message.replies.length }} 則回覆
          </button>
        </div>

        <div
          v-if="message.replies?.length && isThreadExpanded(message.id)"
          :id="replyRegionId(message.id)"
          class="discussion-replies"
        >
          <DiscussionMessageCard
            v-for="reply in message.replies"
            :key="reply.id"
            :message="reply"
            is-reply
            :can-delete="canDelete(reply)"
            :like-loading="isLikeLoading(reply.id)"
            :expanded="isExpanded(reply.id)"
            :report-open="reportTarget?.id === reply.id"
            :report-reason="reportReason"
            :report-custom-message="reportCustomMessage"
            :report-loading="reportSubmitting"
            @reply="startReply"
            @like="toggleLike"
            @report="toggleReport"
            @delete="confirmDelete"
            @toggle-expanded="toggleExpanded"
            @update:report-reason="reportReason = $event"
            @update:report-custom-message="reportCustomMessage = $event"
            @cancel-report="cancelReport"
            @submit-report="handleReportSubmit"
          />
        </div>

        <form
          v-if="replyTarget?.rootId === message.id"
          class="discussion-reply-editor"
          @submit.prevent="sendReply"
        >
          <div class="discussion-reply-editor__heading">
            <span>回覆 @{{ replyTarget.message.user_name }}</span>
            <Button
              icon="pi pi-times"
              severity="secondary"
              text
              rounded
              size="small"
              aria-label="取消回覆"
              title="取消回覆"
              class="discussion-cancel-reply-btn"
              @click="cancelReply"
            />
          </div>
          <Textarea
            name="discussion-reply"
            v-model="replyDraft"
            :placeholder="`回覆 @${replyTarget.message.user_name}`"
            class="w-full"
            :maxlength="MESSAGE_MAX_LENGTH"
            :disabled="!canSend"
            rows="2"
            autofocus
            @keydown.enter.ctrl.exact.prevent="sendReply"
            @keydown.enter.meta.exact.prevent="sendReply"
          />
          <div class="discussion-editor-meta">
            <span :style="{ color: replyLengthColor }">{{ replyLengthLabel }}</span>
            <Button
              type="submit"
              icon="pi pi-send"
              label="送出回覆"
              severity="secondary"
              size="small"
              :disabled="!canSend || !replyDraft.trim()"
            />
          </div>
        </form>
      </section>
    </div>

    <form class="discussion-footer" @submit.prevent="sendMessage">
      <div class="discussion-composer">
        <Textarea
          name="discussion-message"
          v-model="draft"
          placeholder="輸入訊息"
          class="w-full"
          :maxlength="MESSAGE_MAX_LENGTH"
          :disabled="!canSend"
          rows="1"
          @keydown.enter.ctrl.exact.prevent="sendMessage"
          @keydown.enter.meta.exact.prevent="sendMessage"
        />
        <div class="discussion-editor-meta">
          <span :style="{ color: messageLengthColor }">{{ messageLengthLabel }}</span>
          <Button
            type="submit"
            icon="pi pi-send"
            label="送出"
            severity="secondary"
            :disabled="!canSend || !draft.trim()"
          />
        </div>
      </div>
    </form>

    <Dialog
      :visible="showNicknameDialog"
      @update:visible="(value) => !value && closeNicknameDialog()"
      :modal="true"
      :draggable="false"
      :style="{ width: '420px', maxWidth: '92vw' }"
      :autoFocus="false"
      :pt="{ root: { 'aria-label': '討論區設定', 'aria-labelledby': null } }"
    >
      <template #header>
        <div class="flex align-items-center gap-2.5">
          <i class="pi pi-cog text-2xl" />
          <div class="text-xl leading-tight font-semibold">討論區設定</div>
        </div>
      </template>
      <div class="flex flex-column gap-3">
        <div class="flex flex-column gap-2">
          <label for="discussion-nickname" class="font-semibold">暱稱</label>
          <InputText
            id="discussion-nickname"
            name="discussion-nickname"
            v-model="nicknameDraft"
            placeholder="輸入暱稱"
            maxlength="15"
            class="w-full"
          />
          <small class="discussion-setting-hint">{{ nicknameHint }}</small>
        </div>
        <div class="flex flex-column gap-2">
          <span class="font-semibold">其他</span>
          <label for="discussion-desktop-default-open" class="flex align-items-center gap-2">
            <Checkbox
              inputId="discussion-desktop-default-open"
              name="discussion-desktop-default-open"
              v-model="desktopDefaultOpen"
              :binary="true"
              @change="handleDesktopDefaultOpenChange"
            />
            <span>預設開啟討論區</span>
          </label>
          <label for="discussion-show-level-title" class="discussion-setting-option">
            <Checkbox
              inputId="discussion-show-level-title"
              name="discussion-show-level-title"
              v-model="showLevelTitleDraft"
              :binary="true"
            />
            <span>
              <span>顯示我的等級稱號</span>
              <small>開啟後，留言名稱旁會顯示目前的 Lv. 與投稿稱號</small>
            </span>
          </label>
        </div>
      </div>

      <template #footer>
        <div class="flex justify-content-end gap-2">
          <Button
            label="取消"
            severity="secondary"
            @click="closeNicknameDialog"
            :disabled="nicknameSaving"
          />
          <Button
            label="儲存"
            severity="success"
            :loading="nicknameSaving"
            :disabled="!canSaveNickname"
            @click="saveNickname"
          />
        </div>
      </template>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { discussionService, userService } from '../api'
import { getCurrentUser } from '../utils/auth'
import { trackEvent, EVENTS } from '../utils/analytics'
import { getBooleanPreference, setBooleanPreference } from '../utils/usePreferences'
import { STORAGE_KEYS } from '../utils/storage'
import { loadContributorLevelSettings } from '../utils/submissionLevel'
import DiscussionMessageCard from './DiscussionMessageCard.vue'

const DESKTOP_DEFAULT_OPEN_KEY = STORAGE_KEYS.local.DISCUSSION_DESKTOP_DEFAULT_OPEN
const MESSAGE_MAX_LENGTH = 200
const WS_RECONNECT_MAX_ATTEMPTS = 6

loadContributorLevelSettings()

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  archiveId: { type: [Number, String], required: true },
  width: { type: String, default: '360px' },
  enabled: { type: Boolean, default: true },
  showHeader: { type: Boolean, default: true },
  showSettings: { type: Boolean, default: true },
})

const emit = defineEmits(['desktop-default-open-change'])
const toast = inject('toast', null)
const confirm = inject('confirm', null)

const messages = ref([])
const loading = ref(false)
const connected = ref(false)
const connecting = ref(false)
const draft = ref('')
const replyDraft = ref('')
const replyTarget = ref(null)
const reportTarget = ref(null)
const reportReason = ref(null)
const reportCustomMessage = ref('')
const reportSubmitting = ref(false)
const expandedById = ref({})
const expandedThreadsById = ref({})
const likeLoadingById = ref({})
const deleteLoadingById = ref({})
const reconnectAttempts = ref(0)
const currentUser = computed(() => getCurrentUser())
const canSend = computed(() => props.enabled && connected.value && Boolean(currentUser.value))
const canPin = computed(() => Boolean(currentUser.value?.is_admin))
const messagesRef = ref(null)

const profile = ref({ nickname: '', name: '', showLevelTitle: true })
const showNicknameDialog = ref(false)
const nicknameDraft = ref('')
const showLevelTitleDraft = ref(true)
const nicknameSaving = ref(false)
const desktopDefaultOpen = ref(getBooleanPreference(DESKTOP_DEFAULT_OPEN_KEY, true))

let socket = null
let reconnectTimer = null
let connectSeq = 0

const sortedMessages = computed(() =>
  [...messages.value].sort((left, right) => {
    if (Boolean(left.is_pinned) !== Boolean(right.is_pinned)) return left.is_pinned ? -1 : 1
    const likeDifference = Number(right.like_count || 0) - Number(left.like_count || 0)
    if (likeDifference) return likeDifference
    const timeDifference =
      new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
    return timeDifference || Number(right.id || 0) - Number(left.id || 0)
  })
)

const nicknameHint = computed(() => {
  const trimmed = (nicknameDraft.value || '').trim()
  return `設定後，討論區會以暱稱顯示，留空以清除暱稱（${trimmed.length}/15）`
})
const canSaveNickname = computed(() => Boolean(currentUser.value) && !nicknameSaving.value)
const messageLengthLabel = computed(
  () => `${String(draft.value ?? '').length}/${MESSAGE_MAX_LENGTH}`
)
const replyLengthLabel = computed(
  () => `${String(replyDraft.value ?? '').length}/${MESSAGE_MAX_LENGTH}`
)
const messageLengthColor = computed(() =>
  draft.value.length > MESSAGE_MAX_LENGTH ? 'var(--p-red-500)' : 'var(--text-secondary)'
)
const replyLengthColor = computed(() =>
  replyDraft.value.length > MESSAGE_MAX_LENGTH ? 'var(--p-red-500)' : 'var(--text-secondary)'
)

function normalizeId(raw) {
  if (raw === null || raw === undefined) return null
  const value = typeof raw === 'string' ? Number(raw) : raw
  return Number.isFinite(value) ? value : null
}

function isExpanded(messageId) {
  return Boolean(expandedById.value?.[messageId])
}

function toggleExpanded(messageId) {
  expandedById.value = { ...expandedById.value, [messageId]: !isExpanded(messageId) }
}

function isThreadExpanded(messageId) {
  return Boolean(expandedThreadsById.value?.[messageId])
}

function setThreadExpanded(messageId, expanded) {
  const next = { ...expandedThreadsById.value }
  if (expanded) next[messageId] = true
  else delete next[messageId]
  expandedThreadsById.value = next
}

function toggleThread(messageId) {
  setThreadExpanded(messageId, !isThreadExpanded(messageId))
}

function replyRegionId(messageId) {
  return `discussion-replies-${messageId}`
}

function isLikeLoading(messageId) {
  return Boolean(likeLoadingById.value?.[messageId])
}

function findMessage(messageId) {
  for (const root of messages.value) {
    if (root.id === messageId) return root
    const reply = (root.replies || []).find((item) => item.id === messageId)
    if (reply) return reply
  }
  return null
}

function updateCurrentUserMessageNames() {
  const user = currentUser.value
  if (!user) return
  const preferredName = (profile.value.nickname || profile.value.name || '').trim()
  const update = (message) => {
    if (message.user_id === user.id) {
      message.user_name = preferredName
      message.author_show_level_title = profile.value.showLevelTitle
    }
    ;(message.replies || []).forEach(update)
  }
  messages.value.forEach(update)
}

function closeSocket() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (!socket) return
  try {
    socket.__manualClose = true
    socket.close()
  } catch {
    // ignore
  }
  socket = null
  connected.value = false
  connecting.value = false
}

function scheduleReconnect() {
  if (!props.enabled || !currentUser.value || reconnectTimer) return
  if (reconnectAttempts.value >= WS_RECONNECT_MAX_ATTEMPTS) {
    toast?.add?.({
      severity: 'warn',
      summary: '連線中斷',
      detail: '討論區已斷線，請重新整理後再試',
      life: 4000,
    })
    return
  }
  reconnectAttempts.value += 1
  const delay = Math.min(10_000, 500 * 2 ** (reconnectAttempts.value - 1))
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)
}

function applyIncomingMessage(incoming) {
  if (findMessage(incoming.id)) return
  const user = currentUser.value
  const preferredName = (profile.value.nickname || profile.value.name || '').trim()
  const normalized =
    user && preferredName && incoming.user_id === user.id
      ? {
          ...incoming,
          user_name: preferredName,
          author_show_level_title: profile.value.showLevelTitle,
          replies: incoming.replies || [],
        }
      : { ...incoming, replies: incoming.replies || [] }

  if (normalized.parent_id) {
    const root = messages.value.find((message) => message.id === normalized.parent_id)
    if (!root) return
    root.replies = [...(root.replies || []), normalized].sort(
      (left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime() ||
        Number(left.id) - Number(right.id)
    )
    if (Number(normalized.user_id) === Number(currentUser.value?.id)) {
      setThreadExpanded(root.id, true)
    }
    if (replyTarget.value?.message?.id === normalized.reply_to_message_id) cancelReply()
    return
  }
  messages.value = [...messages.value, normalized]
}

function applyDelete(messageId, preserveThread) {
  if (reportTarget.value?.id === messageId) cancelReport()
  if (replyTarget.value?.message?.id === messageId) cancelReply()
  const root = messages.value.find((message) => message.id === messageId)
  if (root) {
    if (preserveThread) {
      root.is_deleted = true
      root.content = ''
      root.is_pinned = false
    } else {
      messages.value = messages.value.filter((message) => message.id !== messageId)
      setThreadExpanded(messageId, false)
    }
    return
  }
  for (const message of messages.value) {
    message.replies = (message.replies || []).filter((reply) => reply.id !== messageId)
    if (message.replies.length === 0) setThreadExpanded(message.id, false)
  }
}

async function connect() {
  const seq = (connectSeq += 1)
  closeSocket()
  if (!props.enabled || !currentUser.value) return
  const courseId = normalizeId(props.courseId)
  const archiveId = normalizeId(props.archiveId)
  if (!courseId || !archiveId) return

  connecting.value = true
  loading.value = true
  const ws = discussionService.openArchiveDiscussionWebSocket(courseId, archiveId)
  if (!ws) {
    connecting.value = false
    loading.value = false
    return
  }
  socket = ws

  ws.onopen = () => {
    if (seq !== connectSeq) return
    connecting.value = false
    connected.value = true
    reconnectAttempts.value = 0
  }
  ws.onmessage = (event) => {
    try {
      if (seq !== connectSeq) return
      const data = JSON.parse(event.data)
      if (data.type === 'history' && Array.isArray(data.messages)) {
        messages.value = data.messages
        expandedThreadsById.value = {}
        updateCurrentUserMessageNames()
      } else if (data.type === 'message' && data.message) {
        applyIncomingMessage(data.message)
      } else if (data.type === 'delete' && data.message_id) {
        applyDelete(data.message_id, Boolean(data.preserve_thread))
      } else if (data.type === 'pin' && data.message_id) {
        const message = findMessage(data.message_id)
        if (message) message.is_pinned = Boolean(data.is_pinned)
      } else if (data.type === 'like' && data.message_id) {
        const message = findMessage(data.message_id)
        if (message) {
          message.like_count = Math.max(0, Number(data.like_count) || 0)
          if (Number(data.user_id) === Number(currentUser.value?.id)) {
            message.liked_by_current_user = Boolean(data.liked)
          }
        }
      } else if (data.type === 'error') {
        toast?.add?.({
          severity: 'error',
          summary: '送出失敗',
          detail: data.detail || '無法送出訊息，請稍後再試',
          life: 3000,
        })
      }
    } catch {
      // Ignore malformed socket events.
    } finally {
      loading.value = false
    }
  }
  ws.onerror = () => {
    if (seq !== connectSeq || ws.__manualClose) return
    connected.value = false
    connecting.value = false
    loading.value = false
    scheduleReconnect()
  }
  ws.onclose = (event) => {
    if (seq !== connectSeq || ws.__manualClose) return
    connected.value = false
    connecting.value = false
    loading.value = false
    if (event?.code !== 4401) scheduleReconnect()
  }
}

function sendContent(content, replyToMessageId = null) {
  const normalizedContent = String(content ?? '').trim()
  if (!normalizedContent || normalizedContent.length > MESSAGE_MAX_LENGTH) return false
  if (!socket || socket.readyState !== WebSocket.OPEN) return false
  socket.send(
    JSON.stringify({
      type: 'send',
      content: normalizedContent,
      ...(replyToMessageId ? { reply_to_message_id: replyToMessageId } : {}),
    })
  )
  trackEvent(EVENTS.DISCUSSION_SEND_MESSAGE, {
    courseId: normalizeId(props.courseId),
    archiveId: normalizeId(props.archiveId),
    length: normalizedContent.length,
    isReply: Boolean(replyToMessageId),
  })
  return true
}

function sendMessage() {
  if (sendContent(draft.value)) draft.value = ''
}

function startReply(message) {
  if (!currentUser.value) {
    toast?.add?.({
      severity: 'warn',
      summary: '請先登入',
      detail: '登入後即可回覆留言',
      life: 3000,
    })
    return
  }
  cancelReport()
  replyTarget.value = {
    message,
    rootId: message.parent_id || message.id,
  }
  replyDraft.value = ''
}

function cancelReply() {
  replyTarget.value = null
  replyDraft.value = ''
}

function resetReportForm() {
  reportReason.value = null
  reportCustomMessage.value = ''
}

function cancelReport() {
  reportTarget.value = null
  resetReportForm()
}

function toggleReport(message) {
  if (!currentUser.value) {
    toast?.add?.({
      severity: 'warn',
      summary: '請先登入',
      detail: '登入後即可回報留言',
      life: 3000,
    })
    return
  }
  if (reportTarget.value?.id === message.id) {
    cancelReport()
    return
  }
  cancelReply()
  resetReportForm()
  reportTarget.value = message
}

async function handleReportSubmit(payload) {
  const courseId = normalizeId(props.courseId)
  const archiveId = normalizeId(props.archiveId)
  const commentId = normalizeId(payload?.comment_id)
  if (!courseId || !archiveId || !commentId || reportSubmitting.value) return
  reportSubmitting.value = true
  try {
    await discussionService.reportArchiveMessage(courseId, archiveId, commentId, {
      report_reason: payload.report_reason,
      custom_message: payload.custom_message,
    })
    toast?.add?.({
      severity: 'success',
      summary: '回報已送出',
      detail: '留言回報已送出，請等待管理員審核',
      life: 3500,
    })
    cancelReport()
  } catch (error) {
    console.error('Submit comment report error:', error)
    const isDuplicate = error?.response?.status === 409
    toast?.add?.({
      severity: isDuplicate ? 'warn' : 'error',
      summary: isDuplicate ? '已有待審核回報' : '回報送出失敗',
      detail: isDuplicate ? '相同原因的回報仍在處理中' : '請稍後再試',
      life: 3500,
    })
  } finally {
    reportSubmitting.value = false
  }
}

function sendReply() {
  if (!replyTarget.value) return
  if (sendContent(replyDraft.value, replyTarget.value.message.id)) {
    replyDraft.value = ''
  }
}

function canDelete(message) {
  const user = currentUser.value
  return Boolean(user && !message.is_deleted && (user.is_admin || message.user_id === user.id))
}

async function toggleLike(message) {
  if (!currentUser.value || isLikeLoading(message.id)) return
  const courseId = normalizeId(props.courseId)
  const archiveId = normalizeId(props.archiveId)
  if (!courseId || !archiveId) return

  const previousLiked = Boolean(message.liked_by_current_user)
  const previousCount = Math.max(0, Number(message.like_count) || 0)
  likeLoadingById.value = { ...likeLoadingById.value, [message.id]: true }
  message.liked_by_current_user = !previousLiked
  message.like_count = Math.max(0, previousCount + (previousLiked ? -1 : 1))

  try {
    const { data } = previousLiked
      ? await discussionService.unlikeArchiveMessage(courseId, archiveId, message.id)
      : await discussionService.likeArchiveMessage(courseId, archiveId, message.id)
    message.liked_by_current_user = Boolean(data?.liked)
    message.like_count = Math.max(0, Number(data?.like_count) || 0)
  } catch (error) {
    console.error('Toggle discussion like error:', error)
    message.liked_by_current_user = previousLiked
    message.like_count = previousCount
    toast?.add?.({
      severity: 'error',
      summary: '愛心更新失敗',
      detail: '無法更新愛心，請稍後再試',
      life: 3000,
    })
  } finally {
    likeLoadingById.value = { ...likeLoadingById.value, [message.id]: false }
  }
}

async function deleteMessage(message) {
  if (deleteLoadingById.value[message.id]) return

  const courseId = normalizeId(props.courseId)
  const archiveId = normalizeId(props.archiveId)
  if (!courseId || !archiveId) return
  deleteLoadingById.value = { ...deleteLoadingById.value, [message.id]: true }
  try {
    const { data } = await discussionService.deleteArchiveMessage(courseId, archiveId, message.id)
    applyDelete(message.id, Boolean(data?.preserve_thread))
    toast?.add?.({
      severity: 'success',
      summary: '刪除成功',
      detail: '留言已刪除',
      life: 3000,
    })
  } catch (error) {
    console.error('Delete message error:', error)
    toast?.add?.({
      severity: 'error',
      summary: '刪除失敗',
      detail: '無法刪除訊息，請稍後再試',
      life: 3000,
    })
  } finally {
    deleteLoadingById.value = { ...deleteLoadingById.value, [message.id]: false }
  }
}

function confirmDelete(message) {
  if (!confirm?.require || deleteLoadingById.value[message.id]) return

  const hasReplies = !message.parent_id && Boolean(message.replies?.length)
  confirm.require({
    message: hasReplies
      ? '留言刪除後無法復原，也不會進入垃圾桶。已有的回覆會依目前討論串規則保留。'
      : '留言刪除後無法復原，也不會進入垃圾桶。',
    header: '刪除這則留言？',
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: '取消',
    acceptLabel: '刪除',
    acceptClass: 'p-button-danger',
    accept: () => deleteMessage(message),
  })
}

async function togglePin(message) {
  if (!canPin.value || message.parent_id) return
  const courseId = normalizeId(props.courseId)
  const archiveId = normalizeId(props.archiveId)
  if (!courseId || !archiveId) return
  const previous = Boolean(message.is_pinned)
  message.is_pinned = !previous
  try {
    await discussionService.pinArchiveMessage(courseId, archiveId, message.id, !previous)
  } catch (error) {
    console.error('Pin message error:', error)
    message.is_pinned = previous
    toast?.add?.({
      severity: 'error',
      summary: '置頂失敗',
      detail: '無法更新留言置頂狀態',
      life: 3000,
    })
  }
}

async function loadMe() {
  if (!currentUser.value) return
  try {
    const { data } = await userService.getMe()
    profile.value = {
      nickname: (data?.nickname || data?.name || '').trim(),
      name: (data?.name || '').trim(),
      showLevelTitle: data?.show_level_title !== false,
    }
    updateCurrentUserMessageNames()
  } catch {
    // Keep token profile fallback.
  }
}

function openNicknameDialog() {
  nicknameDraft.value = (profile.value.nickname || profile.value.name || '').trim()
  showLevelTitleDraft.value = profile.value.showLevelTitle
  desktopDefaultOpen.value = getBooleanPreference(DESKTOP_DEFAULT_OPEN_KEY, true)
  showNicknameDialog.value = true
}

function closeNicknameDialog() {
  showNicknameDialog.value = false
}

defineExpose({ openNicknameDialog })

async function saveNickname() {
  if (!currentUser.value) return
  nicknameSaving.value = true
  const nextNickname = (nicknameDraft.value || '').trim()
  try {
    const { data } = await userService.updateMyDiscussionSettings(
      nextNickname,
      showLevelTitleDraft.value
    )
    profile.value = {
      nickname: (data?.nickname || data?.name || '').trim(),
      name: (data?.name || profile.value.name || '').trim(),
      showLevelTitle: data?.show_level_title !== false,
    }
    updateCurrentUserMessageNames()
    trackEvent(EVENTS.DISCUSSION_UPDATE_NICKNAME, {
      cleared: !nextNickname,
      length: nextNickname.length,
    })
    toast?.add?.({
      severity: 'success',
      summary: '儲存成功',
      detail: '討論區設定已儲存',
      life: 2500,
    })
    closeNicknameDialog()
  } catch (error) {
    console.error('Update nickname error:', error)
    const detail = error?.response?.data?.detail
    toast?.add?.({
      severity: 'error',
      summary: '更新失敗',
      detail: typeof detail === 'string' && detail.trim() ? detail : '無法更新暱稱，請稍後再試',
      life: 3000,
    })
  } finally {
    nicknameSaving.value = false
  }
}

function handleDesktopDefaultOpenChange() {
  const next = Boolean(desktopDefaultOpen.value)
  setBooleanPreference(DESKTOP_DEFAULT_OPEN_KEY, next)
  emit('desktop-default-open-change', next)
  trackEvent(EVENTS.DISCUSSION_SET_DEFAULT_OPEN, { enabled: next })
}

watch(
  () => [props.courseId, props.archiveId, props.enabled],
  () => {
    messages.value = []
    cancelReply()
    cancelReport()
    connect()
  }
)

onMounted(() => {
  loadMe()
  connect()
})
onBeforeUnmount(closeSocket)
</script>

<style scoped>
.discussion-panel {
  container-type: inline-size;
  display: flex;
  min-width: 280px;
  max-width: 420px;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-primary);
}

.discussion-header,
.discussion-footer {
  flex: 0 0 auto;
}

.discussion-header {
  border-bottom: 1px solid var(--border-color);
}

.discussion-messages {
  display: flex;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 0.65rem;
  overflow: auto;
  padding: 0.75rem;
}

.discussion-state {
  display: flex;
  min-height: 8rem;
  flex: 1;
  align-items: center;
  justify-content: center;
}

.discussion-empty {
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  line-height: 1.5;
}

.discussion-thread,
.discussion-replies {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.5rem;
}

.discussion-thread-toggle {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.4rem;
  padding-inline: 0.15rem;
}

.discussion-thread-toggle__line {
  width: 1.25rem;
  height: 1px;
  flex: 0 0 auto;
  background: color-mix(in srgb, var(--text-secondary) 42%, transparent);
}

.discussion-thread-toggle__button {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 0.28rem;
  padding: 0.15rem 0.2rem;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
  cursor: pointer;
}

.discussion-thread-toggle__button:hover {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--text-secondary) 9%, transparent);
}

.discussion-thread-toggle__button:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.discussion-thread-toggle__button .pi {
  font-size: 0.7rem;
}

.discussion-replies {
  margin-left: clamp(0.55rem, 4cqi, 1rem);
  padding-left: 0.5rem;
  border-left: 2px solid color-mix(in srgb, var(--border-color) 82%, transparent);
}

.discussion-reply-editor {
  display: flex;
  min-width: 0;
  margin-left: clamp(0.55rem, 4cqi, 1rem);
  padding: 0.65rem;
  flex-direction: column;
  gap: 0.45rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-secondary) 72%, var(--bg-primary));
}

.discussion-reply-editor__heading,
.discussion-editor-meta {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.discussion-reply-editor__heading {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
  overflow-wrap: anywhere;
}

.discussion-footer {
  padding: 0.75rem;
  border-top: 1px solid var(--border-color);
}

.discussion-composer {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.35rem;
}

.discussion-editor-meta {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  font-variant-numeric: tabular-nums;
}

.discussion-setting-option {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}

.discussion-setting-option > span {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.15rem;
}

.discussion-setting-option small,
.discussion-setting-hint {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

:deep(.discussion-settings-btn.p-button),
:deep(.discussion-cancel-reply-btn.p-button) {
  min-width: 2rem;
  width: 2rem;
  height: 2rem;
  padding: 0;
}

@container (max-width: 320px) {
  .discussion-messages,
  .discussion-footer {
    padding: 0.55rem;
  }

  .discussion-replies,
  .discussion-reply-editor {
    margin-left: 0.35rem;
    padding-left: 0.35rem;
  }
}
</style>
