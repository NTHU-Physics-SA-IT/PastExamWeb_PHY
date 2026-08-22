<template>
  <section class="report-management" :aria-label="$t('回報管理')">
    <Tabs v-model:value="activeReportTab" class="mb-4">
      <TabList>
        <Tab value="archive">
          <span class="report-tab-label">
            <span>{{ $t('考古題回報') }}</span>
            <Badge
              class="admin-attention-badge admin-attention-badge--child"
              v-if="formatAttentionBadge(attentionCounts.archive_reports)"
              :value="formatAttentionBadge(attentionCounts.archive_reports)"
              severity="danger"
            />
          </span>
        </Tab>
        <Tab value="comment">
          <span class="report-tab-label">
            <span>{{ $t('留言回報') }}</span>
            <Badge
              class="admin-attention-badge admin-attention-badge--child"
              v-if="formatAttentionBadge(attentionCounts.comment_reports)"
              :value="formatAttentionBadge(attentionCounts.comment_reports)"
              severity="danger"
            />
          </span>
        </Tab>
        <Tab value="wish">
          <span class="report-tab-label">
            <span>{{ $t('許願回報') }}</span>
            <Badge
              class="admin-attention-badge admin-attention-badge--child"
              v-if="formatAttentionBadge(attentionCounts.wish_reports)"
              :value="formatAttentionBadge(attentionCounts.wish_reports)"
              severity="danger"
            />
          </span>
        </Tab>
        <Tab value="system">
          <span class="report-tab-label">
            <span>{{ $t('系統問題回報') }}</span>
            <Badge
              class="admin-attention-badge admin-attention-badge--child"
              v-if="formatAttentionBadge(attentionCounts.system_issues)"
              :value="formatAttentionBadge(attentionCounts.system_issues)"
              severity="danger"
            />
          </span>
        </Tab>
      </TabList>
    </Tabs>
    <section
      v-show="activeReportTab === 'system'"
      class="report-section"
      aria-labelledby="system-report-heading"
    >
      <div class="report-section__header report-section__header--system">
        <div class="report-section__copy">
          <h4 id="system-report-heading">{{ $t('系統問題回報') }}</h4>
          <p>{{ $t('檢視使用者提交至本站的系統問題摘要。') }}</p>
        </div>
        <div class="report-section__actions">
          <Button
            as="a"
            href="https://github.com/NTHU-Physics-SA-IT/PastExamWeb_PHY/issues"
            target="_blank"
            rel="noopener noreferrer"
            :label="$t('前往專案 Issues')"
            icon="pi pi-github"
            outlined
            size="small"
          />
          <Button
            icon="pi pi-refresh"
            :label="$t('重新整理')"
            outlined
            :loading="loading"
            @click="refreshAll"
          />
        </div>
      </div>
      <div class="report-management__filters report-management__filters--system">
        <InputText
          v-model="systemFilters.search"
          class="report-filter-search"
          :placeholder="$t('搜尋標題、回報者或內容摘要')"
          @keyup.enter="applySystemFilters"
        />
        <Select
          v-model="systemFilters.type"
          class="report-filter-select report-filter-select--primary"
          :options="systemTypeOptions"
          optionLabel="label"
          optionValue="value"
          :placeholder="$t('全部類型')"
          showClear
          @change="applySystemFilters"
        />
        <Select
          v-model="systemFilters.readState"
          class="report-filter-select report-filter-select--secondary"
          :options="systemReadStateOptions"
          optionLabel="label"
          optionValue="value"
          :aria-label="$t('系統問題回報閱讀狀態')"
          @change="applySystemFilters"
        />
        <Button
          class="report-filter-submit"
          :label="$t('搜尋')"
          icon="pi pi-search"
          outlined
          @click="applySystemFilters"
        />
      </div>
      <Message v-if="systemError" severity="error" :closable="false">{{ systemError }}</Message>
      <DataTable
        v-else
        :value="systemIssues"
        :loading="loadingSystem"
        lazy
        paginator
        :first="systemPage.first"
        :rows="systemPage.rows"
        :totalRecords="systemTotal"
        :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
        :currentPageReportTemplate="paginationReportTemplate"
        :sortField="systemPage.sortField"
        :sortOrder="systemPage.sortOrder"
        responsiveLayout="stack"
        breakpoint="1399.98px"
        class="report-management__table report-management__system-table admin-data-table admin-responsive-card-table"
        tableStyle="table-layout: fixed; min-width: 60rem"
        @page="onSystemPage"
        @sort="onSystemSort"
      >
        <template #empty>{{ $t('目前沒有系統問題回報') }}</template>
        <Column
          field="created_at"
          sortField="created_at"
          :header="$t('回報')"
          sortable
          headerClass="report-person-time-column"
          bodyClass="report-person-time-column"
          style="width: 10rem; min-width: 10rem"
          ><template #body="{ data }"
            ><div v-if="!isCardLayout" class="report-person-time">
              <span class="report-person-time__name" :title="data.reporter_name">
                {{ data.reporter_name }}
              </span>
              <time class="report-person-time__time" :datetime="data.created_at">
                {{ formatDateTime(data.created_at, true) }}
              </time>
            </div>
          </template>
        </Column>
        <Column
          field="title"
          sortField="title"
          :header="$t('標題與內容')"
          sortable
          headerClass="system-report-column"
          bodyClass="system-report-column"
          style="width: clamp(15rem, 22vw, 21.25rem)"
          ><template #body="{ data }"
            ><div v-if="!isCardLayout" class="system-report-summary">
              <strong class="system-report-summary__title" :title="data.title || $t('未命名回報')">
                {{ data.title || $t('未命名回報') }}
              </strong>
              <span class="system-report-summary__body">{{ data.description || '—' }}</span>
            </div>
            <article v-else class="report-mobile-card report-mobile-card-content">
              <header class="report-mobile-card__header report-mobile-card-header">
                <strong class="report-mobile-card-title" :title="data.title || $t('未命名回報')">
                  {{ data.title || $t('未命名回報') }}
                </strong>
                <Tag
                  class="system-read-state-tag report-mobile-card-status"
                  :severity="data.is_read ? 'secondary' : 'warn'"
                  :value="data.is_read ? $t('已讀') : $t('未讀')"
                />
                <div class="report-mobile-card-badges">
                  <Tag :value="issueTypeLabel(data.report_type)" />
                  <Tag severity="secondary" :value="$t('本地摘要')" />
                </div>
              </header>
              <div class="report-mobile-card__body">
                <section
                  class="report-mobile-card__summary report-mobile-summary-preview"
                  :aria-label="$t('內容摘要')"
                >
                  <span class="report-mobile-summary-preview__label">{{ $t('內容摘要') }}</span>
                  <p class="report-mobile-summary-preview__text">
                    {{ data.description || $t('未提供詳細描述') }}
                  </p>
                </section>
                <dl class="report-mobile-card__metadata report-mobile-info-grid">
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報者') }}</dt>
                    <dd>{{ data.reporter_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報時間') }}</dt>
                    <dd>
                      <time :datetime="data.created_at">{{
                        formatDateTime(data.created_at, true)
                      }}</time>
                    </dd>
                  </div>
                </dl>
              </div>
              <footer class="report-mobile-card__footer">
                <div class="report-row-actions">
                  <Button
                    :label="$t('檢視')"
                    icon="pi pi-search"
                    :aria-label="$t('檢視系統問題回報')"
                    :title="$t('檢視系統問題回報')"
                    size="small"
                    outlined
                    :loading="loadingSystemDetailId === data.id"
                    :disabled="loadingSystemDetailId !== null"
                    @click="openSystemReport(data)"
                  />
                  <Button
                    :label="$t('刪除')"
                    icon="pi pi-trash"
                    severity="danger"
                    :aria-label="$t('刪除系統問題回報')"
                    :title="$t('刪除系統問題回報')"
                    size="small"
                    outlined
                    :loading="deletingSystemId === data.id"
                    :disabled="deletingSystemId !== null"
                    @click="confirmDeleteSystemIssue(data)"
                  />
                </div>
              </footer></article></template
        ></Column>
        <Column
          field="report_type"
          sortField="report_type"
          :header="$t('類型')"
          sortable
          style="width: 8rem"
          ><template #body="{ data }"
            ><Tag v-if="!isCardLayout" :value="issueTypeLabel(data.report_type)" /></template
        ></Column>
        <Column :header="$t('說明')" style="width: 8rem"
          ><template #body
            ><Tag v-if="!isCardLayout" severity="secondary" :value="$t('本地摘要')" /></template
        ></Column>
        <Column
          field="read_state"
          sortField="read_state"
          :header="$t('狀態')"
          sortable
          style="width: 7rem"
          ><template #body="{ data }"
            ><Tag
              v-if="!isCardLayout"
              class="system-read-state-tag"
              :severity="data.is_read ? 'secondary' : 'warn'"
              :value="data.is_read ? $t('已讀') : $t('未讀')" /></template
        ></Column>
        <Column
          :header="$t('操作')"
          headerClass="report-actions-column report-actions-column--system"
          bodyClass="report-actions-column report-actions-column--system"
          style="width: 12rem; min-width: 12rem"
          ><template #body="{ data }"
            ><footer v-if="!isCardLayout" class="report-desktop-actions">
              <div class="report-row-actions">
                <Button
                  :label="$t('檢視')"
                  icon="pi pi-search"
                  :aria-label="$t('檢視系統問題回報')"
                  :title="$t('檢視系統問題回報')"
                  size="small"
                  outlined
                  :loading="loadingSystemDetailId === data.id"
                  :disabled="loadingSystemDetailId !== null"
                  @click="openSystemReport(data)"
                />
                <Button
                  :label="$t('刪除')"
                  icon="pi pi-trash"
                  severity="danger"
                  :aria-label="$t('刪除系統問題回報')"
                  :title="$t('刪除系統問題回報')"
                  size="small"
                  outlined
                  :loading="deletingSystemId === data.id"
                  :disabled="deletingSystemId !== null"
                  @click="confirmDeleteSystemIssue(data)"
                />
              </div></footer></template
        ></Column>
      </DataTable>

      <Dialog
        v-model:visible="systemDetailVisible"
        class="report-management-dialog"
        modal
        :header="$t('系統問題回報詳情')"
        :style="{ width: '680px', maxWidth: '94vw' }"
        :contentStyle="{ maxHeight: '70vh', overflowY: 'auto' }"
        :draggable="false"
      >
        <div v-if="selectedSystemReport" class="system-report-detail">
          <dl class="report-review__meta">
            <div>
              <dt>{{ $t('回報者') }}</dt>
              <dd>{{ selectedSystemReport.reporter_name }}</dd>
            </div>
            <div>
              <dt>{{ $t('回報時間') }}</dt>
              <dd>{{ formatDateTime(selectedSystemReport.created_at, true) }}</dd>
            </div>
            <div>
              <dt>{{ $t('問題類型') }}</dt>
              <dd>{{ issueTypeLabel(selectedSystemReport.report_type) }}</dd>
            </div>
            <div>
              <dt>{{ $t('聯絡方式') }}</dt>
              <dd>{{ selectedSystemReport.contact || $t('未提供') }}</dd>
            </div>
          </dl>
          <section class="report-review__content-field system-report-detail__content">
            <strong class="report-review__content-label">{{ $t('問題標題') }}</strong>
            <div class="report-review__content-block">
              <p>{{ selectedSystemReport.title || $t('未命名回報') }}</p>
            </div>
          </section>
          <section class="report-review__content-field system-report-detail__content">
            <strong class="report-review__content-label">{{ $t('完整詳細描述') }}</strong>
            <div class="report-review__content-block">
              <p>{{ selectedSystemReport.description || '—' }}</p>
            </div>
          </section>
          <section class="system-report-detail__note">
            <Tag severity="secondary" :value="$t('本地摘要')" />
            <p>{{ $t('此紀錄保存在本站，無法確認使用者是否已在 GitHub 正式建立 Issue。') }}</p>
          </section>
          <section class="system-report-detail__read-state">
            <div class="system-report-detail__read-heading">
              <strong>{{ $t('已讀狀態') }}</strong>
              <Tag
                class="system-read-state-tag"
                :severity="selectedSystemReport.is_read ? 'secondary' : 'warn'"
                :value="selectedSystemReport.is_read ? $t('已讀') : $t('未讀')"
              />
            </div>
            <label class="system-report-detail__read-option">
              <Checkbox v-model="systemReadForm" binary :disabled="systemReadSaving" />
              {{ $t('標記為已讀') }}
            </label>
            <small>{{ $t('閱讀狀態由管理員手動維護，開啟此視窗不會自動標記已讀。') }}</small>
            <small v-if="selectedSystemReport.read_at">
              {{ $t('最後標記：') }}{{ selectedSystemReport.read_by_username || $t('管理員') }}，{{
                formatDateTime(selectedSystemReport.read_at, true)
              }}
            </small>
          </section>
          <div class="report-review__actions">
            <span class="report-review__spacer" />
            <Button
              :label="$t('關閉')"
              severity="secondary"
              outlined
              @click="systemDetailVisible = false"
            />
            <Button
              :label="$t('儲存')"
              icon="pi pi-save"
              :loading="systemReadSaving"
              :disabled="systemReadSaving"
              @click="saveSystemReadState"
            />
          </div>
        </div>
      </Dialog>
    </section>

    <section
      v-show="activeReportTab === 'comment'"
      class="report-section"
      aria-labelledby="comment-report-heading"
    >
      <div class="report-section__header">
        <div>
          <h4 id="comment-report-heading">{{ $t('留言回報') }}</h4>
          <p>{{ $t('依狀態、原因與內容搜尋留言回報，並開啟詳情完成審核。') }}</p>
        </div>
      </div>
      <div class="report-management__filters">
        <InputText
          v-model="commentFilters.search"
          class="report-filter-search"
          :placeholder="$t('搜尋留言、課程或使用者')"
          @keyup.enter="applyCommentFilters"
        />
        <Select
          v-model="commentFilters.status"
          class="report-filter-select report-filter-select--primary"
          :options="statusOptions"
          optionLabel="label"
          optionValue="value"
          :placeholder="$t('全部狀態')"
          showClear
          @change="applyCommentFilters"
        />
        <Select
          v-model="commentFilters.reason"
          class="report-filter-select report-filter-select--secondary"
          :options="reasonOptions"
          optionLabel="label"
          optionValue="value"
          :placeholder="$t('全部原因')"
          showClear
          @change="applyCommentFilters"
        />
        <Button
          class="report-filter-submit"
          :label="$t('搜尋')"
          icon="pi pi-search"
          outlined
          @click="applyCommentFilters"
        />
      </div>
      <Message v-if="commentError" severity="error" :closable="false">{{ commentError }}</Message>
      <DataTable
        v-else
        :value="commentReports"
        :loading="loadingComments"
        lazy
        paginator
        :first="commentPage.first"
        :rows="commentPage.rows"
        :totalRecords="commentTotal"
        :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
        :currentPageReportTemplate="paginationReportTemplate"
        :sortField="commentPage.sortField"
        :sortOrder="commentPage.sortOrder"
        responsiveLayout="stack"
        breakpoint="1399.98px"
        class="report-management__table report-management__comment-table admin-data-table admin-responsive-card-table"
        tableStyle="table-layout: fixed; min-width: 75rem"
        @page="onCommentPage"
        @sort="onCommentSort"
      >
        <template #empty>{{ $t('目前沒有符合條件的留言回報') }}</template>
        <Column
          field="created_at"
          sortField="created_at"
          :header="$t('回報')"
          sortable
          headerClass="report-person-time-column"
          bodyClass="report-person-time-column"
          style="width: 9.5rem; min-width: 9.5rem"
          ><template #body="{ data }"
            ><div v-if="!isCardLayout" class="report-person-time">
              <span class="report-person-time__name" :title="data.reporter_name">
                {{ data.reporter_name }}
              </span>
              <time class="report-person-time__time" :datetime="data.created_at">
                {{ formatDateTime(data.created_at, true) }}
              </time>
            </div>
          </template>
        </Column>
        <Column
          field="reason"
          sortField="reason"
          :header="$t('原因與留言摘要')"
          sortable
          headerClass="comment-report-content-column"
          bodyClass="comment-report-content-column"
          style="width: clamp(16rem, 24vw, 20rem)"
          ><template #body="{ data }"
            ><div
              v-if="!isCardLayout"
              class="comment-report-content"
              :title="data.comment_content_snapshot"
            >
              <strong class="comment-report-content__reason" :title="reasonLabel(data.reason)">
                {{ reasonLabel(data.reason) }}
              </strong>
              <span class="comment-report-content__summary">{{
                data.comment_content_snapshot || '—'
              }}</span>
            </div>
            <article v-else class="report-mobile-card report-mobile-card-content">
              <header class="report-mobile-card__header report-mobile-card-header">
                <strong class="report-mobile-card-title" :title="reasonLabel(data.reason)">
                  {{ reasonLabel(data.reason) }}
                </strong>
                <Tag
                  class="report-mobile-card-status"
                  :severity="statusSeverity(data.status)"
                  :value="statusLabel(data.status)"
                />
              </header>
              <div class="report-mobile-card__body">
                <section
                  class="report-mobile-card__summary report-mobile-summary-preview"
                  :aria-label="$t('留言摘要')"
                >
                  <span class="report-mobile-summary-preview__label">{{ $t('留言摘要') }}</span>
                  <p class="report-mobile-summary-preview__text">
                    {{ data.comment_content_snapshot || $t('無留言摘要') }}
                  </p>
                </section>
                <dl
                  class="report-mobile-card__metadata report-mobile-info-grid report-mobile-info-grid--comment"
                >
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報者') }}</dt>
                    <dd>{{ data.reporter_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報時間') }}</dt>
                    <dd>
                      <time :datetime="data.created_at">{{
                        formatDateTime(data.created_at, true)
                      }}</time>
                    </dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('留言者') }}</dt>
                    <dd>{{ data.comment_author_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item report-mobile-info-item--wide">
                    <dt>{{ $t('課程／考古題') }}</dt>
                    <dd>{{ localizedCourseSnapshotName(data) }} · {{ data.archive_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('審核人') }}</dt>
                    <dd>{{ data.reviewer_name || $t('尚未審核') }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('審核時間') }}</dt>
                    <dd>{{ formatReviewTime(data.reviewed_at) }}</dd>
                  </div>
                </dl>
              </div>
              <footer class="report-mobile-card__footer">
                <div class="report-row-actions">
                  <Button
                    :label="isFinal(data.status) ? $t('檢視') : $t('檢視／審核')"
                    icon="pi pi-search"
                    :aria-label="$t('檢視或審核留言回報')"
                    :title="$t('檢視或審核留言回報')"
                    size="small"
                    outlined
                    @click="openCommentReport(data.id)"
                  />
                  <Button
                    :label="$t('刪除')"
                    icon="pi pi-trash"
                    severity="danger"
                    :aria-label="$t('刪除留言回報')"
                    :title="$t('刪除留言回報')"
                    size="small"
                    outlined
                    :loading="deletingCommentId === data.id"
                    :disabled="deletingCommentId !== null"
                    @click="confirmDeleteCommentReport(data)"
                  />
                </div>
              </footer>
            </article>
          </template>
        </Column>
        <Column
          field="comment_author_name"
          sortField="comment_author"
          :header="$t('留言者')"
          sortable
          headerClass="report-user-column"
          bodyClass="report-user-column"
          style="width: 7rem; min-width: 7rem"
          ><template #body="{ data }"
            ><span
              v-if="!isCardLayout"
              class="report-user-cell__text"
              :title="data.comment_author_name"
              >{{ data.comment_author_name }}</span
            ></template
          ></Column
        >
        <Column
          sortField="course_archive"
          :header="$t('課程／考古題')"
          sortable
          style="width: 11rem"
          ><template #body="{ data }"
            ><div v-if="!isCardLayout" class="report-management__summary">
              <span>{{ localizedCourseSnapshotName(data) }}</span
              ><small>{{ data.archive_name }}</small>
            </div></template
          ></Column
        >
        <Column field="status" sortField="status" :header="$t('狀態')" sortable style="width: 8rem"
          ><template #body="{ data }"
            ><Tag
              v-if="!isCardLayout"
              :severity="statusSeverity(data.status)"
              :value="statusLabel(data.status)"
          /></template>
        </Column>
        <Column
          field="reviewed_at"
          sortField="reviewed_at"
          :header="$t('審核')"
          sortable
          headerClass="report-review-column"
          bodyClass="report-review-column"
          style="width: 10rem; min-width: 10rem"
          ><template #body="{ data }"
            ><div v-if="!isCardLayout" class="report-person-time">
              <span
                class="report-person-time__name"
                :class="{ 'report-person-time__name--empty': !data.reviewer_name }"
                :title="data.reviewer_name || $t('尚未審核')"
              >
                {{ data.reviewer_name || $t('尚未審核') }}
              </span>
              <time
                v-if="data.reviewed_at"
                class="report-person-time__time"
                :datetime="data.reviewed_at"
              >
                {{ formatDateTime(data.reviewed_at, true) }}
              </time>
              <span v-else class="report-person-time__time">--</span>
            </div>
          </template>
        </Column>
        <Column
          :header="$t('操作')"
          headerClass="report-actions-column"
          bodyClass="report-actions-column"
          style="width: 17rem; min-width: 17rem"
          ><template #body="{ data }"
            ><footer v-if="!isCardLayout" class="report-desktop-actions">
              <div class="report-row-actions">
                <Button
                  :label="isFinal(data.status) ? $t('檢視') : $t('檢視／審核')"
                  icon="pi pi-search"
                  :aria-label="$t('檢視或審核留言回報')"
                  :title="$t('檢視或審核留言回報')"
                  size="small"
                  outlined
                  @click="openCommentReport(data.id)"
                />
                <Button
                  :label="$t('刪除')"
                  icon="pi pi-trash"
                  severity="danger"
                  :aria-label="$t('刪除留言回報')"
                  :title="$t('刪除留言回報')"
                  size="small"
                  outlined
                  :loading="deletingCommentId === data.id"
                  :disabled="deletingCommentId !== null"
                  @click="confirmDeleteCommentReport(data)"
                />
              </div></footer></template
        ></Column>
      </DataTable>
    </section>

    <section
      v-show="activeReportTab === 'archive'"
      class="report-section"
      aria-labelledby="archive-report-heading"
      :aria-busy="archiveListState.loading"
    >
      <div class="report-section__header">
        <div>
          <h4 id="archive-report-heading">{{ $t('考古題回報') }}</h4>
          <p>{{ $t('依課程、考古題、回報者、原因與狀態搜尋，並完成審核。') }}</p>
        </div>
      </div>
      <div class="report-management__filters">
        <InputText
          v-model="archiveFilters.search"
          class="report-filter-search"
          :placeholder="$t('搜尋回報者、課程、考試、教師或編號')"
          @keyup.enter="applyArchiveFilters"
        />
        <Select
          v-model="archiveFilters.status"
          class="report-filter-select report-filter-select--primary"
          :options="statusOptions"
          optionLabel="label"
          optionValue="value"
          :placeholder="$t('全部狀態')"
          showClear
          @change="applyArchiveFilters"
        />
        <Select
          v-model="archiveFilters.reason"
          class="report-filter-select report-filter-select--secondary"
          :options="archiveReasonOptions"
          optionLabel="label"
          optionValue="value"
          :placeholder="$t('全部原因')"
          showClear
          @change="applyArchiveFilters"
        />
        <Button
          class="report-filter-submit"
          :label="$t('搜尋')"
          icon="pi pi-search"
          outlined
          @click="applyArchiveFilters"
        />
      </div>
      <Message v-if="archiveListState.error" severity="error" :closable="false">
        {{ archiveListState.error }}
      </Message>
      <DataTable
        v-else
        :value="archiveReports"
        :loading="archiveListState.loading"
        lazy
        paginator
        :first="archiveListState.first"
        :rows="archiveListState.rows"
        :totalRecords="archiveListState.total"
        :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
        :currentPageReportTemplate="paginationReportTemplate"
        :sortField="archiveListState.sortField"
        :sortOrder="archiveListState.sortOrder"
        responsiveLayout="stack"
        breakpoint="1399.98px"
        class="report-management__table report-management__archive-table admin-data-table admin-responsive-card-table"
        tableStyle="table-layout: fixed; min-width: 72rem"
        @page="onArchivePage"
        @sort="onArchiveSort"
      >
        <template #empty>{{ $t('目前沒有符合條件的考古題回報') }}</template>
        <Column
          field="created_at"
          sortField="created_at"
          :header="$t('回報')"
          sortable
          style="width: 10rem"
        >
          <template #body="{ data }">
            <div v-if="!isCardLayout" class="report-person-time">
              <span class="report-person-time__name">{{ data.reporter_name }}</span>
              <time class="report-person-time__time" :datetime="data.created_at">{{
                formatDateTime(data.created_at, true)
              }}</time>
            </div>
          </template>
        </Column>
        <Column
          field="reason"
          sortField="reason"
          :header="$t('原因與摘要')"
          sortable
          style="width: 20rem"
        >
          <template #body="{ data }">
            <div v-if="!isCardLayout" class="comment-report-content">
              <strong class="comment-report-content__reason">{{
                archiveReasonLabel(data.reason)
              }}</strong>
              <span class="comment-report-content__summary">{{
                data.supplementary_detail || $t('未提供補充說明')
              }}</span>
            </div>
            <article v-else class="report-mobile-card report-mobile-card-content">
              <header class="report-mobile-card__header report-mobile-card-header">
                <strong class="report-mobile-card-title">{{
                  archiveReasonLabel(data.reason)
                }}</strong>
                <Tag
                  class="report-mobile-card-status"
                  :severity="statusSeverity(data.status)"
                  :value="statusLabel(data.status)"
                />
              </header>
              <div class="report-mobile-card__body">
                <section class="report-mobile-card__summary report-mobile-summary-preview">
                  <span class="report-mobile-summary-preview__label">{{ $t('補充說明') }}</span>
                  <p class="report-mobile-summary-preview__text">
                    {{ data.supplementary_detail || $t('未提供補充說明') }}
                  </p>
                </section>
                <dl class="report-mobile-card__metadata report-mobile-info-grid">
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報者') }}</dt>
                    <dd>{{ data.reporter_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報時間') }}</dt>
                    <dd>{{ formatDateTime(data.created_at, true) }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('課程名稱') }}</dt>
                    <dd>{{ localizedCourseSnapshotName(data) }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('考試名稱') }}</dt>
                    <dd>{{ data.archive_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item report-mobile-info-item--wide">
                    <dt>{{ $t('考古題編號') }}</dt>
                    <dd>#{{ data.archive_id_snapshot }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('審核人') }}</dt>
                    <dd>{{ data.reviewer_name || $t('尚未審核') }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('審核時間') }}</dt>
                    <dd>{{ formatReviewTime(data.reviewed_at) }}</dd>
                  </div>
                </dl>
              </div>
              <footer class="report-mobile-card__footer">
                <div class="report-row-actions">
                  <Button
                    :label="isFinal(data.status) ? $t('檢視') : $t('檢視／審核')"
                    icon="pi pi-search"
                    :aria-label="$t('檢視或審核考古題回報')"
                    :title="$t('檢視或審核考古題回報')"
                    size="small"
                    outlined
                    @click="openArchiveReport(data.id)"
                  />
                  <Button
                    :label="$t('刪除')"
                    icon="pi pi-trash"
                    severity="danger"
                    :aria-label="$t('刪除考古題回報')"
                    :title="$t('刪除考古題回報')"
                    size="small"
                    outlined
                    :loading="deletingArchiveId === data.id"
                    @click="confirmDeleteArchiveReport(data)"
                  />
                </div>
              </footer>
            </article>
          </template>
        </Column>
        <Column
          sortField="course_archive"
          :header="$t('課程／考古題')"
          sortable
          style="width: 14rem"
        >
          <template #body="{ data }">
            <div v-if="!isCardLayout" class="report-management__summary">
              <span>{{ localizedCourseSnapshotName(data) }}</span>
              <small
                >{{ data.archive_name }} · #{{ data.archive_id_snapshot }} ·
                {{ data.professor }}</small
              >
            </div>
          </template>
        </Column>
        <Column field="status" sortField="status" :header="$t('狀態')" sortable style="width: 8rem">
          <template #body="{ data }">
            <Tag
              v-if="!isCardLayout"
              :severity="statusSeverity(data.status)"
              :value="statusLabel(data.status)"
            />
          </template>
        </Column>
        <Column
          field="reviewed_at"
          sortField="reviewed_at"
          :header="$t('審核')"
          sortable
          style="width: 10rem"
        >
          <template #body="{ data }">
            <div v-if="!isCardLayout" class="report-person-time">
              <span class="report-person-time__name">{{
                data.reviewer_name || $t('尚未審核')
              }}</span>
              <time
                v-if="data.reviewed_at"
                class="report-person-time__time"
                :datetime="data.reviewed_at"
              >
                {{ formatDateTime(data.reviewed_at, true) }}
              </time>
              <span v-else class="report-person-time__time">--</span>
            </div>
          </template>
        </Column>
        <Column :header="$t('操作')" style="width: 16rem">
          <template #body="{ data }">
            <div v-if="!isCardLayout" class="report-row-actions">
              <Button
                :label="isFinal(data.status) ? $t('檢視') : $t('檢視／審核')"
                icon="pi pi-search"
                :aria-label="$t('檢視或審核考古題回報')"
                :title="$t('檢視或審核考古題回報')"
                size="small"
                outlined
                @click="openArchiveReport(data.id)"
              />
              <Button
                :label="$t('刪除')"
                icon="pi pi-trash"
                severity="danger"
                :aria-label="$t('刪除考古題回報')"
                :title="$t('刪除考古題回報')"
                size="small"
                outlined
                :loading="deletingArchiveId === data.id"
                @click="confirmDeleteArchiveReport(data)"
              />
            </div>
          </template>
        </Column>
      </DataTable>
    </section>

    <section
      v-show="activeReportTab === 'wish'"
      class="report-section"
      aria-labelledby="wish-report-heading"
    >
      <div class="report-section__header">
        <div>
          <h4 id="wish-report-heading">{{ $t('許願回報') }}</h4>
          <p>{{ $t('審核使用者針對考古許願提交的回報。') }}</p>
        </div>
      </div>
      <div class="report-management__filters report-management__filters--compact">
        <InputText
          v-model="wishFilters.search"
          class="report-filter-search"
          :placeholder="$t('搜尋許願或回報內容')"
          @keyup.enter="applyWishFilters"
        />
        <Select
          v-model="wishFilters.status"
          class="report-filter-select report-filter-select--primary"
          :options="statusOptions"
          optionLabel="label"
          optionValue="value"
          :placeholder="$t('全部狀態')"
          showClear
          @change="applyWishFilters"
        />
        <Button
          class="report-filter-submit"
          :label="$t('搜尋')"
          icon="pi pi-search"
          outlined
          @click="applyWishFilters"
        />
      </div>
      <Message v-if="wishError" severity="error" :closable="false">{{ wishError }}</Message>
      <DataTable
        v-else
        :value="wishReports"
        :loading="wishLoading"
        lazy
        paginator
        :first="wishPage.first"
        :rows="wishPage.rows"
        :totalRecords="wishTotal"
        :rowsPerPageOptions="ADMIN_PAGE_SIZE_OPTIONS"
        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown CurrentPageReport"
        :currentPageReportTemplate="paginationReportTemplate"
        :sortField="wishPage.sortField"
        :sortOrder="wishPage.sortOrder"
        responsiveLayout="stack"
        breakpoint="1399.98px"
        class="report-management__table report-management__wish-table admin-data-table admin-responsive-card-table"
        tableStyle="table-layout: fixed; min-width: 68rem"
        @page="onWishPage"
        @sort="onWishSort"
      >
        <template #empty>{{ $t('目前沒有符合條件的許願回報') }}</template>
        <Column
          field="created_at"
          sortField="created_at"
          :header="$t('回報')"
          sortable
          style="width: 10rem"
        >
          <template #body="{ data }">
            <div v-if="!isCardLayout" class="report-person-time">
              <span class="report-person-time__name" :title="data.reporter_name">{{
                data.reporter_name
              }}</span>
              <time class="report-person-time__time" :datetime="data.created_at">{{
                formatDateTime(data.created_at, true)
              }}</time>
            </div>
          </template>
        </Column>
        <Column
          field="reason"
          sortField="reason"
          :header="$t('回報原因')"
          sortable
          style="width: 13rem"
        >
          <template #body="{ data }">
            <strong
              v-if="!isCardLayout"
              class="comment-report-content__reason"
              :title="reasonLabel(data.reason)"
              >{{ reasonLabel(data.reason) }}</strong
            >
            <article v-else class="report-mobile-card report-mobile-card-content">
              <header class="report-mobile-card__header report-mobile-card-header">
                <strong class="report-mobile-card-title" :title="reasonLabel(data.reason)">{{
                  reasonLabel(data.reason)
                }}</strong>
                <Tag
                  class="report-mobile-card-status"
                  :severity="statusSeverity(data.status)"
                  :value="statusLabel(data.status)"
                />
              </header>
              <div class="report-mobile-card__body">
                <section
                  class="report-mobile-card__summary report-mobile-summary-preview"
                  :aria-label="$t('許願標題')"
                >
                  <span class="report-mobile-summary-preview__label">{{ $t('許願標題') }}</span>
                  <p class="report-mobile-summary-preview__text">
                    {{ data.wish_title }}
                  </p>
                </section>
                <dl
                  class="report-mobile-card__metadata report-mobile-info-grid report-mobile-info-grid--wish"
                >
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報者') }}</dt>
                    <dd>{{ data.reporter_name }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('回報時間') }}</dt>
                    <dd>
                      <time :datetime="data.created_at">{{
                        formatDateTime(data.created_at, true)
                      }}</time>
                    </dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('許願者') }}</dt>
                    <dd>{{ data.wisher_name || $t('已刪除使用者') }}</dd>
                  </div>
                  <div class="report-mobile-info-item report-mobile-info-item--wide">
                    <dt>{{ $t('許願目標') }}</dt>
                    <dd>{{ formatWishTargetSummary(data.target_summary) }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('審核人') }}</dt>
                    <dd>{{ data.reviewer_name || $t('尚未審核') }}</dd>
                  </div>
                  <div class="report-mobile-info-item">
                    <dt>{{ $t('審核時間') }}</dt>
                    <dd>{{ formatReviewTime(data.reviewed_at) }}</dd>
                  </div>
                </dl>
              </div>
              <footer class="report-mobile-card__footer">
                <div class="report-row-actions">
                  <Button
                    :label="isFinal(data.status) ? $t('檢視') : $t('檢視／審核')"
                    icon="pi pi-search"
                    :aria-label="$t('檢視或審核許願回報')"
                    :title="$t('檢視或審核許願回報')"
                    size="small"
                    outlined
                    @click="openWishReport(data.id)"
                  />
                  <Button
                    :label="$t('刪除')"
                    icon="pi pi-trash"
                    severity="danger"
                    :aria-label="$t('刪除許願回報')"
                    :title="$t('刪除許願回報')"
                    size="small"
                    outlined
                    :loading="deletingWishReportId === data.id"
                    :disabled="deletingWishReportId !== null"
                    @click="confirmDeleteWishReport(data)"
                  />
                </div>
              </footer>
            </article>
          </template>
        </Column>
        <Column
          field="wisher_name"
          sortField="wisher"
          :header="$t('許願者')"
          sortable
          style="width: 9rem"
        >
          <template #body="{ data }"
            ><span
              v-if="!isCardLayout"
              class="report-user-cell__text"
              :title="data.wisher_name || $t('已刪除使用者')"
              >{{ data.wisher_name || $t('已刪除使用者') }}</span
            ></template
          >
        </Column>
        <Column sortField="wish_target" :header="$t('許願目標')" sortable>
          <template #body="{ data }"
            ><div
              v-if="!isCardLayout"
              class="comment-report-content"
              :title="formatWishTargetSummary(data.target_summary)"
            >
              <strong class="comment-report-content__reason">{{ data.wish_title }}</strong
              ><span class="comment-report-content__summary">{{
                formatWishTargetSummary(data.target_summary)
              }}</span>
            </div></template
          >
        </Column>
        <Column field="status" sortField="status" :header="$t('狀態')" sortable style="width: 8rem"
          ><template #body="{ data }"
            ><Tag
              v-if="!isCardLayout"
              :severity="statusSeverity(data.status)"
              :value="statusLabel(data.status)" /></template
        ></Column>
        <Column
          field="reviewed_at"
          sortField="reviewed_at"
          :header="$t('審核')"
          sortable
          headerClass="report-review-column"
          bodyClass="report-review-column"
          style="width: 10rem; min-width: 10rem"
          ><template #body="{ data }"
            ><div v-if="!isCardLayout" class="report-person-time">
              <span
                class="report-person-time__name"
                :class="{ 'report-person-time__name--empty': !data.reviewer_name }"
                :title="data.reviewer_name || $t('尚未審核')"
              >
                {{ data.reviewer_name || $t('尚未審核') }}
              </span>
              <time
                v-if="data.reviewed_at"
                class="report-person-time__time"
                :datetime="data.reviewed_at"
              >
                {{ formatDateTime(data.reviewed_at, true) }}
              </time>
              <span v-else class="report-person-time__time">--</span>
            </div>
          </template>
        </Column>
        <Column :header="$t('操作')" style="width: 17rem">
          <template #body="{ data }"
            ><footer v-if="!isCardLayout" class="report-desktop-actions">
              <div class="report-row-actions">
                <Button
                  :label="isFinal(data.status) ? $t('檢視') : $t('檢視／審核')"
                  icon="pi pi-search"
                  :aria-label="$t('檢視或審核許願回報')"
                  :title="$t('檢視或審核許願回報')"
                  size="small"
                  outlined
                  @click="openWishReport(data.id)"
                /><Button
                  :label="$t('刪除')"
                  icon="pi pi-trash"
                  :aria-label="$t('刪除許願回報')"
                  :title="$t('刪除許願回報')"
                  size="small"
                  severity="danger"
                  outlined
                  :loading="deletingWishReportId === data.id"
                  :disabled="deletingWishReportId !== null"
                  @click="confirmDeleteWishReport(data)"
                />
              </div></footer
          ></template>
        </Column>
      </DataTable>
    </section>

    <Dialog
      v-model:visible="wishReviewVisible"
      class="report-management-dialog"
      modal
      :header="$t('許願回報審核')"
      :style="{ width: '720px', maxWidth: '94vw' }"
      :draggable="false"
    >
      <div v-if="selectedWishReport" class="report-review">
        <div class="report-review__title">
          <div>
            <strong>{{ $t('許願回報') }}</strong
            ><small>{{ formatDateTime(selectedWishReport.created_at) }}</small>
          </div>
          <Tag
            :severity="statusSeverity(selectedWishReport.status)"
            :value="statusLabel(selectedWishReport.status)"
          />
        </div>
        <dl class="report-review__meta">
          <div>
            <dt>{{ $t('回報者') }}</dt>
            <dd>{{ selectedWishReport.reporter_name }}</dd>
          </div>
          <div>
            <dt>{{ $t('許願者') }}</dt>
            <dd>{{ selectedWishReport.wisher_name || $t('已刪除使用者') }}</dd>
          </div>
          <div>
            <dt>{{ $t('回報原因') }}</dt>
            <dd>{{ reasonLabel(selectedWishReport.reason) }}</dd>
          </div>
          <div>
            <dt>{{ $t('許願目標') }}</dt>
            <dd>{{ formatWishTargetSummary(selectedWishReport.target_summary) }}</dd>
          </div>
        </dl>
        <section v-if="selectedWishReport.custom_message" class="report-review__content-field">
          <strong class="report-review__content-label">{{ $t('補充說明') }}</strong>
          <div class="report-review__content-block">
            <p>{{ selectedWishReport.custom_message }}</p>
          </div>
        </section>
        <p v-if="isFinal(selectedWishReport.status)" class="report-review__response">
          <strong>{{ $t('管理員答覆：') }}</strong
          >{{ selectedWishReport.admin_response || $t('未提供答覆') }}
        </p>
        <Message
          v-if="isFinal(selectedWishReport.status)"
          class="report-review__message"
          severity="info"
          :closable="false"
        >
          {{ $t('審核結果已送出，無法修改。') }}
        </Message>
        <div v-if="!isFinal(selectedWishReport.status)" class="report-review__field">
          <label for="wish-review-status">{{ $t('審核結果') }}</label>
          <Select
            inputId="wish-review-status"
            v-model="wishReviewForm.status"
            :options="statusOptions.filter((item) => item.value !== 'pending')"
            optionLabel="label"
            optionValue="value"
            :disabled="wishReviewSaving"
          />
        </div>
        <div v-if="!isFinal(selectedWishReport.status)" class="report-review__field">
          <label for="wish-admin-response">{{ $t('給回報者的答覆') }}</label>
          <Textarea
            id="wish-admin-response"
            v-model="wishReviewForm.admin_response"
            rows="4"
            maxlength="1000"
            :placeholder="$t('可留空；若未提供答覆，通知中將顯示「未提供答覆」。')"
            :disabled="wishReviewSaving"
          />
          <small>{{ wishReviewForm.admin_response.length }}/1000</small>
        </div>
        <div class="report-review__actions">
          <Button
            :label="$t('關閉')"
            severity="secondary"
            text
            @click="wishReviewVisible = false"
          /><Button
            v-if="!isFinal(selectedWishReport.status)"
            :label="$t('確認送出')"
            icon="pi pi-check"
            :loading="wishReviewSaving"
            :disabled="!['upheld', 'dismissed'].includes(wishReviewForm.status)"
            @click="confirmSaveWishReview"
          />
        </div>
      </div>
    </Dialog>

    <Dialog
      v-model:visible="reviewVisible"
      class="report-management-dialog"
      modal
      :header="$t('留言回報審核')"
      :style="{ width: '720px', maxWidth: '94vw' }"
      :draggable="false"
    >
      <div v-if="selectedReport" class="report-review">
        <div class="report-review__title">
          <div>
            <strong>{{ $t('留言回報') }}</strong>
            <small>{{ formatDateTime(selectedReport.created_at) }}</small>
          </div>
          <Tag
            :severity="statusSeverity(selectedReport.status)"
            :value="statusLabel(selectedReport.status)"
          />
        </div>
        <dl class="report-review__meta">
          <div>
            <dt>{{ $t('回報者') }}</dt>
            <dd>{{ selectedReport.reporter_name }}</dd>
          </div>
          <div>
            <dt>{{ $t('留言作者') }}</dt>
            <dd>{{ selectedReport.comment_author_name }}</dd>
          </div>
          <div>
            <dt>{{ $t('回報原因') }}</dt>
            <dd>{{ reasonLabel(selectedReport.reason) }}</dd>
          </div>
          <div>
            <dt>{{ $t('建立時間') }}</dt>
            <dd>{{ formatDateTime(selectedReport.created_at) }}</dd>
          </div>
          <div>
            <dt>{{ $t('所屬考古題') }}</dt>
            <dd>
              {{ localizedCourseSnapshotName(selectedReport) }} · {{ selectedReport.archive_name }}
            </dd>
          </div>
          <div class="report-review__thread">
            <dt>Thread</dt>
            <dd class="report-review__thread-content">
              <span class="report-review__thread-id">{{
                selectedReport.thread_id ? `#${selectedReport.thread_id}` : '—'
              }}</span>
              <Tag
                class="soft-badge soft-badge--info report-review__thread-hint"
                severity="info"
                :value="$t('此識別碼代表該回覆串的第一則留言，用於定位討論串。')"
              />
            </dd>
          </div>
        </dl>
        <section class="report-review__content-field">
          <strong class="report-review__content-label">{{ $t('留言內容快照') }}</strong>
          <div class="report-review__content-block">
            <p>{{ selectedReport.comment_content_snapshot }}</p>
            <small>{{ formatDateTime(selectedReport.comment_created_at_snapshot) }}</small>
          </div>
        </section>
        <Message
          v-if="!selectedReport.source_exists"
          class="report-review__message"
          severity="warn"
          :closable="false"
        >
          {{ $t('來源留言已不存在；仍可根據快照完成審核。') }}
        </Message>
        <section class="report-review__content-field">
          <strong class="report-review__content-label">{{ $t('回報者補充') }}</strong>
          <div class="report-review__content-block">
            <p>{{ selectedReport.custom_message || $t('未提供補充') }}</p>
          </div>
        </section>
        <p v-if="isFinal(selectedReport.status)" class="report-review__response">
          <strong>{{ $t('管理員答覆：') }}</strong
          >{{ selectedReport.admin_response || $t('未提供答覆') }}
        </p>
        <Message
          v-if="isFinal(selectedReport.status)"
          class="report-review__message"
          severity="info"
          :closable="false"
        >
          {{ $t('審核結果已送出，無法修改。') }}
        </Message>
        <div v-if="!isFinal(selectedReport.status)" class="report-review__field">
          <label for="report-review-status">{{ $t('審核結果') }}</label>
          <Select
            inputId="report-review-status"
            v-model="reviewForm.status"
            :options="reviewStatusOptions"
            optionLabel="label"
            optionValue="value"
            :disabled="reviewSaving"
          />
        </div>
        <div v-if="!isFinal(selectedReport.status)" class="report-review__field">
          <label for="report-admin-response">{{ $t('給回報者的答覆') }}</label>
          <Textarea
            id="report-admin-response"
            v-model="reviewForm.admin_response"
            rows="4"
            maxlength="1000"
            :placeholder="$t('可留空；若未提供答覆，通知中將顯示「未提供答覆」。')"
            :disabled="reviewSaving"
          />
          <small>{{ reviewForm.admin_response.length }}/1000</small>
        </div>
        <label
          v-if="!isFinal(selectedReport.status) && reviewForm.status === 'upheld'"
          class="report-review__delete-option"
        >
          <Checkbox
            v-model="reviewForm.delete_comment"
            binary
            :disabled="!selectedReport.source_exists"
          />
          {{ $t('同時刪除來源留言（使用既有留言刪除政策）') }}
        </label>
        <div class="report-review__actions">
          <Button
            :label="$t('前往來源')"
            icon="pi pi-external-link"
            severity="secondary"
            text
            :disabled="!selectedReport.source_exists"
            @click="openReportSource"
          />
          <span class="report-review__spacer" />
          <Button
            :label="$t('關閉')"
            severity="secondary"
            outlined
            @click="reviewVisible = false"
          />
          <Button
            v-if="!isFinal(selectedReport.status)"
            :label="$t('儲存審核')"
            icon="pi pi-check"
            :loading="reviewSaving"
            :disabled="!canSaveReview"
            @click="confirmSaveReview"
          />
        </div>
      </div>
    </Dialog>

    <Dialog
      v-model:visible="archiveReviewVisible"
      class="report-management-dialog"
      modal
      :header="$t('考古題回報審核')"
      :style="{ width: '760px', maxWidth: '94vw' }"
      :contentStyle="{ maxHeight: '76vh', overflowY: 'auto' }"
      :draggable="false"
    >
      <div v-if="selectedArchiveReport" class="report-review">
        <div class="report-review__title">
          <div>
            <strong
              >{{ localizedCourseSnapshotName(selectedArchiveReport) }} ·
              {{ selectedArchiveReport.archive_name }}</strong
            >
            <small>{{ $t('考古題') }} #{{ selectedArchiveReport.archive_id_snapshot }}</small>
          </div>
          <Tag
            :severity="statusSeverity(selectedArchiveReport.status)"
            :value="statusLabel(selectedArchiveReport.status)"
          />
        </div>
        <dl class="report-review__meta">
          <div>
            <dt>{{ $t('回報者') }}</dt>
            <dd>{{ selectedArchiveReport.reporter_name }}</dd>
          </div>
          <div>
            <dt>{{ $t('建立時間') }}</dt>
            <dd>{{ formatDateTime(selectedArchiveReport.created_at) }}</dd>
          </div>
          <div>
            <dt>{{ $t('回報原因') }}</dt>
            <dd>{{ archiveReasonLabel(selectedArchiveReport.reason) }}</dd>
          </div>
          <div>
            <dt>{{ $t('學期／年度') }}</dt>
            <dd>{{ selectedArchiveReport.academic_year }}</dd>
          </div>
          <div>
            <dt>{{ $t('授課教師') }}</dt>
            <dd>{{ selectedArchiveReport.professor || '—' }}</dd>
          </div>
          <div>
            <dt>{{ $t('考試名稱') }}</dt>
            <dd>{{ selectedArchiveReport.archive_name }}</dd>
          </div>
          <div>
            <dt>{{ $t('目前狀態') }}</dt>
            <dd>{{ archiveSourceStateLabel(selectedArchiveReport.source_state) }}</dd>
          </div>
          <div>
            <dt>{{ $t('審核人') }}</dt>
            <dd>{{ selectedArchiveReport.reviewer_name || $t('尚未審核') }}</dd>
          </div>
          <div>
            <dt>{{ $t('審核時間') }}</dt>
            <dd>{{ formatReviewTime(selectedArchiveReport.reviewed_at) }}</dd>
          </div>
        </dl>
        <section class="report-review__content-field">
          <strong class="report-review__content-label">{{ $t('補充說明') }}</strong>
          <div class="report-review__content-block">
            <p>{{ selectedArchiveReport.supplementary_detail || $t('未提供補充說明') }}</p>
          </div>
        </section>
        <p v-if="isFinal(selectedArchiveReport.status)" class="report-review__response">
          <strong>{{ $t('管理員答覆：') }}</strong
          >{{ selectedArchiveReport.admin_response || $t('未提供答覆') }}
        </p>
        <Message v-if="isFinal(selectedArchiveReport.status)" severity="info" :closable="false">
          {{ $t('審核結果已送出，無法修改。')
          }}{{ selectedArchiveReport.archive_taken_down ? $t('本次審核已將考古題下架。') : '' }}
        </Message>
        <Message v-else-if="!selectedArchiveReport.can_take_down" severity="warn" :closable="false">
          {{ archiveTakedownUnavailableMessage(selectedArchiveReport.source_state) }}
        </Message>
        <div v-if="!isFinal(selectedArchiveReport.status)" class="report-review__field">
          <label for="archive-review-status">{{ $t('審核結果') }}</label>
          <Select
            inputId="archive-review-status"
            v-model="archiveReviewForm.status"
            :options="statusOptions"
            optionLabel="label"
            optionValue="value"
            :disabled="archiveReviewSaving"
          />
        </div>
        <div v-if="!isFinal(selectedArchiveReport.status)" class="report-review__field">
          <label for="archive-admin-response">{{ $t('給回報者的答覆') }}</label>
          <Textarea
            id="archive-admin-response"
            v-model="archiveReviewForm.admin_response"
            rows="4"
            maxlength="1000"
            :placeholder="$t('可留空；若未提供答覆，通知中將顯示「未提供答覆」。')"
            :disabled="archiveReviewSaving"
          />
          <small>{{ archiveReviewForm.admin_response.length }}/1000</small>
        </div>
        <label
          v-if="!isFinal(selectedArchiveReport.status) && archiveReviewForm.status === 'upheld'"
          class="report-review__delete-option"
        >
          <Checkbox
            v-model="archiveReviewForm.take_down_archive"
            binary
            :disabled="!selectedArchiveReport.can_take_down || archiveReviewSaving"
          />
          {{ $t('同時將此考古題下架') }}
        </label>
        <div class="report-review__actions">
          <Button
            :label="$t('前往來源')"
            icon="pi pi-external-link"
            severity="secondary"
            text
            :disabled="!selectedArchiveReport.source_exists"
            @click="openArchiveReportSource"
          />
          <span class="report-review__spacer" />
          <Button
            :label="$t('關閉')"
            severity="secondary"
            outlined
            @click="archiveReviewVisible = false"
          />
          <Button
            v-if="!isFinal(selectedArchiveReport.status)"
            :label="$t('儲存審核')"
            icon="pi pi-check"
            :loading="archiveReviewSaving"
            :disabled="!canSaveArchiveReview"
            @click="confirmSaveArchiveReview"
          />
        </div>
      </div>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useConfirm } from 'primevue/useconfirm'
