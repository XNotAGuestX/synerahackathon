import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/errors'
import { gateway } from '../../api/gateway'
import type { EmergencyChallenge, EmergencyPerson, EmergencyRoster, EmergencyStatus } from '../../api/gateway'
import { clockLabel, personName, placeLabel, secondsSince, statusLabel } from '../../domain/emergency'
import { copy, fill } from '../../i18n/en'
import type { AdminSession } from './useEmergency'

const text = copy.emergency

type Props = {
  buildingId: string
  status: EmergencyStatus | null
  onStatus: (status: EmergencyStatus) => void
  admin: AdminSession | null
  onAdmin: (admin: AdminSession | null) => void
  roster: EmergencyRoster | null
  onRoster: (roster: EmergencyRoster | null) => void
  rosterFailed: boolean
}

/** The user-facing sentence for an admin request that failed; the UI branches on the stable error code. */
function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : copy.apiUnavailable
  switch (error.code) {
    case '10003_admin_disabled': return text.disabled
    case '10002_forbidden': return error.details.some((detail) => detail.field === 'pin') ? text.wrongPin : error.message
    case '00002_rate_limited': return text.tooManyAttempts
    case '30021_challenge_invalid': return text.codeInvalid
    default: return error.message
  }
}

export function EmergencyAdminPanel({ buildingId, status, onStatus, admin, onAdmin, roster, onRoster, rosterFailed }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const panelRef = useRef<HTMLElement>(null)
  useEffect(() => setError(null), [buildingId, admin?.token, status?.active])
  // On phones the panel stacks below the map; bring it into view when it opens.
  useEffect(() => { if (window.matchMedia('(max-width: 800px)').matches) panelRef.current?.scrollIntoView({ block: 'start' }) }, [])

  /** Runs an admin request; a rejected token locks the view, every other failure is shown in place. */
  const run = async (task: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try { await task() } catch (caught: unknown) {
      if (caught instanceof ApiError && caught.code === '10002_forbidden' && admin && !caught.details.some((detail) => detail.field === 'pin')) onAdmin(null)
      setError(errorText(caught))
    } finally { setBusy(false) }
  }

  let body
  if (!admin) body = <UnlockForm busy={busy} onUnlock={(pin, name) => run(async () => {
    const token = await gateway.createAdminToken(pin, name)
    onAdmin({ token: token.token, name: token.name })
  })} />
  else if (!status?.active) body = <ActivateForm buildingId={buildingId} token={admin.token} busy={busy} run={run} onStarted={(started) => {
    onRoster(started)
    onStatus({ building_id: started.building_id, active: true, reason: started.reason, started_at: started.started_at })
  }} onAlreadyActive={async () => onStatus(await gateway.getEmergency(buildingId))} />
  else body = <ActiveList roster={roster} failed={rosterFailed} busy={busy}
    onMark={(person, note) => run(async () => { onRoster(await gateway.markOutside(buildingId, admin.token, person.id, note)) })}
    onUndo={(person) => run(async () => {
      await gateway.clearOutsideMark(buildingId, admin.token, person.id)
      onRoster(await gateway.listEmergencyPeople(buildingId, admin.token))
    })}
    onEnd={() => run(async () => {
      await gateway.endEmergency(buildingId, admin.token)
      onRoster(null)
      onStatus({ building_id: buildingId, active: false, reason: null, started_at: null })
    })} />

  return (
    <section className="emergency-panel" ref={panelRef} aria-labelledby="emergency-title">
      <div className="emergency-panel-head">
        <h2 id="emergency-title">{status?.active ? fill(text.active, { reason: status.reason ?? '' }) : text.title}</h2>
        {admin && <button type="button" className="text-action" onClick={() => onAdmin(null)}>{text.lock}</button>}
      </div>
      {admin && <p className="eyebrow">{fill(text.adminAs, { name: admin.name })}</p>}
      {error && <p className="emergency-error" role="alert">{error}</p>}
      {body}
    </section>
  )
}

