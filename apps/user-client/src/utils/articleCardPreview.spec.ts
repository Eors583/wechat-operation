import { expect, it } from 'vitest'
import { articleCardPreview } from './articleCardPreview'

it('shows the version title and opening paragraphs, not the title again or the entire article', () => {
  const result = articleCardPreview({
    title: '错误的当前标题',
    contentHtml: '<h1>历史标题</h1><p>第一段 &amp; 引文</p><p>第二段</p><p>第三段</p><p>第四段</p>',
  })
  expect(result).toEqual({ title: '历史标题', excerpt: '第一段 & 引文\n第二段\n第三段' })
})
it('bounds long content and only returns text', () => {
  const result = articleCardPreview({
    title: '标题',
    contentHtml: `<script>secret</script><p>${'长'.repeat(500)}</p>`,
  })
  expect(result.excerpt).toBe('长'.repeat(320) + '…')
  expect(articleCardPreview({ title: '空文章', contentHtml: '' })).toEqual({
    title: '空文章',
    excerpt: '',
  })
})
