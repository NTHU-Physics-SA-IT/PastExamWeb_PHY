<template>
  <div>
    <Dialog
      :visible="modelValue"
      @update:visible="$emit('update:modelValue', $event)"
      class="archive-upload-dialog"
      :class="{
        'archive-upload-dialog-christmas': christmas,
        'archive-edit-dialog-christmas': christmas,
      }"
      :modal="true"
      :draggable="false"
      :closeOnEscape="false"
      :style="{ width: '700px', maxWidth: '90vw' }"
      :autoFocus="false"
      :pt="{ root: { 'aria-label': dialogTitle, 'aria-labelledby': null } }"
    >
      <template #header>
        <div class="flex align-items-center gap-2.5">
          <i class="pi pi-cloud-upload text-2xl" />
          <div class="text-xl leading-tight font-semibold">{{ dialogTitle }}</div>
        </div>
      </template>
      <Stepper :value="uploadStep" @update:value="uploadStep = $event" linear>
        <StepList>
          <Step value="1" :pt="christmasStepPt">{{ $t('選擇課程') }}</Step>
          <Step value="2" :pt="christmasStepPt">{{ $t('考試資訊') }}</Step>
          <Step value="3" :pt="christmasStepPt">{{
            isWishMode ? $t('許願標題') : $t('上傳檔案')
          }}</Step>
          <Step value="4" :pt="christmasStepPt">{{ $t('確認資訊') }}</Step>
        </StepList>

        <StepPanels>
          <StepPanel v-slot="{ activateCallback }" value="1">
            <div class="flex flex-column gap-4">
              <div v-if="!sourceWishId && !isEditMode" class="request-mode-panel">
                <div class="flex align-items-start gap-2">
                  <Checkbox
                    v-model="form.requestNewCourse"
                    :binary="true"
                    inputId="request-new-course"
                    name="request-new-course"
                    :disabled="form.requestNewCategory"
                  />
                  <div>
                    <label for="request-new-course" class="font-semibold">{{
                      $t('申請新增課程')
                    }}</label>
                    <div class="text-sm text-500 mt-1">
                      {{
                        isWishMode
                          ? $t(
                              '勾選後，許願會保存課程申請資訊；協助上傳後仍須經審核，通過後才建立新課程。'
                            )
                          : $t(
                              '勾選後，這份考古會先進入審核；管理者通過後才建立新課程並公開考古題。'
                            )
                      }}
                    </div>
                    <div v-if="form.requestNewCategory" class="text-sm text-500 mt-1">
                      {{ $t('新增分類必須同時申請新增課程。') }}
                    </div>
                  </div>
                </div>
                <div class="flex align-items-start gap-2 mt-3">
                  <Checkbox
                    v-model="form.requestNewCategory"
                    :binary="true"
                    inputId="request-new-category"
                    name="request-new-category"
                  />
                  <div>
                    <label for="request-new-category" class="font-semibold">{{
                      $t('同時申請新增課程分類')
                    }}</label>
                    <div class="text-sm text-500 mt-1">
                      {{ $t('適合現有分類都不合用的課程；勾選後會自動視為新增課程申請。') }}
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="form.requestNewCategory" class="new-category-grid">
                <div class="flex flex-column gap-2">
                  <label>{{ $t('新分類 Key') }}</label>
                  <InputText
                    id="requested-category-key"
                    name="requested-category-key"
                    v-model="form.requestedCategoryKey"
                    :placeholder="$t('例如 astrophysics')"
                    class="w-full"
                    :class="{ 'p-invalid': form.requestedCategoryKey && !isCategoryKeyValid }"
                  />
                  <small
                    :class="
                      form.requestedCategoryKey && !isCategoryKeyValid ? 'p-error' : 'text-gray-500'
                    "
                  >
                    {{ $t('請使用小寫英文字母、數字或連字號，2 到 40 字。') }}
                  </small>
                </div>
                <div class="flex flex-column gap-2">
                  <label for="requested-category-name">{{ $t('分類中文名稱') }}</label>
                  <InputText
                    id="requested-category-name"
                    name="requested-category-name"
                    v-model="form.requestedCategoryName"
                    :placeholder="$t('例如 天文物理')"
                    class="w-full"
                  />
                </div>
                <div class="flex flex-column gap-2">
                  <label for="requested-category-name-en">{{ $t('英文分類名稱') }}</label>
                  <InputText
                    id="requested-category-name-en"
                    name="requested-category-name-en"
                    v-model="form.requestedCategoryNameEn"
                    :placeholder="$t('例如 Astrophysics')"
                    class="w-full"
                  />
                </div>
                <div class="flex flex-column gap-2">
                  <label for="requested-category-label">{{ $t('中文短標籤') }}</label>
                  <InputText
                    id="requested-category-label"
                    name="requested-category-label"
                    v-model="form.requestedCategoryLabel"
                    :placeholder="$t('例如 天文')"
                    class="w-full"
                  />
                </div>
                <div class="flex flex-column gap-2">
                  <label for="requested-category-label-en">{{ $t('英文短標籤') }}</label>
                  <InputText
                    id="requested-category-label-en"
                    name="requested-category-label-en"
                    v-model="form.requestedCategoryLabelEn"
                    :placeholder="$t('例如 Astro')"
                    class="w-full"
                  />
                </div>
              </div>

              <div class="flex flex-column gap-2">
                <label>{{ $t('課程類別') }}</label>
                <Select
                  inputId="upload-category"
                  name="upload-category"
                  v-model="form.category"
                  :options="categoryOptions"
                  optionLabel="name"
                  optionValue="value"
                  :placeholder="$t('選擇課程類別')"
                  class="w-full"
                  :disabled="form.requestNewCategory || Boolean(sourceWishId)"
                  :panelClass="{
                    'archive-edit-overlay-christmas': christmas,
                  }"
                />
                <small v-if="form.requestNewCategory" class="text-gray-500">
                  {{ $t('已改為申請新分類，這份考古會歸到上方的新分類。') }}
                </small>
              </div>

              <div v-if="form.requestNewCourse" class="flex flex-column gap-2">
                <label for="requested-course-name">{{
                  $t('課程中文名稱 / Course Name (Chinese)')
                }}</label>
                <InputText
                  id="requested-course-name"
                  name="requested-course-name"
                  v-model="form.requestedCourseName"
                  :placeholder="$t('例如 普通物理(一)')"
                  class="w-full"
                />
              </div>

              <div v-if="form.requestNewCourse" class="flex flex-column gap-2">
                <label for="requested-course-name-en">{{
                  $t('課程英文名稱 / Course Name (English)')
                }}</label>
                <InputText
                  id="requested-course-name-en"
                  name="requested-course-name-en"
                  v-model="form.requestedCourseNameEn"
                  :placeholder="$t('例如 General Physics (I)')"
                  class="w-full"
                />
              </div>

              <div v-else class="flex flex-column gap-2">
                <label>{{ $t('課程名稱') }}</label>
                <Select
                  inputId="upload-subject"
                  name="upload-subject"
                  v-model="form.subject"
                  :options="subjectOptions"
                  optionLabel="name"
                  :placeholder="$t('選擇課程名稱')"
                  class="w-full"
                  :disabled="!form.category || Boolean(sourceWishId)"
                  :panelClass="{
                    'archive-edit-overlay-christmas': christmas,
                  }"
                  filter
                  showClear
                >
                  <template #item="{ item }">
                    <div>{{ item.name }}</div>
                  </template>
                </Select>
                <small v-if="!isEditMode" class="text-gray-500">{{
                  $t('若課程不在列表上，請勾選「申請新增課程」。')
                }}</small>
              </div>

              <div class="flex flex-column gap-2">
                <label>{{ $t('授課教授') }}</label>
                <AutoComplete
                  inputId="upload-professor"
                  name="upload-professor"
                  :modelValue="form.professor"
                  @update:modelValue="(val) => (form.professor = val)"
                  :suggestions="availableProfessors"
                  @complete="searchProfessor"
                  @item-select="onProfessorSelect"
                  @focus="() => searchProfessor({ query: '' })"
                  @click="() => searchProfessor({ query: '' })"
                  optionLabel="name"
                  :placeholder="$t('搜尋或輸入授課教授')"
                  class="w-full"
                  :disabled="!effectiveSubject || Boolean(sourceWishId)"
                  :panelClass="{
                    'archive-edit-overlay-christmas': christmas,
                  }"
                  dropdown
                  completeOnFocus
                  :minLength="0"
                  autoHighlight="true"
                >
                  <template #item="{ item }">
                    <div>{{ item.name }}</div>
                  </template>
                </AutoComplete>
                <small class="text-gray-500">{{
                  $t('如果授課教授不在列表上，可自行輸入新增')
                }}</small>
              </div>
            </div>
            <div class="flex pt-6 justify-end">
              <Button
                :label="$t('下一步')"
                icon="pi pi-arrow-right"
                class="archive-upload-next-button"
                :data-christmas-snow-control="christmas ? 'true' : undefined"
                @click="activateCallback('2')"
                :disabled="!canGoToStep2"
              />
            </div>
          </StepPanel>

          <StepPanel v-slot="{ activateCallback }" value="2">
            <div class="flex flex-column gap-4">
              <div class="flex flex-column gap-2">
                <div class="flex align-items-center justify-content-between gap-2">
                  <label>{{ isWishMode ? $t('考試學期（選填）') : $t('考試學期') }}</label>
                  <Button
                    v-if="isWishMode && form.academicYear"
                    type="button"
                    :label="$t('清除選取')"
                    text
                    size="small"
                    @click="form.academicYear = null"
                  />
                </div>
                <div class="semester-picker">
                  <div class="semester-picker-value">
                    {{
                      formatSemester(form.academicYear) ||
                      (isWishMode ? $t('不限學期') : $t('選擇考試學期'))
                    }}
                  </div>
                  <div class="semester-grid" role="listbox" :aria-label="$t('選擇考試學期')">
                    <div v-for="group in semesterGroups" :key="group.year" class="semester-row">
                      <div class="semester-year">{{ group.year }}</div>
                      <button
                        v-for="semester in group.semesters"
                        :key="semester.code"
                        type="button"
                        class="semester-option"
                        :class="{ selected: form.academicYear === semester.code }"
                        @click="form.academicYear = semester.code"
                      >
                        {{ semester.label }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div class="flex flex-column gap-2">
                <label>{{ $t('考試類型') }}</label>
                <Select
                  inputId="upload-exam-type"
                  name="upload-exam-type"
                  v-model="form.type"
                  :options="[
                    { name: $t('期中考'), value: 'midterm' },
                    { name: $t('期末考'), value: 'final' },
                    { name: $t('小考'), value: 'quiz' },
                    { name: $t('其他'), value: 'other' },
                  ]"
                  optionLabel="name"
                  optionValue="value"
                  :placeholder="$t('選擇考試類型')"
                  class="w-full"
                  :disabled="Boolean(sourceWishId)"
                  :panelClass="{
                    'archive-edit-overlay-christmas': christmas,
                  }"
                />
              </div>

              <div v-if="requiresExamNumber" class="flex flex-column gap-2">
                <label>{{ form.type === 'midterm' ? $t('第幾次期中考') : $t('第幾次小考') }}</label>
                <Select
                  inputId="upload-exam-number"
                  name="upload-exam-number"
                  v-model="form.examNumber"
                  :options="examNumberOptions"
                  optionLabel="name"
                  optionValue="value"
                  :placeholder="$t('選擇次數')"
                  class="w-full"
                  :disabled="Boolean(sourceWishId)"
                  :panelClass="{
                    'archive-edit-overlay-christmas': christmas,
                  }"
                />
                <small class="text-gray-500">
                  {{
                    $t('系統會自動建立名稱：{name}', {
                      name: generatedFilename || $t('請先選擇次數'),
                    })
                  }}
                </small>
              </div>

              <div v-if="form.type === 'other'" class="flex flex-column gap-2">
                <label for="filename-input">{{ $t('其他考試名稱') }}</label>
                <div class="relative w-full">
                  <InputText
                    id="filename-input"
                    name="filename-input"
                    v-model="form.otherName"
                    :placeholder="$t('例如 retake1')"
                    class="w-full pr-8"
                    :disabled="Boolean(sourceWishId)"
                    :class="{
                      'p-invalid': form.otherName && !isFilenameValid,
                    }"
                    :maxlength="30"
                    @input="validateFilename"
                  />
                  <i
                    v-if="isFilenameValid && form.otherName"
                    class="pi pi-check text-green-500 absolute right-3 top-1/2 -mt-2"
                  />
                  <i
                    v-else-if="form.otherName"
                    class="pi pi-times text-red-500 absolute right-3 top-1/2 -mt-2"
                  />
                </div>
                <small v-if="form.otherName && !isFilenameValid" class="p-error">
                  {{ $t('名稱格式必須是小寫英文字母和阿拉伯數字，數字需放在結尾（如：makeup1）') }}
                </small>
                <small v-else class="text-gray-500">
                  {{ $t('請輸入小寫英文字母和阿拉伯數字，數字需放在結尾（如：makeup1）') }}
                </small>
              </div>

              <div v-if="form.type === 'final'" class="flex flex-column gap-2">
                <label>{{ $t('考試名稱') }}</label>
                <InputText
                  id="generated-filename"
                  name="generated-filename"
                  :modelValue="generatedFilename"
                  class="w-full"
                  disabled
                />
              </div>

              <div v-if="!isWishMode" class="flex align-items-center gap-2">
                <Checkbox
                  inputId="upload-has-answers"
                  name="upload-has-answers"
                  v-model="form.hasAnswers"
                  :binary="true"
                />
                <label for="upload-has-answers">{{ $t('附解答') }}</label>
              </div>
            </div>
            <div class="flex pt-6 justify-between">
              <Button
                :label="$t('上一步')"
                icon="pi pi-arrow-left"
                class="archive-upload-back-button"
                severity="secondary"
                @click="activateCallback('1')"
              />
              <Button
                :label="$t('下一步')"
                icon="pi pi-arrow-right"
                class="archive-upload-next-button"
                :data-christmas-snow-control="christmas ? 'true' : undefined"
                @click="activateCallback('3')"
                :disabled="!canGoToStep3"
              />
            </div>
          </StepPanel>

          <StepPanel v-slot="{ activateCallback }" value="3">
            <div v-if="isWishMode" class="flex flex-column gap-2">
              <label for="archive-wish-title">{{ $t('許願標題') }}</label>
              <InputText
                id="archive-wish-title"
                v-model="form.wishTitle"
                maxlength="150"
                class="w-full"
                :placeholder="$t('例如: 王道維普物一 midterm1')"
              />
            </div>
            <div v-else class="flex flex-column gap-4">
              <div v-if="isEditMode" class="current-file-panel">
                <div>
                  <div class="font-semibold">{{ $t('目前 PDF') }}</div>
                  <div class="text-sm text-500 mt-1">
                    {{ form.file ? $t('將撤換目前檔案') : $t('保留目前檔案') }}
                  </div>
                </div>
                <Button
                  type="button"
                  icon="pi pi-eye"
                  :label="$t('預覽目前 PDF')"
                  severity="secondary"
                  outlined
                  :loading="uploadPreviewLoading && previewingCurrentFile"
                  @click="previewCurrentFile"
                />
              </div>
              <FileUpload
                ref="fileUpload"
                accept="application/pdf"
                :maxFileSize="MAX_PDF_SIZE_BYTES"
                :invalidFileSizeMessage="$t('{0}：PDF 檔案超過 20 MB 大小上限')"
                class="w-full"
                @select="onFileSelect"
                :multiple="false"
                :auto="false"
              >
                <template #header="{ chooseCallback }">
                  <div class="flex justify-between items-center flex-1 gap-4">
                    <div class="flex gap-2">
                      <Button
                        @click="chooseCallback()"
                        icon="pi pi-file-pdf"
                        class="archive-upload-file-picker-button"
                        :data-christmas-snow="christmas ? 'off' : undefined"
                        rounded
                        outlined
                        severity="secondary"
                        :label="$t('選擇檔案')"
                      ></Button>
                    </div>
                    <div v-if="form.file" class="text-sm text-500">
                      {{ formatFileSize(form.file.size) }} / 20MB
                    </div>
                  </div>
                </template>

                <template #content="{ removeFileCallback }">
                  <div v-if="form.file" class="flex flex-col gap">
                    <div class="p-4 surface-50 border-1 border-round">
                      <div class="flex align-items-center gap-3">
                        <i class="pi pi-file-pdf text-2xl"></i>
                        <div class="flex-1">
                          <div class="font-semibold text-overflow-ellipsis overflow-hidden">
                            {{ form.file.name }}
                          </div>
                          <div class="text-sm text-500">
                            {{ formatFileSize(form.file.size) }}
                          </div>
                        </div>
                        <Button
                          icon="pi pi-times"
                          :aria-label="$t('移除已選檔案')"
                          :title="$t('移除已選檔案')"
                          @click="clearSelectedFile(removeFileCallback)"
                          outlined
                          rounded
                          severity="danger"
                          size="small"
                        />
                      </div>
                    </div>
                  </div>
                </template>

                <template #empty>
                  <div
                    v-if="!form.file"
                    class="flex align-items-center justify-content-center flex-column p-5 border-1 border-dashed border-round"
                  >
                    <i
                      class="pi pi-cloud-upload border-2 border-round p-5 text-4xl text-500 mb-3"
                    ></i>
                    <p class="m-0 text-600">
                      {{
                        isEditMode
                          ? $t('選擇新的 PDF 以撤換目前檔案')
                          : $t('將 PDF 檔案拖放至此處以上傳')
                      }}
                    </p>
                    <p class="m-0 text-sm text-500 mt-2">
                      {{ $t('僅接受 PDF 檔案，檔案大小最大 20MB') }}
                    </p>
                  </div>
                </template>
              </FileUpload>
              <small
                v-if="fileValidationError"
                id="archive-upload-file-error"
                class="p-error"
                role="alert"
              >
                {{ fileValidationError }}
              </small>
            </div>
            <div class="flex pt-6 justify-between">
              <Button
                :label="$t('上一步')"
                icon="pi pi-arrow-left"
                class="archive-upload-back-button"
                severity="secondary"
                @click="activateCallback('2')"
              />
              <Button
                :label="$t('下一步')"
                icon="pi pi-arrow-right"
                class="archive-upload-next-button"
                :data-christmas-snow-control="christmas ? 'true' : undefined"
                @click="activateCallback('4')"
                :disabled="isWishMode ? !form.wishTitle.trim() : !isEditMode && !form.file"
              />
            </div>
          </StepPanel>

          <StepPanel v-slot="{ activateCallback }" value="4">
            <div class="flex flex-column gap-4">
              <div class="flex flex-column gap-2 p-3 surface-ground border-round">
                <div v-if="isWishMode">
                  <strong>{{ $t('許願標題：') }}</strong> {{ form.wishTitle }}
                </div>
                <div>
                  <strong>{{ $t('投稿類型：') }}</strong>
                  {{ submissionKindLabel }}
                </div>
                <div v-if="form.requestNewCategory">
                  <strong>{{ $t('申請分類中文名稱：') }}</strong>
                  {{ form.requestedCategoryName }}（{{ form.requestedCategoryKey }}）
                </div>
                <div v-if="form.requestNewCategory">
                  <strong>{{ $t('申請分類英文名稱：') }}</strong>
                  {{ form.requestedCategoryNameEn }}
                </div>
                <div v-if="form.requestNewCategory">
                  <strong>{{ $t('申請分類短標籤：') }}</strong>
                  {{ form.requestedCategoryLabel }} / {{ form.requestedCategoryLabelEn }}
                </div>
                <div>
                  <strong>{{ $t('課程類別：') }}</strong>
                  {{ effectiveCategoryName }}
                </div>
                <div>
                  <strong>{{
                    form.requestNewCourse ? $t('課程中文名稱：') : $t('課程名稱：')
                  }}</strong>
                  {{ effectiveSubject || '' }}
                </div>
                <div v-if="form.requestNewCourse">
                  <strong>{{ $t('課程英文名稱：') }}</strong>
                  {{ effectiveSubjectEn }}
                </div>
                <div>
                  <strong>{{ $t('授課教授：') }}</strong> {{ form.professor }}
                </div>
                <div>
                  <strong>{{ $t('考試學期：') }}</strong>
                  {{ formatSemester(form.academicYear) || $t('不限學期') }}
                </div>
                <div>
                  <strong>{{ $t('考試類型：') }}</strong>
                  {{ getTypeName(form.type) }}
                </div>
                <div>
                  <strong>{{ $t('考試名稱：') }}</strong> {{ generatedFilename }}
                </div>
                <div v-if="!isWishMode">
                  <strong>{{ $t('附解答：') }}</strong>
                  {{ form.hasAnswers ? $t('是') : $t('否') }}
                </div>
                <div v-if="isEditMode">
                  <strong>{{ $t('PDF：') }}</strong>
                  {{ form.file ? form.file.name : $t('保留目前檔案') }}
                </div>
              </div>
              <p v-if="!isWishMode" class="m-0 text-sm text-color-secondary line-height-3">
                {{
                  $t(
                    'PDF 處理說明：為確保檔案相容性與安全性，部分 PDF 可能在上傳時自動進行正規化處理；若原檔包含數位簽章，正規化後原有簽章將不會保留。'
                  )
                }}
              </p>
            </div>
            <div class="flex pt-6 justify-between">
              <Button
                :label="$t('上一步')"
                icon="pi pi-arrow-left"
                class="archive-upload-back-button"
                severity="secondary"
                @click="activateCallback('3')"
              />
              <div class="flex gap-2.5">
                <Button
                  v-if="!isWishMode && (!isEditMode || form.file)"
                  icon="pi pi-eye"
                  :label="$t('預覽')"
                  severity="secondary"
                  @click="previewUploadFile"
                />
                <Button
                  :label="isWishMode ? $t('送出許願') : isEditMode ? $t('儲存') : $t('上傳')"
                  :icon="
                    isWishMode ? 'pi pi-sparkles' : isEditMode ? 'pi pi-check' : 'pi pi-upload'
                  "
                  severity="success"
                  @click="handleUpload"
                  :loading="uploading"
                  :disabled="!canUpload"
                />
              </div>
            </div>
          </StepPanel>
        </StepPanels>
      </Stepper>
    </Dialog>

    <PdfPreviewModal
      :visible="showUploadPreview"
      @update:visible="showUploadPreview = $event"
      :christmas="christmas && !isWishMode"
      :previewUrl="uploadPreviewUrl"
      :title="
        previewingCurrentFile
          ? `${generatedFilename || prefill?.name || ''}.pdf`
          : form.file?.name || ''
      "
      :academicYear="form.academicYear"
      :archiveType="form.type || ''"
      :courseName="effectiveSubject || ''"
      :professorName="
        typeof form.professor === 'string' ? form.professor : form.professor?.name || ''
      "
      :loading="uploadPreviewLoading"
      :error="uploadPreviewError"
      :showDownload="false"
      @hide="closeUploadPreview"
      @error="handleUploadPreviewError"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToast } from 'primevue/usetoast'
