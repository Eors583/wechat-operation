/* global document, window */
import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width, height }, colorScheme })
      await page.addInitScript(() => {
        const timer = window.setTimeout.bind(window)
        window.setTimeout = (fn, ms, ...args) => timer(fn, Math.min(ms ?? 0, 20), ...args)
        localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user: { id: 'test', name: '测试', points: 100 }, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z' }))
        if (!localStorage.getItem('wechat-ai-pending-message')) localStorage.setItem('wechat-ai-pending-message', JSON.stringify({ original: {
          ownerId: 'test', path: '/tasks/existing/messages', taskId: 'existing', idempotencyKey: 'original', intentSignature: 'original-intent', createdAt: new Date().toISOString(),
          body: { text: '已经发送的消息不能消失', clientMessageId: 'client-original', content: { attachments: [{ id: 'doc', documentId: 'doc', name: '已上传参考文件.pdf', kind: 'file', status: 'ready' }] } },
        } }))
      })
      const keys = []
      const bodies = []
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname
        let payload = { items: [], next_cursor: null }
        if (path.endsWith('/me')) payload = { id: 'test', name: '测试', points: 100 }
        else if (path.endsWith('/model-options')) payload = { items: [{ id: 'model', name: '模型' }] }
        else if (path.endsWith('/tasks/existing')) payload = { id: 'existing', title: '现有会话', messages: [{ id: 'history', task_id: 'existing', role: 'user', plain_text: '历史消息' }] }
        else if (path.endsWith('/tasks/existing/messages') && route.request().method() === 'POST') {
          keys.push(route.request().headers()['idempotency-key'])
          bodies.push(route.request().postData())
          await route.fulfill({ status: 503, json: { code: 'TEMPORARY', message: '测试网络失败', retryable: true } })
          return
        } else if (route.request().method() !== 'GET') throw new Error('Unexpected write ' + path)
        await route.fulfill({ json: payload })
      })
      await page.goto('http://127.0.0.1:9003/tasks/existing')
      const button = page.getByRole('button', { name: '继续原请求', exact: true })
      await expect(button).toBeEnabled()
      await expect(page.locator('.conversation')).toContainText('发送结果待确认')
      await expect(page.locator('.message--user')).toHaveCount(2)
      await expect(page.locator('.conversation')).toContainText('已上传参考文件.pdf')
      await expect(page.getByRole('button', { name: '切换模型', exact: true })).toHaveCount(0)
      await button.click()
      await expect(button).toBeEnabled()
      await page.reload()
      await expect(button).toBeEnabled()
      await expect(page.locator('.message--user')).toHaveCount(2)
      expect(keys.length).toBe(36)
      expect(new Set(keys)).toEqual(new Set(['original']))
      expect(new Set(bodies).size).toBe(1)
      const geometry = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
      expect(geometry.scroll).toBe(geometry.width)
      await page.screenshot({ path: `../../artifacts/pending-message-${width}-${colorScheme}.png` })
      console.log(width, colorScheme, 'history + pending attachment retained after resume/reload, same key/body', geometry)
      await page.close()
    }
  }
} finally { await browser.close() }
