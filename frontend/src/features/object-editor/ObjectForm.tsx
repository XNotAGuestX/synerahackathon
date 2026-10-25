import { useEffect, useId, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ROTATE_STEP_DEG, round } from '../../domain/editor'
import type { ConnectorDraft, ObjectDraft, OpeningDraft } from '../../domain/editor'
import { copy, fill } from '../../i18n/en'
import { SupportPicker } from './SupportPicker'
import type { ObjectEditor } from './useObjectEditor'

const text = copy.editor

type NumberFieldProps = {
  label: string
  value: number
  step: number
  min?: number
  disabled?: boolean
  describedBy?: string
  onCommit: (value: number) => void
  children?: ReactNode
}

/** Number input that keeps the typed text ("0." etc.) and commits only valid numbers. */
function NumberField({ label, value, step, min, disabled, describedBy, onCommit, children }: NumberFieldProps) {
  const id = useId()
  const [draftText, setDraftText] = useState(String(round(value)))
  const [focused, setFocused] = useState(false)
  useEffect(() => { if (!focused) setDraftText(String(round(value))) }, [value, focused])
  const parsed = Number(draftText)
  const valid = draftText.trim() !== '' && Number.isFinite(parsed) && (min == null || parsed >= min)
  return (
    <div className="field">
      <label htmlFor={id} className="field-label">{label}</label>
      <div className="field-inline">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          value={draftText}
          disabled={disabled}
          aria-invalid={!valid}
          aria-describedby={describedBy}
          onFocus={() => setFocused(true)}
          onBlur={() => { setFocused(false); setDraftText(String(round(value))) }}
          onChange={(event) => {
            setDraftText(event.target.value)
            const next = Number(event.target.value)
            if (event.target.value.trim() !== '' && Number.isFinite(next) && (min == null || next >= min)) onCommit(next)
          }}
        />
        {children}
      </div>
    </div>
  )
}

function Actions({ editor }: { editor: ObjectEditor }) {
  return (
    <div className="editor-actions">
      <button type="submit" className="primary-action" disabled={!editor.canSave} aria-busy={editor.saving}>
        {editor.saving ? text.saving : text.save}
      </button>
      <button type="button" className="secondary-action" onClick={editor.cancelForm} disabled={editor.saving}>{text.cancel}</button>
    </div>
  )
}

function Hint({ id, invalid, message }: { id: string; invalid: boolean; message: string | null }) {
  if (!message) return null
  return (
    <p id={id} className={`editor-hint ${invalid ? 'invalid' : 'ok'}`} role="status">
      <span aria-hidden="true">{invalid ? '!' : '✓'}</span>
      <span>{message}</span>
    </p>
  )
}

function ObjectFields({ editor, draft }: { editor: ObjectEditor; draft: ObjectDraft }) {
  const hintId = useId()
  const keysId = useId()
  const nameId = useId()
  const disabled = editor.saving
  const position = draft.position ?? [0, 0]
  const hintMessage = editor.hint ?? (draft.position ? text.valid : null)
  return (
    <>
      <div className="field">
        <label htmlFor={nameId} className="field-label">{text.name}</label>
        <input id={nameId} value={draft.name} disabled={disabled} placeholder={editor.original ? text.namePlaceholder : editor.typeLabel} onChange={(event) => editor.updateObject({ name: event.target.value })} />
      </div>
      <div className="field">
        <span className="field-label">{text.type}</span>
        <div className="field-inline type-current">
          <strong>{editor.typeLabel}</strong>
          <span className="mono">{draft.category}</span>
          <button type="button" className="small-action" onClick={editor.startChangeType} disabled={disabled}>{text.changeType}</button>
        </div>
      </div>
      <div className="field">
        <span className="field-label">{text.room}</span>
        <output className={editor.draftRoomName ? 'field-value' : 'field-value invalid'}>{editor.draftRoomName ?? text.noRoom}</output>
      </div>
      <div className="field-row">
        <NumberField label={text.positionX} value={position[0]} step={0.1} disabled={disabled} describedBy={keysId} onCommit={(x) => editor.updateObject({ position: [x, position[1]] })} />
        <NumberField label={text.positionY} value={position[1]} step={0.1} disabled={disabled} describedBy={keysId} onCommit={(y) => editor.updateObject({ position: [position[0], y] })} />
      </div>
      <NumberField label={text.rotation} value={draft.rotation} step={ROTATE_STEP_DEG} disabled={disabled} onCommit={(rotation) => editor.updateObject({ rotation })}>
        <button type="button" className="small-action" onClick={() => editor.rotate(-ROTATE_STEP_DEG)} disabled={disabled}>{text.rotateLeft}</button>
        <button type="button" className="small-action" onClick={() => editor.rotate(ROTATE_STEP_DEG)} disabled={disabled}>{text.rotateRight}</button>
      </NumberField>
      <div className="field-row">
        <NumberField label={text.width} value={draft.width} step={0.05} min={0.05} disabled={disabled} onCommit={(width) => editor.updateObject({ width })} />
        <NumberField label={text.depth} value={draft.depth} step={0.05} min={0.05} disabled={disabled} onCommit={(depth) => editor.updateObject({ depth })} />
      </div>
      <NumberField label={text.height} value={editor.height.value} step={0.05} min={0.01} disabled={disabled} onCommit={(height) => editor.updateObject({ height })}>
        <span className={`status-chip ${editor.height.custom ? 'warn' : 'ok'}`}>{editor.height.custom ? text.heightCustom : text.heightDefault}</span>
        {editor.height.canReset && <button type="button" className="small-action" onClick={() => editor.updateObject({ height: null })} disabled={disabled}>{text.useDefault}</button>}
      </NumberField>
      <SupportPicker
        draft={draft}
        assets={editor.floorAssets}
        selected={editor.selectedSupports}
        excluded={editor.descendants}
        layerOf={editor.layerOf}
        elevation={editor.height.elevation}
        layer={editor.height.layer}
        disabled={disabled}
        onChange={editor.setSupports}
      />
      <p id={keysId} className="field-note">{text.keysHint}</p>
      <Hint id={hintId} invalid={Boolean(editor.hint)} message={hintMessage} />
    </>
  )
}

