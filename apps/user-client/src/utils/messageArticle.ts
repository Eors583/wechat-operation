import type { Article, Message, UserApi } from '@/api/types'

export async function messageArticle(
  api: Pick<UserApi, 'getArticle' | 'getArticleVersionsPage'>,
  message: Pick<Message, 'articleId' | 'articleVersionNo'>,
): Promise<{ article: Article; historical: boolean }> {
  if (!message.articleId) throw new Error('这条消息没有关联文章。')
  const current = await api.getArticle(message.articleId)
  if (message.articleVersionNo === current.versionNo) return { article: current, historical: false }
  if (!message.articleVersionNo) throw new Error('这条旧消息缺少文章版本号，请从文章库查看。')
  let cursor: string | undefined
  do {
    const page = await api.getArticleVersionsPage(message.articleId, cursor, 100)
    const version = page.items.find((item) => item.versionNo === message.articleVersionNo)
    if (version)
      return {
        article: {
          ...current,
          versionNo: version.versionNo,
          contentJson: version.contentJson,
          contentHtml: version.contentHtml,
          title: `历史文章 · 第 ${version.versionNo} 版`,
        },
        historical: true,
      }
    cursor = page.nextCursor
  } while (cursor)
  throw new Error('该消息关联的历史版本不存在，未替换为其他版本。')
}
