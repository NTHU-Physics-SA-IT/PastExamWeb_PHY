<template>
  <form class="archive-report-panel" aria-label="回報考古題" @submit.prevent="submitReport">
    <header class="archive-report-panel__header">
      <div>
        <h3>回報考古題</h3>
        <p>請告訴我們這份考古題遇到的問題。</p>
      </div>
      <i class="pi pi-flag" aria-hidden="true" />
    </header>

    <section class="archive-report-panel__source" aria-label="目前考古題">
      <strong>{{ courseName || '未命名課程' }}</strong>
      <span>{{ title || '未命名考古題' }}</span>
      <small>{{ sourceMeta }}</small>
    </section>

    <Message v-if="!authenticated" severity="warn" :closable="false">
      請先登入後再送出考古回報。
    </Message>

    <div class="archive-report-panel__field">
      <label :for="reasonInputId">問題類型 <span aria-hidden="true">*</span></label>
      <Select
        :inputId="reasonInputId"
        v-model="reason"
        :options="ARCHIVE_REPORT_REASONS"
        optionLabel="label"
        optionValue="value"
        placeholder="請選擇問題類型"
        :disabled="submitting || !authenticated"
        fluid
      />
    </div>

    <div class="archive-report-panel__field archive-report-panel__field--grow">
      <label :for="messageInputId">
        補充說明
        <span v-if="isOtherReason" class="archive-report-panel__required">（選擇其他時必填）</span>
      </label>
      <Textarea
        :id="messageInputId"
        v-model="customMessage"
        rows="7"
        :maxlength="ARCHIVE_REPORT_CUSTOM_MESSAGE_MAX_LENGTH"
        placeholder="請補充發生情況、正確資訊或其他有助查核的內容"
        :disabled="submitting || !authenticated"
        fluid
      />
      <small
        class="archive-report-panel__counter"
        :class="{ 'is-invalid': isOtherReason && !customMessage.trim() }"
      >
        {{ customMessage.length }}/{{ ARCHIVE_REPORT_CUSTOM_MESSAGE_MAX_LENGTH }}
      </small>
    </div>

    <footer class="archive-report-panel__actions">
      <Button
        type="button"
        label="返回留言區"
        icon="pi pi-comments"
        severity="secondary"
        outlined
        :disabled="submitting"
        @click="$emit('back')"
      />
      <Button
        type="submit"
        label="送出回報"
        icon="pi pi-send"
        :loading="submitting"
        :disabled="!canSubmit"
      />
    </footer>
  </form>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useToast } from 'primevue/usetoast'
import { reportService } from '@/api'
import { isAuthenticated } from '@/utils/auth'
import {
  ARCHIVE_REPORT_CUSTOM_MESSAGE_MAX_LENGTH,
  ARCHIVE_REPORT_OTHER_REASON,
  ARCHIVE_REPORT_REASONS,
  buildArchiveReportPayload,
} from '@/constants/archiveReport'

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  archiveId: { type: [Number, String], required: true },
  courseName: { type: String, default: '' },
  title: { type: String, default: '' },
  academicYear: { type: [Number, String], default: '' },
  professorName: { type: String, default: '' },
})

const emit = defineEmits(['back', 'submitted'])
const toast = useToast()
const reason = ref(null)
const customMessage = ref('')
const submitting = ref(false)
const authenticated = computed(() => isAuthenticated())
const isOtherReason = computed(() => reason.value === ARCHIVE_REPORT_OTHER_REASON)
const sourceMeta = computed(() =>
  [props.academicYear ? `${props.academicYear} 學年度` : '', props.professorName]
    .filter(Boolean)
    .join(' · ')
)
const reasonInputId = computed(() => `archive-report-reason-${props.courseId}-${props.archiveId}`)
const messageInputId = computed(() => `archive-report-message-${props.courseId}-${props.archiveId}`)
const canSubmit = computed(
  () =>
    authenticated.value &&
    Boolean(reason.value) &&
    (!isOtherReason.value || Boolean(customMessage.value.trim())) &&
    customMessage.value.length <= ARCHIVE_REPORT_CUSTOM_MESSAGE_MAX_LENGTH &&
    !submitting.value
)

watch(
  () => props.archiveId,
  () => {
    reason.value = null
    customMessage.value = ''
    submitting.value = false
  }
)

async function submitReport() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const { data } = await reportService.createArchiveReport(
      props.courseId,
      props.archiveId,
      buildArchiveReportPayload(reason.value, customMessage.value)
    )
    toast.add({
      severity: 'success',
      summary: '考古回報已送出',
      detail: `回報編號 #${data.id}，目前為待審核`,
      life: 4000,
    })
    reason.value = null
    customMessage.value = ''
    emit('submitted', data)
    emit('back')
  } catch (error) {
    const duplicated = error?.response?.status === 409
    toast.add({
      severity: duplicated ? 'warn' : 'error',
      summary: duplicated ? '已有待審核回報' : '送出失敗',
      detail: duplicated ? '你已針對相同問題送出回報' : '考古回報未送出，請稍後再試',
      life: 4000,
    })
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.archive-report-panel {
  display: flex;
  min-height: 0;
  height: 100%;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  overflow: auto;
  border: 1px solid var(--surface-border);
  border-radius: var(--content-border-radius, 6px);
  background: var(--surface-card);
  color: var(--text-color);
}

.archive-report-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.archive-report-panel__header h3,
.archive-report-panel__header p {
  margin: 0;
}

.archive-report-panel__header h3 {
  font-size: 1.125rem;
}

.archive-report-panel__header p,
.archive-report-panel__source small {
  margin-top: 0.25rem;
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.archive-report-panel__header > i {
  color: var(--p-orange-500);
  font-size: 1.4rem;
}

.archive-report-panel__source {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  background: var(--surface-ground);
}

.archive-report-panel__source span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archive-report-panel__field {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.archive-report-panel__field--grow {
  flex: 1 1 auto;
}

.archive-report-panel__field label {
  font-weight: 600;
}

.archive-report-panel__required,
.archive-report-panel__counter.is-invalid {
  color: var(--p-red-500);
}

.archive-report-panel__counter {
  align-self: flex-end;
  color: var(--text-secondary);
}

.archive-report-panel__actions {
  position: sticky;
  bottom: -1rem;
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: auto;
  padding: 0.75rem 0 0;
  background: var(--surface-card);
}

@media (max-width: 480px) {
  .archive-report-panel {
    padding: 0.75rem;
  }

  .archive-report-panel__actions {
    flex-direction: column-reverse;
  }

  .archive-report-panel__actions :deep(.p-button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
