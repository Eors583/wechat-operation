/* global document, DataTransfer */
import { chromium, expect } from '@playwright/test'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()
const user = { id: 'test', name: '拖拽测试', role: '内容运营', points: 100, themePreference: 'system' }
await page.addInitScript(user => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z' })), user)
await page.route('**/api/v1/**', async route => {
  const path = new URL(route.request().url()).pathname
  if (route.request().method() !== 'GET') throw new Error('Unexpected write: ' + path)
  let payload = { items: [], next_cursor: null }
  if (path.endsWith('/me')) payload = user
  if (path.endsWith('/tasks/drop-test')) payload = { id: 'drop-test', title: '拖拽测试', messages: [] }
  await route.fulfill({ json: payload })
})
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ colorScheme })
      for (const path of ['/create', '/tasks/drop-test']) {
        await page.goto('http://127.0.0.1:9003' + path)
        const composer = page.getByRole('region', { name: '创作输入', exact: true })
        await composer.waitFor()
        await composer.scrollIntoViewIfNeeded()
        await page.waitForTimeout(350)
        const dataTransfer = await page.evaluateHandle(() => {
          const data = new DataTransfer()
          data.items.add(new File(['reference'], '长文件名'.repeat(80) + '.txt', { type: 'text/plain' }))
          data.items.add(new File(['reference two'], '参考资料.md', { type: 'text/markdown' }))
          return data
        })
        await composer.dispatchEvent('dragenter', { dataTransfer })
        await composer.dispatchEvent('dragover', { dataTransfer })
        await expect(composer.getByRole('status')).toContainText('松开添加附件')
        await page.screenshot({ path: `../../artifacts/file-drag-${width}-${colorScheme}-${path.includes('tasks') ? 'task' : 'new'}.png` })
        await composer.locator('textarea').dispatchEvent('drop', { dataTransfer })
        await expect(composer.locator('.q-chip')).toHaveCount(2)
        await expect(composer.getByRole('status')).toHaveCount(0)
        const geometry = await composer.evaluate(el => {
          const rect = el.getBoundingClientRect()
          return { root: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth, left: rect.left, right: rect.right }
        })
        if (geometry.root > geometry.viewport || geometry.left < 0 || geometry.right > width + 1) throw new Error(JSON.stringify(geometry))
        await page.screenshot({ path: `../../artifacts/file-drop-${width}-${colorScheme}-${path.includes('tasks') ? 'task' : 'new'}.png` })
        await dataTransfer.dispose()
        console.log(path, width, colorScheme, geometry)
      }
    }
  }
} finally { await browser.close() }
