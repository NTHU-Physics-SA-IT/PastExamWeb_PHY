<template>
  <div>
    <Dialog
      :visible="visible"
      @update:visible="$emit('update:visible', $event)"
      modal
      :style="{ width: 'min(820px, calc(100vw - 2rem))', maxWidth: '100%' }"
      :draggable="false"
      :blockScroll="true"
      class="notification-center-dialog"
      :pt="{ root: { 'aria-label': '公告與通知', 'aria-labelledby': null } }"
    >
      <template #header>
        <div class="notification-dialog-header">
          <i class="pi pi-bell text-2xl" />
          <span class="notification-dialog-header__title">公告與通知</span>
          <Badge v-if="counts.total" :value="counts.total" severity="danger" />
        </div>
      </template>

      <div v-if="loading" class="flex justify-content-center py-5">
        <ProgressSpinner style="width: 40px; height: 40px" strokeWidth="4" />
      </div>
      <Tabs v-else v-model:value="activeTab" class="notification-center-tabs">
        <TabList>
          <Tab value="announcements"><i class="pi pi-megaphone mr-2" />公告</Tab>
          <Tab value="personal">
            <i class="pi pi-bell mr-2" />個人通知
            <Badge
              v-if="counts.personal_notifications"
              :value="counts.personal_notifications"
              severity="danger"
              class="ml-2"
            />
          </Tab>
        </TabList>
        <TabPanels>
          <TabPanel value="announcements">
            <div v-if="announcements.length === 0" class="notification-empty">
              <i class="pi pi-megaphone text-4xl" /><span>目前沒有公告</span>
            </div>
            <div v-else class="notification-groups notification-announcement-groups">
              <section
                v-for="group in groupedAnnouncements"
                :key="group.key"
                class="notification-month-group"
              >
                <h3 class="notification-month-heading">{{ group.label }}</h3>
                <div class="notification-card-list">
                  <article
                    v-for="(item, itemIndex) in group.items"
                    :key="item.id"
                    class="notification-card"
                    :class="{
                      'notification-card--unread': !item.is_read,
                      'notification-card--divided': itemIndex > 0,
                    }"
                  >
                    <div class="notification-card__heading">
                      <span class="notification-card__type">
                        <i class="pi pi-megaphone notification-card__icon" aria-hidden="true" />
                        <span>公告</span>
                      </span>
                      <Tag :severity="item.is_read ? 'secondary' : 'warn'">{{
                        item.is_read ? '已讀' : '未讀'
                      }}</Tag>
                    </div>
                    <strong class="notification-card__title">{{ item.title }}</strong>
                    <div class="notification-card__tags">
                      <Tag :severity="severity(item.severity)">{{
                        severityLabel(item.severity)
                      }}</Tag>
                    </div>
                    <div class="notification-card__footer">
                      <small class="text-500"
                        >最近更新：{{ formatTimestamp(item.updated_at) }}</small
                      >
                      <Button
                        label="檢視"
                        size="small"
                        outlined
                        class="notification-view-button"
                        @click="openAnnouncement(item)"
                      />
                    </div>
                  </article>
                </div>
              </section>
            </div>
          </TabPanel>

          <TabPanel value="personal">
            <div class="personal-toolbar">
              <span class="text-sm text-500">{{ counts.personal_notifications }} 則未讀</span>
              <div class="personal-toolbar__actions">
                <Button
                  label="全部標記為已讀"
                  icon="pi pi-check-circle"
                  size="small"
                  outlined
                  class="personal-mark-all-button"
                  :disabled="!counts.personal_notifications || deletingAllPersonal"
                  @click="$emit('mark-all-personal-read')"
                />
                <Button
                  label="全部刪除"
                  icon="pi pi-trash"
                  severity="danger"
                  size="small"
                  outlined
                  class="personal-delete-all-button"
                  :loading="deletingAllPersonal"
                  :disabled="personalNotifications.length === 0 || deletingAllPersonal"
                  @click="$emit('delete-all-personal')"
                />
              </div>
            </div>
            <div v-if="personalNotifications.length === 0" class="notification-empty">
              <i class="pi pi-bell text-4xl" /><span>目前沒有個人通知</span>
            </div>
            <div v-else class="notification-groups notification-personal-groups">
              <section
                v-for="group in groupedPersonalNotifications"
                :key="group.key"
                class="notification-month-group"
              >
                <h3 class="notification-month-heading">{{ group.label }}</h3>
                <div class="notification-card-list">
                  <article
                    v-for="(item, itemIndex) in group.items"
                    :key="item.id"
                    class="notification-card"
                    :class="{
                      'notification-card--unread': !item.read_at,
                      'notification-card--divided': itemIndex > 0,
                    }"
                  >
                    <div class="notification-card__heading">
                      <span class="notification-card__type">
                        <i :class="notificationIcon(item.notification_type)" aria-hidden="true" />
                        <span>個人通知</span>
                      </span>
                      <Tag :severity="item.read_at ? 'secondary' : 'warn'">{{
                        item.read_at ? '已讀' : '未讀'
                      }}</Tag>
                    </div>
                    <strong class="notification-card__title">{{ item.title }}</strong>
                    <p class="notification-card__summary">{{ item.message }}</p>
                    <small v-if="!item.source_available" class="text-500">來源已不存在</small>
                    <div class="notification-card__footer">
                      <small class="text-500">{{ formatTimestamp(item.created_at) }}</small>
                      <div class="notification-card__actions">
                        <Button
                          label="檢視"
                          size="small"
                          outlined
                          class="notification-view-button"
                          :disabled="deletingPersonalId === item.id || deletingAllPersonal"
                          @click="openPersonal(item)"
                        />
                        <Button
                          icon="pi pi-trash"
                          severity="danger"
                          size="small"
                          outlined
                          class="notification-delete-button"
                          aria-label="刪除通知"
                          title="刪除通知"
                          :loading="deletingPersonalId === item.id"
                          :disabled="deletingPersonalId === item.id || deletingAllPersonal"
                          @click="$emit('delete-personal', item)"
                        />
                      </div>
                    </div>
                  </article>
                </div>
              </section>
            </div>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Dialog>

    <Dialog
      :visible="detailVisible"
      @update:visible="detailVisible = $event"
      modal
      :style="{ width: '520px', maxWidth: '90vw' }"
      :draggable="false"
      :header="selectedType === 'announcement' ? '公告內容' : '個人通知'"
    >
      <div v-if="selectedItem" class="notification-detail">
        <h3>{{ selectedItem.title }}</h3>
        <small class="text-500">{{
          formatTimestamp(selectedItem.updated_at || selectedItem.created_at)
        }}</small>
        <div
          v-if="selectedType === 'announcement'"
          class="markdown-content"
          v-html="renderedBody"
        />
        <p v-else>{{ selectedItem.message }}</p>
        <small v-if="selectedType === 'personal' && !selectedItem.source_available" class="text-500"
          >來源已不存在，無法開啟原留言。</small
        >
      </div>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import { formatExactDateTime24h } from '@/utils/time'