import { useToast } from 'primevue/usetoast'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { reportService, wishService } from '@/api'
import { ADMIN_PAGE_SIZE_OPTIONS } from '@/constants/pagination'
import { ARCHIVE_REPORT_REASONS } from '@/constants/archiveReport'
import { getMessageTemplate } from '@/i18n'
import { getCurrentUser } from '@/utils/auth'
import { localizedCourseSnapshotName } from '@/utils/localizedCatalog'
import { formatRelativeOrAbsoluteDateTime } from '@/utils/time'

const props = defineProps({
  attentionCounts: {
    type: Object,
    default: () => ({
      archive_reports: 0,
      comment_reports: 0,
      wish_reports: 0,
      system_issues: 0,
    }),
  },
})
const emit = defineEmits(['attention-change'])
const attentionCounts = computed(() => props.attentionCounts)

const confirm = useConfirm()
const toast = useToast()
const router = useRouter()
const { t } = useI18n()
const paginationReportTemplate = computed(() =>
  getMessageTemplate('第 {currentPage} / {totalPages} 頁，共 {totalRecords} 筆')
)
const REPORT_CARD_MEDIA_QUERY = '(max-width: 1399.98px)'
let reportCardMediaQuery = null
const isCardLayout = ref(false)
const activeReportTab = ref('archive')
const wishReports = ref([])
const wishTotal = ref(0)
const wishLoading = ref(false)
const wishError = ref('')
const wishFilters = ref({ search: '', status: null })
const wishPage = ref({ first: 0, rows: 10, sortField: 'created_at', sortOrder: -1 })
const wishReviewVisible = ref(false)
const selectedWishReport = ref(null)
const wishReviewForm = ref({ status: 'pending', admin_response: '' })
const wishReviewSaving = ref(false)
const deletingWishReportId = ref(null)
const loadingSystem = ref(false)
const loadingComments = ref(false)
const archiveReports = ref([])
const systemIssues = ref([])
const systemTotal = ref(0)
const systemError = ref('')
const commentReports = ref([])
const commentTotal = ref(0)
const commentError = ref('')
const reviewVisible = ref(false)
const archiveReviewVisible = ref(false)
const systemDetailVisible = ref(false)
const loadingSystemDetailId = ref(null)
const systemReadSaving = ref(false)
const systemReadForm = ref(false)
const reviewSaving = ref(false)
const archiveReviewSaving = ref(false)
const deletingSystemId = ref(null)
const deletingCommentId = ref(null)
const deletingArchiveId = ref(null)
const selectedReport = ref(null)
const selectedSystemReport = ref(null)
const selectedArchiveReport = ref(null)
const systemFilters = ref({ search: '', type: null, readState: 'all' })
const commentFilters = ref({ search: '', status: null, reason: null })
const archiveFilters = ref({ search: '', status: null, reason: null })
const systemPage = ref({ first: 0, rows: 10, sortField: 'read_state', sortOrder: 1 })
const commentPage = ref({ first: 0, rows: 10, sortField: 'status', sortOrder: 1 })
const archiveListState = ref({
  first: 0,
  rows: 10,
  total: 0,
  sortField: 'created_at',
  sortOrder: -1,
  loading: false,
  error: '',
})
const reviewForm = ref({ status: 'pending', admin_response: '', delete_comment: false })
const archiveReviewForm = ref({
  status: 'pending',
  admin_response: '',
  take_down_archive: false,
})
const loading = computed(
  () => loadingSystem.value || loadingComments.value || archiveListState.value.loading
)
const formatAttentionBadge = (value) => {
  const count = Number(value) || 0
  if (count <= 0) return null
  return count > 99 ? '99+' : count
}

