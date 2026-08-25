<template>
  <section
    class="slogan-management admin-management-typography"
    :aria-label="$t('首頁 slogan 管理')"
  >
    <section class="slogan-overview admin-insights-card">
      <button
        type="button"
        class="slogan-overview__toggle section-collapse-toggle"
        :aria-expanded="overviewExpanded"
        @click="toggleOverview"
      >
        <span>
          <strong>{{ $t('目前啟用的首頁 slogan') }}</strong>
          <small>{{ $t('目前共 {count} 則啟用', { count: statusCounts.enabled }) }}</small>
        </span>
        <span class="slogan-overview__counts">
          <Tag severity="warn">{{ $t('待審核') }} {{ statusCounts.pending }}</Tag>
          <Tag severity="success">{{ $t('啟用') }} {{ statusCounts.enabled }}</Tag>
          <Tag severity="secondary">{{ $t('未啟用') }} {{ statusCounts.disabled }}</Tag>
          <i :class="overviewExpanded ? 'pi pi-chevron-up' : 'pi pi-chevron-down'" />
        </span>
      </button>
      <div v-if="overviewExpanded" class="slogan-overview__body">
        <ProgressSpinner v-if="overviewLoading && !enabledItems.length" strokeWidth="4" />
        <Message v-else-if="overviewError" severity="error" :closable="false">
          {{ overviewError }}
        </Message>
        <p v-else-if="!enabledItems.length" class="slogan-empty">
          {{ $t('目前沒有啟用的首頁 slogan。') }}
        </p>
        <div v-else class="slogan-overview__table" role="table">
          <div class="slogan-overview__grid slogan-overview__header" role="row">
            <span role="columnheader">{{ $t('投稿內容') }}</span>
            <span role="columnheader">{{ $t('投稿人') }}</span>
            <span role="columnheader">{{ $t('出現等級') }}</span>
          </div>
          <ul class="slogan-overview__list" role="rowgroup">
            <li
              v-for="item in enabledItems"
              :key="item.id"
              class="slogan-overview__grid slogan-overview__row"
              role="row"
            >
              <span class="slogan-overview__cell" role="cell">
                <span class="slogan-overview__mobile-label">{{ $t('投稿內容') }}</span>
                <span class="slogan-overview__content">{{ item.content }}</span>
              </span>
              <span class="slogan-overview__cell" role="cell">
                <span class="slogan-overview__mobile-label">{{ $t('投稿人') }}</span>
                <span>{{ item.submitter_name }}</span>
              </span>
              <span class="slogan-overview__cell" role="cell">
                <span class="slogan-overview__mobile-label">{{ $t('出現等級') }}</span>
                <Tag severity="info">{{ levelLabel(item.occurrence_level) }}</Tag>
              </span>
            </li>
          </ul>
        </div>
        <Button
          v-if="enabledItems.length < enabledTotal"
          :label="$t('載入更多')"
          icon="pi pi-angle-down"
          outlined
          size="small"
          :loading="overviewLoading"
          @click="loadEnabledOverview(false)"
        />
      </div>
    </section>

    <div class="slogan-filters report-management__filters">
      <InputText
        v-model="filters.search"
        class="report-filter-search"
        :placeholder="$t('搜尋 slogan 或投稿人')"
        @keyup.enter="applyFilters"
      />
      <Select
        v-model="filters.status"
        class="report-filter-select report-filter-select--primary"
        :options="statusFilterOptions"
        optionLabel="label"
        optionValue="value"
        :placeholder="$t('全部')"
        @change="applyFilters"
      />
      <Button
        class="report-filter-submit"
        :label="$t('搜尋')"
        icon="pi pi-search"
        outlined
        @click="applyFilters"
      />
      <Button
        class="report-filter-refresh"
        :label="$t('重新整理')"
        icon="pi pi-refresh"
        outlined
        :loading="loading"
        @click="refreshAll"
      />
    </div>

    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
    <DataTable
      v-else
      :value="items"
      :loading="loading"
      lazy
      paginator
      :first="page.first"
      :rows="page.rows"
      :totalRecords="total"
      :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
      paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
      :currentPageReportTemplate="paginationReportTemplate"
      :sortField="page.sortField"
      :sortOrder="page.sortOrder"
      class="slogan-table admin-data-table"
      tableStyle="table-layout: fixed; min-width: 68rem"
      @page="onPage"
      @sort="onSort"
    >
      <template #empty>{{ $t('目前沒有首頁 slogan 投稿。') }}</template>
      <Column field="created_at" sortField="created_at" :header="$t('投稿')" sortable>
        <template #body="{ data }">
          <PersonTime :name="data.submitter_name" :time="data.created_at" />
        </template>
      </Column>
      <Column field="content" :header="$t('投稿內容')" sortable>
        <template #body="{ data }"
          ><span class="slogan-content">{{ data.content }}</span></template
        >
      </Column>
      <Column field="reviewed_at" sortField="reviewed_at" :header="$t('審核')" sortable>
        <template #body="{ data }">
          <PersonTime :name="data.reviewer_name" :time="data.reviewed_at" empty />
        </template>
      </Column>
      <Column field="status" :header="$t('審核狀態')" sortable>
        <template #body="{ data }">
          <Tag :severity="statusSeverity(data.status)">{{ statusLabel(data.status) }}</Tag>
        </template>
      </Column>
      <Column field="occurrence_level" :header="$t('出現等級')" sortable>
        <template #body="{ data }">
          <Tag severity="info" :value="levelLabel(data.occurrence_level)" />
        </template>
      </Column>
      <Column :header="$t('操作')">
        <template #body="{ data }">
          <div class="report-row-actions">
            <Button
              :label="$t('查看/審核')"
              icon="pi pi-search"
              :aria-label="$t('查看/審核')"
              :title="$t('查看/審核')"
              size="small"
              outlined
              @click="openReview(data)"
            />
            <Button
              :label="$t('永久刪除')"
              icon="pi pi-trash"
              severity="danger"
              outlined
              size="small"
              @click="confirmDelete(data)"
            />
          </div>
        </template>
      </Column>
    </DataTable>

    <div class="slogan-mobile-list">
      <ProgressSpinner v-if="loading" strokeWidth="4" />
      <p v-else-if="!items.length" class="slogan-empty">
        {{ $t('目前沒有首頁 slogan 投稿。') }}
      </p>
      <article
        v-for="item in items"
        v-else
        :key="item.id"
        class="report-mobile-card report-mobile-card-content admin-responsive-card-surface"
      >
        <header class="report-mobile-card__header report-mobile-card-header">
          <strong class="report-mobile-card-title" :title="item.content">
            {{ item.content }}
          </strong>
          <div class="report-mobile-card-status-group">
            <Tag severity="info" :value="levelLabel(item.occurrence_level)" />
            <Tag
              class="report-mobile-card-status"
              :severity="statusSeverity(item.status)"
              :value="statusLabel(item.status)"
            />
          </div>
        </header>
        <div class="report-mobile-card__body">
          <dl class="report-mobile-card__metadata report-mobile-info-grid">
            <div class="report-mobile-info-item">
              <dt>{{ $t('投稿人') }}</dt>
              <dd>{{ item.submitter_name }}</dd>
            </div>
            <div class="report-mobile-info-item">
              <dt>{{ $t('投稿時間') }}</dt>
              <dd>
                <time :datetime="item.created_at">{{ formatTime(item.created_at) }}</time>
              </dd>
            </div>
            <div class="report-mobile-info-item">
              <dt>{{ $t('審核人') }}</dt>
              <dd>{{ item.reviewer_name || '—' }}</dd>
            </div>
            <div class="report-mobile-info-item">
              <dt>{{ $t('審核時間') }}</dt>
              <dd>
                <time v-if="item.reviewed_at" :datetime="item.reviewed_at">{{
                  formatTime(item.reviewed_at)
                }}</time
                ><span v-else>—</span>
              </dd>
            </div>
          </dl>
        </div>
        <footer class="report-mobile-card__footer">
          <div class="report-row-actions">
            <Button
              :label="$t('查看/審核')"
              icon="pi pi-search"
              :aria-label="$t('查看/審核')"
              :title="$t('查看/審核')"
              size="small"
              outlined
              @click="openReview(item)"
            />
            <Button
              :label="$t('永久刪除')"
              icon="pi pi-trash"
              severity="danger"
              outlined
              size="small"
              @click="confirmDelete(item)"
            />
          </div>
        </footer>
      </article>
      <Paginator
        v-if="total > 0"
        :first="page.first"
        :rows="page.rows"
        :totalRecords="total"
        :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
        :currentPageReportTemplate="paginationReportTemplate"
        template="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
        @page="onPage"
      />
    </div>

    <Dialog
      v-model:visible="reviewVisible"
      modal
      :draggable="false"
      :header="$t('查看/審核首頁 slogan')"
      :style="{ width: '520px', maxWidth: '94vw' }"
    >
      <div v-if="selected" class="slogan-review">
        <dl>
          <div>
            <dt>{{ $t('投稿人') }}</dt>
            <dd>{{ selected.submitter_name }}</dd>
          </div>
          <div>
            <dt>{{ $t('投稿時間') }}</dt>
            <dd>{{ formatTime(selected.created_at) }}</dd>
          </div>
          <div>
            <dt>{{ $t('slogan 內容') }}</dt>
            <dd class="slogan-content">{{ selected.content }}</dd>
          </div>
          <div>
            <dt>{{ $t('目前狀態') }}</dt>
            <dd>
              <Tag :severity="statusSeverity(selected.status)">{{
                statusLabel(selected.status)
              }}</Tag>
            </dd>
          </div>
          <div>
            <dt>{{ $t('審核人') }}</dt>
            <dd>{{ selected.reviewer_name || '—' }}</dd>
          </div>
          <div>
            <dt>{{ $t('審核時間') }}</dt>
            <dd>{{ formatTime(selected.reviewed_at) }}</dd>
          </div>
        </dl>
        <div class="slogan-review__field">
          <label for="slogan-review-status">{{ $t('審核狀態') }}</label>
          <Select
            v-model="reviewForm.status"
            inputId="slogan-review-status"
            :options="reviewStatusOptions"
            optionLabel="label"
            optionValue="value"
            class="w-full"
          />
        </div>
        <div class="slogan-review__field">
          <label for="slogan-review-level">{{ $t('出現等級') }}</label>
          <Select
            v-model="reviewForm.occurrence_level"
            inputId="slogan-review-level"
            :options="levelOptions"
            optionLabel="label"
            optionValue="value"
            class="w-full"
          />
        </div>
        <div class="slogan-review__actions">
          <Button :label="$t('取消')" severity="secondary" text @click="reviewVisible = false" />
          <Button :label="$t('儲存')" icon="pi pi-save" :loading="saving" @click="saveReview" />
        </div>
      </div>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { useI18n } from 'vue-i18n'
