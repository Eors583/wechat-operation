import { expect, test } from '@playwright/test'
import { expectNoGlobalOverflow } from '../e2e/support'

async function register(page: import('@playwright/test').Page): Promise<void> {
  const phone = `139${Date.now().toString().slice(-8)}`
  const password = 'Integration#2026'
  await page.goto('/register')
  await page.getByLabel('手机号').fill(phone)
  const codeResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().endsWith('/api/v1/auth/verification-codes'),
  )
  await page.getByRole('button', { name: '获取验证码' }).click()
  const codePayload = (await (await codeResponse).json()) as { debug_code?: string }
  if (codePayload.debug_code) await page.getByLabel('验证码').fill(codePayload.debug_code)
  await expect(page.getByLabel('验证码')).not.toHaveValue('')
  await page.getByLabel('设置密码').fill(password)
  await page.getByLabel('确认密码').fill(password)
  await page.getByRole('checkbox').check({ force: true })
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(page).toHaveURL(/\/create$/)
}

test('registers, generates an article over SSE, saves it, and finds it in the library', async ({
  page,
}) => {
  await register(page)

  await expect(page).toHaveURL(/\/create$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('创作')

  await page
    .getByLabel('给内容助手发送消息')
    .fill(
      '请写一篇可直接用于微信公众号的完整文章，主题是中小企业如何安全使用生成式 AI，包含标题、导语、三个小节和结语。',
    )
  await page.getByRole('button', { name: '发送消息' }).click()

  await expect(page).toHaveURL(/\/tasks\/[0-9a-f-]{36}$/i, { timeout: 60_000 })
  const continueGeneration = page.getByRole('button', { name: '继续生成完整文章' })
  if (await continueGeneration.isVisible()) await continueGeneration.click()
  const editButton = page.getByRole('button', { name: '打开编辑' })
  await expect(editButton).toBeVisible({ timeout: 60_000 })
  await editButton.click()

  await expect(page).toHaveURL(/\/articles\/[0-9a-f-]{36}\/edit$/i)
  const title = (await page.locator('.article-title input').inputValue()).trim()
  expect(title).not.toBe('')

  const saveResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      /\/api\/v1\/articles\/[0-9a-f-]{36}\/save-local$/i.test(response.url()),
  )
  await page.getByRole('button', { name: '存本地草稿箱' }).click()
  await expect((await saveResponse).status()).toBe(200)
  await expect(page.getByText('文章已存入本地草稿箱，并出现在文章库。')).toBeVisible()

  await page.goto('/articles')
  await expect(page.getByRole('heading', { name: '文章库' })).toBeVisible()
  await page.getByLabel('搜索文章库').fill(title)
  await expect(page.getByText(title, { exact: true }).first()).toBeVisible()
  await expect(page.getByText('公众号文章').first()).toBeVisible()
})

test('renders a contained one-time official-account authorization QR dialog', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.route('**/api/v1/official-accounts/authorize-url', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        authorization_url:
          'https://mp.weixin.qq.com/cgi-bin/componentloginpage?component_appid=wx_component_test&pre_auth_code=preauth_test&redirect_uri=https%3A%2F%2Fapi.example.com%2Fcallbacks%2Fv1%2Fwechat%2Fauthorize&auth_type=1',
        expires_in: 300,
      }),
    })
  })
  await register(page)
  await page.goto('/official-accounts')

  await page.getByRole('button', { name: '授权新公众号' }).click()
  await expect(page.getByRole('heading', { name: '授权新公众号' })).toBeVisible()
  await expect(page.getByAltText('微信公众号授权二维码')).toBeVisible()
  await expect(page.getByText('请使用公众号管理员微信扫码')).toBeVisible()
  await expect(page.getByText('扫码后将直接进入微信授权确认')).toBeVisible()
  await expect(page.getByRole('button', { name: '打开授权页面' })).toHaveCount(0)
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expectNoGlobalOverflow(page, `公众号扫码授权弹窗 ${viewport.width}px`)
    await page.screenshot({
      path: `test-results/visual/wechat-authorization-${viewport.width}.png`,
      animations: 'disabled',
    })
  }
})
