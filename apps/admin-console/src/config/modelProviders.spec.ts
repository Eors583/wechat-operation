import { describe, expect, it } from 'vitest'

import { providerPresets } from './modelProviders'

describe('model provider presets', () => {
  it('keeps the provider model ids and adapters aligned with the supported APIs', () => {
    expect(
      Object.fromEntries(
        providerPresets.map(({ id, adapter, models }) => [
          id,
          { adapter, models: models.map((model) => model.id) },
        ]),
      ),
    ).toEqual({
      manus: { adapter: 'manus_v2', models: ['standard', 'lite', 'max'] },
      openai: {
        adapter: 'openai_responses',
        models: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-4.1', 'gpt-4.1-mini'],
      },
      deepseek: {
        adapter: 'openai_chat_completions',
        models: ['deepseek-v4-flash', 'deepseek-v4-pro'],
      },
      qwen: {
        adapter: 'openai_chat_completions',
        models: ['qwen3.8-max', 'qwen3.7-plus', 'qwen3.7-flash', 'qwen-plus', 'qwen-max'],
      },
      kimi: { adapter: 'openai_chat_completions', models: ['kimi-k2.6', 'kimi-k2.5'] },
      'kimi-code': {
        adapter: 'openai_chat_completions',
        models: ['k3', 'k3-256k', 'kimi-for-coding', 'kimi-for-coding-highspeed'],
      },
      zhipu: { adapter: 'openai_chat_completions', models: ['glm-5'] },
    })
  })
})