import { courseService, archiveService, wishService } from '../api'
import PdfPreviewModal from './PdfPreviewModal.vue'
import { PDFDocument } from 'pdf-lib'
import { trackEvent, EVENTS } from '../utils/analytics'
import { isUnauthorizedError } from '../utils/http'
import { formatCourseDisplayName } from '../utils/courseText'
import { formatAcademicTerm as formatCanonicalAcademicTerm } from '../utils/academicTerm'
import { localizedCategoryName, localizedCourseName } from '../utils/localizedCatalog'

const MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  coursesList: {
    type: Object,
    required: true,
  },
  courseCategories: {
    type: Array,
    default: () => [],
  },
  prefill: { type: Object, default: null },
  sourceWishId: { type: Number, default: null },
  mode: { type: String, default: 'upload' },
  submissionId: { type: Number, default: null },
  christmas: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'upload-success', 'stale'])

const toast = useToast()
const { t } = useI18n()
const NEW_CATEGORY_REQUIRES_COURSE_MESSAGE = '新增分類必須同時申請新增課程。'
const isWishMode = computed(() => props.mode === 'wish')
const isEditMode = computed(() => props.mode === 'edit')
const christmasStepPt = computed(() => ({
  header: {
    'data-christmas-snow': props.christmas ? 'off' : undefined,
  },
}))
const dialogTitle = computed(() =>
  isWishMode.value
    ? t('新增考古許願')
    : isEditMode.value
      ? t('編輯考古投稿')
      : props.sourceWishId
        ? t('協助上傳考古題')
        : t('上傳考古題')
)
let applyingPrefill = false

