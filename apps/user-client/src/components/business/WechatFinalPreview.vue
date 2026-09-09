<script setup lang="ts">
import { computed } from 'vue'
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
            :srcdoc="renderHtml"
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
    min-width: 0;
    min-height: 0;
    padding: 20px;
    overflow-y: auto;
    background: var(--app-bg-subtle);
  }

  &__label {
    margin-bottom: 14px;
    color: var(--app-text-secondary);
    text-align: center;
  }

  &__phone {
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
      min-height: min(68vh, 760px);
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
      min-height: 58vh;
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
