<template>
  <main class="about-us-page">
    <section class="about-us-shell">
      <header class="about-us-header">
        <div>
          <h1>{{ $t('關於我們') }}</h1>
          <p>{{ $t('認識清大物理考古題網站與維護團隊。') }}</p>
        </div>
        <Button
          v-if="isAdmin"
          :label="$t('新增關於我們內容')"
          icon="pi pi-plus"
          @click="openCreate"
        />
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
        <Card v-for="entry in entries" :key="entry.id" class="about-us-entry">
          <template #title>
            <div class="about-us-entry-title">
              <h2>{{ localizedField(entry, 'title') }}</h2>
              <div v-if="isAdmin" class="flex gap-2">
                <Button
                  :label="$t('編輯')"
                  icon="pi pi-pencil"
                  size="small"
                  text
                  @click="openEdit(entry)"
                />
                <Button
                  :label="$t('永久刪除')"
                  icon="pi pi-trash"
                  severity="danger"
                  size="small"
                  text
                  @click="requestDelete(entry)"
                />
              </div>
            </div>
          </template>
          <template #content>
            <div
              class="markdown-content"
              v-html="renderMarkdown(localizedField(entry, 'body'))"
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
    >
      <form class="about-us-form" @submit.prevent="saveEntry">
        <div class="field">
          <label for="about-us-title">{{ $t('標題') }}</label>
          <InputText
            id="about-us-title"
            v-model="form.title"
            class="w-full"
            maxlength="150"
            :class="{ 'p-invalid': errors.title }"
            :aria-invalid="Boolean(errors.title)"
            :aria-describedby="errors.title ? 'about-us-title-error' : undefined"
          />
          <small v-if="errors.title" id="about-us-title-error" class="p-error" role="alert">
            {{ errors.title }}
          </small>
        </div>
        <div class="field">
          <label for="about-us-title-en">{{ $t('英文標題') }}</label>
          <InputText
            id="about-us-title-en"
            v-model="form.title_en"
            class="w-full"
            maxlength="150"
            :class="{ 'p-invalid': errors.title_en }"
            :aria-invalid="Boolean(errors.title_en)"
            :aria-describedby="errors.title_en ? 'about-us-title-en-error' : undefined"
          />
          <small v-if="errors.title_en" id="about-us-title-en-error" class="p-error" role="alert">{{
            errors.title_en
          }}</small>
        </div>
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
            :aria-describedby="errors.body ? 'about-us-body-error' : undefined"
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
            :aria-describedby="errors.body_en ? 'about-us-body-en-error' : undefined"
          />
          <small v-if="errors.body_en" id="about-us-body-en-error" class="p-error" role="alert">{{
            errors.body_en
          }}</small>
        </div>
        <section v-if="form.body.trim()" class="about-us-preview" :aria-label="$t('Markdown 預覽')">
          <h3>{{ $t('預覽') }}</h3>
          <div class="markdown-content" v-html="renderMarkdown(form.body)"></div>
        </section>
        <Message v-if="saveError" severity="error" :closable="false">{{ saveError }}</Message>
        <div class="about-us-form-actions">
          <Button
            type="button"
            :label="$t('取消')"
            severity="secondary"
            @click="dialogVisible = false"
          />
          <Button type="submit" :label="$t('儲存')" icon="pi pi-check" :loading="saving" />
        </div>
      </form>
    </Dialog>
  </main>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { aboutUsService } from '@/api'
import { getCurrentUser } from '@/utils/auth.js'
import { renderMarkdown } from '@/utils/markdown.js'

const { t, locale } = useI18n()
const isAdmin = Boolean(getCurrentUser()?.is_admin)
const entries = ref([])
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const saveError = ref('')
const dialogVisible = ref(false)
const editingEntry = ref(null)
const form = reactive({ title: '', body: '', title_en: '', body_en: '' })
const errors = reactive({ title: '', body: '', title_en: '', body_en: '' })

async function loadEntries() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await aboutUsService.list()
    entries.value = Array.isArray(response.data) ? response.data : []
  } catch {
    loadError.value = t('關於我們內容載入失敗，請稍後再試。')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.title = ''
  form.body = ''
  form.title_en = ''
  form.body_en = ''
  errors.title = ''
  errors.body = ''
  errors.title_en = ''
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
  form.title = entry.title
  form.body = entry.body
  form.title_en = entry.title_en || ''
  form.body_en = entry.body_en || ''
  dialogVisible.value = true
}

function validate() {
  errors.title = form.title.trim() ? '' : t('標題是必填欄位')
  errors.body = form.body.trim() ? '' : t('內容是必填欄位')
  errors.title_en = form.title_en.trim() ? '' : t('英文標題是必填欄位')
  errors.body_en = form.body_en.trim() ? '' : t('英文內容是必填欄位')
  return !errors.title && !errors.body && !errors.title_en && !errors.body_en
}

async function saveEntry() {
  if (!validate() || saving.value) return
  saving.value = true
  saveError.value = ''
  const payload = {
    title: form.title.trim(),
    body: form.body.trim(),
    title_en: form.title_en.trim(),
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

async function deleteEntry(entry) {
  try {
    await aboutUsService.remove(entry.id)
    entries.value = entries.value.filter((item) => item.id !== entry.id)
  } catch {
    loadError.value = t('關於我們內容永久刪除失敗，請稍後再試。')
  }
}

function requestDelete(entry) {
  if (
    window.confirm(
      t('確定要永久刪除「{title}」嗎？此動作無法復原。', { title: localizedField(entry, 'title') })
    )
  ) {
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
.about-us-entry-title,
.about-us-form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.about-us-header {
  margin-bottom: 1.5rem;
}

.about-us-header h1,
.about-us-entry-title h2,
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
}

:deep(.markdown-content strong) {
  font-weight: 750;
}

:deep(.markdown-content blockquote) {
  margin: 1.5rem 0;
  padding: 0.9rem 1.1rem;
  border-inline-start: 0.25rem solid var(--title-gradient-start);
  border-radius: 0.5rem;
  background: color-mix(in srgb, var(--bg-primary) 82%, var(--title-gradient-start));
  color: var(--text-primary);
}

:deep(.markdown-content blockquote p) {
  margin: 0;
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
}

:deep(.markdown-content hr + p strong),
:deep(.markdown-content hr + p em) {
  display: block;
}

.field {
  display: grid;
  gap: 0.5rem;
}

.about-us-preview {
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  background: var(--bg-secondary);
}

@media (max-width: 640px) {
  .about-us-header,
  .about-us-entry-title {
    align-items: flex-start;
    flex-direction: column;
  }

  :deep(.markdown-content) {
    line-height: 1.72;
  }

  :deep(.markdown-content blockquote) {
    padding: 0.8rem 0.9rem;
  }
}
</style>