const form = ref({
  category: null,
  subject: null,
  subjectId: null,
  requestNewCourse: false,
  requestedCourseName: '',
  requestedCourseNameEn: '',
  requestNewCategory: false,
  requestedCategoryKey: '',
  requestedCategoryName: '',
  requestedCategoryNameEn: '',
  requestedCategoryLabel: '',
  requestedCategoryLabelEn: '',
  professor: null,
  filename: '',
  examNumber: null,
  otherName: '',
  type: null,
  hasAnswers: false,
  academicYear: null,
  file: null,
  wishTitle: '',
})

const uploadStep = ref('1')
const uploading = ref(false)
const fileUpload = ref(null)
const fileValidationError = ref('')
const uploadFormProfessors = ref([])
const isFilenameValid = ref(false)

const showUploadPreview = ref(false)
const uploadPreviewUrl = ref('')
const uploadPreviewLoading = ref(false)
const uploadPreviewError = ref(false)
const previewingCurrentFile = ref(false)

const availableProfessors = ref([])

const normalizedProfessor = computed(() =>
  typeof form.value.professor === 'string'
    ? form.value.professor.trim()
    : form.value.professor?.name?.trim() || ''
)

const categoryOptions = computed(() =>
  props.courseCategories.map((category) => ({
    name: localizedCategoryName(category),
    value: category.key,
  }))
)

