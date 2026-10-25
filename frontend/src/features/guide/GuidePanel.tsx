import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, RefObject } from 'react'
import { formatMetres } from '../../domain/presentation'
import type { ActionProposal, AskEffect, AskOption, ChatMessage, FloorSummary, Route } from '../../domain/types'
import { copy } from '../../i18n/en'
import { useDetailsDismiss } from '../../ui/useDetailsDismiss'
import type { VoiceState } from '../voice/useVoice'
import { RichText, hasNumberedSteps } from './RichText'
import { RouteShare } from './RouteShare'

export type VoicePanelState = {
  state: VoiceState
  level: number
  muted: boolean
  setMuted: (muted: boolean) => void
  error: string | null
}

const voiceLabels: Record<VoiceState, string> = {
  off: copy.voiceOff,
  listening: copy.voiceListening,
  hearing: copy.voiceHearing,
  transcribing: copy.voiceTranscribing,
  queued: copy.voiceQueued,
  thinking: copy.voiceThinking,
  speaking: copy.voiceSpeaking,
}

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

async function requestMicrophone(): Promise<string | null> {
  if (!window.isSecureContext) return copy.speechSecureContext
  if (!navigator.mediaDevices?.getUserMedia) return copy.speechMicrophoneUnavailable
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((track) => track.stop())
    return null
  } catch (error) {
    const name = error instanceof DOMException ? error.name : ''
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') return copy.speechPermissionDenied
    if (name === 'NotFoundError') return copy.speechMicrophoneUnavailable
    return copy.speechPermissionFailed
  }
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
  comparisonVisible?: boolean
  onClearComparison?: () => void
  query: string
  messages: ChatMessage[]
  busy: boolean
  ready: boolean
  connection: 'connecting' | 'connected' | 'offline' | 'local'
  /** Example questions that fit rooms the loaded building actually has. */
  suggestions: string[]
  stepFree: boolean
  activeRoute: Route | null
  shareUrl: string | null
  activeMessageId: string | null
  pendingActionId: string | null
  directionIndex: number
  onQuery: (value: string) => void
  onSubmit: (event: FormEvent) => void
  onChoose: (option: AskOption, role: 'start' | 'destination') => void
  onRetry: (message: ChatMessage) => void
  onConfirm: () => void
  onCancel: () => void
  onShowMap: () => void
  onShowFloor: (floorId: string) => void
  onAllowStairs: () => void
  onChooseStart: () => void
  inputMode: 'text' | 'transcript' | 'voice'
  onInputMode: (mode: 'text' | 'transcript' | 'voice') => void
  voice: VoicePanelState
  guidanceActive: boolean
  onStopGuidance: () => void
  inputRef: RefObject<HTMLTextAreaElement | null>
  floors: FloorSummary[]
  forklift: boolean
  onToggleStepFree: () => void
  onToggleForklift: () => void
}

export function readableDirection(text: string): string {
  return text.replace(/\s*\[[^\]]+\]/g, '')
}

function routeFloorNames(route: Route, floors: FloorSummary[]): string[] {
  return [...new Set(route.legs.map((leg) => floors.find((floor) => floor.id === leg.floor_id)?.name ?? 'Floor ' + leg.floor_level))]
}

function routeStatus(route: Route): string {
  if (!route.reachable) return 'Cannot reach destination'
  if (route.closed_ids.length > 0) return 'Rerouted around closure'
  return 'Route validated'
}

/** Changing the map (closing, removing) is confirmed with a danger button; other changes with the primary one. */
function destructive(proposal: ActionProposal | undefined): boolean {
  if (!proposal) return false
  return proposal.closed === true || /close|remove|delete/.test(proposal.kind)
}

const COMPOSER_MAX_PX = 160