const props = defineProps({
  visible: Boolean,
  announcements: { type: Array, default: () => [] },
  personalNotifications: { type: Array, default: () => [] },
  counts: { type: Object, default: () => ({ total: 0, personal_notifications: 0 }) },
  loading: Boolean,
  deletingPersonalId: { type: Number, default: null },
  deletingAllPersonal: Boolean,
  focusType: { type: String, default: null },
  focusId: { type: Number, default: null },
})
const emit = defineEmits([
  'update:visible',
  'mark-announcement-read',
  'mark-personal-read',
  'mark-all-personal-read',
  'delete-personal',
  'delete-all-personal',
  'open-personal-source',
])
const activeTab = ref('announcements')
const detailVisible = ref(false)
const selectedItem = ref(null)
const selectedType = ref('announcement')
const renderedBody = computed(() => renderMarkdown(selectedItem.value?.body || ''))
const groupedAnnouncements = computed(() => groupItemsByMonth(props.announcements, 'updated_at'))
const groupedPersonalNotifications = computed(() =>
  groupItemsByMonth(props.personalNotifications, 'created_at')
)
const severity = (value) => (value === 'danger' ? 'danger' : 'info')
const severityLabel = (value) => (value === 'danger' ? '重要' : '一般')

function groupItemsByMonth(items, dateField) {
  const groups = new Map()
  const sortedItems = [...items]
    .map((item, index) => {
      const date = item[dateField] ? new Date(item[dateField]) : null
      const timestamp = date && !Number.isNaN(date.getTime()) ? date.getTime() : null
      return { item, date, timestamp, index }
    })
    .sort((a, b) => {
      if (a.timestamp === null && b.timestamp === null) return a.index - b.index
      if (a.timestamp === null) return 1
      if (b.timestamp === null) return -1
      return b.timestamp - a.timestamp
    })

  sortedItems.forEach(({ item, date, timestamp }) => {
    const key = timestamp === null ? 'unknown' : `${date.getFullYear()}-${date.getMonth() + 1}`
    const label =
      timestamp === null ? '日期未明' : `${date.getFullYear()}年${date.getMonth() + 1}月`
    if (!groups.has(key)) groups.set(key, { key, label, items: [] })
    groups.get(key).items.push(item)
  })

  return [...groups.values()]
}

