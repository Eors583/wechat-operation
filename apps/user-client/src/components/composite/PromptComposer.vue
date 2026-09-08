<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from '@/api/client'
import type { Attachment, LibraryItem, ModelOption, Skill } from '@/api/types'
import { platform } from '@/platform'
import { linkAttachmentLabel, safeHttpUrl } from '@/utils/safeUrl'
import { parseWechatArticleCapture, WECHAT_CAPTURE_BOOKMARKLET } from '@/utils/wechatCapture'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'

const props = withDefaults(
  defineProps<{
    disabled?: boolean
    sendDisabled?: boolean
    loading?: boolean
    skills: Skill[]
    skillsHasMore?: boolean
    skillsLoadingMore?: boolean
    selectedSkillId?: string | null
    selectedModelId?: string | null
    models?: ModelOption[]
    modelsLoading?: boolean
    usePreferences?: boolean
    placeholder?: string
    allowedExtensions?: string[]
    maxFileMb?: number
    linkFetchEnabled?: boolean
    skillsEnabled?: boolean
    visualUnderstandingEnabled?: boolean
  }>(),
  {
    disabled: false,
    sendDisabled: false,
    loading: false,
    skillsHasMore: false,
    skillsLoadingMore: false,
    selectedSkillId: null,
    selectedModelId: null,
    models: () => [],
    modelsLoading: false,
    usePreferences: true,
    placeholder: '告诉内容助手你想写什么……',
    allowedExtensions: () => [
      'pdf',
      'docx',
      'pptx',
      'xlsx',
      'csv',
      'txt',
      'md',
      'html',
      'png',
      'jpg',
      'jpeg',
      'mp3',
      'm4a',
      'mp4',
    ],
    maxFileMb: 200,
    linkFetchEnabled: true,
    skillsEnabled: true,
    visualUnderstandingEnabled: true,
  },
)

const emit = defineEmits<{
  send: [payload: { text: string; attachments: Attachment[]; draftId: string }]
  stop: []
  'load-more-skills': []
  'update:selectedSkillId': [value: string | null]
  'update:selectedModelId': [value: string | null]
  'update:usePreferences': [value: boolean]
}>()
const $q = useQuasar()

const text = ref('')
const attachments = ref<Attachment[]>([])
const linkEditorOpen = ref(false)
const wechatCaptureDialog = ref(false)
const link = ref('')
const normalizedLink = computed(() => safeHttpUrl(link.value, { rejectSensitiveQuery: true }))
const skillMenuOpen = ref(false)
const libraryDialog = ref(false)
const libraryLoading = ref(false)
const libraryItems = ref<LibraryItem[]>([])
const selectedLibraryIds = ref<string[]>([])
const libraryNextCursor = ref<string>()
const submittedDrafts = new Map<string, { text: string; attachments: Attachment[] }>()
const maxAttachments = 20
const dragDepth = ref(0)
const modelOptions = computed(() => [
  {
    label: '自动（稳定优先）',
    value: null,
    description: '主模型异常时自动切换备用模型',
  },
  ...props.models.map((model) => ({
    label: model.name,
    value: model.id,
    description: `${[model.providerName, model.modelId].filter(Boolean).join(' · ')} · 优先使用，失败自动切换`,
  })),
])

const availableAttachmentSlots = () => Math.max(0, maxAttachments - attachments.value.length)
const notifyAttachmentLimit = () =>
  $q.notify({ type: 'warning', message: `每条消息最多添加 ${maxAttachments} 个文件、资料或链接。` })

const addFiles = (files: File[]) => {
  if (props.disabled) return
  if (!availableAttachmentSlots()) return notifyAttachmentLimit()
  const allowed = new Set(
    props.allowedExtensions.map((item) => item.toLowerCase().replace(/^\./, '')),
  )
  const maxBytes = props.maxFileMb * 1024 * 1024
  const accepted = files.filter((file) => {
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    return (
      allowed.has(extension) &&
      file.size <= maxBytes &&
      (props.visualUnderstandingEnabled || !file.type.startsWith('image/'))
    )
  })
  if (accepted.length !== files.length)
    $q.notify({
      type: 'warning',
      message: `部分文件不符合当前格式、图片能力或 ${props.maxFileMb}MB 大小限制，已跳过。`,
    })
  if (accepted.length > availableAttachmentSlots()) notifyAttachmentLimit()
  attachments.value.push(
    ...accepted.slice(0, availableAttachmentSlots()).map((file) => ({
      id: `attachment_${crypto.randomUUID()}`,
      name: file.name,
      kind: file.type.startsWith('image/') ? ('image' as const) : ('file' as const),
      size: file.size,
      mimeType: file.type || 'application/octet-stream',
      status: 'reading' as const,
      saveToLibrary: true,
      sourceFile: file,
    })),
  )
}

