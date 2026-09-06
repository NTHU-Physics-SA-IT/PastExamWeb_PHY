<template>
  <main
    class="about-us-page"
    :class="{ 'about-us-page--christmas': effectiveTheme === 'christmas' }"
  >
    <section class="about-us-shell">
      <header class="about-us-header">
        <div>
          <h1>{{ $t('關於我們') }}</h1>
          <p>{{ $t('認識清大物理考古題網站與維護團隊。') }}</p>
        </div>
        <div v-if="isAdmin || entries.length > 1" class="about-us-header-actions">
          <Button
            v-if="isAdmin"
            :label="$t('新增關於我們內容')"
            icon="pi pi-plus"
            severity="success"
            class="about-us-add-action review-action-republish"
            @click="openCreate"
          />
          <nav
            v-if="entries.length > 1"
            class="about-us-pagination"
            :aria-label="$t('瀏覽關於我們內容')"
          >
            <Button
              v-for="(entry, index) in entries"
              :key="entry.id"
              :label="String(index + 1)"
              class="about-us-pagination-page"
              :severity="index === currentEntryIndex ? 'primary' : 'secondary'"
              :outlined="index !== currentEntryIndex"
              size="small"
              :aria-label="
                $t('第 {current} / {total} 則', {
                  current: index + 1,
                  total: entries.length,
                })
              "
              :aria-current="index === currentEntryIndex ? 'page' : undefined"
              @click="selectEntry(index)"
            />
          </nav>
        </div>
      </header>

      <div v-if="loading" class="about-us-state" role="status">
        <ProgressSpinner strokeWidth="4" />
        <span>{{ $t('正在載入關於我們內容') }}</span>
      </div>
      <Message v-else-if="loadError" severity="error" :closable="false">
        <div class="flex align-items-center gap-3 flex-wrap">
          <span>{{ loadError }}</span>
          <Button :label="$t('重試')" size="small" outlined @click="loadEntries" />
        </div>
      </Message>
      <Card v-else-if="entries.length === 0" class="about-us-empty">
        <template #content>
          <i class="pi pi-info-circle" aria-hidden="true"></i>
          <p>{{ $t('目前尚無關於我們內容') }}</p>
        </template>
      </Card>
      <div v-else class="about-us-list">
        <Card v-if="currentEntry" :key="currentEntry.id" class="about-us-entry">
          <template #content>
            <div v-if="isAdmin" class="about-us-entry-actions">
              <div class="about-us-order-actions" :aria-label="$t('關於我們內容順序')">
                <span class="about-us-control-label">{{ $t('排序') }}</span>
                <Button
                  icon="pi pi-arrow-left"
                  severity="secondary"
                  size="small"
                  text
                  rounded
                  :disabled="!canMoveEntry(currentEntry, -1) || orderSaving"
                  :aria-label="$t('移到前面')"
                  :title="$t('移到前面')"
                  @click="moveEntry(currentEntry, -1)"
                />
                <Button
                  icon="pi pi-arrow-right"
                  severity="secondary"
                  size="small"
                  text
                  rounded
                  :disabled="!canMoveEntry(currentEntry, 1) || orderSaving"
                  :aria-label="$t('移到後面')"
                  :title="$t('移到後面')"
                  @click="moveEntry(currentEntry, 1)"
                />
              </div>
              <div class="about-us-edit-actions">
                <Button
                  :label="$t('編輯')"
                  icon="pi pi-pencil"
                  size="small"
                  outlined
                  class="about-us-edit-action review-action-preview"
                  @click="openEdit(currentEntry)"
                />
                <Button
                  :label="$t('永久刪除')"
                  icon="pi pi-trash"
                  severity="danger"
                  size="small"
                  outlined
                  class="about-us-delete-action review-action-delete"
                  @click="requestDelete(currentEntry)"
                />
              </div>
            </div>
            <div
              class="markdown-content"
              v-html="renderMarkdown(localizedField(currentEntry, 'body'))"
            ></div>
          </template>
        </Card>
      </div>
    </section>

    <Dialog
      v-model:visible="dialogVisible"
      modal
      :draggable="false"
      :header="editingEntry ? $t('編輯關於我們內容') : $t('新增關於我們內容')"
      :style="{ width: '720px', maxWidth: '94vw' }"
      :class="{ 'about-us-editor-dialog--christmas': effectiveTheme === 'christmas' }"
    >
      <form class="about-us-form" @submit.prevent="saveEntry">
        <div class="field">
          <label for="about-us-body">{{ $t('Markdown 內容') }}</label>
          <Textarea
            id="about-us-body"
            v-model="form.body"
            class="w-full"
            rows="10"
            autoResize
            :class="{ 'p-invalid': errors.body }"
            :aria-invalid="Boolean(errors.body)"
            :aria-describedby="
              errors.body ? 'about-us-body-error about-us-image-help' : 'about-us-image-help'
            "
          />
          <small v-if="errors.body" id="about-us-body-error" class="p-error" role="alert">
            {{ errors.body }}
          </small>
        </div>
        <div class="field">
          <label for="about-us-body-en">{{ $t('英文 Markdown 內容') }}</label>
          <Textarea
            id="about-us-body-en"
            v-model="form.body_en"
            class="w-full"
            rows="10"
            autoResize
            :class="{ 'p-invalid': errors.body_en }"
            :aria-invalid="Boolean(errors.body_en)"
            :aria-describedby="
              errors.body_en ? 'about-us-body-en-error about-us-image-help' : 'about-us-image-help'
            "
          />
          <small id="about-us-image-help" class="about-us-editor-hint">{{
            $t('aboutUsImageHelp')
          }}</small>
          <small v-if="errors.body_en" id="about-us-body-en-error" class="p-error" role="alert">{{
            errors.body_en
          }}</small>
        </div>
        <section v-if="form.body.trim()" class="about-us-preview" :aria-label="$t('Markdown 預覽')">
          <h3>{{ $t('中文預覽') }}</h3>
          <div class="markdown-content" v-html="renderMarkdown(form.body)"></div>
        </section>
        <section
          v-if="form.body_en.trim()"
          class="about-us-preview"
          :aria-label="$t('英文 Markdown 預覽')"
        >
          <h3>{{ $t('英文預覽') }}</h3>
          <div class="markdown-content" v-html="renderMarkdown(form.body_en)"></div>
        </section>
        <Message v-if="saveError" severity="error" :closable="false">{{ saveError }}</Message>
        <div class="about-us-form-actions">
          <Button
            type="button"
            :label="$t('取消')"
            severity="secondary"
            outlined
            class="about-us-dialog-cancel-action review-action-preview"
            @click="dialogVisible = false"
          />
          <Button
            type="submit"
            :label="$t('儲存')"
            icon="pi pi-check"
            severity="success"
            class="about-us-dialog-save-action review-action-republish"
            :loading="saving"
          />
        </div>
      </form>
    </Dialog>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { aboutUsService } from '@/api'