const reasonOptions = computed(() => [
  { label: t('垃圾訊息或重複洗版'), value: 'spam_or_duplicate' },
  { label: t('攻擊、騷擾或不友善內容'), value: 'harassment_or_hostility' },
  { label: t('不當或違法內容'), value: 'inappropriate_or_illegal' },
  { label: t('洩漏個人資料或隱私'), value: 'privacy_violation' },
  { label: t('錯誤或誤導資訊'), value: 'misinformation' },
  { label: t('其他'), value: 'other' },
])
const archiveReasonOptions = computed(() =>
  ARCHIVE_REPORT_REASONS.map((item) => ({ ...item, label: t(item.label) }))
)
const systemTypeOptions = computed(() => [
  { label: t('程式錯誤'), value: 'bug' },
  { label: t('功能建議'), value: 'enhancement' },
  { label: t('效能問題'), value: 'performance' },
  { label: 'UI/UX', value: 'ui-ux' },
  { label: t('其他'), value: 'question' },
])
const systemReadStateOptions = computed(() => [
  { label: t('全部狀態'), value: 'all' },
  { label: t('未讀'), value: 'unread' },
  { label: t('已讀'), value: 'read' },
])
const statusOptions = computed(() => [
  { label: t('待審核'), value: 'pending' },
  { label: t('回報成立'), value: 'upheld' },
  { label: t('回報不成立'), value: 'dismissed' },
])
const reviewStatusOptions = computed(() =>
  isFinal(selectedReport.value?.status)
    ? statusOptions.value.filter((item) => item.value !== 'pending')
    : statusOptions.value
)
const canSaveReview = computed(() => {
  if (!['upheld', 'dismissed'].includes(reviewForm.value.status)) return false
  return reviewForm.value.admin_response.length <= 1000
})
const canSaveArchiveReview = computed(() => {
  if (!['upheld', 'dismissed'].includes(archiveReviewForm.value.status)) return false
  if (archiveReviewForm.value.admin_response.length > 1000) return false
  if (
    archiveReviewForm.value.take_down_archive &&
    (archiveReviewForm.value.status !== 'upheld' || !selectedArchiveReport.value?.can_take_down)
  )
    return false
  return true
})
watch(
  () => archiveReviewForm.value.status,
  (value) => {
    if (value !== 'upheld') archiveReviewForm.value.take_down_archive = false
  }
)

