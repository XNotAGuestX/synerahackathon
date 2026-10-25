import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { buildDiscovery, discoveryResultLimit, searchDiscovery } from '../../domain/discovery'
import type { DiscoveryPlace } from '../../domain/discovery'
import type { FloorPlan, FloorSummary } from '../../domain/types'
import { copy } from '../../i18n/en'

type PlaceDiscoveryProps = {
  plans: FloorPlan[]
  floors: FloorSummary[]
  busyId: string | null
  onFocus: (place: DiscoveryPlace) => void
  onRoute: (place: DiscoveryPlace) => void
}

export function PlaceDiscovery({ plans, floors, busyId, onFocus, onRoute }: PlaceDiscoveryProps) {
  const categories = useMemo(() => buildDiscovery(plans, floors), [plans, floors])
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [typeId, setTypeId] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(1)
  const [typePage, setTypePage] = useState(1)
  // Browse and search results float over the map instead of pushing it down.
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const category = categories.find((item) => item.id === categoryId) ?? null
  const type = category?.types.find((item) => item.id === typeId) ?? null
  const searching = filter.trim().length > 0
  const filtered = searchDiscovery(categories, filter)
  const paged = filtered.slice((page - 1) * 15, page * 15)
  const typeSlice = type ? type.places.slice((typePage - 1) * 15, typePage * 15) : []
  const results = searching ? paged : typeSlice

  const chooseCategory = (id: string) => {
    setFilter('')
    setCategoryId(id)
    setTypeId(null)
  }
  const chooseType = (id: string) => {
    setFilter('')
    setTypeId(id)
    setTypePage(1)
  }
  const reset = () => {
    setCategoryId(null)
    setTypeId(null)
    setFilter('')
  }
  const submitFilter = (event: FormEvent) => {
    event.preventDefault()
  }

  const atRoot = !searching && !category
  const browseId = useId()
  const typesId = useId()
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => { if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])

  const close = () => { setOpen(false); inputRef.current?.focus() }
  const focusPlace = (place: DiscoveryPlace) => { setOpen(false); onFocus(place) }
  const routePlace = (place: DiscoveryPlace) => { setOpen(false); onRoute(place) }

  return (
    <section ref={rootRef} className="place-search" aria-label={copy.discover} onKeyDown={(event) => { if (event.key === 'Escape' && open) { event.stopPropagation(); close() } }}>
      <div className="discover-bar">
        <form onSubmit={submitFilter} role="search" className="discover-field">
          <svg className="discover-icon" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" />
            <path d="M10.5 10.5 14 14" />
          </svg>
          <input
            ref={inputRef}
            value={filter}
            aria-controls={open ? panelId : undefined}
            onFocus={() => { if (searching) setOpen(true) }}
            onChange={(event) => { setFilter(event.target.value); setPage(1); setOpen(event.target.value.trim().length > 0 || open) }}
            placeholder={copy.filterPlaces}
            aria-label={copy.filterPlaces}
          />
          {searching && (
            <button type="button" className="discover-clear" aria-label={copy.clearFilter} onClick={() => { setFilter(''); setPage(1) }}>×</button>
          )}
        </form>
        <button type="button" className="discover-browse-toggle" aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={() => setOpen((value) => !value)}>
          {copy.browse}<span className="discover-chevron" aria-hidden="true" />
        </button>
      </div>
      {open && <div id={panelId} className="discover-panel">
      <nav className="discover-crumb" aria-label={copy.categoryPath}>
        <ol>
          <li>
            <button type="button" onClick={reset} aria-current={atRoot ? 'page' : undefined}>{copy.allCategories}</button>
          </li>
          {!searching && category && (
            <li>
              {type
                ? <button type="button" onClick={() => setTypeId(null)}>{category.label}</button>
                : <span aria-current="page">{category.label}</span>}
            </li>
          )}
          {!searching && type && <li><span aria-current="page">{type.label}</span></li>}
          {searching && <li><span aria-current="page">{copy.searchResults}: “{filter.trim()}”</span></li>}
        </ol>
        {searching && filtered.length > 0 && (
          <span className="discover-count">
            {filtered.length > 15 ? `${(page - 1) * 15 + 1}–${Math.min(page * 15, filtered.length)} ${copy.of} ` : ''}{filtered.length} {copy.placesFound}
          </span>
        )}
        {!searching && type && type.count > discoveryResultLimit && (
          <span className="discover-count">{(typePage - 1) * 15 + 1}–{Math.min(typePage * 15, type.count)} {copy.of} {type.count}</span>
        )}
        <button type="button" className="discover-close" aria-label={copy.closeResults} title={copy.closeResults} onClick={close}>×</button>
      </nav>
      <div className="discover-browse">
        <div className="browse-row" role="group" aria-labelledby={browseId}>
          <span id={browseId} className="eyebrow browse-label">{copy.browseCategories}</span>
          {categories.length === 0
            ? <p className="discover-empty" role="status">{copy.noCategories}</p>
            : (
              <ul className="discover-categories">
                {categories.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      aria-pressed={!searching && item.id === categoryId}
                      onClick={() => item.id === categoryId && !searching ? reset() : chooseCategory(item.id)}
                    >
                      <strong>{item.label}</strong>
                      <span className="count-chip">{item.count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
        </div>
        {!searching && category && (
          <div className="browse-row" role="group" aria-labelledby={typesId}>
            <span id={typesId} className="eyebrow browse-label">{copy.browseTypes} {category.label}</span>
            <ul className="discover-categories discover-types">
              {category.types.map((item) => (
                <li key={item.id}>
                  <button type="button" aria-pressed={item.id === typeId} onClick={() => item.id === typeId ? setTypeId(null) : chooseType(item.id)}>
                    <strong>{item.label}</strong>
                    <span className="count-chip">{item.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {searching && results.length === 0 && <p className="discover-empty" role="status">{copy.noMatches}</p>}
      {results.length > 0 && (
        <ul className="place-results">
          {results.map((place) => (
            <li key={place.id} className="place-card">
              <button type="button" className="place-main" onClick={() => focusPlace(place)}>
                <strong>{place.name}</strong>
                <span>{place.floorName}</span>
              </button>
              <button type="button" className="place-route" onClick={() => routePlace(place)} disabled={busyId === place.id} aria-busy={busyId === place.id}>
                {busyId === place.id ? copy.working : copy.routeHere}
              </button>
            </li>
          ))}
          {!searching && type && type.places.length > typePage * 15 && (
            <li>
              <button type="button" className="more-button" onClick={() => setTypePage((value) => value + 1)}>
                {copy.more} ({type.places.length - typePage * 15})
              </button>
            </li>
          )}
          {searching && filtered.length > page * 15 && (
            <li>
              <button type="button" className="more-button" onClick={() => setPage((value) => value + 1)}>
                {copy.more} ({filtered.length - page * 15})
              </button>
            </li>
          )}
        </ul>
      )}
      </div>}
    </section>
  )
}
