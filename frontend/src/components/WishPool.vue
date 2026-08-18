<template>
  <section class="wish-pool" aria-labelledby="wish-pool-title">
    <header class="wish-header">
      <div>
        <h2 id="wish-pool-title">{{ $t('考古許願池') }}</h2>
        <p>{{ $t('點選許願可按愛心、回報問題或協助上傳。') }}</p>
      </div>
      <Button :label="$t('新增許願')" icon="pi pi-plus" @click="emit('add-wish')" />
    </header>
    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <ProgressSpinner v-if="loading" class="wish-spinner" />
    <div v-else class="wish-cloud" role="list" :aria-label="$t('考古許願池')">
      <button
        v-for="wish in wishes"
        :key="wish.id"
        type="button"
        role="listitem"
        class="wish-word"
        :class="{ fulfilled: wish.fulfilled }"
        :style="{ fontSize: fontSize(wish.heart_count) }"
        @click="selected = wish"
      >
        {{ wish.title }}
        <small>♥ {{ wish.heart_count }}</small>
        <span v-if="wish.fulfilled" class="fulfilled-label">{{ $t('已實現') }}</span>
      </button>
    </div>
    <Button
      v-if="wishes.length < total"
      class="load-more"
      :label="$t('載入更多')"
      text
      @click="loadMore"
    />

    <Dialog
      :visible="Boolean(selected)"
      @update:visible="!$event && closeWishDetail()"
      modal
      :draggable="false"
      :header="selected?.title"
      :style="{ width: '520px', maxWidth: '94vw' }"
    >
      <div v-if="selected" class="wish-detail">
        <p>
          {{ selected.subject }} · {{ selected.professor }} · {{ selected.academic_year }} ·
          {{ selected.name }}
        </p>
        <Tag v-if="selected.fulfilled" severity="success">{{ $t('已實現') }}</Tag>
        <div class="dialog-actions wrap">
          <Button
            :label="$t('愛心 {count}', { count: selected.heart_count })"
            :icon="selected.hearted_by_me ? 'pi pi-heart-fill' : 'pi pi-heart'"
            @click="toggleHeart"
          />
          <Button
            :label="$t('回報')"
            icon="pi pi-flag"
            severity="secondary"
            outlined
            @click="toggleReport"
          />
          <Button
            :label="$t('協助上傳')"
            icon="pi pi-cloud-upload"
            severity="success"
            @click="$emit('help-upload', selected)"
          />
          <Button
            v-if="isAdmin"
            :label="$t('永久刪除')"
            icon="pi pi-trash"
            severity="danger"
            outlined
            :loading="deleting"
            :disabled="deleting"
            @click="requestRemoveWish"
          />
        </div>
        <InlineCommentReport
          v-if="reportVisible"
          :message="reportTarget"
          targetType="wish"
          :reason="report.reason"
          :loading="reportSubmitting"
          @update:reason="report.reason = $event"
          @cancel="closeReport"
          @submit="submitReport"
        />
      </div>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { wishService } from '@/api'
import { getCurrentUser } from '@/utils/auth'
import InlineCommentReport from '@/components/InlineCommentReport.vue'

const emit = defineEmits(['add-wish', 'help-upload'])
const { t } = useI18n()
const confirm = useConfirm()
const toast = useToast()
const isAdmin = Boolean(getCurrentUser()?.is_admin)
const wishes = ref([]),
  total = ref(0),
  loading = ref(true),
  error = ref('')
const selected = ref(null)
const reportVisible = ref(false)
const reportSubmitting = ref(false),
  deleting = ref(false)
