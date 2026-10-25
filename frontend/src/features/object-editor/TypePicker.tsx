import { useEffect, useId, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { catalogKey, searchCatalog } from '../../domain/editor'
import type { CatalogEntry } from '../../domain/editor'
import type { ObjectGroup, ObjectType } from '../../domain/types'
import { copy } from '../../i18n/en'

const text = copy.editor

type TypePickerProps = {
  groups: ObjectGroup[]
  entries: CatalogEntry[]
  recent: string[]
  /** Changing an object's type: connections are not offered. */
  onlyObjects: boolean
  onChoose: (entry: CatalogEntry) => void
  searchRef: RefObject<HTMLInputElement | null>
}

function typeMeta(type: ObjectType): string {
  if (type.width_m != null && type.depth_m != null) return `${type.width_m} × ${type.depth_m} m`
  if (type.width_m != null) return `${type.width_m} m`
  return ''
}

/** Hierarchical type picker: breadcrumb, one level of buttons at a time, search across all levels, recent types. */
export function TypePicker({ groups, entries, recent, onlyObjects, onChoose, searchRef }: TypePickerProps) {
  const [query, setQuery] = useState('')
  const [groupId, setGroupId] = useState<string | null>(null)
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const navigated = useRef(false)
  const searchId = useId()
  const countId = useId()
  const listLabelId = useId()

  const allowed = (type: ObjectType) => !onlyObjects || type.action === 'add_object'
  const visibleEntries = entries.filter((entry) => allowed(entry.type))
  const visibleGroups = groups
    .map((group) => ({ ...group, categories: group.categories.map((category) => ({ ...category, types: category.types.filter(allowed) })).filter((category) => category.types.length > 0) }))
    .filter((group) => group.categories.length > 0)
  const group = visibleGroups.find((item) => item.id === groupId) ?? null
  const category = group?.categories.find((item) => item.id === categoryId) ?? null
  const searching = query.trim().length > 0
  const results = searching ? searchCatalog(visibleEntries, query) : []
  const recentEntries = recent.map((key) => visibleEntries.find((entry) => entry.key === key)).filter((entry): entry is CatalogEntry => Boolean(entry))

  // Moving one level down replaces the pressed button; keep keyboard focus on the new level.
  useEffect(() => {
    if (!navigated.current) return
    navigated.current = false
    listRef.current?.querySelector('button')?.focus()
  }, [groupId, categoryId])

  const go = (nextGroup: string | null, nextCategory: string | null) => {
    navigated.current = true
    setGroupId(nextGroup)
    setCategoryId(nextCategory)
  }

  const entryOf = (type: ObjectType): CatalogEntry | undefined => group && category ? visibleEntries.find((entry) => entry.key === catalogKey(group.id, category.id, type.id)) : undefined

  return (
    <div className="type-picker">
      <form className="type-search" role="search" onSubmit={(event) => { event.preventDefault(); if (results[0]) onChoose(results[0]) }}>
        <label htmlFor={searchId} className="field-label">{text.searchTypes}</label>
        <input
          ref={searchRef}
          id={searchId}
          type="search"
          value={query}
          autoComplete="off"
          placeholder={text.searchPlaceholder}
          aria-describedby={searching ? countId : undefined}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            // First Esc clears the search; the next one leaves the picker.
            if (event.key === 'Escape' && query) {
              event.preventDefault()
              setQuery('')
            }
          }}
        />
      </form>

      {searching ? (
        <>
          <p id={countId} className="type-count" role="status">{results.length} {text.typesFound}</p>
          {results.length === 0 ? <p className="discover-empty">{text.noTypes}</p> : (
            <ul className="type-results" aria-label={copy.searchResults}>
              {results.map((entry) => (
                <li key={entry.key}>
                  <button type="button" className="type-result" onClick={() => onChoose(entry)}>
                    <strong>{entry.type.label}</strong>
                    <span>{entry.groupLabel} › {entry.categoryLabel}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <>
          <nav className="discover-crumb type-crumb" aria-label={copy.categoryPath}>
            <ol>
              <li>{group ? <button type="button" onClick={() => go(null, null)}>{text.allTypes}</button> : <span aria-current="page">{text.allTypes}</span>}</li>
              {group && <li>{category ? <button type="button" onClick={() => go(group.id, null)}>{group.label}</button> : <span aria-current="page">{group.label}</span>}</li>}
              {category && <li><span aria-current="page">{category.label}</span></li>}
            </ol>
          </nav>

          {!group && recentEntries.length > 0 && (
            <div className="type-recent" role="group" aria-label={text.recentTypes}>
              <span className="eyebrow">{text.recentTypes}</span>
              <ul>
                {recentEntries.map((entry) => (
                  <li key={entry.key}><button type="button" onClick={() => onChoose(entry)}>{entry.type.label}</button></li>
                ))}
              </ul>
            </div>
          )}

          <span id={listLabelId} className="sr-only">{category?.label ?? group?.label ?? text.allTypes}</span>
          <ul ref={listRef} className="type-grid" aria-labelledby={listLabelId}>
            {!group && visibleGroups.map((item) => (
              <li key={item.id}>
                <button type="button" className="type-tile" onClick={() => go(item.id, null)}>
                  <strong>{item.label}</strong>
                  <span className="count-chip">{item.categories.length}</span>
                </button>
              </li>
            ))}
            {group && !category && group.categories.map((item) => (
              <li key={item.id}>
                <button type="button" className="type-tile" onClick={() => go(group.id, item.id)}>
                  <strong>{item.label}</strong>
                  <span className="count-chip">{item.types.length}</span>
                </button>
              </li>
            ))}
            {category && category.types.map((type) => {
              const entry = entryOf(type)
              return (
                <li key={type.id}>
                  <button type="button" className="type-tile leaf" disabled={!entry} onClick={() => entry && onChoose(entry)}>
                    <strong>{type.label}</strong>
                    {typeMeta(type) && <span className="type-meta mono">{typeMeta(type)}</span>}
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
