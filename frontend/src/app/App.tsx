import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { toUiError } from '../api/errors'
import type { UiError } from '../api/errors'
import { catalog } from '../api/fixtures'
import { gateway } from '../api/gateway'
import type { BuildingSummary, InputMode, Session } from '../api/gateway'
import { clearRecovery, readRecovery, writeRecovery } from '../api/recovery'
import { choiceMessage, choiceRole, optionName, placeById, withStartOptions } from '../domain/clarify'
import { closureHighlights, distance, labelFromPlans, pendingReply, selectionFacts } from '../domain/live'
import type { DiscoveryPlace } from '../domain/discovery'
import { editedFloors } from '../domain/editor'
import { markersOnFloor } from '../domain/emergency'
import { buildPresentation, formatMetres } from '../domain/presentation'
import type { Decision } from '../domain/presentation'
import type { AskOption, ClientContext, FloorPlan, FloorSummary, GuidanceEvent, Point, Reply, ReplyId, Route, Selection, ViewEffect } from '../domain/types'
import { DebugPanel } from '../features/debug/DebugPanel'
import { EmergencyAdminPanel } from '../features/emergency/EmergencyAdminPanel'
import { EmergencyBanner } from '../features/emergency/EmergencyBanner'
import { useAdminToken, useEmergencyRoster, useEmergencyStatus } from '../features/emergency/useEmergency'
import { PlaceDiscovery } from '../features/discovery/PlaceDiscovery'
import { GuidePanel } from '../features/guide/GuidePanel'
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
type MessageJob = { text: string; destination: string | null; sessionId: string; mode: InputMode; signal?: AbortSignal; onStart?: () => void }

const themeModes: ThemeMode[] = ['system', 'light', 'dark']

