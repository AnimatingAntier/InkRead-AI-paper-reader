import { ArrowDown, Languages, LoaderCircle, RefreshCw, Settings2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getTranslationStatus, translateText } from '../api'
import type { TranslationResult, TranslationStatus } from '../types'

const translationCache = new Map<string, TranslationResult>()
const pendingTranslations = new Map<string, Promise<TranslationResult>>()

interface Props {
  text: string
  onOpenSettings: () => void
}

function looksLikeEnglish(text: string): boolean {
  const latinCount = (text.match(/[A-Za-z]/g) || []).length
  const hanCount = (text.match(/[\u3400-\u9fff]/g) || []).length
  return latinCount >= 2 && latinCount >= hanCount * 2
}

function translateOnce(source: string): Promise<TranslationResult> {
  const cached = translationCache.get(source)
  if (cached) return Promise.resolve(cached)
  const pending = pendingTranslations.get(source)
  if (pending) return pending
  const request = translateText(source)
    .then((value) => {
      translationCache.set(source, value)
      if (translationCache.size > 128) {
        const oldest = translationCache.keys().next().value
        if (oldest) translationCache.delete(oldest)
      }
      return value
    })
    .finally(() => pendingTranslations.delete(source))
  pendingTranslations.set(source, request)
  return request
}

export function TranslationPanel({ text, onOpenSettings }: Props) {
  const [result, setResult] = useState<TranslationResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [status, setStatus] = useState<TranslationStatus | null>(null)
  const source = text.trim()

  useEffect(() => {
    void getTranslationStatus().then(setStatus).catch(() => undefined)
  }, [])

  useEffect(() => {
    const cached = translationCache.get(source) || null
    setResult(cached)
    setError('')
    if (!source) {
      setLoading(false)
      return
    }
    if (!looksLikeEnglish(source)) {
      setLoading(false)
      setError('当前选区不像英文，请重新选择需要翻译的英文内容。')
      return
    }

    if (cached) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    const timer = window.setTimeout(() => {
      void translateOnce(source)
        .then((value) => {
          if (cancelled) return
          setResult(value)
          setError('')
          void getTranslationStatus().then(setStatus).catch(() => undefined)
        })
        .catch((reason) => {
          if (cancelled) return
          setError(reason instanceof Error ? reason.message : '翻译失败')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, 260)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [retry, source])

  useEffect(() => {
    if (!loading) return
    const timer = window.setInterval(() => {
      void getTranslationStatus().then(setStatus).catch(() => undefined)
    }, 700)
    return () => window.clearInterval(timer)
  }, [loading])

  const activeProvider = result?.provider || status?.provider
  const providerLabel = activeProvider === 'local' ? '本地翻译' : '百度翻译'
  const isDownloading = status?.local_model_state === 'downloading'

  return (
    <>
      <div className="translation-head">
        <div>
          <span>BAIDU PRIORITY · LOCAL FALLBACK</span>
          <h2>选区翻译</h2>
          <p>英语 <ArrowDown size={11} /> 简体中文</p>
        </div>
        <button title="翻译设置" onClick={onOpenSettings}>
          <Settings2 size={16} />
        </button>
      </div>
      <div className={`translation-provider-status ${activeProvider || 'checking'}`}>
        <i />
        <span>
          {!status
            ? '正在检测百度翻译…'
            : status.baidu_available
              ? '百度翻译可用，将优先使用'
              : status.baidu_reason}
        </span>
      </div>

      {!source ? (
        <div className="translation-placeholder">
          <Languages size={27} />
          <b>选择英文即可翻译</b>
          <span>在 PDF 或 Markdown 中划选英文，原文和中文译文会自动出现在这里。</span>
        </div>
      ) : (
        <div className="translation-content">
          <section className="translation-card source">
            <header>
              <span>英文原文</span>
              <small>{source.length.toLocaleString()} 字符</small>
            </header>
            <p>{source}</p>
          </section>

          <div className="translation-flow">
            <i />
            <ArrowDown size={13} />
            <i />
          </div>

          <section className="translation-card result">
            <header>
              <span>中文译文</span>
              <small>{providerLabel}</small>
            </header>
            {loading ? (
              <div className="translation-loading">
                <LoaderCircle className="spin" size={17} />
                {isDownloading
                  ? `首次准备本地模型 ${status?.local_model_progress || 0}%`
                  : '正在翻译…'}
              </div>
            ) : error ? (
              <div className="translation-error">
                <p>{error}</p>
                <div>
                  <button
                    onClick={() => {
                      translationCache.delete(source)
                      setRetry((value) => value + 1)
                    }}
                  >
                    <RefreshCw size={13} /> 重试
                  </button>
                  <button onClick={onOpenSettings}>
                    <Settings2 size={13} /> 设置
                  </button>
                </div>
              </div>
            ) : (
              <p>{result?.translation}</p>
            )}
          </section>

          {result?.fallback_reason && (
            <p className="translation-fallback-note">{result.fallback_reason}</p>
          )}
          <p className="translation-privacy">
            {result?.provider === 'local'
              ? '本次译文由本机离线模型生成，选区文字未发送到第三方。'
              : '百度可用时优先翻译；额度耗尽或服务不可用时自动改用本机模型。'}
          </p>
        </div>
      )}
    </>
  )
}
