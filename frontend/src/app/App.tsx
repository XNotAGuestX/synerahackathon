import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { toUiError } from '../api/errors'
import type { UiError } from '../api/errors'
import { gateway, requestId } from '../api/gateway'
import type { BuildingSummary, InputMode } from '../api/gateway'
import { catalog } from '../api/fixtures'
import { clearRecovery, readRecovery, writeRecovery } from '../api/recovery'
import { placeById } from '../domain/clarify'
import { labelFromPlans, selectionFacts } from '../domain/live'
import { buildPresentation, formatMetres } from '../domain/presentation'
import type { Presentation } from '../domain/presentation'
import type { DiscoveryPlace } from '../domain/discovery'
import type { AskOption, ChatMessage, ClientContext, FloorPlan, FloorSummary, PendingAction, Point, Reply, ReplyId, Route, Selection, Session, TranscriptMessage } from '../domain/types'
import { GuidePanel, readableDirection } from '../features/guide/GuidePanel'
import { PlaceDiscovery } from '../features/discovery/PlaceDiscovery'
import { PlanImport } from '../features/building-ingestion/PlanImport'
import { DebugPanel } from '../features/debug/DebugPanel'
import { PlanCanvas } from '../rendering/PlanCanvas'
import { FloorStack3D } from '../rendering/floor-stack-3d/FloorStack3D'

const emptyPresentation = buildPresentation({ guideText: '', understood: null, effects: [], routes: [], pendingSummary: null, decision: null, confirmedEffects: [], confirmedClosedIds: [], confirmedText: '', cancelledText: '' })
type Theme = 'system' | 'light' | 'dark'

function replyFor(message: TranscriptMessage, routes: Route[] = []): Reply {
  return { id: 'accepted', userText: null, guideText: message.text, understood: message.understood, effects: message.effects, routes, pending: null }
}

function localMessage(text: string, reply?: Reply): ChatMessage {
  return { id: requestId(), role: 'guide', text, created_at: new Date().toISOString(), understood: reply?.understood ?? null, effects: reply?.effects ?? [], pending_action_id: reply?.pending?.id ?? null, reply }
}

