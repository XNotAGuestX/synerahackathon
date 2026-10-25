import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { toUiError } from '../api/errors'
import type { UiError } from '../api/errors'
import { catalog } from '../api/fixtures'
import { gateway, requestId } from '../api/gateway'
import { CampusWalkway } from '../features/campus/CampusWalkway'
import type { BuildingSummary, InputMode } from '../api/gateway'
import { readRecovery, writeRecovery } from '../api/recovery'
import { placeById, withStartOptions } from '../domain/clarify'
import { distance, labelFromPlans, selectionFacts } from '../domain/live'
import type { DiscoveryPlace } from '../domain/discovery'
import { editedFloors } from '../domain/editor'
import { buildPresentation, formatMetres } from '../domain/presentation'
import type { Presentation } from '../domain/presentation'
import type { AskOption, ChatMessage, ClientContext, FloorPlan, FloorSummary, GuidanceEvent, PendingAction, Point, Reply, ReplyId, Route, Selection, Session, TranscriptMessage } from '../domain/types'
import { DebugPanel } from '../features/debug/DebugPanel'
import { PlaceDiscovery } from '../features/discovery/PlaceDiscovery'
import { GuidePanel, readableDirection } from '../features/guide/GuidePanel'
import { useGuidanceFeed } from '../features/live/useGuidanceFeed'
import { usePositionSync } from '../features/live/usePositionSync'
import type { Walker } from '../features/live/usePositionSync'
import { EditorPanel } from '../features/object-editor/EditorPanel'
import { useObjectEditor } from '../features/object-editor/useObjectEditor'
import { useVoice } from '../features/voice/useVoice'
import { copy } from '../i18n/en'
import { PlanImport } from '../features/building-ingestion/PlanImport'
import { PlanCanvas } from '../rendering/PlanCanvas'
const FloorStack3D = lazy(() => import('../rendering/floor-stack-3d/FloorStack3D').then((module) => ({ default: module.FloorStack3D })))

const emptyPresentation = buildPresentation({ guideText: '', understood: null, effects: [], routes: [], pendingSummary: null, decision: null, confirmedEffects: [], confirmedClosedIds: [], confirmedText: catalog.confirmedText, cancelledText: copy.cancelled })
type ThemeMode = 'system' | 'light' | 'dark'

const themeModes: ThemeMode[] = ['system', 'light', 'dark']