const subjectOptions = computed(() =>
  (props.coursesList[form.value.category] || [])
    .filter((course) => !course.deleted_at)
    .map((course) => ({
      name: localizedCourseName(course),
      canonicalName: course.name,
      code: course.id,
    }))
)

const examNumberOptions = computed(() =>
  Array.from({ length: 20 }, (_, index) => ({
    name: t('第 {count} 次', { count: index + 1 }),
    value: index + 1,
  }))
)

const currentSemesterCode = (() => {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth() + 1
  const rocYear = month >= 8 ? year - 1911 : year - 1912
  const semester = month >= 8 || month === 1 ? 1 : 2
  return rocYear * 10 + semester
})()

const semesterGroups = computed(() => {
  const groups = []
  const currentRocYear = Math.floor(currentSemesterCode / 10)
  const currentSemester = currentSemesterCode % 10

  for (let year = currentRocYear; year >= 89; year -= 1) {
    const semesters = []
    for (const semester of [1, 2]) {
      if (year === currentRocYear && semester > currentSemester) continue
      semesters.push({
        label: t(semester === 1 ? '上學期' : '下學期'),
        code: year * 10 + semester,
      })
    }
    if (semesters.length) {
      groups.push({ year, semesters })
    }
  }

  return groups
})

const requiresExamNumber = computed(() => ['midterm', 'quiz'].includes(form.value.type))

