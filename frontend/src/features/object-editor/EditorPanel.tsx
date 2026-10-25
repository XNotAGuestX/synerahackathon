import { useEffect, useId, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { copy, fill } from '../../i18n/en'
import { ObjectForm } from './ObjectForm'
import { TypePicker } from './TypePicker'
import type { ObjectEditor } from './useObjectEditor'

const text = copy.editor

type InlineConfirmProps = {
  question: string
  confirmLabel: string
  cancelLabel: string
  busy: boolean
  safeRef: RefObject<HTMLButtonElement | null>
  onConfirm: () => void
  onCancel: () => void
}

/** Inline question instead of window.confirm. Focus starts on the safe choice. */
function InlineConfirm({ question, confirmLabel, cancelLabel, busy, safeRef, onConfirm, onCancel }: InlineConfirmProps) {
  const questionId = useId()
  return (
    <div className="inline-confirm" role="group" aria-labelledby={questionId}>
      <p id={questionId}><span aria-hidden="true">!</span><strong>{question}</strong></p>
      <div className="confirm-row">
        <button type="button" className="danger-action" onClick={onConfirm} disabled={busy} aria-busy={busy}>{busy ? text.saving : confirmLabel}</button>
        <button type="button" className="secondary-action" ref={safeRef} onClick={onCancel} disabled={busy}>{cancelLabel}</button>
      </div>
    </div>
  )
}

function PlaceStep({ editor }: { editor: ObjectEditor }) {
  const [room, setRoom] = useState('')
  const roomId = useId()
  return (
    <div className="editor-step">
      <p className="guide-text">{text.placeHint}</p>
      <form className="field" onSubmit={(event) => { event.preventDefault(); if (room) editor.placeInSpace(room) }}>
        <label htmlFor={roomId} className="field-label">{text.placeRoom}</label>
        <div className="field-inline">
          <select id={roomId} value={room} onChange={(event) => setRoom(event.target.value)}>
            <option value="">{text.chooseRoom}</option>
            {editor.currentSpaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
          </select>
          <button type="submit" className="small-action" disabled={!room}>{text.placeInRoom}</button>
        </div>
      </form>
      <button type="button" className="text-action" onClick={editor.backToTypes}>{text.backToTypes}</button>
    </div>
  )
}

function panelTitle(editor: ObjectEditor): string {
  const draft = editor.draft
  if (editor.step === 'pick') return editor.changingType ? text.titleChangeType : text.titleAdd
  if (editor.step === 'place') return fill(text.titlePlace, { type: editor.typeLabel })
  if (!draft) return text.titleAdd
  if (draft.target === 'object') return editor.original ? fill(text.titleEditObject, { name: draft.name || editor.typeLabel }) : fill(text.titleNewObject, { type: editor.typeLabel })
  if (draft.target === 'opening') return fill(editor.original ? text.titleEditOpening : text.titleNewOpening, { type: editor.typeLabel })
  return fill(text.titleNewConnector, { type: editor.typeLabel })
}

function modeLabel(editor: ObjectEditor): string {
  switch (editor.overlay?.mode) {
    case 'place': return text.modePlace
    case 'wall': return text.modeWall
    case 'rooms': return text.modeRooms
    case 'form': return editor.original ? text.modeEdit : text.modeAdd
    default: return text.modePick
  }
}

/** Replaces the guide panel while the map editor is open. */
export function EditorPanel({ editor }: { editor: ObjectEditor }) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const safeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const wanted = editor.focusRequest.target === 'search' ? searchRef.current : editor.focusRequest.target === 'confirm' ? safeRef.current : headingRef.current
      const target = wanted ?? headingRef.current
      target?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [editor.focusRequest.id])

  const removeName = editor.draft?.target === 'object' ? (editor.draft.name || editor.typeLabel) : editor.typeLabel
  const removeQuestion = editor.removeCount > 0
    ? fill(text.removeConfirmStack, { name: removeName, count: editor.removeCount })
    : fill(text.removeConfirm, { name: removeName })

  return (
    <aside className="editor-panel" aria-labelledby={titleId} data-mode={editor.overlay?.mode ?? 'pick'}>
      <div className="guide-heading">
        <span className="eyebrow">{text.eyebrow}</span>
        <span className="editor-mode">{modeLabel(editor)}</span>
      </div>
      <h2 id={titleId} ref={headingRef} tabIndex={-1}>{panelTitle(editor)}</h2>
      {editor.isLocal && <div className="notice amber"><span aria-hidden="true">?</span><div><strong>{text.localSession}</strong></div></div>}
      {editor.error && (
        <div className="notice red" role="alert">
          <span aria-hidden="true">!</span>
          <div><strong>{editor.error}</strong></div>
        </div>
      )}
      {editor.confirming === 'discard' && (
        <InlineConfirm question={text.discardConfirm} confirmLabel={text.discard} cancelLabel={text.keepEditing} busy={false} safeRef={safeRef} onConfirm={editor.confirmDiscard} onCancel={editor.dismissConfirm} />
      )}
      {editor.step === 'pick' && (
        <>
          {editor.catalogOffline && <p className="field-note">{text.offlineCatalog}</p>}
          <TypePicker groups={editor.groups} entries={editor.entries} recent={editor.recent} onlyObjects={editor.changingType} onChoose={editor.chooseType} searchRef={searchRef} />
          {editor.changingType && <button type="button" className="text-action" onClick={editor.escape}>{text.cancel}</button>}
        </>
      )}
      {editor.step === 'place' && <PlaceStep editor={editor} />}
      {editor.step === 'form' && <ObjectForm editor={editor} />}
      {editor.confirming === 'remove' && (
        <InlineConfirm question={removeQuestion} confirmLabel={text.remove} cancelLabel={text.removeKeep} busy={editor.saving} safeRef={safeRef} onConfirm={editor.remove} onCancel={editor.dismissConfirm} />
      )}
      <div className="editor-footer">
        {editor.step === 'form' && editor.original && (
          <button type="button" className="secondary-action" onClick={editor.addNew} disabled={editor.saving}>{text.addNew}</button>
        )}
        {editor.step === 'form' && editor.canRemove && editor.confirming !== 'remove' && (
          <button type="button" className="danger-action" onClick={editor.askRemove} disabled={editor.saving}>{text.remove}</button>
        )}
        <button type="button" className="secondary-action" onClick={editor.undo} disabled={editor.saving || editor.isLocal}>{text.undo}</button>
      </div>
    </aside>
  )
}