import { getCurrentUser } from '@/utils/auth.js'
import { renderMarkdown } from '@/utils/markdown.js'
import { useTheme } from '@/utils/useTheme'

const { t, locale } = useI18n()
const { effectiveTheme } = useTheme()
const isAdmin = Boolean(getCurrentUser()?.is_admin)
const entries = ref([])
const currentEntryIndex = ref(0)
const currentEntry = computed(() => entries.value[currentEntryIndex.value] || null)
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const orderSaving = ref(false)
const saveError = ref('')
const dialogVisible = ref(false)
const editingEntry = ref(null)
const form = reactive({ body: '', body_en: '' })
const errors = reactive({ body: '', body_en: '' })

async function loadEntries() {
  loading.value = true
  loadError.value = ''
  try {
    const currentEntryId = currentEntry.value?.id
    const response = await aboutUsService.list()
    entries.value = Array.isArray(response.data) ? response.data : []
    const retainedIndex = entries.value.findIndex((entry) => entry.id === currentEntryId)
    currentEntryIndex.value =
      retainedIndex >= 0
        ? retainedIndex
        : Math.min(currentEntryIndex.value, Math.max(entries.value.length - 1, 0))
  } catch {
    loadError.value = t('關於我們內容載入失敗，請稍後再試。')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.body = ''
  form.body_en = ''
  errors.body = ''
  errors.body_en = ''
  saveError.value = ''
}

function openCreate() {
  editingEntry.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(entry) {
  editingEntry.value = entry
  resetForm()
  form.body = entry.body
  form.body_en = entry.body_en || ''
  dialogVisible.value = true
}

function validate() {
  errors.body = form.body.trim() ? '' : t('內容是必填欄位')
  errors.body_en = form.body_en.trim() ? '' : t('英文內容是必填欄位')
  return !errors.body && !errors.body_en
}

async function saveEntry() {
  if (!validate() || saving.value) return
  saving.value = true
  saveError.value = ''
  const payload = {
    body: form.body.trim(),
    body_en: form.body_en.trim(),
  }
  try {
    if (editingEntry.value) {
      await aboutUsService.update(editingEntry.value.id, payload)
    } else {
      await aboutUsService.create(payload)
    }
    dialogVisible.value = false
    await loadEntries()
  } catch {
    saveError.value = t('關於我們內容儲存失敗，請稍後再試。')
  } finally {
    saving.value = false
  }
}

function localizedField(entry, field) {
  if (locale.value.toLowerCase().startsWith('en'))
    return entry[`${field}_en`]?.trim() || entry[field]
  return entry[field]
}

function canMoveEntry(entry, direction) {
  const index = entries.value.findIndex((item) => item.id === entry.id)
  const target = index + direction
  return index >= 0 && target >= 0 && target < entries.value.length
}

function selectEntry(index) {
  if (index >= 0 && index < entries.value.length) currentEntryIndex.value = index
}

async function moveEntry(entry, direction) {
  if (!canMoveEntry(entry, direction) || orderSaving.value) return
  const index = entries.value.findIndex((item) => item.id === entry.id)
  const reordered = [...entries.value]
  const [moved] = reordered.splice(index, 1)
  reordered.splice(index + direction, 0, moved)
  orderSaving.value = true
  loadError.value = ''
  try {
    const response = await aboutUsService.reorder(reordered.map((item) => item.id))
    entries.value = Array.isArray(response.data) ? response.data : reordered
    currentEntryIndex.value = entries.value.findIndex((item) => item.id === entry.id)
  } catch {
    loadError.value = t('關於我們內容順序儲存失敗，請稍後再試。')
  } finally {
    orderSaving.value = false
  }
}

async function deleteEntry(entry) {
  try {
    await aboutUsService.remove(entry.id)
    entries.value = entries.value.filter((item) => item.id !== entry.id)
    currentEntryIndex.value = Math.min(
      currentEntryIndex.value,
      Math.max(entries.value.length - 1, 0)
    )
  } catch {
    loadError.value = t('關於我們內容永久刪除失敗，請稍後再試。')
  }
}

function requestDelete(entry) {
  if (window.confirm(t('確定要永久刪除這筆關於我們內容嗎？此動作無法復原。'))) {
    void deleteEntry(entry)
  }
}

onMounted(loadEntries)
</script>

<style scoped>
.about-us-page {
  min-height: calc(100vh - 5rem);
  padding: 2rem 1rem 4rem;
}

.about-us-shell {
  width: min(960px, 100%);
  margin: 0 auto;
}

.about-us-header,
.about-us-form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.about-us-header {
  margin-bottom: 1.5rem;
}

.about-us-header-actions {
  display: flex;
  flex: 0 1 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem 0.75rem;
  min-width: 0;
}

.about-us-header h1,
.about-us-preview h3 {
  margin: 0;
}

.about-us-header p {
  margin: 0.4rem 0 0;
  color: var(--text-secondary);
}

.about-us-list,
.about-us-form {
  display: grid;
  gap: 1rem;
}

.about-us-entry-actions,
.about-us-order-actions,
.about-us-edit-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.about-us-entry-actions {
  justify-content: space-between;
  margin-bottom: 0.75rem;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid var(--border-color);
}

.about-us-control-label {
  color: var(--text-secondary);
  font-size: 0.9rem;
  font-weight: 650;
}

.about-us-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.about-us-pagination-page {
  width: 2.25rem;
  min-width: 2.25rem;
  height: 2.25rem;
  padding: 0.25rem;
}

.about-us-state,
.about-us-empty :deep(.p-card-content) {
  display: flex;
  min-height: 12rem;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 1rem;
  color: var(--text-secondary);
}

.about-us-entry :deep(.p-card-body),
.about-us-empty :deep(.p-card-body) {
  background: var(--bg-secondary);
}

.about-us-entry :deep(.markdown-content) {
  width: 100%;
  margin-inline: 0 auto;
}

:deep(.markdown-content) {
  color: var(--text-primary);
  line-height: 1.8;
  overflow-wrap: anywhere;
}

:deep(.markdown-content > :first-child) {
  margin-top: 0;
}

:deep(.markdown-content > :last-child) {
  margin-bottom: 0;
}

:deep(.markdown-content h1),
:deep(.markdown-content h2),
:deep(.markdown-content h3) {
  color: var(--text-primary);
  font-weight: 750;
  line-height: 1.25;
  text-wrap: balance;
}

:deep(.markdown-content h1) {
  margin: 0 0 1.35rem;
  font-size: clamp(1.85rem, 4vw, 2.35rem);
}

:deep(.markdown-content h2) {
  margin: 2.25rem 0 0.9rem;
  font-size: clamp(1.4rem, 3vw, 1.7rem);
}

:deep(.markdown-content h3) {
  margin: 1.75rem 0 0.75rem;
  font-size: clamp(1.15rem, 2.4vw, 1.35rem);
}

:deep(.markdown-content p) {
  margin: 0 0 1.1rem;
  text-align: justify;
  text-align-last: left;
  text-justify: auto;
}

:deep(.markdown-content strong) {
  font-weight: 750;
}

:deep(.markdown-content blockquote) {
  margin: 1.5rem 0;
  padding: 0.9rem 1.1rem;
  border: 1px solid var(--border-color);
  border-inline-start-width: 0.22rem;
  border-radius: 0.5rem;
  background: color-mix(in srgb, var(--bg-secondary) 92%, transparent);
  color: var(--text-primary);
}

:deep(.markdown-content blockquote p) {
  margin: 0;
}

:deep(.markdown-content img) {
  display: block;
  width: auto;
  max-width: 100%;
  height: auto;
  margin: 1.25rem auto;
}

:deep(.markdown-content img.about-us-image--align-left) {
  margin-inline: 0 auto;
}

:deep(.markdown-content img.about-us-image--align-center) {
  margin-inline: auto;
}

:deep(.markdown-content img.about-us-image--align-right) {
  margin-inline: auto 0;
}

:deep(.markdown-content::after) {
  display: block;
  clear: both;
  content: '';
}

:deep(.markdown-content img.about-us-image--align-left.about-us-image--wrap) {
  float: left;
  margin: 0.25rem 1rem 0.75rem 0;
}

:deep(.markdown-content img.about-us-image--align-right.about-us-image--wrap) {
  float: right;
  margin: 0.25rem 0 0.75rem 1rem;
}

:deep(.markdown-content h1),
:deep(.markdown-content h2),
:deep(.markdown-content h3),
:deep(.markdown-content hr),
:deep(.markdown-content blockquote) {
  clear: both;
}

:deep(.markdown-content ul),
:deep(.markdown-content ol) {
  margin: 1rem 0 1.25rem;
  padding-inline-start: 1.8rem;
}

:deep(.markdown-content ul) {
  list-style: disc;
}

:deep(.markdown-content ol) {
  list-style: decimal;
}

:deep(.markdown-content ul ul) {
  list-style: circle;
}

:deep(.markdown-content ol ol) {
  list-style: lower-alpha;
}

:deep(.markdown-content li + li) {
  margin-top: 0.45rem;
}

:deep(.markdown-content hr) {
  margin: 2rem 0;
  border: 0;
  border-top: 1px solid var(--border-color);
}

:deep(.markdown-content a) {
  color: var(--title-gradient-start);
  font-weight: 600;
  text-decoration: underline;
  text-decoration-thickness: 0.08em;
  text-underline-offset: 0.18em;
}

:deep(.markdown-content a:hover) {
  color: var(--title-gradient-end);
}

:deep(.markdown-content code) {
  padding: 0.12rem 0.35rem;
  border: 1px solid var(--border-color);
  border-radius: 0.3rem;
  background: var(--code-bg);
  color: var(--code-text);
  font-size: 0.9em;
}

:deep(.markdown-content pre) {
  margin: 1.25rem 0;
  padding: 1rem;
  overflow-x: auto;
  border: 1px solid var(--border-color);
  border-radius: 0.6rem;
  background: var(--code-bg);
  line-height: 1.6;
}

:deep(.markdown-content pre code) {
  padding: 0;
  border: 0;
  background: transparent;
}

:deep(.markdown-content hr + p) {
  color: var(--text-secondary);
  line-height: 1.7;
  text-align: end;
  text-align-last: auto;
}

:deep(.markdown-content hr + p strong),
:deep(.markdown-content hr + p em) {
  display: block;
}

.field {
  display: grid;
  gap: 0.5rem;
}

.about-us-editor-hint {
  color: var(--text-secondary);
  line-height: 1.45;
  white-space: pre-line;
}

.about-us-preview {
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  background: var(--bg-secondary);
}

.about-us-page--christmas {
  color: #f8f2e8;
}

.about-us-page--christmas .about-us-header h1,
.about-us-page--christmas .about-us-header p,
.about-us-page--christmas .about-us-control-label,
.about-us-page--christmas .about-us-state,
.about-us-page--christmas .about-us-empty :deep(.p-card-content),
.about-us-page--christmas :deep(.markdown-content),
.about-us-page--christmas :deep(.markdown-content h1),
.about-us-page--christmas :deep(.markdown-content h2),
.about-us-page--christmas :deep(.markdown-content h3) {
  color: #f8f2e8;
}

.about-us-page--christmas .about-us-header p,
.about-us-page--christmas .about-us-control-label {
  color: #c5d5d2;
}

.about-us-page--christmas .about-us-entry,
.about-us-page--christmas .about-us-empty,
.about-us-page--christmas .about-us-entry :deep(.p-card),
.about-us-page--christmas .about-us-empty :deep(.p-card),
.about-us-page--christmas .about-us-entry :deep(.p-card-body),
.about-us-page--christmas .about-us-empty :deep(.p-card-body),
.about-us-page--christmas .about-us-entry :deep(.p-card-content),
.about-us-page--christmas .about-us-empty :deep(.p-card-content) {
  border-color: rgba(222, 199, 142, 0.38);
  background: transparent;
  box-shadow: none;
}

.about-us-page--christmas .about-us-empty :deep(.p-card-content) {
  min-height: 12rem;
  border: 1px solid rgba(222, 199, 142, 0.38);
  border-radius: 0.75rem;
  background: rgba(41, 63, 82, 0.32);
}

.about-us-page--christmas .about-us-entry :deep(.p-card-body) {
  border: 1px solid rgba(222, 199, 142, 0.38);
  border-radius: 0.75rem;
  background: rgba(41, 63, 82, 0.36);
}

.about-us-page--christmas .about-us-entry-actions,
.about-us-page--christmas :deep(.markdown-content hr) {
  border-color: rgba(222, 199, 142, 0.38);
}

.about-us-page--christmas :deep(.review-action-preview.p-button) {
  border-color: rgba(225, 246, 252, 0.96);
  background: #d7edf5;
  color: #245368;
}

.about-us-page--christmas :deep(.review-action-republish.p-button) {
  border-color: rgba(127, 188, 145, 0.82);
  background: linear-gradient(180deg, #3d8a64 0%, #2d6c52 100%);
  color: #f5fff7;
}

.about-us-page--christmas :deep(.review-action-delete.p-button) {
  border-color: rgba(244, 141, 151, 0.82);
  background: rgba(116, 38, 50, 0.82);
  color: #fff2f3;
}

.about-us-page--christmas :deep(.review-action-preview.p-button:hover),
.about-us-page--christmas :deep(.review-action-republish.p-button:hover),
.about-us-page--christmas :deep(.review-action-delete.p-button:hover) {
  box-shadow:
    0 0 0.34rem rgba(255, 218, 94, 0.58),
    0 0 0.72rem rgba(255, 201, 59, 0.34);
  text-shadow: 0 0 0.2rem rgba(255, 209, 72, 0.62);
}

@media (max-width: 640px) {
  .about-us-header,
  .about-us-entry-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .about-us-header-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .about-us-edit-actions {
    flex-wrap: wrap;
  }

  .about-us-order-actions {
    flex-wrap: wrap;
  }

  :deep(.markdown-content) {
    line-height: 1.72;
  }

  :deep(.markdown-content blockquote) {
    padding: 0.8rem 0.9rem;
  }
}
</style>

<style>
html[data-effective-theme='christmas'] body .p-dialog.about-us-editor-dialog--christmas {
  border: 1px solid rgba(222, 199, 142, 0.46);
  background: #3e5f72;
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas .p-dialog-header {
  border-bottom: 1px solid rgba(222, 199, 142, 0.38);
  background: #293f52;
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas .p-dialog-content,
html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas .p-dialog-footer {
  background: #3e5f72;
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .p-dialog-close-button {
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas label,
html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas h3 {
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .about-us-editor-hint {
  color: #c5d5d2;
}

html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas .p-textarea {
  border-color: rgba(222, 199, 142, 0.42);
  background: #293f52;
  color: #f8f2e8;
  caret-color: #f8f2e8;
}

html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas .p-textarea:focus {
  border-color: #f0c96f;
  box-shadow: 0 0 0 0.16rem rgba(240, 201, 111, 0.22);
}

html[data-effective-theme='christmas'] body .about-us-editor-dialog--christmas .about-us-preview {
  border-color: rgba(222, 199, 142, 0.38);
  background: rgba(41, 63, 82, 0.58);
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .about-us-preview
  .markdown-content {
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .about-us-preview
  .markdown-content
  :is(h1, h2, h3, h4, h5, h6, p, li, strong, em, blockquote, pre, code) {
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .about-us-preview
  .markdown-content
  :is(blockquote, pre, code) {
  border-color: rgba(222, 199, 142, 0.38);
  background: rgba(30, 51, 68, 0.74);
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .about-us-preview
  .markdown-content
  a {
  color: #bfe9ff;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .about-us-preview
  .markdown-content
  hr {
  border-top-color: rgba(222, 199, 142, 0.45);
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .review-action-preview.p-button {
  border-color: rgba(225, 246, 252, 0.96);
  background: #d7edf5;
  color: #245368;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .review-action-republish.p-button {
  border-color: rgba(127, 188, 145, 0.82);
  background: linear-gradient(180deg, #3d8a64 0%, #2d6c52 100%);
  color: #f5fff7;
}

html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .review-action-preview.p-button:hover,
html[data-effective-theme='christmas']
  body
  .about-us-editor-dialog--christmas
  .review-action-republish.p-button:hover {
  box-shadow:
    0 0 0.34rem rgba(255, 218, 94, 0.58),
    0 0 0.72rem rgba(255, 201, 59, 0.34);
  text-shadow: 0 0 0.2rem rgba(255, 209, 72, 0.62);
}
</style>
