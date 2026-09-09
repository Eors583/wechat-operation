<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Article, LayoutTemplate, OfficialAccount } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'
import AppDialog from '@/components/base/AppDialog.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    article: Article
    account: OfficialAccount
    template: LayoutTemplate
    action: 'draft' | 'publish'
    renderHtml?: string
    coverName?: string
    loading?: boolean
  }>(),
  { loading: false },
)

const hasCapability = computed(() =>
  props.account.capabilities.includes(props.action === 'publish' ? 'publish' : 'draft'),
)

const author = ref('')
const region = ref('')
const original = ref(false)
const previewTime = ref('')
watch(() => props.modelValue, (open) => {
  if (!open) return
  const now = new Date()
  previewTime.value = `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}, { immediate: true })

const readingHtml = computed(() => {
  if (!props.renderHtml) return ''
  const doc = new DOMParser().parseFromString(props.renderHtml, 'text/html')
  const header = doc.createElement('header')
  header.id = 'wechat-reading-header'
  const title = doc.createElement('h1')
  title.textContent = props.article.title
  header.append(title)
  const metadata = doc.createElement('div')
  metadata.className = 'wechat-reading-metadata'
  for (const [text, className] of [
    [original.value ? '原创' : '', 'original'],
    [author.value, 'author'],
    [props.account.name, 'account'],
    [previewTime.value, 'time'],
    [region.value, 'region'],
  ]) {
    if (!text) continue
    const item = doc.createElement('span')
    item.className = className ?? ''
    item.textContent = text
    metadata.append(item)
  }
  header.append(metadata)
  const main = doc.createElement('main')
  main.id = 'wechat-reading-main'
  main.append(header, ...Array.from(doc.body.childNodes))
  doc.body.append(main)
  const footer = doc.createElement('footer')
  footer.id = 'wechat-reading-footer'
  const identity = doc.createElement('div')
  identity.className = 'identity'
  const avatar = doc.createElement('span')
  avatar.className = 'avatar'
  avatar.textContent = props.account.avatarText || props.account.name.slice(0, 1)
  const name = doc.createElement('span')
  name.textContent = props.account.name
  identity.append(avatar, name)
  const actions = doc.createElement('div')
  actions.className = 'actions'
  const icons = [
    ['赞', 'M7 10v11H3V10h4Zm0 0 5-7c2 0 2 2 1 6h6c2 0 2 2 1 4l-2 8H7'],
    ['分享', 'M14 4 22 11 14 18v-5C7 13 4 16 2 20c0-9 4-13 12-13V4Z'],
    ['推荐', 'M12 21 3 12C-3 5 7-1 12 6c5-7 15-1 9 6l-9 9Z'],
    ['写留言', 'M14 18H8l-4 4v-4H2V3h20v11M19 16v7m-3-3h6'],
  ]
  for (const [label, path] of icons) {
    const button = doc.createElement('button')
    button.type = 'button'
    button.setAttribute('aria-disabled', 'true')
    button.title = '仅展示微信阅读页效果，不执行真实操作'
    const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('viewBox', '0 0 24 24')
    svg.setAttribute('aria-hidden', 'true')
    const line = doc.createElementNS('http://www.w3.org/2000/svg', 'path')
    line.setAttribute('d', path ?? '')
    svg.append(line)
    button.append(svg, doc.createTextNode(label ?? ''))
    actions.append(button)
  }
  footer.append(identity, actions)
  doc.body.append(footer)
  const style = doc.createElement('style')
  style.textContent = `
    :root { color-scheme: light; --wx-paper: #fff; --wx-text: #191919; --wx-muted: #b2b2b2; --wx-link: #576b95; --wx-rule: #ededed; --wx-width: 677px; }
    html { background: var(--wx-paper); }
    body { margin: 0 !important; padding: 0 !important; max-width: none !important; background: var(--wx-paper) !important; color: var(--wx-text); font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', sans-serif; }
    #wechat-reading-main { box-sizing: border-box; width: 100%; max-width: calc(var(--wx-width) + 48px); margin: 0 auto; padding: 32px 24px 112px; overflow-wrap: anywhere; }
    #wechat-reading-header { margin: 0 0 36px; text-align: left; }
    #wechat-reading-header h1 { margin: 0 0 16px; padding: 0; border: 0; font-size: 22px; font-weight: 600; line-height: 1.4; color: var(--wx-text); }
    .wechat-reading-metadata { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 15px; line-height: 1.5; color: var(--wx-muted); }
    .wechat-reading-metadata .account { color: var(--wx-link); }
    .wechat-reading-metadata .original { padding: 0 3px; background: var(--wx-rule); font-size: 12px; }
    #wechat-reading-main img, #wechat-reading-main video { max-width: 100%; height: auto; }
    #wechat-reading-footer { position: fixed; bottom: 0; left: 0; right: 0; display: flex; align-items: center; justify-content: space-between; gap: 16px; box-sizing: border-box; padding: 18px max(24px, calc((100% - var(--wx-width)) / 2)); padding-bottom: max(18px, env(safe-area-inset-bottom)); background: var(--wx-paper); border-top: 1px solid var(--wx-rule); color: var(--wx-text); font-size: 14px; }
    #wechat-reading-footer .identity { display: flex; align-items: center; gap: 8px; min-width: 0; }
    #wechat-reading-footer .identity > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #wechat-reading-footer .avatar { display: grid; place-items: center; flex: 0 0 30px; height: 30px; border-radius: 50%; background: var(--wx-rule); color: var(--wx-link); font-size: 12px; overflow: hidden; }
    #wechat-reading-footer .actions { display: flex; gap: 18px; flex-shrink: 0; }
    #wechat-reading-footer button { display: flex; align-items: center; gap: 5px; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; cursor: default; }
    #wechat-reading-footer svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.25; stroke-linejoin: round; stroke-linecap: round; }
    @media (max-width: 520px) { #wechat-reading-main { padding: 24px 16px 132px; } #wechat-reading-footer { flex-wrap: wrap; padding: 12px 16px; gap: 12px; } #wechat-reading-footer .actions { width: 100%; justify-content: space-between; gap: 8px; } }
  `
  doc.head.append(style)
  return `<!doctype html>${doc.documentElement.outerHTML}`
})

defineEmits<{ 'update:modelValue': [value: boolean]; confirm: [] }>()
</script>

<template>
  <AppDialog
    :model-value="modelValue"
    :title="action === 'publish' ? '发布前最终预览' : '公众号草稿最终预览'"
    width="1480px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="final-preview">
      <section class="final-preview__canvas">
        <div class="final-preview__label">微信公众号最终效果 · 只读</div>
        <div class="final-preview__phone">
          <iframe
            v-if="renderHtml"
            :srcdoc="readingHtml"
            sandbox=""
            title="微信公众号服务端锁定排版预览"
          />
          <q-banner v-else rounded class="final-preview__warning"
            >服务端排版版本不可用，不能确认提交。</q-banner
          >
        </div>
      </section>
      <aside class="final-preview__meta">
        <h3>{{ action === 'publish' ? '发布信息' : '草稿信息' }}</h3>
        <dl>
          <div>
            <dt>目标公众号</dt>
            <dd>{{ account.name }}</dd>
          </div>
          <div>
            <dt>使用模板</dt>
            <dd>{{ template.name }}</dd>
          </div>
          <div>
            <dt>文章标题</dt>
            <dd>{{ article.title }}</dd>
          </div>
          <div>
            <dt>封面</dt>
            <dd :class="{ positive: coverName || article.coverState === 'ready' }">
              {{ coverName || (article.coverState === 'ready' ? '已设置' : '未设置') }}
            </dd>
          </div>
          <div>
            <dt>排版版本</dt>
            <dd class="positive">已锁定</dd>
          </div>
        </dl>
        <div class="final-preview__display-settings">
          <p>阅读页展示信息（仅预览，不写入草稿）</p>
          <q-input v-model="author" outlined dense label="作者" placeholder="未设置" />
          <q-input v-model="previewTime" outlined dense label="预览发布时间" />
          <q-input v-model="region" outlined dense label="发布地区" placeholder="未设置" />
          <q-checkbox v-model="original" dense label="展示原创标记" />
          <p>实际发布时间、地区和原创状态以微信发布结果为准。底栏仅展示外观。</p>
        </div>
        <q-banner v-if="account.status !== 'connected'" rounded class="final-preview__warning">
          公众号授权已由管理员解除，请先重新扫码绑定。排版内容不会丢失。
        </q-banner>
        <q-banner v-else-if="!hasCapability" rounded class="final-preview__warning">
          该公众号没有{{
            action === 'publish' ? '发布文章' : '写入草稿箱'
          }}的能力，无法确认本次操作。
        </q-banner>
      </aside>
    </div>
    <template #actions>
      <span class="final-preview__hint">{{
        action === 'publish'
          ? '确认后将提交至微信发布，结果会先显示为处理中。'
          : '确认后将使用当前锁定排版写入公众号草稿箱。'
      }}</span>
      <AppButton variant="outline" label="返回修改" @click="$emit('update:modelValue', false)" />
      <AppButton
        :label="action === 'publish' ? '确认发布' : '确认存入草稿箱'"
        :loading="loading"
        :disabled="account.status !== 'connected' || !hasCapability || !renderHtml"
        @click="$emit('confirm')"
      />
    </template>
  </AppDialog>
</template>

<style scoped lang="scss">
.final-preview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
  min-width: 0;
  min-height: 0;
  height: min(74vh, 820px);

  &__canvas {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    padding: 20px;
    background: var(--app-bg-subtle);
  }

  &__label {
    margin-bottom: 14px;
    color: var(--app-text-secondary);
    text-align: center;
  }

  &__phone {
    flex: 1;
    min-height: 0;
    width: min(100%, 760px);
    min-width: 0;
    margin-inline: auto;
    overflow: clip;
    background: var(--app-bg-surface);
    border: 1px solid var(--app-border-default);
    border-radius: 14px;
    box-shadow: var(--app-shadow-sm);

    iframe {
      display: block;
      width: 100%;
      height: 100%;
      border: 0;
    }
  }

  &__meta {
    min-width: 0;
    padding: 24px;
    overflow-y: auto;
    border-left: 1px solid var(--app-border-default);

    h3 {
      margin: 0 0 18px;
      font-size: 22px;
      line-height: 1.4;
    }

    dl {
      margin: 0;
    }

    dl > div {
      display: grid;
      grid-template-columns: 96px minmax(0, 1fr);
      gap: 12px;
      padding: 14px 0;
      border-bottom: 1px solid var(--app-border-default);
    }

    dt {
      color: var(--app-text-secondary);
    }
    dd {
      min-width: 0;
      margin: 0;
      overflow-wrap: anywhere;
    }
  }

  &__warning {
    margin-top: 20px;
    color: var(--app-warning);
    background: color-mix(in srgb, var(--app-warning) 10%, var(--app-bg-surface));
    overflow-wrap: anywhere;
  }

  &__display-settings {
    display: grid;
    gap: 12px;
    margin-top: 20px;
    min-width: 0;

    p {
      margin: 0;
      color: var(--app-text-secondary);
      font-size: 12px;
      line-height: 1.6;
    }
  }

  &__hint {
    margin-right: auto;
    color: var(--app-text-secondary);
    overflow-wrap: anywhere;
  }
}

.positive {
  color: var(--app-action-primary);
}

@media (max-width: 767px) {
  .final-preview {
    display: block;
    height: auto;

    &__canvas {
      height: 68dvh;
    }
    &__meta {
      border-top: 1px solid var(--app-border-default);
      border-left: 0;
    }
    &__hint {
      width: 100%;
      margin-bottom: 8px;
    }
  }
}
</style>
