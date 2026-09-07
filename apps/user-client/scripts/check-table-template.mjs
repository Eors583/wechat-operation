/* global document */
import { chromium, expect } from '@playwright/test'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const user = { id: 'test', name: '测试', role: '内容运营', points: 100, themePreference: 'system' }
await page.addInitScript(user => localStorage.setItem('wechat-ai-user-client-auth', JSON.stringify({ user, accessToken: 'test-only' })), user)
let tokens = {}
let saves = 0
const template = () => ({ id: 'style-test', name: '表格模板', enabled: true, extraction_status: 'ready', version: { style_tokens: tokens } })
await page.route('**/api/v1/**', async route => {
  const path = new URL(route.request().url()).pathname
  let data = { items: [] }
  if (route.request().method() === 'PATCH' && path.endsWith('/layout-templates/style-test')) {
    tokens = route.request().postDataJSON().style_tokens
    expect(tokens.table_header.background).toBe('#234567')
    expect(tokens.table_cell.border_all).toBe('1px solid #d1d5db')
    saves++; data = template()
  } else if (route.request().method() !== 'GET') throw new Error('Unexpected write')
  else if (path.endsWith('/me')) data = user
  else if (path.endsWith('/layout-templates')) data = { items: [template()] }
  await route.fulfill({ json: data })
})
try {
  await page.goto('http://127.0.0.1:9003/official-accounts')
  await page.getByRole('button', { name: '排版模板', exact: true }).click()
  await page.getByRole('button', { name: /表格表头/ }).click()
  await page.locator('.template-editor__settings input[type=color]').nth(1).fill('#234567')
  await expect(page.locator('.template-editor__table-wrap th').first()).toHaveCSS('background-color', 'rgb(35, 69, 103)')
  await page.getByRole('button', { name: /保存/ }).last().click()
  await expect.poll(() => saves).toBe(1)
  await page.reload()
  await page.getByRole('button', { name: '排版模板', exact: true }).click()
  await page.getByRole('button', { name: /表格表头/ }).click()
  await expect(page.locator('.template-editor__table-wrap th').first()).toHaveCSS('background-color', 'rgb(35, 69, 103)')
  await page.locator('.template-editor__table-wrap').scrollIntoViewIfNeeded()
  await page.screenshot({ path: '../../artifacts/table-template-settings.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  console.log('Table header/cell controls, save payload and reload PASS')
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    for (const colorScheme of ['light', 'dark']) {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ colorScheme })
      await page.waitForTimeout(350)
      if (width < 1024) {
        await page.getByRole('tab', { name: '模块', exact: true }).click()
        await page.getByRole('button', { name: /表格单元格/ }).click()
        await page.getByRole('tab', { name: '样式', exact: true }).click()
        await expect(page.getByText('表格单元格样式', { exact: true })).toBeVisible()
        await page.getByRole('tab', { name: '预览', exact: true }).click()
      }
      await page.locator('.template-editor__table-wrap').scrollIntoViewIfNeeded()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
      await page.screenshot({ path: `../../artifacts/table-template-${width}-${colorScheme}.png` })
      console.log(width, colorScheme, 'template table settings/preview geometry PASS')
    }
  }
} finally { await browser.close() }
