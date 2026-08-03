export interface ModelOption {
  name: string
  id: string
}

export interface ModelGroup {
  label: string
  models: readonly ModelOption[]
}

export const MODEL_GROUPS: readonly ModelGroup[] = [
  {
    label: 'OpenAI · GPT',
    models: [
      { name: 'GPT 5.6 Sol', id: 'gpt-5.6-sol' },
      { name: 'GPT 5.6 Terra', id: 'gpt-5.6-terra' },
      { name: 'GPT 5.6 Luna', id: 'gpt-5.6-luna' },
      { name: 'GPT 5.5', id: 'gpt-5.5' },
      { name: 'GPT 5.5 Pro', id: 'gpt-5.5-pro' },
      { name: 'GPT 5.4', id: 'gpt-5.4' },
      { name: 'GPT 5.4 Pro', id: 'gpt-5.4-pro' },
      { name: 'GPT 5.4 Mini', id: 'gpt-5.4-mini' },
      { name: 'GPT 5.4 Nano', id: 'gpt-5.4-nano' },
      { name: 'GPT 5.3 Codex', id: 'gpt-5.3-codex' },
      { name: 'GPT 5.3 Codex Spark', id: 'gpt-5.3-codex-spark' },
      { name: 'GPT 5.2', id: 'gpt-5.2' },
      { name: 'GPT 5.2 Codex', id: 'gpt-5.2-codex' },
      { name: 'GPT 5.1', id: 'gpt-5.1' },
      { name: 'GPT 5.1 Codex', id: 'gpt-5.1-codex' },
      { name: 'GPT 5.1 Codex Max', id: 'gpt-5.1-codex-max' },
      { name: 'GPT 5.1 Codex Mini', id: 'gpt-5.1-codex-mini' },
      { name: 'GPT 5', id: 'gpt-5' },
      { name: 'GPT 5 Codex', id: 'gpt-5-codex' },
      { name: 'GPT 5 Nano', id: 'gpt-5-nano' },
    ],
  },
  {
    label: 'Anthropic · Claude',
    models: [
      { name: 'Claude Fable 5', id: 'claude-fable-5' },
      { name: 'Claude Opus 5', id: 'claude-opus-5' },
      { name: 'Claude Opus 4.8', id: 'claude-opus-4-8' },
      { name: 'Claude Opus 4.7', id: 'claude-opus-4-7' },
      { name: 'Claude Opus 4.6', id: 'claude-opus-4-6' },
      { name: 'Claude Opus 4.5', id: 'claude-opus-4-5' },
      { name: 'Claude Sonnet 5', id: 'claude-sonnet-5' },
      { name: 'Claude Sonnet 4.6', id: 'claude-sonnet-4-6' },
      { name: 'Claude Sonnet 4.5', id: 'claude-sonnet-4-5' },
      { name: 'Claude Haiku 4.5', id: 'claude-haiku-4-5' },
    ],
  },
  {
    label: 'Google · Gemini',
    models: [
      { name: 'Gemini 3.6 Flash', id: 'gemini-3.6-flash' },
      { name: 'Gemini 3.5 Flash', id: 'gemini-3.5-flash' },
      { name: 'Gemini 3.5 Flash Lite', id: 'gemini-3.5-flash-lite' },
      { name: 'Gemini 3.1 Pro', id: 'gemini-3.1-pro' },
      { name: 'Gemini 3 Flash', id: 'gemini-3-flash' },
    ],
  },
  {
    label: 'xAI · Grok',
    models: [
      { name: 'Grok 4.5', id: 'grok-4.5' },
      { name: 'Grok Build 0.1', id: 'grok-build-0.1' },
    ],
  },
  {
    label: 'Qwen',
    models: [
      { name: 'Qwen3.7 Max', id: 'qwen3.7-max' },
      { name: 'Qwen3.7 Plus', id: 'qwen3.7-plus' },
      { name: 'Qwen3.6 Plus', id: 'qwen3.6-plus' },
      { name: 'Qwen3.5 Plus', id: 'qwen3.5-plus' },
    ],
  },
  {
    label: 'DeepSeek',
    models: [
      { name: 'DeepSeek V4 Pro', id: 'deepseek-v4-pro' },
      { name: 'DeepSeek V4 Flash', id: 'deepseek-v4-flash' },
    ],
  },
  {
    label: 'MiniMax',
    models: [
      { name: 'MiniMax M3', id: 'minimax-m3' },
      { name: 'MiniMax M2.7', id: 'minimax-m2.7' },
      { name: 'MiniMax M2.5', id: 'minimax-m2.5' },
    ],
  },
  {
    label: 'GLM',
    models: [
      { name: 'GLM 5.2', id: 'glm-5.2' },
      { name: 'GLM 5.1', id: 'glm-5.1' },
      { name: 'GLM 5', id: 'glm-5' },
    ],
  },
  {
    label: 'Kimi',
    models: [
      { name: 'Kimi K2.5', id: 'kimi-k2.5' },
      { name: 'Kimi K2.6', id: 'kimi-k2.6' },
      { name: 'Kimi K2.7 Code', id: 'kimi-k2.7-code' },
      { name: 'Kimi K3', id: 'kimi-k3' },
    ],
  },
  {
    label: '其他',
    models: [
      { name: 'Big Pickle', id: 'big-pickle' },
    ],
  },
  {
    label: '免费模型',
    models: [
      { name: 'MiMo-V2.5 Free', id: 'mimo-v2.5-free' },
      { name: 'Laguna S 2.1 Free', id: 'laguna-s-2.1-free' },
      { name: 'Ling-3.0-flash Free', id: 'ling-3.0-flash-free' },
      { name: 'North Mini Code Free', id: 'north-mini-code-free' },
      { name: 'Nemotron 3 Ultra Free', id: 'nemotron-3-ultra-free' },
      { name: 'DeepSeek V4 Flash Free', id: 'deepseek-v4-flash-free' },
    ],
  },
]

export const MODEL_IDS = new Set(
  MODEL_GROUPS.flatMap((group) => group.models.map((model) => model.id)),
)

export const MODEL_COUNT = MODEL_IDS.size