import { homepageSloganService } from '@/api'
import { ADMIN_PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { getMessageTemplate } from '@/i18n'
import { formatExactDateTime24h } from '@/utils/time'

const emit = defineEmits(['attention-change'])
const { t } = useI18n()
const confirm = useConfirm()
const toast = useToast()
const paginationReportTemplate = computed(() =>
  getMessageTemplate('第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆')
)
const items = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const filters = ref({ search: '', status: null })
const page = ref({ first: 0, rows: 10, sortField: 'created_at', sortOrder: -1 })
const statusCounts = ref({ pending: 0, enabled: 0, disabled: 0 })
const overviewExpanded = ref(false)
const overviewLoading = ref(false)
const overviewError = ref('')
const enabledItems = ref([])
const enabledTotal = ref(0)
const reviewVisible = ref(false)
const selected = ref(null)
const reviewForm = ref({ status: 'disabled', occurrence_level: 'normal' })
const saving = ref(false)

const statusFilterOptions = computed(() => [
  { label: t('全部'), value: null },
  { label: t('待審核'), value: 'pending' },
  { label: t('啟用'), value: 'enabled' },
  { label: t('未啟用'), value: 'disabled' },
])
const reviewStatusOptions = computed(() => [
  { label: t('啟用'), value: 'enabled' },
  { label: t('未啟用'), value: 'disabled' },
])
const levelOptions = computed(() => [
  { label: t('超級少'), value: 'super_rare' },
  { label: t('較少'), value: 'rare' },
  { label: t('一般'), value: 'normal' },
  { label: t('較常'), value: 'frequent' },
  { label: t('超級常'), value: 'super_frequent' },
])

const PersonTime = defineComponent({
  props: { name: String, time: String, empty: Boolean },
  setup(props) {
    return () =>
      h('div', { class: 'slogan-person-time' }, [
        h('span', props.name || (props.empty ? '—' : '')),
        props.time ? h('time', { datetime: props.time }, formatTime(props.time)) : h('small', '—'),
      ])
  },
})

function formatTime(value) {
  return formatExactDateTime24h(value)
}
function statusLabel(value) {
  return { pending: t('待審核'), enabled: t('啟用'), disabled: t('未啟用') }[value] || value
}
function statusSeverity(value) {
  return { pending: 'warn', enabled: 'success', disabled: 'secondary' }[value] || 'secondary'
}
function levelLabel(value) {
  return levelOptions.value.find((option) => option.value === value)?.label || value
}
function requestParams() {
  return {
    limit: page.value.rows,
    offset: page.value.first,
    status: filters.value.status || undefined,
    search: filters.value.search.trim() || undefined,
    sort_by: page.value.sortField,
    sort_order: page.value.sortOrder === 1 ? 'asc' : 'desc',
  }
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await homepageSloganService.listAdmin(requestParams())
    items.value = data.items
    total.value = data.total
    statusCounts.value = data.status_counts
  } catch (loadError) {
    error.value = loadError?.response?.data?.detail || t('載入首頁 slogan 投稿失敗。')
  } finally {
    loading.value = false
  }
}
function applyFilters() {
  page.value.first = 0
  void load()
}
function onPage(event) {
  page.value.first = event.first
  page.value.rows = event.rows
  void load()
}
function onSort(event) {
  page.value.first = 0
  page.value.sortField = event.sortField || 'created_at'
  page.value.sortOrder = event.sortOrder || -1
  void load()
}
async function refreshAll() {
  await load()
  if (overviewExpanded.value) await loadEnabledOverview(true)
}
function toggleOverview() {
  overviewExpanded.value = !overviewExpanded.value
  if (overviewExpanded.value && !enabledItems.value.length) void loadEnabledOverview(true)
}
async function loadEnabledOverview(reset) {
  if (overviewLoading.value) return
  overviewLoading.value = true
  overviewError.value = ''
  if (reset) enabledItems.value = []
  try {
    const { data } = await homepageSloganService.listAdmin({
      status: 'enabled',
      limit: 50,
      offset: reset ? 0 : enabledItems.value.length,
      sort_by: 'created_at',
      sort_order: 'desc',
    })
    enabledItems.value = reset ? data.items : [...enabledItems.value, ...data.items]
    enabledTotal.value = data.total
    statusCounts.value = data.status_counts
  } catch (loadError) {
    overviewError.value = loadError?.response?.data?.detail || t('載入啟用 slogan 失敗。')
  } finally {
    overviewLoading.value = false
  }
}
function openReview(item) {
  selected.value = item
  reviewForm.value = {
    status: item.status === 'pending' ? 'disabled' : item.status,
    occurrence_level: item.occurrence_level,
  }
  reviewVisible.value = true
}
async function saveReview() {
  if (!selected.value || saving.value) return
  saving.value = true
  try {
    await homepageSloganService.updateAdmin(selected.value.id, reviewForm.value)
    reviewVisible.value = false
    toast.add({
      severity: 'success',
      summary: t('儲存成功'),
      detail: t('首頁 slogan 狀態已更新。'),
      life: 3500,
    })
    emit('attention-change')
    await refreshAll()
  } catch (saveError) {
    toast.add({
      severity: 'error',
      summary: t('儲存失敗'),
      detail: saveError?.response?.data?.detail || t('請稍後再試。'),
      life: 4000,
    })
  } finally {
    saving.value = false
  }
}
function confirmDelete(item) {
  confirm.require({
    header: t('永久刪除首頁 slogan 投稿？'),
    message: t('這筆首頁 slogan 投稿將永久刪除，無法復原，也不會進入垃圾桶。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('永久刪除'),
    acceptClass: 'p-button-danger',
    accept: () => removeItem(item),
  })
}
async function removeItem(item) {
  try {
    await homepageSloganService.removeAdmin(item.id)
    toast.add({
      severity: 'success',
      summary: t('已永久刪除'),
      detail: t('首頁 slogan 投稿已永久刪除。'),
      life: 3500,
    })
    emit('attention-change')
    if (items.value.length === 1 && page.value.first > 0)
      page.value.first = Math.max(0, page.value.first - page.value.rows)
    await refreshAll()
  } catch (deleteError) {
    toast.add({
      severity: 'error',
      summary: t('永久刪除失敗'),
      detail: deleteError?.response?.data?.detail || t('請稍後再試。'),
      life: 4000,
    })
  }
}

onMounted(load)
</script>

<style scoped>
.slogan-management {
  container-name: report-section;
  container-type: inline-size;
  display: grid;
  gap: 1rem;
}
.slogan-overview {
  padding: 0;
  overflow: hidden;
}
.slogan-overview__toggle {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.2rem;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.slogan-overview__toggle > span:first-child {
  display: grid;
  gap: 0.25rem;
}
.slogan-overview__toggle small {
  color: var(--text-color-secondary);
}
.slogan-overview__counts {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.slogan-overview__body {
  display: grid;
  gap: 0.75rem;
  padding: 0 1.2rem 1.2rem;
}
.slogan-overview__table {
  max-height: 24rem;
  overflow: auto;
  border: 1px solid var(--border-color);
  border-radius: var(--p-content-border-radius);
  background: transparent;
}
.slogan-overview__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(7rem, 10rem) minmax(6rem, 8rem);
  align-items: center;
  gap: 0.75rem;
}
.slogan-overview__header {
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-sm);
  font-weight: 600;
}
.slogan-overview__list {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}
.slogan-overview__row {
  padding: 0.75rem;
  border-bottom: 1px solid var(--border-color);
}
.slogan-overview__row:last-child {
  border-bottom: 0;
}
.slogan-overview__cell {
  min-width: 0;
}
.slogan-overview__cell:last-child :deep(.p-tag) {
  justify-self: start;
}
.slogan-overview__mobile-label {
  display: none;
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
  font-weight: 600;
}
.slogan-overview__content,
.slogan-content {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.slogan-person-time {
  display: grid;
  gap: 0.2rem;
  min-width: 0;
}
.slogan-person-time span {
  overflow: hidden;
  text-overflow: ellipsis;
}
.slogan-person-time time,
.slogan-person-time small {
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
}
.slogan-mobile-list {
  display: none;
}
.slogan-review,
.slogan-review dl {
  display: grid;
  gap: 0.75rem;
}
.slogan-review dl {
  margin: 0;
}
.slogan-review dl > div {
  display: grid;
  grid-template-columns: 6rem minmax(0, 1fr);
  gap: 0.75rem;
}
.slogan-review dt {
  color: var(--text-color-secondary);
}
.slogan-review dd {
  margin: 0;
}
.slogan-review__field {
  display: grid;
  gap: 0.4rem;
}
.slogan-review__field label {
  font-weight: 600;
}
.slogan-review__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 0.5rem;
}
.slogan-empty {
  margin: 0;
  color: var(--text-color-secondary);
}
@media (max-width: 1399.98px) {
  .slogan-table {
    display: none;
  }
  .slogan-mobile-list {
    display: grid;
    gap: 0.8rem;
  }
  .slogan-overview__toggle {
    align-items: flex-start;
    flex-direction: column;
  }
  .slogan-overview__counts {
    justify-content: flex-start;
  }
}
@media (max-width: 640px) {
  .slogan-review dl > div {
    grid-template-columns: 1fr;
    gap: 0.2rem;
  }
  .slogan-overview__header {
    display: none;
  }
  .slogan-overview__row {
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
    gap: 0.55rem;
  }
  .slogan-overview__cell {
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr);
    align-items: start;
    gap: 0.5rem;
  }
  .slogan-overview__mobile-label {
    display: block;
  }
}
</style>