const pickFiles = async () => {
  if (props.disabled) return
  if (!availableAttachmentSlots()) return notifyAttachmentLimit()
  addFiles(
    await platform.pickFiles(
      props.allowedExtensions.map((item) => `.${item.replace(/^\./, '')}`).join(','),
    ),
  )
}

const isFileDrag = (event: DragEvent) =>
  Array.from(event.dataTransfer?.types ?? []).includes('Files')
const onDragEnter = (event: DragEvent) => {
  if (!isFileDrag(event)) return
  event.preventDefault()
  if (!props.disabled) dragDepth.value++
}
const onDragOver = (event: DragEvent) => {
  if (!isFileDrag(event)) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = props.disabled ? 'none' : 'copy'
}
const onDragLeave = () => {
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}
const onDrop = (event: DragEvent) => {
  dragDepth.value = 0
  if (!isFileDrag(event)) return
  event.preventDefault()
  if (props.disabled || !event.dataTransfer) return
  const items = Array.from(event.dataTransfer.items ?? [])
  if (items.some((item) => item.webkitGetAsEntry?.()?.isDirectory)) {
    $q.notify({ type: 'warning', message: '暂不支持拖入文件夹，请选择文件夹中的文件。' })
  }
  const files = items.length
    ? items
        .filter((item) => item.kind === 'file' && !item.webkitGetAsEntry?.()?.isDirectory)
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null)
    : Array.from(event.dataTransfer.files)
  addFiles(files)
}

const addLink = () => {
  if (!availableAttachmentSlots()) return notifyAttachmentLimit()
  const value = normalizedLink.value
  if (!value) {
    $q.notify({
      type: 'warning',
      message:
        '请输入有效网址，可直接输入 baidu.com、www.example.com 或 https:// 开头链接；不要包含账号密码、密钥参数或片段。',
    })
    return
  }
  attachments.value.push({
    id: `attachment_${crypto.randomUUID()}`,
    name: linkAttachmentLabel(value),
    kind: 'link',
    url: value,
    status: 'ready',
    saveToLibrary: false,
  })
  link.value = ''
  linkEditorOpen.value = false
}

const cancelLink = () => {
  link.value = ''
  linkEditorOpen.value = false
}

const captureFilename = (title: string) =>
  `${
    title
      .replace(/[\\/:*?"<>|]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 80) || '微信公众号文章'
  }.txt`

const onPaste = (event: ClipboardEvent) => {
  const capture = parseWechatArticleCapture(event.clipboardData?.getData('text/plain') ?? '')
  if (!capture) return
  event.preventDefault()
  if (props.disabled) return
  if (!availableAttachmentSlots()) return notifyAttachmentLimit()
  addFiles([
    new File([capture.text], captureFilename(capture.title), {
      type: 'text/plain',
      lastModified: Date.now(),
    }),
  ])
  if (!text.value.trim()) text.value = `请依据《${capture.title}》的正文进行改写。`
  $q.notify({ type: 'positive', message: '公众号正文已在本地采集，并添加为待解析附件。' })
}

const copyCaptureBookmarklet = async () => {
  try {
    await navigator.clipboard.writeText(WECHAT_CAPTURE_BOOKMARKLET)
    $q.notify({ type: 'positive', message: '采集书签代码已复制，请新建书签并粘贴到网址栏。' })
  } catch {
    $q.notify({ type: 'warning', message: '浏览器未允许复制，请将绿色按钮拖到书签栏完成安装。' })
  }
}

const openLibrary = async () => {
  libraryDialog.value = true
  libraryLoading.value = true
  selectedLibraryIds.value = attachments.value
    .map((item) => item.documentId)
    .filter((id): id is string => Boolean(id))
  try {
    const page = await api.listLibraryItemsPage({ type: 'reference' })
    libraryItems.value = page.items
    libraryNextCursor.value = page.nextCursor
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '资料库没有加载完成。',
    })
  } finally {
    libraryLoading.value = false
  }
}