function OpeningFields({ editor, draft }: { editor: ObjectEditor; draft: OpeningDraft }) {
  const firstId = useId()
  const secondId = useId()
  const wallHintId = useId()
  const disabled = editor.saving
  const adding = !editor.original
  return (
    <>
      {adding && <p className="guide-text">{text.wallHint}</p>}
      {adding && <Hint id={wallHintId} invalid={editor.invalid} message={editor.wallText} />}
      {adding && (
        <div className="field-row">
          <div className="field">
            <label htmlFor={firstId} className="field-label">{text.firstRoom}</label>
            <select id={firstId} value={draft.firstSpace ?? ''} disabled={disabled} onChange={(event) => editor.chooseOpeningRooms(event.target.value || null, draft.secondSpace)}>
              <option value="">{text.chooseRoom}</option>
              {editor.currentSpaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor={secondId} className="field-label">{text.secondRoom}</label>
            <select id={secondId} value={draft.secondSpace ?? ''} disabled={disabled} onChange={(event) => editor.chooseOpeningRooms(draft.firstSpace, event.target.value || null)}>
              <option value="">{text.chooseRoom}</option>
              {editor.currentSpaces.filter((space) => space.id !== draft.firstSpace).map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
            </select>
          </div>
        </div>
      )}
      <div className="field">
        <span className="field-label" id={`${firstId}-kind`}>{text.kind}</span>
        <div className="segmented" role="group" aria-labelledby={`${firstId}-kind`}>
          <button type="button" aria-pressed={draft.kind === 'door'} disabled={disabled} onClick={() => editor.updateOpening({ kind: 'door' })}>{text.door}</button>
          <button type="button" aria-pressed={draft.kind === 'opening'} disabled={disabled} onClick={() => editor.updateOpening({ kind: 'opening' })}>{text.passage}</button>
        </div>
      </div>
      <NumberField label={text.width} value={draft.width} step={0.05} min={0.05} disabled={disabled} onCommit={(width) => editor.updateOpening({ width })} />
      <label className="check-field">
        <input type="checkbox" checked={draft.stepFree} disabled={disabled} onChange={(event) => editor.updateOpening({ stepFree: event.target.checked })} />
        <span>{text.stepFree}</span>
      </label>
    </>
  )
}

function ConnectorFields({ editor, draft }: { editor: ObjectEditor; draft: ConnectorDraft }) {
  const [room, setRoom] = useState('')
  const roomId = useId()
  const nameId = useId()
  const stopsHintId = useId()
  const disabled = editor.saving
  return (
    <>
      <p className="guide-text">{text.roomsHint}</p>
      <div className="field">
        <span className="field-label">{text.roomsChosen}</span>
        {editor.stops.length === 0 ? <p className="field-note">{text.roomsNone}</p> : (
          <ul className="chip-list" aria-label={text.roomsChosen}>
            {editor.stops.map((stop) => (
              <li key={stop.id} className="chip">
                <span>{stop.name}</span>
                <span className="chip-meta">{stop.floorName}</span>
                <button type="button" aria-label={fill(text.removeStop, { name: stop.name })} disabled={disabled} onClick={() => editor.pickStop(stop.id)}>×</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="field">
        <label htmlFor={roomId} className="field-label">{text.placeRoom}</label>
        <div className="field-inline">
          <select id={roomId} value={room} disabled={disabled} onChange={(event) => setRoom(event.target.value)}>
            <option value="">{text.chooseRoom}</option>
            {editor.currentSpaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
          </select>
          <button type="button" className="small-action" disabled={!room || disabled} onClick={() => { editor.pickStop(room); setRoom('') }}>{text.addStop}</button>
        </div>
      </div>
      {editor.stops.length < 2 && <Hint id={stopsHintId} invalid={false} message={text.roomsNeedTwo} />}
      <div className="field">
        <label htmlFor={nameId} className="field-label">{text.name}</label>
        <input id={nameId} value={draft.name} disabled={disabled} placeholder={text.namePlaceholder} onChange={(event) => editor.updateConnector({ name: event.target.value })} />
      </div>
      {draft.kind === 'lift'
        ? (
          <label className="check-field">
            <input type="checkbox" checked={draft.stepFree} disabled={disabled} onChange={(event) => editor.updateConnector({ stepFree: event.target.checked })} />
            <span>{text.stepFree}</span>
          </label>
        )
        : <p className="field-note">{text.stepFreeHint}</p>}
    </>
  )
}

/** The editor form for the current draft. Save = propose + confirm. */
export function ObjectForm({ editor }: { editor: ObjectEditor }) {
  const draft = editor.draft
  if (!draft) return null
  const submit = (event: FormEvent) => {
    event.preventDefault()
    editor.save()
  }
  return (
    <form className="editor-form" onSubmit={submit} aria-busy={editor.saving} noValidate>
      {draft.target === 'object' && <ObjectFields editor={editor} draft={draft} />}
      {draft.target === 'opening' && <OpeningFields editor={editor} draft={draft} />}
      {draft.target === 'connector' && <ConnectorFields editor={editor} draft={draft} />}
      <Actions editor={editor} />
    </form>
  )
}