const report = reactive({ reason: null })
const reportTarget = computed(() => ({
  id: selected.value?.id,
  user_name: selected.value?.creator_name || t('許願者'),
  created_at: selected.value?.created_at,
  content: selected.value
    ? `${selected.value.title} · ${selected.value.subject} · ${selected.value.professor} · ${selected.value.academic_year} · ${selected.value.name}`
    : '',
  is_deleted: false,
}))
const fontSize = (count) => `${Math.min(2.2, 0.95 + Math.log2(Number(count || 0) + 1) * 0.24)}rem`
async function load(reset = true) {
  loading.value = reset
  error.value = ''
  try {
    const { data } = await wishService.list({ limit: 60, offset: reset ? 0 : wishes.value.length })
    wishes.value = reset ? data.items : [...wishes.value, ...data.items]
    total.value = data.total
  } catch {
    error.value = t('許願池載入失敗，請稍後再試。')
  } finally {
    loading.value = false
  }
}
const loadMore = () => load(false)
async function toggleHeart() {
  const { data } = await wishService.toggleHeart(selected.value.id)
  Object.assign(selected.value, { hearted_by_me: data.hearted, heart_count: data.heart_count })
  const item = wishes.value.find((wish) => wish.id === selected.value.id)
  if (item) Object.assign(item, selected.value)
}
function toggleReport() {
  if (reportVisible.value) return closeReport()
  report.reason = null
  reportVisible.value = true
}
function closeReport() {
  reportVisible.value = false
  report.reason = null
}
function closeWishDetail() {
  closeReport()
  selected.value = null
}
async function submitReport(payload) {
  if (!selected.value || reportSubmitting.value) return
  reportSubmitting.value = true
  try {
    await wishService.report(selected.value.id, {
      report_reason: payload.report_reason,
      custom_message: null,
    })
    toast.add({
      severity: 'success',
      summary: t('回報已送出'),
      detail: t('許願回報已送出，請等待管理員審核'),
      life: 3500,
    })
    closeReport()
  } catch (requestError) {
    const isDuplicate = requestError?.response?.status === 409
    toast.add({
      severity: isDuplicate ? 'warn' : 'error',
      summary: isDuplicate ? t('已有待審核回報') : t('回報送出失敗'),
      detail: isDuplicate ? t('這筆許願已有你的回報') : t('請稍後再試'),
      life: 3500,
    })
  } finally {
    reportSubmitting.value = false
  }
}
function requestRemoveWish() {
  if (!selected.value || deleting.value) return
  confirm.require({
    header: t('永久刪除這筆許願？'),
    message: t('這筆許願將永久刪除，無法復原，也不會進入垃圾桶。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('永久刪除'),
    acceptClass: 'p-button-danger',
    defaultFocus: 'reject',
    accept: removeWish,
  })
}
async function removeWish() {
  if (!selected.value || deleting.value) return
  const wishId = selected.value.id
  deleting.value = true
  try {
    await wishService.remove(wishId)
    wishes.value = wishes.value.filter((wish) => wish.id !== wishId)
    total.value = Math.max(0, total.value - 1)
    selected.value = null
    closeReport()
    toast.add({
      severity: 'success',
      summary: t('許願已永久刪除'),
      detail: t('這筆許願已永久移除，未進入垃圾桶。'),
      life: 3000,
    })
  } catch {
    toast.add({
      severity: 'error',
      summary: t('永久刪除失敗'),
      detail: t('許願未變更，請稍後再試。'),
      life: 3500,
    })
  } finally {
    deleting.value = false
  }
}
onMounted(() => load())
</script>

<style scoped>
.wish-pool {
  box-sizing: border-box;
  width: 100%;
  padding: 1.5rem;
  margin: 0;
  container-type: inline-size;
}
.wish-header,
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.wish-header {
  width: 100%;
  text-align: left;
}
.wish-header > div {
  min-width: 0;
}
.wish-header h2,
.wish-header p {
  margin: 0.2rem 0;
  text-align: left;
}
.wish-header :deep(.p-button) {
  flex: 0 0 auto;
  min-height: 2.75rem;
  white-space: nowrap;
}
.wish-cloud {
  display: flex;
  max-width: 1100px;
  margin: 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.6rem 1.1rem;
  padding: 2rem 0.5rem;
}
.wish-word {
  border: 0;
  background: transparent;
  color: var(--text-color);
  cursor: pointer;
  padding: 0.35rem;
  border-radius: 0.5rem;
}
.wish-word:hover,
.wish-word:focus-visible {
  background: var(--surface-hover);
  outline: 2px solid var(--primary-color);
}
.wish-word small,
.fulfilled-label {
  font-size: 0.7rem;
  margin-left: 0.3rem;
}
.fulfilled-label {
  font-weight: 700;
}
.wish-word.fulfilled {
  color: var(--green-600);
  font-weight: 600;
}
.wish-word.fulfilled:hover,
.wish-word.fulfilled:focus-visible {
  color: var(--green-500);
}
.wish-spinner,
.load-more {
  display: block;
  margin: 2rem auto;
}
.wish-detail {
  display: grid;
  gap: 0.8rem;
}
.dialog-actions {
  justify-content: flex-end;
  margin-top: 0.8rem;
}
.wrap {
  flex-wrap: wrap;
  justify-content: flex-start;
}
@container (max-width:720px) {
  .wish-header {
    align-items: stretch;
    flex-direction: column;
  }
  .wish-header :deep(.p-button) {
    width: 100%;
    justify-content: center;
  }
}
</style>
