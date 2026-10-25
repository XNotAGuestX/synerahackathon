import { useId, useState } from 'react'
import { supportCandidates } from '../../domain/editor'
import type { ObjectDraft } from '../../domain/editor'
import type { Asset } from '../../domain/types'
import { copy, fill } from '../../i18n/en'

const text = copy.editor

type SupportPickerProps = {
  draft: ObjectDraft
  /** Objects on the draft's floor. */
  assets: Asset[]
  selected: Asset[]
  /** The draft and everything on top of it: never offered (no cycles). */
  excluded: string[]
  layerOf: (id: string) => number
  elevation: number
  layer: number
  disabled: boolean
  onChange: (ids: string[]) => void
}

function metres(value: number): string {
  return `${Number(value.toFixed(2))} m`
}

/** "Stands on": ARIA 1.2 combobox with a multi-select listbox and removable chips. */
export function SupportPicker({ draft, assets, selected, excluded, layerOf, elevation, layer, disabled, onChange }: SupportPickerProps) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(false)
  // -1 = no active option yet; the first ArrowDown activates the first one.
  const [active, setActive] = useState(-1)
  const inputId = useId()
  const labelId = useId()
  const listId = useId()
  const statusId = useId()
  const options = supportCandidates(assets, draft, new Set(excluded), query)
  const activeIndex = Math.min(active, options.length - 1)
  const activeOption = expanded && activeIndex >= 0 ? options[activeIndex] : undefined
  const optionId = (id: string) => `${listId}-${id.replace(/[^A-Za-z0-9_-]/g, '_')}`

  const toggle = (id: string) => {
    const ids = draft.onTopOf.includes(id) ? draft.onTopOf.filter((item) => item !== id) : [...draft.onTopOf, id]
    onChange(ids)
  }

  return (
    <div className="field support-picker">
      <label id={labelId} htmlFor={inputId} className="field-label">{text.standsOn}</label>
      {selected.length > 0 && (
        <ul className="chip-list" aria-label={fill(text.supportsChosen, { count: selected.length })}>
          {selected.map((asset) => (
            <li key={asset.id} className="chip">
              <span>{asset.name}</span>
              <span className="chip-meta">{fill(text.layer, { n: layerOf(asset.id) })}</span>
              <button type="button" aria-label={fill(text.removeSupport, { name: asset.name })} disabled={disabled} onClick={() => toggle(asset.id)}>×</button>
            </li>
          ))}
        </ul>
      )}
      <div className="combo">
        <input
          id={inputId}
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeOption ? optionId(activeOption.asset.id) : undefined}
          aria-describedby={statusId}
          autoComplete="off"
          value={query}
          disabled={disabled}
          placeholder={text.standsOnPlaceholder}
          onChange={(event) => { setQuery(event.target.value); setExpanded(true); setActive(event.target.value.trim() ? 0 : -1) }}
          onFocus={() => setExpanded(true)}
          onBlur={() => { setExpanded(false); setActive(-1) }}
          onClick={() => setExpanded(true)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              setExpanded(true)
              setActive((index) => Math.min(index + 1, options.length - 1))
            } else if (event.key === 'ArrowUp') {
              event.preventDefault()
              setExpanded(true)
              setActive((index) => (index <= 0 ? options.length - 1 : index - 1))
            } else if (event.key === 'Home' && expanded) {
              event.preventDefault()
              setActive(0)
            } else if (event.key === 'End' && expanded) {
              event.preventDefault()
              setActive(Math.max(options.length - 1, 0))
            } else if (event.key === 'Enter') {
              // Enter picks the option; it never submits the form.
              event.preventDefault()
              if (activeOption) toggle(activeOption.asset.id)
            } else if (event.key === 'Escape') {
              if (expanded) {
                event.preventDefault()
                setExpanded(false)
                setActive(-1)
              } else if (query) {
                event.preventDefault()
                setQuery('')
              }
            } else if (event.key === 'Backspace' && !query && draft.onTopOf.length > 0) {
              toggle(draft.onTopOf[draft.onTopOf.length - 1])
            }
          }}
        />
        <ul id={listId} role="listbox" aria-labelledby={labelId} aria-multiselectable="true" className="combo-list" hidden={!expanded || options.length === 0}>
          {options.map((option, index) => {
            const chosen = draft.onTopOf.includes(option.asset.id)
            const optionLayer = layerOf(option.asset.id)
            return (
              <li
                key={option.asset.id}
                id={optionId(option.asset.id)}
                role="option"
                aria-selected={chosen}
                className={index === activeIndex ? 'active' : undefined}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActive(index)}
                onClick={() => toggle(option.asset.id)}
              >
                <span className="combo-check" aria-hidden="true">{chosen ? '✓' : ''}</span>
                <span className="combo-text">
                  <strong>{option.asset.name}</strong>
                  <small>
                    {option.asset.type.replaceAll('_', ' ')}
                    {option.distance != null ? ` · ${fill(text.away, { distance: metres(option.distance) })}` : ''}
                    {optionLayer > 0 ? ` · ${fill(text.layer, { n: optionLayer })}` : ''}
                  </small>
                </span>
              </li>
            )
          })}
        </ul>
        {expanded && options.length === 0 && <p className="combo-empty">{text.noSupports}</p>}
      </div>
      <p id={statusId} className="field-note" aria-live="polite">
        {selected.length === 0 ? text.onTheFloor : `${fill(text.sitsAt, { height: metres(elevation) })} · ${fill(text.layer, { n: layer })}`}
      </p>
    </div>
  )
}
