import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { toUiError } from '../api/errors'
import type { UiError } from '../api/errors'
import { catalog, labelFor, matchUserText } from '../api/fixtures'
import { currentLocation, setCurrentLocation } from '../api/interpret'
import { gateway } from '../api/gateway'
import type { BuildingSummary, InputMode, Session } from '../api/gateway'
import { readRecovery, writeRecovery } from '../api/recovery'
import type { DiscoveryPlace } from '../domain/discovery'
import { buildPresentation, formatMetres } from '../domain/presentation'
import type { Decision } from '../domain/presentation'
import type { FloorPlan, FloorSummary, Reply, ReplyId, Selection } from '../domain/types'
import { DebugPanel } from '../features/debug/DebugPanel'
import { PlaceDiscovery } from '../features/discovery/PlaceDiscovery'
import { GuidePanel } from '../features/guide/GuidePanel'
import { copy } from '../i18n/en'
import { PlanImport } from '../features/building-ingestion/PlanImport'
import { PlanCanvas } from '../rendering/PlanCanvas'
import { FloorStack3D } from '../rendering/floor-stack-3d/FloorStack3D'

const emptyPresentation = buildPresentation({ guideText: '', understood: null, effects: [], routes: [], pendingSummary: null, decision: null, confirmedEffects: [], confirmedClosedIds: [], confirmedText: catalog.confirmedText, cancelledText: copy.cancelled })
type ThemeMode = 'system' | 'light' | 'dark'

const themeModes: ThemeMode[] = ['system', 'light', 'dark']

