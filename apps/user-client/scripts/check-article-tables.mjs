/* global document, getComputedStyle */
import { chromium, expect } from '@playwright/test'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()
page.on('pageerror', error => console.log('PAGE ERROR', error.message))
const makeDoc = () => ({ type: 'doc', content: [
  { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: '表格文章' }] },
  { type: 'table', content: ['表头', '正文', '结尾'].map((label, row) => ({ type: 'tableRow', content: [0, 1, 2].map(col => ({
    type: row === 0 ? 'tableHeader' : 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: `${label}${col}：` + (col === 2 ? '长中文内容'.repeat(12) : '对比信息') }] }],
  })) })) },
] })
let content = makeDoc()
let version = 1
let saved = false
const user = { id: 'test', name: '表格测试', role: '内容运营', points: 100, themePreference: 'system' }
await page.addInitScript(user => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z' })), user)
await page.route('**/api/v1/**', async route => {
  const path = new URL(route.request().url()).pathname
  let payload = { items: [], next_cursor: null }
  const envelope = () => ({ article: { id: 'B', title: '表格文章', current_version_no: version, source_task_id: 'test-task', status: 'local_draft' }, version: { version_no: version, content_json: content } })
  if (route.request().method() === 'PUT' && path.endsWith('/articles/B/content')) {
    const body = route.request().postDataJSON()
    expect(body.base_version_no).toBe(version)
    expect(body.content.content.some(n => n.type === 'table')).toBe(true)
    content = body.content
    version += 1
    saved = true
    payload = envelope()
  } else if (route.request().method() !== 'GET') throw new Error('Unexpected write ' + path)
  else if (path.endsWith('/me')) payload = user
  else if (path.endsWith('/layout-templates')) payload = { items: [{ id: 'template-style', name: '表格样式模板', enabled: true, extraction_status: 'ready', version: { style_tokens: { table_header: { background: '#123456', color: '#ffffff', font_size: 19, padding: 12, border_all: '2px solid #059669' }, table_cell: { font_size: 14, padding: 10 } } } }] }
  else if (path.endsWith('/tasks/test-task')) payload = { id: 'test-task', title: '表格端到端测试', current_article_id: 'B', messages: [{ id: 'm1', task_id: 'test-task', role: 'assistant', plain_text: '文章已生成', content_json: { article_id: 'B', version_no: version } }] }
  else if (path.endsWith('/articles/B/versions')) payload = { items: [{ id: 'v1', article_id: 'B', version_no: 1, content_json: makeDoc() }] }
  else if (path.endsWith('/articles/B')) payload = envelope()
  await route.fulfill({ json: payload })
})
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      content = makeDoc(); version = 1; saved = false
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ colorScheme })
      await page.goto('http://127.0.0.1:9003/tasks/test-task')
      await page.getByRole('button', { name: '点击预览', exact: true }).click()
      const editor = page.getByLabel('文章预览富文本编辑器', { exact: true })
      await expect(editor.locator('tr')).toHaveCount(3)
      await expect(editor.locator('th')).toHaveCount(3)
      await expect(editor.locator('td')).toHaveCount(6)
      await expect(editor.locator('th').first()).toHaveCSS('background-color', 'rgb(18, 52, 86)')
      await expect(editor.locator('th p').first()).toHaveCSS('font-size', '19px')
      await expect(editor.locator('th').first()).toHaveCSS('border-top-width', '2px')
      await editor.locator('td').first().click()
      await page.keyboard.press('End')
      await page.keyboard.insertText('修改')
      await page.getByRole('button', { name: '表格操作', exact: true }).click()
      await page.getByText('在下方增加一行', { exact: true }).click()
      await expect(editor.locator('tr')).toHaveCount(4)
      await page.getByRole('button', { name: '存本地草稿箱', exact: true }).click()
      await expect.poll(() => saved).toBe(true)
      expect(JSON.stringify(content)).toContain('修改')
      await page.reload()
      await page.getByRole('button', { name: '点击预览', exact: true }).click()
      await expect(editor.locator('tr')).toHaveCount(4)
      await editor.locator('table').scrollIntoViewIfNeeded()
      await page.waitForTimeout(350)
      const geometry = await editor.locator('.tableWrapper').evaluate(element => ({
        root: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth,
        width: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX,
      }))
      expect(geometry.root).toBe(geometry.viewport)
      expect(geometry.overflow).toBe('auto')
      await page.screenshot({ path: `../../artifacts/article-tables-${width}-${colorScheme}.png` })
      await page.goto('http://127.0.0.1:9003/articles/B/edit')
      const formal = page.getByLabel('文章正文编辑器', { exact: true })
      await expect(formal.locator('tr')).toHaveCount(4)
      await expect(formal).toContainText('修改')
      console.log(width, colorScheme, 'edit/add-row/save/reload/formal-editor PASS', geometry)
    }
  }
} catch (error) {
  console.log((await page.locator('body').innerText()).slice(-2000))
  await page.screenshot({ path: '../../artifacts/article-tables-failure.png' })
  throw error
} finally { await browser.close() }
