<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const documentType = computed(() => String(route.params.document))
const title = computed(
  () =>
    ({
      terms: '用户协议与版权承诺',
      privacy: '隐私政策与数据保留规则',
      ai: 'AI 内容生成说明',
    })[documentType.value] ?? '合规说明',
)
</script>

<template>
  <q-layout view="hHh lpR fFf" class="legal-layout">
    <q-header bordered class="legal-header"
      ><q-toolbar
        ><q-toolbar-title>微信公众号 AI 运营助手</q-toolbar-title
        ><q-btn flat no-caps label="返回登录" to="/login" /></q-toolbar
    ></q-header>
    <q-page-container>
      <q-page class="legal-page">
        <article class="legal-document surface-card">
          <header>
            <span>更新日期：2026 年 8 月 31 日</span>
            <h1>{{ title }}</h1>
            <p>运营主体及联系方式以本服务备案信息、正式部署页脚和应用商店公示为准。</p>
          </header>

          <template v-if="documentType === 'terms'">
            <section>
              <h2>1. 服务范围</h2>
              <p>
                本服务提供资料管理、AI 辅助创作、文章编辑、排版预览与公众号授权操作。AI
                输出、排版预览及外部服务降级结果均不等于已经在微信平台发布；最终提交前由用户确认目标账号、模板、封面和锁定版本。
              </p>
            </section>
            <section>
              <h2>2. 账号与安全</h2>
              <p>
                用户应妥善保管登录凭据，不得转让账号、绕过权限或上传恶意文件。发现异常授权时应立即断开公众号并退出全部设备。原生端刷新凭据仅保存在系统安全存储，Web
                端刷新会话由 HttpOnly Cookie 管理。
              </p>
            </section>
            <section>
              <h2>3. 内容与版权承诺</h2>
              <p>
                用户确认对输入的文字、文件、图片、音视频、链接和公众号素材拥有合法权利或充分授权；不得生成或发布违法、侵权、虚假、歧视、欺诈或泄露他人隐私的内容。用户须人工核验事实、引用、商标、肖像、音乐、字体及图片许可，并对最终发布内容负责。
              </p>
            </section>
            <section>
              <h2>4. AI 与第三方平台</h2>
              <p>
                AI
                可能产生不准确、遗漏或相似表达。积分扣减、模型状态和外部服务降级会在界面明确展示。公众号草稿、发布及授权能力受微信开放平台规则约束；结果未知时系统会冻结原操作供对账，用户不得通过新操作重复发布。
              </p>
            </section>
            <section>
              <h2>5. 暂停与终止</h2>
              <p>
                对安全事件、滥用、欠费、监管要求或第三方平台限制，服务可限制相关能力并保留必要审计记录。用户可导出需要保留的文章后发起账号注销；注销规则见隐私政策。
              </p>
            </section>
          </template>

          <template v-else-if="documentType === 'privacy'">
            <section>
              <h2>1. 处理的数据</h2>
              <p>
                为提供服务，我们处理账号标识、联系方式、登录设备信息、项目与任务、对话、文章及版本、用户偏好、上传资料及解析结果、公众号授权状态、排版模板、积分与操作审计。参考链接只作为不可信
                URL 字符串进入本轮上下文，不抓取网页正文。
              </p>
            </section>
            <section>
              <h2>2. 处理目的与边界</h2>
              <p>
                数据仅用于身份认证、安全风控、完成用户指令、保存与同步内容、计费对账、故障恢复和履行法定义务。资料、链接和历史偏好只在用户选择的项目、任务及开关范围内进入
                AI 上下文；服务端会冻结实际使用的技能版本和偏好快照以便审计。
              </p>
            </section>
            <section>
              <h2>3. 存储与传输</h2>
              <p>
                生产环境必须使用
                HTTPS。访问令牌和本地恢复命令按账号隔离；退出登录会清除当前账号在设备上的待发送正文、上传恢复信息和文章本地草稿。原生刷新令牌使用
                Windows 安全存储、iOS Keychain 或 Android Keystore，界面代码不能读取。
              </p>
            </section>
            <section>
              <h2>4. 保存期限</h2>
              <p>
                业务内容在账号存续及用户主动删除前保存；已删除内容按系统备份轮转周期清理。安全审计、计费与外部平台对账记录在法律要求或争议处理所需期限内保留。账号注销后，除依法必须保留或为完成争议处理而隔离保存的数据外，个人业务数据将在
                30 日内删除或匿名化。
              </p>
            </section>
            <section>
              <h2>5. 用户权利</h2>
              <p>
                用户可在产品内查看、修改和删除项目、文章、资料、个人技能、模板与写作偏好，并可断开公众号授权。账号注销前应自行保存所需内容；用户可在“个人设置—账号注销”完成密码核验并发起注销，提交后会撤销全部会话和公众号凭据，进入不可恢复的数据清理流程。
              </p>
            </section>
            <section>
              <h2>6. 未成年人及变更</h2>
              <p>
                本服务面向具备完全民事行为能力的内容运营人员。政策发生实质变化时将在生效前以产品内通知或部署方公告提示，不会以静默方式扩大历史数据用途。
              </p>
            </section>
          </template>

          <template v-else>
            <section>
              <h2>1. AI 身份披露</h2>
              <p>
                页面中带有“AI”“生成”或“修改建议”标识的内容由模型辅助产生。模型只提出草稿或局部修改提案，不会在用户确认前自动覆盖文章，也不会把未完成的公众号操作描述为真实成功。
              </p>
            </section>
            <section>
              <h2>2. 人工复核责任</h2>
              <p>
                发布前请核对事实、日期、数据、引用来源、医疗法律金融等高风险表达、广告合规、个人信息与知识产权。不得把
                AI 输出作为专业意见或唯一决策依据。
              </p>
            </section>
            <section>
              <h2>3. 输入注意事项</h2>
              <p>
                不要在提示词、文件名、链接参数或正文中输入密码、访问令牌、API
                Key、身份证号等不必要的敏感信息。系统会拒绝明显带凭据的
                URL，但无法识别所有秘密内容。
              </p>
            </section>
            <section>
              <h2>4. 反馈与可追溯性</h2>
              <p>
                文章版本、AI
                运行、技能版本、偏好快照与最终排版校验和用于恢复和审计。发现不当输出时，请停止发布、保留请求编号，并通过正式部署方公示的支持渠道反馈。
              </p>
            </section>
          </template>

          <footer>
            <router-link to="/legal/terms">用户协议</router-link
            ><router-link to="/legal/privacy">隐私政策</router-link
            ><router-link to="/legal/ai">AI 说明</router-link>
          </footer>
        </article>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<style scoped lang="scss">
.legal-layout {
  min-width: 0;
  background: var(--app-bg-page);
}
.legal-header {
  color: var(--app-text-primary);
  background: var(--app-bg-surface);
}
.legal-page {
  min-width: 0;
  padding: clamp(16px, 4vw, 56px);
}
.legal-document {
  width: min(100%, 920px);
  min-width: 0;
  margin: 0 auto;
  padding: clamp(22px, 5vw, 58px);
}
.legal-document header {
  padding-bottom: 20px;
  border-bottom: 1px solid var(--app-border-default);
}
.legal-document header span {
  color: var(--app-text-secondary);
}
.legal-document h1 {
  margin: 10px 0;
  font-size: clamp(28px, 4vw, 42px);
  overflow-wrap: anywhere;
}
.legal-document h2 {
  margin: 28px 0 8px;
  font-size: 20px;
  overflow-wrap: anywhere;
}
.legal-document p {
  margin: 0;
  color: var(--app-text-secondary);
  line-height: 1.9;
  overflow-wrap: anywhere;
}
.legal-document footer {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 36px;
  padding-top: 20px;
  border-top: 1px solid var(--app-border-default);
}
</style>
