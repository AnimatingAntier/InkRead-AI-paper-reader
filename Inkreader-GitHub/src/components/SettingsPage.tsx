import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  Globe,
  Highlighter,
  KeyRound,
  Languages,
  LoaderCircle,
  PlugZap,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import {
  getProviders,
  getSettings,
  getTranslationStatus,
  listAiModels,
  saveSettings,
  testAiConnection,
} from '../api'
import type {
  AiTestResult,
  AppSettings,
  ProviderInfo,
  ProviderModel,
  TranslationStatus,
} from '../types'

interface Props {
  open: boolean
  onClose: () => void
  onSaved?: (settings: AppSettings) => void
}

type Tab = 'ai' | 'search' | 'translation' | 'reading'

const TABS: { id: Tab; label: string; hint: string; icon: typeof Sparkles }[] = [
  { id: 'ai', label: 'AI 模型', hint: '供应商 · 密钥 · 模型', icon: Sparkles },
  { id: 'search', label: '学术检索', hint: '联网检索与事实校验', icon: Globe },
  { id: 'translation', label: '翻译', hint: '百度翻译与本地模型', icon: Languages },
  { id: 'reading', label: '阅读与批注', hint: '批注卡外观', icon: Highlighter },
]

const REGION_LABEL: Record<ProviderInfo['region'], string> = {
  global: '国际',
  cn: '国内',
  local: '本地',
}

/** Serialise settings for dirty-checking; the model cache is backend-owned and must not count as an edit. */
function comparable(settings: AppSettings): string {
  const { model_cache: _cache, ...rest } = settings
  return JSON.stringify(rest)
}

function formatFetchedAt(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000)
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return date.toDateString() === new Date().toDateString()
    ? `今天 ${time}`
    : `${date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })} ${time}`
}

const SERPAPI_URL = 'https://serpapi.com/manage-api-key'
const BAIDU_URL = 'https://fanyi-api.baidu.com/manage/developer'

const isMasked = (value: string) => /^•+$/.test(value)

function SecretInput({
  value,
  onChange,
  placeholder,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
}) {
  const [show, setShow] = useState(false)
  const masked = isMasked(value)
  return (
    <div className="sp-secret">
      <input
        type={show && !masked ? 'text' : 'password'}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={(event) => {
          // A masked value is only a placeholder for the stored secret; typing replaces it.
          if (masked) event.target.select()
        }}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
      />
      <span className="sp-secret-state">
        {value ? (masked ? `已保存 · ${Array.from(value).length} 位` : `已输入 · ${value.length} 位`) : '未填写'}
      </span>
      <button
        type="button"
        title={show ? '隐藏' : '显示'}
        onClick={() => setShow((current) => !current)}
        disabled={masked}
      >
        {show ? <EyeOff size={15} /> : <Eye size={15} />}
      </button>
    </div>
  )
}

function Toggle({
  checked,
  onChange,
  title,
  hint,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  title: string
  hint: string
}) {
  return (
    <label className="sp-toggle">
      <span>
        <b>{title}</b>
        <small>{hint}</small>
      </span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  )
}

