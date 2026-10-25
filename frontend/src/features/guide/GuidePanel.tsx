import { useEffect, useRef, useState } from 'react'
import type { FormEvent, RefObject } from 'react'
import { formatMetres } from '../../domain/presentation'
import type { AskEffect, AskOption, ChatMessage, FloorSummary, Route } from '../../domain/types'
import { copy } from '../../i18n/en'
import type { VoiceState } from '../voice/useVoice'

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
  query: string
  messages: ChatMessage[]
  busy: boolean
  ready: boolean
  activeRoute: Route | null
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
  inputMode: 'text' | 'transcript' | 'voice'
  onInputMode: (mode: 'text' | 'transcript' | 'voice') => void
  voice: VoicePanelState
  guidanceActive: boolean
  onStopGuidance: () => void
  inputRef: RefObject<HTMLTextAreaElement | null>
  floors: FloorSummary[]
}

export function readableDirection(text: string): string {
  return text.replace(/\s*\[[^\]]+\]/g, '')
}

export function GuidePanel({ query, messages, busy, ready, activeRoute, activeMessageId,
  pendingActionId, onQuery, onSubmit, onChoose, onRetry, onConfirm, onCancel,
  onShowMap, onShowFloor, inputMode, onInputMode, voice, guidanceActive, onStopGuidance, inputRef, floors }: GuidePanelProps) {
  const feedRef = useRef<HTMLDivElement>(null)
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

  return <aside className="chat-panel" aria-label="Building chat">
    <header className="chat-heading"><span className="chat-avatar" aria-hidden="true">W</span><div><h2>Your building guide</h2><p>{busy ? 'Finding an answer…' : 'Ask a question or tell me where you want to go.'}</p></div>
      <div className="input-mode" role="group" aria-label="Input mode"><button type="button" aria-pressed={inputMode === 'text'} onClick={() => onInputMode('text')}>{copy.textMode}</button><button type="button" aria-pressed={inputMode === 'transcript'} onClick={() => onInputMode('transcript')}>{copy.transcriptMode}</button><button type="button" aria-pressed={inputMode === 'voice'} onClick={() => onInputMode('voice')}>{copy.voiceMode}</button></div></header>
    {inputMode === 'voice' && <div className="voice-bar chat-voice-bar">
      <span className={`voice-pill ${voice.muted ? 'muted' : voice.state}`} role="status">{voice.muted ? copy.voiceMuted : voiceLabels[voice.state]}</span>
      <span className="voice-meter" aria-hidden="true"><span style={{ transform: `scaleX(${voice.muted ? 0 : voice.level})` }} /></span>
      <button type="button" aria-pressed={voice.muted} onClick={() => voice.setMuted(!voice.muted)}>{voice.muted ? copy.voiceUnmute : copy.voiceMute}</button>
      {guidanceActive && <button type="button" onClick={onStopGuidance}>{copy.stopGuidance}</button>}
      {voice.error ? <p className="chat-voice-note" role="alert">{voice.error}</p> : <p className="chat-voice-note">{copy.voiceModeHint}</p>}
    </div>}
    {inputMode !== 'voice' && guidanceActive && <div className="voice-bar chat-voice-bar"><button type="button" onClick={onStopGuidance}>{copy.stopGuidance}</button></div>}
    <div ref={feedRef} className="chat-feed" role="log" aria-label="Conversation" aria-live="polite"
      onScroll={() => { const feed = feedRef.current; if (feed) nearBottom.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80 }}>
      {messages.length === 0 && <div className="chat-welcome"><h3>Where would you like to go?</h3><p>Tell me your starting room and what you need. For example: “I’m in Office 1.04. Take me to the nearest coffee machine.”</p></div>}
      {messages.map((message) => {
        const reply = message.reply
        const asks = reply?.effects.filter((effect): effect is AskEffect => effect.type === 'ask' && Array.isArray(effect.options)) ?? []
        const active = message.id === activeMessageId
        const route = reply?.routes.at(-1)
        const isCurrentRoute = route?.id === activeRoute?.id
        const actionActive = Boolean(active && reply?.pending && reply.pending.id === pendingActionId)
        const role = reply?.understood?.missing.includes('start') ? 'start' : 'destination'
        return <article key={message.id} className={`chat-message ${message.role === 'user' ? 'chat-outgoing' : 'chat-incoming'}`} data-message-id={message.id} data-delivery={message.delivery ?? 'sent'} aria-label={message.role === 'user' ? 'Your message' : 'Guide reply'}>
          <p className="chat-text">{message.text}</p>
          {route && <div className="chat-route-card">
            <strong>{route.reachable ? route.length_m === 0 ? 'You’re already here' : formatMetres(route.length_m) : 'No route available'}</strong>
            <span>{route.step_free ? 'Step-free' : 'Stairs allowed'}</span>
            {isCurrentRoute && route.reachable && <button type="button" onClick={onShowMap}>View route ↗</button>}
            {route.directions.length > 0 && <details><summary>Directions</summary><ol>{route.directions.map((direction, index) => <li key={index}>{readableDirection(direction.text)}</li>)}</ol></details>}
            {isCurrentRoute && route.legs.length > 1 && <div className="chat-floor-links">{[...new Set(route.legs.map((leg) => leg.floor_id))].map((id) => <button type="button" key={id} onClick={() => onShowFloor(id)}>{floors.find((floor) => floor.id === id)?.name ?? 'Show floor'}</button>)}</div>}
          </div>}
          {active && asks.map((ask, index) => <div className="chat-choices" key={index}>
            {ask.question !== message.text && <p>{ask.question}</p>}
            {ask.options.slice(0, 4).map((option) => <button key={option.id} type="button" disabled={busy} onClick={() => onChoose(option, role)}>{option.label}</button>)}
          </div>)}
          {reply?.pending && (actionActive || reply.pending.status !== 'pending') && <div className="chat-confirmation">{actionActive ? <><p>{reply.pending.summary}</p><button type="button" disabled={busy} onClick={onConfirm}>Confirm</button><button type="button" disabled={busy} onClick={onCancel}>Cancel</button></> : <span>Action {reply.pending.status}</span>}</div>}
          {message.delivery === 'failed' && <div className="chat-send-error" role="alert"><span>{message.error ?? 'Message was not sent.'}</span><button type="button" disabled={busy} onClick={() => onRetry(message)}>Retry</button></div>}
          <footer className="chat-message-meta"><time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>{message.role === 'user' && <span>{message.delivery === 'sending' ? 'Sending…' : message.delivery === 'failed' ? 'Not sent' : '✓'}</span>}</footer>
        </article>
      })}
      {busy && <p className="chat-typing" role="status">Guide is typing<span aria-hidden="true">…</span></p>}
    </div>
    <form onSubmit={onSubmit} className="chat-composer">
      {inputMode === 'transcript' && <button type="button" className="chat-microphone" aria-label={listening ? 'Stop listening' : 'Dictate message'} aria-pressed={listening} onClick={listen}>🎙</button>}
      <textarea ref={inputRef} value={query} rows={2} maxLength={4000} placeholder="Ask your building…" aria-label="Message your building" onChange={(event) => onQuery(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!busy && ready && query.trim()) event.currentTarget.form?.requestSubmit() } }} />
      <button type="submit" className="chat-send" disabled={busy || !ready || !query.trim()} aria-label="Send message">↑</button>
      {speechNote && <p className="chat-speech-note" role="status">{speechNote}</p>}
    </form>
  </aside>
}