function initialThemeMode(): ThemeMode {
  const stored = window.localStorage.getItem('talk-building-theme')
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

export function App() {
  const inputRef = useRef<HTMLInputElement>(null)
  const editButtonRef = useRef<HTMLButtonElement>(null)
  const announcedPoint = useRef<Point | null>(null)
  const sessionRef = useRef('')
  const messageTailRef = useRef<Promise<unknown>>(Promise.resolve())
  const executeMessageRef = useRef<(job: MessageJob) => Promise<Reply | null>>(async () => null)
  const walkerRef = useRef<Walker | null>(null)
  const jumpSeqRef = useRef(0)
  const viewedFloorRef = useRef('')
  const [query, setQuery] = useState('')
  const [replyId, setReplyId] = useState<ReplyId | 'miss'>('accepted')
  const [liveReply, setLiveReply] = useState<Reply | null>(null)
  const [decision, setDecision] = useState<Decision | null>(null)
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
  const [missed, setMissed] = useState(false)
  const [sessionId, setSessionId] = useState('')
  const [buildings, setBuildings] = useState<BuildingSummary[]>([])
  const [buildingId, setBuildingId] = useState(() => window.localStorage.getItem('wayfinder-building') ?? 'proc-factory-dev-003')
  const [loading, setLoading] = useState(false)
  const [queuedMessages, setQueuedMessages] = useState(0)
  const [loadError, setLoadError] = useState<UiError | null>(null)
  const [booting, setBooting] = useState(true)
  const [revision, setRevision] = useState(1)
  const [objectRevision, setObjectRevision] = useState(0)
  const objectRevisionRef = useRef(0)
  const plansRef = useRef(plans)
  plansRef.current = plans
  const invalidateObjectsRef = useRef<() => void>(() => undefined)
  const [inputMode, setInputMode] = useState<InputMode>('text')
  const [stackOpen, setStackOpen] = useState(true)
  const [themeMode, setThemeMode] = useState<ThemeMode>(initialThemeMode)
  const [stepFree, setStepFree] = useState(() => window.localStorage.getItem('wayfinder-step-free') === 'true')
  const [routingId, setRoutingId] = useState<string | null>(null)
  const [hereId, setHereId] = useState<string | null>(null)
  const [appliedClosed, setAppliedClosed] = useState<string[] | null>(null)
  // Destination picked from a guide question while the start was still unknown.
  const [pendingDestination, setPendingDestination] = useState<string | null>(null)
  const [sampleId, setSampleId] = useState<ReplyId | null>(null)
  const [confirmedEffects, setConfirmedEffects] = useState<ViewEffect[]>([])
  // Summary of a confirmed map edit; null for closures, which keep their own text.
  const [confirmedNote, setConfirmedNote] = useState<string | null>(null)
  const [markerArmed, setMarkerArmed] = useState(false)
  const [mockPoint, setMockPoint] = useState<Point | null>(null)
  const [checkpointNote, setCheckpointNote] = useState<string | null>(null)
  const [importedPlans, setImportedPlans] = useState<Map<string, FloorPlan>>(new Map())
  const debugEnabled = import.meta.env.DEV
  const [emergencyOpen, setEmergencyOpen] = useState(false)
  const [emergencyStatus, setEmergencyStatus] = useEmergencyStatus(buildingId)
  const emergencyActive = Boolean(emergencyStatus?.active)
  const emergencyActiveRef = useRef(false)
  emergencyActiveRef.current = emergencyActive
  const [admin, setAdmin] = useAdminToken()
  const emergency = useEmergencyRoster(buildingId, admin?.token ?? null, emergencyActive, () => setAdmin(null))

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
    setBooting(true)
    window.localStorage.setItem('wayfinder-building', buildingId)
    setSessionId('')
    objectRevisionRef.current = 0
    setObjectRevision(0)
    setWalkerFloorId(null)
    walkerRef.current = null
    setHereId(null)
    setPendingDestination(null)
    setLiveReply(null)
    setSelection(null)
    setReplyId('miss')
    setPlans(new Map())
    setFloors([])
    setLoadError(null)
    const openSession = async (): Promise<Session> => {
      const imported = importedPlans.get(buildingId)
      if (imported) {
        return {
          id: `local-${buildingId}`,
          building_id: buildingId,
          building_name: imported.floor.name,
          revision: 1,
          preferences: { step_free: stepFree },
          closed_ids: imported.closed_ids,
          last_route_id: null,
          pending_action_id: null,
        }
      }
      const items = await gateway.listBuildings().catch(() => [])
      if (!cancelled && items.length) setBuildings((current) => [...items, ...current.filter((item) => item.id.startsWith('imported:') && !items.some((next) => next.id === item.id))])
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
      const imported = importedPlans.get(buildingId)
      if (imported) {
        if (cancelled) return
        setSessionId(session.id)
        setRevision(1)
        setFloors([imported.floor])
        setPlans(new Map([[imported.floor.id, imported]]))
        setFloorId(imported.floor.id)
        setBooting(false)
        return
      }
      const nextFloors = await gateway.listFloors(session.id)
      const nextPlans = await Promise.all(nextFloors.map(async (floor) => [floor.id, await gateway.getFloorPlan(session.id, floor.id)] as const))
      if (cancelled) return
      setSessionId(session.id)
      setRevision(session.revision)
      objectRevisionRef.current = session.object_revision ?? 0
      setObjectRevision(session.object_revision ?? 0)
      setStepFree(session.preferences.step_free)
      setFloors(nextFloors)
      setPlans(new Map(nextPlans))
      setFloorId(nextFloors.find((floor) => floor.level === 0)?.id ?? nextFloors[0]?.id ?? '')
      writeRecovery({ id: session.id, buildingId: session.building_id, revision: session.revision, stepFree: session.preferences.step_free, lastRouteId: session.last_route_id ?? null, pendingActionId: session.pending_action_id ?? null })
      if (session.pending_action_id && !session.id.startsWith('local-')) {
        try {
          const action = await gateway.getAction(session.id, session.pending_action_id)
          if (cancelled) return
          if (action.status === 'pending') {
            // Editor proposals bring their own ghosts; closures highlight the affected rooms.
            const highlights = action.preview_effects.some((effect) => effect.type === 'preview_objects')
              ? action.preview_effects
              : closureHighlights(nextPlans.map(([, plan]) => plan), action.proposal?.element_ref)
            setLiveReply(pendingReply(action, highlights))
            setReplyId('pending')
            setDecision('pending')
          } else {
            setLoadError({ message: 'Action is no longer pending.', code: '30009_action_expired', traceId: null, requestId: null })
          }
        } catch (error: unknown) {
          if (!cancelled) setLoadError(toUiError(error))
        }
      }
      // A persisted route is not shown until the user chooses a start point.
    }).catch((error: unknown) => {
      if (!cancelled) {
        const ui = toUiError(error)
        if (ui.code === '30001_building_not_found') ui.message = copy.otherBuilding
        setLoadError(ui)
      }
    }).finally(() => { if (!cancelled) setBooting(false) })
    return () => { cancelled = true }
  }, [buildingId, importedPlans])

  sessionRef.current = sessionId

  useEffect(() => {
    // A slow request from an old building must not hold up the new session.
    messageTailRef.current = Promise.resolve()
    setQueuedMessages(0)
    setLoading(false)
  }, [sessionId])

  const openFreshSession = async (): Promise<string> => {
    clearRecovery()
    const created = await gateway.createSession(buildingId)
    const stored = window.localStorage.getItem('wayfinder-step-free')
    const wanted = stored === 'true' || stored === 'false' ? stored === 'true' : created.preferences.step_free
    const session = wanted === created.preferences.step_free ? created : await gateway.updatePreferences(created.id, { step_free: wanted })
    setSessionId(session.id)
    setRevision(session.revision)
    objectRevisionRef.current = session.object_revision ?? 0
    setObjectRevision(session.object_revision ?? 0)
    setStepFree(session.preferences.step_free)
    sessionRef.current = session.id
    writeRecovery({ id: session.id, buildingId: session.building_id, revision: session.revision, stepFree: session.preferences.step_free, lastRouteId: session.last_route_id ?? null, pendingActionId: session.pending_action_id ?? null })
    return session.id
  }

  const withLiveSession = async <T,>(run: (id: string) => Promise<T>): Promise<T> => {
    const current = sessionRef.current
    if (!current) return run(await openFreshSession())
    try {
      return await run(current)
    } catch (error: unknown) {
      if (toUiError(error).code !== '30002_session_not_found') throw error
      return run(await openFreshSession())
    }
  }

  const reply = sampleId ? catalog.replies[sampleId] : replyId === 'miss' ? null : liveReply
  const presentation = useMemo(() => {
    if (!reply) return { ...emptyPresentation, alert: missed ? { tone: 'amber' as const, text: copy.missTitle } : null, guideText: missed ? copy.missBody : '' }
    return buildPresentation({ guideText: reply.guideText, understood: reply.understood, effects: reply.effects, routes: reply.routes, pendingSummary: reply.pending?.summary ?? null, decision, confirmedEffects, confirmedClosedIds: appliedClosed ?? [], confirmedText: confirmedNote ?? catalog.confirmedText, confirmedTone: confirmedNote ? 'green' : 'red', cancelledText: copy.cancelled })
  }, [reply, decision, missed, appliedClosed, confirmedNote])

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
  viewedFloorRef.current = floor.id
  const walkerHere = walkerFloorId === null || walkerFloorId === floor.id
  usePositionSync(sessionId, () => {
    const walker = walkerRef.current
    // During an alarm every phone reports, whichever floor is on screen.
    return walker && (emergencyActiveRef.current || walker.floorId === viewedFloorRef.current) ? walker : null
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
    gateway.getRoute(sessionId, guidedRouteId).then((route) => { if (!cancelled) setGuidedRoute(route) }, (error: unknown) => { if (!cancelled) setLoadError(toUiError(error)) })
    return () => { cancelled = true }
  }, [sessionId, guidedRouteId])
  const mapRoute = presentation.route ?? (guidedRouteId && guidedRoute?.id === guidedRouteId ? guidedRoute : null)
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
    const route = presentation.route
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
    const id = sessionRef.current || sessionId
    if (!id || id.startsWith('local-')) return new Map()
    for (let attempt = 0; attempt < 2; attempt++) {
      const session = await gateway.getSession(id)
      const changed = (session.object_revision ?? 0) !== objectRevisionRef.current
      const unique = [...new Set(changed ? [...plansRef.current.keys(), ...floorIds] : floorIds)]
      const entries = await Promise.all(unique.map(async (item) => [item, await gateway.getFloorPlan(id, item)] as const))
      const latest = await gateway.getSession(id)
      if (id !== sessionRef.current) return new Map()
      if (latest.object_revision !== session.object_revision) continue
      setRevision(latest.revision)
      if (changed) invalidateObjectsRef.current()
      objectRevisionRef.current = session.object_revision ?? 0
      setObjectRevision(session.object_revision ?? 0)
      setPlans((current) => { const next = new Map(current); for (const [item, nextPlan] of entries) next.set(item, nextPlan); return next })
      return new Map(entries)
    }
    throw new Error(copy.sharedObjectsChanged)
  }

  const editor = useObjectEditor({ sessionId, objectRevision, plans, floors, floorId: floor.id, selection, onSelect: setSelection, refreshFloors, buttonRef: editButtonRef })

  // A click on the flat plan or the 3D stack; the 3D stack can pick items on other floors. Items open in the editor.
  const selectOnMap = (next: Selection) => {
    setSelection(next)
    if (next.floorId !== floor.id) { setFloorId(next.floorId); setFloorPinned(true) }
    if (next.kind === 'asset') editor.editItem(next)
  }

  const clientContext = (): ClientContext | undefined => {
    if (!floors.some((item) => item.id === floor.id)) return undefined
    if (selection?.kind === 'space') return { floor_level: floor.level, selected_space_id: selection.id }
    if (selection) return { floor_level: floor.level, selected_object_id: selection.id }
    return { floor_level: floor.level }
  }
  const step = presentation.route?.directions[directionIndex]
  const nextText = !presentation.route ? copy.askRoute : presentation.route.reachable ? (step?.text ?? copy.askRoute) : copy.noRoute
  const visibleEffects = decision === 'confirmed' ? confirmedEffects : decision === 'cancelled' || !reply ? [] : reply.effects

  const loadReply = (id: ReplyId) => {
    const next = catalog.replies[id]
    setSampleId(id)
    setDecision(id === 'pending' ? 'pending' : null)
    setMissed(false)
    setDirectionIndex(0)
    setFloorPinned(false)
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

  const routeToPlace = async (place: DiscoveryPlace, knownStart?: string) => {
    const liveSessionId = sessionRef.current || sessionId
    if (!liveSessionId || (loading && !knownStart)) return
    if (liveSessionId.startsWith('local-')) {
      setLoadError({ message: copy.importedNoRoute, code: null, traceId: null, requestId: null })
      return
    }
    const start = knownStart ?? hereId ?? (selection?.kind === 'space' ? selection.id : null)
    if (!start) {
      setPendingDestination(place.id)
      setSampleId(null)
      setLiveReply(withStartOptions({
        id: 'clarify',
        userText: null,
        guideText: copy.askStartBody,
        understood: {
          intent: 'clarify',
          summary: copy.askStart,
          constraints: { step_free: stepFree, via: [], closed_ids: [] },
          resolved: { start_space_id: null, destination_space_id: place.id, space_ids: [place.id], asset_ids: place.kind === 'asset' ? [place.id] : [], count: null },
          missing: ['start'],
        },
        effects: [{ type: 'ask', question: copy.askStart, options: [] }],
        routes: [],
        pending: null,
      }, [...plans.values()]))
      setReplyId('clarify')
      setDecision(null)
      return
    }
    setRoutingId(place.id)
    setLoading(true)
    setLoadError(null)
    try {
      const route = await gateway.createRoute(liveSessionId, { start_space_id: start, destination_space_id: place.id, step_free: stepFree })
      if (sessionRef.current !== liveSessionId) return
      setLiveReply({
        id: route.reachable ? 'accepted' : 'unreachable',
        userText: null,
        guideText: route.reachable ? `Route is ${formatMetres(route.length_m)}. Follow the tape on the plan.` : 'No route to that place with the current preference.',
        understood: {
          intent: 'route',
          summary: `${placeName(start)} to ${place.name}`,
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

  const placeName = (id: string | null) => labelFromPlans([...plans.values()], id)

  executeMessageRef.current = async (job: MessageJob): Promise<Reply | null> => {
    const { text, destination, sessionId: originalSession, mode, signal, onStart } = job
    const valid = () => originalSession === sessionRef.current && !signal?.aborted
    if (!valid()) return null
    onStart?.()
    let sent: Reply | null = null
    setSampleId(null)
    setLoading(true); setLoadError(null); setMissed(false)
    let routeFrom: string | null = null
    try {
      const context = clientContext()
      // Let an already-dispatched model turn finish before the next same-session turn.
      // Aborting fetch cannot cancel the server's tool work; ignore its UI result instead.
      const next = withStartOptions(await gateway.sendMessage(originalSession, text, mode, context), [...plans.values()])
      if (!valid()) return null
      sent = next
      setLiveReply(next); setReplyId(next.id); setDecision(next.pending ? 'pending' : null); setDirectionIndex(0); setFloorPinned(false)
      // A stated location becomes UI context only after the main agent resolves it.
      const resolved = next.understood?.resolved
      const locationConfirmed = /^\s*i am (?:now )?at\b/i.test(text)
        && next.understood?.intent === 'locate' && next.understood.missing.length === 0
        && !next.effects.some((effect) => effect.type === 'ask')
      const start = locationConfirmed && resolved?.space_ids.length === 1 ? resolved.space_ids[0] : null
      if (start) {
        setHereId(start)
        if (destination) routeFrom = start
      }
      // Keep the picked destination only while the guide still waits for a start.
      if (!next.understood?.missing.includes('start')) setPendingDestination(null)
      if (next.understood && next.understood.constraints.step_free !== stepFree) {
        setStepFree(next.understood.constraints.step_free)
        window.localStorage.setItem('wayfinder-step-free', String(next.understood.constraints.step_free))
      }
    } catch (error: unknown) {
      if (valid()) {
        setLoadError(toUiError(error))
        if (toUiError(error).code === '30002_session_not_found') await openFreshSession()
      }
    } finally { if (originalSession === sessionRef.current) setLoading(false) }
    // The guide only records the start. Finish the route that was asked for.
    const place = routeFrom && destination ? placeById([...plans.values()], floors, destination) : null
    if (valid() && routeFrom && place) await routeToPlace(place, routeFrom)
    return sent
  }

  const sendText = (text: string, destination: string | null = pendingDestination,
    options: { signal?: AbortSignal; onStart?: () => void } = {}): Promise<Reply | null> => {
    if (!text.trim()) return Promise.resolve(null)
    const originalSession = sessionRef.current
    if (!originalSession || originalSession.startsWith('local-')) {
      setLoadError({ message: copy.voiceSessionRequired, code: null, traceId: null, requestId: null })
      return Promise.resolve(null)
    }
    const job = { text, destination, sessionId: originalSession, mode: inputMode, ...options }
    setQueuedMessages((count) => count + 1)
    const result = messageTailRef.current.then(() => executeMessageRef.current(job))
    messageTailRef.current = result.catch(() => undefined)
    return result.finally(() => {
      if (sessionRef.current === originalSession) setQueuedMessages((count) => Math.max(0, count - 1))
    })
  }

  const voice = useVoice({ active: inputMode === 'voice' && Boolean(sessionId) && !sessionId.startsWith('local-'), sessionId,
    busy: loading || queuedMessages > 0, send: (text, signal, onStart) => sendText(text, pendingDestination, { signal, onStart }) })
  speakRef.current = voice.speakGuidance


  invalidateObjectsRef.current = () => {
    voice.interruptPlayback()
    setPlaying(false)
    setGuidedRoute(null)
    setConfirmedEffects([])
    setConfirmedNote(null)
    setSampleId(null)
    setLiveReply((current) => current ? { ...current, effects: [], routes: [], pending: null } : current)
    setDecision(null)
    setDirectionIndex(0)
    feed.refresh()
  }

  const pollObjectsRef = useRef<(id: string, valid: () => boolean) => Promise<void>>(async () => undefined)
  pollObjectsRef.current = async (id, valid) => {
    const session = await gateway.getSession(id)
    if (!valid() || (session.object_revision ?? 0) === objectRevisionRef.current) return
    const entries = await Promise.all([...plansRef.current.keys()].map(async (floorId) => [floorId, await gateway.getFloorPlan(id, floorId)] as const))
    // A second edit during the floor fetch is retried on the next tick; never mix revisions.
    const latest = await gateway.getSession(id)
    if (!valid() || latest.object_revision !== session.object_revision) return
    invalidateObjectsRef.current()
    objectRevisionRef.current = session.object_revision ?? 0
    setObjectRevision(session.object_revision ?? 0)
    setRevision(session.revision)
    setPlans(new Map(entries))
    setSelection((current) => current?.kind === 'asset' && !entries.some(([, plan]) => plan.assets.some((asset) => asset.id === current.id)) ? null : current)
  }

  useEffect(() => {
    if (!sessionId || sessionId.startsWith('local-')) return
    let cancelled = false
    let polling = false
    const valid = () => !cancelled && sessionRef.current === sessionId
    const poll = async () => {
      if (document.hidden || polling || !valid()) return
      polling = true
      try { await pollObjectsRef.current(sessionId, valid) }
      catch (error: unknown) { if (valid()) setLoadError(toUiError(error)) }
      finally { polling = false }
    }
    const timer = window.setInterval(() => { void poll() }, 2000)
    document.addEventListener('visibilitychange', poll)
    void poll()
    return () => { cancelled = true; window.clearInterval(timer); document.removeEventListener('visibilitychange', poll) }
  }, [sessionId])

  const changeInputMode = (mode: InputMode) => {
    if (mode === 'voice') {
      if (!sessionId || sessionId.startsWith('local-')) {
        setLoadError({ message: copy.voiceSessionRequired, code: null, traceId: null, requestId: null })
        return
      }
      voice.enable()
    }
    setInputMode(mode)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    await sendText(query)
  }

  // A picked option becomes a sentence the guide understands. Known start: route at once.
  const chooseOption = async (option: AskOption) => {
    if (loading) return
    const name = optionName(option.label)
    const placeId = option.place_id ?? option.id
    const role = choiceRole(reply)
    if (role === 'destination') {
      const start = hereId
      const place = placeById([...plans.values()], floors, placeId)
      if (start && place) {
        setQuery(choiceMessage(role, name))
        setPendingDestination(null)
        await routeToPlace(place, start)
        return
      }
      setPendingDestination(placeId)
    }
    const text = choiceMessage(role, name)
    setQuery(text)
    await sendText(text, role === 'destination' ? placeId : pendingDestination)
  }

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
        const directions = presentation.route?.directions ?? []
        if (!presentation.route?.reachable || directions.length === 0) return index
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
  }, [playing, presentation.route])

  const advance = () => {
    const directions = presentation.route?.directions ?? []
    if (!presentation.route?.reachable || directions.length === 0) return
    const nextIndex = (directionIndex + 1) % directions.length
    setDirectionIndex(nextIndex)
    if (directions[nextIndex]?.floor_id) { setFloorId(directions[nextIndex].floor_id); setFloorPinned(true) }
  }

  // Confirms any pending guide action: closures, doors, and object edits.
  const confirm = async () => {
    if (!sessionId || !reply?.pending) return
    setLoading(true); setLoadError(null)
    try {
      const elementId = reply.pending.proposal.element_ref
      const action = await gateway.confirmAction(sessionId, reply.pending.id)
      const edit = editedFloors(action)
      if (!sessionId.startsWith('local-')) await refreshFloors(edit?.floorIds.length ? edit.floorIds : [floor.id])
      if (edit) {
        setConfirmedEffects([])
        setAppliedClosed(null)
        setConfirmedNote(edit.summary ?? action.summary)
      } else {
        setConfirmedEffects(closureHighlights([...plans.values()], elementId))
        setAppliedClosed(action.closed_ids)
        setConfirmedNote(null)
      }
      setDecision('confirmed')
      writeRecovery({ id: sessionId, buildingId, revision, stepFree, lastRouteId: null, pendingActionId: null })
    } catch (error: unknown) { setLoadError(toUiError(error)) } finally { setLoading(false) }
  }
  const cancel = async () => {
    if (!sessionId || !reply?.pending) return
    setLoading(true); setLoadError(null)
    try { await gateway.cancelAction(sessionId, reply.pending.id); setDecision('cancelled') } catch (error: unknown) { setLoadError(toUiError(error)) } finally { setLoading(false) }
  }

  return <main className="app-shell" data-scenario={replyId} data-decision={decision ?? 'none'}>
    <header className="topbar"><div className="brand"><span className="brand-mark" aria-hidden="true">W</span><span>{copy.title}</span></div><div className="building-meta"><span className="eyebrow">{copy.buildingEyebrow}</span><select className="building-picker" value={buildingId} onChange={(event) => setBuildingId(event.target.value)} aria-label="Choose building">{(buildings.length ? buildings : [{ id: buildingId, name: catalog.buildingName } as BuildingSummary]).map((building) => <option key={building.id} value={building.id}>{building.name}</option>)}</select><span className="status-pill"><span />{sessionId ? 'API connected' : 'API disconnected'}</span><button type="button" className="emergency-toggle" aria-pressed={emergencyOpen} data-active={emergencyActive} title={copy.emergency.toggleHint} onClick={() => setEmergencyOpen((open) => !open)}>{copy.emergency.toggle}</button><div className="theme-switcher" role="group" aria-label="Theme"><span className="sr-only">Theme</span>{themeModes.map((mode) => <button key={mode} type="button" className={themeMode === mode ? 'active' : undefined} aria-pressed={themeMode === mode} onClick={() => setThemeMode(mode)}>{mode === 'system' ? 'Auto' : mode === 'light' ? 'Light' : 'Dark'}</button>)}</div></div></header>
    {booting && <p className="app-status" role="status">{copy.loadingPlan}</p>}
    {loadError && <div className="app-alert" role="alert"><strong>{loadError.code ?? copy.apiUnavailable}</strong><span>{loadError.message}</span>{loadError.traceId && <span>trace {loadError.traceId}</span>}{loadError.requestId && <span>request {loadError.requestId}</span>}</div>}
    {emergencyActive && emergencyStatus && <EmergencyBanner status={emergencyStatus} sessionId={sessionId} />}
    <PlaceDiscovery plans={[...plans.values()]} floors={floors} stepFree={stepFree} busyId={routingId} onToggleStepFree={toggleStepFree} onFocus={focusDiscoveryPlace} onRoute={routeToPlace} />
    <section className="workspace"><div className="map-column"><div className="map-toolbar"><div><span className="eyebrow">{copy.planEyebrow}</span><h1>{floor.name}</h1></div><div className="map-toolbar-actions"><button type="button" ref={editButtonRef} className="edit-map-toggle" aria-pressed={editor.open} aria-keyshortcuts="E" title={copy.editor.openHint} onClick={editor.toggle}><svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18"><path d="M4 20h4L19 9l-4-4L4 16v4Z M13.5 6.5l4 4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg><span>{editor.open ? copy.editor.done : copy.editor.open}</span></button><div className="floor-rail" role="toolbar" aria-label="Floors">{floors.map((item) => <button type="button" key={item.id} className={item.id === floor.id ? 'active' : undefined} aria-pressed={item.id === floor.id} aria-label={`${copy.showFloor} ${item.name}`} onClick={() => { setFloorId(item.id); setFloorPinned(true) }}>{item.level}</button>)}<button type="button" className="floor-rail-toggle" aria-pressed={stackOpen} onClick={() => setStackOpen((open) => !open)}>{stackOpen ? copy.flatPlan : copy.stackFloors}</button>{debugEnabled && <button type="button" aria-pressed={activePanel === 'debug' && mapFocusActive} onClick={() => { setMapFocusActive(true); setActivePanel('debug') }}>{copy.debug}</button>}</div></div></div><div className="plan-stage"><PlanCanvas plan={plan} floorName={floor.name} route={mapRoute} spaceReasons={presentation.spaceReasons} assetIds={presentation.assetIds} closedIds={presentation.closedIds} focusPoint={presentation.focusFloorId === floor.id ? presentation.focusPoint : null} stepPoint={step?.floor_id === floor.id ? step.at : null} storyIndex={directionIndex} selectionId={selection?.id ?? null} onSelect={selectOnMap} onFocusSelection={(focused) => { setMapFocusActive(Boolean(focused)); setActivePanel(debugEnabled && focused ? 'debug' : 'guide') }} mockPoint={mockPoint} markerArmed={markerArmed} stepFree={stepFree} onPlaceMarker={(point) => { setMockPoint(point); setMarkerArmed(false); const near = plan?.spaces.find((space) => space.polygon.length > 0 && Math.hypot(point[0] - space.polygon[0][0], point[1] - space.polygon[0][1]) < 8); if (near) void sendText(`I am at ${near.name}`) }} walkerHere={walkerHere} onWalkerMove={onWalkerMove} onChangeFloor={changeWalkerFloor} guidanceTarget={guidanceTarget} editor={editor.overlay} preview={editor.open ? null : presentation.previewObjects} people={emergencyOpen && emergency.roster ? markersOnFloor(emergency.roster.people, floor.id) : undefined} /><div className="map-caption" role="status" data-editor={editor.open ? (editor.invalid ? 'invalid' : 'on') : undefined}>{editor.caption ? <strong>{editor.caption}</strong> : selection ? <><strong>{selection.name}</strong><span>{selection.floorName}</span></> : <><span className="legend-dot focus-dot" /> {copy.destinationFocus}</>}</div></div>{stackOpen && <Suspense fallback={<p role="status">Loading 3D view…</p>}><FloorStack3D plans={stackPlans} route={mapRoute} activeFloorId={floor.id} onSelectFloor={(id) => { setFloorId(id); setFloorPinned(true) }} onSelect={selectOnMap} selectedId={selection?.id ?? null} /></Suspense>}<PlanImport onApply={(imported) => { const id = `imported:${imported.floor.id}`; setImportedPlans((current) => new Map(current).set(id, imported)); setBuildings((current) => current.some((item) => item.id === id) ? current : [...current, { id, name: `${copy.importedSession}: ${imported.floor.name}`, floors: 1, has_lift: imported.connectors.some((item) => item.kind === 'lift'), has_step_free_entrance: imported.openings.some((item) => item.kind === 'entrance' && item.step_free) }]); setBuildingId(id) }} /><p className="revision-note"><span className="eyebrow">{copy.revision}</span><span className="mono">{revision}</span></p></div>
      <div className="guide-region">
        {emergencyOpen ? <EmergencyAdminPanel buildingId={buildingId} status={emergencyStatus} onStatus={setEmergencyStatus} admin={admin} onAdmin={setAdmin} roster={emergency.roster} onRoster={emergency.setRoster} rosterFailed={emergency.failed} /> : editor.open ? <EditorPanel editor={editor} /> : <>
        {mapFocusActive && <div className="panel-tabs" role="tablist" aria-label="Guide views">
          <button type="button" role="tab" aria-selected={activePanel === 'guide'} className={activePanel === 'guide' ? 'active' : undefined} onClick={() => { setActivePanel('guide') }}>Your Guide</button>
          {debugEnabled && <button type="button" role="tab" aria-selected={activePanel === 'debug'} className={activePanel === 'debug' ? 'active' : undefined} onClick={() => { setActivePanel('debug') }}>Debug</button>}
        </div>}
        {!mapFocusActive || activePanel === 'guide' ? <GuidePanel query={query} presentation={presentation} loading={loading} queuedMessages={queuedMessages} directionIndex={directionIndex} onQuery={setQuery} onSubmit={submit} onChoose={(option) => { void chooseOption(option) }} onConfirm={confirm} onCancel={cancel} onReplay={() => { setDirectionIndex(0); setPlaying(true) }} onAskText={(text) => { void sendText(text) }} onReopen={() => { const ids = appliedClosed ?? presentation.closedIds; const named = ids[0] ? placeName(ids[0]) : ''; void sendText(named && named !== ids[0] ? `Reopen ${named}` : ids[0] ? `Reopen ${ids[0]}` : copy.reopen) }} onShowFloor={(nextFloor) => { setFloorId(nextFloor); setFloorPinned(true) }} hereName={hereId ? placeName(hereId) : null} inputMode={inputMode} onInputMode={changeInputMode} voice={voice} guidanceActive={guidanceActive} onStopGuidance={() => { void stopGuidance() }} inputRef={inputRef} label={placeName} floors={floors} /> : <DebugPanel selection={selection} presentation={presentation} effects={visibleEffects} facts={plan && selection ? selectionFacts(plan, selection) : null} markerArmed={markerArmed} onArmMarker={() => setMarkerArmed((armed) => !armed)} onLoad={loadReply} onLeavePreview={() => setSampleId(null)} />}
        </>}
      </div>
    </section>
    <p className="sr-only" role="status" aria-live="polite"><span key={editor.announcement.id}>{editor.announcement.text}</span></p>
    <footer className="next-bar"><div><span className="eyebrow">{copy.nextStep}</span><strong>{loading ? copy.working : guidanceActive && feed.latestInstruction ? feed.latestInstruction.text : checkpointNote ?? nextText}</strong></div>{guidanceActive ? <button type="button" className="next-distance" onClick={() => { void stopGuidance() }}>{copy.stopGuidance}</button> : presentation.route?.reachable && !sessionId.startsWith('local-') && <button type="button" className="next-distance" onClick={() => { void guideMe() }}>{copy.guideMe}</button>}<button type="button" className="next-distance" onClick={() => setPlaying((value) => !value)} disabled={!presentation.route?.reachable} aria-pressed={playing}>{playing ? copy.pause : copy.play}</button><button type="button" className="next-distance" onClick={advance} disabled={!presentation.route?.reachable}>{presentation.route?.reachable ? `${formatMetres(presentation.route.length_m)} ->` : `${copy.noRoute} ->`}</button></footer>
  </main>
}
