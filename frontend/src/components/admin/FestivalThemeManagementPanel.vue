<template>
  <section class="festival-theme-management" :aria-label="$t('節日主題管理')">
    <div
      v-if="loading"
      class="festival-theme-management__state"
      data-testid="theme-management-loading"
      role="status"
      aria-live="polite"
    >
      <ProgressSpinner strokeWidth="4" />
      <span>{{ $t('載入節日主題管理資料') }}</span>
    </div>
    <Message
      v-else-if="error"
      severity="error"
      :closable="false"
      data-testid="theme-management-error"
    >
      <div class="festival-theme-management__error">
        <span>{{ error }}</span>
        <Button
          :label="$t('重新載入')"
          icon="pi pi-refresh"
          severity="danger"
          outlined
          size="small"
          data-testid="theme-management-retry"
          @click="loadCapabilities"
        />
      </div>
    </Message>

    <div v-else class="festival-theme-management__sections" data-testid="theme-management-sections">
      <Message
        v-if="activationError || mutationError"
        severity="error"
        :closable="false"
        data-testid="theme-management-action-error"
      >
        {{ activationError || mutationError }}
      </Message>
      <Message
        v-if="multipleActiveThemeViolation"
        severity="warn"
        :closable="false"
        data-testid="multiple-active-theme-violation"
      >
        {{ $t('主題資料同時標記多個已啟用主題，請檢查資料契約。') }}
      </Message>

      <section class="festival-theme-management__panel" data-testid="theme-overview-panel">
        <div class="festival-theme-management__intro">
          <h3>{{ $t('主題一覽') }}</h3>
          <div class="festival-theme-management__intro-row">
            <Tag
              v-if="previewEnabled"
              severity="secondary"
              data-testid="festival-theme-preview-indicator"
              >{{ $t('UI 預覽模式') }}</Tag
            >
          </div>
        </div>

        <div class="theme-table-wrap" data-testid="theme-overview-table">
          <table class="theme-table admin-data-table">
            <thead>
              <tr>
                <th>{{ $t('主題名稱') }}</th>
                <th>{{ $t('主題簡介') }}</th>
                <th>{{ $t('深淺模式') }}</th>
                <th>{{ $t('狀態') }}</th>
                <th>{{ $t('操作') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in themeOverviewRows"
                :key="row.id"
                data-testid="theme-overview-row"
                :data-theme-kind="row.kind"
              >
                <td>
                  <strong>{{ row.name }}</strong>
                </td>
                <td>{{ row.description }}</td>
                <td>
                  <Tag :severity="row.supportsColorModes ? 'info' : 'secondary'">{{
                    row.supportsColorModes ? $t('有') : $t('無')
                  }}</Tag>
                </td>
                <td>
                  <Tag
                    v-if="row.isActive"
                    severity="success"
                    :data-testid="
                      row.kind === 'classic'
                        ? 'classic-theme-active-status'
                        : 'festival-theme-active-status'
                    "
                    >{{ $t('已啟用') }}</Tag
                  >
                  <Button
                    v-else
                    class="theme-download-action"
                    :label="$t('啟用')"
                    icon="pi pi-power-off"
                    severity="success"
                    size="small"
                    :disabled="Boolean(activatingThemeId)"
                    :loading="activatingThemeId === row.id"
                    :data-testid="
                      row.kind === 'classic'
                        ? 'classic-theme-activation'
                        : 'festival-theme-activation'
                    "
                    @click="activateTheme(row.id)"
                  />
                </td>
                <td>
                  <span v-if="row.kind === 'classic'" class="theme-system-label"
                    ><i class="pi pi-lock" aria-hidden="true" />{{ $t('系統內建') }}</span
                  >
                  <div v-else class="theme-row-actions">
                    <Button
                      class="theme-download-action"
                      :label="$t('編輯')"
                      icon="pi pi-pencil"
                      severity="success"
                      size="small"
                      data-testid="festival-theme-edit"
                      @click="openEdit(row.theme)"
                    />
                    <Button
                      class="theme-admin-delete-action"
                      :label="$t('刪除')"
                      icon="pi pi-trash"
                      severity="danger"
                      outlined
                      size="small"
                      :disabled="deletingThemeId === row.id || row.isActive"
                      :title="row.isActive ? $t('請先停用此主題後再刪除') : undefined"
                      data-testid="festival-theme-delete"
                      @click="confirmDelete(row.theme)"
                    />
                    <small v-if="row.isActive" class="theme-delete-guidance">{{
                      $t('請先停用此主題後再刪除')
                    }}</small>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="theme-mobile-list">
          <article
            v-for="row in themeOverviewRows"
            :key="row.id"
            class="theme-mobile-card"
            data-testid="theme-overview-mobile-card"
            :data-theme-kind="row.kind"
          >
            <header>
              <strong>{{ row.name }}</strong>
              <Tag v-if="row.isActive" severity="success">{{ $t('已啟用') }}</Tag>
              <Button
                v-else
                class="theme-download-action"
                :label="$t('啟用')"
                icon="pi pi-power-off"
                severity="success"
                size="small"
                :disabled="Boolean(activatingThemeId)"
                :loading="activatingThemeId === row.id"
                @click="activateTheme(row.id)"
              />
            </header>
            <p>{{ row.description }}</p>
            <dl>
              <div>
                <dt>{{ $t('深淺模式') }}</dt>
                <dd>{{ row.supportsColorModes ? $t('有') : $t('無') }}</dd>
              </div>
              <div v-if="row.kind === 'classic'">
                <dt>{{ $t('操作') }}</dt>
                <dd>{{ $t('系統內建') }}</dd>
              </div>
            </dl>
            <footer v-if="row.kind === 'festival'" class="theme-row-actions">
              <Button
                class="theme-download-action"
                :label="$t('編輯')"
                icon="pi pi-pencil"
                severity="success"
                @click="openEdit(row.theme)"
              />
              <Button
                class="theme-admin-delete-action"
                :label="$t('刪除')"
                icon="pi pi-trash"
                severity="danger"
                outlined
                :disabled="deletingThemeId === row.id || row.isActive"
                :title="row.isActive ? $t('請先停用此主題後再刪除') : undefined"
                @click="confirmDelete(row.theme)"
              />
              <small v-if="row.isActive" class="theme-delete-guidance">{{
                $t('請先停用此主題後再刪除')
              }}</small>
            </footer>
          </article>
        </div>

        <p
          v-if="!festivalThemes.length"
          class="theme-overview-note"
          data-testid="festival-theme-empty-note"
        >
          {{ $t('目前尚未建立節日主題') }}
        </p>
      </section>
    </div>

    <Dialog
      v-model:visible="editVisible"
      modal
      :draggable="false"
      :header="$t('編輯節日主題')"
      :style="{ width: '720px', maxWidth: '94vw' }"
    >
      <div class="theme-edit-form" data-testid="festival-theme-edit-dialog">
        <Message v-if="selectedThemeIsPreview" severity="info" :closable="false">{{
          $t('預覽模式不會儲存變更。')
        }}</Message>
        <Message v-if="editPersistenceError" severity="error" :closable="false">{{
          editPersistenceError
        }}</Message>
        <div class="theme-edit-field">
          <label for="festival-theme-name">{{ $t('主題名稱') }}</label
          ><InputText id="festival-theme-name" v-model="editForm.name" class="w-full" />
        </div>
        <div class="theme-edit-field">
          <label for="festival-theme-description">{{ $t('主題簡介') }}</label
          ><Textarea
            id="festival-theme-description"
            v-model="editForm.description"
            rows="4"
            autoResize
            class="w-full"
          />
        </div>
        <div class="theme-edit-field theme-edit-field--inline">
          <Checkbox
            v-model="editForm.supports_color_modes"
            inputId="festival-theme-color-modes"
            binary
            disabled
          /><label for="festival-theme-color-modes">{{ $t('支援淺色與深色模式') }}</label>
        </div>
        <div class="theme-edit-dates">
          <div class="theme-edit-field">
            <label for="festival-theme-starts-at">{{ $t('啟用時間') }}</label
            ><DatePicker
              v-model="editForm.starts_at"
              inputId="festival-theme-starts-at"
              showTime
              hourFormat="24"
              :showIcon="true"
              class="w-full"
            />
          </div>
          <div class="theme-edit-field">
            <label for="festival-theme-ends-at">{{ $t('停用時間') }}</label
            ><DatePicker
              v-model="editForm.ends_at"
              inputId="festival-theme-ends-at"
              showTime
              hourFormat="24"
              :showIcon="true"
              class="w-full"
              :class="{ 'p-invalid': editErrors.ends_at }"
            /><small
              v-if="editErrors.ends_at"
              class="p-error"
              data-testid="festival-theme-end-error"
              >{{ editErrors.ends_at }}</small
            >
          </div>
        </div>
        <div class="theme-edit-actions">
          <Button
            class="theme-dialog-cancel-action review-action-preview"
            :label="$t('取消')"
            severity="secondary"
            outlined
            size="small"
            @click="editVisible = false"
          /><Button
            class="theme-dialog-save-action review-action-republish"
            :label="$t('儲存')"
            icon="pi pi-save"
            severity="success"
            size="small"
            :disabled="selectedThemeIsPreview || Boolean(savingThemeId)"
            :loading="savingThemeId === selectedTheme?.id"
            data-testid="festival-theme-save"
            @click="saveEdit"
          />
        </div>
      </div>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import { useI18n } from 'vue-i18n'
import { themeManagementService } from '@/api'
import { useTheme } from '@/utils/useTheme'
import {
  createFestivalThemePreviewRows,
  isFestivalThemePreviewEnabled,
} from '@/utils/festivalThemePreview'

const { locale, t } = useI18n()
const confirm = useConfirm()
const { applyActiveSiteTheme } = useTheme()
const loading = ref(true)
const error = ref('')
const activationError = ref('')
const mutationError = ref('')
const activatingThemeId = ref('')
const deletingThemeId = ref('')
const savingThemeId = ref('')
const capabilities = ref(null)
const previewEnabled = isFestivalThemePreviewEnabled()
const previewThemes = ref(previewEnabled ? createFestivalThemePreviewRows() : [])
const previewActiveThemeId = ref(previewEnabled ? 'preview-christmas' : null)
const editVisible = ref(false)
const selectedTheme = ref(null)
const editPersistenceError = ref('')
const editErrors = ref({ ends_at: '' })
const editForm = ref(emptyEditForm())

const festivalThemes = computed(() =>
  previewEnabled ? previewThemes.value : (capabilities.value?.festival_theme?.themes ?? [])
)
const activeFestivalThemeId = computed(() =>
  previewEnabled
    ? previewActiveThemeId.value === 'general'
      ? null
      : previewActiveThemeId.value
    : (capabilities.value?.festival_theme?.active ?? null)
)
const isEnglish = computed(() => locale.value.toLowerCase().startsWith('en'))
const selectedThemeIsPreview = computed(() => selectedTheme.value?.preview_only === true)
const activeFestivalThemeIds = computed(() => {
  const activeValue = activeFestivalThemeId.value
  const requestedIds = Array.isArray(activeValue) ? activeValue : activeValue ? [activeValue] : []
  const availableIds = new Set(festivalThemes.value.map((theme) => theme.id))
  return [...new Set(requestedIds.filter((themeId) => availableIds.has(themeId)))]
})
const multipleActiveThemeViolation = computed(() => activeFestivalThemeIds.value.length > 1)
const classicThemeActive = computed(() => activeFestivalThemeIds.value.length === 0)
const themeOverviewRows = computed(() => {
  const classicRow = {
    kind: 'classic',
    id: 'general',
    name: t('經典模式'),
    description: t('最初設計的模式，有深淺色可供使用者切換。'),
    supportsColorModes: true,
    isActive: classicThemeActive.value,
    originalOrder: -1,
    theme: null,
  }
  const festivalRows = festivalThemes.value.map((theme, originalOrder) => ({
    kind: 'festival',
    id: theme.id,
    name: localizedThemeName(theme),
    description: localizedThemeDescription(theme),
    supportsColorModes: themeSupportsColorModes(theme),
    isActive: activeFestivalThemeIds.value.includes(theme.id),
    originalOrder,
    theme,
  }))
  const priority = (row) => (row.isActive ? 0 : row.kind === 'classic' ? 1 : 2)
  return [classicRow, ...festivalRows].sort(
    (left, right) => priority(left) - priority(right) || left.originalOrder - right.originalOrder
  )
})

function emptyEditForm() {
  return { name: '', description: '', supports_color_modes: false, starts_at: null, ends_at: null }
}
function parseDate(value) {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}
const localizedThemeName = (theme) => (isEnglish.value ? theme.name_en || theme.name : theme.name)
const localizedThemeDescription = (theme) =>
  isEnglish.value ? theme.description_en || theme.description : theme.description
const isActiveFestivalTheme = (themeId) => activeFestivalThemeIds.value.includes(themeId)
const themeSupportsColorModes = (theme) =>
  theme.supports_color_modes === true ||
  (Array.isArray(theme.supported_modes) && theme.supported_modes.length > 1)

async function loadCapabilities() {
  loading.value = true
  error.value = ''
  try {
    capabilities.value = (await themeManagementService.getAdmin()).data
    syncEffectiveTheme(capabilities.value)
  } catch (loadError) {
    capabilities.value = null
    error.value = loadError?.response?.data?.detail || t('載入節日主題管理資料失敗。')
  } finally {
    loading.value = false
  }
}
async function activateTheme(themeId) {
  const isActive = themeId === 'general' ? classicThemeActive.value : isActiveFestivalTheme(themeId)
  if (activatingThemeId.value || isActive) return
  if (previewEnabled) {
    previewActiveThemeId.value = themeId
    return
  }
  activatingThemeId.value = themeId
  activationError.value = ''
  mutationError.value = ''
  try {
    capabilities.value = (await themeManagementService.activateAdmin(themeId)).data
    syncEffectiveTheme(capabilities.value)
  } catch (activationFailure) {
    activationError.value = activationFailure?.response?.data?.detail || t('啟用主題失敗。')
  } finally {
    activatingThemeId.value = ''
  }
}
function openEdit(theme) {
  selectedTheme.value = theme
  editPersistenceError.value = ''
  editErrors.value = { ends_at: '' }
  editForm.value = {
    name: localizedThemeName(theme),
    description: localizedThemeDescription(theme),
    supports_color_modes: themeSupportsColorModes(theme),
    starts_at: parseDate(theme.starts_at),
    ends_at: parseDate(theme.ends_at),
  }
  editVisible.value = true
}
async function saveEdit() {
  if (selectedThemeIsPreview.value) return
  editErrors.value.ends_at = ''
  const { starts_at: startsAt, ends_at: endsAt } = editForm.value
  if (startsAt && endsAt && endsAt <= startsAt) {
    editErrors.value.ends_at = t('停用時間必須晚於啟用時間。')
    return
  }
  if (savingThemeId.value || !selectedTheme.value) return
  const theme = selectedTheme.value
  const payload = {
    name: isEnglish.value ? theme.name : editForm.value.name,
    name_en: isEnglish.value ? editForm.value.name : theme.name_en,
    description: isEnglish.value ? theme.description : editForm.value.description,
    description_en: isEnglish.value ? editForm.value.description : theme.description_en,
    starts_at: startsAt ? startsAt.toISOString() : null,
    ends_at: endsAt ? endsAt.toISOString() : null,
  }
  savingThemeId.value = theme.id
  editPersistenceError.value = ''
  try {
    capabilities.value = (await themeManagementService.updateAdmin(theme.id, payload)).data
    syncEffectiveTheme(capabilities.value)
    editVisible.value = false
  } catch (saveFailure) {
    editPersistenceError.value = saveFailure?.response?.data?.detail || t('儲存節日主題失敗。')
  } finally {
    savingThemeId.value = ''
  }
}
function confirmDelete(theme) {
  if (deletingThemeId.value) return
  if (isActiveFestivalTheme(theme.id)) {
    mutationError.value = t('請先停用此主題後再刪除')
    return
  }
  confirm.require({
    header: t('刪除節日主題'),
    message: t('確定要刪除「{name}」嗎？', { name: localizedThemeName(theme) }),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('確認刪除'),
    acceptClass: 'p-button-danger',
    accept: () => removeTheme(theme),
  })
}
async function removeTheme(theme) {
  if (deletingThemeId.value) return
  if (isActiveFestivalTheme(theme.id)) {
    mutationError.value = t('請先停用此主題後再刪除')
    return
  }
  deletingThemeId.value = theme.id
  mutationError.value = ''
  try {
    if (theme.preview_only === true) {
      previewThemes.value = previewThemes.value.filter((item) => item.id !== theme.id)
      return
    }
    capabilities.value = (await themeManagementService.removeAdmin(theme.id)).data
    syncEffectiveTheme(capabilities.value)
  } catch (deleteFailure) {
    mutationError.value = deleteFailure?.response?.data?.detail || t('刪除節日主題失敗。')
  } finally {
    deletingThemeId.value = ''
  }
}
function syncEffectiveTheme(nextCapabilities) {
  applyActiveSiteTheme(nextCapabilities?.festival_theme?.active || 'general')
}
onMounted(loadCapabilities)
</script>

<style scoped>
.festival-theme-management {
  min-width: 0;
  color: var(--text-primary);
}
.festival-theme-management__intro {
  display: grid;
  gap: 0.35rem;
}
.festival-theme-management__intro h3 {
  margin: 0;
}
.festival-theme-management__intro p,
.theme-mobile-card p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.6;
}
.festival-theme-management__intro-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
}
.festival-theme-management__state {
  display: grid;
  min-height: 20rem;
  place-content: center;
  justify-items: center;
  gap: 0.85rem;
  color: var(--text-secondary);
}
.festival-theme-management__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.festival-theme-management__sections {
  display: grid;
  gap: 2rem;
  min-width: 0;
}
.festival-theme-management__panel {
  display: grid;
  gap: 1rem;
  min-width: 0;
}
.theme-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
}
.theme-table {
  width: 100%;
  min-width: 62rem;
  border-collapse: collapse;
  table-layout: fixed;
  background: var(--bg-primary);
}
.theme-table th,
.theme-table td {
  padding: 0.9rem 1rem;
  border-bottom: 1px solid var(--border-color);
  text-align: left;
  vertical-align: middle;
}
.theme-table th {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 700;
}
.theme-table tr:last-child td {
  border-bottom: 0;
}
.theme-table th:nth-child(1) {
  width: 16%;
}
.theme-table th:nth-child(2) {
  width: 31%;
}
.theme-table th:nth-child(3) {
  width: 12%;
}
.theme-table th:nth-child(4) {
  width: 12%;
}
.theme-table th:nth-child(5) {
  width: 29%;
}
.theme-system-label {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--text-secondary);
  font-weight: 600;
}
.theme-row-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.theme-delete-guidance {
  color: var(--text-secondary);
  font-size: var(--app-font-size-xs);
}
.theme-mobile-list {
  display: none;
  gap: 0.75rem;
}
.theme-mobile-card {
  display: none;
  gap: 0.8rem;
  padding: 1rem;
  border: 1px solid var(--border-color);
  border-radius: 0.75rem;
  background: var(--bg-primary);
}
.theme-mobile-card header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}
.theme-mobile-card dl {
  display: grid;
  gap: 0.5rem;
  margin: 0;
}
.theme-mobile-card dl div {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}
.theme-mobile-card dt {
  color: var(--text-secondary);
}
.theme-mobile-card dd {
  margin: 0;
  font-weight: 600;
  text-align: right;
}
.theme-overview-note {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--app-font-size-sm);
}
.theme-edit-form,
.theme-edit-field {
  display: grid;
  gap: 0.5rem;
}
.theme-edit-form {
  gap: 1rem;
}
.theme-edit-field--inline {
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
}
.theme-edit-dates {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.theme-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding-top: 0.75rem;
}
@media (max-width: 1399.98px) {
  .theme-table-wrap {
    display: none;
  }
  .theme-mobile-card,
  .theme-mobile-list {
    display: grid;
  }
}
@media (max-width: 640px) {
  .festival-theme-management__error {
    align-items: stretch;
    flex-direction: column;
  }
  .theme-edit-dates {
    grid-template-columns: minmax(0, 1fr);
  }
  .theme-row-actions :deep(.p-button) {
    flex: 1 1 100%;
  }
}
</style>