const isCategoryKeyValid = computed(() =>
  /^[a-z0-9-]{2,40}$/.test((form.value.requestedCategoryKey || '').trim())
)

const effectiveSubject = computed(() => {
  if (form.value.requestNewCourse) return formatCourseDisplayName(form.value.requestedCourseName)
  if (typeof form.value.subject === 'string') return formatCourseDisplayName(form.value.subject)
  return formatCourseDisplayName(form.value.subject?.name)
})

const canonicalSubject = computed(() => {
  if (form.value.requestNewCourse) return effectiveSubject.value
  if (typeof form.value.subject === 'string') return formatCourseDisplayName(form.value.subject)
  return formatCourseDisplayName(form.value.subject?.canonicalName || form.value.subject?.name)
})

const effectiveSubjectEn = computed(() =>
  form.value.requestNewCourse ? form.value.requestedCourseNameEn.trim() : ''
)

const effectiveCategory = computed(() => {
  if (form.value.requestNewCategory)
    return (form.value.requestedCategoryKey || '').trim().toLowerCase()
  return form.value.category
})

const effectiveCategoryName = computed(() => {
  if (form.value.requestNewCategory) return (form.value.requestedCategoryName || '').trim()
  return getCategoryName(form.value.category)
})

const submissionKindLabel = computed(() => {
  if (form.value.requestNewCategory) return t('新分類與新課程申請')
  if (form.value.requestNewCourse) return t('新課程申請')
  return t('既有課程投稿')
})

const generatedFilename = computed(() => {
  if (form.value.type === 'midterm' && form.value.examNumber) {
    return `midterm${form.value.examNumber}`
  }
  if (form.value.type === 'quiz' && form.value.examNumber) {
    return `quiz${form.value.examNumber}`
  }
  if (form.value.type === 'final') return 'final'
  if (form.value.type === 'other') return form.value.otherName
  return ''
})

const canGoToStep2 = computed(() => {
  if (form.value.requestNewCategory && !form.value.requestNewCourse) return false
  const hasCategory = form.value.requestNewCategory
    ? isCategoryKeyValid.value &&
      form.value.requestedCategoryName.trim() &&
      form.value.requestedCategoryNameEn.trim() &&
      form.value.requestedCategoryLabel.trim() &&
      form.value.requestedCategoryLabelEn.trim()
    : form.value.category
  const hasCourseNames = form.value.requestNewCourse
    ? effectiveSubject.value && effectiveSubjectEn.value
    : effectiveSubject.value
  return hasCategory && hasCourseNames && form.value.professor
})

const canGoToStep3 = computed(() => {
  return (
    (isWishMode.value || form.value.academicYear) &&
    form.value.type &&
    generatedFilename.value &&
    isFilenameValid.value
  )
})

const canUpload = computed(() => {
  if (isWishMode.value) {
    return Boolean(
      form.value.wishTitle.trim() &&
      canGoToStep2.value &&
      canGoToStep3.value &&
      (form.value.requestNewCourse || form.value.subjectId)
    )
  }
  if (isEditMode.value) {
    return Boolean(
      form.value.subjectId &&
      effectiveCategory.value &&
      effectiveSubject.value &&
      normalizedProfessor.value &&
      form.value.academicYear &&
      form.value.type &&
      generatedFilename.value &&
      isFilenameValid.value
    )
  }
  return (
    form.value.file &&
    effectiveCategory.value &&
    effectiveSubject.value &&
    (!form.value.requestNewCourse || effectiveSubjectEn.value) &&
    (!form.value.requestNewCategory ||
      (form.value.requestedCategoryNameEn.trim() &&
        form.value.requestedCategoryLabel.trim() &&
        form.value.requestedCategoryLabelEn.trim())) &&
    form.value.professor &&
    form.value.academicYear &&
    form.value.type &&
    generatedFilename.value
  )
})

function validateFilename() {
  const regex = /^[a-z]+[0-9]*$/
  isFilenameValid.value = regex.test(generatedFilename.value)
}

