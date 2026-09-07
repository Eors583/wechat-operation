import { describe, expect, it } from 'vitest'
import { separateArticleTitle } from './articleTitle'

describe('article title separation', () => {
  it('moves only the first H1 into metadata without changing the original document', () => {
    const heading = {
      type: 'heading',
      attrs: { level: 1 },
      content: [
        { type: 'text', text: '真正的', marks: [{ type: 'bold' }] },
        { type: 'text', text: '文章标题' },
      ],
    }
    const paragraph = { type: 'paragraph', content: [{ type: 'text', text: '正文开始。' }] }
    const document = { type: 'doc', content: [heading, paragraph] }
    const result = separateArticleTitle(document, '原来的请求文字')
    expect(result.title).toBe('真正的文章标题')
    expect(result.content.content).toEqual([paragraph])
    expect(document.content).toEqual([heading, paragraph])
    expect(separateArticleTitle(result.content, result.title).separated).toBe(false)
  })

  it.each(['paragraph', 'blockquote'])(
    'does not guess a title from ordinary %s content',
    (type) => {
      const document = {
        type: 'doc',
        content: [{ type, content: [{ type: 'text', text: '普通开头' }] }],
      }
      expect(separateArticleTitle(document, '已有标题')).toEqual({
        title: '已有标题',
        content: document,
        separated: false,
      })
    },
  )

  it('preserves section headings and non-text content', () => {
    for (const heading of [
      { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: '第一节' }] },
      {
        type: 'heading',
        attrs: { level: 1 },
        content: [{ type: 'image', attrs: { src: '/image' } }],
      },
    ]) {
      const document = { type: 'doc', content: [heading] }
      expect(separateArticleTitle(document, '已有标题').content).toBe(document)
    }
  })
})