export function App() {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const sessionRef = useRef<Session | null>(null)
  const epoch = useRef(0)
  const busyRef = useRef(false)
  const drawerRef = useRef<HTMLElement>(null)
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [mapView, setMapView] = useState<Presentation>(emptyPresentation)
  const [latestReply, setLatestReply] = useState<Reply | null>(null)
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [buildings, setBuildings] = useState<BuildingSummary[]>([])
  const [buildingId, setBuildingId] = useState(() => window.localStorage.getItem('wayfinder-building') ?? 'proc-factory-dev-003')
  const [floors, setFloors] = useState<FloorSummary[]>([])
  const [plans, setPlans] = useState<Map<string, FloorPlan>>(new Map())
  const [floorId, setFloorId] = useState('')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [hereId, setHereId] = useState<string | null>(null)
  const [stepFree, setStepFree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [booting, setBooting] = useState(true)
  const [ready, setReady] = useState(false)
  const [loadError, setLoadError] = useState<UiError | null>(null)
  const [reload, setReload] = useState(0)
  const [mobileView, setMobileView] = useState<'chat' | 'map'>('chat')
  const [drawer, setDrawer] = useState<'places' | 'location' | null>(null)
  const [locationFilter, setLocationFilter] = useState('')
  const [locationFloor, setLocationFloor] = useState('')
  const [pendingPlace, setPendingPlace] = useState<DiscoveryPlace | null>(null)
  const [routingId, setRoutingId] = useState<string | null>(null)
  const [directionIndex, setDirectionIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [stackOpen, setStackOpen] = useState(false)
  const [simulation, setSimulation] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [markerArmed, setMarkerArmed] = useState(false)
  const [mockPoint, setMockPoint] = useState<Point | null>(null)
  const [inputMode, setInputMode] = useState<InputMode>('text')
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = window.localStorage.getItem('talk-building-theme')
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  })
  const [importedPlans, setImportedPlans] = useState<Map<string, FloorPlan>>(new Map())
  const floor = floors.find((item) => item.id === floorId) ?? floors[0]
  const plan = floor ? plans.get(floor.id) ?? null : null
  const route = mapView.route
  const step = route?.directions[directionIndex]
  const nameOf = (id: string | null) => labelFromPlans([...plans.values()], id)
  const destinationAsset = [...plans.values()].flatMap((item) => item.assets).find((asset) => mapView.assetIds.has(asset.id) && asset.space_id === route?.destination_space_id)
  const destinationName = destinationAsset?.name ?? (route ? nameOf(route.destination_space_id) : '')

  const saveSession = (session: Session) => {
    sessionRef.current = session
    setHereId(session.current_space_id ?? null)
    setStepFree(session.preferences.step_free)
    writeRecovery({ id: session.id, buildingId: session.building_id, revision: session.revision, stepFree: session.preferences.step_free, lastRouteId: session.last_route_id ?? null, pendingActionId: session.pending_action_id ?? null, currentSpaceId: session.current_space_id ?? null })
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    window.localStorage.setItem('talk-building-theme', theme)
  }, [theme])

  useEffect(() => {
    const turn = ++epoch.current
    let cancelled = false
    busyRef.current = false
    setBusy(false); setBooting(true); setReady(false); setLoadError(null)
    setMessages([]); setLatestReply(null); setActiveMessageId(null); setPendingAction(null)
    setMapView(emptyPresentation); setHereId(null); setSelection(null); setPlans(new Map()); setFloors([])
    setPendingPlace(null); setDrawer(null); setDirectionIndex(0); setPlaying(false); setQuery('')
    setSimulation(false); setMockPoint(null); setDebugOpen(false); setStackOpen(false)
    sessionRef.current = null
    window.localStorage.setItem('wayfinder-building', buildingId)
    const open = async () => {
      const imported = importedPlans.get(buildingId)
      if (imported) {
        setFloors([imported.floor]); setPlans(new Map([[imported.floor.id, imported]])); setFloorId(imported.floor.id)
        setMessages([localMessage('Your imported plan is ready to inspect. Navigation needs a building connected to the guide service.')])
        return
      }
      const items = await gateway.listBuildings()
      if (cancelled) return
      setBuildings((current) => [...items, ...current.filter((item) => item.id.startsWith('imported:'))])
      const recovered = readRecovery(buildingId)
      let session: Session | null = null
      if (recovered) {
        try { session = await gateway.getSession(recovered.id) }
        catch (error) { if (toUiError(error).code !== '30002_session_not_found') throw error }
      }
      session ??= await gateway.createSession(buildingId)
      const stored = window.localStorage.getItem('wayfinder-step-free')
      if ((stored === 'true' || stored === 'false') && session.preferences.step_free !== (stored === 'true')) session = await gateway.updatePreferences(session.id, { step_free: stored === 'true' })
      const nextFloors = await gateway.listFloors(session.id)
      const [entries, transcript, savedRoute, action] = await Promise.all([
        Promise.all(nextFloors.map(async (item) => [item.id, await gateway.getFloorPlan(session!.id, item.id)] as const)),
        gateway.listMessages(session.id),
        session.last_route_id ? gateway.getRoute(session.id, session.last_route_id) : Promise.resolve(null),
        session.pending_action_id ? gateway.getAction(session.id, session.pending_action_id) : Promise.resolve(null),
      ])
      if (cancelled || turn !== epoch.current) return
      const nextPlans = new Map(entries)
      const remembered = session.current_space_id ?? recovered?.currentSpaceId
      if (remembered && entries.some(([, item]) => item.spaces.some((space) => space.id === remembered))) session = { ...session, current_space_id: remembered }
      saveSession(session)
      setFloors(nextFloors); setPlans(nextPlans)
      setFloorId(savedRoute?.legs[0]?.floor_id ?? nextFloors.find((item) => item.level === 0)?.id ?? nextFloors[0]?.id ?? '')
      const restored: ChatMessage[] = transcript.map((message) => ({ ...message, delivery: 'sent', reply: message.role === 'guide' ? replyFor(message, savedRoute && message.effects.some((effect) => effect.type === 'draw_route' && effect.route_id === savedRoute.id) ? [savedRoute] : []) : undefined }))
      if (savedRoute && !restored.some((message) => message.reply?.routes.some((item) => item.id === savedRoute.id))) restored.push(localMessage(savedRoute.reachable ? `Your route is ready: ${formatMetres(savedRoute.length_m)}.` : 'Your previous destination is unreachable.', { id: 'accepted', userText: null, guideText: '', understood: null, effects: [{ type: 'draw_route', route_id: savedRoute.id }], routes: [savedRoute], pending: null }))
      if (action?.status === 'pending') {
        const pending: PendingAction = { id: action.id, summary: action.summary, status: action.status, proposal: action.proposal ?? { kind: 'set_closed' } }
        setPendingAction(pending)
        const index = restored.findLastIndex((message) => message.pending_action_id === pending.id)
        if (index >= 0 && restored[index].reply) restored[index].reply = { ...restored[index].reply!, pending }
        else restored.push(localMessage(pending.summary, { id: 'pending', userText: null, guideText: pending.summary, understood: null, effects: [], routes: [], pending }))
      }
      setMessages(restored)
      const lastGuide = restored.findLast((message) => message.role === 'guide')
      setActiveMessageId(lastGuide?.id ?? null); setLatestReply(lastGuide?.reply ?? null)
      const routeMessage = restored.findLast((message) => savedRoute && message.effects.some((effect) => effect.type === 'draw_route' && effect.route_id === savedRoute.id))
      const routeAssets = (routeMessage?.understood?.resolved.asset_ids ?? []).filter((id) => entries.some(([, item]) => item.assets.some((asset) => asset.id === id && asset.space_id === savedRoute?.destination_space_id)))
      setMapView({ ...emptyPresentation, route: savedRoute, assetIds: new Set(routeAssets), closedIds: session.closed_ids ?? [] })
      setReady(true)
    }
    void open().catch((error: unknown) => { if (!cancelled) setLoadError(toUiError(error)) }).finally(() => { if (!cancelled) setBooting(false) })
    return () => { cancelled = true }
  }, [buildingId, importedPlans, reload])

  useEffect(() => {
    if (!route) return
    setDirectionIndex(0); setPlaying(false); setSelection(null)
    if (route.reachable && route.legs[0]) { setFloorId(route.legs[0].floor_id); setMobileView('map') }
  }, [route?.id])

  useEffect(() => {
    if (!playing || !route?.reachable || route.directions.length === 0) return
    const timer = window.setInterval(() => setDirectionIndex((index) => {
      const next = (index + 1) % route.directions.length
      const id = route.directions[next].floor_id
      if (id) setFloorId(id)
      return next
    }), 2200)
    return () => window.clearInterval(timer)
  }, [playing, route])

  useEffect(() => {
    if (!drawer) return
    const before = document.activeElement as HTMLElement | null
    drawerRef.current?.querySelector<HTMLInputElement>('input')?.focus()
    return () => before?.focus()
  }, [drawer])

  const acceptReply = (next: Reply) => {
    setLatestReply(next); setPendingAction(next.pending)
    if (next.session) saveSession(next.session)
    setMapView((previous) => buildPresentation({ previous, guideText: next.guideText, understood: next.understood, effects: next.effects, routes: next.routes, pendingSummary: next.pending?.summary ?? null, decision: next.pending ? 'pending' : null, confirmedEffects: [], confirmedClosedIds: [], confirmedText: '', cancelledText: '' }))
    if (!next.effects.some((effect) => effect.type === 'draw_route')) {
      const focus = next.effects.find((effect) => effect.type === 'focus')
      if (focus && 'floor_id' in focus && typeof focus.floor_id === 'string') setFloorId(focus.floor_id)
    }
    if (next.effects.some((effect) => effect.type === 'building_patched')) {
      const id = sessionRef.current?.id
      const turn = epoch.current
      if (id) void Promise.all(floors.map(async (item) => [item.id, await gateway.getFloorPlan(id, item.id)] as const)).then((entries) => { if (turn === epoch.current) setPlans(new Map(entries)) }).catch((error) => { if (turn === epoch.current) setLoadError(toUiError(error)) })
    }
  }

  const sendText = async (text: string, context: ClientContext = {}, retry?: ChatMessage) => {
    if (!text.trim() || busyRef.current || !sessionRef.current) return
    const turn = epoch.current
    const session = sessionRef.current
    const request = retry?.request ?? { text, key: requestId(), inputMode, sessionId: session.id, context: { current_space_id: hereId, selected_space_id: selection?.kind === 'space' ? selection.id : null, floor_level: floor?.level, preferences: { step_free: stepFree }, ...context } }
    const clientId = retry?.id ?? requestId()
    busyRef.current = true; setBusy(true); setLoadError(null)
    if (retry) setMessages((current) => current.map((message) => message.id === clientId ? { ...message, delivery: 'sending', error: undefined } : message))
    else setMessages((current) => [...current, { id: clientId, role: 'user', text, created_at: new Date().toISOString(), understood: null, effects: [], pending_action_id: null, delivery: 'sending', request }])
    try {
      let next: Reply
      try { next = await gateway.sendMessage(request.sessionId, request.text, request.inputMode, request.context, request.key) }
      catch (error) {
        if (toUiError(error).code !== '30002_session_not_found') throw error
        const fresh = await gateway.createSession(buildingId)
        if (turn !== epoch.current) return
        saveSession(fresh); setMapView(emptyPresentation); setPendingAction(null)
        setMessages((current) => current.filter((message) => message.id === clientId))
        request.sessionId = fresh.id; request.key = requestId()
        next = await gateway.sendMessage(fresh.id, request.text, request.inputMode, request.context, request.key)
      }
      if (turn !== epoch.current) return
      acceptReply(next)
      const received = next.messages?.length ? next.messages : [
        { id: requestId(), role: 'user' as const, text: request.text, created_at: new Date().toISOString(), understood: null, effects: [], pending_action_id: null },
        localMessage(next.guideText, next),
      ]
      const guideId = received.findLast((message) => message.role === 'guide')?.id ?? null
      setActiveMessageId(guideId)
      setMessages((current) => {
        const remaining = current.filter((message) => message.id !== clientId)
        for (const message of received) {
          const full: ChatMessage = { ...message, delivery: 'sent', reply: message.role === 'guide' ? next : undefined }
          const index = remaining.findIndex((item) => item.id === message.id)
          if (index < 0) remaining.push(full)
          else remaining[index] = full
        }
        return remaining
      })
      if (next.understood?.missing.includes('start')) { setLocationFloor(floor?.id ?? ''); setLocationFilter(''); setDrawer('location'); setMobileView('chat') }
    } catch (error) {
      if (turn === epoch.current) setMessages((current) => current.map((message) => message.id === clientId ? { ...message, delivery: 'failed', error: toUiError(error).message, request } : message))
    } finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false) } }
  }

  const routeToPlace = async (place: DiscoveryPlace, knownStart = hereId, preference = stepFree) => {
    if (busyRef.current || !sessionRef.current) return
    if (!knownStart) {
      setPendingPlace(place); setDrawer('location'); setLocationFloor(floor?.id ?? ''); setLocationFilter('')
      const message = localMessage(`Where are you starting? Choose a room to get directions to ${place.name}.`)
      setMessages((current) => [...current, message]); setActiveMessageId(message.id); setMobileView('chat')
      return
    }
    const turn = epoch.current
    busyRef.current = true; setBusy(true); setRoutingId(place.id); setLoadError(null)
    try {
      const computed = await gateway.createRoute(sessionRef.current.id, { start_space_id: knownStart, destination_space_id: place.id, step_free: preference, current_space_id: knownStart })
      if (turn !== epoch.current) return
      const next: Reply = { id: computed.reachable ? 'accepted' : 'unreachable', userText: null,
        guideText: computed.reachable ? computed.length_m === 0 ? `You're already at ${place.name}.` : `${place.name} is ${formatMetres(computed.length_m)} away. Follow the route on the map.` : `No route to ${place.name} with the current constraints.`,
        understood: null, effects: [{ type: 'draw_route', route_id: computed.id }, { type: 'highlight_assets', asset_ids: place.kind === 'asset' ? [place.id] : [] }], routes: [computed], pending: pendingAction }
      acceptReply(next)
      const message = localMessage(next.guideText, next)
      setMessages((current) => [...current, message]); setActiveMessageId(message.id)
      setHereId(knownStart); setPendingPlace(null); setDrawer(null)
      if (sessionRef.current) saveSession({ ...sessionRef.current, current_space_id: knownStart, last_route_id: computed.id })
    } catch (error) { if (turn === epoch.current) setLoadError(toUiError(error)) }
    finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false); setRoutingId(null) } }
  }

  const useLocation = async (id: string) => {
    const place = placeById([...plans.values()], floors, id)
    if (!place) return
    const roomId = place.kind === 'space' ? place.id : [...plans.values()].flatMap((item) => item.assets).find((item) => item.id === id)?.space_id
    if (!roomId) return
    setHereId(roomId); setDrawer(null)
    if (sessionRef.current) saveSession({ ...sessionRef.current, current_space_id: roomId })
    if (pendingPlace) await routeToPlace(pendingPlace, roomId)
    else if (latestReply?.understood?.missing.includes('start')) await sendText(`I am at ${place.name}.`, { current_space_id: roomId })
    else setMessages((current) => [...current, localMessage(`Your starting place is ${nameOf(roomId)}.`)])
  }

  const choose = async (option: AskOption, role: 'start' | 'destination') => {
    const id = option.place_id ?? option.id
    const place = placeById([...plans.values()], floors, id)
    if (role === 'start' && place) { await useLocation(id); return }
    await sendText(place ? `Take me to ${place.name}.` : option.label,
      place ? { destination_place_id: id } : {})
  }

  const toggleStepFree = async () => {
    if (busyRef.current) return
    const next = !stepFree
    const turn = epoch.current
    busyRef.current = true; setBusy(true)
    let updated = false
    try {
      if (sessionRef.current) {
        const session = await gateway.updatePreferences(sessionRef.current.id, { step_free: next })
        if (turn !== epoch.current) return
        saveSession(session)
      }
      else setStepFree(next)
      window.localStorage.setItem('wayfinder-step-free', String(next))
      updated = true
    } catch (error) { if (turn === epoch.current) setLoadError(toUiError(error)) }
    finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false) } }
    if (updated && turn === epoch.current && route?.reachable && route.destination_space_id) {
      setMapView((current) => ({ ...current, route: null }))
      const place = placeById([...plans.values()], floors, route.destination_space_id)
      if (place) await routeToPlace(place, route.start_space_id ?? hereId, next)
    }
  }

  const finishAction = async (confirm: boolean) => {
    const session = sessionRef.current
    if (!session || !pendingAction || busyRef.current) return
    const turn = epoch.current
    busyRef.current = true; setBusy(true)
    try {
      const action = await (confirm ? gateway.confirmAction(session.id, pendingAction.id) : gateway.cancelAction(session.id, pendingAction.id))
      const updated = await gateway.getSession(session.id)
      const entries = confirm ? await Promise.all(floors.map(async (item) => [item.id, await gateway.getFloorPlan(session.id, item.id)] as const)) : null
      if (turn !== epoch.current) return
      saveSession(updated); setPendingAction(null)
      if (entries) { setPlans(new Map(entries)); setMapView((current) => ({ ...current, route: null, closedIds: updated.closed_ids ?? [] })) }
      setMessages((current) => [...current.map((message) => message.reply?.pending?.id === pendingAction.id ? { ...message, reply: { ...message.reply, pending: { ...message.reply.pending, status: confirm ? 'confirmed' : 'cancelled' } } } : message), localMessage(action.summary)])
    } catch (error) { if (turn === epoch.current) setLoadError(toUiError(error)) }
    finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false) } }
  }

  const focusPlace = (place: DiscoveryPlace) => {
    setFloorId(place.floorId); setSelection({ kind: place.kind, id: place.id, name: place.name, floorId: place.floorId, floorName: place.floorName, note: place.type })
    setMobileView('map'); setDrawer(null)
  }
  const preview = (id: ReplyId) => { const next = catalog.replies[id]; acceptReply(next); const message = localMessage(next.guideText, next); setMessages((current) => [...current, message]); setActiveMessageId(message.id) }
  const submit = (event: FormEvent) => { event.preventDefault(); if (!query.trim() || busyRef.current || !ready) return; const text = query.trim(); setQuery(''); void sendText(text) }
  const nextDirection = () => { if (!route?.directions.length) return; const next = (directionIndex + 1) % route.directions.length; setDirectionIndex(next); const id = route.directions[next].floor_id; if (id) setFloorId(id) }
  const locationSpaces = [...plans.values()].flatMap((item) => item.spaces).filter((space) => (!locationFloor || space.floor_id === locationFloor) && `${space.name} ${space.ref ?? ''}`.toLowerCase().includes(locationFilter.toLowerCase())).slice(0, 40)

  return <main className={`app-shell navigation-app mobile-${mobileView}`}>
    <header className="topbar">
      <div className="brand"><span className="brand-mark" aria-hidden="true">W</span><span>Wayfinder</span></div>
      <select className="building-picker" aria-label="Choose building" value={buildingId} disabled={busy} onChange={(event) => setBuildingId(event.target.value)}>{(buildings.length ? buildings : [{ id: buildingId, name: 'Choose building' }]).map((building) => <option key={building.id} value={building.id}>{building.name}</option>)}</select>
      <button type="button" className="location-chip" aria-label="Set your location" onClick={() => { setLocationFloor(floor?.id ?? ''); setLocationFilter(''); setDrawer('location') }}>⌖ {hereId ? nameOf(hereId) : 'Set your location'}</button>
      <button type="button" className="step-free-toggle" aria-pressed={stepFree} disabled={busy} onClick={() => void toggleStepFree()}>Step-free</button>
      <button type="button" className="find-place-button" onClick={() => setDrawer('places')}>Find a place</button>
      <details className="more-menu"><summary>More</summary><div className="more-popover">
        <fieldset><legend>Appearance</legend>{(['system', 'light', 'dark'] as Theme[]).map((value) => <button type="button" key={value} aria-pressed={theme === value} onClick={() => setTheme(value)}>{value === 'system' ? 'Auto' : value === 'light' ? 'Light' : 'Dark'}</button>)}</fieldset>
        <label><input type="checkbox" checked={inputMode === 'transcript'} onChange={(event) => setInputMode(event.target.checked ? 'transcript' : 'text')} />Voice input</label>
        <label><input type="checkbox" checked={stackOpen} onChange={(event) => setStackOpen(event.target.checked)} />3D floor overview</label>
        <label><input type="checkbox" checked={simulation} onChange={(event) => setSimulation(event.target.checked)} />Walking simulation</label>
        {route?.reachable && <button type="button" onClick={() => setPlaying((value) => !value)}>{playing ? 'Pause route playback' : 'Play route playback'}</button>}
        {import.meta.env.DEV && <label><input type="checkbox" checked={debugOpen} onChange={(event) => setDebugOpen(event.target.checked)} />Diagnostics</label>}
        <PlanImport onApply={(imported) => { const id = `imported:${imported.floor.id}`; setImportedPlans((current) => new Map(current).set(id, imported)); setBuildings((current) => [...current.filter((item) => item.id !== id), { id, name: imported.floor.name, floors: 1, has_lift: false, has_step_free_entrance: false }]); setBuildingId(id) }} />
        <p className="connection-note">{gateway.mode === 'fixture' ? 'Demo: saved examples only.' : 'Connected building service'}</p><a href={gateway.mode === 'fixture' ? '/' : '/?demo=1'}>{gateway.mode === 'fixture' ? 'Use live building service' : 'Open example demo'}</a>
      </div></details>
    </header>
    {gateway.mode === 'fixture' && <p className="demo-banner" role="status">Example demo — only saved routes are available.</p>}
    {loadError && <div className="connection-banner" role="alert"><span>{loadError.message} {!ready && 'Start the backend on port 8000, then reconnect.'}</span><button type="button" onClick={() => setReload((value) => value + 1)}>Reconnect</button><button type="button" aria-label="Dismiss error" onClick={() => setLoadError(null)}>×</button></div>}
    <nav className="mobile-tabs" aria-label="Workspace"><button type="button" aria-pressed={mobileView === 'chat'} onClick={() => setMobileView('chat')}>Chat</button><button type="button" aria-pressed={mobileView === 'map'} onClick={() => setMobileView('map')}>Map {route?.reachable ? '•' : ''}</button></nav>
    <section className="workspace">
      <section className="map-column" aria-label="Building map">
        <div className="map-toolbar"><div><h1>{floor?.name ?? 'Building map'}</h1>{route?.reachable && <p className="map-route-target">To {destinationName} · {formatMetres(route.length_m)}</p>}</div><div className="floor-rail" role="toolbar" aria-label="Floors">{floors.map((item) => <button type="button" key={item.id} aria-label={`Show ${item.name}`} aria-pressed={item.id === floor?.id} className={item.id === floor?.id ? 'active' : undefined} onClick={() => setFloorId(item.id)}>{item.level}</button>)}</div></div>
        {booting ? <p className="map-loading" role="status">Loading your building…</p> : !floor ? <div className="map-loading">Connect to a building to see its map.</div> : <div className="plan-stage">
          <PlanCanvas plan={plan} floorName={floor.name} route={route} spaceReasons={mapView.spaceReasons} assetIds={mapView.assetIds} closedIds={mapView.closedIds} focusPoint={mapView.focusFloorId === floor.id ? mapView.focusPoint : null} stepPoint={step?.floor_id === floor.id ? step.at : null} selectionId={selection?.id ?? null} onSelect={setSelection} onFocusSelection={() => {}} simulation={simulation} mockPoint={mockPoint} markerArmed={markerArmed} stepFree={stepFree} onPlaceMarker={(point) => { setMockPoint(point); setMarkerArmed(false) }} />
          <div className="map-caption" role="status">{selection ? <><span><strong>{selection.name}</strong> · {selection.floorName}</span>{selection.kind !== 'opening' && <button type="button" disabled={busy} onClick={() => void useLocation(selection.id)}>Use as my location</button>}</> : <span>{hereId ? `Starting at ${nameOf(hereId)}` : 'Choose a room to set your starting point.'}</span>}</div>
        </div>}
        {stackOpen && <FloorStack3D plans={[...plans.values()]} route={route} activeFloorId={floor?.id ?? ''} />}
        {debugOpen && <DebugPanel selection={selection} presentation={mapView} effects={latestReply?.effects ?? []} facts={plan && selection ? selectionFacts(plan, selection) : null} markerArmed={markerArmed} onArmMarker={() => setMarkerArmed((value) => !value)} onLoad={preview} onLeavePreview={() => { setDebugOpen(false); setReload((value) => value + 1) }} />}
      </section>
      <GuidePanel query={query} messages={messages} busy={busy} ready={ready} activeRoute={route} activeMessageId={activeMessageId} pendingActionId={pendingAction?.id ?? null} directionIndex={directionIndex} onQuery={setQuery} onSubmit={submit} onChoose={(option, role) => { void choose(option, role) }} onRetry={(message) => { void sendText(message.text, {}, message) }} onConfirm={() => { void finishAction(true) }} onCancel={() => { void finishAction(false) }} onShowMap={() => setMobileView('map')} onShowFloor={(id) => { setFloorId(id); setMobileView('map') }} inputMode={inputMode} inputRef={inputRef} floors={floors} />
    </section>
    {route && <footer className="next-bar" aria-label="Current route"><div><span>{route.reachable ? formatMetres(route.length_m) : 'No route available'}</span><strong>{route.reachable ? step ? readableDirection(step.text) : 'Your route is shown on the map.' : 'Try another destination or change your route constraints.'}</strong></div><button type="button" onClick={() => { setMapView((current) => ({ ...current, route: null })); setPlaying(false) }} aria-label="Hide route">×</button>{route.reachable && route.directions.length > 1 && <button type="button" onClick={nextDirection}>Next direction →</button>}</footer>}
    {drawer && <div className="drawer-backdrop" onClick={(event) => { if (event.target === event.currentTarget) setDrawer(null) }}>
      <aside ref={drawerRef} className="navigation-drawer" role="dialog" aria-modal="true" aria-label={drawer === 'location' ? 'Choose your starting location' : 'Find a place'} onKeyDown={(event) => {
        if (event.key === 'Escape') setDrawer(null)
        if (event.key === 'Tab') { const items = [...(drawerRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, [tabindex="0"]') ?? [])].filter((item) => item.offsetParent !== null); const first = items[0]; const last = items.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() } }
      }}><header><h2>{drawer === 'location' ? 'Where are you starting?' : 'Find a place'}</h2><button type="button" aria-label="Close search" onClick={() => setDrawer(null)}>×</button></header>
        {drawer === 'places' ? <PlaceDiscovery plans={[...plans.values()]} floors={floors} stepFree={stepFree} busyId={routingId} onToggleStepFree={() => { void toggleStepFree() }} onFocus={focusPlace} onRoute={(place) => { void routeToPlace(place) }} /> : <><p>Pick the room you are in.</p><input aria-label="Search starting rooms" placeholder="Room name or number" value={locationFilter} onChange={(event) => setLocationFilter(event.target.value)} /><select aria-label="Starting floor" value={locationFloor} onChange={(event) => setLocationFloor(event.target.value)}><option value="">All floors</option>{floors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><ul className="location-results">{locationSpaces.map((space) => <li key={space.id}><button type="button" disabled={busy} onClick={() => { void useLocation(space.id) }}><strong>{space.name}</strong><span>{floors.find((item) => item.id === space.floor_id)?.name}</span></button></li>)}</ul>{locationSpaces.length === 0 && <p>No rooms match. Try another name or floor.</p>}</>}
      </aside>
    </div>}
  </main>
}