function formatSemester(value) {
  const numericValue = Number(value)
  if (!numericValue) return ''
  return formatCanonicalAcademicTerm(numericValue, t) || `${numericValue}`
}

function getCategoryName(code) {
  return (
    localizedCategoryName(props.courseCategories.find((category) => category.key === code)) || code
  )
}

function getTypeName(code) {
  const types = {
    midterm: t('期中考'),
    final: t('期末考'),
    quiz: t('小考'),
    other: t('其他'),
  }
  return types[code] || code
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

async function fetchProfessorsForSubject(subjectId) {
  if (!subjectId) return

  try {
    const response = await courseService.getCourseArchives(subjectId)
    const archiveData = response.data

    const uniqueProfessors = new Set()
    archiveData.forEach((archive) => {
      if (archive.professor) uniqueProfessors.add(archive.professor)
    })

    uploadFormProfessors.value = Array.from(uniqueProfessors)
      .sort()
      .map((professor) => ({
        name: professor,
        code: professor,
      }))
  } catch (error) {
    console.error('Error fetching professors for subject:', error)
    uploadFormProfessors.value = []
  }
}

const handleUpload = async () => {
  if (isWishMode.value) {
    try {
      uploading.value = true
      await wishService.create({
        title: form.value.wishTitle.trim(),
        course_id: form.value.requestNewCourse ? null : form.value.subjectId,
        subject: canonicalSubject.value,
        category: effectiveCategory.value,
        professor:
          typeof form.value.professor === 'string'
            ? form.value.professor.trim()
            : form.value.professor?.name,
        archive_type: form.value.type,
        name: generatedFilename.value,
        academic_year: form.value.academicYear,
        requested_course_name: form.value.requestNewCourse ? effectiveSubject.value : null,
        requested_course_name_en: form.value.requestNewCourse ? effectiveSubjectEn.value : null,
        requested_category_key: form.value.requestNewCategory ? effectiveCategory.value : null,
        requested_category_name: form.value.requestNewCategory
          ? form.value.requestedCategoryName.trim()
          : null,
        requested_category_name_en: form.value.requestNewCategory
          ? form.value.requestedCategoryNameEn.trim()
          : null,
        requested_category_label: form.value.requestNewCategory
          ? form.value.requestedCategoryLabel.trim()
          : null,
        requested_category_label_en: form.value.requestNewCategory
          ? form.value.requestedCategoryLabelEn.trim()
          : null,
      })
      emit('update:modelValue', false)
      emit('upload-success')
      toast.add({
        severity: 'success',
        summary: t('許願已送出'),
        detail: t('你的考古許願已加入許願池。'),
        life: 3000,
      })
    } catch (error) {
      const detail = error?.response?.data?.detail
      const duplicateWish = detail?.code === 'wish_already_exists'
      const archiveAvailable = detail?.code === 'wish_target_already_available'
      toast.add({
        severity: duplicateWish || archiveAvailable ? 'warn' : 'error',
        summary: archiveAvailable
          ? t('考古已存在')
          : duplicateWish
            ? t('相同許願已存在')
            : t('許願送出失敗'),
        detail: archiveAvailable
          ? t('這份考古已經存在，不需要再許願。')
          : duplicateWish
            ? t('相同目標的許願已存在。')
            : t('發生錯誤，請稍後再試'),
        life: 3000,
      })
    } finally {
      uploading.value = false
    }
    return
  }
  if (
    (!isEditMode.value && !form.value.file) ||
    (form.value.file && form.value.file.size > MAX_PDF_SIZE_BYTES)
  ) {
    fileValidationError.value = t('PDF 檔案超過 20 MB 大小上限')
    uploadStep.value = '3'
    form.value.file = null
    return
  }
  if (form.value.requestNewCategory && !form.value.requestNewCourse) {
    toast.add({
      severity: 'error',
      summary: t('無法送出'),
      detail: t(NEW_CATEGORY_REQUIRES_COURSE_MESSAGE),
      life: 3000,
    })
    return
  }

  try {
    uploading.value = true

    const cleanFileWithName = form.value.file ? await sanitizePdf(form.value.file) : null

    if (isEditMode.value) {
      await archiveService.editOwnerPendingSubmission(props.submissionId, {
        course_id: form.value.subjectId,
        professor: normalizedProfessor.value,
        academic_year: form.value.academicYear,
        archive_type: form.value.type,
        sequence: requiresExamNumber.value ? form.value.examNumber : undefined,
        has_answers: form.value.hasAnswers,
        other_name: form.value.type === 'other' ? form.value.otherName : undefined,
        file: cleanFileWithName || undefined,
      })
      closeUploadPreview()
      emit('update:modelValue', false)
      emit('upload-success')
      toast.add({
        severity: 'success',
        summary: t('更新成功'),
        detail: t('考古投稿已更新，仍在等待審核。'),
        life: 3000,
      })
      return
    }

    const formData = new FormData()
    formData.append('file', cleanFileWithName)
    formData.append('subject', canonicalSubject.value)
    if (!form.value.requestNewCourse && form.value.subjectId) {
      formData.append('course_id', form.value.subjectId)
    }
    formData.append('category', effectiveCategory.value)
    formData.append('professor', form.value.professor)
    formData.append('archive_type', form.value.type)
    formData.append('has_answers', form.value.hasAnswers)
    formData.append('filename', generatedFilename.value)
    formData.append('academic_year', form.value.academicYear)
    formData.append('request_new_course', form.value.requestNewCourse)
    formData.append('request_new_category', form.value.requestNewCategory)
    if (form.value.requestNewCourse) {
      formData.append('requested_course_name', effectiveSubject.value)
      formData.append('requested_course_name_en', effectiveSubjectEn.value)
    }
    if (form.value.requestNewCategory) {
      formData.append('requested_category_key', effectiveCategory.value)
      formData.append('requested_category_name', form.value.requestedCategoryName.trim())
      formData.append('requested_category_name_en', form.value.requestedCategoryNameEn.trim())
      formData.append('requested_category_label', form.value.requestedCategoryLabel.trim())
      formData.append('requested_category_label_en', form.value.requestedCategoryLabelEn.trim())
      formData.append('requested_category_icon', 'pi pi-fw pi-book')
    }
    if (props.sourceWishId) formData.append('source_wish_id', props.sourceWishId)

    const response = await archiveService.uploadArchive(formData)
    const uploadResult = response?.data || {}
    const uploadedSubmission = uploadResult.submission || {}
    const isAdminUpload =
      uploadResult.is_admin_upload === true || uploadedSubmission.is_admin_upload === true

    emit('update:modelValue', false)
    emit('upload-success')

    toast.add({
      severity: 'success',
      summary: isAdminUpload ? t('管理員投稿成功') : t('已送出審核'),
      detail: isAdminUpload
        ? t('考古題已直接建立，不需再經審核。')
        : t('考古題投稿已送至管理者審核，通過後才會公開'),
      life: 3000,
    })
  } catch (error) {
    console.error('Upload error:', error)
    if (isUnauthorizedError(error)) {
      return
    }

    const responseDetail = error?.response?.data?.detail
    if (isEditMode.value && responseDetail?.code === 'archive_submission_stale_state') {
      closeUploadPreview()
      emit('update:modelValue', false)
      emit('stale')
      toast.add({
        severity: 'warn',
        summary: t('投稿狀態已變更'),
        detail: t('投稿狀態已變更，無法再編輯'),
        life: 4000,
      })
      return
    }
    if (responseDetail === 'File size exceeds 20MB limit') {
      fileValidationError.value = t('PDF 檔案超過 20 MB 大小上限')
      uploadStep.value = '3'
      form.value.file = null
      fileUpload.value?.clear()
      return
    }
    toast.add({
      severity: 'error',
      summary: t('上傳失敗'),
      detail: typeof responseDetail === 'string' ? t(responseDetail) : t('發生錯誤，請稍後再試'),
      life: 3000,
    })
  } finally {
    uploading.value = false
  }
}

async function sanitizePdf(file) {
  const fileArrayBuffer = await file.arrayBuffer()
  const pdfDoc = await PDFDocument.load(fileArrayBuffer)
  pdfDoc.setTitle('')
  pdfDoc.setAuthor('')
  pdfDoc.setSubject('')
  pdfDoc.setKeywords([])
  pdfDoc.setProducer('')
  pdfDoc.setCreator('')
  pdfDoc.setCreationDate(new Date())
  pdfDoc.setModificationDate(new Date())
  const pdfBytes = await pdfDoc.save()
  return new File([new Blob([pdfBytes], { type: 'application/pdf' })], file.name, {
    type: 'application/pdf',
  })
}

const onFileSelect = (event) => {
  const newFile = event.files[0]

  closeUploadPreview()
  fileUpload.value?.clear?.()
  form.value.file = null
  fileValidationError.value = ''

  if (!newFile || newFile.size > MAX_PDF_SIZE_BYTES) {
    fileValidationError.value = t('PDF 檔案超過 20 MB 大小上限')
    return
  }

  nextTick(() => {
    form.value.file = newFile
  })
}

function clearSelectedFile(removeFileCallback) {
  if (removeFileCallback) removeFileCallback(0)
  closeUploadPreview()
  form.value.file = null
  fileValidationError.value = ''
  fileUpload.value?.clear?.()
}

function previewUploadFile() {
  if (!form.value.file) return

  previewingCurrentFile.value = false
  uploadPreviewLoading.value = true
  uploadPreviewError.value = false
  closeUploadPreviewUrl()

  try {
    const fileUrl = URL.createObjectURL(new Blob([form.value.file], { type: 'application/pdf' }))
    uploadPreviewUrl.value = fileUrl
    showUploadPreview.value = true

    trackEvent(EVENTS.PREVIEW_ARCHIVE, {
      context: 'upload-dialog',
      fileName: generatedFilename.value,
      fileSize: form.value.file.size,
    })
  } catch (error) {
    console.error('Preview error:', error)
    uploadPreviewError.value = true
    toast.add({
      severity: 'error',
      summary: t('預覽失敗'),
      detail: t('無法預覽檔案'),
      life: 3000,
    })
  } finally {
    uploadPreviewLoading.value = false
  }
}

async function previewCurrentFile() {
  if (!isEditMode.value || !props.submissionId) return
  previewingCurrentFile.value = true
  uploadPreviewLoading.value = true
  uploadPreviewError.value = false
  closeUploadPreviewUrl()
  showUploadPreview.value = true

  try {
    const { data } = await archiveService.getOwnerPendingPreviewFile(props.submissionId)
    uploadPreviewUrl.value = URL.createObjectURL(data)
  } catch (error) {
    const detail = error?.response?.data?.detail
    if (detail?.code === 'archive_submission_stale_state') {
      closeUploadPreview()
      emit('update:modelValue', false)
      emit('stale')
      toast.add({
        severity: 'warn',
        summary: t('投稿狀態已變更'),
        detail: t('投稿狀態已變更，無法再編輯'),
        life: 4000,
      })
      return
    }
    uploadPreviewError.value = true
    toast.add({
      severity: 'error',
      summary: t('預覽失敗'),
      detail: t('無法預覽目前 PDF'),
      life: 3000,
    })
  } finally {
    uploadPreviewLoading.value = false
  }
}

function handleUploadPreviewError() {
  uploadPreviewError.value = true
}

function closeUploadPreview() {
  showUploadPreview.value = false
  closeUploadPreviewUrl()
  uploadPreviewError.value = false
  previewingCurrentFile.value = false
}

function closeUploadPreviewUrl() {
  if (uploadPreviewUrl.value) {
    URL.revokeObjectURL(uploadPreviewUrl.value)
    uploadPreviewUrl.value = ''
  }
}

const searchProfessor = (event) => {
  const query = event?.query?.toLowerCase() || ''
  const filteredProfessors = uploadFormProfessors.value
    .filter((professor) => professor.name.toLowerCase().includes(query))
    .sort((a, b) => a.name.localeCompare(b.name))

  availableProfessors.value = filteredProfessors
}

const onProfessorSelect = (event) => {
  if (event.value && typeof event.value === 'object') {
    form.value.professor = event.value.name
  }
}

watch(
  () => form.value.category,
  () => {
    if (applyingPrefill) return
    if (form.value.requestNewCategory) return
    form.value.subject = null
    form.value.subjectId = null
    form.value.professor = null
  }
)

watch(
  () => form.value.subject,
  (subject) => {
    form.value.subjectId = subject && typeof subject === 'object' ? subject.code : null
  }
)

watch(
  () => effectiveSubject.value,
  (newSubject) => {
    if (applyingPrefill) return
    form.value.professor = null
    if (newSubject && !form.value.requestNewCourse) {
      fetchProfessorsForSubject(form.value.subjectId)
    } else {
      uploadFormProfessors.value = []
    }
  }
)

watch(
  () => form.value.requestNewCategory,
  (enabled) => {
    if (applyingPrefill) return
    if (enabled) {
      form.value.requestNewCourse = true
      form.value.category = null
      form.value.subject = null
      form.value.subjectId = null
    } else {
      form.value.requestedCategoryKey = ''
      form.value.requestedCategoryName = ''
      form.value.requestedCategoryNameEn = ''
      form.value.requestedCategoryLabel = ''
      form.value.requestedCategoryLabelEn = ''
    }
  }
)

watch(
  () => form.value.requestNewCourse,
  (enabled) => {
    if (applyingPrefill) return
    if (!enabled && form.value.requestNewCategory) {
      form.value.requestNewCourse = true
      return
    }
    form.value.subject = null
    form.value.subjectId = null
    form.value.requestedCourseName = ''
    form.value.requestedCourseNameEn = ''
    form.value.professor = null
  }
)

watch(
  () => form.value.type,
  (type) => {
    if (applyingPrefill) return
    form.value.examNumber = null
    form.value.otherName = ''
    if (type === 'final') {
      form.value.filename = 'final'
    } else {
      form.value.filename = ''
    }
    validateFilename()
  }
)

watch(generatedFilename, (filename) => {
  form.value.filename = filename
  validateFilename()
})

watch(
  () => props.modelValue,
  (newValue, oldValue) => {
    if (newValue === true && props.prefill) {
      applyPrefill()
    } else if (oldValue === true && newValue === false) {
      resetForm()
    }
  }
)

function applyPrefill() {
  applyingPrefill = true
  const value = props.prefill || {}
  form.value.requestNewCourse = Boolean(value.requested_course_name)
  form.value.requestNewCategory = Boolean(value.requested_category_key)
  form.value.requestedCourseName = value.requested_course_name || ''
  form.value.requestedCourseNameEn = value.requested_course_name_en || ''
  form.value.requestedCategoryKey = value.requested_category_key || ''
  form.value.requestedCategoryName = value.requested_category_name || ''
  form.value.requestedCategoryNameEn = value.requested_category_name_en || ''
  form.value.requestedCategoryLabel = value.requested_category_label || ''
  form.value.requestedCategoryLabelEn = value.requested_category_label_en || ''
  form.value.category = form.value.requestNewCategory ? null : value.category || null
  const course = (props.coursesList[form.value.category] || []).find(
    (item) => item.id === value.course_id
  )
  form.value.subject = form.value.requestNewCourse
    ? null
    : course
      ? { name: localizedCourseName(course), canonicalName: course.name, code: course.id }
      : value.subject || null
  form.value.subjectId = form.value.requestNewCourse ? null : course?.id || value.course_id || null
  form.value.professor = value.professor || null
  form.value.academicYear = value.academic_year || null
  form.value.type = value.archive_type || null
  form.value.hasAnswers = Boolean(value.has_answers ?? value.hasAnswers)
  const match = /^(midterm|quiz)(\d+)$/.exec(value.name || '')
  form.value.examNumber = match ? Number(match[2]) : null
  form.value.otherName = value.archive_type === 'other' ? value.name || '' : ''
  nextTick(() => {
    applyingPrefill = false
    validateFilename()
  })
}

function resetForm() {
  form.value = {
    category: null,
    subject: null,
    subjectId: null,
    requestNewCourse: false,
    requestedCourseName: '',
    requestedCourseNameEn: '',
    requestNewCategory: false,
    requestedCategoryKey: '',
    requestedCategoryName: '',
    requestedCategoryNameEn: '',
    requestedCategoryLabel: '',
    requestedCategoryLabelEn: '',
    professor: null,
    filename: '',
    examNumber: null,
    otherName: '',
    type: null,
    hasAnswers: false,
    academicYear: null,
    file: null,
    wishTitle: '',
  }
  fileValidationError.value = ''
  uploadStep.value = '1'
  isFilenameValid.value = false
  availableProfessors.value = []
  uploadFormProfessors.value = []

  fileUpload.value?.clear?.()

  closeUploadPreview()
}

onBeforeUnmount(closeUploadPreview)
</script>

<style scoped>
.flex-wrap {
  flex-wrap: wrap;
}

.ellipsis {
  display: inline-block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.request-mode-panel,
.new-category-grid {
  border: 1px solid var(--p-content-border-color);
  border-radius: 8px;
  padding: 0.9rem;
  background: color-mix(in srgb, var(--p-content-background) 92%, var(--p-primary-color) 8%);
}

.new-category-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9rem;
}

.new-category-grid > :first-child {
  grid-column: 1 / -1;
}

.current-file-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.9rem;
  border: 1px solid var(--p-content-border-color);
  border-radius: 8px;
  background: var(--p-content-background);
}