function ensureAdmin() {
  if (!getCurrentUser()?.is_admin) throw new Error('Admin access required')
}
async function loadSystemIssues() {
  ensureAdmin()
  loadingSystem.value = true
  systemError.value = ''
  try {
    const { data } = await reportService.listSystemIssues({
      search: systemFilters.value.search.trim() || undefined,
      report_type: systemFilters.value.type || undefined,
      read_state: systemFilters.value.readState,
      sort_by: systemPage.value.sortField,
      sort_order: systemPage.value.sortOrder === 1 ? 'asc' : 'desc',
      limit: systemPage.value.rows,
      offset: systemPage.value.first,
    })
    systemIssues.value = data.items || []
    systemTotal.value = Number(data.total || 0)
  } catch (error) {
    console.error('Load system issue reports error:', error)
    systemError.value = t('無法載入系統問題回報，請重新整理後再試。')
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入系統問題回報'),
      life: 3000,
    })
  } finally {
    loadingSystem.value = false
  }
}
async function loadCommentReports() {
  ensureAdmin()
  loadingComments.value = true
  commentError.value = ''
  try {
    const { data } = await reportService.listCommentReports({
      search: commentFilters.value.search.trim() || undefined,
      status: commentFilters.value.status || undefined,
      reason: commentFilters.value.reason || undefined,
      sort_by: commentPage.value.sortField,
      sort_order: commentPage.value.sortOrder === 1 ? 'asc' : 'desc',
      limit: commentPage.value.rows,
      offset: commentPage.value.first,
    })
    commentReports.value = data.items || []
    commentTotal.value = Number(data.total || 0)
  } catch (error) {
    console.error('Load comment reports error:', error)
    commentError.value = t('無法載入留言回報，請重新整理後再試。')
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入留言回報'),
      life: 3000,
    })
  } finally {
    loadingComments.value = false
  }
}
async function loadArchiveReports() {
  ensureAdmin()
  archiveListState.value.loading = true
  archiveListState.value.error = ''
  try {
    const { data } = await reportService.listArchiveReports({
      search: archiveFilters.value.search.trim() || undefined,
      status: archiveFilters.value.status || undefined,
      reason: archiveFilters.value.reason || undefined,
      sort_by: archiveListState.value.sortField,
      sort_order: archiveListState.value.sortOrder === 1 ? 'asc' : 'desc',
      limit: archiveListState.value.rows,
      offset: archiveListState.value.first,
    })
    archiveReports.value = data.items || []
    archiveListState.value.total = Number(data.total || 0)
  } catch (error) {
    console.error('Load archive reports error:', error)
    archiveListState.value.error = t('無法載入考古題回報，請重新整理後再試。')
  } finally {
    archiveListState.value.loading = false
  }
}
function applySystemFilters() {
  systemPage.value.first = 0
  return loadSystemIssues()
}
function applyCommentFilters() {
  commentPage.value.first = 0
  return loadCommentReports()
}
function applyArchiveFilters() {
  archiveListState.value.first = 0
  return loadArchiveReports()
}
function onSystemPage(event) {
  const pageSizeChanged = systemPage.value.rows !== event.rows
  systemPage.value.first = pageSizeChanged ? 0 : event.first
  systemPage.value.rows = event.rows
  return loadSystemIssues()
}
function onCommentPage(event) {
  const pageSizeChanged = commentPage.value.rows !== event.rows
  commentPage.value.first = pageSizeChanged ? 0 : event.first
  commentPage.value.rows = event.rows
  return loadCommentReports()
}
function onArchivePage(event) {
  const pageSizeChanged = archiveListState.value.rows !== event.rows
  archiveListState.value.first = pageSizeChanged ? 0 : event.first
  archiveListState.value.rows = event.rows
  return loadArchiveReports()
}
function onSystemSort(event) {
  systemPage.value.first = 0
  systemPage.value.sortField = event.sortField || 'read_state'
  systemPage.value.sortOrder = event.sortOrder || 1
  return loadSystemIssues()
}
function onCommentSort(event) {
  commentPage.value.first = 0
  commentPage.value.sortField = event.sortField || 'status'
  commentPage.value.sortOrder = event.sortOrder || 1
  return loadCommentReports()
}
function onArchiveSort(event) {
  archiveListState.value.first = 0
  archiveListState.value.sortField = event.sortField || 'status'
  archiveListState.value.sortOrder = event.sortOrder || 1
  return loadArchiveReports()
}
async function refreshAll() {
  Object.assign(systemPage.value, { first: 0, sortField: 'read_state', sortOrder: 1 })
  Object.assign(commentPage.value, { first: 0, sortField: 'status', sortOrder: 1 })
  Object.assign(wishPage.value, { first: 0, sortField: 'created_at', sortOrder: -1 })
  Object.assign(archiveListState.value, {
    first: 0,
    sortField: 'status',
    sortOrder: 1,
  })
  const result = await Promise.allSettled([
    loadSystemIssues(),
    loadCommentReports(),
    loadArchiveReports(),
    loadWishReports(),
  ])
  emit('attention-change')
  return result
}
async function loadWishReports() {
  wishLoading.value = true
  wishError.value = ''
  try {
    const { data } = await wishService.listReports({
      search: wishFilters.value.search.trim() || undefined,
      status: wishFilters.value.status || undefined,
      sort_by: wishPage.value.sortField,
      sort_order: wishPage.value.sortOrder === 1 ? 'asc' : 'desc',
      limit: wishPage.value.rows,
      offset: wishPage.value.first,
    })
    wishReports.value = data.items || []
    wishTotal.value = Number(data.total || 0)
  } catch {
    wishError.value = t('無法載入許願回報，請重新整理後再試。')
  } finally {
    wishLoading.value = false
  }
}
function applyWishFilters() {
  wishPage.value.first = 0
  return loadWishReports()
}
function onWishPage(event) {
  const pageSizeChanged = wishPage.value.rows !== event.rows
  wishPage.value.first = pageSizeChanged ? 0 : event.first
  wishPage.value.rows = event.rows
  return loadWishReports()
}
function onWishSort(event) {
  wishPage.value.first = 0
  wishPage.value.sortField = event.sortField || 'created_at'
  wishPage.value.sortOrder = event.sortOrder || -1
  return loadWishReports()
}
async function openWishReport(id) {
  try {
    const { data } = await wishService.getReport(id)
    selectedWishReport.value = data
    wishReviewForm.value = { status: data.status, admin_response: data.admin_response || '' }
    wishReviewVisible.value = true
  } catch {
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入回報詳情'),
      life: 3000,
    })
  }
}
function confirmSaveWishReview() {
  if (
    !selectedWishReport.value ||
    wishReviewSaving.value ||
    !['upheld', 'dismissed'].includes(wishReviewForm.value.status)
  )
    return
  confirm.require({
    header: t('確認送出審核結果'),
    message: t('審核結果與管理員答覆送出後將無法修改。'),
    icon: 'pi pi-question-circle',
    rejectLabel: t('取消'),
    acceptLabel: t('確認送出'),
    defaultFocus: 'reject',
    accept: saveWishReview,
  })
}
async function saveWishReview() {
  wishReviewSaving.value = true
  try {
    const { data } = await wishService.reviewReport(selectedWishReport.value.id, {
      status: wishReviewForm.value.status,
      admin_response: wishReviewForm.value.admin_response.trim() || null,
    })
    selectedWishReport.value = data
    toast.add({
      severity: 'success',
      summary: t('審核已更新'),
      detail: t('許願回報審核狀態已更新'),
      life: 3000,
    })
    await loadWishReports()
    emit('attention-change')
  } catch {
    toast.add({
      severity: 'error',
      summary: t('更新失敗'),
      detail: t('回報狀態未變更'),
      life: 3000,
    })
  } finally {
    wishReviewSaving.value = false
  }
}
function confirmDeleteWishReport(report) {
  if (!report?.id || deletingWishReportId.value !== null) return
  confirm.require({
    header: t('永久刪除這筆回報？'),
    message: t('這筆許願回報將永久刪除且無法復原。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('永久刪除'),
    acceptClass: 'p-button-danger',
    defaultFocus: 'reject',
    accept: () => removeWishReport(report),
  })
}
async function removeWishReport(report) {
  deletingWishReportId.value = report.id
  try {
    await wishService.removeReport(report.id)
    wishReports.value = wishReports.value.filter((item) => item.id !== report.id)
    wishTotal.value = clampReportPageAfterDelete(wishPage.value, wishTotal.value)
    if (selectedWishReport.value?.id === report.id) wishReviewVisible.value = false
    toast.add({
      severity: 'success',
      summary: t('回報已永久刪除'),
      detail: t('許願回報已永久移除'),
      life: 3000,
    })
    await loadWishReports()
    emit('attention-change')
  } catch {
    toast.add({
      severity: 'error',
      summary: t('刪除失敗'),
      detail: t('許願回報未變更'),
      life: 3000,
    })
  } finally {
    deletingWishReportId.value = null
  }
}
function clampReportPageAfterDelete(page, total) {
  const nextTotal = Math.max(0, total - 1)
  const maxFirst = nextTotal
    ? Math.floor((nextTotal - 1) / Math.max(1, page.rows)) * Math.max(1, page.rows)
    : 0
  page.first = Math.min(page.first, maxFirst)
  return nextTotal
}
function confirmDeleteSystemIssue(item) {
  if (!item?.id || deletingSystemId.value !== null) return
  confirm.require({
    header: t('刪除這筆回報？'),
    message: t('回報會移至垃圾桶，可由管理員在垃圾桶中還原或永久刪除。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('刪除'),
    acceptClass: 'p-button-danger',
    accept: () => deleteSystemIssue(item),
  })
}
async function openSystemReport(item) {
  if (!item?.id || loadingSystemDetailId.value !== null) return
  loadingSystemDetailId.value = item.id
  try {
    const { data } = await reportService.getSystemIssue(item.id)
    selectedSystemReport.value = data
    systemReadForm.value = Boolean(data.is_read)
    systemDetailVisible.value = true
  } catch (error) {
    console.error('Load system issue report detail error:', error)
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入回報詳情'),
      life: 3000,
    })
  } finally {
    loadingSystemDetailId.value = null
  }
}
async function saveSystemReadState() {
  if (!selectedSystemReport.value?.id || systemReadSaving.value) return
  systemReadSaving.value = true
  try {
    const { data } = await reportService.updateSystemIssueReadState(
      selectedSystemReport.value.id,
      systemReadForm.value
    )
    selectedSystemReport.value = data
    systemReadForm.value = Boolean(data.is_read)
    systemIssues.value = systemIssues.value.map((item) => (item.id === data.id ? data : item))
    toast.add({
      severity: 'success',
      summary: t('閱讀狀態已更新'),
      detail: data.is_read ? t('已標記為已讀') : t('已標記為未讀'),
      life: 3000,
    })
    emit('attention-change')
  } catch (error) {
    console.error('Update system issue report read state error:', error)
    systemReadForm.value = Boolean(selectedSystemReport.value.is_read)
    toast.add({
      severity: 'error',
      summary: t('更新失敗'),
      detail: t('閱讀狀態未變更'),
      life: 3000,
    })
  } finally {
    systemReadSaving.value = false
  }
}
async function deleteSystemIssue(item) {
  if (!item?.id || deletingSystemId.value !== null) return
  deletingSystemId.value = item.id
  try {
    await reportService.deleteSystemIssue(item.id)
    systemIssues.value = systemIssues.value.filter((candidate) => candidate.id !== item.id)
    systemTotal.value = clampReportPageAfterDelete(systemPage.value, systemTotal.value)
    toast.add({
      severity: 'success',
      summary: t('回報已移至垃圾桶'),
      detail: t('系統問題回報可在垃圾桶中還原或永久刪除'),
      life: 3000,
    })
    await loadSystemIssues()
    emit('attention-change')
  } catch (error) {
    console.error('Delete system issue report error:', error)
    toast.add({
      severity: 'error',
      summary: t('刪除失敗'),
      detail: t('系統問題回報未變更'),
      life: 3000,
    })
  } finally {
    deletingSystemId.value = null
  }
}
function confirmDeleteCommentReport(item) {
  if (!item?.id || deletingCommentId.value !== null) return
  confirm.require({
    header: t('刪除這筆回報？'),
    message: t('回報會移至垃圾桶，可由管理員在垃圾桶中還原或永久刪除。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('刪除'),
    acceptClass: 'p-button-danger',
    accept: () => deleteCommentReport(item),
  })
}
async function deleteCommentReport(item) {
  if (!item?.id || deletingCommentId.value !== null) return
  deletingCommentId.value = item.id
  try {
    await reportService.deleteCommentReport(item.id)
    commentReports.value = commentReports.value.filter((candidate) => candidate.id !== item.id)
    commentTotal.value = clampReportPageAfterDelete(commentPage.value, commentTotal.value)
    if (selectedReport.value?.id === item.id) reviewVisible.value = false
    toast.add({
      severity: 'success',
      summary: t('回報已移至垃圾桶'),
      detail: t('留言回報可在垃圾桶中還原或永久刪除'),
      life: 3000,
    })
    await loadCommentReports()
    emit('attention-change')
  } catch (error) {
    console.error('Delete comment report error:', error)
    toast.add({
      severity: 'error',
      summary: t('刪除失敗'),
      detail: t('留言回報未變更'),
      life: 3000,
    })
  } finally {
    deletingCommentId.value = null
  }
}
async function openCommentReport(id) {
  try {
    const { data } = await reportService.getCommentReport(id)
    selectedReport.value = data
    reviewForm.value = {
      status: data.status,
      admin_response: data.admin_response || '',
      delete_comment: false,
    }
    reviewVisible.value = true
  } catch (error) {
    console.error('Load comment report detail error:', error)
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入回報詳情'),
      life: 3000,
    })
  }
}
function confirmSaveReview() {
  if (
    reviewSaving.value ||
    !selectedReport.value ||
    isFinal(selectedReport.value.status) ||
    !canSaveReview.value
  )
    return
  const deletesComment = reviewForm.value.status === 'upheld' && reviewForm.value.delete_comment
  const message = [t('送出後將通知回報者。'), t('審核結果與管理員答覆送出後將無法修改。')]
  if (deletesComment) {
    message.push(t('被回報留言將永久刪除，無法復原，也不會進入垃圾桶。'))
  }
  confirm.require({
    header: t('確認送出審核結果'),
    message: message.join('\n'),
    icon: deletesComment ? 'pi pi-exclamation-triangle' : 'pi pi-question-circle',
    rejectLabel: t('取消'),
    acceptLabel: t('確認送出'),
    acceptClass: deletesComment ? 'p-button-danger' : 'p-button-primary',
    defaultFocus: 'reject',
    accept: saveReview,
  })
}
async function saveReview() {
  if (
    reviewSaving.value ||
    !selectedReport.value ||
    isFinal(selectedReport.value.status) ||
    !canSaveReview.value
  )
    return
  reviewSaving.value = true
  try {
    const { data } = await reportService.reviewCommentReport(selectedReport.value.id, {
      status: reviewForm.value.status,
      admin_response: reviewForm.value.admin_response.trim() || null,
      delete_comment: reviewForm.value.delete_comment,
    })
    selectedReport.value = data
    toast.add({
      severity: 'success',
      summary: t('審核已更新'),
      detail: t('留言回報審核狀態已更新'),
      life: 3000,
    })
    await loadCommentReports()
    emit('attention-change')
  } catch (error) {
    console.error('Review comment report error:', error)
    toast.add({
      severity: 'error',
      summary: t('更新失敗'),
      detail: t('回報狀態未變更'),
      life: 3000,
    })
  } finally {
    reviewSaving.value = false
  }
}
function openReportSource() {
  const item = selectedReport.value
  if (!item?.source_exists) return
  reviewVisible.value = false
  router.push({
    path: '/archive',
    query: {
      courseId: item.course_id,
      archiveId: item.archive_id,
      threadId: item.thread_id,
      messageId: item.comment_id,
    },
  })
}
function confirmDeleteArchiveReport(item) {
  if (!item?.id || deletingArchiveId.value !== null) return
  confirm.require({
    header: t('刪除這筆考古題回報？'),
    message: t('回報會移至垃圾桶；考古題、投稿與 PDF 不會受到影響。'),
    icon: 'pi pi-exclamation-triangle',
    rejectLabel: t('取消'),
    acceptLabel: t('刪除'),
    acceptClass: 'p-button-danger',
    accept: () => deleteArchiveReport(item),
  })
}
async function deleteArchiveReport(item) {
  deletingArchiveId.value = item.id
  try {
    await reportService.deleteArchiveReport(item.id)
    archiveReports.value = archiveReports.value.filter((candidate) => candidate.id !== item.id)
    archiveListState.value.total = clampReportPageAfterDelete(
      archiveListState.value,
      archiveListState.value.total
    )
    if (selectedArchiveReport.value?.id === item.id) {
      archiveReviewVisible.value = false
    }
    toast.add({
      severity: 'success',
      summary: t('回報已移至垃圾桶'),
      detail: t('考古題與投稿未變更'),
      life: 3000,
    })
    await loadArchiveReports()
    emit('attention-change')
  } catch (error) {
    console.error('Delete archive report error:', error)
    toast.add({ severity: 'error', summary: t('刪除失敗'), detail: t('回報未變更'), life: 3000 })
  } finally {
    deletingArchiveId.value = null
  }
}
async function openArchiveReport(id) {
  try {
    const { data } = await reportService.getArchiveReport(id)
    selectedArchiveReport.value = data
    archiveReviewForm.value = {
      status: data.status,
      admin_response: data.admin_response || '',
      take_down_archive: false,
    }
    archiveReviewVisible.value = true
  } catch (error) {
    console.error('Load archive report detail error:', error)
    toast.add({
      severity: 'error',
      summary: t('載入失敗'),
      detail: t('無法載入回報詳情'),
      life: 3000,
    })
  }
}
function confirmSaveArchiveReview() {
  if (
    archiveReviewSaving.value ||
    !selectedArchiveReport.value ||
    isFinal(selectedArchiveReport.value.status) ||
    !canSaveArchiveReview.value
  )
    return
  const takesDown =
    archiveReviewForm.value.status === 'upheld' && archiveReviewForm.value.take_down_archive
  confirm.require({
    header: t('確認送出考古題回報審核'),
    message: takesDown
      ? t('送出後將通知回報者，並以既有流程下架考古題；不會刪除考古題、投稿或 PDF。')
      : t('送出後將通知回報者，審核結果無法修改。'),
    icon: takesDown ? 'pi pi-exclamation-triangle' : 'pi pi-question-circle',
    rejectLabel: t('取消'),
    acceptLabel: t('確認送出'),
    defaultFocus: 'reject',
    accept: saveArchiveReview,
  })
}
async function saveArchiveReview() {
  if (!canSaveArchiveReview.value || archiveReviewSaving.value) return
  archiveReviewSaving.value = true
  try {
    const { data } = await reportService.reviewArchiveReport(selectedArchiveReport.value.id, {
      status: archiveReviewForm.value.status,
      admin_response: archiveReviewForm.value.admin_response.trim() || null,
      take_down_archive:
        archiveReviewForm.value.status === 'upheld' && archiveReviewForm.value.take_down_archive,
    })
    selectedArchiveReport.value = data
    archiveReviewForm.value.take_down_archive = false
    toast.add({
      severity: 'success',
      summary: t('審核已完成'),
      detail: data.archive_taken_down ? t('回報成立，考古題已下架') : t('考古題回報審核已更新'),
      life: 3500,
    })
    await loadArchiveReports()
    emit('attention-change')
  } catch (error) {
    console.error('Review archive report error:', error)
    const conflict = error?.response?.status === 409
    toast.add({
      severity: 'error',
      summary: conflict ? t('資料狀態已變更') : t('更新失敗'),
      detail: conflict ? t('請重新開啟回報確認最新狀態') : t('回報狀態未變更'),
      life: 3500,
    })
  } finally {
    archiveReviewSaving.value = false
  }
}
function openArchiveReportSource() {
  const item = selectedArchiveReport.value
  if (!item?.source_exists) return
  archiveReviewVisible.value = false
  router.push({
    path: '/archive',
    query: { courseId: item.course_id, archiveId: item.archive_id },
  })
}
function archiveReasonLabel(value) {
  return archiveReasonOptions.value.find((item) => item.value === value)?.label || value
}
function archiveSourceStateLabel(value) {
  return (
    {
      available: t('公開中'),
      taken_down: t('已下架'),
      trashed: t('已在垃圾桶'),
      deleted: t('投稿已刪除'),
      missing: t('來源已不存在'),
      unavailable: t('目前不可公開'),
      not_managed: t('無投稿紀錄可供下架'),
    }[value] || value
  )
}
function archiveTakedownUnavailableMessage(value) {
  return (
    {
      taken_down: t('此考古題已下架，不能重複執行。'),
      trashed: t('此考古題或課程已在垃圾桶，不能執行下架。'),
      deleted: t('對應投稿已刪除，不能執行下架。'),
      missing: t('來源已不存在，仍可完成審核但不能執行下架。'),
      unavailable: t('此考古題目前不是公開狀態，不能執行下架。'),
      not_managed: t('此考古題沒有可供既有下架 service 管理的投稿紀錄。'),
    }[value] || t('目前不能執行下架。')
  )
}
function reasonLabel(value) {
  return reasonOptions.value.find((item) => item.value === value)?.label || value
}
function statusLabel(value) {
  return statusOptions.value.find((item) => item.value === value)?.label || value
}
function statusSeverity(value) {
  return { pending: 'warn', upheld: 'success', dismissed: 'danger' }[value] || 'secondary'
}
function issueTypeLabel(value) {
  return (
    {
      bug: t('程式錯誤'),
      enhancement: t('功能建議'),
      performance: t('效能問題'),
      'ui-ux': 'UI/UX',
      question: t('其他'),
    }[value] || value
  )
}
function isFinal(value) {
  return ['upheld', 'dismissed'].includes(value)
}
const formatDateTime = (value) => formatRelativeOrAbsoluteDateTime(value)
const formatReviewTime = (value) => (value ? formatDateTime(value, true) : '--')