function UnlockForm({ busy, onUnlock }: { busy: boolean; onUnlock: (pin: string, name: string) => void }) {
  const pinId = useId()
  const nameId = useId()
  const [pin, setPin] = useState('')
  const [name, setName] = useState(() => window.localStorage.getItem('wayfinder-display-name') ?? '')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (pin && name.trim()) onUnlock(pin, name.trim())
  }
  return (
    <form className="emergency-form" onSubmit={submit}>
      <p className="guide-text">{text.lockedIntro}</p>
      <label className="field-label" htmlFor={nameId}>{text.adminName}</label>
      <input id={nameId} value={name} maxLength={80} autoComplete="name" onChange={(event) => setName(event.target.value)} />
      <label className="field-label" htmlFor={pinId}>{text.pin}</label>
      <input id={pinId} type="password" inputMode="numeric" autoComplete="off" value={pin} maxLength={64} onChange={(event) => setPin(event.target.value)} />
      <button type="submit" className="primary-action" disabled={busy || !pin || !name.trim()}>{text.unlock}</button>
    </form>
  )
}

type ActivateProps = {
  buildingId: string
  token: string
  busy: boolean
  run: (task: () => Promise<void>) => Promise<void>
  onStarted: (roster: EmergencyRoster) => void
  onAlreadyActive: () => Promise<void>
}

/** Two steps against accidental alarms: the server shows a one-time code and the admin types it back. */
function ActivateForm({ buildingId, token, busy, run, onStarted, onAlreadyActive }: ActivateProps) {
  const reasonId = useId()
  const codeId = useId()
  const [reason, setReason] = useState<string>(text.reasonDefault)
  const [challenge, setChallenge] = useState<EmergencyChallenge | null>(null)
  const [code, setCode] = useState('')
  const codeRef = useRef<HTMLInputElement>(null)
  useEffect(() => { if (challenge) codeRef.current?.focus() }, [challenge])

  const prepare = () => run(async () => {
    setCode('')
    try { setChallenge(await gateway.createEmergencyChallenge(buildingId, token)) } catch (error: unknown) {
      if (error instanceof ApiError && error.code === '30020_emergency_already_active') { await onAlreadyActive(); return }
      throw error
    }
  })
  const activate = (event: FormEvent) => {
    event.preventDefault()
    if (!challenge) return
    void run(async () => {
      try { onStarted(await gateway.startEmergency(buildingId, token, challenge.id, code, reason.trim() || text.reasonDefault)) } catch (error: unknown) {
        if (error instanceof ApiError && error.code === '30021_challenge_invalid') setChallenge(null)  // one attempt per code
        if (error instanceof ApiError && error.code === '30020_emergency_already_active') { await onAlreadyActive(); return }
        throw error
      }
    })
  }

  return (
    <form className="emergency-form" onSubmit={activate}>
      <label className="field-label" htmlFor={reasonId}>{text.reason}</label>
      <input id={reasonId} value={reason} maxLength={200} onChange={(event) => setReason(event.target.value)} />
      {!challenge
        ? <button type="button" className="danger-action" disabled={busy || !reason.trim()} onClick={() => { void prepare() }}>{text.prepare}</button>
        : <>
            <p className="guide-text">{text.codeIntro}</p>
            <p className="emergency-code" aria-label={challenge.code.split('').join(' ')}>{challenge.code}</p>
            <label className="field-label" htmlFor={codeId}>{text.codeLabel}</label>
            <input id={codeId} ref={codeRef} className="emergency-code-input" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))} />
            <p className="field-hint">{text.codeValid}</p>
            <div className="confirm-row">
              <button type="submit" className="danger-action" disabled={busy || code.length !== 6}>{text.activate}</button>
              <button type="button" className="secondary-action" disabled={busy} onClick={() => setChallenge(null)}>{text.cancel}</button>
            </div>
          </>}
      {!challenge && <p className="field-hint">{text.codeValid}</p>}
    </form>
  )
}

type ActiveProps = {
  roster: EmergencyRoster | null
  failed: boolean
  busy: boolean
  onMark: (person: EmergencyPerson, note: string) => void
  onUndo: (person: EmergencyPerson) => void
  onEnd: () => void
}

function ActiveList({ roster, failed, busy, onMark, onUndo, onEnd }: ActiveProps) {
  const [marking, setMarking] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [ending, setEnding] = useState(false)
  const endSafeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (ending) endSafeRef.current?.focus() }, [ending])
  if (!roster) return <p role="status">{copy.working}</p>
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
                <strong>{personName(person)}</strong>
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
