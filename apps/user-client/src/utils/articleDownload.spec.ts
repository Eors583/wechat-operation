import { describe, expect, it } from 'vitest'
import { articleDownloadFile } from '@/utils/articleDownload'

describe('formatted article download', () => {
  it('keeps rendered styles and tables, includes title and version', async () => {
    const file = articleDownloadFile(
      '标题',
      2,
      '<p style="color:red">完整正文</p><table><tr><td>数据</td></tr></table>',
    )
    const html = await new Promise<string>((resolve) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.readAsText(file)
    })
    expect(file.name).toBe('标题-第2版.html')
    expect(html).toContain('>标题</h1>')
    expect(html).toContain('style="color:red"')
    expect(html).toContain('<table>')
    expect(html).toContain("default-src 'none'")
  })
  it('rejects empty output and uses the historical heading for filenames', () => {
    expect(() => articleDownloadFile('标题', 1, '')).toThrow('正文为空')
    expect(articleDownloadFile('最新标题', 1, '<h1>历史/标题</h1><p>旧正文</p>').name).toBe(
      '历史_标题-第1版.html',
    )
  })
})
