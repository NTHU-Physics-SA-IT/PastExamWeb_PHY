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
        v-if="activationError"
        severity="error"
        :closable="false"
        data-testid="theme-management-action-error"
      >
        {{ activationError }}
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

        <div class="theme-gallery" data-testid="theme-overview-gallery">
          <article
            v-for="row in themeOverviewRows"
            :key="row.id"
            class="theme-gallery-card"
            :class="{
              'theme-gallery-card--active': row.isActive,
              'theme-gallery-card--inactive': !row.isActive,
            }"
            data-testid="theme-overview-card"
            :data-theme-kind="row.kind"
            :aria-label="row.name"
            :aria-current="row.isActive ? 'true' : undefined"
            :aria-describedby="`theme-card-details-${row.id}`"
            tabindex="0"
          >
            <div
              class="theme-gallery-card__visual"
              data-testid="theme-mode-visual"
              aria-hidden="true"
            >
              <i
                :class="row.kind === 'classic' ? 'pi pi-palette' : 'pi pi-sparkles'"
                aria-hidden="true"
              />
            </div>

            <footer class="theme-gallery-card__footer">
              <header class="theme-gallery-card__header">
                <div class="theme-gallery-card__identity">
                  <i
                    :class="row.kind === 'classic' ? 'pi pi-palette' : 'pi pi-sparkles'"
                    aria-hidden="true"
                  />
                  <strong class="theme-gallery-card__title">{{ row.name }}</strong>
                </div>
                <Tag
                  :severity="row.isActive ? 'success' : 'secondary'"
                  :data-testid="
                    row.isActive
                      ? row.kind === 'classic'
                        ? 'classic-theme-active-status'
                        : 'festival-theme-active-status'
                      : undefined
                  "
                  >{{ row.isActive ? $t('已啟用') : $t('未啟用') }}</Tag
                >
              </header>

              <div
                :id="`theme-card-details-${row.id}`"
                class="theme-gallery-card__details"
                data-testid="theme-card-details"
              >
                <p class="theme-gallery-card__description" :title="row.description">
                  {{ row.description }}
                </p>

                <div class="theme-gallery-card__metadata">
                  <span class="theme-gallery-card__kind"
                    ><i
                      :class="row.kind === 'classic' ? 'pi pi-lock' : 'pi pi-sparkles'"
                      aria-hidden="true"
                    />{{ row.kind === 'classic' ? $t('系統內建') : $t('節日主題') }}</span
                  >
                  <span class="theme-gallery-card__mode">
                    {{ $t('深淺模式') }}
                    <Tag :severity="row.supportsColorModes ? 'info' : 'secondary'">{{
                      row.supportsColorModes ? $t('有') : $t('無')
                    }}</Tag>
                  </span>
                </div>

                <div class="theme-row-actions">
                  <Button
                    v-if="!row.isActive"
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
                  <template v-if="row.kind === 'festival'">
                    <Button
                      class="theme-download-action"
                      :label="$t('編輯')"
                      icon="pi pi-pencil"
                      severity="success"
                      size="small"
                      data-testid="festival-theme-edit"
                      @click="openEdit(row.theme)"
                    />
                  </template>
                </div>
              </div>
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
import { useI18n } from 'vue-i18n'
import { themeManagementService } from '@/api'
import { useTheme } from '@/utils/useTheme'
import {
  createFestivalThemePreviewRows,
  isFestivalThemePreviewEnabled,
} from '@/utils/festivalThemePreview'

const { locale, t } = useI18n()
const { applyActiveSiteTheme } = useTheme()
const loading = ref(true)
const error = ref('')
const activationError = ref('')
const activatingThemeId = ref('')
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
function syncEffectiveTheme(nextCapabilities) {
  applyActiveSiteTheme(nextCapabilities?.festival_theme?.active || 'general')
}
onMounted(loadCapabilities)
</script>

