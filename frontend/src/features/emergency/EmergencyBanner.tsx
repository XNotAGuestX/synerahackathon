import { useEffect, useId, useState } from 'react'
import type { FormEvent } from 'react'
import { gateway } from '../../api/gateway'
import type { EmergencyStatus } from '../../api/gateway'
import { copy, fill } from '../../i18n/en'

const text = copy.emergency
const NAME_KEY = 'wayfinder-display-name'

/** Shown on every phone while the building's alarm is active. Asks once for a name the admins see in the list. */
export function EmergencyBanner({ status, sessionId }: { status: EmergencyStatus; sessionId: string }) {
  const inputId = useId()
  const [name, setName] = useState(() => window.localStorage.getItem(NAME_KEY) ?? '')
  const [draft, setDraft] = useState(name)
  const realSession = Boolean(sessionId) && !sessionId.startsWith('local-')

  // A new session (building change, reload) does not know the name yet.
  useEffect(() => {
    if (realSession && name) void gateway.putProfile(sessionId, name).catch(() => undefined)
  }, [realSession, sessionId, name])

  const save = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = draft.trim()
    if (!trimmed) return
    window.localStorage.setItem(NAME_KEY, trimmed)
    setName(trimmed)
  }

  return (
    <section className="emergency-banner" role="alert" aria-live="assertive">
      <p><strong>{text.bannerTitle}: {status.reason}</strong> {text.bannerBody}</p>
      {realSession && (name
        ? <p className="emergency-banner-name">{fill(text.nameShared, { name })}</p>
        : <form className="emergency-name-form" onSubmit={save}>
            <label htmlFor={inputId}>{text.namePrompt}</label>
            <div className="field-inline">
              <input id={inputId} value={draft} maxLength={60} autoComplete="name" placeholder={text.namePlaceholder} onChange={(event) => setDraft(event.target.value)} />
              <button type="submit" className="small-action" disabled={!draft.trim()}>{text.nameSave}</button>
            </div>
          </form>)}
    </section>
  )
}
