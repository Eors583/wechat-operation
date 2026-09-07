import { describe, expect, it } from 'vitest'
import { renderSafeMarkdown } from './safeMarkdown'

describe('renderSafeMarkdown', () => {
  it('renders common assistant markdown without exposing raw markers', () => {
    expect(renderSafeMarkdown('你好，**重点** 和 `代码`')).toBe(
      '<p>你好，<strong>重点</strong> 和 <code>代码</code></p>',
    )
  })

  it('escapes html before rendering markdown', () => {
    expect(renderSafeMarkdown('<script>alert(1)</script> **安全**')).toBe(
      '<p>&lt;script&gt;alert(1)&lt;/script&gt; <strong>安全</strong></p>',
    )
  })

  it('renders lists and fenced code blocks', () => {
    expect(renderSafeMarkdown('- A\n- **B**\n\n```json\n{"ok": true}\n```')).toBe(
      '<ul><li>A</li><li><strong>B</strong></li></ul><pre><code>{&quot;ok&quot;: true}</code></pre>',
    )
  })

  it('renders assistant headings and GFM tables instead of showing markdown markers', () => {
    const rendered = renderSafeMarkdown(
      '### 后续提纲\n\n| 章节 | 核心任务 | 展开要点 |\n|:---|:---:|---:|\n| **第一段** | 锚定事实 | 南京大学 |\n| 第二段 | `A|B` | <script> |',
    )

    expect(rendered).toContain('<h3>后续提纲</h3>')
    expect(rendered).toContain(
      '<div class="markdown-table-wrap" role="region" aria-label="表格" tabindex="0">',
    )
    expect(rendered).toContain('<th scope="col">章节</th>')
    expect(rendered).toContain('class="markdown-table__cell--center"')
    expect(rendered).toContain('<td><strong>第一段</strong></td>')
    expect(rendered).toContain('<code>A|B</code>')
    expect(rendered).toContain('&lt;script&gt;')
    expect(rendered).not.toContain('###')
    expect(rendered).not.toContain('|:---|')
  })

  it('renders blockquotes, ordered lists and separators', () => {
    expect(renderSafeMarkdown('> 引用一\n> 引用二\n\n1. 第一项\n2) 第二项\n\n---')).toBe(
      '<blockquote>引用一<br>引用二</blockquote><ol><li>第一项</li><li>第二项</li></ol><hr>',
    )
  })
})