export function GuidePanel({ comparisonVisible = false, onClearComparison, query, messages, busy, ready, connection, suggestions, stepFree, activeRoute, shareUrl, activeMessageId,
  pendingActionId, onQuery, onSubmit, onChoose, onRetry, onConfirm, onCancel,
  onShowMap, onShowFloor, onAllowStairs, onChooseStart, inputMode, onInputMode, voice, guidanceActive, onStopGuidance, inputRef, floors, forklift, onToggleStepFree, onToggleForklift }: GuidePanelProps) {
  const feedRef = useRef<HTMLDivElement>(null)
  const restrictionsRef = useDetailsDismiss()
  const activeRestrictions = Number(stepFree) + Number(forklift)
  const nearBottom = useRef(true)
  const speechRef = useRef<BrowserSpeech | null>(null)
  const [listening, setListening] = useState(false)
  const [speechNote, setSpeechNote] = useState<string | null>(null)
  const last = messages.at(-1)

  useEffect(() => {
    const feed = feedRef.current
    if (feed && (nearBottom.current || last?.role === 'user')) feed.scrollTop = feed.scrollHeight
  }, [messages, busy, last?.text])
  useEffect(() => () => speechRef.current?.stop(), [])
  // The composer grows with its text up to a limit, then scrolls.
  useLayoutEffect(() => {
    const box = inputRef.current
    if (!box) return
    box.style.height = 'auto'
    box.style.height = `${Math.min(box.scrollHeight, COMPOSER_MAX_PX)}px`
  }, [query, inputRef])

  const listen = async () => {
    if (listening) { speechRef.current?.stop(); setListening(false); return }
    const recognition = createSpeechRecognition()
    if (!recognition) { inputRef.current?.focus(); setSpeechNote(copy.speechUnavailable); return }
    const error = await requestMicrophone()
    if (error) { setSpeechNote(error); return }
    recognition.lang = 'en-US'
    recognition.interimResults = false
    recognition.onresult = (event) => {
      const text = event.results[0]?.[0]?.transcript?.trim()
      if (text) onQuery(text)
    }
    recognition.onerror = () => setSpeechNote(copy.speechKeyboardHint)
    recognition.onend = () => setListening(false)
    speechRef.current = recognition
    setSpeechNote(null)
    setListening(true)
    try { recognition.start() } catch { setListening(false); setSpeechNote(copy.speechUnavailable) }
  }

  const suggest = (text: string) => { onQuery(text); requestAnimationFrame(() => inputRef.current?.focus()) }
  const offline = connection === 'offline'
  const connecting = connection === 'connecting'

  return <aside className="chat-panel" aria-label="Building chat">
    <header className="chat-heading">
      <div className="chat-title"><span className="chat-avatar" aria-hidden="true"><svg viewBox="0 0 24 24" width="18" height="18"><path d="M4 5h16v11H9l-5 4V5Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg></span><div><h2>{copy.guideTitle}</h2><p>{busy ? copy.guideBusy : copy.guideIntro}</p></div></div>
      <div className="input-mode segmented" role="group" aria-label="Input mode"><button type="button" aria-pressed={inputMode === 'text'} onClick={() => onInputMode('text')}>{copy.textMode}</button><button type="button" aria-pressed={inputMode === 'transcript'} onClick={() => onInputMode('transcript')}>{copy.transcriptMode}</button><button type="button" aria-pressed={inputMode === 'voice'} onClick={() => onInputMode('voice')}>{copy.voiceMode}</button></div>
      <details ref={restrictionsRef} className="route-restrictions">
        <summary>{copy.restrictions}{activeRestrictions > 0 && <span className="route-restrictions-count">{activeRestrictions}</span>}</summary>
        <fieldset className="route-restrictions-panel">
          <legend className="sr-only">{copy.restrictions}</legend>
          <label className="check-field"><input type="checkbox" checked={stepFree} disabled={busy} onChange={onToggleStepFree} /><span>{copy.stepFree}</span></label>
          <label className="check-field" title={copy.forkliftHint}><input type="checkbox" checked={forklift} onChange={onToggleForklift} /><span>{copy.forklift}</span></label>
        </fieldset>
      </details>
    </header>
    {inputMode === 'voice' && <div className="voice-bar chat-voice-bar">
      <span className={`voice-pill ${voice.muted ? 'muted' : voice.state}`} role="status">{voice.muted ? copy.voiceMuted : voiceLabels[voice.state]}</span>
      <span className="voice-meter" aria-hidden="true"><span style={{ transform: `scaleX(${voice.muted ? 0 : voice.level})` }} /></span>
      <button type="button" className="small-action" aria-pressed={voice.muted} onClick={() => voice.setMuted(!voice.muted)}>{voice.muted ? copy.voiceUnmute : copy.voiceMute}</button>
      {guidanceActive && <button type="button" className="small-action" onClick={onStopGuidance}>{copy.stopGuidance}</button>}
      {voice.error ? <p className="chat-voice-note" role="alert">{voice.error}</p> : <p className="chat-voice-note">{copy.voiceModeHint}</p>}
    </div>}
    {inputMode !== 'voice' && guidanceActive && <div className="voice-bar chat-voice-bar"><button type="button" className="small-action" onClick={onStopGuidance}>{copy.stopGuidance}</button></div>}
    <div ref={feedRef} className="chat-feed" role="log" aria-label="Conversation"
      onScroll={() => { const feed = feedRef.current; if (feed) nearBottom.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80 }}>
      {messages.length === 0 && <div className="chat-welcome">
        {connecting ? <p>{copy.connectingBuilding}</p>
          : offline ? <><h3>{copy.offline}</h3><p>{copy.offlineBody}</p></>
            : <>
              <h3>{copy.welcomeTitle}</h3>
              <p>{suggestions.length ? copy.welcomeBody : 'Tell me your starting room and what you need. For example: “I’m in Office 1.04. Take me to the nearest coffee machine.”'}</p>
              {suggestions.length > 0 && <ul className="chat-suggestions">{suggestions.map((text) => <li key={text}><button type="button" onClick={() => suggest(text)}>{text}</button></li>)}</ul>}
            </>}
      </div>}
      {messages.map((message, messageIndex) => {
        const reply = message.reply
        const asks = reply?.effects.filter((effect): effect is AskEffect => effect.type === 'ask' && Array.isArray(effect.options)) ?? []
        const active = message.id === activeMessageId
        const route = reply?.routes.at(-1)
        const isCurrentRoute = route?.id === activeRoute?.id
        const actionActive = Boolean(active && reply?.pending && reply.pending.id === pendingActionId)
        const role = reply?.understood?.missing.includes('start') ? 'start' : 'destination'
        // Steps already written in the reply are not listed a second time in the route card.
        const stepsInText = hasNumberedSteps(message.text)
        const previousRoute = isCurrentRoute && route?.closed_ids.length && route.reachable
          ? messages.slice(0, messageIndex).flatMap((item) => item.reply?.routes ?? []).reverse().find((item) => item.reachable && item.id !== route.id && item.length_m !== null)
          : null
        return <article key={message.id} className={`chat-message ${message.role === 'user' ? 'chat-outgoing' : 'chat-incoming'}`} data-message-id={message.id} data-delivery={message.delivery ?? 'sent'} aria-label={message.role === 'user' ? 'Your message' : 'Guide reply'}>
          <p className="chat-text">{message.role === 'guide' ? <RichText text={message.text} /> : message.text}</p>
          {route && <div className={`chat-route-card${route.reachable ? '' : ' is-unreachable'}`}>
            <strong>{route.reachable ? route.length_m === 0 ? 'You’re already here' : formatMetres(route.length_m) : 'No route available'}</strong>
            <span>{route.step_free ? 'Step-free' : 'Stairs allowed'}</span>
            <div className="route-task-summary" data-route-status={route.reachable ? 'valid' : 'blocked'}>
              <div className="route-task-heading"><span className="route-status-mark" aria-hidden="true">{route.reachable ? '✓' : '!'}</span><strong>{routeStatus(route)}</strong></div>
              <div className="route-task-grid">
                <span><small>Floors</small><b>{route.reachable ? routeFloorNames(route, floors).join(' → ') || 'Single floor' : 'Not connected'}</b></span>
                <span><small>Constraint</small><b>{route.step_free ? 'No stairs' : 'Stairs allowed'}</b></span>
                <span><small>Connectors</small><b>{route.via.length > 0 ? route.via.join(' · ') : 'Direct path'}</b></span>
                <span><small>Closures</small><b>{route.closed_ids.length > 0 ? route.closed_ids.length + ' active' : 'None'}</b></span>
              </div>
              {!route.reachable && <p className="route-task-reason">No valid opening or connector satisfies the current route constraints.</p>}
              {route.reachable && route.closed_ids.length > 0 && <p className="route-task-reason">The original path was unavailable. This route avoids: {route.closed_ids.join(', ')}.</p>}
            </div>
            {isCurrentRoute && previousRoute && route.length_m !== null && previousRoute.length_m !== null && <div className="route-change-summary" role="status">
              <span className="route-change-label">Closure impact</span>
              <div><strong>{formatMetres(previousRoute.length_m)}</strong><span> before</span><span className="route-change-arrow" aria-hidden="true">→</span><strong>{formatMetres(route.length_m)}</strong><span> now</span></div>
              <b className={route.length_m > previousRoute.length_m ? 'route-change-increase' : 'route-change-decrease'}>{route.length_m >= previousRoute.length_m ? '+' : ''}{formatMetres(route.length_m - previousRoute.length_m)}</b>
            </div>}
            {isCurrentRoute && comparisonVisible && previousRoute && onClearComparison && <button type="button" className="route-clear-comparison" onClick={onClearComparison}>Clear previous route</button>}
            {isCurrentRoute && route.reachable && <button type="button" className="route-show" onClick={onShowMap}>{copy.showRoute}</button>}
            {isCurrentRoute && shareUrl && <RouteShare key={shareUrl} url={shareUrl} />}
            {isCurrentRoute && !route.reachable && <div className="chat-route-recovery">
              {stepFree && <button type="button" className="small-action is-primary" disabled={busy} onClick={onAllowStairs}>{copy.allowStairs}</button>}
              <button type="button" className="small-action" disabled={busy} onClick={onChooseStart}>{copy.chooseStart}</button>
            </div>}
            {route.directions.length > 0 && !stepsInText && <details><summary>{copy.directions}</summary><ol>{route.directions.map((direction, index) => <li key={index}><span className="route-step-number">{index + 1}</span><span><b>{floors.find((floor) => floor.id === direction.floor_id)?.name ?? 'Floor'}</b>{readableDirection(direction.text)}</span></li>)}</ol></details>}
            {isCurrentRoute && route.legs.length > 1 && <div className="chat-floor-links">{[...new Set(route.legs.map((leg) => leg.floor_id))].map((id) => <button type="button" key={id} onClick={() => onShowFloor(id)}>{floors.find((floor) => floor.id === id)?.name ?? 'Show floor'}</button>)}</div>}
          </div>}
          {active && asks.map((ask, index) => <div className="chat-choices" key={index}>
            {ask.question !== message.text && <p>{ask.question}</p>}
            {ask.options.slice(0, 4).map((option) => <button key={option.id} type="button" disabled={busy} onClick={() => onChoose(option, role)}>{option.label}</button>)}
          </div>)}
          {reply?.pending && (actionActive || reply.pending.status !== 'pending') && <div className="chat-confirmation">{actionActive ? <><p>{reply.pending.summary}</p><div className="chat-confirmation-actions"><button type="button" className={`small-action ${destructive(reply.pending.proposal) ? 'is-danger' : 'is-primary'}`} disabled={busy} onClick={onConfirm}>{copy.confirm}</button><button type="button" className="small-action" disabled={busy} onClick={onCancel}>{copy.cancel}</button></div></> : <span>Action {reply.pending.status}</span>}</div>}
          {message.delivery === 'failed' && <div className="chat-send-error" role="alert"><span>{message.error ?? 'Message was not sent.'}</span><button type="button" disabled={busy} onClick={() => onRetry(message)}>Retry</button></div>}
          <footer className="chat-message-meta"><time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>{message.role === 'user' && <span>{message.delivery === 'sending' ? 'Sending…' : message.delivery === 'failed' ? 'Not sent' : '✓'}</span>}</footer>
        </article>
      })}
      {busy && <p className="chat-typing">{copy.typing}<span aria-hidden="true">…</span></p>}
    </div>
    <form onSubmit={onSubmit} className="chat-composer">
      {inputMode === 'transcript' && <button type="button" className="chat-microphone small-action" aria-label={listening ? 'Stop listening' : 'Dictate message'} aria-pressed={listening} onClick={listen}>{listening ? copy.stopDictation : copy.dictate}</button>}
      <textarea ref={inputRef} value={query} rows={2} maxLength={4000} placeholder={ready ? 'Ask your building…' : offline ? copy.offline : copy.connectingBuilding} disabled={offline} aria-label="Message your building" onChange={(event) => onQuery(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!busy && ready && query.trim()) event.currentTarget.form?.requestSubmit() } }} />
      <button type="submit" className="chat-send" disabled={busy || !ready || !query.trim()} aria-label="Send message">{copy.send}</button>
      {speechNote && <p className="chat-speech-note" role="status">{speechNote}</p>}
    </form>
  </aside>
}