function initialThemeMode(): ThemeMode {
  const stored = window.localStorage.getItem('talk-building-theme')
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

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
  const [activePanel, setActivePanel] = useState<'guide' | 'debug'>('guide')
  const [mapFocusActive, setMapFocusActive] = useState(false)
  const [directionIndex, setDirectionIndex] = useState(0)
  const [missed, setMissed] = useState(false)
  const [sessionId, setSessionId] = useState('')
  const [buildings, setBuildings] = useState<BuildingSummary[]>([])
  const [buildingId, setBuildingId] = useState('proc-factory-dev-003')
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<UiError | null>(null)
  const [booting, setBooting] = useState(true)
  const [revision, setRevision] = useState(1)
  const [inputMode, setInputMode] = useState<InputMode>('text')
  const [stackOpen, setStackOpen] = useState(false)
  const [themeMode, setThemeMode] = useState<ThemeMode>(initialThemeMode)
  const [stepFree, setStepFree] = useState(() => window.localStorage.getItem('wayfinder-step-free') === 'true')
  const [routingId, setRoutingId] = useState<string | null>(null)
  const [hereId, setHereId] = useState<string | null>(null)
  const [appliedClosed, setAppliedClosed] = useState<string[] | null>(null)

  useEffect(() => {
    const root = document.documentElement
    const applyTheme = (mode: ThemeMode) => {
      root.dataset.theme = mode
      window.localStorage.setItem('talk-building-theme', mode)
    }
    applyTheme(themeMode)
    if (themeMode !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = () => { root.dataset.systemTheme = media.matches ? 'dark' : 'light' }
    handleChange()
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [themeMode])

  useEffect(() => {
    let cancelled = false
    gateway.listBuildings().then((items) => { if (!cancelled) setBuildings(items) }).catch(() => {})
    setBooting(true)
    setLiveReply(null)
    setSelection(null)
    setReplyId('miss')
    setPlans(new Map())
    setFloors([])
    setLoadError(null)
    const openSession = async (): Promise<Session> => {
      const recovered = readRecovery(buildingId)
      if (recovered) {
        try { return await gateway.getSession(recovered.id) } catch { /* create a new session below */ }
      }
      const created = await gateway.createSession(buildingId)
      const stored = window.localStorage.getItem('wayfinder-step-free')
      const wanted = stored === 'true' || stored === 'false' ? stored === 'true' : created.preferences.step_free
      return wanted === created.preferences.step_free ? created : gateway.updatePreferences(created.id, { step_free: wanted })
    }
    openSession().then(async (session) => {
      const nextFloors = await gateway.listFloors(session.id)
      const nextPlans = await Promise.all(nextFloors.map(async (floor) => [floor.id, await gateway.getFloorPlan(session.id, floor.id)] as const))
      if (cancelled) return
      setSessionId(session.id)
      setRevision(session.revision)
      setStepFree(session.preferences.step_free)
      setFloors(nextFloors)
      setPlans(new Map(nextPlans))
      setFloorId(nextFloors.find((floor) => floor.level === 0)?.id ?? nextFloors[0]?.id ?? '')
      writeRecovery({ id: session.id, buildingId: session.building_id, revision: session.revision, stepFree: session.preferences.step_free, lastRouteId: session.last_route_id ?? null, pendingActionId: session.pending_action_id ?? null })
      if (session.last_route_id) {
        const route = await gateway.getRoute(session.id, session.last_route_id)
        if (!cancelled) setLiveReply({ id: route.reachable ? 'accepted' : 'unreachable', userText: null, guideText: route.reachable ? `Route is ${formatMetres(route.length_m)}.` : copy.noRoute, understood: null, effects: [{ type: 'draw_route', route_id: route.id }], routes: [route], pending: null })
      }
    }).catch((error: unknown) => {
      if (!cancelled) {
        const ui = toUiError(error)
        if (ui.code === '30001_building_not_found') ui.message = copy.otherBuilding
        setLoadError(ui)
      }
    }).finally(() => { if (!cancelled) setBooting(false) })
    return () => { cancelled = true }
  }, [buildingId])

  const reply = replyId === 'miss' ? null : liveReply ?? catalog.replies[replyId]
  const presentation = useMemo(() => {
    if (!reply) return { ...emptyPresentation, alert: missed ? { tone: 'amber' as const, text: copy.missTitle } : null, guideText: missed ? copy.missBody : '' }
    return buildPresentation({ guideText: reply.guideText, understood: reply.understood, effects: reply.effects, routes: reply.routes, pendingSummary: reply.pending?.summary ?? null, decision, confirmedEffects: catalog.confirmedEffects, confirmedClosedIds: appliedClosed ?? catalog.confirmedClosedIds, confirmedText: catalog.confirmedText, cancelledText: copy.cancelled })
  }, [reply, decision, missed, appliedClosed])

  useEffect(() => { if (!floorPinned && presentation.focusFloorId) setFloorId(presentation.focusFloorId) }, [floorPinned, presentation.focusFloorId])
  const patchedKey = presentation.patchedFloorIds.join('|')
  useEffect(() => {
    if (!sessionId || !patchedKey) return
    let cancelled = false
    Promise.all(patchedKey.split('|').map(async (id) => [id, await gateway.getFloorPlan(sessionId, id)] as const)).then((entries) => {
      if (cancelled) return
      setPlans((current) => { const next = new Map(current); for (const [id, nextPlan] of entries) next.set(id, nextPlan); return next })
    }).catch((error: unknown) => { if (!cancelled) setLoadError(toUiError(error)) })
    return () => { cancelled = true }
  }, [sessionId, patchedKey])

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

  const focusDiscoveryPlace = (place: DiscoveryPlace) => {
    setFloorId(place.floorId)
    setFloorPinned(true)
    setSelection({ kind: place.kind, id: place.id, name: place.name, floorId: place.floorId, floorName: place.floorName, note: place.type })
  }

  const toggleStepFree = async () => {
    const next = !stepFree
    setStepFree(next)
    window.localStorage.setItem('wayfinder-step-free', String(next))
    if (!sessionId) return
    try {
      const updated = await gateway.updatePreferences(sessionId, { step_free: next })
      setStepFree(updated.preferences.step_free)
    } catch (error: unknown) {
      setLoadError(toUiError(error))
    }
  }

  const routeToPlace = async (place: DiscoveryPlace) => {
    if (!sessionId || loading) return
    const start = hereId ?? (selection?.kind === 'space' ? selection.id : null) ?? currentLocation() ?? catalog.replies.accepted.routes[0]?.start_space_id
    if (!start) return
    setRoutingId(place.id)
    setLoading(true)
    setLoadError(null)
    try {
      const route = await gateway.createRoute(sessionId, { start_space_id: start, destination_space_id: place.id, step_free: stepFree })
      setLiveReply({
        id: route.reachable ? 'accepted' : 'unreachable',
        userText: null,
        guideText: route.reachable ? `Route is ${formatMetres(route.length_m)}. Follow the tape on the plan.` : 'No route to that place with the current preference.',
        understood: {
          intent: 'route',
          summary: `${labelFor(start)} to ${place.name}`,
          constraints: { step_free: route.step_free, via: route.via, closed_ids: route.closed_ids },
          resolved: {
            start_space_id: route.start_space_id,
            destination_space_id: route.destination_space_id,
            space_ids: [route.start_space_id, route.destination_space_id].filter((id): id is string => Boolean(id)),
            asset_ids: place.kind === 'asset' ? [place.id] : [],
            count: null,
          },
          missing: [],
        },
        effects: [
          { type: 'draw_route', route_id: route.id },
          { type: 'focus', floor_id: place.floorId, floor_level: place.floorLevel, point: place.position },
          place.kind === 'asset'
            ? { type: 'highlight_assets', asset_ids: [place.id] }
            : { type: 'highlight_spaces', space_ids: [place.id], reason: 'selected' },
        ],
        routes: [route],
        pending: null,
      })
      setReplyId(route.reachable ? 'accepted' : 'unreachable')
      setDecision(null)
      setDirectionIndex(0)
      setFloorPinned(false)
      focusDiscoveryPlace(place)
    } catch (error: unknown) {
      setLoadError(toUiError(error))
    } finally {
      setLoading(false)
      setRoutingId(null)
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!query.trim() || loading) return
    setLoading(true); setLoadError(null); setMissed(false)
    try {
      const next = await gateway.sendMessage(sessionId, query, inputMode)
      setLiveReply(next); setReplyId(next.id); setDecision(next.pending ? 'pending' : null); setDirectionIndex(0); setFloorPinned(false)
      if (next.understood?.intent === 'context' && next.understood.resolved.start_space_id) {
        setHereId(next.understood.resolved.start_space_id)
        setCurrentLocation(next.understood.resolved.start_space_id)
      }
    } catch (error: unknown) {
      const match = matchUserText(query)
      if (gateway.mode === 'fixture' && match) loadReply(match)
      else setLoadError(toUiError(error))
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
    try { const result = await gateway.confirmAction(sessionId, reply.pending.id); setAppliedClosed(result.closed_ids); setDecision('confirmed'); const refreshed = await gateway.getSession(sessionId); setRevision(refreshed.revision); const floorPlan = await gateway.getFloorPlan(sessionId, floorId); setPlans((current) => new Map(current).set(floorId, floorPlan)) } catch (error: unknown) { setLoadError(toUiError(error)) } finally { setLoading(false) }
  }
  const cancel = async () => {
    if (!sessionId || !reply?.pending) return
    setLoading(true); setLoadError(null)
    try { await gateway.cancelAction(sessionId, reply.pending.id); setDecision('cancelled') } catch (error: unknown) { setLoadError(toUiError(error)) } finally { setLoading(false) }
  }

  return <main className="app-shell" data-scenario={replyId} data-decision={decision ?? 'none'}>
    <header className="topbar"><div className="brand"><span className="brand-mark">W</span><span>{copy.title}</span></div><div className="building-meta"><span className="eyebrow">{copy.buildingEyebrow}</span><select className="building-picker" value={buildingId} onChange={(event) => setBuildingId(event.target.value)} aria-label="Choose building">{(buildings.length ? buildings : [{ id: buildingId, name: catalog.buildingName } as BuildingSummary]).map((building) => <option key={building.id} value={building.id}>{building.name}</option>)}</select><span className="status-pill"><span />{gateway.mode === 'fixture' ? copy.fixtures : 'API connected'}</span><div className="theme-switcher" role="group" aria-label="Theme"><span className="sr-only">Theme</span>{themeModes.map((mode) => <button key={mode} type="button" className={themeMode === mode ? 'active' : undefined} aria-pressed={themeMode === mode} onClick={() => setThemeMode(mode)}>{mode === 'system' ? 'Auto' : mode === 'light' ? 'Light' : 'Dark'}</button>)}</div></div></header>
    {booting && <p className="app-status" role="status">{copy.loadingPlan}</p>}
    {loadError && <div className="app-alert" role="alert"><strong>{loadError.code ?? copy.apiUnavailable}</strong><span>{loadError.message}</span>{loadError.traceId && <span>trace {loadError.traceId}</span>}{loadError.requestId && <span>request {loadError.requestId}</span>}</div>}
    <PlaceDiscovery plans={[...plans.values()]} floors={floors} stepFree={stepFree} busyId={routingId} onToggleStepFree={toggleStepFree} onFocus={focusDiscoveryPlace} onRoute={routeToPlace} />
    <section className="workspace"><div className="map-column"><div className="map-toolbar"><div><span className="eyebrow">{copy.planEyebrow}</span><h1>{floor.name}</h1></div><div className="floor-rail" role="toolbar" aria-label="Floors">{floors.map((item) => <button type="button" key={item.id} className={item.id === floor.id ? 'active' : undefined} aria-pressed={item.id === floor.id} aria-label={`${copy.showFloor} ${item.name}`} onClick={() => { setFloorId(item.id); setFloorPinned(true) }}>{item.level}</button>)}<button type="button" aria-pressed={stackOpen} onClick={() => setStackOpen((open) => !open)}>{stackOpen ? copy.flatPlan : copy.stackFloors}</button></div></div><div className="plan-stage"><PlanCanvas plan={plan} floorName={floor.name} route={presentation.route} spaceReasons={presentation.spaceReasons} assetIds={presentation.assetIds} closedIds={presentation.closedIds} focusPoint={presentation.focusFloorId === floor.id ? presentation.focusPoint : null} stepPoint={step?.floor_id === floor.id ? step.at : null} selectionId={selection?.id ?? null} onSelect={setSelection} onFocusSelection={(focused) => { setMapFocusActive(Boolean(focused)); setActivePanel(focused ? 'debug' : 'guide') }} /><div className="map-caption" role="status">{selection ? <><strong>{selection.name}</strong><span>{selection.floorName}</span></> : <><span className="legend-dot route-dot" /> {copy.routeTape}<span className="legend-dot focus-dot" /> {copy.destinationFocus}</>}</div></div>{stackOpen && <FloorStack3D plans={[...plans.values()]} route={presentation.route} />}<PlanImport onApply={(imported) => setPlans((current) => new Map(current).set(imported.floor.id, imported))} /><p className="revision-note">Revision {revision}</p></div>
      <div className="guide-region">
        {mapFocusActive && <div className="panel-tabs" role="tablist" aria-label="Guide views">
          <button type="button" role="tab" aria-selected={activePanel === 'guide'} className={activePanel === 'guide' ? 'active' : undefined} onClick={() => { setActivePanel('guide') }}>Your Guide</button>
          <button type="button" role="tab" aria-selected={activePanel === 'debug'} className={activePanel === 'debug' ? 'active' : undefined} onClick={() => { setActivePanel('debug') }}>Debug</button>
        </div>}
        {!mapFocusActive || activePanel === 'guide' ? <GuidePanel query={query} presentation={presentation} directionIndex={directionIndex} onQuery={setQuery} onSubmit={submit} onChoose={(label) => { setQuery(label); inputRef.current?.focus() }} onConfirm={confirm} onCancel={cancel} onReplay={() => { setDirectionIndex(0) }} onReopen={() => { void gateway.sendMessage(sessionId, 'Reopen the closed connector').then((next) => { setLiveReply(next); setReplyId(next.id); setDecision(next.pending ? 'pending' : null) }) }} onShowFloor={(nextFloor) => { setFloorId(nextFloor); setFloorPinned(true) }} hereName={hereId ? labelFor(hereId) : null} inputMode={inputMode} onInputMode={setInputMode} inputRef={inputRef} /> : <DebugPanel selection={selection} presentation={presentation} effects={visibleEffects} onLoad={loadReply} />}
      </div>
    </section>
    <footer className="next-bar"><div><span className="eyebrow">{copy.nextStep}</span><strong>{loading ? 'Working…' : nextText}</strong></div><button type="button" className="next-distance" onClick={advance} disabled={!presentation.route?.reachable}>{presentation.route?.reachable ? `${formatMetres(presentation.route.length_m)} ->` : `${copy.noRoute} ->`}</button></footer>
  </main>
}
