/* global document, DataTransfer */
import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      const page = await browser.newPage({ viewport: { width, height }, colorScheme })
      const user = { id: 'test', name: '测试', points: 100 }
      await page.addInitScript(user => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user, accessToken: 'test-only', expiresAt: '2099-01-01T00:00:00Z' })), user)
      let releaseComplete
      const completeGate = new Promise(resolve => { releaseComplete = resolve })
      await page.route('**/api/v1/**', async route => {
        const path = new URL(route.request().url()).pathname
        let payload = { items: [], next_cursor: null }
        if (path.endsWith('/me')) payload = user
        else if (path.endsWith('/model-options')) payload = { items: [{ id: 'test-model', name: '测试模型' }] }
        else if (path.endsWith('/uploads')) payload = { upload: { id: 'upload-test' }, part_urls: ['/api/v1/test-part'], part_size_bytes: 4194304 }
        else if (path.endsWith('/test-part')) { await route.fulfill({ status: 200, headers: { ETag: 'test-etag' }, body: '' }); return }
        else if (path.endsWith('/complete')) { await completeGate; payload = { asset: { id: 'asset-test' }, document: { id: 'doc-test' } } }
        else if (path.endsWith('/documents/doc-test')) payload = { id: 'doc-test', status: 'processing' }
        else if (route.request().method() !== 'GET') throw new Error('Unexpected write: ' + path)
        await route.fulfill({ json: payload })
      })
      await page.goto('http://127.0.0.1:9003/create')
      const composer = page.getByRole('region', { name: '创作输入', exact: true })
      const dataTransfer = await page.evaluateHandle(() => {
        const data = new DataTransfer()
        data.items.add(new File([new Uint8Array(4194304)], '长文件名'.repeat(60) + '.txt', { type: 'text/plain' }))
        return data
      })
      await composer.dispatchEvent('drop', { dataTransfer })
      await expect(composer.locator('.q-chip')).toHaveCount(1)
      await expect(composer.locator('.q-chip .prompt-composer__file-status')).toHaveCount(0)
      await expect(composer).not.toContainText('待上传')
      await expect(composer.locator('.q-chip .q-spinner')).toHaveCount(0)
      await composer.locator('textarea').fill('参考附件写文章')
      await composer.getByRole('button', { name: '发送消息', exact: true }).click()
      await expect(page.locator('.blank-create')).toHaveCount(0)
      await expect(page.locator('.message--user')).toContainText('参考附件写文章')
      await expect(page.locator('.message--user .q-chip')).toHaveCount(1)
      const progress = composer.getByLabel('附件上传进度')
      await expect(progress).toContainText('4.00 MB / 4.00 MB · 确认上传中')
      releaseComplete()
      await expect(progress).toContainText('4.00 MB / 4.00 MB · 解析中')
      await progress.scrollIntoViewIfNeeded()
      const geometry = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
      expect(geometry.scroll).toBe(geometry.width)
      await page.screenshot({ path: `../../artifacts/upload-bytes-${width}-${colorScheme}.png` })
      console.log(width, colorScheme, geometry, 'XHR upload bytes and processing verified')
      await page.close()
    }
  }
} finally { await browser.close() }
