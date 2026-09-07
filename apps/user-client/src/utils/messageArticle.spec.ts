import { describe, expect, it, vi } from 'vitest'
import { messageArticle } from './messageArticle'
import type { Article } from '@/api/types'

describe('message article identity', () => {
  const current = { id: 'A', versionNo: 4, title: '最新文章', contentHtml: '损坏 JSON' } as Article
  it('opens the message article and immutable version, not the task current article', async () => {
    const api = {
      getArticle: vi.fn().mockResolvedValue(current),
      getArticleVersionsPage: vi
        .fn()
        .mockResolvedValueOnce({ items: [], nextCursor: 'older' })
        .mockResolvedValueOnce({
          items: [{ versionNo: 2, contentHtml: '<p>旧正文</p>', contentJson: { type: 'doc' } }],
        }),
    }
    const result = await messageArticle(api, { articleId: 'A', articleVersionNo: 2 })
    expect(api.getArticle).toHaveBeenCalledWith('A')
    expect(api.getArticleVersionsPage).toHaveBeenLastCalledWith('A', 'older', 100)
    expect(result.historical).toBe(true)
    expect(result.article.contentHtml).toBe('<p>旧正文</p>')
    expect(result.article.versionNo).toBe(2)
    expect(current.contentHtml).toBe('损坏 JSON')
  })
  it('does not silently substitute latest content if version is missing', async () => {
    const api = {
      getArticle: vi.fn().mockResolvedValue(current),
      getArticleVersionsPage: vi.fn().mockResolvedValue({ items: [] }),
    }
    await expect(messageArticle(api, { articleId: 'A', articleVersionNo: 1 })).rejects.toThrow(
      '未替换',
    )
    await expect(messageArticle(api, { articleId: 'A' })).rejects.toThrow('缺少文章版本号')
  })
  it('allows editing only the current version of the selected article', async () => {
    const api = { getArticle: vi.fn().mockResolvedValue(current), getArticleVersionsPage: vi.fn() }
    expect(await messageArticle(api, { articleId: 'A', articleVersionNo: 4 })).toEqual({
      article: current,
      historical: false,
    })
    expect(api.getArticleVersionsPage).not.toHaveBeenCalled()
  })
})
