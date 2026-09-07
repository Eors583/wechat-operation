<script setup lang="ts">
defineProps<{ title: string; subtitle: string }>()
</script>

<template>
  <main class="auth-shell">
    <section class="auth-shell__story" aria-label="产品介绍">
      <router-link class="auth-shell__brand" to="/login"
        ><q-icon name="auto_awesome" />微信公众号运营系统</router-link
      >
      <div class="auth-shell__hero">
        <h1>让公众号内容创作<br /><span>更简单、更有序</span></h1>
        <p>从资料整理、文章生成到草稿箱与发布，在同一个工作台完成。</p>
        <ul>
          <li>
            <q-icon name="folder_open" /><span
              ><strong>按项目沉淀创作资料</strong
              ><small>资料、会话和文章统一归档，来源清晰可追溯。</small></span
            >
          </li>
          <li>
            <q-icon name="auto_awesome" /><span
              ><strong>与内容助手协作创作</strong
              ><small>通过自然对话完成素材整理、文章生成和内容调整。</small></span
            >
          </li>
          <li>
            <q-icon name="description" /><span
              ><strong>统一管理草稿与发布</strong
              ><small>确认后的文章可写入公众号草稿箱或完成发布。</small></span
            >
          </li>
        </ul>
      </div>
      <small class="auth-shell__copyright">© 2026 微信公众号运营系统</small>
    </section>
    <section class="auth-shell__form">
      <div class="auth-shell__panel">
        <div class="auth-shell__mobile-brand"><q-icon name="auto_awesome" />公众号运营系统</div>
        <h2>{{ title }}</h2>
        <p>{{ subtitle }}</p>
        <slot />
      </div>
    </section>
  </main>
</template>

<style scoped lang="scss">
.auth-shell {
  display: grid;
  grid-template-columns: minmax(460px, 1fr) minmax(500px, 1fr);
  min-width: 0;
  min-height: 100dvh;
  background: var(--app-bg-surface);

  &__story,
  &__form {
    min-width: 0;
    padding: clamp(36px, 5vw, 76px);
  }

  &__story {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    background:
      radial-gradient(
        circle at 15% 18%,
        color-mix(in srgb, var(--app-action-primary) 10%, transparent),
        transparent 36%
      ),
      linear-gradient(145deg, #f9fcfa, var(--app-bg-surface));
    border-right: 1px solid var(--app-border-default);
  }

  &__brand,
  &__mobile-brand {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    color: var(--app-text-primary);
    font-size: 22px;
    font-weight: 700;
    text-decoration: none;

    .q-icon {
      color: var(--app-action-primary);
      font-size: 30px;
    }
  }

  &__hero {
    align-self: center;
    width: min(100%, 620px);

    h1 {
      margin: 0;
      font-size: clamp(40px, 3.8vw, 58px);
      font-weight: 600;
      line-height: 1.22;
      letter-spacing: -0.03em;
      overflow-wrap: anywhere;
      span {
        color: var(--app-action-primary);
      }
    }

    > p {
      max-width: 540px;
      margin: 26px 0 38px;
      color: var(--app-text-secondary);
      font-size: 19px;
      line-height: 1.7;
    }

    ul {
      display: grid;
      gap: 24px;
      margin: 0;
      padding: 0;
      list-style: none;
    }
    li {
      display: grid;
      grid-template-columns: 58px minmax(0, 1fr);
      align-items: center;
      gap: 18px;
      min-width: 0;
    }
    li > .q-icon {
      display: grid;
      place-items: center;
      width: 58px;
      height: 58px;
      color: var(--app-action-primary);
      font-size: 29px;
      background: var(--app-action-soft);
      border-radius: 14px;
    }
    li span {
      display: grid;
      min-width: 0;
    }
    li strong {
      font-size: 17px;
      overflow-wrap: anywhere;
    }
    li small {
      margin-top: 3px;
      color: var(--app-text-secondary);
      overflow-wrap: anywhere;
    }
  }

  &__copyright {
    color: var(--app-text-secondary);
  }

  &__form {
    display: grid;
    place-items: center;
  }

  &__panel {
    width: min(100%, 576px);
    min-width: 0;

    h2 {
      margin: 0;
      font-size: clamp(34px, 3.5vw, 42px);
      line-height: 1.25;
      letter-spacing: -0.025em;
    }
    > p {
      margin: 10px 0 34px;
      color: var(--app-text-secondary);
      font-size: 17px;
    }
  }

  &__mobile-brand {
    display: none;
    margin-bottom: 30px;
  }
}

@media (max-width: 900px) {
  .auth-shell {
    display: block;
    background: var(--app-bg-page);

    &__story {
      display: none;
    }
    &__form {
      min-height: 100dvh;
      padding: max(24px, env(safe-area-inset-top)) 18px max(24px, env(safe-area-inset-bottom));
    }
    &__panel {
      padding: 24px;
      background: var(--app-bg-surface);
      border: 1px solid var(--app-border-default);
      border-radius: 12px;
      box-shadow: var(--app-shadow-sm);
    }
    &__mobile-brand {
      display: inline-flex;
    }
  }
}
</style>
