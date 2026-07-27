<template>
  <section class="archive-report-panel" aria-labelledby="archive-report-title">
    <header class="archive-report-panel__header">
      <Button
        icon="pi pi-arrow-left"
        severity="secondary"
        text
        rounded
        aria-label="返回留言區"
        title="返回留言區"
        :disabled="submitting"
        @click="$emit('back')"
      />
      <div>
        <h3 id="archive-report-title">回報考古題</h3>
        <p>{{ courseName || '課程' }} · {{ archiveName || `考古題 #${archiveId}` }}</p>
      </div>
    </header>

    <Message v-if="pendingReport" severity="warn" :closable="false">
      此考古題已有待審核回報，請等待管理員處理。
    </Message>
    <Message v-else-if="errorMessage" severity="error" :closable="false">
      {{ errorMessage }}
    </Message>

    <form class="archive-report-panel__form" @submit.prevent="submit">
      <div class="archive-report-panel__field">
        <label for="archive-report-reason">回報原因<span aria-hidden="true"> *</span></label>
        <Select
          inputId="archive-report-reason"
          v-model="reason"
          :options="ARCHIVE_REPORT_REASONS"
          optionLabel="label"
          optionValue="value"
          placeholder="請選擇原因"
          :disabled="submitting || Boolean(pendingReport)"
          @change="validate"
        />
        <small v-if="errors.reason" class="archive-report-panel__error">{{ errors.reason }}</small>
      </div>

      <div class="archive-report-panel__field">
        <label for="archive-report-detail">
          補充說明
          <span v-if="reason === ARCHIVE_REPORT_OTHER_REASON" aria-hidden="true"> *</span>
        </label>
        <Textarea
          id="archive-report-detail"
          v-model="detail"
          rows="6"
          :maxlength="ARCHIVE_REPORT_DETAIL_MAX_LENGTH"
          placeholder="請補充檔案頁面、資訊落差或其他有助於審核的內容"
          :disabled="submitting || Boolean(pendingReport)"
          @blur="validate"
        />
        <div class="archive-report-panel__field-meta">
          <small v-if="errors.detail" class="archive-report-panel__error">{{
            errors.detail
          }}</small>
          <small
            :class="{
              'archive-report-panel__count--limit':
                detail.length >= ARCHIVE_REPORT_DETAIL_MAX_LENGTH,
            }"
          >
            {{ detail.length }}/{{ ARCHIVE_REPORT_DETAIL_MAX_LENGTH }}
          </small>
        </div>
      </div>

      <div class="archive-report-panel__actions">
        <Button
          type="button"
          label="返回留言區"
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
          :disabled="submitting || Boolean(pendingReport)"
        />
      </div>
    </form>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useToast } from 'primevue/usetoast'
import { reportService } from '@/api'
import { getCurrentUser } from '@/utils/auth'
import {
  ARCHIVE_REPORT_DETAIL_MAX_LENGTH,
  ARCHIVE_REPORT_OTHER_REASON,
  ARCHIVE_REPORT_REASONS,
} from '@/constants/archiveReport'

const props = defineProps({
  courseId: { type: [Number, String], required: true },
  archiveId: { type: [Number, String], required: true },
  courseName: { type: String, default: '' },
  archiveName: { type: String, default: '' },
})

const emit = defineEmits(['back', 'submitted'])
const toast = useToast()
const reason = ref(null)
const detail = ref('')
const submitting = ref(false)
const pendingReport = ref(null)
const errorMessage = ref('')
const errors = reactive({ reason: '', detail: '' })

function validate() {
  errors.reason = reason.value ? '' : '請選擇回報原因'
  const normalizedDetail = detail.value.trim()
  errors.detail =
    reason.value === ARCHIVE_REPORT_OTHER_REASON && !normalizedDetail
      ? '選擇「其他問題」時必須填寫補充說明'
      : ''
  return !errors.reason && !errors.detail
}

async function loadPendingReport() {
  if (!getCurrentUser()) return
  try {
    const { data } = await reportService.getPendingArchiveReport(props.courseId, props.archiveId)
    pendingReport.value = data
  } catch (error) {
    if (error?.response?.status !== 404) {
      errorMessage.value = '無法確認既有回報狀態，仍可嘗試送出。'
    }
  }
}

async function submit() {
  errorMessage.value = ''
  if (!getCurrentUser()) {
    errorMessage.value = '請先登入後再送出考古題回報。'
    return
  }
  if (!validate() || submitting.value || pendingReport.value) return

  submitting.value = true
  try {
    const { data } = await reportService.createArchiveReport(props.courseId, props.archiveId, {
      report_reason: reason.value,
      supplementary_detail: detail.value.trim() || null,
    })
    pendingReport.value = data
    toast.add({
      severity: 'success',
      summary: '考古題回報已送出',
      detail: '管理員審核完成後會透過個人通知告知結果。',
      life: 4000,
    })
    emit('submitted', data)
  } catch (error) {
    if (error?.response?.status === 409) {
      errorMessage.value = '此考古題已有待審核回報。'
      pendingReport.value = { conflict: true }
    } else if (error?.response?.status === 401) {
      errorMessage.value = '登入狀態已失效，請重新登入後再試。'
    } else {
      errorMessage.value = '回報送出失敗，請稍後再試；目前輸入已保留。'
    }
  } finally {
    submitting.value = false
  }
}

onMounted(loadPendingReport)
</script>

<style scoped>
.archive-report-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  overflow-y: auto;
  color: var(--text-color);
  background: var(--surface-card);
}

.archive-report-panel__header {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}

.archive-report-panel__header h3,
.archive-report-panel__header p {
  margin: 0;
}

.archive-report-panel__header h3 {
  font-size: var(--app-font-size-lg);
}

.archive-report-panel__header p {
  margin-top: 0.25rem;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
}

.archive-report-panel__form,
.archive-report-panel__field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.archive-report-panel__form {
  flex: 1;
  gap: 1rem;
}

.archive-report-panel__field label {
  font-weight: 650;
}

.archive-report-panel__field :deep(.p-select),
.archive-report-panel__field :deep(.p-textarea) {
  width: 100%;
  font-size: var(--app-control-font-size);
}

.archive-report-panel__field-meta,
.archive-report-panel__actions {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
}

.archive-report-panel__error,
.archive-report-panel__count--limit {
  color: var(--p-red-500);
}

.archive-report-panel__actions {
  margin-top: auto;
  justify-content: flex-end;
  flex-wrap: wrap;
}

@media (max-width: 480px) {
  .archive-report-panel {
    padding: 0.75rem;
  }

  .archive-report-panel__actions :deep(.p-button) {
    flex: 1 1 10rem;
  }
}
</style>
