import { expect, test, type Page } from '@playwright/test'

async function expectCenteredDialog(page: Page, selector: string): Promise<void> {
  const dialog = page.locator(selector)
  await expect(dialog).toBeVisible()
  await page.waitForTimeout(350)
  const geometry = await dialog.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return {
      centerOffsetX: Math.abs(rect.left + rect.width / 2 - window.innerWidth / 2),
      centerOffsetY: Math.abs(rect.top + rect.height / 2 - window.innerHeight / 2),
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
    }
  })
  expect(geometry.centerOffsetX).toBeLessThanOrEqual(2)
  expect(geometry.centerOffsetY).toBeLessThanOrEqual(2)
  expect(geometry.left).toBeGreaterThanOrEqual(0)
  expect(geometry.right).toBeLessThanOrEqual(await page.evaluate(() => window.innerWidth))
  expect(geometry.top).toBeGreaterThanOrEqual(0)
  expect(geometry.bottom).toBeLessThanOrEqual(await page.evaluate(() => window.innerHeight))
  await expect(page.locator('.el-drawer:visible')).toHaveCount(0)
}

test('logs in with a real administrator session and reads protected operations data', async ({
  page,
}, testInfo) => {
  const pageErrors: string[] = []
  const apiErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('response', (response) => {
    if (response.url().includes('/admin-api/v1/') && response.status() >= 400)
      apiErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`)
  })
  await page.goto('/login')
  await page.getByLabel('管理员账号').fill('e2e-admin')
  await page.getByRole('textbox', { name: '密码', exact: true }).fill('AdminE2E2026_')
  const dashboardResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' && response.url().endsWith('/admin-api/v1/dashboard'),
  )
  const loginResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && response.url().endsWith('/admin-api/v1/auth/login'),
  )
  await page.getByRole('button', { name: '登录' }).click()

  await expect((await dashboardResponse).status()).toBe(200)
  const auth = await (await loginResponse).json()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '管理首页' })).toBeVisible()
  await expect(page.getByText('AI 运行质量')).toBeVisible()

  await page.goto('/settings/admins')
  await expect(page.getByRole('heading', { name: '管理员账号' })).toBeVisible()
  await expect(page.locator('tbody').getByText('e2e-admin', { exact: true }).first()).toBeVisible()

  await page.goto('/settings/audit')
  await expect(page.getByRole('heading', { name: '审计日志' })).toBeVisible()
  await expect(
    page.locator('tbody').getByText('admin.login', { exact: true }).first(),
  ).toBeVisible()
  await expect(
    page
      .locator('tbody')
      .getByText(/^admin:/)
      .first(),
  ).toBeVisible()

  const routes = [
    ['/ai/config', '模型、排版智能体与积分'],
    ['/ai/prompts', '提示词版本'],
    ['/skills', '官方技能库'],
    ['/users', '用户与额度'],
    ['/wechat/platform', '微信平台配置'],
    ['/wechat/accounts', '公众号连接'],
    ['/tasks', '任务与对账'],
    ['/settings', '系统设置'],
    ['/settings/external-knowledge', '外部知识库'],
  ] as const
  for (const [route, heading] of routes) {
    await page.goto(route)
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    await page.waitForLoadState('networkidle')
    const width = await page.evaluate(() => ({
      client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
    }))
    expect(width.scroll, `${route} root width`).toBeLessThanOrEqual(width.client)
  }

  await page.goto('/wechat/platform')
  await page.getByRole('button', { name: '替换密钥' }).click()
  await expect(page.getByText('填写平台密钥', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Component AppSecret')).toHaveAttribute('type', 'password')
  await expect(page.getByLabel('消息校验 Token')).toHaveAttribute('type', 'password')
  await expect(page.getByLabel('EncodingAESKey')).toHaveAttribute('type', 'password')
  const secretDialogWidth = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }))
  expect(secretDialogWidth.scroll, '微信密钥弹窗 root width').toBeLessThanOrEqual(
    secretDialogWidth.client,
  )
  await testInfo.attach('wechat-secret-dialog', {
    body: await page.screenshot(),
    contentType: 'image/png',
  })
  await page.getByRole('button', { name: '关闭' }).click()

  if (testInfo.project.name === 'real-backend-390') {
    await page.goto('/ai/config')
    await expect(page.locator('.admin-aside')).toHaveCount(0)
    await page.getByRole('tab', { name: '排版智能体', exact: true }).click()
    const mobileLayout = await page.evaluate(() => {
      const content = document.querySelector<HTMLElement>('.admin-content')
      const grid = document.querySelector<HTMLElement>('.layout-agent-grid')
      return {
        contentWidth: content?.clientWidth ?? 0,
        gridWidth: grid?.getBoundingClientRect().width ?? 0,
        viewportWidth: window.innerWidth,
      }
    })
    expect(mobileLayout.contentWidth).toBe(mobileLayout.viewportWidth)
    expect(mobileLayout.gridWidth).toBeGreaterThanOrEqual(340)

    await page.getByRole('button', { name: '打开或收起导航' }).click()
    await expect(page.locator('.admin-aside')).toBeVisible()
    await expect(page.locator('.admin-aside-scrim')).toBeVisible()
    const drawer = await page.locator('.admin-aside').evaluate((element) => {
      const rect = element.getBoundingClientRect()
      return { left: rect.left, right: rect.right, width: rect.width }
    })
    expect(drawer).toEqual({ left: 0, right: 252, width: 252 })
    await page.getByRole('button', { name: '打开或收起导航' }).click()
  }

  await page.goto('/skills')
  await page.getByRole('button', { name: '新建官方技能' }).click()
  await expectCenteredDialog(page, '.admin-center-dialog')
  await expect(page.getByLabel('分类')).toHaveValue('文章创作')
  await expect(page.getByRole('combobox', { name: '适用场景' })).toBeVisible()
  await testInfo.attach('centered-skill-dialog', {
    body: await page.screenshot(),
    contentType: 'image/png',
  })
  await page.getByRole('button', { name: '关闭编辑器' }).click()

  await page.goto('/ai/config')
  const modelName = `E2E 删除模型 ${testInfo.project.name}`
  const createdModel = await page.request.post(
    'http://127.0.0.1:9011/admin-api/v1/model-configurations',
    {
      headers: { Authorization: `Bearer ${auth.access_token}` },
      data: {
        name: modelName,
        base_url: 'https://models.example/v1',
        secret_ref: 'env:E2E_MODEL_KEY',
        model_id: 'e2e-delete-model',
      },
    },
  )
  expect(createdModel.status()).toBe(201)
  await page.reload()
  await expect(page.getByText(modelName, { exact: true })).toBeVisible()
  await page.getByRole('button', { name: `删除模型 ${modelName}` }).click()
  await expectCenteredDialog(page, '.confirm-dialog')
  await expect(page.getByText(/相关路由将自动移除该模型；主模型有备用时会自动切换/)).toBeVisible()
  await testInfo.attach('delete-model-confirm-dialog', {
    body: await page.screenshot(),
    contentType: 'image/png',
  })
  const deleteResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'DELETE' &&
      response.url().includes('/admin-api/v1/model-configurations/'),
  )
  await page.getByRole('button', { name: '删除', exact: true }).click()
  expect((await deleteResponse).status()).toBe(204)
  await expect(page.getByText(modelName, { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: '添加模型' }).click()
  await expectCenteredDialog(page, '.model-dialog')
  await expect(page.getByLabel('模型厂商')).toBeVisible()
  await expect(page.getByRole('combobox', { name: '模型', exact: true })).toBeVisible()
  await expect(page.getByLabel('API Key')).toBeVisible()
  await expect(page.getByRole('button', { name: '测试连接' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '保存草稿' })).toBeDisabled()
  await expect(page.getByLabel('API 地址')).toHaveCount(0)
  await expect(page.getByLabel('调用 model 值')).toHaveCount(0)
  await testInfo.attach('provider-preset-model-dialog', {
    body: await page.screenshot(),
    contentType: 'image/png',
  })
  await page.getByRole('button', { name: '取消' }).click()

  await page.goto('/settings/audit')
  await page.getByRole('button', { name: '详情' }).first().click()
  await expectCenteredDialog(page, '.admin-center-dialog')
  await page.getByRole('button', { name: '关闭' }).click()

  expect(pageErrors).toEqual([])
  expect(apiErrors).toEqual([])
})
