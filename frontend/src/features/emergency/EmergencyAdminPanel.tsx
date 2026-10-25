import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/errors'
import { gateway } from '../../api/gateway'
import type { EmergencyPerson, EmergencyRoster } from '../../api/gateway'
import { clockLabel, personName, placeLabel, reasonText, secondsSince, statusLabel } from '../../domain/emergency'
import { copy, fill } from '../../i18n/en'
import type { AdminSession, EmergencyState } from './useEmergency'

const text = copy.emergency
const NAME_KEY = 'wayfinder-display-name'

type Props = {
  buildingId: string
  emergency: EmergencyState
  admin: AdminSession | null
  onAdmin: (admin: AdminSession | null) => void
  onShowPerson: (person: EmergencyPerson) => void
}

/** A change that needs admin rights; it waits for name + PIN when this device is not unlocked yet. */
type AdminAction = { kind: 'mark'; person: EmergencyPerson; note: string } | { kind: 'undo'; person: EmergencyPerson } | { kind: 'end' }

/** The user-facing sentence for a failed admin request; the UI branches on the stable error code. */
function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : copy.apiUnavailable
  switch (error.code) {
    case '10003_admin_disabled': return text.disabled
    case '10002_forbidden': return error.details.some((detail) => detail.field === 'pin') ? text.wrongPin : text.unlockAgain
    case '00002_rate_limited': return text.tooManyAttempts
    default: return error.message
  }
}

export function EmergencyAdminPanel({ buildingId, emergency, admin, onAdmin, onShowPerson }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [waiting, setWaiting] = useState<AdminAction | null>(null)
  const panelRef = useRef<HTMLElement>(null)
  const active = Boolean(emergency.roster)
  useEffect(() => { setError(null); setWaiting(null) }, [buildingId, active])
  // On phones the panel stacks below the map; bring it into view when it opens.
  useEffect(() => { if (window.matchMedia('(max-width: 800px)').matches) panelRef.current?.scrollIntoView({ block: 'start' }) }, [])

  /** Runs a request; a rejected token locks this device again, every failure is shown in place. */
  const run = async (task: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try { await task() } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.code === '10002_forbidden' && !caught.details.some((detail) => detail.field === 'pin')) onAdmin(null)
      setError(errorText(caught))
    } finally { setBusy(false) }
  }

  const unlock = async (name: string, pin: string): Promise<AdminSession> => {
    const token = await gateway.createAdminToken(pin, name)
    const session = { token: token.token, name: token.name }
    onAdmin(session)
    window.localStorage.setItem(NAME_KEY, token.name)  // the banner then knows this phone's owner
    return session
  }

  const perform = async (action: AdminAction, session: AdminSession) => {
    if (action.kind === 'mark') emergency.setRoster(await gateway.markOutside(buildingId, session.token, action.person.id, action.note))
    else if (action.kind === 'undo') {
      await gateway.clearOutsideMark(buildingId, session.token, action.person.id)
      emergency.setRoster(await gateway.listEmergencyPeople(buildingId))
    } else {
      await gateway.endEmergency(buildingId, session.token)
      emergency.setRoster(null)
    }
  }

  const request = (action: AdminAction) => {
    if (admin) void run(() => perform(action, admin))
    else { setError(null); setWaiting(action) }
  }

  const activate = (name: string, pin: string) => run(async () => {
    const session = admin ?? await unlock(name, pin)
    try { emergency.setRoster(await gateway.startEmergency(buildingId, session.token)) } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.code === '30020_emergency_already_active') { emergency.setRoster(await gateway.listEmergencyPeople(buildingId)); return }
      throw caught
    }
  })

  return (
    <section className="emergency-panel" ref={panelRef} aria-labelledby="emergency-title">
      <div className="emergency-panel-head">
        <h2 id="emergency-title">{active ? text.active + (reasonText(emergency.status?.reason) ? `: ${reasonText(emergency.status?.reason)}` : '') : text.title}</h2>
        {admin && <button type="button" className="text-action" onClick={() => onAdmin(null)}>{text.lock}</button>}
      </div>
      {admin && <p className="eyebrow">{fill(text.adminAs, { name: admin.name })}</p>}
      {error && <p className="emergency-error" role="alert">{error}</p>}
      {!active && <ActivateForm unlocked={Boolean(admin)} busy={busy} onActivate={activate} />}
      {active && waiting && (
        <UnlockForm busy={busy} intro={text.unlockFor[waiting.kind]} submitLabel={text.unlockAndContinue} onCancel={() => setWaiting(null)}
          onUnlock={(name, pin) => run(async () => { const session = await unlock(name, pin); const action = waiting; setWaiting(null); await perform(action, session) })} />
      )}
      {active && <ActiveList roster={emergency.roster!} failed={emergency.failed} busy={busy} onShowPerson={onShowPerson}
        onMark={(person, note) => request({ kind: 'mark', person, note })}
        onUndo={(person) => request({ kind: 'undo', person })}
        onEnd={() => request({ kind: 'end' })} />}
    </section>
  )
}

type UnlockProps = { busy: boolean; intro: string; submitLabel: string; danger?: boolean; onUnlock: (name: string, pin: string) => void; onCancel?: () => void }

