import { expect, test } from '@playwright/test'
import { expectNoGlobalOverflow, login } from './support'

test('first message creates a task, article, editor and confirmed WeChat draft', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await login(page)

  await page.getByLabel('所属项目（可选）').click()
  await page.getByRole('option', { name: '品牌内容运营' }).click()
  const composer = page.getByLabel('给内容助手发送消息')
  await composer.fill('请生成一篇关于团队知识管理的公众号文章，语气专业、开头直接进入主题。')
  await page.getByRole('button', { name: '发送消息' }).click()

  await expect(page).toHaveURL(/\/tasks\/task_/)
  await expect(page.getByText('文章已经生成并完成内容检查。')).toBeVisible()
  await expect(page.getByLabel('所属项目')).toHaveValue('品牌内容运营')
  await expect(page.getByLabel('当前文章侧栏')).toBeVisible()
  await expectNoGlobalOverflow(page, '生成结果工作台')
  await page.screenshot({ path: 'test-results/visual/flow-generated-1440.png', fullPage: true })

  await page.getByRole('button', { name: '打开编辑' }).click()
  await expect(page).toHaveURL(/\/articles\/article_.*\/edit/)
  await expect(page.getByLabel('文章正文编辑器')).toBeVisible()
  await expect(page.getByLabel('目标公众号')).toHaveValue('品牌内容号')
  await expect(page.getByLabel('已启用模板')).toHaveValue('标准排版')

  await page.getByRole('button', { name: '存公众号草稿箱' }).click()
  await expect(page.getByRole('heading', { name: '公众号草稿最终预览' })).toBeVisible()
  await expect(page.getByText('微信公众号最终效果 · 只读')).toBeVisible()
  await expect(page.getByText('排版版本已锁定', { exact: true })).toBeVisible()
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'test-results/visual/flow-final-preview-1440.png', fullPage: true })
  await page.getByRole('button', { name: '确认存入草稿箱' }).click()

  await expect(page.getByRole('heading', { name: '公众号草稿最终预览' })).toBeHidden()
  await expect(page.getByText('模拟草稿', { exact: true })).toBeVisible()
  await expect(
    page.getByText('当前是模拟通道：系统仅记录了操作，没有写入或发布到真实公众号。'),
  ).toBeVisible()
})

test('article version conflicts preserve local edits and offer an explicit recovery path', async ({
  page,
  context,
}) => {
  test.setTimeout(70_000)
  await page.setViewportSize({ width: 1440, height: 960 })
  await login(page)
  await page.goto('/articles/article_brand_strategy/edit')
  await expect(page.getByLabel('文章正文编辑器')).toBeVisible()

  const concurrent = await context.newPage()
  await concurrent.goto('/articles/article_brand_strategy/edit')
  await expect(concurrent.getByLabel('文章正文编辑器')).toBeVisible()
  await concurrent.getByLabel('文章标题').fill('并发窗口保存的新标题')
  await expect(concurrent.getByText('正在保存', { exact: true })).toBeVisible()
  await expect(concurrent.getByText('已保存', { exact: true })).toBeVisible({ timeout: 25_000 })

  await page.getByLabel('文章标题').fill('当前窗口保留的本地标题')
  await expect(page.getByText('检测到服务端新版本')).toBeVisible({ timeout: 25_000 })
  await expect(page.getByRole('button', { name: '复制本地内容' })).toBeVisible()
  await expect(page.getByRole('button', { name: '放弃本地并加载最新版' })).toBeVisible()
  await expect(page.getByRole('button', { name: '本地内容创建新版本' })).toBeVisible()
})

test('V3 official account list stays minimal and opens the four-pane template editor', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await login(page)
  await page.goto('/official-accounts')

  await expect(page.getByRole('heading', { name: '公众号管理' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '公众号' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '连接状态' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '最近同步' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '操作' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: /账号类型|原始ID|授权能力/ })).toHaveCount(0)

  await page.getByRole('button', { name: '模板管理' }).first().click()
  await expect(page.getByRole('heading', { name: '文章排版设置' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '排版模板' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '文章模块' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /样式$/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: '文章预览' })).toBeVisible()
  await expect(page.getByText('模板管理不受公众号连接状态影响')).toBeVisible()
  await expectNoGlobalOverflow(page, '四栏模板编辑器')
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'test-results/visual/template-editor-1440.png', fullPage: true })
})

test('official-account QR opens WeChat authorization directly without an intermediate button', async ({
  page,
}) => {
  await page.route('**/api/v1/official-accounts/authorize-url', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        authorization_url:
          'https://mp.weixin.qq.com/safe/bindcomponent?component_appid=wx_component_test&pre_auth_code=preauth_test&redirect_uri=https%3A%2F%2Fapi.example.com%2Fcallbacks%2Fv1%2Fwechat%2Fauthorize&action=bindcomponent&no_scan=1#wechat_redirect',
        expires_in: 600,
      }),
    })
  })
  await login(page)
  await page.goto('/official-accounts')
  await page.getByRole('button', { name: '授权新公众号' }).click()

  await expect(page.getByAltText('微信公众号授权二维码')).toBeVisible()
  await expect(page.getByText('扫码后将直接进入微信授权确认')).toBeVisible()
  await expect(page.getByRole('button', { name: '打开授权页面' })).toHaveCount(0)
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 1024, height: 768 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expectNoGlobalOverflow(page, `公众号直接授权弹窗 ${viewport.width}px`)
    await page.screenshot({
      path: `test-results/visual/wechat-direct-authorization-${viewport.width}.png`,
      animations: 'disabled',
    })
  }
})