<style scoped>
.festival-theme-management {
  --festival-card-shadow: 0 0.55rem 1.35rem rgba(15, 23, 42, 0.12);

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
.theme-gallery-card__description {
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
.theme-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 23rem), 28rem));
  justify-content: start;
  gap: 1rem;
}
.theme-gallery-card {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-rows: minmax(8.75rem, 1fr) auto;
  aspect-ratio: 1.7 / 1;
  min-width: 0;
  min-height: 15.5rem;
  overflow: hidden;
  border: 1px solid var(--theme-card-border);
  border-radius: 0.9rem;
  color: var(--theme-card-text);
  background: var(--theme-card-surface);
  box-shadow: 0 0.2rem 0.6rem rgba(15, 23, 42, 0.07);
  transition:
    flex-grow 220ms ease,
    transform 160ms ease,
    border-color 160ms ease,
    box-shadow 160ms ease,
    background-color 160ms ease;
}
.theme-gallery-card[data-theme-kind='classic'] {
  --theme-card-surface: #eef6f2;
  --theme-card-layer: #f7fbfb;
  --theme-card-text: #172522;
  --theme-card-muted-text: #5d6f6a;
  --theme-card-accent: #176f7b;
  --theme-card-border: #cbdad4;
}
.theme-gallery-card[data-theme-kind='festival'] {
  --theme-card-surface: #17483f;
  --theme-card-layer: #103a34;
  --theme-card-text: #f8f2e8;
  --theme-card-muted-text: #f5eedc;
  --theme-card-accent: #dec78e;
  --theme-card-border: #294f47;
}
.theme-gallery-card::before {
  position: absolute;
  z-index: 2;
  inset: 0 0 auto;
  height: 0.22rem;
  background: var(--theme-card-accent);
  content: '';
  opacity: 0;
  transition: opacity 160ms ease;
}
.theme-gallery-card--active {
  border-color: color-mix(in srgb, var(--theme-card-accent) 58%, var(--theme-card-border));
  box-shadow:
    0 0.3rem 0.9rem rgba(15, 23, 42, 0.1),
    inset 0 0 0 1px color-mix(in srgb, var(--theme-card-accent) 18%, transparent);
}
.theme-gallery-card--active::before {
  opacity: 1;
}
.theme-gallery-card:focus-within {
  border-color: var(--theme-card-accent);
  box-shadow:
    0 0 0 0.18rem color-mix(in srgb, var(--theme-card-accent) 28%, transparent),
    var(--festival-card-shadow);
}
.theme-gallery-card:focus-visible {
  outline: 0.18rem solid color-mix(in srgb, var(--theme-card-accent) 72%, transparent);
  outline-offset: 0.18rem;
}
.theme-gallery-card__visual {
  display: grid;
  min-width: 0;
  min-height: 0;
  place-items: center;
  border-bottom: 1px solid var(--theme-card-border);
  color: var(--theme-card-accent);
  background: var(--theme-card-surface);
}
.theme-gallery-card__visual > i {
  font-size: clamp(2.75rem, 5vw, 4.4rem);
  opacity: 0.86;
}
.theme-gallery-card__footer {
  display: grid;
  gap: 0;
  padding: 0.8rem 0.9rem 0.85rem;
  background: var(--theme-card-layer);
}
.theme-gallery-card__details {
  display: grid;
  gap: 0.55rem;
  min-width: 0;
}
.theme-gallery-card__header,
.theme-gallery-card__identity,
.theme-gallery-card__metadata,
.theme-gallery-card__mode,
.theme-row-actions {
  display: flex;
  align-items: center;
}
.theme-gallery-card__header {
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.65rem;
}
.theme-gallery-card__header :deep(.p-tag) {
  flex: 0 0 auto;
}
.theme-gallery-card__identity {
  gap: 0.5rem;
  min-width: 0;
}
.theme-gallery-card__identity > i {
  color: var(--theme-card-accent);
}
.theme-gallery-card__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  overflow-wrap: anywhere;
}
.theme-gallery-card__kind {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  color: var(--theme-card-muted-text);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.theme-gallery-card__description {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--theme-card-muted-text);
}
.theme-gallery-card__metadata {
  flex-wrap: wrap;
  gap: 0.3rem 0.65rem;
  color: var(--theme-card-muted-text);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
}
.theme-gallery-card__mode {
  gap: 0.3rem;
}
.theme-row-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
  min-width: 0;
}
.theme-row-actions :deep(.p-button) {
  flex: 0 1 auto;
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
/* Interaction model adapted from Uiverse.io by arshshaikh06: Cards/arshshaikh06_hard-cobra-69.html */
@media (min-width: 768px) and (hover: hover) and (pointer: fine) {
  .theme-gallery {
    display: flex;
    align-items: stretch;
    width: min(100%, 58rem);
    height: clamp(18rem, 32vw, 21rem);
    padding: 0.5rem;
    overflow: hidden;
    border: 1px solid var(--border-color);
    border-radius: 1.1rem;
    background: color-mix(in srgb, var(--bg-secondary) 68%, transparent);
    box-shadow: 0 0.3rem 0.9rem rgba(15, 23, 42, 0.08);
  }
  .theme-gallery-card {
    flex: 1 1 0;
    grid-template-rows: minmax(0, 1fr) 4.25rem;
    aspect-ratio: auto;
    min-height: 0;
  }
  .theme-gallery-card:hover,
  .theme-gallery-card:focus,
  .theme-gallery-card:focus-within {
    flex-grow: 1.85;
    border-color: color-mix(in srgb, var(--theme-card-accent) 44%, var(--theme-card-border));
    box-shadow: var(--festival-card-shadow);
  }
  .theme-gallery-card__details {
    position: absolute;
    z-index: 1;
    right: 0.9rem;
    bottom: 4.8rem;
    left: 0.9rem;
    max-height: 0;
    overflow: hidden;
    opacity: 0;
    pointer-events: none;
    transform: translateY(0.35rem);
    transition:
      max-height 220ms ease,
      margin-top 220ms ease,
      opacity 150ms ease,
      transform 180ms ease;
  }
  .theme-gallery-card:hover .theme-gallery-card__details,
  .theme-gallery-card:focus .theme-gallery-card__details,
  .theme-gallery-card:focus-within .theme-gallery-card__details {
    max-height: 12rem;
    margin-top: 0.55rem;
    opacity: 1;
    pointer-events: auto;
    transform: translateY(0);
  }
  .theme-gallery-card__footer {
    min-height: 4.25rem;
  }
}
@media (prefers-reduced-motion: reduce) {
  .theme-gallery-card,
  .theme-gallery-card::before,
  .theme-gallery-card__details {
    transition: none;
  }
}
@media (max-width: 767.98px) {
  .festival-theme-management__error {
    align-items: stretch;
    flex-direction: column;
  }
  .theme-edit-dates {
    grid-template-columns: minmax(0, 1fr);
  }
  .theme-gallery {
    grid-template-columns: minmax(0, 1fr);
  }
  .theme-gallery-card {
    aspect-ratio: auto;
  }
  .theme-gallery-card__visual {
    min-height: 9rem;
  }
  .theme-gallery-card__footer {
    align-items: stretch;
  }
  .theme-row-actions :deep(.p-button) {
    flex: 1 1 100%;
    width: 100%;
  }
  .theme-row-actions {
    align-items: stretch;
  }
  .theme-row-actions {
    flex: 1 1 100%;
  }
}
</style>
