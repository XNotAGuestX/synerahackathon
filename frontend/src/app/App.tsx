import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { catalog, matchUserText } from '../api/fixtures'
import { gateway } from '../api/gateway'
import type { BuildingSummary, Place } from '../api/gateway'
import { buildPresentation, formatMetres } from '../domain/presentation'
import type { Decision } from '../domain/presentation'
import type { FloorPlan, FloorSummary, Reply, ReplyId, Selection } from '../domain/types'
import { DebugPanel } from '../features/debug/DebugPanel'
import { GuidePanel } from '../features/guide/GuidePanel'
import { copy } from '../i18n/en'
import { PlanCanvas } from '../rendering/PlanCanvas'

const emptyPresentation = buildPresentation({ guideText: '', understood: null, effects: [], routes: [], pendingSummary: null, decision: null, confirmedEffects: [], confirmedClosedIds: [], confirmedText: catalog.confirmedText, cancelledText: copy.cancelled })

export function App() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [replyId, setReplyId] = useState<ReplyId | 'miss'>('accepted')
  const [liveReply, setLiveReply] = useState<Reply | null>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
  const [floors, setFloors] = useState<FloorSummary[]>(catalog.floors)
  const [plans, setPlans] = useState<Map<string, FloorPlan>>(new Map(catalog.floors.map((floor) => [floor.id, catalog.plans.get(floor.id)!])))
  const [floorId, setFloorId] = useState(catalog.floors.find((floor) => floor.level === 0)?.id ?? catalog.floors[0].id)
  const [floorPinned, setFloorPinned] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [debugOpen, setDebugOpen] = useState(false)
  const [directionIndex, setDirectionIndex] = useState(0)
  const [missed, setMissed] = useState(false)
  const [sessionId, setSessionId] = useState('')
  const [buildings, setBuildings] = useState<BuildingSummary[]>([])
  const [buildingId, setBuildingId] = useState('proc-factory-dev-003')
  const [placeQuery, setPlaceQuery] = useState('')
  const [places, setPlaces] = useState<Place[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    gateway.listBuildings().then((items) => { if (!cancelled) setBuildings(items) }).catch(() => {})
    gateway.createSession(buildingId).then(async (session) => {
      const nextFloors = await gateway.listFloors(session.id)
      const nextPlans = await Promise.all(nextFloors.map(async (floor) => [floor.id, await gateway.getFloorPlan(session.id, floor.id)] as const))
      if (!cancelled) { setSessionId(session.id); setFloors(nextFloors); setPlans(new Map(nextPlans)); setFloorId(nextFloors.find((floor) => floor.level === 0)?.id ?? nextFloors[0]?.id ?? '') }
    }).catch((error: unknown) => { if (!cancelled) setLoadError(error instanceof Error ? error.message : 'Unable to load building data') })
    return () => { cancelled = true }
  }, [buildingId])

  const reply = replyId === 'miss' ? null : liveReply ?? catalog.replies[replyId]
  const presentation = useMemo(() => {
    if (!reply) return { ...emptyPresentation, alert: missed ? { tone: 'amber' as const, text: copy.missTitle } : null, guideText: missed ? copy.missBody : '' }
    return buildPresentation({ guideText: reply.guideText, understood: reply.understood, effects: reply.effects, routes: reply.routes, pendingSummary: reply.pending?.summary ?? null, decision, confirmedEffects: catalog.confirmedEffects, confirmedClosedIds: catalog.confirmedClosedIds, confirmedText: catalog.confirmedText, cancelledText: copy.cancelled })
  }, [reply, decision, missed])

  useEffect(() => { if (!floorPinned && presentation.focusFloorId) setFloorId(presentation.focusFloorId) }, [floorPinned, presentation.focusFloorId])

  const floor = floors.find((item) => item.id === floorId) ?? floors[0] ?? catalog.floors[0]
  const plan = plans.get(floor.id) ?? null
  const step = presentation.route?.directions[directionIndex]
  const nextText = !presentation.route ? copy.askRoute : presentation.route.reachable ? (step?.text ?? copy.askRoute) : copy.noRoute
  const visibleEffects = decision === 'confirmed' ? catalog.confirmedEffects : decision === 'cancelled' || !reply ? [] : reply.effects

  const loadReply = (id: ReplyId) => {
    const next = catalog.replies[id]
    setLiveReply(null); setReplyId(id); setDecision(id === 'pending' ? 'pending' : null); setMissed(false); setDirectionIndex(0); setFloorPinned(false)
    if (next.userText) setQuery(next.userText)
  }

  const searchPlaces = async (event: FormEvent) => {
    event.preventDefault()
    if (!sessionId || !placeQuery.trim()) return
    setLoading(true); setLoadError(null)
    try { setPlaces(await gateway.searchPlaces(sessionId, placeQuery)) } catch (error) { setLoadError(error instanceof Error ? error.message : 'Unable to search places') } finally { setLoading(false) }
  }

  const focusPlace = (place: Place) => {
    setFloorId(place.floor_id); setFloorPinned(true)
    setSelection({ kind: place.kind === 'asset' ? 'asset' : 'space', id: place.id, name: place.name, floorId: place.floor_id, floorName: floors.find((item) => item.id === place.floor_id)?.name ?? '', note: null })
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!query.trim() || loading) return
    setLoading(true); setLoadError(null); setMissed(false)
    try {
      const next = await gateway.sendMessage(sessionId, query)
      setLiveReply(next); setReplyId(next.id); setDecision(next.pending ? 'pending' : null); setDirectionIndex(0); setFloorPinned(false)
    } catch (error: unknown) {
      const match = matchUserText(query)
      if (gateway.mode === 'fixture' && match) loadReply(match)
      else setLoadError(error instanceof Error ? error.message : 'Unable to send message')
    } finally { setLoading(false) }
  }

  const advance = () => {
    const directions = presentation.route?.directions ?? []
    if (!presentation.route?.reachable || directions.length === 0) return
    const nextIndex = (directionIndex + 1) % directions.length
    setDirectionIndex(nextIndex)
    if (directions[nextIndex]?.floor_id) { setFloorId(directions[nextIndex].floor_id); setFloorPinned(true) }
  }

  const confirm = async () => {
    if (!sessionId || !reply?.pending) return
    setLoading(true); setLoadError(null)
    try { await gateway.confirmAction(sessionId, reply.pending.id); setDecision('confirmed') } catch (error: unknown) { setLoadError(error instanceof Error ? error.message : 'Unable to confirm action') } finally { setLoading(false) }
  }
  const cancel = async () => {
    if (!sessionId || !reply?.pending) return
    setLoading(true); setLoadError(null)
    try { await gateway.cancelAction(sessionId, reply.pending.id); setDecision('cancelled') } catch (error: unknown) { setLoadError(error instanceof Error ? error.message : 'Unable to cancel action') } finally { setLoading(false) }
  }

  return <main className="app-shell" data-scenario={replyId} data-decision={decision ?? 'none'}>
    <header className="topbar"><div className="brand"><span className="brand-mark">W</span><span>{copy.title}</span></div><div className="building-meta"><span className="eyebrow">{copy.buildingEyebrow}</span><select className="building-picker" value={buildingId} onChange={(event) => setBuildingId(event.target.value)} aria-label="Choose building">{(buildings.length ? buildings : [{ id: buildingId, name: catalog.buildingName } as BuildingSummary]).map((building) => <option key={building.id} value={building.id}>{building.name}</option>)}</select><span className="status-pill"><span />{gateway.mode === 'fixture' ? copy.fixtures : 'API connected'}</span></div><button type="button" className="icon-button" aria-label={copy.debug} aria-pressed={debugOpen} onClick={() => setDebugOpen((open) => !open)}><span className="menu-dots" aria-hidden="true"><span /><span /><span /></span></button></header>
    {loadError && <div className="app-alert" role="alert">{loadError}</div>}
    <section className="place-search"><form onSubmit={searchPlaces}><input value={placeQuery} onChange={(event) => setPlaceQuery(event.target.value)} placeholder="Search rooms or equipment" aria-label="Search rooms or equipment"/><button type="submit">Search</button></form>{places.length > 0 && <div className="place-results">{places.map((place) => <button type="button" key={place.id} onClick={() => focusPlace(place)}><strong>{place.name}</strong><span>{place.kind} · Floor {place.floor_level}</span></button>)}</div>}</section>
    <section className="workspace"><div className="map-column"><div className="map-toolbar"><div><span className="eyebrow">{copy.planEyebrow}</span><h1>{floor.name}</h1></div><div className="floor-rail" role="toolbar" aria-label="Floors">{floors.map((item) => <button type="button" key={item.id} className={item.id === floor.id ? 'active' : undefined} aria-pressed={item.id === floor.id} aria-label={`${copy.showFloor} ${item.name}`} onClick={() => { setFloorId(item.id); setFloorPinned(true) }}>{item.level}</button>)}</div></div><div className="plan-stage"><PlanCanvas plan={plan} floorName={floor.name} route={presentation.route} spaceReasons={presentation.spaceReasons} assetIds={presentation.assetIds} closedIds={presentation.closedIds} focusPoint={presentation.focusFloorId === floor.id ? presentation.focusPoint : null} stepPoint={step?.floor_id === floor.id ? step.at : null} selectionId={selection?.id ?? null} onSelect={setSelection} /><div className="map-caption" role="status">{selection ? <><strong>{selection.name}</strong><span>{selection.floorName}</span></> : <><span className="legend-dot route-dot" /> {copy.routeTape}<span className="legend-dot focus-dot" /> {copy.destinationFocus}</>}</div>{debugOpen && <DebugPanel selection={selection} presentation={presentation} effects={visibleEffects} onLoad={loadReply} />}</div></div>
      <GuidePanel query={query} presentation={presentation} directionIndex={directionIndex} onQuery={setQuery} onSubmit={submit} onChoose={(label) => { setQuery(label); inputRef.current?.focus() }} onConfirm={confirm} onCancel={cancel} onReplay={() => { setDirectionIndex(0) }} inputRef={inputRef} />
    </section>
    <footer className="next-bar"><div><span className="eyebrow">{copy.nextStep}</span><strong>{loading ? 'Working…' : nextText}</strong></div><button type="button" className="next-distance" onClick={advance} disabled={!presentation.route?.reachable}>{presentation.route?.reachable ? `${formatMetres(presentation.route.length_m)} ->` : `${copy.noRoute} ->`}</button></footer>
  </main>
}