const formatWishTargetSummary = (value) =>
  String(value || '')
    .split(' · ')
    .map((part) => {
      const term = part.match(/^term:(any|\d+)$/i)?.[1]
      if (!term) return part
      if (term.toLowerCase() === 'any') return t('不限學期')
      const numericValue = Number(term)
      const year = Math.floor(numericValue / 10)
      const semester = numericValue % 10
      if (numericValue >= 1000 && numericValue < 2000 && (semester === 1 || semester === 2)) {
        return t(semester === 1 ? '{year}上學期' : '{year}下學期', { year })
      }
      return t('{value} 年', { value: numericValue })
    })
    .join(' · ')

function syncCardLayout(event) {
  isCardLayout.value = event.matches
}

function setupCardLayout() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  reportCardMediaQuery = window.matchMedia(REPORT_CARD_MEDIA_QUERY)
  if (!reportCardMediaQuery) return
  isCardLayout.value = reportCardMediaQuery.matches
  if (typeof reportCardMediaQuery.addEventListener === 'function') {
    reportCardMediaQuery.addEventListener('change', syncCardLayout)
  } else {
    reportCardMediaQuery.addListener?.(syncCardLayout)
  }
}

function teardownCardLayout() {
  if (typeof reportCardMediaQuery?.removeEventListener === 'function') {
    reportCardMediaQuery.removeEventListener('change', syncCardLayout)
  } else {
    reportCardMediaQuery?.removeListener?.(syncCardLayout)
  }
}

