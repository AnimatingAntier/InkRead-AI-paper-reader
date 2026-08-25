import { FormEvent, useEffect, useState } from 'react'
import { Check, Eye, EyeOff, LoaderCircle, Settings, X } from 'lucide-react'
import { getSettings, saveSettings } from '../api'
import { MODEL_COUNT, MODEL_GROUPS, MODEL_IDS } from '../modelCatalog'
import type { AppSettings, ProviderCatalogEntry, ProviderModel } from '../types'

interface Props {
  open: boolean
  onClose: () => void
  onSaved?: (settings: AppSettings) => void
}

function SecretLabel({ name, value }: { name: string; value: string }) {
  const masked = /^•+$/.test(value)
  return (
    <span className="settings-field-label">
      <b>{name}</b>
      {value && <small>{masked ? '已保存' : '已输入'} · {Array.from(value).length} 位</small>}
    </span>
  )
}

function isEmptyKey(value: string | undefined, hasKey?: boolean) {
  if (hasKey) return false
  const text = value || ''
  return !text || text.trim() === ''
}

function catalogEntry(settings: AppSettings, providerId: string): ProviderCatalogEntry | undefined {
  return (settings.catalog || []).find((item) => item.id === providerId)
}

export function SettingsModal({ open, onClose, onSaved }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [showKeys, setShowKeys] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setError('')
    void getSettings().then(setSettings).catch((reason) => setError(String(reason)))
  }, [open])

  if (!open) return null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!settings) return
    setSaving(true)
    setSaved(false)
    setError('')
    try {
      const updated = await saveSettings(settings)
      setSettings(updated)
      onSaved?.(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 1600)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const switchProvider = (id: string) => {
    if (!settings) return
    const slot = settings.providers?.[id]
    const entry = catalogEntry(settings, id)
    setSettings({
      ...settings,
      provider: id,
      api_key: slot?.api_key || '',
      model: slot?.model || '',
      base_url: entry?.needs_base_url
        ? (slot?.base_url || '')
        : (entry?.base_url || slot?.base_url || ''),
    })
  }

  const selected = settings ? catalogEntry(settings, settings.provider) : undefined
  const slot = settings ? settings.providers?.[settings.provider] : undefined
  const cachedModels: ProviderModel[] = slot?.models?.length ? slot.models : []
  const usingCache = cachedModels.length > 0
  const fallbackIds = MODEL_IDS
  const cachedIds = new Set(cachedModels.map((model) => model.id))
  const knownIds = usingCache ? cachedIds : fallbackIds
  const showBaseUrl = Boolean(selected?.needs_base_url || settings?.provider === 'openai_compatible')
  const showKeyHint = Boolean(
    settings && selected && selected.key_url && isEmptyKey(settings.api_key, slot?.has_key),
  )

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="settings-modal" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <div>
            <Settings size={18} />
            <span>
              <b>AI、检索与翻译设置</b>
              <small>密钥仅保存在本机设置目录</small>
            </span>
          </div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </header>
        {!settings ? (
          <div className="modal-loading"><LoaderCircle className="spin" /> 正在读取设置…</div>
        ) : (
          <div className="settings-body">
            <label>
              <span>供应商</span>
              <select
                value={settings.provider}
                onChange={(event) => switchProvider(event.target.value)}
              >
                {(settings.catalog && settings.catalog.length > 0
                  ? settings.catalog
                  : [
                      { id: 'openrouter', name: 'OpenRouter' },
                      { id: 'openai_compatible', name: '自定义 OpenAI 兼容' },
                      { id: 'opencode_zen', name: 'OpenCode Zen' },
                    ]
                ).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            {showBaseUrl && (
              <label>
                <span>Base URL</span>
                <input
                  value={settings.base_url}
                  onChange={(event) => setSettings({ ...settings, base_url: event.target.value })}
                  placeholder="https://api.example.com/v1"
                />
              </label>
            )}
            <label>
              <span>模型</span>
              <div className="model-select-wrap">
                <select
                  aria-label="选择 AI 模型"
                  value={settings.model}
                  onChange={(event) => setSettings({ ...settings, model: event.target.value })}
                >
                  {settings.model && !knownIds.has(settings.model) && (
                    <option value={settings.model}>当前自定义模型 · {settings.model}</option>
                  )}
                  {usingCache
                    ? cachedModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name} · {model.id}
                        </option>
                      ))
                    : MODEL_GROUPS.map((group) => (
                        <optgroup key={group.label} label={group.label}>
                          {group.models.map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.name} · {model.id}
                            </option>
                          ))}
                        </optgroup>
                      ))}
                </select>
                <small>
                  {usingCache
                    ? `共 ${cachedModels.length} 个模型 · 启动时会自动更新已配置供应商的模型列表`
                    : `共 ${MODEL_COUNT} 个内置模型 · 启动时会自动更新已配置供应商的模型列表`}
                </small>
              </div>
            </label>
            <label>
              <SecretLabel name="AI API Key" value={settings.api_key} />
              <div>
                <div className="secret-field">
                  <input
                    type={showKeys ? 'text' : 'password'}
                    value={settings.api_key}
                    onChange={(event) => setSettings({ ...settings, api_key: event.target.value })}
                    placeholder="粘贴该供应商的 API Key"
                  />
                  <button type="button" onClick={() => setShowKeys((value) => !value)}>
                    {showKeys ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {showKeyHint && selected?.key_url && (
                  <p className="settings-key-hint">
                    还没有填写 API Key。可在 {selected.name} 申请：
                    {' '}
                    <a href={selected.key_url} target="_blank" rel="noreferrer">
                      {selected.key_url}
                    </a>
                  </p>
                )}
              </div>
            </label>
            <div className="settings-divider" />
            <div className="settings-subhead">
              <b>论文批注卡</b>
              <small>鼠标移开后的透明程度；移入或编辑时始终恢复清晰</small>
            </div>
            <label>
              <span>闲置透明度</span>
              <div className="comment-opacity-control">
                <input
                  type="range"
                  min="0.15"
                  max="1"
                  step="0.05"
                  value={settings.comment_idle_opacity}
                  aria-label="批注卡闲置透明度"
                  style={
                    {
                      '--comment-opacity-position': `${
                        ((settings.comment_idle_opacity - 0.15) / 0.85) * 100
                      }%`,
                    } as React.CSSProperties
                  }
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      comment_idle_opacity: Number(event.target.value),
                    })
                  }
                />
                <output>{Math.round(settings.comment_idle_opacity * 100)}%</output>
              </div>
            </label>
            <div className="settings-divider" />
            <label>
              <SecretLabel name="SerpApi Key" value={settings.serpapi_key} />
              <div className="secret-field">
                <input
                  type={showKeys ? 'text' : 'password'}
                  value={settings.serpapi_key}
                  onChange={(event) => setSettings({ ...settings, serpapi_key: event.target.value })}
                  placeholder="用于 Google Scholar 检索"
                />
                <button type="button" onClick={() => setShowKeys((value) => !value)}>
                  {showKeys ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            <div className="settings-divider" />
            <div className="settings-subhead">
              <b>百度优先 · 本地后备</b>
              <small>启动时检测百度；额度耗尽或不可用时自动改用本地英译中</small>
            </div>
            <label>
              <span>百度翻译 APP ID</span>
              <input
                value={settings.baidu_translate_appid}
                onChange={(event) =>
                  setSettings({ ...settings, baidu_translate_appid: event.target.value })
                }
                placeholder="在百度翻译开放平台的开发者信息中查看"
              />
            </label>
            <label>
              <SecretLabel name="百度翻译 API Key" value={settings.baidu_translate_api_key} />
              <div className="secret-field">
                <input
                  type={showKeys ? 'text' : 'password'}
                  value={settings.baidu_translate_api_key}
                  onChange={(event) =>
                    setSettings({ ...settings, baidu_translate_api_key: event.target.value })
                  }
                  placeholder="SA1b_…"
                />
                <button type="button" onClick={() => setShowKeys((value) => !value)}>
                  {showKeys ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>
            <div className="settings-divider" />
            <label className="toggle-row">
              <span>
                <b>允许学术网络检索</b>
                <small>仅在用户要求、问题具有当下意图或原文覆盖不足时触发</small>
              </span>
              <input
                type="checkbox"
                checked={settings.web_search}
                onChange={(event) => setSettings({ ...settings, web_search: event.target.checked })}
              />
            </label>
            <label className="toggle-row">
              <span>
                <b>事实校验 Agent</b>
                <small>检查来源编号、引用覆盖率与回答—原文语义重合</small>
              </span>
              <input
                type="checkbox"
                checked={settings.fact_check}
                onChange={(event) => setSettings({ ...settings, fact_check: event.target.checked })}
              />
            </label>
          </div>
        )}
        <footer>
          {error && <span className="settings-error">{error}</span>}
          <button type="button" className="secondary" onClick={onClose}>取消</button>
          <button type="submit" disabled={!settings || saving}>
            {saving ? <LoaderCircle size={15} className="spin" /> : saved ? <Check size={15} /> : null}
            {saved ? '已保存' : '保存设置'}
          </button>
        </footer>
      </form>
    </div>
  )
}
