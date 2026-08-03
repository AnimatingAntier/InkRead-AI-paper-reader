import {
  BookOpen,
  CheckSquare2,
  FilePlus2,
  FileText,
  Focus,
  Library,
  Languages,
  ListTree,
  LoaderCircle,
  Moon,
  Search,
  ScanLine,
  Settings,
  SquareDashed,
  Sun,
  Trash2,
  X,
} from 'lucide-react'
import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  deleteDocument,
  getSettings,
  getTranslationStatus,
  importDocument,
  listDocuments,
  openDocument,
  saveProgress,
} from './api'
import { AssistantPanel } from './components/AssistantPanel'
import { MarkdownReader } from './components/MarkdownReader'
import { MaskCard } from './components/MaskCard'
import { PdfReader } from './components/PdfReader'
import { ScreenshotOverlay } from './components/ScreenshotOverlay'
import { SettingsModal } from './components/SettingsModal'
import { TranslationPanel } from './components/TranslationPanel'
import type { LibraryDocument, OpenDocument, ScreenshotAttachment } from './types'

type Toast = { message: string; kind: 'success' | 'error' | 'info' }
type SidebarView = 'library' | 'outline' | 'translation'

function isEnglishSelection(text: string): boolean {
  const latinCount = (text.match(/[A-Za-z]/g) || []).length
  const hanCount = (text.match(/[\u3400-\u9fff]/g) || []).length
  return latinCount >= 2 && latinCount >= hanCount * 2
}

