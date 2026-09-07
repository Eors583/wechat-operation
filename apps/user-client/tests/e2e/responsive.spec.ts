import { expect, test } from '@playwright/test'
import { expectNoGlobalOverflow, login } from './support'

const viewports = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1024, height: 900 },
  { width: 1440, height: 960 },
  { width: 1920, height: 1080 },
] as const

test('critical pages remain contained at all five acceptance viewports', async ({ page }) => {
  await page.setViewportSize(viewports[3])
  await login(page)

  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    const suffix = `${viewport.width}x${viewport.height}`

    await page.goto('/create')
    await expect(page.getByRole('heading', { name: '今天想创作什么？' })).toBeVisible()
    await page
      .getByLabel('给内容助手发送消息')
      .fill(
        `超长内容安全检查 https://example.com/${'unbroken-segment-'.repeat(45)} 这是用于验证中文长段落、URL 和输入框不会撑破布局的测试文本。`,
      )
    await expectNoGlobalOverflow(page, `AI 创作 ${suffix}`)
    await page.screenshot({ path: `test-results/visual/create-${suffix}.png`, fullPage: true })

    await page.goto('/articles')
    await expect(page.getByRole('heading', { name: '文章库' })).toBeVisible()
    await expect(
      page
        .locator('.library-title:visible, .library-card:visible')
        .filter({ hasText: '品牌内容策略：从信息堆砌到清晰表达' })
        .first(),
    ).toBeVisible()
    await expectNoGlobalOverflow(page, `文章库 ${suffix}`)
    await page.screenshot({ path: `test-results/visual/library-${suffix}.png`, fullPage: true })

    await page.goto('/tasks/task_brand_article')
    await expect(page.getByText('文章已经生成并完成内容检查。')).toBeVisible()
    await expectNoGlobalOverflow(page, `任务工作台 ${suffix}`)
    await page.screenshot({ path: `test-results/visual/task-${suffix}.png`, fullPage: true })
  }
})

test('sent attachment progress belongs to the chat message, not the composer', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)
  await page.route('**/*', async (route) => {
    if (route.request().method() === 'PUT')
      await new Promise((resolve) => setTimeout(resolve, 5000))
    await route.continue()
  })

  const filename = `${'华为战略规划与执行综合框架'.repeat(5)}.pptx`
  const chooserRequest = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: '上传附件' }).click()
  const chooser = await chooserRequest
  await chooser.setFiles({
    name: filename,
    mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    buffer: Buffer.alloc(2 * 1024 * 1024, 1),
  })
  await page.getByLabel('给内容助手发送消息').fill('根据附件生成文章')
  await page.getByRole('button', { name: '发送消息' }).click()

  const messageProgress = page.locator('.message--user .message__attachment-progress')
  await expect(messageProgress).toContainText('上传中')
  await expect(page.locator('.prompt-composer__uploads')).toHaveCount(0)
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expect(messageProgress).toBeVisible()
    await expectNoGlobalOverflow(page, `消息附件上传进度 ${viewport.width}x${viewport.height}`)
  }
  await page.screenshot({
    path: 'test-results/visual/message-upload-progress-390x844.png',
    fullPage: true,
  })
})

test('the user-selected model survives reload and is never replaced by the first option', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)

  const modelSelect = page.getByLabel('选择对话模型')
  await expect(modelSelect).toHaveValue('自动（稳定优先）')
  await modelSelect.click()
  await page.getByRole('option', { name: /Manus Lite/ }).click()
  await expect(modelSelect).toHaveValue('Manus Lite')

  await page.reload()
  await expect(page.getByRole('heading', { name: '今天想创作什么？' })).toBeVisible()
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expect(page.getByLabel('选择对话模型')).toHaveValue('Manus Lite')
    await expectNoGlobalOverflow(page, `用户模型选择持久化 ${viewport.width}x${viewport.height}`)
  }
})