const loadMoreLibrary = async () => {
  if (!libraryNextCursor.value || libraryLoading.value) return
  libraryLoading.value = true
  try {
    const page = await api.listLibraryItemsPage({ type: 'reference' }, libraryNextCursor.value)
    libraryItems.value.push(...page.items)
    libraryNextCursor.value = page.nextCursor
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '更多资料没有加载完成。',
    })
  } finally {
    libraryLoading.value = false
  }
}

const addLibraryItems = () => {
  const existing = new Set(attachments.value.map((item) => item.documentId))
  const selected = libraryItems.value.filter(
    (item) => selectedLibraryIds.value.includes(item.sourceId) && !existing.has(item.sourceId),
  )
  if (selected.length > availableAttachmentSlots()) notifyAttachmentLimit()
  attachments.value.push(
    ...selected.slice(0, availableAttachmentSlots()).map((item) => ({
      id: `library_${item.id}`,
      name: item.title,
      kind: 'file' as const,
      status: 'ready' as const,
      saveToLibrary: false,
      documentId: item.sourceId,
    })),
  )
  libraryDialog.value = false
}

const submit = () => {
  const value = text.value.trim()
  if (!value || props.disabled || props.sendDisabled || props.loading) return
  const draftId = crypto.randomUUID()
  const draftAttachments = [...attachments.value]
  submittedDrafts.set(draftId, {
    text: text.value,
    attachments: draftAttachments,
  })
  emit('send', { text: value, attachments: draftAttachments, draftId })
  text.value = ''
  attachments.value = []
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

defineExpose({
  setText: (value: string) => {
    text.value = value
  },
  acknowledgeDraft: (draftId: string) => {
    submittedDrafts.delete(draftId)
  },
  restoreDraft: (draftId: string) => {
    const submitted = submittedDrafts.get(draftId)
    if (!submitted) return
    if (!text.value && !attachments.value.length) {
      text.value = submitted.text
      attachments.value = submitted.attachments
    }
    submittedDrafts.delete(draftId)
  },
})
</script>

<template>
  <section
    class="prompt-composer surface-card"
    :class="{ 'prompt-composer--dragging': dragDepth > 0 && !disabled }"
    aria-label="创作输入"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div v-if="dragDepth > 0 && !disabled" class="prompt-composer__drop-hint" role="status">
      松开添加附件 · 点击发送后上传并解析
    </div>
    <div v-if="attachments.length" class="prompt-composer__attachments" aria-label="待发送附件">
      <q-chip
        v-for="item in attachments"
        :key="item.id"
        removable
        outline
        color="primary"
        :icon="item.kind === 'link' ? 'link' : item.kind === 'image' ? 'image' : 'attach_file'"
        @remove="attachments = attachments.filter((entry) => entry.id !== item.id)"
      >
        <span class="prompt-composer__chip-label">{{ item.name }}</span>
        <q-tooltip>{{ item.name }}</q-tooltip>
      </q-chip>
    </div>
    <q-input
      v-model="text"
      class="prompt-composer__input"
      type="textarea"
      autogrow
      borderless
      :placeholder="placeholder"
      :disable="disabled"
      maxlength="5000"
      aria-label="给内容助手发送消息"
      @keydown="onKeydown"
      @paste="onPaste"
    />
    <div v-if="linkEditorOpen" class="prompt-composer__link-editor">
      <q-input
        v-model="link"
        dense
        outlined
        autofocus
        placeholder="请输入参考文章链接"
        maxlength="2000"
        aria-label="参考文章链接"
        @keyup.enter="addLink"
      >
        <template #prepend><q-icon name="link" /></template>
      </q-input>
      <q-btn flat round icon="close" aria-label="取消添加链接" @click="cancelLink"
        ><q-tooltip>取消</q-tooltip></q-btn
      >
      <q-btn
        round
        unelevated
        color="primary"
        icon="check"
        aria-label="确认添加链接"
        :disable="!normalizedLink"
        @click="addLink"
        ><q-tooltip>添加链接</q-tooltip></q-btn
      >
    </div>
    <div class="prompt-composer__toolbar">
      <div class="prompt-composer__tools">
        <q-btn
          class="prompt-composer__plus"
          flat
          round
          icon="add"
          aria-label="更多创作选项"
          @mouseenter="skillMenuOpen = true"
          @click="skillMenuOpen = true"
        >
          <q-tooltip>更多创作选项</q-tooltip>
          <q-menu
            v-model="skillMenuOpen"
            anchor="top left"
            self="bottom left"
            :offset="[0, 8]"
            @mouseenter="skillMenuOpen = true"
            @mouseleave="skillMenuOpen = false"
          >
            <q-list class="skill-menu">
              <q-item-label v-if="skillsEnabled" header>选择技能</q-item-label>
              <q-item
                v-if="skillsEnabled"
                clickable
                v-close-popup
                @click="emit('update:selectedSkillId', null)"
              >
                <q-item-section avatar
                  ><q-icon name="auto_awesome" color="primary"
                /></q-item-section>
                <q-item-section
                  ><q-item-label>自动选择</q-item-label
                  ><q-item-label caption>根据需求匹配合适技能</q-item-label></q-item-section
                >
              </q-item>
              <q-item
                v-for="skill in skillsEnabled ? skills.filter((item) => item.enabled) : []"
                :key="skill.id"
                clickable
                v-close-popup
                @click="emit('update:selectedSkillId', skill.id)"
              >
                <q-item-section avatar><q-icon name="extension" /></q-item-section>
                <q-item-section
                  ><q-item-label>{{ skill.name }}</q-item-label
                  ><q-item-label caption>{{ skill.description }}</q-item-label></q-item-section
                >
              </q-item>
              <q-item
                v-if="skillsEnabled && skillsHasMore"
                clickable
                :disable="skillsLoadingMore"
                @click.stop="emit('load-more-skills')"
              >
                <q-item-section avatar
                  ><q-spinner v-if="skillsLoadingMore" color="primary" size="20px" /><q-icon
                    v-else
                    name="expand_more"
                    color="primary"
                /></q-item-section>
                <q-item-section
                  ><q-item-label class="text-primary">加载更多技能</q-item-label></q-item-section
                >
              </q-item>
              <q-separator v-if="skillsEnabled" />
              <q-item
                clickable
                :disable="attachments.length >= maxAttachments"
                @click="openLibrary"
              >
                <q-item-section avatar><q-icon name="folder_open" /></q-item-section>
                <q-item-section>从资料库选择</q-item-section>
              </q-item>
              <q-item tag="label">
                <q-item-section avatar><q-icon name="history" /></q-item-section>
                <q-item-section
                  ><q-toggle
                    :model-value="usePreferences"
                    dense
                    label="使用历史偏好"
                    @update:model-value="emit('update:usePreferences', $event)"
                /></q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
        <q-btn
          class="prompt-composer__tool-button"
          outline
          no-caps
          icon="attach_file"
          label="上传附件"
          aria-label="上传附件"
          :disable="disabled || attachments.length >= maxAttachments"
          @click="pickFiles"
        />
        <q-btn
          v-if="linkFetchEnabled"
          class="prompt-composer__tool-button"
          outline
          no-caps
          icon="link"
          label="添加参考文章链接"
          aria-label="添加参考文章链接"
          :disable="attachments.length >= maxAttachments"
          @click="linkEditorOpen = true"
        />
        <q-btn
          class="prompt-composer__tool-button"
          outline
          no-caps
          icon="travel_explore"
          label="本地采集公众号"
          aria-label="本地采集公众号正文"
          :disable="disabled || attachments.length >= maxAttachments"
          @click="wechatCaptureDialog = true"
        />
        <span v-if="attachments.length" class="prompt-composer__count"
          >{{ attachments.length }}/{{ maxAttachments }}</span
        >
      </div>
      <div class="prompt-composer__actions">
        <q-select
          class="prompt-composer__model-select"
          dense
          outlined
          emit-value
          map-options
          options-dense
          :model-value="selectedModelId"
          :options="modelOptions"
          :display-value="selectedModelId ? undefined : '自动（稳定优先）'"
          :loading="modelsLoading"
          :disable="modelsLoading || !models.length"
          placeholder="暂无可用模型"
          aria-label="选择对话模型"
          @update:model-value="emit('update:selectedModelId', $event)"
        >
          <template #prepend><q-icon name="smart_toy" /></template>
          <template #option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section class="prompt-composer__model-option">
                <q-item-label>{{ scope.opt.label }}</q-item-label>
                <q-item-label caption>{{ scope.opt.description }}</q-item-label>
              </q-item-section>
            </q-item>
          </template>
          <template #no-option>
            <q-item>
              <q-item-section class="text-grey">暂无可用模型</q-item-section>
            </q-item>
          </template>
        </q-select>
        <q-btn flat round icon="keyboard_voice" aria-label="语音输入"
          ><q-tooltip>语音输入</q-tooltip></q-btn
        >
        <AppButton
          v-if="loading"
          variant="outline"
          icon="stop_circle"
          label="停止"
          @click="emit('stop')"
        />
        <q-btn
          v-else
          class="prompt-composer__send"
          round
          unelevated
          color="primary"
          icon="send"
          aria-label="发送消息"
          :disable="!text.trim() || disabled || sendDisabled"
          @click="submit"
        >
          <q-tooltip v-if="sendDisabled">请先选择一个可用模型</q-tooltip>
        </q-btn>
      </div>
    </div>
  </section>

  <AppDialog v-model="libraryDialog" title="从资料库选择" width="620px">
    <div class="library-dialog">
      <p>选择已经解析完成的资料。发送时只引用资料编号，不会重复上传或复制文件。</p>
      <div v-if="libraryLoading" class="library-dialog__loading">
        <q-spinner color="primary" size="32px" /><span>正在加载资料库…</span>
      </div>
      <q-list v-else-if="libraryItems.length" bordered separator>
        <q-item
          v-for="item in libraryItems"
          :key="item.id"
          tag="label"
          :disable="item.status !== 'ready'"
        >
          <q-item-section avatar
            ><q-checkbox
              v-model="selectedLibraryIds"
              :val="item.sourceId"
              :disable="item.status !== 'ready'"
          /></q-item-section>
          <q-item-section
            ><q-item-label>{{ item.title }}</q-item-label
            ><q-item-label caption>{{
              item.summary || (item.status === 'ready' ? '已解析' : '尚未解析完成')
            }}</q-item-label></q-item-section
          >
        </q-item>
      </q-list>
      <q-banner v-else rounded
        >资料库中还没有可选择的资料。可以先上传文件，成功解析后会自动进入资料库。</q-banner
      >
      <AppButton
        v-if="libraryNextCursor"
        variant="outline"
        label="加载更多资料"
        :loading="libraryLoading"
        @click="loadMoreLibrary"
      />
    </div>
    <template #actions>
      <AppButton variant="ghost" label="取消" @click="libraryDialog = false" />
      <AppButton
        label="添加所选资料"
        :disabled="!selectedLibraryIds.length || libraryLoading"
        @click="addLibraryItems"
      />
    </template>
  </AppDialog>

  <AppDialog v-model="wechatCaptureDialog" title="本地采集公众号正文" width="620px">
    <div class="capture-dialog">
      <q-banner rounded class="capture-dialog__notice">
        微信会拦截服务器读取部分文章。采集书签只在当前浏览器读取你已经打开的正文，并复制到本机剪贴板。
      </q-banner>
      <ol>
        <li>把下面的绿色按钮拖到浏览器书签栏，只需安装一次。</li>
        <li>在浏览器中正常打开需要改写的微信公众号文章。</li>
        <li>点击书签栏里的“采集公众号正文”。</li>
        <li>返回本页面，在创作输入框中粘贴；正文会自动变成文本附件。</li>
      </ol>
      <a
        class="capture-dialog__bookmarklet"
        :href="WECHAT_CAPTURE_BOOKMARKLET"
        draggable="true"
        @click.prevent
      >
        <q-icon name="content_copy" />
        采集公众号正文
      </a>
      <p class="capture-dialog__privacy">
        采集过程不会读取聊天记录、账号密码或其他页面；正文只有在你返回平台粘贴并发送后才会上传。
      </p>
    </div>
    <template #actions>
      <AppButton variant="ghost" label="复制安装代码" @click="copyCaptureBookmarklet" />
      <AppButton label="我知道了" @click="wechatCaptureDialog = false" />
    </template>
  </AppDialog>
</template>

<style scoped lang="scss">
.prompt-composer {
  width: 100%;
  min-width: 0;
  padding: 16px 16px 14px;
  border-radius: 18px;
  box-shadow: 0 10px 26px rgba(18, 43, 31, 0.08);

  &--dragging {
    outline: 2px dashed var(--app-action-primary);
    outline-offset: -2px;
  }

  &__drop-hint {
    min-width: 0;
    color: var(--app-action-primary);
    font-size: 13px;
    overflow-wrap: anywhere;
    pointer-events: none;
  }

  &__attachments {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    min-width: 0;
    max-height: 160px;
    padding-bottom: 6px;
    overflow-y: auto;
  }

  &__chip-label {
    display: block;
    max-width: min(300px, 52vw);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__attachments :deep(.q-chip) {
    max-width: 100%;
    height: auto;
  }

  &__attachments :deep(.q-chip__content) {
    flex-wrap: wrap;
    gap: 4px;
    min-width: 0;
  }

  &__input {
    width: 100%;
    min-width: 0;

    :deep(textarea.q-field__native) {
      min-height: 78px;
      max-height: min(32vh, 220px);
      padding: 6px 8px 12px;
      color: var(--app-text-primary);
      overflow-y: auto !important;
      overflow-wrap: anywhere;
      line-height: 1.6;
    }
  }

  &__toolbar,
  &__tools,
  &__actions,
  &__link-editor {
    display: flex;
    align-items: center;
    min-width: 0;
  }

  &__toolbar {
    justify-content: space-between;
    gap: 12px;
  }

  &__tools {
    flex: 1 1 auto;
    flex-wrap: wrap;
    gap: 8px;
  }

  &__actions {
    flex: 0 0 auto;
    gap: 8px;
  }

  &__model-select {
    width: 164px;
    min-width: 0;

    :deep(.q-field__control) {
      min-height: 36px;
      border-radius: 10px;
    }

    :deep(.q-field__native),
    :deep(.q-field__input) {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  &__model-option {
    min-width: 0;

    :deep(.q-item__label) {
      white-space: normal;
      overflow-wrap: anywhere;
    }
  }

  &__link-editor {
    gap: 8px;
    padding: 8px 0 12px;

    .q-field {
      flex: 1 1 auto;
    }

    .q-btn {
      flex: 0 0 auto;
    }
  }

  &__plus {
    width: 40px;
    height: 40px;
    color: var(--app-text-secondary);
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 50%;
    box-shadow: var(--app-shadow-sm);
  }

  &__tool-button {
    min-height: 36px;
    padding-inline: 12px;
    color: var(--app-text-primary);
    background: var(--app-bg-surface);
    border-radius: 10px;

    &::before {
      border-color: var(--app-border-default);
    }
  }

  &__send {
    width: 40px;
    height: 40px;
    background: color-mix(in srgb, var(--app-action-primary) 68%, #fff);
  }

  &__count {
    margin-inline: 4px;
    color: var(--app-text-secondary);
    font-size: 12px;
  }
}

.skill-menu {
  width: min(360px, calc(100vw - 24px));
  max-height: 360px;
  overflow-y: auto;
}

.library-dialog {
  display: grid;
  gap: 14px;
  min-width: 0;
  max-height: min(62vh, 560px);
  padding: 20px;
  overflow-y: auto;

  p {
    margin: 0;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;
  }
  .q-list {
    min-width: 0;
    border-color: var(--app-border-default);
    border-radius: 10px;
  }
  :deep(.q-item__label) {
    white-space: normal;
    overflow-wrap: anywhere;
  }

  &__loading {
    display: grid;
    place-items: center;
    gap: 10px;
    min-height: 180px;
    color: var(--app-text-secondary);
  }
}

.capture-dialog {
  display: grid;
  gap: 16px;
  min-width: 0;
  max-height: min(68vh, 600px);
  padding: 20px;
  overflow-y: auto;

  &__notice,
  &__privacy,
  li {
    min-width: 0;
    overflow-wrap: anywhere;
  }

  ol {
    display: grid;
    gap: 8px;
    margin: 0;
    padding-left: 24px;
  }

  &__bookmarklet {
    display: inline-flex;
    align-items: center;
    justify-self: start;
    gap: 8px;
    max-width: 100%;
    padding: 10px 16px;
    color: var(--app-action-primary-text);
    background: var(--app-action-primary);
    border-radius: 10px;
    text-decoration: none;
    overflow-wrap: anywhere;
    cursor: grab;
  }

  &__privacy {
    margin: 0;
    color: var(--app-text-secondary);
  }
}

@media (max-width: 599px) {
  .prompt-composer {
    border-radius: 14px;

    &__input :deep(textarea.q-field__native) {
      min-height: 92px;
    }

    &__toolbar {
      flex-wrap: wrap;
      align-items: flex-end;
    }

    &__tools {
      flex-basis: 100%;
    }

    &__actions {
      justify-content: flex-end;
      width: 100%;
    }

    &__link-editor {
      flex-wrap: wrap;
    }

    &__tool-button {
      padding-inline: 10px;
    }

    &__model-select {
      width: min(148px, 42vw);
    }
  }
}
</style>
