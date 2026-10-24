import { useEffect, useRef, useState } from 'react'
import type { FormEvent, RefObject } from 'react'
import { assumptionLines, formatMetres } from '../../domain/presentation'
import type { Presentation } from '../../domain/presentation'
import type { AskOption, FloorSummary } from '../../domain/types'
import { copy } from '../../i18n/en'

type SpeechResultEvent = {
  results: ArrayLike<ArrayLike<{ transcript: string }>>
}

type BrowserSpeech = {
  lang: string
  interimResults: boolean
  onresult: ((event: SpeechResultEvent) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

function createSpeechRecognition(): BrowserSpeech | null {
  const host = window as Window & {
    SpeechRecognition?: new () => BrowserSpeech
    webkitSpeechRecognition?: new () => BrowserSpeech
  }
  const Recognition = host.SpeechRecognition ?? host.webkitSpeechRecognition
  return Recognition ? new Recognition() : null
}

type GuidePanelProps = {
  query: string
  presentation: Presentation
  directionIndex: number
  onQuery: (value: string) => void
  onSubmit: (event: FormEvent) => void
  onChoose: (option: AskOption) => void
  onAskText: (text: string) => void
  onConfirm: () => void
  onCancel: () => void
  onReplay: () => void
  onReopen: () => void
  onShowFloor: (floorId: string) => void
  hereName: string | null
  inputMode: 'text' | 'transcript'
  onInputMode: (mode: 'text' | 'transcript') => void
  inputRef: RefObject<HTMLInputElement | null>
  label: (id: string | null) => string
  floors: FloorSummary[]
}

export function GuidePanel({
  query,
  presentation,
  directionIndex,
  onQuery,
  onSubmit,
  onChoose,
  onAskText,
  onConfirm,
  onCancel,
  onReplay,
  onReopen,
  onShowFloor,
  hereName,
  inputMode,
  onInputMode,
  inputRef,
  label,
  floors,
}: GuidePanelProps) {
  const assumptions = presentation.understood ? assumptionLines(presentation.understood, label) : null
  const route = presentation.route
  const routePreview = !route
    ? null
    : route.reachable
      ? `${formatMetres(route.length_m)} · ${route.step_free ? 'Step-free' : 'Stairs allowed'}`
      : 'Unreachable'
  const localRef = useRef<HTMLInputElement>(null)
  const fieldRef = inputRef ?? localRef
  const speechRef = useRef<BrowserSpeech | null>(null)
  const [listening, setListening] = useState(false)
  const [speechNote, setSpeechNote] = useState<string | null>(null)
  const transcript = inputMode === 'transcript'
  const confirmation = presentation.understood?.summary || presentation.guideText
  const nextInstruction = route?.directions[directionIndex]?.text
    ?? presentation.asks[0]?.question
    ?? (presentation.guideText && presentation.guideText !== confirmation ? presentation.guideText : '')
  const detailLines = [
    ...(assumptions ? [assumptions.preview, ...assumptions.details] : []),
    ...(presentation.understood?.resolved.start_space_id ? [`Start id: ${presentation.understood.resolved.start_space_id}`] : []),
    ...(presentation.understood?.resolved.destination_space_id ? [`Destination id: ${presentation.understood.resolved.destination_space_id}`] : []),
    ...(route?.directions.map((direction) => direction.text) ?? []),
    ...(route?.via.map((id) => `Via id: ${id}`) ?? []),
  ]

  useEffect(() => () => speechRef.current?.stop(), [])
  useEffect(() => {
    if (!transcript) speechRef.current?.stop()
  }, [transcript])

  const listen = () => {
    if (listening) {
      speechRef.current?.stop()
      setListening(false)
      return
    }
    const recognition = createSpeechRecognition()
    if (!recognition) {
      setSpeechNote(copy.speechUnavailable)
      return
    }
    recognition.lang = 'en-US'
    recognition.interimResults = false
    recognition.onresult = (event) => {
      const said = event.results[0]?.[0]?.transcript?.trim() ?? ''
      if (said) onQuery(said)
    }
    recognition.onerror = () => setSpeechNote(copy.speechUnavailable)
    recognition.onend = () => setListening(false)
    speechRef.current = recognition
    setSpeechNote(null)
    setListening(true)
    try {
      recognition.start()
    } catch {
      setListening(false)
      setSpeechNote(copy.speechUnavailable)
    }
  }

  return (
    <aside className="guide-panel" aria-label="Navigation guide">
      <div className="guide-heading">
        <span className="eyebrow">{copy.guideEyebrow}</span>
        <div className="guide-orbit" aria-hidden="true"><span /></div>
      </div>
      <h2>{copy.prompt}</h2>
      <div className="input-mode" role="group" aria-label="Input mode">
        <button type="button" aria-pressed={inputMode === 'text'} onClick={() => onInputMode('text')}>{copy.textMode}</button>
        <button type="button" aria-pressed={inputMode === 'transcript'} onClick={() => onInputMode('transcript')}>{copy.transcriptMode}</button>
      </div>
      <p className="guide-text">{transcript ? copy.transcriptModeHint : copy.textModeHint}</p>
      <form onSubmit={onSubmit} className="composer">
        {transcript && (
          <button type="button" className="listen-button" aria-pressed={listening} onClick={listen}>
            {listening ? copy.listening : copy.listen}
          </button>
        )}
        <input
          ref={fieldRef}
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder={copy.placeholder}
          aria-label={copy.prompt}
        />
        <button type="submit" aria-label={copy.findRoute}>→</button>
      </form>
      {speechNote && <p className="guide-text" role="status">{speechNote}</p>}
      <div className="guide-content" aria-live="polite">
        {presentation.alert && (
          <div role="alert" className={`notice ${presentation.alert.tone}`}>
            <span>{presentation.alert.tone === 'red' ? '!' : '?'}</span>
            <div>
              <strong>{presentation.alert.text}</strong>
              {presentation.guideText !== presentation.alert.text && <p>{presentation.guideText}</p>}
            </div>
          </div>
        )}
        {hereName && <p className="guide-text">{copy.youAreAt} {hereName}.</p>}
        {transcript && (confirmation || nextInstruction) && (
          <div className="transcript-lead">
            {confirmation && <p className="guide-text">{confirmation}</p>}
            {nextInstruction && <p className="transcript-next"><span className="eyebrow">{copy.nextInstruction}</span> {nextInstruction}</p>}
          </div>
        )}
        {transcript && detailLines.length > 0 && (
          <details className="fold">
            <summary>
              <span>
                <span className="eyebrow">{copy.spokenDetails}</span>
                <span className="fold-preview">{detailLines.length} lines</span>
              </span>
            </summary>
            <ol className="assumption-list">
              {detailLines.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}
            </ol>
          </details>
        )}
        {!transcript && presentation.understood && (
          <div className="understood">
            <span className="check" aria-hidden="true">✓</span>
            <div>
              <span className="eyebrow">{copy.understood}</span>
              <strong>{presentation.understood.summary}</strong>
            </div>
          </div>
        )}
        {!transcript && presentation.guideText && presentation.guideText !== presentation.alert?.text && !presentation.alert && (
          <p className="guide-text">{presentation.guideText}</p>
        )}
        {!transcript && assumptions && (
          <details className="fold">
            <summary>
              <span>
                <span className="eyebrow">{copy.assumptions}</span>
                <span className="fold-preview">{assumptions.preview}</span>
              </span>
            </summary>
            <ol className="assumption-list" start={2}>
              {assumptions.details.map((line) => <li key={line}>{line}</li>)}
            </ol>
          </details>
        )}
        {!transcript && routePreview && (
          <details className="fold">
            <summary>
              <span>
                <span className="eyebrow">{copy.route}</span>
                <span className="fold-preview">{routePreview}</span>
              </span>
            </summary>
            {route && route.directions.length > 0 && (
              <ol className="directions">
                {route.directions.map((direction, index) => (
                  <li key={direction.text} className={index === directionIndex ? 'current-step' : undefined}>{direction.text}</li>
                ))}
              </ol>
            )}
            {route && route.via.length > 0 && (
              <p className="guide-text">{copy.tourStops}: {route.via.map((id) => label(id)).join(' → ')}</p>
            )}
            {route && route.legs.length > 1 && (
              <div className="route-floors">
                <span className="eyebrow">{copy.routeFloors}</span>
                {route.legs.map((leg, index) => {
                  const floor = floors.find((item) => item.id === leg.floor_id)
                  const previous = route.legs[index - 1]
                  return (
                    <button type="button" key={`${leg.floor_id}-${index}`} onClick={() => onShowFloor(leg.floor_id)}>
                      {previous && previous.floor_id !== leg.floor_id ? `Change to ${floor?.name ?? leg.floor_id}` : (floor?.name ?? leg.floor_id)}
                    </button>
                  )
                })}
              </div>
            )}
            {route?.reachable && (
              <button type="button" className="secondary-action" onClick={onReplay}>{copy.replay} <span>↗</span></button>
            )}
          </details>
        )}
        {transcript && route?.reachable && (
          <button type="button" className="secondary-action" onClick={onReplay}>{copy.replay} <span>↗</span></button>
        )}
        {presentation.closedIds.length > 0 && !presentation.showDecision && (
          <button type="button" className="secondary-action" onClick={onReopen}>{copy.reopen}</button>
        )}
        {presentation.asks.map((ask) => (
          <div key={ask.question} className="ask-block">
            <div className="notice amber">
              <span>?</span>
              <div>
                <strong>{ask.question}</strong>
                <p>{copy.choosePlace}</p>
              </div>
            </div>
            {ask.options.length > 0 ? (
              <div className="choice-list">
                {ask.options.slice(0, 4).map((option) => (
                  <button type="button" key={option.id} onClick={() => onChoose(option)}>
                    {option.label}
                    <span>→</span>
                  </button>
                ))}
              </div>
            ) : (
              <QuestionField question={ask.question} onAskText={onAskText} />
            )}
          </div>
        ))}
        {presentation.showDecision && (
          <div className="confirm-row">
            <button type="button" className="primary-action" onClick={onConfirm}>{copy.confirm}</button>
            <button type="button" className="secondary-action" onClick={onCancel}>{copy.cancel}</button>
          </div>
        )}
      </div>
    </aside>
  )
}

function QuestionField({ question, onAskText }: { question: string; onAskText: (text: string) => void }) {
  const [value, setValue] = useState('')
  return (
    <form className="ask-field" onSubmit={(event) => { event.preventDefault(); if (value.trim()) onAskText(value.trim()) }}>
      <label>
        <span className="sr-only">{question}</span>
        <input value={value} onChange={(event) => setValue(event.target.value)} placeholder={copy.askInQuestion} aria-label={question} />
      </label>
      <button type="submit">{copy.findRoute}</button>
    </form>
  )
}