export default function App() {
  const [documents, setDocuments] = useState<LibraryDocument[]>([])
  const [active, setActive] = useState<OpenDocument | null>(null)
  const [loading, setLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const [search, setSearch] = useState('')
  const [night, setNight] = useState(false)
  const [focus, setFocus] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [sidebarView, setSidebarView] = useState<SidebarView>('library')
  const [selectedText, setSelectedText] = useState('')
  const [translationText, setTranslationText] = useState('')
  const [screenshotOpen, setScreenshotOpen] = useState(false)
  const [maskCardOpen, setMaskCardOpen] = useState(false)
  const [commentMode, setCommentMode] = useState(false)
  const [commentIdleOpacity, setCommentIdleOpacity] = useState(0.58)
  const [screenshotAttachment, setScreenshotAttachment] =
    useState<ScreenshotAttachment | null>(null)
  const [comparisonIds, setComparisonIds] = useState<string[]>([])
  const [targetSection, setTargetSection] = useState<string>()
  const [targetPage, setTargetPage] = useState<number>()
  const [toast, setToast] = useState<Toast | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const saveTimer = useRef<number>()
  const outlineList = useRef<HTMLDivElement>(null)
  const readingStage = useRef<HTMLElement>(null)

  const notify = (message: string, kind: Toast['kind'] = 'info') => {
    setToast({ message, kind })
    window.setTimeout(() => setToast(null), 3200)
  }

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments())
    } catch (error) {
      notify(error instanceof Error ? error.message : '文库加载失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
    void getTranslationStatus(true).catch(() => undefined)
    void getSettings()
      .then((settings) => setCommentIdleOpacity(settings.comment_idle_opacity || 0.58))
      .catch(() => undefined)
  }, [refresh])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'o') {
        event.preventDefault()
        fileInput.current?.click()
      }
      if ((event.ctrlKey || event.metaKey) && event.key === ',') {
        event.preventDefault()
        setSettingsOpen(true)
      }
      if (event.key === 'Escape') {
        if (focus) setFocus(false)
        if (commentMode) setCommentMode(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [commentMode, focus])

  const visibleDocuments = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return documents
    return documents.filter(
      (document) =>
        document.title.toLowerCase().includes(query) ||
        document.name.toLowerCase().includes(query),
    )
  }, [documents, search])

  const outlineSections = useMemo(() => active?.sections.slice(0, 120) || [], [active?.sections])

  const currentOutlineIndex = useMemo(() => {
    if (!outlineSections.length || !active) return -1
    if (active.kind === 'pdf' && active.pageCount) {
      const currentPage = Math.max(
        1,
        Math.min(active.pageCount, Math.round((active.progress / 100) * active.pageCount)),
      )
      let currentIndex = 0
      outlineSections.forEach((section, index) => {
        if ((section.page || 1) <= currentPage) currentIndex = index
      })
      return currentIndex
    }
    return Math.min(
      outlineSections.length - 1,
      Math.max(0, Math.round((active.progress / 100) * (outlineSections.length - 1))),
    )
  }, [active, outlineSections])

  const outlineProgress = useMemo(() => {
    const sectionCount = outlineSections.length
    if (currentOutlineIndex < 0 || sectionCount < 2) return 0
    return (currentOutlineIndex / (sectionCount - 1)) * 100
  }, [currentOutlineIndex, outlineSections.length])

  useEffect(() => {
    if (sidebarView !== 'outline' || currentOutlineIndex < 0) return
    const current = outlineList.current?.querySelector<HTMLElement>('[data-current="true"]')
    current?.scrollIntoView({ block: 'nearest' })
  }, [active?.id, currentOutlineIndex, sidebarView])

  const openPaper = async (id: string) => {
    setLoading(true)
    setSelectedText('')
    setTranslationText('')
    setScreenshotOpen(false)
    setMaskCardOpen(false)
    setCommentMode(false)
    setScreenshotAttachment(null)
    setTargetPage(undefined)
    setTargetSection(undefined)
    try {
      const document = await openDocument(id)
      setActive(document)
      setDocuments((items) =>
        items.map((item) => (item.id === id ? { ...item, lastOpenedAt: document.lastOpenedAt } : item)),
      )
    } catch (error) {
      notify(error instanceof Error ? error.message : '论文打开失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (!files.length) return
    setImporting(true)
    let last: LibraryDocument | null = null
    try {
      for (const file of files) {
        const extension = file.name.split('.').pop()?.toLowerCase()
        if (!['pdf', 'md', 'markdown'].includes(extension || '')) {
          notify(`已跳过不支持的文件：${file.name}`, 'error')
          continue
        }
        last = await importDocument(file)
      }
      await refresh()
      if (last) {
        await openPaper(last.id)
        notify(`已导入《${last.title}》`, 'success')
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : '导入失败', 'error')
    } finally {
      setImporting(false)
    }
  }

  const removePaper = async (document: LibraryDocument) => {
    if (!window.confirm(`确定从本机文库移除《${document.title}》吗？源文件副本也会删除。`)) return
    try {
      await deleteDocument(document.id)
      if (active?.id === document.id) setActive(null)
      setComparisonIds((ids) => ids.filter((id) => id !== document.id))
      await refresh()
      notify('已从文库移除', 'success')
    } catch (error) {
      notify(error instanceof Error ? error.message : '删除失败', 'error')
    }
  }

  const updateProgress = useCallback(
    (value: number) => {
      if (!active) return
      setActive((document) => (document ? { ...document, progress: value } : document))
      setDocuments((items) =>
        items.map((item) => (item.id === active.id ? { ...item, progress: value } : item)),
      )
      window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(() => {
        void saveProgress(active.id, value)
      }, 900)
    },
    [active?.id],
  )

  const toggleCompare = (id: string) => {
    if (id === active?.id) return
    setComparisonIds((ids) =>
      ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id].slice(-4),
    )
  }

  const handleSelection = (text: string) => {
    setSelectedText(text)
    setTranslationText(text)
    if (isEnglishSelection(text)) {
      setFocus(false)
      setSidebarView('translation')
    }
  }

  return (
    <div className={`ink-app ${night ? 'night' : ''} ${focus ? 'focus' : ''}`}>
      <input
        ref={fileInput}
        className="hidden-input"
        type="file"
        accept=".pdf,.md,.markdown"
        multiple
        onChange={handleImport}
      />

      <nav className="ritual-rail">
        <button className="seal" title="砚读首页" onClick={() => setFocus(false)}>砚</button>
        <div className="rail-actions">
          <button
            className={sidebarView === 'library' ? 'active' : ''}
            title="文库"
            aria-pressed={sidebarView === 'library'}
            onClick={() => {
              setFocus(false)
              setSidebarView('library')
            }}
          >
            <Library size={19} />
            <span>文库</span>
          </button>
          <button
            className={sidebarView === 'outline' ? 'active' : ''}
            title="大纲"
            aria-pressed={sidebarView === 'outline'}
            onClick={() => {
              setFocus(false)
              setSidebarView('outline')
            }}
          >
            <ListTree size={19} />
            <span>大纲</span>
          </button>
          <button
            className={sidebarView === 'translation' ? 'active' : ''}
            title="翻译"
            aria-pressed={sidebarView === 'translation'}
            onClick={() => {
              setFocus(false)
              setSidebarView('translation')
            }}
          >
            <Languages size={19} />
            <span>翻译</span>
          </button>
          <button title="设置" onClick={() => setSettingsOpen(true)}>
            <Settings size={19} />
            <span>设置 · Ctrl ,</span>
          </button>
        </div>
        <div className="rail-brand">InkRead · 砚读</div>
      </nav>

      <aside
        className={
          sidebarView === 'library'
            ? 'library-panel'
            : sidebarView === 'translation'
              ? 'translation-panel'
              : 'outline-panel'
        }
      >
        {sidebarView === 'library' ? (
          <>
            <div className="library-head">
              <div>
                <span>LIBRARY</span>
                <h2>我的文库</h2>
              </div>
              <button onClick={() => fileInput.current?.click()} disabled={importing} title="导入论文">
                {importing ? <LoaderCircle size={17} className="spin" /> : <FilePlus2 size={17} />}
              </button>
            </div>
            <label className="library-search">
              <Search size={14} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索题目…"
              />
              {search && <button onClick={() => setSearch('')}><X size={12} /></button>}
            </label>
            <div className="library-summary">
              <span>{documents.length} 篇论文</span>
              {comparisonIds.length ? <b>已选 {comparisonIds.length + 1} 篇对比</b> : <span>本机私有</span>}
            </div>
            <div className="document-list">
              {loading && !documents.length ? (
                <div className="library-empty"><LoaderCircle className="spin" />正在整理书架…</div>
              ) : visibleDocuments.length ? (
                visibleDocuments.map((document) => (
                  <article
                    className={`document-card ${active?.id === document.id ? 'active' : ''}`}
                    key={document.id}
                    onClick={() => void openPaper(document.id)}
                  >
                    <div className={`document-icon ${document.kind}`}>
                      {document.kind === 'pdf' ? 'PDF' : 'MD'}
                    </div>
                    <div className="document-info">
                      <h3>{document.title}</h3>
                      <p>
                        {document.kind === 'pdf'
                          ? `${document.pageCount} 页`
                          : `${document.sectionCount} 节`}
                        <span>·</span>
                        {document.progress ? `已读 ${Math.round(document.progress)}%` : '未开始'}
                      </p>
                      <div className="document-progress">
                        <i style={{ width: `${document.progress}%` }} />
                      </div>
                    </div>
                    <div className="document-actions">
                      <button
                        className={comparisonIds.includes(document.id) ? 'checked' : ''}
                        title="加入多篇对比"
                        onClick={(event) => {
                          event.stopPropagation()
                          toggleCompare(document.id)
                        }}
                      >
                        <CheckSquare2 size={13} />
                      </button>
                      <button
                        title="从文库移除"
                        onClick={(event) => {
                          event.stopPropagation()
                          void removePaper(document)
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </article>
                ))
              ) : (
                <div className="library-empty">
                  <BookOpen size={25} />
                  <b>{search ? '没有匹配的论文' : '书架还是空的'}</b>
                  <span>{search ? '试试其他关键词' : '导入 PDF 或 Markdown 开始阅读'}</span>
                  {!search && <button onClick={() => fileInput.current?.click()}>导入第一篇</button>}
                </div>
              )}
            </div>
            <div className="library-foot">
              <span><i /> 原文仅存于本机</span>
              <span>{documents.reduce((sum, item) => sum + item.charCount, 0).toLocaleString()} 字符</span>
            </div>
          </>
        ) : sidebarView === 'translation' ? (
          <TranslationPanel
            text={translationText}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        ) : active ? (
          <>
            <div className="outline-meta">
              <span>{active.kind === 'pdf' ? 'PDF PAPER' : 'MARKDOWN NOTE'}</span>
              <h2>{active.title}</h2>
              <p>{active.name}</p>
            </div>
            <div className="outline-label">大纲 · CONTENTS</div>
            <div className="outline-list" ref={outlineList}>
              <div
                className="outline-track"
                style={{ '--outline-progress': `${outlineProgress}%` } as React.CSSProperties}
              >
                <div className="outline-progress-rail" aria-hidden="true" />
                {outlineSections.map((section, index) => (
                  <button
                    className={index === currentOutlineIndex ? 'current' : ''}
                    data-current={index === currentOutlineIndex}
                    aria-current={index === currentOutlineIndex ? 'location' : undefined}
                    style={{ paddingLeft: `${18 + Math.min(2, section.level - 1) * 14}px` }}
                    key={section.id}
                    onClick={() => {
                      setTargetSection(`${section.id}:${Date.now()}`)
                      if (section.page) setTargetPage(section.page)
                    }}
                  >
                    <span>{String(index + 1).padStart(2, '0')}</span>
                    <b>{section.title}</b>
                  </button>
                ))}
              </div>
            </div>
            <div className="reading-stat">
              <div
                className="progress-ring"
                style={{ '--progress': `${active.progress * 3.6}deg` } as React.CSSProperties}
              >
                <span>{Math.round(active.progress)}%</span>
              </div>
              <div>
                <b>阅读进度</b>
                <span>{active.kind === 'pdf' ? `${active.pageCount} 页` : `${active.sectionCount} 节`}</span>
              </div>
            </div>
          </>
        ) : (
          <div className="outline-placeholder">
            <FileText size={24} />
            <span>打开论文后显示结构化大纲</span>
          </div>
        )}
      </aside>

      <main className="reading-stage" ref={readingStage}>
        <header className="stage-topbar">
          <i className="reading-hairline" style={{ width: `${active?.progress || 0}%` }} />
          <div className="breadcrumb">
            文库 <span>/</span>
            <b>{active?.title || '欢迎来到砚读'}</b>
            {active && <em>{active.kind === 'pdf' ? `${active.pageCount} pages` : 'Markdown'}</em>}
          </div>
          <div className="stage-actions">
            <button
              className={maskCardOpen ? 'active' : ''}
              disabled={!active}
              title="打开遮挡卡 · Tab 切换透明度"
              aria-pressed={maskCardOpen}
              onClick={() => {
                setScreenshotOpen(false)
                setCommentMode(false)
                setMaskCardOpen((value) => !value)
              }}
            >
              <SquareDashed size={15} />遮挡
            </button>
            <button
              className={screenshotOpen ? 'active' : ''}
              disabled={!active}
              title="框选论文截图并发送给 AI"
              onClick={() => {
                setMaskCardOpen(false)
                setCommentMode(false)
                setScreenshotOpen((value) => !value)
              }}
            >
              <ScanLine size={15} />截图
            </button>
            <button className={focus ? 'active' : ''} onClick={() => setFocus((value) => !value)}>
              <Focus size={15} />{focus ? '退出沉浸' : '沉浸'}
            </button>
            <button onClick={() => setNight((value) => !value)}>
              {night ? <Sun size={15} /> : <Moon size={15} />}{night ? '晨读' : '夜读'}
            </button>
            <div className="user-seal">研</div>
          </div>
        </header>

        {loading && active ? (
          <div className="stage-loading"><LoaderCircle className="spin" />正在展开论文…</div>
        ) : active ? (
          active.kind === 'markdown' ? (
            <MarkdownReader
              document={active}
              onProgress={updateProgress}
              onSelection={handleSelection}
              scrollTarget={targetSection}
              commentMode={commentMode}
              onCommentModeChange={(enabled) => {
                if (enabled) {
                  setMaskCardOpen(false)
                  setScreenshotOpen(false)
                }
                setCommentMode(enabled)
              }}
              commentIdleOpacity={commentIdleOpacity}
            />
          ) : (
            <PdfReader
              document={active}
              onProgress={updateProgress}
              onSelection={handleSelection}
              targetPage={targetPage}
              commentMode={commentMode}
              onCommentModeChange={(enabled) => {
                if (enabled) {
                  setMaskCardOpen(false)
                  setScreenshotOpen(false)
                }
                setCommentMode(enabled)
              }}
              commentIdleOpacity={commentIdleOpacity}
            />
          )
        ) : (
          <div className="welcome-stage">
            <div className="welcome-seal">砚</div>
            <span className="welcome-kicker">A SCHOLAR'S READING ROOM</span>
            <h1>让每一篇论文，<em>读得深，信得过。</em></h1>
            <p>
              原生支持 PDF 与精排 Markdown。结构化长上下文检索、学术网络搜索和事实校验 Agent
              协同工作，每项结论都能追溯到原文或网络来源。
            </p>
            <button onClick={() => fileInput.current?.click()}>
              <FilePlus2 size={17} /> 导入论文
            </button>
            <div className="welcome-features">
              <span><b>01</b>本机私有文库</span>
              <span><b>02</b>长文精准检索</span>
              <span><b>03</b>可信来源隔离</span>
            </div>
          </div>
        )}
        {active && (
          <MaskCard
            visible={maskCardOpen}
            topOffset={(focus ? 0 : 52) + (active.kind === 'pdf' ? 46 : 0)}
            onClose={() => setMaskCardOpen(false)}
          />
        )}
      </main>

      <AssistantPanel
        activeDocument={active}
        comparisonDocuments={comparisonIds}
        selectedText={selectedText}
        onClearSelection={() => setSelectedText('')}
        screenshot={screenshotAttachment}
        onClearScreenshot={() => setScreenshotAttachment(null)}
      />

      <SettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={(settings) => setCommentIdleOpacity(settings.comment_idle_opacity)}
      />
      {screenshotOpen && readingStage.current && (
        <ScreenshotOverlay
          target={readingStage.current}
          onCancel={() => setScreenshotOpen(false)}
          onConfirm={(attachment) => {
            setScreenshotAttachment(attachment)
            setScreenshotOpen(false)
            setFocus(false)
            notify('截图已附加到 AI 助手，输入问题后点击发送', 'success')
          }}
        />
      )}
      {toast && <div className={`toast ${toast.kind}`}>{toast.message}</div>}
    </div>
  )
}
