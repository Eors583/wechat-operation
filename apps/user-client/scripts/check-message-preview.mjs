/* global document, getComputedStyle */
import { chromium, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()
const doc = (title, body) => ({ type: 'doc', content: [
  { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: title }] },
  { type: 'paragraph', content: [{ type: 'text', text: body }] },
] })
const user = { id: 'test', name: '预览测试', role: '内容运营', points: 100, themePreference: 'system' }
await page.addInitScript((user) => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z' })), user)
const bodies = { A: '文章 A 旧版本正文。' + '长中文文章内容。'.repeat(70), B: '文章 B 独立正文 ' + 'https://example.com/' + 'a'.repeat(300) }
const versions = { A: 4, B: 1 }
await page.route('**/api/v1/**', async route => {
  const path = new URL(route.request().url()).pathname
  if (path.endsWith('/article-renders/render/download')) {
    const format = new URL(route.request().url()).searchParams.get('format')
    await route.fulfill({ contentType: format === 'md' ? 'text/markdown' : format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', body: 'exported-' + format })
    return
  }
  if (path.endsWith('/article-renders')) {
    const input = route.request().postDataJSON()
    expect(input.article_id).toBe('A')
    expect(input.article_version_no).toBe(2)
    expect(input.template_id).toBe('default-template')
    await route.fulfill({ json: { id: 'render', html: '<h1>旧版本标题 A</h1><p style="color:rgb(12, 34, 56)">文章 A 旧版本正文</p><table><tr><td>完整表格</td></tr></table>' } })
    return
  }
  if (route.request().method() !== 'GET') throw new Error('Unexpected write: ' + path)
  let payload = { items: [], next_cursor: null }
  if (path.endsWith('/me')) payload = user
  else if (path.endsWith('/layout-templates')) payload = { items: [{ id: 'default-template', name: '默认排版', enabled: true, extraction_status: 'completed' }] }
  else if (path.endsWith('/tasks/test-task')) payload = {
    id: 'test-task', title: '历史版本隔离测试', current_article_id: 'A',
    messages: ['A', 'B'].map((id, i) => ({ id: 'message-' + id, task_id: 'test-task', role: 'assistant',
      plain_text: '文章已生成', content_json: { article_id: id, version_no: i === 0 ? 2 : 1 } })),
  }
  else if (/\/articles\/[AB]\/versions$/.test(path)) {
    const id = path.split('/').at(-2)
    payload = { items: [{ id: 'v2', article_id: id, version_no: 2, content_json: doc('旧版本标题 A', bodies[id]) }] }
  } else if (/\/articles\/[AB]$/.test(path)) {
    const id = path.split('/').at(-1)
    payload = { article: { id, title: '当前标题 ' + id, current_version_no: versions[id], source_task_id: 'test-task' },
      version: { version_no: versions[id], content_json: doc('当前标题 ' + id, id === 'A' ? '不应串入的最新版 JSON' : bodies[id]) } }
  }
  await route.fulfill({ json: payload })
})
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ colorScheme })
      await page.goto('http://127.0.0.1:9003/tasks/test-task')
      const buttons = page.getByRole('button', { name: '点击预览', exact: true })
      const cards = page.locator('.message-article-card')
      await expect(cards.first()).toContainText('旧版本标题 A')
      await expect(cards.first().locator('.message-article-card__excerpt')).toContainText('文章 A 旧版本正文')
      await expect(cards.first()).not.toContainText('不应串入的最新版')
      await expect(cards.nth(1)).toContainText('文章 B 独立正文')
      await cards.first().scrollIntoViewIfNeeded()
      await page.waitForTimeout(350)
      const cardGeometry = await cards.first().evaluate(card => {
        const excerpt = card.querySelector('.message-article-card__excerpt')
        return { root: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth,
          height: excerpt.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(excerpt).lineHeight) }
      })
      if (cardGeometry.root > cardGeometry.viewport || cardGeometry.height > cardGeometry.lineHeight * 5 + 1) throw new Error('Card excerpt overflow')
      await page.screenshot({ path: `../../artifacts/article-card-excerpt-${width}-${colorScheme}.png` })
      for (const [format, label] of [['md', 'Markdown (.md)'], ['pdf', 'PDF (.pdf)'], ['docx', 'Word (.docx)']]) {
        const trigger = cards.first().getByRole('button', { name: '下载', exact: true })
        await trigger.hover()
        await expect(page.getByRole('menu', { name: '文章下载格式' })).toBeVisible()
        if (format === 'md') {
          await page.waitForTimeout(350)
          await page.screenshot({ path: `../../artifacts/article-download-menu-${width}-${colorScheme}.png` })
        }
        const downloadReady = page.waitForEvent('download')
        await page.getByRole('menuitem', { name: label, exact: true }).click()
        const downloaded = await downloadReady
        expect(downloaded.suggestedFilename()).toBe(`旧版本标题 A-第2版.${format}`)
        expect(await readFile(await downloaded.path(), 'utf8')).toBe('exported-' + format)
        await expect(page.getByRole('menu', { name: '文章下载格式' })).toHaveCount(0)
      }
      await buttons.first().click()
      const editor = page.getByLabel('文章预览富文本编辑器', { exact: true })
      await editor.getByText(bodies.A, { exact: true }).waitFor()
      if (await editor.getAttribute('contenteditable') !== 'false') throw new Error('History is editable')
      if (await page.getByRole('button', { name: '存本地草稿箱', exact: true }).count()) throw new Error('History can save')
      await page.waitForTimeout(350)
      const geometry = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
      if (geometry.scroll > geometry.client) throw new Error('Overflow')
      await page.screenshot({ path: `../../artifacts/message-preview-${width}-${colorScheme}.png` })
      await page.keyboard.press('Escape')
      await buttons.nth(1).click()
      await editor.getByText(bodies.B, { exact: true }).waitFor()
      if (await editor.getAttribute('contenteditable') !== 'true') throw new Error('Wrong current article')
      await page.keyboard.press('Escape')
      console.log(width, colorScheme, 'history A v2 / current B v1 isolated', geometry)
    }
  }
} finally { await browser.close() }
