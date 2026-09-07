<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuasar } from 'quasar'
import { useQuery } from '@tanstack/vue-query'
import type { Message } from '@/api/types'
import { api } from '@/api/client'
import { messageArticle } from '@/utils/messageArticle'
import { articleCardPreview } from '@/utils/articleCardPreview'
import AppButton from '@/components/base/AppButton.vue'
import { defaultArticleTemplate } from '@/utils/articleDownload'
import { platform } from '@/platform'

const props = defineProps<{ message: Message }>()
const downloading = ref(false)
const downloadMenu = ref(false)
const $q = useQuasar()
const download = async (format: 'md' | 'pdf' | 'docx') => {
  if (downloading.value) return
  downloadMenu.value = false
  downloading.value = true
  try {
    const { article } = await messageArticle(api, props.message)
    const templates = await api.listTemplatesPage(undefined, undefined, 100)
    const template = defaultArticleTemplate(article, templates.items)
    const rendered = await api.prepareArticleRender(
      article.id,
      article.accountId ?? template?.accountId ?? null,
      template?.id ?? null,
      null,
      article.versionNo,
    )
    const data = await api.downloadArticleRender(rendered.renderId, format)
    const title = articleCardPreview(article)
      .title.replace(/[\\/:*?"<>|]/g, '_')
      .slice(0, 100)
    await platform.downloadFile(
      new File([data], `${title}-第${article.versionNo}版.${format}`, { type: data.type }),
    )
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: error instanceof Error ? error.message : '下载失败，请重试。',
    })
  } finally {
    downloading.value = false
  }
}
defineEmits<{ preview: [] }>()
const query = useQuery({
  queryKey: computed(() => [
    'message-article',
    props.message.articleId,
    props.message.articleVersionNo,
  ]),
  queryFn: () => messageArticle(api, props.message),
})
const preview = computed(() =>
  query.data.value ? articleCardPreview(query.data.value.article) : null,
)
</script>

<template>
  <q-card flat bordered class="message-article-card">
    <q-card-section>
      <header>
        <q-icon name="article" color="primary" />
        <strong>{{ preview?.title || '本次生成的文章' }}</strong>
        <AppButton label="点击预览" variant="outline" @click="$emit('preview')" />
        <AppButton
          label="下载"
          icon="download"
          variant="outline"
          :loading="downloading"
          aria-haspopup="menu"
          :aria-expanded="downloadMenu"
          @mouseenter="!downloading && (downloadMenu = true)"
          @click="downloadMenu = !downloadMenu"
        >
          <q-menu v-model="downloadMenu" no-parent-event anchor="bottom right" self="top right">
            <q-list role="menu" aria-label="文章下载格式">
              <q-item
                v-for="option in [
                  { format: 'md', label: 'Markdown (.md)' },
                  { format: 'pdf', label: 'PDF (.pdf)' },
                  { format: 'docx', label: 'Word (.docx)' },
                ] as const"
                :key="option.format"
                clickable
                role="menuitem"
                :disable="downloading"
                @click="download(option.format)"
              >
                <q-item-section>{{ option.label }}</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </AppButton>
      </header>
      <p v-if="preview?.excerpt" class="message-article-card__excerpt">{{ preview.excerpt }}</p>
      <p v-else-if="query.isPending.value" role="status">正在加载文章节选…</p>
      <p v-else-if="query.isError.value" role="status">
        节选加载失败，未替换为其他版本。
        <AppButton label="重试" variant="outline" @click="query.refetch()" />
      </p>
      <small
        >仅展示部分内容，点击预览查看全文<span v-if="message.articleVersionNo">
          · 第 {{ message.articleVersionNo }} 版</span
        ></small
      >
    </q-card-section>
  </q-card>
</template>

<style scoped lang="scss">
.message-article-card {
  min-width: 0;
  max-width: 100%;
  margin-top: 1rem;
  color: var(--app-text-primary);
  background: var(--app-bg-surface);
  border-color: var(--app-border-default);
  overflow-wrap: anywhere;

  header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 0;
  }
  strong {
    flex: 1;
    min-width: 0;
  }
  small {
    color: var(--app-text-secondary);
  }
  &__excerpt {
    display: -webkit-box;
    margin: 1rem 0;
    overflow: hidden;
    line-height: 1.8;
    white-space: pre-line;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 5;
  }
  @media (width <= 599px) {
    header {
      flex-wrap: wrap;
    }
    header .app-button {
      width: 100%;
    }
  }
}
</style>
