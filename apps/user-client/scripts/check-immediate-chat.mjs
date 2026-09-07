/* global document */
import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      for (const chatPath of ['/create', '/tasks/existing']) {
      const page = await browser.newPage({ viewport: { width, height }, colorScheme })
      const user = { id: 'test', name: '测试', points: 100 }
      await page.addInitScript(user => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z' })), user)
      let release
      const gate = new Promise(resolve => { release = resolve })
      let posts = 0
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname
        let payload = { items: [], next_cursor: null }
        if (path.endsWith('/me')) payload = user
        else if (path.endsWith('/model-options')) payload = { items: [{ id: 'test-model', name: '测试模型' }] }
        else if (path.endsWith('/tasks/existing')) payload = route.request().method() === 'PATCH' ? {} : { id: 'existing', title: '现有聊天', messages: [] }
        else if ((path.endsWith('/tasks') || path.endsWith('/tasks/existing/messages')) && route.request().method() === 'POST') {
          posts++
          await gate
          await route.fulfill({ status: 422, json: { error: { code: 'TEST_FAILURE', message: '测试发送失败', retryable: false } } })
          return
        }
        else if (route.request().method() !== 'GET') throw new Error('Unexpected write: ' + path)
        await route.fulfill({ json: payload })
      })
      await page.goto('http://127.0.0.1:9003' + chatPath)
      const text = '请帮我写一篇文章。' + '长内容测试'.repeat(20)
      await page.getByLabel('给内容助手发送消息').fill(text)
      await page.getByRole('button', { name: '发送消息', exact: true }).click()
      await expect(page.locator('.blank-create')).toHaveCount(0)
      await expect(page.locator('.message--user')).toHaveCount(1)
      await expect(page.locator('.message--user')).toContainText(text)
      await expect(page.locator('.message--thinking')).toBeVisible()
      await page.screenshot({ path: `../../artifacts/immediate-chat-${chatPath.includes('existing') ? 'existing' : 'new'}-${width}-${colorScheme}.png` })
      release()
      const retry = page.getByRole('button', { name: '重新生成', exact: true })
      await expect(retry).toBeEnabled()
      await expect(page.locator('.message--user')).toContainText(text)
      await retry.click()
      await expect(retry).toBeEnabled()
      await expect(page.locator('.message--user')).toHaveCount(1)
      await expect.poll(() => posts).toBe(2)
      const geometry = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
      expect(geometry.scroll).toBe(geometry.width)
      console.log(chatPath, width, colorScheme, 'immediate message + failed message retained + retry without duplicate', geometry)
      await page.close()
      }
    }
  }
} finally { await browser.close() }
