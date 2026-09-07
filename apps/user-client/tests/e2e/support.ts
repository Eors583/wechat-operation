import { expect, type Page } from '@playwright/test'

export const login = async (page: Page) => {
  await page.goto('/login')
  await page.evaluate(() => {
    localStorage.clear()
    sessionStorage.clear()
  })
  await page.reload()
  await page.getByLabel('账号').fill('demo@example.com')
  await page.getByRole('textbox', { name: '密码', exact: true }).fill('12345678')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/create$/)
  await expect(page.getByRole('heading', { name: '今天想创作什么？' })).toBeVisible()
}

export const expectNoGlobalOverflow = async (page: Page, label: string) => {
  const readGeometry = () =>
    page.evaluate(() => {
      const root = document.documentElement
      const body = document.body
      const escaped = Array.from(document.querySelectorAll<HTMLElement>('body *'))
        .filter((element) => {
          const rect = element.getBoundingClientRect()
          const style = getComputedStyle(element)
          if (style.position === 'fixed' || style.position === 'absolute') return false
          return rect.width > 0 && (rect.left < -2 || rect.right > window.innerWidth + 2)
        })
        .slice(0, 8)
        .map((element) => ({
          tag: element.tagName.toLowerCase(),
          className: element.className.toString().slice(0, 120),
          text: element.textContent?.trim().slice(0, 60) ?? '',
          rect: element.getBoundingClientRect().toJSON(),
        }))
      return {
        viewport: window.innerWidth,
        rootClientWidth: root.clientWidth,
        rootScrollWidth: root.scrollWidth,
        bodyScrollWidth: body.scrollWidth,
        escaped,
      }
    })
  let geometry: Awaited<ReturnType<typeof readGeometry>> | null = null
  for (let attempt = 0; attempt < 3 && !geometry; attempt += 1) {
    try {
      geometry = await readGeometry()
    } catch (error) {
      if (!(error instanceof Error) || !error.message.includes('Execution context was destroyed'))
        throw error
      await page.waitForLoadState('domcontentloaded')
    }
  }
  if (!geometry) throw new Error(`${label}: 页面在几何检查期间持续导航`)

  expect(
    geometry.rootScrollWidth,
    `${label}: documentElement 横向溢出 ${JSON.stringify(geometry)}`,
  ).toBeLessThanOrEqual(geometry.rootClientWidth + 1)
  expect(
    geometry.bodyScrollWidth,
    `${label}: body 横向溢出 ${JSON.stringify(geometry)}`,
  ).toBeLessThanOrEqual(geometry.viewport + 1)
}
