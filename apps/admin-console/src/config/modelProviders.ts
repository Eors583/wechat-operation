import type { ModelAdapter, ModelConfiguration } from '@/api/contracts'

export interface ModelPreset {
  id: string
  label: string
  type: ModelConfiguration['model_type']
}

export interface ProviderPreset {
  id: string
  label: string
  baseUrl: string
  adapter: ModelAdapter
  models: ModelPreset[]
}

export const providerPresets: ProviderPreset[] = [
  {
    id: 'manus',
    label: 'Manus',
    baseUrl: 'https://api.manus.ai',
    adapter: 'manus_v2',
    models: [
      { id: 'standard', label: 'Manus Standard', type: 'chat' },
      { id: 'lite', label: 'Manus Lite', type: 'chat' },
      { id: 'max', label: 'Manus Max', type: 'chat' },
    ],
  },
  {
    id: 'openai',
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    adapter: 'openai_responses',
    models: [
      { id: 'gpt-5.6-sol', label: 'GPT-5.6 Sol', type: 'chat' },
      { id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', type: 'chat' },
      { id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', type: 'chat' },
      { id: 'gpt-4.1', label: 'GPT-4.1', type: 'chat' },
      { id: 'gpt-4.1-mini', label: 'GPT-4.1 mini', type: 'chat' },
    ],
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    adapter: 'openai_chat_completions',
    models: [
      { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash', type: 'chat' },
      { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', type: 'chat' },
    ],
  },
  {
    id: 'qwen',
    label: '通义千问',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    adapter: 'openai_chat_completions',
    models: [
      { id: 'qwen3.8-max', label: 'Qwen3.8 Max', type: 'chat' },
      { id: 'qwen3.7-plus', label: 'Qwen3.7 Plus', type: 'chat' },
      { id: 'qwen3.7-flash', label: 'Qwen3.7 Flash', type: 'chat' },
      { id: 'qwen-plus', label: 'Qwen Plus', type: 'chat' },
      { id: 'qwen-max', label: 'Qwen Max', type: 'chat' },
    ],
  },
  {
    id: 'kimi',
    label: 'Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    adapter: 'openai_chat_completions',
    models: [
      { id: 'kimi-k2.6', label: 'Kimi K2.6', type: 'chat' },
      { id: 'kimi-k2.5', label: 'Kimi K2.5', type: 'chat' },
    ],
  },
  {
    id: 'kimi-code',
    label: 'Kimi Code（会员）',
    baseUrl: 'https://api.kimi.com/coding/v1',
    adapter: 'openai_chat_completions',
    models: [
      { id: 'k3', label: 'Kimi K3', type: 'chat' },
      { id: 'k3-256k', label: 'Kimi K3 256K', type: 'chat' },
      { id: 'kimi-for-coding', label: 'Kimi K2.7 Code', type: 'chat' },
      {
        id: 'kimi-for-coding-highspeed',
        label: 'Kimi K2.7 Code HighSpeed',
        type: 'chat',
      },
    ],
  },
  {
    id: 'zhipu',
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    adapter: 'openai_chat_completions',
    models: [{ id: 'glm-5', label: 'GLM-5', type: 'chat' }],
  },
]

export const customProviderId = 'custom'

export function findProviderPreset(model: ModelConfiguration): ProviderPreset | undefined {
  return providerPresets.find(
    (provider) =>
      provider.baseUrl === model.base_url &&
      provider.adapter === model.adapter &&
      provider.models.some((candidate) => candidate.id === model.model_id),
  )
}
