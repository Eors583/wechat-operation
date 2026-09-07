/* global document */
import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width, height }, colorScheme })
      await page.addInitScript(() => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({
        user: { id: 'test', name: '测试', points: 100 }, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z',
      })))
      const messages = []
      let posts = 0
      let release
      const gate = new Promise(resolve => { release = resolve })
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname
        let payload = { items: [] }
        if (path.endsWith('/me')) payload = { id: 'test', name: '测试', points: 100 }
        else if (path.endsWith('/model-options')) payload = { items: [{ id: 'model', name: '测试模型' }] }
        else if ((path.endsWith('/tasks') || path.endsWith('/tasks/created/messages')) && route.request().method() === 'POST') {
          posts++
          const body = route.request().postDataJSON()
          const submitted = body.first_message ?? body
          const message = { id: `server-message-${posts}`, role: 'user', task_id: 'created', plain_text: submitted.text, client_message_id: submitted.client_message_id }
          expect(message.client_message_id).toBeTruthy()
          messages.push(message)
          payload = { task: { id: 'created', title: '生成文章' }, ai_run: { id: 'run' } }
        } else if (path.endsWith('/tasks')) payload = { items: posts ? [{ id: 'created', title: '生成文章' }] : [] }
        else if (path.endsWith('/tasks/created')) payload = { id: 'created', title: '生成文章', messages }
        else if (path.endsWith('/ai-runs/run/events')) {
          await gate
          await route.fulfill({ contentType: 'text/event-stream', body: 'event: run.completed\ndata: {}\n\n' })
          return
        } else if (path.endsWith('/ai-runs/run')) payload = { id: 'run', status: 'accepted' }
        else if (route.request().method() !== 'GET') throw new Error('Unexpected write: ' + path)
        await route.fulfill({ json: payload })
      })
      await page.goto('http://127.0.0.1:9003/create')
      await page.getByLabel('给内容助手发送消息').fill('继续生成完整文章' + '长内容'.repeat(40))
      await page.getByRole('button', { name: '发送消息', exact: true }).click()
      await expect(page).toHaveURL(/tasks\/created/)
      await expect(page.locator('.message--thinking')).toBeVisible()
      await expect(page.locator('.message--user')).toHaveCount(1)
      // The sidebar must update while generation is still blocked, without reloading.
      await expect(page.locator('a[href="/tasks/created"]')).toHaveCount(1)
      const geometry = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
      expect(geometry.scroll).toBe(geometry.width)
      await page.screenshot({ path: `../../artifacts/message-dedup-${width}-${colorScheme}.png` })
      release()
      await expect(page.locator('.message--thinking')).toHaveCount(0)
      await expect(page.locator('.message--user')).toHaveCount(1)
      expect(posts).toBe(1)
      await page.getByLabel('给内容助手发送消息').fill('继续生成完整文章' + '长内容'.repeat(40))
      await page.getByRole('button', { name: '发送消息', exact: true }).click()
      await expect.poll(() => posts).toBe(2)
      await expect(page.locator('.message--thinking')).toHaveCount(0)
      await expect(page.locator('.message--user')).toHaveCount(2)
      expect(messages[0].client_message_id).not.toBe(messages[1].client_message_id)
      console.log(width, colorScheme, 'one message before and after completion', geometry)
      await page.close()
    }
  }
} finally { await browser.close() }