function openAnnouncement(item) {
  selectedType.value = 'announcement'
  selectedItem.value = item
  detailVisible.value = true
  if (!item.is_read) emit('mark-announcement-read', item.id)
}
function openPersonal(item) {
  if (!item.read_at) emit('mark-personal-read', item.id)
  if (
    item.source_available &&
    ['archive_discussion_thread', 'archive_submission'].includes(item.source_type)
  ) {
    emit('open-personal-source', item)
    return
  }
  selectedType.value = 'personal'
  selectedItem.value = item
  detailVisible.value = true
}
function notificationIcon(type) {
  const icons = {
    discussion_reply: 'pi pi-reply',
    discussion_like: 'pi pi-heart-fill',
    discussion_pin: 'pi pi-bookmark-fill',
    archive_submission_approved: 'pi pi-check-circle',
    archive_submission_rejected: 'pi pi-undo',
    archive_submission_takedown: 'pi pi-eye-slash',
    comment_report_submitted: 'pi pi-flag',
    comment_report_result: 'pi pi-verified',
  }
  return `${icons[type] || 'pi pi-bell'} notification-card__icon`
}
watch(
  () => props.visible,
  (visible) => {
    if (!visible) detailVisible.value = false
  }
)
watch(
  () => props.personalNotifications,
  (items) => {
    if (
      selectedType.value === 'personal' &&
      selectedItem.value &&
      !items.some((item) => item.id === selectedItem.value.id)
    ) {
      detailVisible.value = false
      selectedItem.value = null
    }
  }
)
watch(
  () => [props.visible, props.focusType, props.focusId, props.loading],
  ([visible, type, id, loading]) => {
    if (!visible || !id || loading) return
    const items = type === 'personal' ? props.personalNotifications : props.announcements
    const item = items.find((candidate) => candidate.id === id)
    if (!item) return
    activeTab.value = type === 'personal' ? 'personal' : 'announcements'
    selectedType.value = type
    selectedItem.value = item
    detailVisible.value = true
  }
)
const formatTimestamp = (value) => formatExactDateTime24h(value)
</script>