onMounted(() => {
  setupCardLayout()
  refreshAll()
})
onBeforeUnmount(teardownCardLayout)
</script>

<style scoped>
.report-management {
  min-width: 0;
  font-size: var(--app-font-size-base);
}

.report-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}
.report-management :deep(.p-component) {
  font-size: var(--app-font-size-base) !important;
}
.report-management :deep(.p-inputtext),
.report-management :deep(.p-inputtext::placeholder),
.report-management :deep(.p-select),
.report-management :deep(.p-select-label),
.report-management :deep(.p-datatable),
.report-management :deep(.p-datatable-thead > tr > th),
.report-management :deep(.p-datatable-tbody > tr > td),
.report-management :deep(.p-paginator),
.report-management :deep(.p-paginator-page),
.report-management :deep(.p-paginator-current),
.report-management :deep(.p-paginator-rpp-dropdown) {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}
.report-management :deep(.p-button) {
  min-height: 2rem;
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}
.report-management :deep(.p-button-label),
.report-management :deep(.p-button-icon) {
  font-size: inherit !important;
}
.report-management :deep(.p-tag) {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}
.report-management > .report-section > .p-message,
.report-management__empty {
  font-size: var(--app-font-size-sm);
}
.report-section__header,
.report-review__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.report-section__header--system {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 1rem;
  width: 100%;
  min-width: 0;
}
.report-section__copy {
  min-width: 0;
}
.report-section {
  container-name: report-section;
  container-type: inline-size;
  min-width: 0;
  padding-block: 1.25rem;
  border-bottom: 1px solid var(--border-color);
}
.report-section:first-of-type {
  padding-top: 0;
}
.report-section:last-of-type {
  border-bottom: 0;
}
.report-section__header h4 {
  margin: 0;
  color: var(--text-color);
  font-size: var(--app-font-size-lg);
}
.report-section__header p {
  margin: 0.25rem 0 0;
  color: var(--text-color-secondary);
}
.report-section__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.report-section__header--system .report-section__actions {
  justify-self: end;
  width: auto;
  min-width: max-content;
  flex-wrap: nowrap;
}
.report-section__actions :deep(.p-button) {
  flex: 0 0 auto;
  width: auto;
  min-width: 0;
}
.report-row-actions {
  display: inline-flex;
  width: 100%;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 0.5rem;
}
.report-row-actions :deep(.p-button) {
  flex: 0 0 auto;
  white-space: nowrap;
}
.report-management__filters {
  display: grid;
  grid-template-areas: 'search primary secondary submit';
  grid-template-columns: minmax(0, 1fr) repeat(2, minmax(9rem, 11rem)) auto;
  align-items: center;
  gap: 0.6rem;
  width: 100%;
  min-width: 0;
  margin-block: 1rem;
}
.report-management__filters--compact {
  grid-template-areas: 'search primary submit';
  grid-template-columns: minmax(0, 1fr) minmax(9rem, 11rem) auto;
}
.report-filter-search {
  grid-area: search;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
:deep(.report-filter-select) {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
:deep(.report-filter-select--primary) {
  grid-area: primary;
}
:deep(.report-filter-select--secondary) {
  grid-area: secondary;
}
:deep(.report-filter-submit.p-button) {
  grid-area: submit;
  justify-self: end;
  width: auto;
  min-width: 0;
  box-sizing: border-box;
  padding-inline: 0.8rem;
  white-space: nowrap;
}
.report-management__filters :deep(.p-inputtext),
.report-management__filters :deep(.p-select),
.report-management__filters :deep(.p-button) {
  min-height: 2.35rem;
}
@container report-section (max-width: 62rem) {
  .report-management__filters {
    grid-template-areas:
      'search search search'
      'primary secondary submit';
    grid-template-columns: repeat(2, minmax(0, 1fr)) auto;
  }
  .report-management__filters--compact {
    grid-template-areas:
      'search search'
      'primary submit';
    grid-template-columns: minmax(0, 1fr) auto;
  }
}
@container report-section (max-width: 34rem) {
  .report-management__filters {
    grid-template-areas:
      'search search'
      'primary secondary'
      '. submit';
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .report-management__filters--compact {
    grid-template-areas:
      'search search'
      'primary submit';
  }
}
@container report-section (max-width: 20rem) {
  .report-management__filters {
    grid-template-areas:
      'search'
      'primary'
      'secondary'
      'submit';
    grid-template-columns: minmax(0, 1fr);
  }
  .report-management__filters--compact {
    grid-template-areas:
      'search'
      'primary'
      'submit';
  }
}
@container report-section (max-width: 42rem) {
  .report-section__header--system {
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
  }
  .report-section__header--system .report-section__actions {
    justify-self: start;
  }
}
@container report-section (max-width: 25rem) {
  .report-section__header--system .report-section__actions {
    min-width: 0;
    flex-wrap: wrap;
  }
}
.report-management__table {
  width: 100%;
}
.report-mobile-card {
  display: grid;
  grid-template-areas:
    'header'
    'body'
    'footer';
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto auto auto;
  align-content: start;
  justify-content: stretch;
  justify-items: stretch;
  width: 100%;
  min-width: 0;
  min-height: 0;
  height: auto;
  max-width: none;
  box-sizing: border-box;
  container-name: report-card;
  container-type: inline-size;
}
.report-mobile-card-content,
.report-mobile-card__header,
.report-mobile-card__body,
.report-mobile-card__footer {
  width: 100%;
  min-width: 0;
  max-width: none;
  box-sizing: border-box;
  justify-self: stretch;
}
.report-mobile-card__footer {
  grid-area: footer;
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: flex-end;
}
.report-desktop-actions {
  width: 100%;
}
.report-management__summary {
  display: flex;
  min-width: 10rem;
  flex-direction: column;
  gap: 0.2rem;
  overflow-wrap: anywhere;
}
.report-management__summary small,
.report-management__summary span {
  color: var(--text-color-secondary);
}
.system-report-summary {
  display: grid;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  white-space: normal;
}
:deep(.system-report-column) {
  width: clamp(15rem, 22vw, 21.25rem);
  max-width: 21.25rem;
  overflow: hidden;
  white-space: normal;
}
.system-report-summary__title {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  color: var(--text-color);
  font-size: var(--app-font-size-sm);
  font-weight: 600;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.system-report-summary__body {
  display: -webkit-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  max-height: calc(1.35em * 3);
  margin-top: 0.2rem;
  overflow: hidden;
  overflow-wrap: anywhere;
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.comment-report-content {
  display: grid;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  white-space: normal;
}
.comment-report-content__reason {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  color: var(--text-color);
  font-size: var(--app-font-size-sm);
  font-weight: 600;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.comment-report-content__summary {
  display: -webkit-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  max-height: calc(1.35em * 3);
  margin-top: 0.2rem;
  overflow: hidden;
  overflow-wrap: anywhere;
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
:deep(.comment-report-content-column) {
  width: clamp(16rem, 24vw, 20rem);
  max-width: 20rem;
  overflow: hidden;
  white-space: normal;
}
:deep(.report-person-time-column) {
  overflow: hidden;
  white-space: normal;
}
:deep(.report-user-column) {
  width: 7rem;
  min-width: 7rem;
  max-width: 7rem;
  overflow: hidden;
}
.report-user-cell__text {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.report-person-time {
  display: grid;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  gap: 0.18rem;
}
.report-person-time__name,
.report-person-time__time {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.report-person-time__name {
  color: var(--text-color);
  line-height: 1.35;
}
.report-person-time__name--empty {
  color: var(--text-color-secondary);
}
.report-person-time__time {
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.3;
}
:deep(.report-review-column) {
  width: 10rem;
  min-width: 10rem;
  padding-inline-end: 1.25rem;
  overflow: hidden;
  white-space: normal;
}
:deep(.report-actions-column) {
  width: 17rem;
  min-width: 17rem;
  padding-inline: 0.75rem 1rem;
  vertical-align: middle;
}
:deep(.report-actions-column--system) {
  width: 12rem;
  min-width: 12rem;
}
:deep(.report-actions-column .p-button) {
  white-space: nowrap;
}
.report-management__empty {
  display: flex;
  min-height: 15rem;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 0.65rem;
  color: var(--text-color-secondary);
  text-align: center;
}
.report-management__empty i {
  font-size: calc(var(--app-icon-size) * 2);
}
.report-review {
  display: grid;
  gap: 1rem;
}
.report-review__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.report-review__title > div {
  display: grid;
  gap: 0.2rem;
}
.report-review__title small {
  color: var(--text-color-secondary);
}
.report-review__meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem;
  margin: 0;
}
.report-review__meta div {
  min-width: 0;
}
.report-review__meta dt {
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
}
.report-review__meta dd {
  display: grid;
  gap: 0.18rem;
  margin: 0.15rem 0 0;
  overflow-wrap: anywhere;
}
.report-review__meta dd small {
  color: var(--text-color-secondary);
  font-size: var(--app-font-size-xs);
  line-height: 1.35;
}
.report-review__thread-content {
  gap: 0.1rem;
}
.report-review__thread-id {
  color: var(--text-primary);
  font-size: var(--app-font-size-base);
  line-height: 1.4;
}
.report-review__thread-content :deep(.report-review__thread-hint.p-tag) {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  justify-self: start;
  margin-top: 0.1rem;
  white-space: normal;
  overflow-wrap: anywhere;
}
.report-review__thread-content :deep(.report-review__thread-hint .p-tag-label) {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}
.report-review__content-field {
  display: grid;
  min-width: 0;
  max-width: 100%;
  gap: 0.4rem;
}
.report-review__content-label {
  line-height: 1.35;
}
.report-review__content-block {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  padding: 0.75rem;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: var(--content-border-radius);
  background: transparent;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.report-review__content-block p {
  max-width: 100%;
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.report-review__content-block small {
  display: block;
  margin-top: 0.45rem;
  color: var(--text-color-secondary);
  overflow-wrap: anywhere;
}
.report-review__field {
  display: grid;
  gap: 0.35rem;
}
.report-review__delete-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.report-review__spacer {
  flex: 1;
}
.system-report-detail {
  display: grid;
  min-width: 0;
  gap: 1rem;
}
.system-report-detail__content,
.system-report-detail__note {
  min-width: 0;
}
.system-report-detail__note p {
  margin: 0.45rem 0 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.system-report-detail__note {
  color: var(--text-color-secondary);
}
.system-report-detail__read-state {
  display: grid;
  gap: 0.65rem;
  padding: 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: var(--content-border-radius);
  background: transparent;
}
.system-report-detail__read-heading,
.system-report-detail__read-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.system-report-detail__read-heading {
  justify-content: space-between;
}
.system-report-detail__read-state small {
  color: var(--text-color-secondary);
  overflow-wrap: anywhere;
}
.system-read-state-tag {
  white-space: nowrap;
}
:global(.report-management-dialog),
:global(.report-management-dialog .p-component) {
  font-size: var(--app-font-size-base) !important;
}
:global(.report-management-dialog .p-dialog-title) {
  font-size: var(--app-font-size-lg) !important;
  line-height: 1.3;
}
:global(.report-management-dialog .p-inputtext),
:global(.report-management-dialog .p-inputtext::placeholder),
:global(.report-management-dialog textarea),
:global(.report-management-dialog .p-textarea),
:global(.report-management-dialog .p-select),
:global(.report-management-dialog .p-select-label) {
  font-size: var(--app-control-font-size) !important;
}
:global(.report-management-dialog .report-review__field .p-select),
:global(.report-management-dialog .report-review__field .p-select-label),
:global(.report-management-dialog .report-review__field textarea),
:global(.report-management-dialog .report-review__field .p-textarea) {
  background: color-mix(
    in srgb,
    var(--p-form-field-background, var(--bg-primary)) 92%,
    var(--p-surface-300, #cbd5e1) 8%
  ) !important;
}
:global(.report-management-dialog .p-button) {
  min-height: 2rem;
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.25;
}
:global(.report-management-dialog .p-button-label),
:global(.report-management-dialog .p-button-icon) {
  font-size: inherit !important;
}
:global(.report-management-dialog .p-tag) {
  font-size: var(--app-badge-font-size) !important;
  line-height: 1.25 !important;
}
:global(.report-management-dialog .report-review__meta dt),
:global(.report-management-dialog .report-review__meta dd small),
:global(.report-management-dialog .system-report-detail__read-state small),
:global(.report-management-dialog .report-review__field > small) {
  font-size: var(--app-font-size-xs) !important;
  line-height: 1.35;
}
:global(.report-management-dialog .system-report-detail__note p),
:global(.report-management-dialog .report-review__content-block small) {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.35;
}
:global(.report-management-dialog .report-review__message .p-message-text) {
  font-size: var(--app-font-size-sm) !important;
  line-height: 1.4;
}
@media (max-width: 1399.98px) {
  .report-section__header:not(.report-section__header--system) {
    align-items: flex-start;
    flex-direction: column;
  }
  :deep(.report-management__table) {
    overflow: visible;
  }
  :deep(.report-management__table .p-datatable-table-container) {
    overflow: visible;
  }
  :deep(.report-management__table .p-datatable-table) {
    display: block;
    width: 100%;
    min-width: 0 !important;
  }
  :deep(.report-management__table .p-datatable-thead) {
    display: none !important;
  }
  :deep(.report-management__table .p-datatable-tbody) {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    width: 100%;
  }
  :deep(.report-management__table .p-datatable-tbody > tr) {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-width: 0;
    margin: 0;
    box-sizing: border-box;
    gap: 0.75rem;
    padding: 0.95rem;
    border-radius: 8px;
  }
  :deep(.report-management__table .p-datatable-tbody > tr > td) {
    display: none !important;
    width: 100%;
    min-width: 0;
    min-height: 0;
    padding: 0 !important;
    border: 0 !important;
    white-space: normal !important;
  }
  :deep(.report-management__table .p-column-title) {
    display: none !important;
  }
  :deep(.report-management__system-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.report-management__comment-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.report-management__wish-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.report-management__archive-table .p-datatable-tbody > tr > td:nth-child(2)) {
    display: flex !important;
    flex-direction: column;
    align-items: stretch;
    width: 100% !important;
    min-width: 0 !important;
    max-width: none !important;
    box-sizing: border-box;
  }
  :deep(.report-management__system-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.report-management__comment-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.report-management__wish-table .p-datatable-tbody > tr > td:nth-child(2)),
  :deep(.report-management__archive-table .p-datatable-tbody > tr > td:nth-child(2)) {
    order: 1;
  }
  :deep(.report-management__table .p-datatable-empty-message > td) {
    display: block !important;
    order: 1;
    padding: 0.75rem !important;
    border-top: 0 !important;
    color: var(--text-color-secondary);
    text-align: center;
  }
  .report-mobile-card-content {
    display: grid;
  }
  .report-mobile-card__header {
    grid-area: header;
    width: 100%;
    min-width: 0;
    min-height: 0;
    margin-top: 0;
    align-self: start;
  }
  .report-mobile-card-header {
    display: grid;
    grid-template-columns: minmax(0, 1fr) max-content;
    align-items: flex-start;
    gap: 0.8rem;
    width: 100%;
    min-width: 0;
  }
  .report-mobile-card-title {
    display: -webkit-box;
    flex: 1 1 auto;
    min-width: 0;
    max-height: calc(1.3em * 2);
    overflow: hidden;
    color: var(--text-color);
    font-size: var(--app-font-size-base);
    font-weight: 800;
    line-height: 1.3;
    overflow-wrap: anywhere;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }
  .report-mobile-card-status {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    justify-self: end;
    width: auto;
    min-width: max-content;
    max-width: none;
    box-sizing: border-box;
    white-space: nowrap;
  }
  .report-mobile-card-status :deep(.p-tag-label) {
    overflow: visible;
    white-space: nowrap;
  }
  .report-mobile-card-badges {
    grid-column: 1 / -1;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    margin-top: 0.55rem;
  }
  .report-mobile-card__body {
    grid-area: body;
    display: grid;
    grid-template-areas:
      'summary'
      'metadata';
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto;
    align-content: start;
    gap: 0.65rem;
    width: 100%;
    min-width: 0;
    min-height: 0;
    margin-top: 0.65rem;
  }
  .report-mobile-card__summary,
  .report-mobile-card__metadata {
    width: 100%;
    min-width: 0;
    max-width: none;
    box-sizing: border-box;
  }
  .report-mobile-card__summary {
    grid-area: summary;
    justify-self: stretch;
  }
  .report-mobile-card__metadata {
    grid-area: metadata;
    align-self: start;
  }
  .report-mobile-summary-preview {
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    margin: 0;
    padding: 0.55rem 0.65rem;
    border: 1px solid color-mix(in srgb, var(--border-color) 76%, transparent);
    border-radius: var(--content-border-radius);
    background: transparent;
  }
  .report-mobile-summary-preview__label {
    display: block;
    margin-bottom: 0.22rem;
    color: var(--text-color-secondary);
    font-size: var(--app-font-size-xs);
    font-weight: 700;
    line-height: 1.25;
  }
  .report-mobile-summary-preview__text {
    display: -webkit-box;
    width: 100%;
    min-width: 0;
    max-height: calc(1.4em * 3);
    margin: 0;
    overflow: hidden;
    overflow-wrap: anywhere;
    color: var(--text-color);
    font-size: var(--app-font-size-sm);
    line-height: 1.4;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
  }
  .report-mobile-info-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.42rem 0.65rem;
    align-content: start;
    margin: 0;
  }
  .report-mobile-info-item {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.12rem 0.35rem;
    min-width: 0;
  }
  .report-mobile-info-item dt {
    flex: 0 0 auto;
    color: var(--text-color-secondary);
    font-size: var(--app-font-size-xs);
    font-weight: 650;
    line-height: 1.2;
  }
  .report-mobile-info-item dd {
    flex: 1 1 auto;
    min-width: 0;
    margin: 0;
    color: var(--text-color);
    font-size: var(--app-font-size-sm);
    line-height: 1.3;
    overflow-wrap: anywhere;
  }
  .report-mobile-info-item--wide {
    grid-column: span 2;
  }
  .report-mobile-card__footer {
    margin-top: 0.75rem;
    padding-top: 0.75rem;
  }
  .report-row-actions {
    justify-content: flex-end;
    width: 100%;
    gap: 0.45rem;
  }
}
@container report-card (min-width: 42rem) {
  .report-mobile-card__body {
    grid-template-areas: 'summary metadata';
    grid-template-columns: minmax(15rem, 0.72fr) minmax(0, 1.28fr);
    grid-template-rows: auto;
    align-items: stretch;
    gap: 1.15rem;
  }
  .report-mobile-card__summary {
    display: grid;
    align-content: center;
  }
}
@container report-section (max-width: 25rem) {
  :deep(.report-management__table .p-datatable-tbody > tr) {
    gap: 0.5rem;
    padding: 0.8rem;
  }
}
@container report-card (max-width: 25rem) {
  .report-mobile-card__body {
    gap: 0.8rem;
  }
  .report-mobile-info-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 0.55rem;
  }
  .report-mobile-info-item--wide {
    grid-column: auto;
  }
}
@media (max-width: 760px) {
  .report-review__meta {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.45rem 0.6rem;
  }
  .report-review__meta dd {
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
  }
  .report-review__actions {
    flex-wrap: wrap;
  }
}
</style>
