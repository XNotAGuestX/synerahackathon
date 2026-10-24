import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { buildDiscovery, limitPlaces, searchDiscovery } from '../../domain/discovery'
import type { DiscoveryPlace } from '../../domain/discovery'
import type { FloorPlan, FloorSummary } from '../../domain/types'
import { copy } from '../../i18n/en'

type PlaceDiscoveryProps = {
  plans: FloorPlan[]
  floors: FloorSummary[]
  stepFree: boolean
  busyId: string | null
  onToggleStepFree: () => void
  onFocus: (place: DiscoveryPlace) => void
  onRoute: (place: DiscoveryPlace) => void
}

export function PlaceDiscovery({ plans, floors, stepFree, busyId, onToggleStepFree, onFocus, onRoute }: PlaceDiscoveryProps) {
  const categories = useMemo(() => buildDiscovery(plans, floors), [plans, floors])
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [typeId, setTypeId] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const category = categories.find((item) => item.id === categoryId) ?? null
  const type = category?.types.find((item) => item.id === typeId) ?? null
  const filtered = searchDiscovery(categories, filter)
  const results = filter.trim() ? filtered : type ? limitPlaces(type.places) : []

  const chooseCategory = (id: string) => {
    setFilter('')
    setCategoryId(id)
    setTypeId(null)
  }
  const chooseType = (id: string) => {
    setFilter('')
    setTypeId(id)
  }
  const reset = () => {
    setCategoryId(null)
    setTypeId(null)
    setFilter('')
  }
  const submitFilter = (event: FormEvent) => {
    event.preventDefault()
  }

  return (
    <section className="place-search" aria-label={copy.discover}>
      <div className="discover-bar">
        <form onSubmit={submitFilter}>
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={copy.filterPlaces}
            aria-label={copy.filterPlaces}
          />
        </form>
        <button type="button" className="step-free-toggle" aria-pressed={stepFree} onClick={onToggleStepFree}>
          {copy.stepFree}
        </button>
      </div>
      <div className="discover-crumb">
        <button type="button" onClick={reset}>{copy.allCategories}</button>
        {category && <button type="button" onClick={() => setTypeId(null)}>{category.label}</button>}
        {type && <span>{type.label}</span>}
      </div>
      {!filter.trim() && !type && (
        <div className="discover-categories">
          {(category ? category.types : categories).map((item) => (
            <button
              type="button"
              key={item.id}
              onClick={() => category ? chooseType(item.id) : chooseCategory(item.id)}
            >
              <strong>{item.label}</strong>
              <span>{item.count}</span>
            </button>
          ))}
        </div>
      )}
      {filter.trim() && results.length === 0 && <p className="discover-empty" role="status">{copy.noMatches}</p>}
      {results.length > 0 && (
        <div className="place-results">
          {results.map((place) => (
            <div key={place.id} className="place-card">
              <button type="button" onClick={() => onFocus(place)}>
                <strong>{place.name}</strong>
                <span>{place.floorName}</span>
              </button>
              <button type="button" onClick={() => onRoute(place)} disabled={busyId === place.id}>
                {busyId === place.id ? copy.working : copy.routeHere}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