@media (max-width: 640px) {
  .new-category-grid {
    grid-template-columns: 1fr;
  }
}

.semester-picker {
  border: 1px solid var(--p-inputtext-border-color);
  border-radius: 8px;
  background: var(--p-inputtext-background);
  overflow: hidden;
}

.semester-picker-value {
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--p-content-border-color);
  color: var(--text-primary);
  font-weight: 600;
}

.semester-grid {
  display: grid;
  gap: 0.45rem;
  max-height: 15.5rem;
  padding: 0.75rem;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.semester-row {
  display: grid;
  grid-template-columns: 4.5rem repeat(2, minmax(0, 1fr));
  align-items: center;
  gap: 0.5rem;
}

.semester-year {
  color: var(--text-secondary);
  font-weight: 700;
}

.semester-option {
  min-height: 2.65rem;
  border: 1px solid rgba(167, 176, 190, 0.34);
  border-radius: 7px;
  background: rgba(21, 38, 33, 0.88);
  color: rgba(242, 248, 244, 0.96);
  font: inherit;
  font-weight: 650;
  cursor: pointer;
  transition:
    background 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease;
}

.semester-option:hover {
  border-color: #35d39a;
  background: rgba(30, 58, 49, 0.94);
}

.semester-option.selected {
  border-color: #42dca4;
  background: #36d399;
  color: #04130e;
  box-shadow: 0 0 0 1px rgba(54, 211, 153, 0.26);
}

.semester-option:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

@media (max-width: 520px) {
  .semester-row {
    grid-template-columns: 1fr;
  }
}
</style>