<style scoped>
.notification-dialog-header {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
}
.notification-dialog-header__title {
  font-size: 1.25rem;
  font-weight: 600;
  line-height: 1.25;
  white-space: nowrap;
}
.notification-center-tabs {
  container-name: notification-center;
  container-type: inline-size;
  min-width: 0;
}
.notification-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 3rem 1rem;
  color: var(--text-color-secondary);
}
:deep(.notification-view-button.p-button) {
  min-inline-size: 3.25rem;
  white-space: nowrap;
}
:deep(.p-tablist-tab-list) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: 100%;
}
:deep(.p-tablist-prev-button),
:deep(.p-tablist-next-button) {
  display: none;
}
:deep(.p-tab) {
  min-width: 0;
  justify-content: center;
  white-space: nowrap;
}
:deep(.p-tabpanels) {
  padding: 0.9rem 0 0;
}
.notification-groups {
  display: grid;
  gap: 1.25rem;
}
.notification-month-group {
  display: grid;
  min-width: 0;
  gap: 0.55rem;
}
.notification-month-heading {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.9rem;
  font-weight: 600;
  line-height: 1.4;
}
.notification-month-heading::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--surface-border);
}
.notification-card-list {
  display: grid;
  gap: 0;
}
.notification-card {
  display: grid;
  min-width: 0;
  gap: 0.55rem;
  padding: 0.8rem;
  border: 1px solid var(--surface-border);
  border-radius: var(--content-border-radius);
  background: var(--surface-card);
}
.notification-card--divided {
  margin-top: 0.6rem;
  border-top: 1px solid var(--border-color);
}
.notification-card--unread {
  border-inline-start-color: var(--primary-color);
  background: var(--highlight-bg);
}
.notification-card__heading,
.notification-card__type,
.notification-card__tags,
.notification-card__footer,
.notification-card__actions,
.personal-toolbar__actions {
  display: flex;
  min-width: 0;
  align-items: center;
}
.notification-card__heading,
.notification-card__footer {
  justify-content: space-between;
  gap: 0.75rem;
}
.notification-card__actions,
.personal-toolbar__actions {
  justify-content: flex-end;
  gap: 0.4rem;
}
:deep(.notification-delete-button.p-button) {
  flex: 0 0 auto;
}
.notification-card__type {
  gap: 0.4rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}
.notification-card__icon {
  flex: 0 0 auto;
  color: var(--primary-color);
}
.notification-card__title {
  min-width: 0;
  color: var(--text-color);
  overflow-wrap: anywhere;
}
.notification-card__summary {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--text-color-secondary);
  line-height: 1.5;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.notification-card__tags {
  flex-wrap: wrap;
  gap: 0.35rem;
}
.notification-card__footer small {
  min-width: 0;
  overflow-wrap: anywhere;
}
.personal-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.personal-toolbar__actions {
  flex-wrap: wrap;
}
.notification-detail {
  max-height: 60vh;
  overflow-y: auto;
}
.notification-detail h3 {
  margin: 0 0 0.25rem;
}
.markdown-content {
  margin-top: 1rem;
  overflow-wrap: anywhere;
}
@container notification-center (max-width: 640px) {
  :deep(.p-tabpanels) {
    padding: 0.75rem 0 0;
  }
  .notification-groups {
    gap: 1rem;
  }
  .notification-card {
    gap: 0.5rem;
    padding: 0.7rem;
  }
  .personal-toolbar {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  :deep(.personal-mark-all-button.p-button) {
    margin-left: auto;
    white-space: nowrap;
  }
  .notification-card__footer {
    align-items: flex-end;
    gap: 0.55rem;
  }
  .personal-toolbar__actions {
    width: 100%;
  }
}

@media (max-width: 640px) {
  :deep(.notification-center-dialog.p-dialog) {
    width: calc(100vw - 1rem) !important;
    max-width: calc(100vw - 1rem) !important;
    max-height: calc(100dvh - 1rem);
    margin-inline: max(0.5rem, env(safe-area-inset-left));
    overflow: hidden;
  }
  :deep(.notification-center-dialog .p-dialog-header) {
    flex: 0 0 auto;
    padding: 0.85rem max(0.85rem, env(safe-area-inset-right)) 0.75rem
      max(0.85rem, env(safe-area-inset-left));
  }
  :deep(.notification-center-dialog .p-dialog-content) {
    min-height: 0;
    padding: 0 0.75rem max(0.75rem, env(safe-area-inset-bottom));
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .notification-dialog-header {
    gap: 0.4rem;
  }
  .notification-dialog-header__title {
    font-size: 1.05rem;
  }
}
</style>
