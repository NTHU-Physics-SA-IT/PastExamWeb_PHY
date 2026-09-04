<template>
  <Dialog
    :visible="visible && total > 0"
    @update:visible="$emit('update:visible', $event)"
    modal
    :style="{ width: '620px', maxWidth: '92vw' }"
    :draggable="false"
    :blockScroll="true"
    :class="{ 'notification-summary-dialog--christmas': effectiveTheme === 'christmas' }"
    :pt="{ root: { 'aria-label': $t('系統公告與通知'), 'aria-labelledby': null } }"
  >
    <template #header>
      <div class="flex align-items-center gap-2">
        <i class="pi pi-bell text-2xl" />
        <span class="text-xl font-semibold">{{ $t('系統公告與通知') }}</span>
        <Badge :value="total" severity="danger" />
      </div>
    </template>
    <div class="summary-list">
      <section v-if="summary.announcements?.length">
        <h3><i class="pi pi-megaphone mr-2" />{{ $t('公告') }}</h3>
        <article
          v-for="(item, itemIndex) in localizedAnnouncements"
          :key="`a-${item.id}`"
          class="summary-item"
          :class="{ 'summary-item--divided': itemIndex > 0 }"
        >
          <div class="summary-item__body">
            <strong>{{ item.title }}</strong>
            <small>{{ formatTimestamp(item.updated_at || item.created_at) }}</small>
            <p>{{ excerpt(item.body) }}</p>
          </div>
          <Button
            :label="$t('檢視')"
            size="small"
            outlined
            class="notification-summary-view-action review-action-preview"
            @click="$emit('view-announcement', item.id)"
          />
        </article>
      </section>
      <section v-if="summary.personal_notifications?.length">
        <h3><i class="pi pi-bell mr-2" />{{ $t('個人通知') }}</h3>
        <article
          v-for="(item, itemIndex) in localizedPersonalNotifications"
          :key="`p-${item.id}`"
          class="summary-item"
          :class="{ 'summary-item--divided': itemIndex > 0 }"
        >
          <div class="summary-item__body">
            <strong>{{ item.title }}</strong>
            <small>{{ formatTimestamp(item.created_at) }}</small>
            <p>{{ excerpt(item.message) }}</p>
          </div>
          <Button
            :label="$t('檢視')"
            size="small"
            outlined
            class="notification-summary-view-action review-action-preview"
            @click="$emit('view-personal', item.id)"
          />
        </article>
      </section>
    </div>
    <template #footer>
      <div class="summary-actions">
        <Button
          :label="$t('稍後再看')"
          severity="secondary"
          outlined
          class="notification-summary-secondary-action review-action-preview"
          @click="$emit('update:visible', false)"
        />
        <Button
          :label="$t('查看全部')"
          severity="secondary"
          outlined
          class="notification-summary-secondary-action review-action-preview"
          @click="$emit('open-center')"
        />
        <Button
          :label="$t('全部標記為已讀')"
          icon="pi pi-check-circle"
          severity="success"
          class="notification-summary-mark-all-action review-action-republish"
          @click="$emit('mark-all-read')"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  localizedAnnouncementBody,
  localizedAnnouncementTitle,
} from '@/utils/announcementNotificationPresentation'
import { localizedPersonalNotification } from '@/utils/personalNotificationPresentation'
import { formatExactDateTime24h } from '@/utils/time'
import { useTheme } from '@/utils/useTheme'

const { locale } = useI18n()
const { effectiveTheme } = useTheme()
const props = defineProps({ visible: Boolean, summary: { type: Object, required: true } })
defineEmits([
  'update:visible',
  'open-center',
  'mark-all-read',
  'view-announcement',
  'view-personal',
])
const total = computed(() => Number(props.summary?.counts?.total || 0))
const localizedAnnouncements = computed(() =>
  (props.summary?.announcements || []).map((item) => ({
    ...item,
    title: localizedAnnouncementTitle(item, locale.value),
    body: localizedAnnouncementBody(item, locale.value),
  }))
)
const localizedPersonalNotifications = computed(() =>
  (props.summary?.personal_notifications || []).map((item) => ({
    ...item,
    ...localizedPersonalNotification(item),
  }))
)
const excerpt = (value) =>
  String(value || '')
    .replace(/[#*_`>\n]/g, ' ')
    .trim()
    .slice(0, 120)
const formatTimestamp = (value) => formatExactDateTime24h(value)
</script>

<style scoped>
.summary-list {
  display: grid;
  gap: 1rem;
  max-height: 55vh;
  overflow-y: auto;
  padding-right: 0.25rem;
}
.summary-list h3 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}
.summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.75rem;
  border-inline-start: 3px solid var(--primary-color);
  background: var(--surface-ground);
  border-radius: var(--content-border-radius);
}
.summary-item--divided {
  margin-top: 0.6rem;
  border-top: 1px solid var(--border-color);
}
.summary-item__body {
  min-width: 0;
}
.summary-item strong,
.summary-item small {
  display: block;
}
.summary-item small {
  color: var(--text-color-secondary);
  margin-top: 0.2rem;
}
.summary-item p {
  margin: 0.35rem 0 0;
  overflow-wrap: anywhere;
}
.summary-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.5rem;
}
@media (max-width: 480px) {
  .summary-item {
    grid-template-columns: 1fr;
  }
  .summary-item .p-button {
    justify-self: end;
  }
}
</style>

<style>
html[data-effective-theme='christmas'] body .p-dialog.notification-summary-dialog--christmas {
  border: 1px solid rgba(222, 199, 142, 0.46);
  background: #3e5f72;
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .p-dialog-header {
  border-bottom: 1px solid rgba(222, 199, 142, 0.38);
  background: #293f52;
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .p-dialog-content,
html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .p-dialog-footer {
  background: #3e5f72;
  color: #f8f2e8;
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .p-dialog-close-button,
html[data-effective-theme='christmas'] body .notification-summary-dialog--christmas h3,
html[data-effective-theme='christmas'] body .notification-summary-dialog--christmas strong,
html[data-effective-theme='christmas'] body .notification-summary-dialog--christmas p {
  color: #f8f2e8;
}

html[data-effective-theme='christmas'] body .notification-summary-dialog--christmas .summary-item {
  border: 1px solid rgba(222, 199, 142, 0.34);
  border-inline-start: 3px solid #7cc9ed;
  background: rgba(41, 63, 82, 0.64);
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .summary-item--divided {
  border-top-color: rgba(222, 199, 142, 0.38);
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .summary-item
  small {
  color: #c5d5d2;
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .review-action-preview.p-button {
  border-color: rgba(225, 246, 252, 0.96);
  background: #d7edf5;
  color: #245368;
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .review-action-republish.p-button {
  border-color: rgba(127, 188, 145, 0.82);
  background: linear-gradient(180deg, #3d8a64 0%, #2d6c52 100%);
  color: #f5fff7;
}

html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .review-action-preview.p-button:hover,
html[data-effective-theme='christmas']
  body
  .notification-summary-dialog--christmas
  .review-action-republish.p-button:hover {
  box-shadow:
    0 0 0.34rem rgba(255, 218, 94, 0.58),
    0 0 0.72rem rgba(255, 201, 59, 0.34);
  text-shadow: 0 0 0.2rem rgba(255, 209, 72, 0.62);
}
</style>