/** Name + admin PIN. The PIN is sent once for a token and never stored. */
function UnlockForm({ busy, intro, submitLabel, danger = false, onUnlock, onCancel }: UnlockProps) {
  const pinId = useId()
  const nameId = useId()
  const [pin, setPin] = useState('')
  const [name, setName] = useState(() => window.localStorage.getItem(NAME_KEY) ?? '')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (pin && name.trim()) onUnlock(name.trim(), pin)
  }
  return (
    <form className="emergency-form" onSubmit={submit}>
      <p className="guide-text">{intro}</p>
      <label className="field-label" htmlFor={nameId}>{text.adminName}</label>
      <input id={nameId} value={name} maxLength={80} autoComplete="name" onChange={(event) => setName(event.target.value)} />
      <label className="field-label" htmlFor={pinId}>{text.pin}</label>
      <input id={pinId} type="password" inputMode="numeric" autoComplete="off" value={pin} maxLength={64} onChange={(event) => setPin(event.target.value)} />
      <div className="confirm-row">
        <button type="submit" className={danger ? 'danger-action' : 'primary-action'} disabled={busy || !pin || !name.trim()}>{submitLabel}</button>
        {onCancel && <button type="button" className="secondary-action" disabled={busy} onClick={onCancel}>{text.cancel}</button>}
      </div>
    </form>
  )
}

function ActivateForm({ unlocked, busy, onActivate }: { unlocked: boolean; busy: boolean; onActivate: (name: string, pin: string) => void }) {
  if (unlocked) {
    return (
      <div className="emergency-form">
        <p className="guide-text">{text.activateIntro}</p>
        <button type="button" className="danger-action emergency-activate" disabled={busy} onClick={() => onActivate('', '')}>{text.activate}</button>
      </div>
    )
  }
  return <UnlockForm busy={busy} intro={text.activateIntro} submitLabel={text.activate} danger onUnlock={onActivate} />
}

type ActiveProps = {
  roster: EmergencyRoster
  failed: boolean
  busy: boolean
  onShowPerson: (person: EmergencyPerson) => void
  onMark: (person: EmergencyPerson, note: string) => void
  onUndo: (person: EmergencyPerson) => void
  onEnd: () => void
}

function ActiveList({ roster, failed, busy, onShowPerson, onMark, onUndo, onEnd }: ActiveProps) {
  const [marking, setMarking] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [ending, setEnding] = useState(false)
  const endSafeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (ending) endSafeRef.current?.focus() }, [ending])
  const counts = roster.counts
  const now = Date.now()
  return (
    <>
      <div className="emergency-counts" role="status" aria-live="polite">
        <div className="emergency-count inside"><strong>{counts.inside}</strong><span>{text.inside}</span></div>
        <div className="emergency-count outside"><strong>{counts.outside}</strong><span>{text.outside}</span></div>
        <div className="emergency-count outside_manual"><strong>{counts.outside_manual}</strong><span>{text.markedOutside}</span></div>
      </div>
      <p className="field-hint">{fill(text.elapsed, { time: clockLabel(roster.elapsed_s) })} · {text.total}: {counts.total}{counts.stale > 0 && <> · {fill(text.staleCount, { count: counts.stale })}</>}</p>
      {failed && <p className="emergency-error" role="status">{text.listFailed}</p>}
      {roster.people.length === 0 && <p>{text.empty}</p>}
      <ul className="emergency-list">
        {roster.people.map((person) => (
          <li key={person.id} className={`emergency-row ${person.status}${person.stale ? ' stale' : ''}`}>
            <div className="emergency-row-main">
              <span className={`emergency-dot ${person.status}`} aria-hidden="true" />
              <div>
                {person.status === 'inside' && person.floor_id
                  ? <button type="button" className="emergency-person-name" title={text.showOnMap} onClick={() => onShowPerson(person)}>{personName(person)}<span className="sr-only"> — {text.showOnMap}</span></button>
                  : <strong>{personName(person)}</strong>}
                <span className="emergency-meta">
                  {statusLabel(person.status)} · {placeLabel(person)} · {person.kind === 'session' ? text.app : text.simulated}
                  {person.stale && <> · {fill(text.staleNote, { seconds: secondsSince(person.last_seen_at, now) })}</>}
                </span>
                {person.manual && <span className="emergency-meta">{fill(text.markedBy, { name: person.manual.marked_by })}{person.manual.note && `: ${person.manual.note}`}</span>}
              </div>
              {person.status === 'inside' && marking !== person.id && <button type="button" className="small-action" disabled={busy} onClick={() => { setMarking(person.id); setNote('') }}>{text.markOutside}</button>}
              {person.status === 'outside_manual' && <button type="button" className="text-action" disabled={busy} onClick={() => onUndo(person)}>{text.undo}</button>}
            </div>
            {marking === person.id && (
              <form className="inline-confirm" onSubmit={(event) => { event.preventDefault(); onMark(person, note.trim()); setMarking(null) }}>
                <p><strong>{fill(text.markQuestion, { name: personName(person) })}</strong></p>
                <input aria-label={text.note} placeholder={text.notePlaceholder} value={note} maxLength={200} autoFocus onChange={(event) => setNote(event.target.value)} />
                <div className="confirm-row">
                  <button type="submit" className="primary-action" disabled={busy}>{text.confirmMark}</button>
                  <button type="button" className="secondary-action" onClick={() => setMarking(null)}>{text.cancel}</button>
                </div>
              </form>
            )}
          </li>
        ))}
      </ul>
      {ending
        ? <div className="inline-confirm" role="group" aria-label={text.endQuestion}>
            <p><span aria-hidden="true">!</span><strong>{text.endQuestion}</strong></p>
            <div className="confirm-row">
              <button type="button" className="danger-action" disabled={busy} onClick={() => { onEnd(); setEnding(false) }}>{text.confirmEnd}</button>
              <button type="button" className="secondary-action" ref={endSafeRef} onClick={() => setEnding(false)}>{text.cancel}</button>
            </div>
          </div>
        : <button type="button" className="danger-action emergency-end" disabled={busy} onClick={() => setEnding(true)}>{text.end}</button>}
    </>
  )
}