function initialThemeMode(): ThemeMode {
  const stored = window.localStorage.getItem('talk-building-theme')
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

function replyFor(message: TranscriptMessage, routes: Route[] = []): Reply {
  return { id: 'accepted', userText: null, guideText: message.text, understood: message.understood, effects: message.effects, routes, pending: null }
}

function localMessage(text: string, reply?: Reply): ChatMessage {
  return { id: requestId(), role: 'guide', text, created_at: new Date().toISOString(), understood: reply?.understood ?? null, effects: reply?.effects ?? [], pending_action_id: reply?.pending?.id ?? null, reply }
}

export function App() {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const mapRef = useRef<HTMLDivElement>(null)
  const drawerRef = useRef<HTMLElement>(null)
  const announcedPoint = useRef<Point | null>(null)
  const sessionRef = useRef<Session | null>(null)
  // Increments on every building switch so late responses from the old building are ignored.
  const epoch = useRef(0)
  const busyRef = useRef(false)
  const editButtonRef = useRef<HTMLButtonElement>(null)
  const walkerRef = useRef<Walker | null>(null)
  const jumpSeqRef = useRef(0)
  const viewedFloorRef = useRef('')
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [mapView, setMapView] = useState<Presentation>(emptyPresentation)
  const [latestReply, setLatestReply] = useState<Reply | null>(null)
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [floors, setFloors] = useState<FloorSummary[]>(catalog.floors)
  const [plans, setPlans] = useState<Map<string, FloorPlan>>(new Map(catalog.floors.map((floor) => [floor.id, catalog.plans.get(floor.id)!])))
  const stackPlans = useMemo(() => [...plans.values()], [plans])
  const [floorId, setFloorId] = useState(catalog.floors.find((floor) => floor.level === 0)?.id ?? catalog.floors[0].id)
  const [floorPinned, setFloorPinned] = useState(false)
  // Null until the walker first appears; afterwards the floor it stands on.
  const [walkerFloorId, setWalkerFloorId] = useState<string | null>(null)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [activePanel, setActivePanel] = useState<'guide' | 'debug'>('guide')
  const [mapFocusActive, setMapFocusActive] = useState(false)
  const [directionIndex, setDirectionIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [buildings, setBuildings] = useState<BuildingSummary[]>([])
  const [buildingId, setBuildingId] = useState(() => window.localStorage.getItem('wayfinder-building') ?? 'proc-factory-dev-003')
  // The live hooks (voice, guidance, walker sync, editor) key on the session id string.
  const [sessionId, setSessionId] = useState('')
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)
  const [loadError, setLoadError] = useState<UiError | null>(null)
  const [booting, setBooting] = useState(true)
  const [reload, setReload] = useState(0)
  const [revision, setRevision] = useState(1)
  const [inputMode, setInputMode] = useState<InputMode>('text')
  const [stackOpen, setStackOpen] = useState(true)
  const [themeMode, setThemeMode] = useState<ThemeMode>(initialThemeMode)
  const [stepFree, setStepFree] = useState(() => window.localStorage.getItem('wayfinder-step-free') === 'true')
  const [routingId, setRoutingId] = useState<string | null>(null)
  const [hereId, setHereId] = useState<string | null>(null)
  // Destination picked while the start was still unknown; routed once a start is chosen.
  const [pendingPlace, setPendingPlace] = useState<DiscoveryPlace | null>(null)
  const [locationOpen, setLocationOpen] = useState(false)
  const [locationFilter, setLocationFilter] = useState('')
  const [locationFloor, setLocationFloor] = useState('')
  const [markerArmed, setMarkerArmed] = useState(false)
  const [mockPoint, setMockPoint] = useState<Point | null>(null)
  const [checkpointNote, setCheckpointNote] = useState<string | null>(null)
  const [importedPlans, setImportedPlans] = useState<Map<string, FloorPlan>>(new Map())
  const debugEnabled = import.meta.env.DEV

  const floor = floors.find((item) => item.id === floorId) ?? floors[0] ?? catalog.floors[0]
  const plan = plans.get(floor.id) ?? null
  viewedFloorRef.current = floor.id
  const walkerHere = walkerFloorId === null || walkerFloorId === floor.id
  usePositionSync(sessionId, () => {
    const walker = walkerRef.current
    return walker && walker.floorId === viewedFloorRef.current ? walker : null
  })
  const speakRef = useRef<(event: GuidanceEvent) => void>(() => undefined)
  const feed = useGuidanceFeed(sessionId, (event) => speakRef.current(event))
  const guidanceActive = feed.guidance?.status === 'active'
  const targetWaypoint = guidanceActive ? feed.guidance?.waypoints.find((waypoint) => waypoint.index === feed.guidance?.target_index) ?? null : null
  const guidanceTarget = targetWaypoint && targetWaypoint.floor_id === floor.id ? targetWaypoint.at : null
  // Active guidance keeps its route on the map after a later reply without one ("thanks", "how far?").
  const guidedRouteId = guidanceActive ? feed.guidance?.route_id ?? null : null
  const [guidedRoute, setGuidedRoute] = useState<Route | null>(null)
  useEffect(() => {
    if (!sessionId || !guidedRouteId) return
    let cancelled = false
    gateway.getRoute(sessionId, guidedRouteId).then((next) => { if (!cancelled) setGuidedRoute(next) }, (error: unknown) => { if (!cancelled) setLoadError(toUiError(error)) })
    return () => { cancelled = true }
  }, [sessionId, guidedRouteId])
  const route = mapView.route ?? (guidedRouteId && guidedRoute?.id === guidedRouteId ? guidedRoute : null)
  const step = route?.directions[directionIndex]
  const nextText = !route ? copy.askRoute : route.reachable ? (step ? readableDirection(step.text) : copy.askRoute) : copy.noRoute
  const placeName = (id: string | null) => labelFromPlans([...plans.values()], id)
  const destinationAsset = [...plans.values()].flatMap((item) => item.assets).find((asset) => mapView.assetIds.has(asset.id) && asset.space_id === route?.destination_space_id)
  const destinationName = destinationAsset?.name ?? (route ? placeName(route.destination_space_id) : '')

  const saveSession = (session: Session) => {
    sessionRef.current = session
    setSessionId(session.id)
    setHereId(session.current_space_id ?? null)
    setStepFree(session.preferences.step_free)
    setRevision(session.revision)
    writeRecovery({ id: session.id, buildingId: session.building_id, revision: session.revision, stepFree: session.preferences.step_free, lastRouteId: session.last_route_id ?? null, pendingActionId: session.pending_action_id ?? null, currentSpaceId: session.current_space_id ?? null })
  }

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
    const turn = ++epoch.current
    let cancelled = false
    busyRef.current = false
    setBusy(false); setBooting(true); setReady(false); setLoadError(null)
    setMessages([]); setLatestReply(null); setActiveMessageId(null); setPendingAction(null)
    setMapView(emptyPresentation); setHereId(null); setSelection(null); setPlans(new Map()); setFloors([])
    setPendingPlace(null); setLocationOpen(false); setDirectionIndex(0); setPlaying(false); setQuery('')
    setMockPoint(null)
    sessionRef.current = null
    setSessionId(''); setWalkerFloorId(null)
    walkerRef.current = null
    window.localStorage.setItem('wayfinder-building', buildingId)
    const open = async () => {
      const imported = importedPlans.get(buildingId)
      if (imported) {
        setFloors([imported.floor]); setPlans(new Map([[imported.floor.id, imported]])); setFloorId(imported.floor.id); setRevision(1)
        setMessages([localMessage(copy.importedNoRoute)])
        return
      }
      const items = await gateway.listBuildings().catch(() => [])
      if (!cancelled && items.length) setBuildings((current) => [...items, ...current.filter((item) => item.id.startsWith('imported:') && !items.some((next) => next.id === item.id))])
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
      // Rebuild the chat from the server transcript; the saved route stays attached to the reply that drew it.
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
      const restoredView = { ...emptyPresentation, route: savedRoute, assetIds: new Set(routeAssets), closedIds: session.closed_ids ?? [] }
      const ghosts = action?.status === 'pending' ? action.preview_effects.filter((effect) => effect.type === 'preview_objects') : []
      setMapView(ghosts.length ? buildPresentation({ previous: restoredView, guideText: '', understood: null, effects: ghosts, routes: [], pendingSummary: action!.summary, decision: 'pending', confirmedEffects: [], confirmedClosedIds: [], confirmedText: '', cancelledText: '' }) : restoredView)
      setReady(true)
    }
    void open().catch((error: unknown) => {
      if (cancelled) return
      const ui = toUiError(error)
      if (ui.code === '30001_building_not_found') ui.message = copy.otherBuilding
      setLoadError(ui)
    }).finally(() => { if (!cancelled) setBooting(false) })
    return () => { cancelled = true }
  }, [buildingId, importedPlans, reload])

  useEffect(() => { if (!floorPinned && mapView.focusFloorId) setFloorId(mapView.focusFloorId) }, [floorPinned, mapView.focusFloorId])

  useEffect(() => {
    if (!route) return
    setDirectionIndex(0); setPlaying(false)
    if (route.reachable && route.legs[0]) { setFloorId(route.legs[0].floor_id); setFloorPinned(true) }
  }, [route?.id])

  useEffect(() => {
    if (!locationOpen) return
    const before = document.activeElement as HTMLElement | null
    drawerRef.current?.querySelector<HTMLInputElement>('input')?.focus()
    return () => before?.focus()
  }, [locationOpen])

  const acceptReply = (next: Reply) => {
    setLatestReply(next); setPendingAction(next.pending); setFloorPinned(false)
    if (next.session) saveSession(next.session)
    setMapView((previous) => buildPresentation({ previous, guideText: next.guideText, understood: next.understood, effects: next.effects, routes: next.routes, pendingSummary: next.pending?.summary ?? null, decision: next.pending ? 'pending' : null, confirmedEffects: [], confirmedClosedIds: [], confirmedText: '', cancelledText: '' }))
    if (next.effects.some((effect) => effect.type === 'building_patched')) {
      const id = sessionRef.current?.id
      const turn = epoch.current
      if (id) void Promise.all(floors.map(async (item) => [item.id, await gateway.getFloorPlan(id, item.id)] as const)).then((entries) => { if (turn === epoch.current) setPlans(new Map(entries)) }).catch((error) => { if (turn === epoch.current) setLoadError(toUiError(error)) })
    }
  }

  const onWalkerMove = (moveFloorId: string, point: Point, source: 'walk' | 'jump') => {
    if (source === 'jump') jumpSeqRef.current += 1
    walkerRef.current = { floorId: moveFloorId, point, jumpSeq: jumpSeqRef.current }
    setWalkerFloorId((current) => current === moveFloorId ? current : moveFloorId)
  }
  const changeWalkerFloor = (nextFloorId: string) => {
    setWalkerFloorId(nextFloorId)
    setFloorId(nextFloorId)
    setFloorPinned(true)
  }
  const guideMe = async () => {
    if (!sessionId || !route?.reachable) return
    try { await gateway.startGuidance(sessionId, route.id) } catch (error: unknown) { setLoadError(toUiError(error)) }
    feed.refresh()
  }
  const stopGuidance = async () => {
    if (!sessionId) return
    try { await gateway.stopGuidance(sessionId) } catch (error: unknown) { setLoadError(toUiError(error)) }
    feed.refresh()
  }

  /** Reload changed floors and the revision after a building edit. Resolves with the fresh plans. */
  const refreshFloors = async (floorIds: string[]): Promise<Map<string, FloorPlan>> => {
    const id = sessionRef.current?.id
    if (!id) return new Map()
    const unique = [...new Set(floorIds)].filter((item) => plans.has(item) || floors.some((entry) => entry.id === item))
    const [session, entries] = await Promise.all([
      gateway.getSession(id),
      Promise.all(unique.map(async (item) => [item, await gateway.getFloorPlan(id, item)] as const)),
    ])
    setRevision(session.revision)
    setPlans((current) => { const next = new Map(current); for (const [item, nextPlan] of entries) next.set(item, nextPlan); return next })
    return new Map(entries)
  }

  const editor = useObjectEditor({ sessionId, plans, floors, floorId: floor.id, selection, onSelect: setSelection, refreshFloors, buttonRef: editButtonRef })

  // A click on the flat plan or the 3D stack; the 3D stack can pick items on other floors. Items open in the editor.
  const selectOnMap = (next: Selection) => {
    setSelection(next)
    if (next.floorId !== floor.id) { setFloorId(next.floorId); setFloorPinned(true) }
    if (next.kind === 'asset') editor.editItem(next)
  }

  const openLocationPicker = () => { setLocationFloor(floor?.id ?? ''); setLocationFilter(''); setLocationOpen(true) }

  const sendText = async (text: string, context: ClientContext = {}, retry?: ChatMessage): Promise<Reply | null> => {
    if (!text.trim() || busyRef.current || !sessionRef.current) return null
    const turn = epoch.current
    const session = sessionRef.current
    const request = retry?.request ?? { text, key: requestId(), inputMode, sessionId: session.id, context: { current_space_id: hereId, selected_space_id: selection?.kind === 'space' ? selection.id : null, selected_object_id: selection && selection.kind !== 'space' ? selection.id : null, floor_level: floor?.level, preferences: { step_free: stepFree }, ...context } }
    const clientId = retry?.id ?? requestId()
    busyRef.current = true; setBusy(true); setLoadError(null)
    if (retry) setMessages((current) => current.map((message) => message.id === clientId ? { ...message, delivery: 'sending', error: undefined } : message))
    else setMessages((current) => [...current, { id: clientId, role: 'user', text, created_at: new Date().toISOString(), understood: null, effects: [], pending_action_id: null, delivery: 'sending', request }])
    let sent: Reply | null = null
    try {
      let next: Reply
      try { next = await gateway.sendMessage(request.sessionId, request.text, request.inputMode, request.context, request.key) }
      catch (error) {
        if (toUiError(error).code !== '30002_session_not_found') throw error
        const fresh = await gateway.createSession(buildingId)
        if (turn !== epoch.current) return null
        saveSession(fresh); setMapView(emptyPresentation); setPendingAction(null)
        setMessages((current) => current.filter((message) => message.id === clientId))
        request.sessionId = fresh.id; request.key = requestId()
        next = await gateway.sendMessage(fresh.id, request.text, request.inputMode, request.context, request.key)
      }
      if (turn !== epoch.current) return null
      next = withStartOptions(next, [...plans.values()])
      acceptReply(next)
      sent = next
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
      if (next.understood?.missing.includes('start')) openLocationPicker()
    } catch (error) {
      if (turn === epoch.current) setMessages((current) => current.map((message) => message.id === clientId ? { ...message, delivery: 'failed', error: toUiError(error).message, request } : message))
    } finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false) } }
    return sent
  }

  const voice = useVoice({ active: inputMode === 'voice', sessionId, send: (text) => sendText(text) })
  speakRef.current = voice.speakGuidance

  const focusDiscoveryPlace = (place: DiscoveryPlace) => {
    setFloorId(place.floorId)
    setFloorPinned(true)
    setSelection({ kind: place.kind, id: place.id, name: place.name, floorId: place.floorId, floorName: place.floorName, note: place.type })
  }

  // Route A (known start) to B (picked place); without a start, ask for it first.
  const routeToPlace = async (place: DiscoveryPlace, knownStart = hereId, preference = stepFree) => {
    if (busyRef.current) return
    if (!sessionRef.current) {
      if (importedPlans.has(buildingId)) setLoadError({ message: copy.importedNoRoute, code: null, traceId: null, requestId: null })
      return
    }
    if (!knownStart) {
      setPendingPlace(place); openLocationPicker()
      const message = localMessage(`Where are you starting? Choose a room to get directions to ${place.name}.`)
      setMessages((current) => [...current, message]); setActiveMessageId(message.id)
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
      setHereId(knownStart); setPendingPlace(null); setLocationOpen(false)
      if (sessionRef.current) saveSession({ ...sessionRef.current, current_space_id: knownStart, last_route_id: computed.id })
    } catch (error) { if (turn === epoch.current) setLoadError(toUiError(error)) }
    finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false); setRoutingId(null) } }
  }

  const useLocation = async (id: string) => {
    const place = placeById([...plans.values()], floors, id)
    if (!place) return
    const roomId = place.kind === 'space' ? place.id : [...plans.values()].flatMap((item) => item.assets).find((item) => item.id === id)?.space_id
    if (!roomId) return
    setHereId(roomId); setLocationOpen(false)
    if (sessionRef.current) saveSession({ ...sessionRef.current, current_space_id: roomId })
    if (pendingPlace) await routeToPlace(pendingPlace, roomId)
    else if (latestReply?.understood?.missing.includes('start')) await sendText(`I am at ${place.name}.`, { current_space_id: roomId })
    else setMessages((current) => [...current, localMessage(`Your starting place is ${placeName(roomId)}.`)])
  }

  const choose = async (option: AskOption, role: 'start' | 'destination') => {
    const id = option.place_id ?? option.id
    const place = placeById([...plans.values()], floors, id)
    if (role === 'start' && place) { await useLocation(id); return }
    await sendText(place ? `Take me to ${place.name}.` : option.label, place ? { destination_place_id: id } : {})
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
    // A changed preference invalidates the shown route; compute it again for the same A and B.
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
      const edit = confirm ? editedFloors(action) : null
      saveSession(updated); setPendingAction(null)
      setMapView((current) => ({ ...current, previewObjects: null }))
      if (entries) { setPlans(new Map(entries)); setMapView((current) => ({ ...current, route: null, closedIds: updated.closed_ids ?? [] })) }
      setMessages((current) => [...current.map((message) => message.reply?.pending?.id === pendingAction.id ? { ...message, reply: { ...message.reply, pending: { ...message.reply.pending, status: confirm ? 'confirmed' : 'cancelled' } } } : message), localMessage(edit?.summary ?? action.summary)])
    } catch (error) { if (turn === epoch.current) setLoadError(toUiError(error)) }
    finally { if (turn === epoch.current) { busyRef.current = false; setBusy(false) } }
  }

  const preview = (id: ReplyId) => { const next = catalog.replies[id]; acceptReply(next); const message = localMessage(next.guideText, next); setMessages((current) => [...current, message]); setActiveMessageId(message.id) }
  const submit = (event: FormEvent) => { event.preventDefault(); if (!query.trim() || busyRef.current || !ready) return; const text = query.trim(); setQuery(''); void sendText(text) }

  useEffect(() => {
    if (!mockPoint || !step?.at || step.floor_id !== floor.id) return
    if (distance(mockPoint, step.at) > 1.5) return
    if (mockPoint === announcedPoint.current) return
    announcedPoint.current = mockPoint
    setCheckpointNote(copy.checkpoint)
    setDirectionIndex((index) => index + 1)
  }, [mockPoint, step, floor.id])

  useEffect(() => {
    if (!playing) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const timer = window.setInterval(() => {
      setDirectionIndex((index) => {
        const directions = route?.directions ?? []
        if (!route?.reachable || directions.length === 0) return index
        const nextIndex = (index + 1) % directions.length
        const nextFloor = directions[nextIndex]?.floor_id
        if (nextFloor) {
          setFloorId(nextFloor)
          setFloorPinned(true)
        }
        return nextIndex
      })
    }, 2200)
    return () => window.clearInterval(timer)
  }, [playing, route])

  const advance = () => {
    const directions = route?.directions ?? []
    if (!route?.reachable || directions.length === 0) return
    const nextIndex = (directionIndex + 1) % directions.length
    setDirectionIndex(nextIndex)
    if (directions[nextIndex]?.floor_id) { setFloorId(directions[nextIndex].floor_id); setFloorPinned(true) }
  }

  const locationSpaces = [...plans.values()].flatMap((item) => item.spaces).filter((space) => (!locationFloor || space.floor_id === locationFloor) && `${space.name} ${space.ref ?? ''}`.toLowerCase().includes(locationFilter.toLowerCase())).slice(0, 40)

  return <main className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark" aria-hidden="true">W</span><span>{copy.title}</span></div><div className="building-meta"><span className="eyebrow">{copy.buildingEyebrow}</span><select className="building-picker" value={buildingId} disabled={busy} onChange={(event) => setBuildingId(event.target.value)} aria-label="Choose building">{(buildings.length ? buildings : [{ id: buildingId, name: catalog.buildingName } as BuildingSummary]).map((building) => <option key={building.id} value={building.id}>{building.name}</option>)}</select><CampusWalkway /><button type="button" className="location-chip" aria-label="Set your location" onClick={openLocationPicker}>⌖ {hereId ? placeName(hereId) : 'Set your location'}</button><span className="status-pill"><span />{ready ? 'API connected' : 'API disconnected'}</span><div className="theme-switcher" role="group" aria-label="Theme"><span className="sr-only">Theme</span>{themeModes.map((mode) => <button key={mode} type="button" className={themeMode === mode ? 'active' : undefined} aria-pressed={themeMode === mode} onClick={() => setThemeMode(mode)}>{mode === 'system' ? 'Auto' : mode === 'light' ? 'Light' : 'Dark'}</button>)}</div></div></header>
    {booting && <p className="app-status" role="status">{copy.loadingPlan}</p>}
    {loadError && <div className="app-alert" role="alert"><strong>{loadError.code ?? copy.apiUnavailable}</strong><span>{loadError.message}</span>{loadError.traceId && <span>trace {loadError.traceId}</span>}{loadError.requestId && <span>request {loadError.requestId}</span>}{!ready && <button type="button" onClick={() => setReload((value) => value + 1)}>Reconnect</button>}</div>}
    <PlaceDiscovery plans={[...plans.values()]} floors={floors} stepFree={stepFree} busyId={routingId} onToggleStepFree={() => { void toggleStepFree() }} onFocus={focusDiscoveryPlace} onRoute={(place) => { void routeToPlace(place) }} />
    <section className="workspace"><div className="map-column" ref={mapRef}><div className="map-toolbar"><div><span className="eyebrow">{copy.planEyebrow}</span><h1>{floor.name}</h1>{route?.reachable && <p className="map-route-target">To {destinationName} · {formatMetres(route.length_m)}</p>}</div><div className="map-toolbar-actions"><button type="button" ref={editButtonRef} className="edit-map-toggle" aria-pressed={editor.open} aria-keyshortcuts="E" title={copy.editor.openHint} onClick={editor.toggle}><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><path d="M4 20h4L19 9l-4-4L4 16v4Z M13.5 6.5l4 4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg><span>{editor.open ? copy.editor.done : copy.editor.open}</span></button><div className="floor-rail" role="toolbar" aria-label="Floors">{floors.map((item) => <button type="button" key={item.id} className={item.id === floor.id ? 'active' : undefined} aria-pressed={item.id === floor.id} aria-label={`${copy.showFloor} ${item.name}`} onClick={() => { setFloorId(item.id); setFloorPinned(true) }}>{item.level}</button>)}<button type="button" className="floor-rail-toggle" aria-pressed={stackOpen} onClick={() => setStackOpen((open) => !open)}>{stackOpen ? copy.flatPlan : copy.stackFloors}</button>{debugEnabled && <button type="button" aria-pressed={activePanel === 'debug' && mapFocusActive} onClick={() => { setMapFocusActive(true); setActivePanel('debug') }}>{copy.debug}</button>}</div></div></div><div className="plan-stage"><PlanCanvas plan={plan} floorName={floor.name} route={route} spaceReasons={mapView.spaceReasons} assetIds={mapView.assetIds} closedIds={mapView.closedIds} focusPoint={mapView.focusFloorId === floor.id ? mapView.focusPoint : null} stepPoint={step?.floor_id === floor.id ? step.at : null} storyIndex={directionIndex} selectionId={selection?.id ?? null} onSelect={selectOnMap} onFocusSelection={(focused) => { setMapFocusActive(Boolean(focused)); setActivePanel(debugEnabled && focused ? 'debug' : 'guide') }} mockPoint={mockPoint} markerArmed={markerArmed} stepFree={stepFree} onPlaceMarker={(point) => { setMockPoint(point); setMarkerArmed(false); const near = plan?.spaces.find((space) => space.polygon.length > 0 && Math.hypot(point[0] - space.polygon[0][0], point[1] - space.polygon[0][1]) < 8); if (near) void sendText(`I am at ${near.name}`, { current_space_id: near.id }) }} walkerHere={walkerHere} onWalkerMove={onWalkerMove} onChangeFloor={changeWalkerFloor} guidanceTarget={guidanceTarget} editor={editor.overlay} preview={editor.open ? null : mapView.previewObjects} /><div className="map-caption" role="status" data-editor={editor.open ? (editor.invalid ? 'invalid' : 'on') : undefined}>{editor.caption ? <strong>{editor.caption}</strong> : selection ? <><strong>{selection.name}</strong><span>{selection.floorName}</span>{selection.kind !== 'opening' && <button type="button" disabled={busy} onClick={() => void useLocation(selection.id)}>Use as my location</button>}</> : <><span className="legend-dot focus-dot" /> {hereId ? `Starting at ${placeName(hereId)}` : copy.destinationFocus}</>}</div></div>{stackOpen && <Suspense fallback={<p role="status">Loading 3D view…</p>}><FloorStack3D plans={stackPlans} route={route} activeFloorId={floor.id} onSelectFloor={(id) => { setFloorId(id); setFloorPinned(true) }} onSelect={selectOnMap} selectedId={selection?.id ?? null} /></Suspense>}<PlanImport onApply={(imported) => { const id = `imported:${imported.floor.id}`; setImportedPlans((current) => new Map(current).set(id, imported)); setBuildings((current) => current.some((item) => item.id === id) ? current : [...current, { id, name: `${copy.importedSession}: ${imported.floor.name}`, floors: 1, has_lift: imported.connectors.some((item) => item.kind === 'lift'), has_step_free_entrance: imported.openings.some((item) => item.kind === 'entrance' && item.step_free) }]); setBuildingId(id) }} /><p className="revision-note"><span className="eyebrow">{copy.revision}</span><span className="mono">{revision}</span></p></div>
      <div className="guide-region">
        {editor.open ? <EditorPanel editor={editor} /> : <>
        {mapFocusActive && <div className="panel-tabs" role="tablist" aria-label="Guide views">
          <button type="button" role="tab" aria-selected={activePanel === 'guide'} className={activePanel === 'guide' ? 'active' : undefined} onClick={() => { setActivePanel('guide') }}>Your Guide</button>
          {debugEnabled && <button type="button" role="tab" aria-selected={activePanel === 'debug'} className={activePanel === 'debug' ? 'active' : undefined} onClick={() => { setActivePanel('debug') }}>Debug</button>}
        </div>}
        {!mapFocusActive || activePanel === 'guide' ? <GuidePanel query={query} messages={messages} busy={busy} ready={ready} activeRoute={route} activeMessageId={activeMessageId} pendingActionId={pendingAction?.id ?? null} directionIndex={directionIndex} onQuery={setQuery} onSubmit={submit} onChoose={(option, role) => { void choose(option, role) }} onRetry={(message) => { void sendText(message.text, {}, message) }} onConfirm={() => { void finishAction(true) }} onCancel={() => { void finishAction(false) }} onShowMap={() => mapRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} onShowFloor={(id) => { setFloorId(id); setFloorPinned(true) }} inputMode={inputMode} onInputMode={setInputMode} voice={voice} guidanceActive={guidanceActive} onStopGuidance={() => { void stopGuidance() }} inputRef={inputRef} floors={floors} /> : <DebugPanel selection={selection} presentation={mapView} effects={latestReply?.effects ?? []} facts={plan && selection ? selectionFacts(plan, selection) : null} markerArmed={markerArmed} onArmMarker={() => setMarkerArmed((armed) => !armed)} onLoad={preview} onLeavePreview={() => { setActivePanel('guide'); setReload((value) => value + 1) }} />}
        </>}
      </div>
    </section>
    <p className="sr-only" role="status" aria-live="polite"><span key={editor.announcement.id}>{editor.announcement.text}</span></p>
    <footer className="next-bar"><div><span className="eyebrow">{copy.nextStep}</span><strong>{busy ? copy.working : guidanceActive && feed.latestInstruction ? feed.latestInstruction.text : checkpointNote ?? nextText}</strong></div>{guidanceActive ? <button type="button" className="next-distance" onClick={() => { void stopGuidance() }}>{copy.stopGuidance}</button> : route?.reachable && sessionId && <button type="button" className="next-distance" onClick={() => { void guideMe() }}>{copy.guideMe}</button>}<button type="button" className="next-distance" onClick={() => setPlaying((value) => !value)} disabled={!route?.reachable} aria-pressed={playing}>{playing ? copy.pause : copy.play}</button><button type="button" className="next-distance" onClick={advance} disabled={!route?.reachable}>{route?.reachable ? `${formatMetres(route.length_m)} ->` : `${copy.noRoute} ->`}</button>{route && <button type="button" className="next-distance" aria-label="Hide route" onClick={() => { setMapView((current) => ({ ...current, route: null })); setPlaying(false) }}>×</button>}</footer>
    {locationOpen && <div className="drawer-backdrop" onClick={(event) => { if (event.target === event.currentTarget) setLocationOpen(false) }}>
      <aside ref={drawerRef} className="navigation-drawer" role="dialog" aria-modal="true" aria-label="Choose your starting location" onKeyDown={(event) => {
        if (event.key === 'Escape') setLocationOpen(false)
        if (event.key === 'Tab') { const items = [...(drawerRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, [tabindex="0"]') ?? [])].filter((item) => item.offsetParent !== null); const first = items[0]; const last = items.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() } }
      }}><header><h2>Where are you starting?</h2><button type="button" aria-label="Close search" onClick={() => setLocationOpen(false)}>×</button></header>
        <p>Pick the room you are in.</p><input aria-label="Search starting rooms" placeholder="Room name or number" value={locationFilter} onChange={(event) => setLocationFilter(event.target.value)} /><select aria-label="Starting floor" value={locationFloor} onChange={(event) => setLocationFloor(event.target.value)}><option value="">All floors</option>{floors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><ul className="location-results">{locationSpaces.map((space) => <li key={space.id}><button type="button" disabled={busy} onClick={() => { void useLocation(space.id) }}><strong>{space.name}</strong><span>{floors.find((item) => item.id === space.floor_id)?.name}</span></button></li>)}</ul>{locationSpaces.length === 0 && <p>No rooms match. Try another name or floor.</p>}
      </aside>
    </div>}
  </main>
}