export function SettingsPage({ open, onClose, onSaved }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  // False until this open's fresh settings arrive, so stale state from a previous visit is never acted on.
  const [ready, setReady] = useState(false)
  const [snapshot, setSnapshot] = useState('')
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [tab, setTab] = useState<Tab>('ai')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [confirmDiscard, setConfirmDiscard] = useState(false)

  const [modelQuery, setModelQuery] = useState('')
  const [remoteModels, setRemoteModels] = useState<ProviderModel[] | null>(null)
  const [remoteFetchedAt, setRemoteFetchedAt] = useState<number | null>(null)
  // 'cache' = restored from the last visit and possibly stale; 'live' = fetched just now.
  const [remoteSource, setRemoteSource] = useState<'cache' | 'live' | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelsError, setModelsError] = useState('')
  const [autoRefreshFailed, setAutoRefreshFailed] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<AiTestResult | null>(null)
  const [translationStatus, setTranslationStatus] = useState<TranslationStatus | null>(null)
  const [checkingTranslation, setCheckingTranslation] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const modelsAbortRef = useRef<AbortController | null>(null)
  const settingsRef = useRef<AppSettings | null>(null)
  settingsRef.current = settings

  useEffect(() => {
    if (!open) return
    setError('')
    setTestResult(null)
    setRemoteModels(null)
    setRemoteFetchedAt(null)
    setRemoteSource(null)
    setModelsError('')
    setAutoRefreshFailed(false)
    setModelQuery('')
    setConfirmDiscard(false)
    setReady(false)
    void Promise.all([getSettings(), getProviders()])
      .then(([loaded, catalog]) => {
        setSettings(loaded)
        setSnapshot(comparable(loaded))
        setProviders(catalog.providers)
        setReady(true)
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
    void getTranslationStatus().then(setTranslationStatus).catch(() => undefined)
    return () => {
      abortRef.current?.abort()
      modelsAbortRef.current?.abort()
    }
  }, [open])

  const dirty = settings !== null && comparable(settings) !== snapshot

  const requestClose = useCallback(() => {
    if (dirty) {
      setConfirmDiscard(true)
      return
    }
    onClose()
  }, [dirty, onClose])

  useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopImmediatePropagation()
        if (confirmDiscard) setConfirmDiscard(false)
        else requestClose()
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void submit()
      }
    }
    window.addEventListener('keydown', handler, true)
    return () => window.removeEventListener('keydown', handler, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, confirmDiscard, requestClose, settings])

  const provider = useMemo(
    () => providers.find((item) => item.id === settings?.provider) ?? providers[0],
    [providers, settings?.provider],
  )

  const catalogModels = useMemo(() => {
    if (!provider) return []
    return provider.groups.flatMap((group) => group.models.map((model) => ({ ...model, group: group.label })))
  }, [provider])

  const visibleGroups = useMemo(() => {
    if (!provider) return []
    const query = modelQuery.trim().toLowerCase()
    const matches = (model: ProviderModel) =>
      !query || model.id.toLowerCase().includes(query) || model.name.toLowerCase().includes(query)
    if (remoteModels) {
      const known = new Map(catalogModels.map((model) => [model.id, model.group]))
      const grouped = new Map<string, ProviderModel[]>()
      for (const model of remoteModels) {
        if (!matches(model)) continue
        const label = model.free ? '免费模型' : known.get(model.id) ?? '在线模型列表'
        grouped.set(label, [...(grouped.get(label) ?? []), model])
      }
      const order = ['免费模型', ...provider.groups.map((group) => group.label), '在线模型列表']
      return [...grouped.entries()]
        .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
        .map(([label, models]) => ({ label, models }))
    }
    return provider.groups
      .map((group) => ({ label: group.label, models: group.models.filter(matches) }))
      .filter((group) => group.models.length > 0)
  }, [provider, modelQuery, remoteModels, catalogModels])

  const allModelIds = useMemo(() => {
    const ids = new Set(catalogModels.map((model) => model.id))
    remoteModels?.forEach((model) => ids.add(model.id))
    return ids
  }, [catalogModels, remoteModels])

  // Whenever the page opens or the provider changes: show the last fetched list right away,
  // then refresh it in the background. Failures fall back to what is already on screen.
  useEffect(() => {
    if (!open || !ready || !provider) return
    const current = settingsRef.current
    if (!current) return
    const cached = current.model_cache?.[provider.id]
    if (cached?.models?.length) {
      setRemoteModels(cached.models)
      setRemoteFetchedAt(cached.fetched_at)
      setRemoteSource('cache')
    }
    const keyReady = !provider.key_required || Boolean(current.api_key)
    const urlReady = !provider.custom_base_url || provider.id === 'ollama' || Boolean(current.base_url)
    if (provider.supports_model_listing && keyReady && urlReady) {
      void refreshModels({ silent: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ready, provider?.id])

  if (!open) return null

  const update = (patch: Partial<AppSettings>) => {
    setSettings((current) => (current ? { ...current, ...patch } : current))
    setSaved(false)
    setTestResult(null)
  }

  const chooseProvider = (next: ProviderInfo) => {
    if (!settings || next.id === settings.provider) return
    const keepModel = next.groups.some((group) => group.models.some((model) => model.id === settings.model))
    const rememberedKeys = { ...settings.api_keys }
    if (settings.api_key) rememberedKeys[settings.provider] = settings.api_key
    update({
      provider: next.id,
      model: keepModel ? settings.model : next.default_model,
      base_url: next.custom_base_url ? settings.base_url || next.base_url : '',
      api_key: rememberedKeys[next.id] ?? '',
      api_keys: rememberedKeys,
    })
    modelsAbortRef.current?.abort()
    setRemoteModels(null)
    setRemoteFetchedAt(null)
    setRemoteSource(null)
    setLoadingModels(false)
    setModelsError('')
    setAutoRefreshFailed(false)
    setModelQuery('')
  }

  const submit = async () => {
    if (!settings || saving) return
    setSaving(true)
    setError('')
    try {
      const updated = await saveSettings(settings)
      setSettings(updated)
      setSnapshot(comparable(updated))
      onSaved?.(updated)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2200)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const refreshModels = async (options: { silent?: boolean } = {}) => {
    const current = settingsRef.current
    if (!current) return
    modelsAbortRef.current?.abort()
    const controller = new AbortController()
    modelsAbortRef.current = controller
    setLoadingModels(true)
    setModelsError('')
    setAutoRefreshFailed(false)
    try {
      const entry = await listAiModels(
        { provider: current.provider, api_key: current.api_key, base_url: current.base_url },
        controller.signal,
      )
      if (controller.signal.aborted) return
      setRemoteModels(entry.models)
      setRemoteFetchedAt(entry.fetched_at)
      setRemoteSource('live')
      // Mirror the backend cache locally so switching away and back in this session stays instant.
      setSettings((state) =>
        state ? { ...state, model_cache: { ...state.model_cache, [current.provider]: entry } } : state,
      )
      if (!entry.models.length && !options.silent) setModelsError('接口返回了空的模型列表')
    } catch (reason) {
      if (controller.signal.aborted) return
      if (options.silent) {
        // Keep whatever is on screen (cache or built-in catalogue); just flag it.
        setAutoRefreshFailed(true)
      } else {
        setModelsError(reason instanceof Error ? reason.message : '获取模型列表失败')
      }
    } finally {
      if (!controller.signal.aborted) setLoadingModels(false)
    }
  }

  const runTest = async () => {
    if (!settings) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setTesting(true)
    setTestResult(null)
    try {
      setTestResult(
        await testAiConnection(
          {
            provider: settings.provider,
            api_key: settings.api_key,
            base_url: settings.base_url,
            model: settings.model,
          },
          controller.signal,
        ),
      )
    } catch (reason) {
      if (!controller.signal.aborted) {
        setTestResult({
          ok: false,
          provider: settings.provider,
          model: settings.model,
          protocol: provider?.protocol ?? 'chat',
          latency_ms: 0,
          error: reason instanceof Error ? reason.message : '连接失败',
        })
      }
    } finally {
      if (!controller.signal.aborted) setTesting(false)
    }
  }

  const recheckTranslation = async () => {
    setCheckingTranslation(true)
    try {
      setTranslationStatus(await getTranslationStatus(true))
    } catch {
      /* status is advisory only */
    } finally {
      setCheckingTranslation(false)
    }
  }

  const keyMissing = Boolean(provider?.key_required && settings && !settings.api_key)
  const urlMissing = Boolean(provider?.custom_base_url && settings && !settings.base_url && provider.id !== 'ollama')
  const canTest = Boolean(settings?.model) && !keyMissing && !urlMissing && !testing

  const aiSummary = (() => {
    if (!settings || !provider) return '读取中…'
    if (!settings.configured && !dirty) return '尚未配置'
    return `${provider.label} · ${settings.model || '未选模型'}`
  })()

  const renderAi = () => {
    if (!settings || !provider) return null
    const selectedKnown = allModelIds.has(settings.model)
    return (
      <>
        <section className="sp-section">
          <header>
            <span className="sp-step">1</span>
            <div>
              <h3>选择供应商</h3>
              <p>接口地址已内置，选择后只需填写密钥。带“免费”标记的供应商提供免费模型。</p>
            </div>
          </header>
          <div className="sp-provider-grid" role="radiogroup" aria-label="AI 供应商">
            {providers.map((item) => {
              const hasFree = item.groups.some((group) => group.models.some((model) => model.free))
              const active = item.id === settings.provider
              return (
                <button
                  type="button"
                  key={item.id}
                  role="radio"
                  aria-checked={active}
                  className={`sp-provider ${active ? 'active' : ''}`}
                  onClick={() => chooseProvider(item)}
                >
                  <span className="sp-provider-head">
                    <b>{item.label}</b>
                    <span className="sp-badges">
                      {hasFree && <em className="free">免费</em>}
                      <em className={item.region}>{REGION_LABEL[item.region]}</em>
                    </span>
                  </span>
                  <small>{item.tagline}</small>
                  {active && <Check size={14} className="sp-provider-check" />}
                </button>
              )
            })}
          </div>
        </section>

        <section className="sp-section">
          <header>
            <span className="sp-step">2</span>
            <div>
              <h3>{provider.key_required ? '填写 API Key' : '连接信息'}</h3>
              <p>
                密钥只保存在本机 <code>%LOCALAPPDATA%\InkRead\settings.json</code>，
                调用时仅发送给所选供应商。
              </p>
            </div>
            {provider.key_url && (
              <a className="sp-link" href={provider.key_url} target="_blank" rel="noreferrer">
                <KeyRound size={13} /> 获取密钥 <ExternalLink size={11} />
              </a>
            )}
          </header>
          <div className="sp-fields">
            {provider.custom_base_url && (
              <label className="sp-field">
                <span>接口地址</span>
                <input
                  value={settings.base_url}
                  onChange={(event) => update({ base_url: event.target.value })}
                  placeholder={provider.base_url || 'https://your-service.example.com/v1'}
                  spellCheck={false}
                />
              </label>
            )}
            <label className="sp-field">
              <span>API Key{!provider.key_required && <small>可选</small>}</span>
              <SecretInput
                value={settings.api_key}
                onChange={(value) => update({ api_key: value })}
                placeholder={provider.key_placeholder}
              />
            </label>
          </div>
        </section>

        <section className="sp-section">
          <header>
            <span className="sp-step">3</span>
            <div>
              <h3>选择模型</h3>
              <p>
                {remoteModels && remoteSource === 'live'
                  ? `已从 ${provider.label} 拉取 ${remoteModels.length} 个模型`
                  : remoteModels
                    ? `${provider.label} 上次拉取的 ${remoteModels.length} 个模型`
                    : `内置 ${catalogModels.length} 个常用模型；也可以拉取在线列表或直接输入模型 ID。`}
                {remoteFetchedAt !== null && ` · 更新于 ${formatFetchedAt(remoteFetchedAt)}`}
                {loadingModels && ' · 正在刷新…'}
                {autoRefreshFailed && !loadingModels && (
                  <span className="sp-stale"> · 在线列表暂不可用{remoteModels ? '' : '，显示内置目录'}</span>
                )}
              </p>
            </div>
            {provider.supports_model_listing && (
              <button
                type="button"
                className="sp-ghost"
                onClick={() => void refreshModels()}
                disabled={loadingModels || keyMissing || urlMissing}
                title={keyMissing ? '请先填写 API Key' : '从供应商拉取当前可用模型'}
              >
                {loadingModels ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}
                拉取在线列表
              </button>
            )}
          </header>
          <div className="sp-model-toolbar">
            <label className="sp-search">
              <Search size={13} />
              <input
                value={modelQuery}
                onChange={(event) => setModelQuery(event.target.value)}
                placeholder="搜索模型名称或 ID"
                spellCheck={false}
              />
              {modelQuery && (
                <button type="button" onClick={() => setModelQuery('')} title="清除">
                  <X size={12} />
                </button>
              )}
            </label>
            <label className="sp-custom-model">
              <span>模型 ID</span>
              <input
                value={settings.model}
                onChange={(event) => update({ model: event.target.value.trim() })}
                placeholder="可直接输入模型 ID"
                spellCheck={false}
              />
            </label>
          </div>
          {modelsError && (
            <div className="sp-inline-error">
              <AlertTriangle size={13} /> {modelsError}
            </div>
          )}
          {!modelsError && remoteSource === 'live' && settings.model && !remoteModels?.some((model) => model.id === settings.model) && (
            <div className="sp-inline-warning">
              <AlertTriangle size={13} /> 模型 <code>{settings.model}</code> 不在 {provider.label} 当前返回的列表中，可能已下线或需要其他权限。
            </div>
          )}
          <div className="sp-model-list" role="listbox" aria-label="模型列表">
            {settings.model && !selectedKnown && (
              <div className="sp-model-group">
                <h4>当前自定义模型</h4>
                <button type="button" role="option" aria-selected className="sp-model active">
                  <span className="sp-model-name">{settings.model}</span>
                  <code>{settings.model}</code>
                  <em className="custom">自定义</em>
                </button>
              </div>
            )}
            {visibleGroups.map((group) => (
              <div className="sp-model-group" key={group.label}>
                <h4>{group.label}</h4>
                {group.models.map((model) => {
                  const active = model.id === settings.model
                  return (
                    <button
                      type="button"
                      role="option"
                      aria-selected={active}
                      key={model.id}
                      className={`sp-model ${active ? 'active' : ''}`}
                      onClick={() => update({ model: model.id })}
                    >
                      <span className="sp-model-name">{model.name}</span>
                      <code>{model.id}</code>
                      <span className="sp-badges">
                        {model.free && <em className="free">免费</em>}
                        {model.vision && <em className="vision">视觉</em>}
                      </span>
                      {active && <Check size={14} />}
                    </button>
                  )
                })}
              </div>
            ))}
            {!visibleGroups.length && !settings.model && (
              <div className="sp-empty">
                {provider.groups.length
                  ? '没有匹配的模型，换个关键词试试。'
                  : '该供应商没有内置模型列表，请拉取在线列表或直接输入模型 ID。'}
              </div>
            )}
          </div>
        </section>

        <section className="sp-section">
          <header>
            <span className="sp-step">4</span>
            <div>
              <h3>测试连接</h3>
              <p>发送一条极短消息，验证密钥、模型与协议是否匹配。测试使用当前表单中的值，无需先保存。</p>
            </div>
            <button type="button" className="sp-primary" onClick={runTest} disabled={!canTest}>
              {testing ? <LoaderCircle size={14} className="spin" /> : <PlugZap size={14} />}
              {testing ? '正在连接…' : '测试连接'}
            </button>
          </header>
          {(keyMissing || urlMissing || !settings.model) && (
            <div className="sp-hint">
              {urlMissing ? '请先填写接口地址。' : keyMissing ? '请先填写 API Key。' : '请先选择模型。'}
            </div>
          )}
          {testResult && (
            <div className={`sp-test ${testResult.ok ? 'ok' : 'fail'}`}>
              {testResult.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <div>
                <b>
                  {testResult.ok ? '连接成功' : '连接失败'} · {testResult.model} · {testResult.protocol}
                  {testResult.ok && ` · ${testResult.latency_ms} ms`}
                </b>
                <small>{testResult.ok ? `模型回复：${testResult.reply || '(空)'}` : testResult.error}</small>
              </div>
            </div>
          )}
        </section>
      </>
    )
  }

  const renderSearch = () =>
    settings && (
      <>
        <section className="sp-section">
          <header>
            <div>
              <h3>检索与校验 Agent</h3>
              <p>控制回答生成前的联网检索，以及生成后的引用可追溯性检查。</p>
            </div>
          </header>
          <div className="sp-fields">
            <Toggle
              checked={settings.web_search}
              onChange={(value) => update({ web_search: value })}
              title="允许学术网络检索"
              hint="仅在用户要求、问题具有当下意图或论文原文覆盖不足时触发；来源以 [W#] 标注并与论文原文隔离"
            />
            <Toggle
              checked={settings.fact_check}
              onChange={(value) => update({ fact_check: value })}
              title="事实校验 Agent"
              hint="检查来源编号有效性、引用覆盖率与回答—原文语义重合，低置信度时给出提示"
            />
          </div>
        </section>
        <section className="sp-section">
          <header>
            <div>
              <h3>Google Scholar（SerpApi）</h3>
              <p>可选。未填写时仍会使用 Semantic Scholar 与 Crossref 进行学术检索。</p>
            </div>
            <a className="sp-link" href={SERPAPI_URL} target="_blank" rel="noreferrer">
              <KeyRound size={13} /> 获取密钥 <ExternalLink size={11} />
            </a>
          </header>
          <div className="sp-fields">
            <label className="sp-field">
              <span>SerpApi Key</span>
              <SecretInput
                value={settings.serpapi_key}
                onChange={(value) => update({ serpapi_key: value })}
                placeholder="用于 Google Scholar 检索"
              />
            </label>
          </div>
        </section>
      </>
    )

  const renderTranslation = () =>
    settings && (
      <>
        <section className="sp-section">
          <header>
            <div>
              <h3>百度翻译（优先）</h3>
              <p>
                需要同一账号下的 APP ID 与 API Key。可用时优先调用；额度耗尽或不可用时自动切换本地英译中，
                不影响阅读。
              </p>
            </div>
            <a className="sp-link" href={BAIDU_URL} target="_blank" rel="noreferrer">
              <KeyRound size={13} /> 开发者信息 <ExternalLink size={11} />
            </a>
          </header>
          <div className="sp-fields">
            <label className="sp-field">
              <span>APP ID</span>
              <input
                value={settings.baidu_translate_appid}
                onChange={(event) => update({ baidu_translate_appid: event.target.value.trim() })}
                placeholder="在百度翻译开放平台的开发者信息中查看"
                spellCheck={false}
              />
            </label>
            <label className="sp-field">
              <span>API Key</span>
              <SecretInput
                value={settings.baidu_translate_api_key}
                onChange={(value) => update({ baidu_translate_api_key: value })}
                placeholder="SA1b_…"
              />
            </label>
          </div>
        </section>
        <section className="sp-section">
          <header>
            <div>
              <h3>本地英译中（后备）</h3>
              <p>OPUS-MT 模型首次启用时下载约 160 MB，之后离线可用，选区不会离开设备。</p>
            </div>
            <button
              type="button"
              className="sp-ghost"
              onClick={recheckTranslation}
              disabled={checkingTranslation}
            >
              {checkingTranslation ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}
              重新检测
            </button>
          </header>
          <dl className="sp-status">
            <div>
              <dt>当前线路</dt>
              <dd>
                {!translationStatus
                  ? '读取中…'
                  : translationStatus.provider === 'baidu'
                    ? '百度翻译'
                    : '本地模型'}
              </dd>
            </div>
            <div>
              <dt>百度状态</dt>
              <dd>
                {!translationStatus
                  ? '—'
                  : translationStatus.baidu_available
                    ? '可用'
                    : translationStatus.baidu_reason || (translationStatus.quota_exhausted ? '额度耗尽' : '未配置或不可用')}
              </dd>
            </div>
            <div>
              <dt>本地模型</dt>
              <dd>
                {!translationStatus
                  ? '—'
                  : {
                      missing: '未下载（首次翻译时自动下载）',
                      downloading: `下载中 ${Math.round(translationStatus.local_model_progress * 100)}%`,
                      ready: '已就绪',
                      error: translationStatus.local_model_error || '下载失败',
                    }[translationStatus.local_model_state]}
              </dd>
            </div>
          </dl>
        </section>
      </>
    )

  const renderReading = () =>
    settings && (
      <section className="sp-section">
        <header>
          <div>
            <h3>论文批注卡</h3>
            <p>鼠标移开后的透明程度；移入、编辑或调用 AI 时始终恢复清晰。修改后保存即可生效。</p>
          </div>
        </header>
        <div className="sp-fields">
          <label className="sp-field">
            <span>闲置透明度</span>
            <div className="sp-slider">
              <input
                type="range"
                min="0.15"
                max="1"
                step="0.05"
                value={settings.comment_idle_opacity}
                aria-label="批注卡闲置透明度"
                style={
                  {
                    '--sp-slider-position': `${((settings.comment_idle_opacity - 0.15) / 0.85) * 100}%`,
                  } as React.CSSProperties
                }
                onChange={(event) => update({ comment_idle_opacity: Number(event.target.value) })}
              />
              <output>{Math.round(settings.comment_idle_opacity * 100)}%</output>
            </div>
          </label>
          <div className="sp-preview" aria-hidden>
            <div className="sp-preview-text">
              The router only reads block summaries, which keeps the cost of selecting candidate blocks low.
            </div>
            <div className="sp-preview-card" style={{ opacity: settings.comment_idle_opacity }}>
              <b>批注示例</b>
              <span>路由只读取块摘要，从而降低选择候选块的计算成本。</span>
            </div>
          </div>
        </div>
      </section>
    )

  const tabSummary: Record<Tab, string> = {
    ai: aiSummary,
    search: settings
      ? `${settings.web_search ? '联网开启' : '联网关闭'} · ${settings.serpapi_key ? 'SerpApi 已填' : '仅免费源'}`
      : '',
    translation: settings
      ? settings.translation_configured || (settings.baidu_translate_appid && settings.baidu_translate_api_key)
        ? '百度优先 · 本地后备'
        : '仅本地模型'
      : '',
    reading: settings ? `闲置透明度 ${Math.round(settings.comment_idle_opacity * 100)}%` : '',
  }

  return (
    <div className="settings-page" role="dialog" aria-modal aria-label="设置">
      <header className="sp-topbar">
        <button type="button" className="sp-back" onClick={requestClose} title="返回阅读 (Esc)">
          <ArrowLeft size={16} />
        </button>
        <div className="sp-title">
          <b>设置</b>
          <small>密钥与偏好仅保存在本机</small>
        </div>
        <div className="sp-actions">
          {error && (
            <span className="sp-error">
              <AlertTriangle size={13} /> {error}
            </span>
          )}
          {dirty && !saving && <span className="sp-dirty">有未保存的更改</span>}
          <button type="button" className="sp-ghost" onClick={requestClose}>
            {dirty ? '取消' : '关闭'}
          </button>
          <button
            type="button"
            className="sp-primary"
            onClick={submit}
            disabled={!settings || saving || (!dirty && !saved)}
            title="Ctrl+S"
          >
            {saving ? <LoaderCircle size={14} className="spin" /> : saved ? <Check size={14} /> : null}
            {saving ? '保存中…' : saved ? '已保存' : '保存设置'}
          </button>
        </div>
      </header>

      <div className="sp-layout">
        <nav className="sp-nav" aria-label="设置分类">
          {TABS.map(({ id, label, hint, icon: Icon }) => (
            <button
              type="button"
              key={id}
              className={tab === id ? 'active' : ''}
              onClick={() => setTab(id)}
            >
              <Icon size={16} />
              <span>
                <b>{label}</b>
                <small>{tabSummary[id] || hint}</small>
              </span>
            </button>
          ))}
        </nav>
        <main className="sp-content">
          {!settings ? (
            <div className="modal-loading">
              <LoaderCircle className="spin" /> 正在读取设置…
            </div>
          ) : (
            <div className="sp-panel" key={tab}>
              {tab === 'ai' && renderAi()}
              {tab === 'search' && renderSearch()}
              {tab === 'translation' && renderTranslation()}
              {tab === 'reading' && renderReading()}
            </div>
          )}
        </main>
      </div>

      {confirmDiscard && (
        <div className="sp-confirm-backdrop" onMouseDown={() => setConfirmDiscard(false)}>
          <div className="sp-confirm" onMouseDown={(event) => event.stopPropagation()}>
            <b>有未保存的更改</b>
            <p>离开前是否保存当前修改？</p>
            <div>
              <button type="button" className="sp-ghost" onClick={() => setConfirmDiscard(false)}>
                继续编辑
              </button>
              <button
                type="button"
                className="sp-ghost danger"
                onClick={() => {
                  setConfirmDiscard(false)
                  onClose()
                }}
              >
                放弃更改
              </button>
              <button
                type="button"
                className="sp-primary"
                onClick={async () => {
                  await submit()
                  setConfirmDiscard(false)
                  onClose()
                }}
              >
                保存并关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
