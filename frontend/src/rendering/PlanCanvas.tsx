import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { Asset, FloorPlan, Opening, Point, Route, Selection } from '../domain/types'
import type { Connector } from '../domain/types'
import { interiorPoint, spaceAt } from '../domain/editor'
import { openingAccessNote, spaceAccessNote } from '../domain/route-compare'
import { connectorNoteFromPlan, escapeSpaceIds, landmarkIds, wayfindingRole } from '../domain/live'
import type { PreviewObjects } from '../domain/presentation'
import { MapTooltip, assetTip, spaceTip } from './MapTooltip'
import { WalkPad } from './WalkPad'

export type GhostAsset = { asset: Asset; layer: number }

/** What the map editor draws and listens for. Built by `useObjectEditor`. */
export type EditorOverlay = {
  /** place: ghost follows the pointer; wall: click a shared wall; rooms: click rooms; form/pick: normal map. */
  mode: 'pick' | 'place' | 'wall' | 'rooms' | 'form'
  /** Draft object first, then everything that moves with it. */
  ghosts: GhostAsset[]
  ghostOpening: Opening | null
  /** Footprint that follows the pointer in place mode. */
  cursor: { width: number; depth: number; rotation: number; category: string } | null
  /** Originals drawn faded while their ghosts sit elsewhere. */
  fadedIds: string[]
  pickedSpaceIds: string[]
  invalid: boolean
  draggable: boolean
  constrain: (point: Point) => Point
  onPoint: (point: Point) => void
  onPickSpace: (spaceId: string) => void
  onDragEnd: (point: Point) => void
}

type PlanCanvasProps = {
  plan: FloorPlan | null
  floorName: string
  /** Shown instead of the plan while it is missing, e.g. during loading. */
  emptyText?: string
  route: Route | null
  previousRoute?: Route | null
  /** Second tape from profile=synera-industrial. The walking route stays the one being followed. */
  forkliftRoute?: Route | null
  /** Door and bay notes that explain why the forklift tape differs. */
  forkliftCompare?: boolean
  spaceReasons: Map<string, string>
  assetIds: Set<string>
  closedIds: string[]
  focusPoint: Point | null
  stepPoint: Point | null
  /** Index of the direction told by the step player; the route up to it is highlighted. */
  storyIndex: number
  selectionId: string | null
  onSelect: (selection: Selection) => void
  onFocusSelection: (selection: Selection | null) => void
  mockPoint?: Point | null
  markerArmed?: boolean
  onPlaceMarker?: (point: Point) => void
  stepFree?: boolean
  walkerHere?: boolean
  onWalkerMove?: (floorId: string, point: Point, source: 'walk' | 'jump') => void
  onChangeFloor?: (floorId: string) => void
  guidanceTarget?: Point | null
  editor?: EditorOverlay | null
  /** Ghosts for a guide proposal that waits for confirmation. */
  preview?: PreviewObjects | null
}

function polygonArea(polygon: Point[]): number {
  let sum = 0
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index]
    const [x2, y2] = polygon[(index + 1) % polygon.length]
    sum += x1 * y2 - x2 * y1
  }
  return Math.abs(sum) / 2
}

function centroid(polygon: Point[]): Point {
  const total = polygon.reduce(([x, y], [px, py]) => [x + px, y + py], [0, 0])
  return [total[0] / polygon.length, total[1] / polygon.length]
}

function prefixTo(points: Point[], target: Point | null): Point[] {
  if (!target || points.length < 2) return points
  let best = 0
  let bestDistance = Number.POSITIVE_INFINITY
  points.forEach((point, index) => {
    const distance = (point[0] - target[0]) ** 2 + (point[1] - target[1]) ** 2
    if (distance < bestDistance) {
      best = index
      bestDistance = distance
    }
  })
  return points.slice(0, Math.max(2, best + 1))
}

function containsPoint(polygon: Point[], point: Point): boolean {
  let inside = false
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const [x, y] = polygon[index]
    const [previousX, previousY] = polygon[previous]
    const intersects = ((y > point[1]) !== (previousY > point[1]))
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x
    if (intersects) inside = !inside
  }
  return inside
}

function closedSpaceIds(closedIds: string[], connectors: Connector[]): Set<string> {
  const closed = new Set(closedIds)
  const spaces = new Set<string>()
  for (const connector of connectors) {
    if (!closed.has(connector.id)) continue
    for (const spaceId of connector.space_ids) spaces.add(spaceId)
  }
  for (const id of closedIds) spaces.add(id)
  return spaces
}

function StackBadge({ x, y, layer }: { x: number; y: number; layer: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(1 -1)`} className="stack-badge" aria-hidden="true">
      <rect x={-0.55} y={-0.38} width={1.1} height={0.76} rx={0.2} />
      <text textAnchor="middle" dominantBaseline="central" fontSize={0.52}>{`L${layer}`}</text>
    </g>
  )
}

function UprightText({ x, y, children }: { x: number; y: number; children: string }) {
  return (
    <g transform={`translate(${x} ${y}) scale(1 -1)`} className="room-label">
      <text textAnchor="middle" dominantBaseline="middle" fontSize={1.15}>{children}</text>
    </g>
  )
}

const MIN_ZOOM = 1
const MAX_ZOOM = 4

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function PlanCanvas(props: PlanCanvasProps) {
  if (!props.plan) {
    return (
      <div className="plan-wrap plan-empty" data-floor="missing">
        <strong>{props.floorName}</strong>
        <p>{props.emptyText ?? 'This floor has no plan yet.'}</p>
      </div>
    )
  }
  return <InteractivePlan {...props} plan={props.plan} />
}

function InteractivePlan({
  plan,
  floorName,
  route,
  previousRoute = null,
  forkliftRoute = null,
  forkliftCompare = false,
  spaceReasons,
  assetIds,
  closedIds,
  focusPoint,
  stepPoint,
  storyIndex,
  selectionId,
  onSelect,
  onFocusSelection,
  mockPoint = null,
  markerArmed = false,
  onPlaceMarker,
  stepFree = false,
  walkerHere = true,
  onWalkerMove,
  onChangeFloor,
  guidanceTarget = null,
  editor = null,
  preview = null,
}: PlanCanvasProps & { plan: FloorPlan }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>([0, 0])
  const [fitRoute, setFitRoute] = useState(true)
  const [hovered, setHovered] = useState<Selection | null>(null)
  const [hoverPosition, setHoverPosition] = useState({ x: 0, y: 0 })
  const [showItems, setShowItems] = useState(true)
  const [showNumbers, setShowNumbers] = useState(false)
  // The legend floats over the plan, so it opens on request only.
  const [legendOpen, setLegendOpen] = useState(false)
  // One Tab stop for all rooms; arrow keys move between them.
  const [rovingId, setRovingId] = useState<string | null>(null)
  const gesture = useRef({ pointerId: -1, x: 0, y: 0, panX: 0, panY: 0, moved: false })
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<{ startDistance: number; startZoom: number; anchorX: number; anchorY: number } | null>(null)
  const suppressClick = useRef(false)
  const planWrap = useRef<HTMLDivElement>(null)
  const [hoverPoint, setHoverPoint] = useState<Point | null>(null)
  const [dragPoint, setDragPoint] = useState<Point | null>(null)
  const drag = useRef<{ pointerId: number; offset: Point } | null>(null)
  const pointerMode = editor?.mode === 'place' || editor?.mode === 'wall' || editor?.mode === 'rooms'
  useEffect(() => { if (!pointerMode) setHoverPoint(null) }, [pointerMode])
  useEffect(() => {
    const element = planWrap.current
    if (!element) return
    const stopPageZoom = (event: WheelEvent) => {
      event.preventDefault()
      event.stopPropagation()
      setZoom((value) => clamp(value * (event.deltaY < 0 ? 1.12 : 1 / 1.12), MIN_ZOOM, MAX_ZOOM))
    }
    element.addEventListener('wheel', stopPageZoom, { passive: false, capture: true })
    return () => element.removeEventListener('wheel', stopPageZoom, true)
  }, [])

  useEffect(() => {
    setZoom(1)
    setPan([0, 0])
    setFitRoute(true)
    pointers.current.clear()
    pinch.current = null
    gesture.current.pointerId = -1
  }, [plan.floor.id, route?.id])

  const exitIds = escapeSpaceIds(plan)
  const reasons = new Map(spaceReasons)
  if (route?.start_space_id && !reasons.has(route.start_space_id)) reasons.set(route.start_space_id, 'selected')
  if (route?.destination_space_id && !reasons.has(route.destination_space_id)) reasons.set(route.destination_space_id, 'selected')
  for (const spaceId of closedSpaceIds(closedIds, plan.connectors)) {
    if (reasons.get(spaceId) !== 'preview') reasons.set(spaceId, 'closed')
  }

  // A new route opens zoomed to its legs on this floor; "Floor" shows the whole plan again.
  const routePoints = route?.reachable && fitRoute ? route.legs.filter((leg) => leg.floor_id === plan.floor.id).flatMap((leg) => leg.points) : []
  const routeBounds = routePoints.length > 0 ? {
    min: [Math.min(...routePoints.map(([x]) => x)), Math.min(...routePoints.map(([, y]) => y))],
    max: [Math.max(...routePoints.map(([x]) => x)), Math.max(...routePoints.map(([, y]) => y))],
  } : null
  const bounds = routeBounds ?? plan.bounds
  const margin = routeBounds ? 2 : 0
  const minX = bounds.min[0] - margin
  const minY = bounds.min[1] - margin
  const maxX = bounds.max[0] + margin
  const maxY = bounds.max[1] + margin
  const pad = 1.2
  const baseX = minX - pad
  const baseY = -(maxY + pad)
  const baseW = maxX - minX + pad * 2
  const baseH = maxY - minY + pad * 2
  const viewW = baseW / zoom
  const viewH = baseH / zoom
  const maxPanX = Math.max(0, baseW - viewW)
  const maxPanY = Math.max(0, baseH - viewH)
  const panX = clamp(pan[0], 0, maxPanX)
  const panY = clamp(pan[1], 0, maxPanY)
  // Building coordinates are metres with y up. SVG y grows down, so the plan
  // group is flipped and the viewBox origin sits at the top of the plan.
  const viewBox = `${baseX + panX} ${baseY + panY} ${viewW} ${viewH}`
  const setZoomAroundCenter = (nextZoom: number) => {
    const clampedZoom = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM)
    const nextW = baseW / clampedZoom
    const nextH = baseH / clampedZoom
    const centerX = panX + viewW / 2
    const centerY = panY + viewH / 2
    setZoom(clampedZoom)
    setPan([
      clamp(centerX - nextW / 2, 0, Math.max(0, baseW - nextW)),
      clamp(centerY - nextH / 2, 0, Math.max(0, baseH - nextH)),
    ])
  }
  const resetView = () => {
    setZoom(1)
    setPan([0, 0])
  }
  const allowSelect = () => {
    if (!suppressClick.current) return true
    suppressClick.current = false
    return false
  }
  const legs = route?.reachable
    ? route.legs.map((leg, index) => ({ leg, index }))
      .filter(({ leg }) => leg.floor_id === plan.floor.id && leg.points.length > 1)
    : []
  const firstLeg = route?.reachable ? route.legs[0] : null
  const lastLeg = route?.reachable ? route.legs.at(-1) : null
  const focusedSpaceId = focusPoint ? plan.spaces.find((space) => containsPoint(space.polygon, focusPoint))?.id ?? null : null
  if (focusedSpaceId && !reasons.has(focusedSpaceId)) reasons.set(focusedSpaceId, 'selected')

  const toPlan = (clientX: number, clientY: number): Point | null => {
    const svg = svgRef.current
    const matrix = svg?.getScreenCTM()
    if (!svg || !matrix) return null
    const point = svg.createSVGPoint()
    point.x = clientX
    point.y = clientY
    const mapped = point.matrixTransform(matrix.inverse())
    return [mapped.x, -mapped.y]
  }
  const floorGhosts = (editor?.ghosts ?? []).filter((ghost) => ghost.asset.floor_id === plan.floor.id)
  const primaryGhost = floorGhosts[0] ?? null
  const startDrag = (event: ReactPointerEvent<SVGGElement>) => {
    if (event.button !== 0 || !editor?.draggable || !primaryGhost) return
    const point = toPlan(event.clientX, event.clientY)
    if (!point) return
    // The ghost owns this pointer: the map does not pan while it moves.
    event.stopPropagation()
    event.preventDefault()
    svgRef.current?.setPointerCapture(event.pointerId)
    drag.current = { pointerId: event.pointerId, offset: [primaryGhost.asset.position[0] - point[0], primaryGhost.asset.position[1] - point[1]] }
    setDragPoint(primaryGhost.asset.position)
  }
  const dragDelta: Point = dragPoint && primaryGhost ? [dragPoint[0] - primaryGhost.asset.position[0], dragPoint[1] - primaryGhost.asset.position[1]] : [0, 0]
  const layers = new Map((plan.stacking ?? []).map((row) => [row.object_id, row.layer]))
  const previewAssets = preview?.assets.filter((asset) => asset.floor_id === plan.floor.id) ?? []
  const previewOpenings = preview?.openings.filter((opening) => opening.floor_id === plan.floor.id) ?? []
  const removedIds = new Set(preview?.removedIds ?? [])
  const fadedIds = new Set([...(editor?.fadedIds ?? []), ...previewAssets.map((asset) => asset.id)])
  const pickedSpaces = new Set(editor?.pickedSpaceIds ?? [])
  const showAssets = showItems || Boolean(editor) || previewAssets.length > 0 || removedIds.size > 0
  const orderedAssets = [...plan.assets].sort((left, right) => (layers.get(left.id) ?? 0) - (layers.get(right.id) ?? 0))
  const cursorPoint = editor?.mode === 'place' ? hoverPoint : null
  const wallPoint = editor?.mode === 'wall' ? hoverPoint : null

  const updateHover = (event: React.MouseEvent<SVGElement>, selection: Selection) => { const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect(); if (rect) setHoverPosition({ x: event.clientX - rect.left + 14, y: event.clientY - rect.top + 14 }); setHovered(selection) }

  const selectSpace = (space: FloorPlan['spaces'][number]) => {
    const note = spaceAccessNote(space.room_type, connectorNoteFromPlan(plan, space.id), forkliftCompare)
    onFocusSelection({ kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note })
    if (!allowSelect()) return
    onSelect({
      kind: 'space',
      id: space.id,
      name: space.name,
      floorId: plan.floor.id,
      floorName: plan.floor.name,
      note,
    })
  }

  const tabbableId = plan.spaces.some((space) => space.id === rovingId) ? rovingId
    : plan.spaces.some((space) => space.id === selectionId) ? selectionId
      : plan.spaces[0]?.id ?? null
  const moveRoving = (event: React.KeyboardEvent<SVGPolygonElement>, index: number) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? plan.spaces.length - 1 : step !== undefined ? (index + step + plan.spaces.length) % plan.spaces.length : null
    if (target === null) return false
    // The editor nudges a draggable ghost with the arrows; leave them to it.
    if (editor?.draggable) return false
    event.preventDefault()
    // Keep the walk pad from also reading this arrow key.
    event.stopPropagation()
    const next = plan.spaces[target]
    setRovingId(next.id)
    svgRef.current?.querySelector<SVGPolygonElement>(`polygon[data-space-id="${CSS.escape(next.id)}"]`)?.focus()
    return true
  }

  return (
    <div className="plan-shell">
      <div className="map-canvas-region">
      <div ref={planWrap} className="plan-wrap" aria-label={`${floorName} plan`} data-floor={plan.floor.id}>
      <svg
        ref={svgRef}
        className={`plan${gesture.current.pointerId >= 0 ? ' panning' : ''}${editor ? ` editing editing-${editor.mode}` : ''}`}
        viewBox={viewBox}
        data-zoom={zoom}
        onClick={(event) => {
          if (editor && pointerMode) {
            if (suppressClick.current) { suppressClick.current = false; return }
            const point = toPlan(event.clientX, event.clientY)
            if (!point) return
            if (editor.mode === 'rooms') {
              const space = spaceAt(plan.spaces, point)
              if (space) editor.onPickSpace(space.id)
              return
            }
            editor.onPoint(point)
            return
          }
          if (!markerArmed || !onPlaceMarker) return
          const svg = event.currentTarget
          const point = svg.createSVGPoint()
          point.x = event.clientX
          point.y = event.clientY
          const mapped = point.matrixTransform(svg.getScreenCTM()?.inverse())
          onPlaceMarker([mapped.x, -mapped.y])
        }}
        onPointerDown={(event) => {
          if (event.button !== 0) return
          pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
          if (pointers.current.size === 1) {
            const interactive = event.target instanceof Element ? event.target.closest('[role="button"]') : null
            if (interactive instanceof SVGElement) interactive.focus({ preventScroll: true })
            else onFocusSelection(null)
          }
          if (pointers.current.size === 2) {
            const [first, second] = [...pointers.current.values()]
            const rect = event.currentTarget.getBoundingClientRect()
            const centerX = (first.x + second.x) / 2
            const centerY = (first.y + second.y) / 2
            pinch.current = { startDistance: Math.hypot(second.x - first.x, second.y - first.y), startZoom: zoom, anchorX: panX + ((centerX - rect.left) / rect.width) * viewW, anchorY: panY + ((centerY - rect.top) / rect.height) * viewH }
            gesture.current.pointerId = -1
            suppressClick.current = true
          }
          gesture.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, panX, panY, moved: false }
        }}
        onPointerMove={(event) => {
          if (drag.current?.pointerId === event.pointerId && editor) {
            const point = toPlan(event.clientX, event.clientY)
            if (point) setDragPoint(editor.constrain([point[0] + drag.current.offset[0], point[1] + drag.current.offset[1]]))
            return
          }
          if ((editor?.mode === 'place' || editor?.mode === 'wall') && event.pointerType === 'mouse') setHoverPoint(toPlan(event.clientX, event.clientY))
          if (!pointers.current.has(event.pointerId)) return
          pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
          if (pointers.current.size >= 2 && pinch.current) {
            const [first, second] = [...pointers.current.values()]
            const distance = Math.hypot(second.x - first.x, second.y - first.y)
            const nextZoom = clamp(pinch.current.startZoom * (distance / pinch.current.startDistance), MIN_ZOOM, MAX_ZOOM)
            const rect = event.currentTarget.getBoundingClientRect()
            const centerX = (first.x + second.x) / 2
            const centerY = (first.y + second.y) / 2
            const nextW = baseW / nextZoom
            const nextH = baseH / nextZoom
            setZoom(nextZoom)
            setPan([
              clamp(pinch.current.anchorX - ((centerX - rect.left) / rect.width) * nextW, 0, Math.max(0, baseW - nextW)),
              clamp(pinch.current.anchorY - ((centerY - rect.top) / rect.height) * nextH, 0, Math.max(0, baseH - nextH)),
            ])
            suppressClick.current = true
            return
          }
          if (gesture.current.pointerId !== event.pointerId) return
          const dx = event.clientX - gesture.current.x
          const dy = event.clientY - gesture.current.y
          if (!gesture.current.moved && Math.hypot(dx, dy) < 6) return
          if (!gesture.current.moved) event.currentTarget.setPointerCapture(event.pointerId)
          gesture.current.moved = true
          const rect = event.currentTarget.getBoundingClientRect()
          setPan([
            clamp(gesture.current.panX - (dx / rect.width) * viewW, 0, maxPanX),
            clamp(gesture.current.panY - (dy / rect.height) * viewH, 0, maxPanY),
          ])
        }}
        onPointerLeave={() => setHoverPoint(null)}
        onPointerUp={(event) => {
          if (drag.current?.pointerId === event.pointerId) {
            const finalPoint = dragPoint
            drag.current = null
            setDragPoint(null)
            if (finalPoint && editor) editor.onDragEnd([Math.round(finalPoint[0] * 1000) / 1000, Math.round(finalPoint[1] * 1000) / 1000])
            return
          }
          pointers.current.delete(event.pointerId)
          if (pointers.current.size === 0) {
            if (gesture.current.pointerId === event.pointerId && gesture.current.moved) suppressClick.current = true
            gesture.current.pointerId = -1
            pinch.current = null
            return
          }
          if (pinch.current) {
            const [remaining] = [...pointers.current.entries()]
            pinch.current = null
            gesture.current = { pointerId: remaining[0], x: remaining[1].x, y: remaining[1].y, panX, panY, moved: true }
          }
        }}
        onPointerCancel={(event) => {
          if (drag.current?.pointerId === event.pointerId) {
            drag.current = null
            setDragPoint(null)
            return
          }
          pointers.current.delete(event.pointerId)
          pinch.current = null
          gesture.current.pointerId = -1
          suppressClick.current = true
        }}
      >
        <g transform="scale(1 -1)">
          {plan.spaces.map((space, spaceIndex) => {
            const reason = reasons.get(space.id)
            const roomType = (space.room_type || space.type || 'other').toLowerCase().replace(/[^a-z0-9]+/g, '-')
            const role = wayfindingRole(space) ?? (exitIds.has(space.id) ? 'escape' : null)
            const picked = selectionId === space.id
            const [cx, cy] = centroid(space.polygon)
            const showLabel = showNumbers && polygonArea(space.polygon) >= 28
            return (
              <g key={space.id}>
                <polygon
                  points={space.polygon.map(([x, y]) => `${x},${y}`).join(' ')}
                  className={['space', `room-type-${roomType}`, role ? `role-${role}` : '', reason ? `reason-${reason}` : '', picked ? 'picked' : '', pickedSpaces.has(space.id) ? 'editor-picked' : ''].filter(Boolean).join(' ')}
                  role="button"
                  tabIndex={space.id === tabbableId ? 0 : -1}
                  data-space-id={space.id}
                  aria-label={space.name}
                  aria-pressed={picked}
                  onMouseEnter={(event) => updateHover(event, spaceTip(plan, space))}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => { setRovingId(space.id); onFocusSelection({ kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note: connectorNoteFromPlan(plan, space.id) }) }}
                  onBlur={(event) => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.ownerSVGElement?.contains(event.relatedTarget)) onFocusSelection(null) }}
                  onClick={() => { if (!pointerMode) selectSpace(space) }}
                  onKeyDown={(event) => {
                    if (moveRoving(event, spaceIndex)) return
                    if (event.key !== 'Enter' && event.key !== ' ') return
                    event.preventDefault()
                    // Keyboard path for the editor: Enter places into this room or picks it as a stop.
                    if (editor?.mode === 'rooms') editor.onPickSpace(space.id)
                    else if (editor?.mode === 'place') editor.onPoint(interiorPoint(space.polygon))
                    else if (editor?.mode !== 'wall') selectSpace(space)
                  }}
                >
                  <title>{space.name}</title>
                </polygon>
                {showLabel && <UprightText x={cx} y={cy}>{space.ref || space.name}</UprightText>}
              </g>
            )
          })}
          {plan.openings.map((opening) => {
            const access = openingAccessNote(opening, forkliftCompare)
            const openingSelection = { kind: 'opening' as const, id: opening.id, name: `${opening.kind}, ${opening.width_m} m`, floorId: plan.floor.id, floorName: plan.floor.name, note: access }
            return (
            <circle
              key={opening.id}
              cx={opening.position[0]}
              cy={opening.position[1]}
              r={opening.kind === 'entrance' ? 0.72 : 0.42}
              className={['opening', opening.kind, selectionId === opening.id ? 'picked' : '', opening.step_free ? '' : 'stepped', closedIds.includes(opening.id) ? 'closed' : '', forkliftCompare && opening.width_m < 3 ? 'forklift-narrow' : ''].filter(Boolean).join(' ')}
              role="button"
              tabIndex={-1}
              onMouseEnter={(event) => updateHover(event, openingSelection)}
              onMouseLeave={() => setHovered(null)}
              aria-label={`${opening.kind}, ${opening.width_m} m. ${access}`}
              onClick={(event) => {
                if (pointerMode) return
                event.stopPropagation()
                onFocusSelection(openingSelection)
                if (!allowSelect()) return
                onSelect(openingSelection)
              }}
            >
              <title>{`${opening.kind}, ${opening.width_m} m. ${access}`}</title>
            </circle>
            )
          })}
          {showAssets && orderedAssets.map((asset) => {
            const landmark = landmarkIds(plan, stepPoint).includes(asset.id)
            const highlighted = assetIds.has(asset.id) || landmark
            const picked = selectionId === asset.id
            const layer = layers.get(asset.id) ?? 0
            const { width_m: width, depth_m: depth, rotation_deg: rotation } = asset.footprint
            return (
              <g
                key={asset.id}
                transform={`translate(${asset.position[0]} ${asset.position[1]}) rotate(${rotation})`}
                className={['asset', asset.category, highlighted ? 'highlighted' : '', landmark ? 'landmark' : '', picked ? 'picked' : '', layer > 0 ? 'stacked' : '', fadedIds.has(asset.id) ? 'moving-origin' : '', removedIds.has(asset.id) ? 'removing' : ''].filter(Boolean).join(' ')}
                role="button"
                tabIndex={highlighted ? 0 : -1}
                onMouseEnter={(event) => updateHover(event, assetTip(plan, asset))}
                onMouseLeave={() => setHovered(null)}
                aria-label={layer > 0 ? `${asset.name}, layer ${layer}` : asset.name}
                aria-pressed={picked}
                onClick={(event) => {
                  if (pointerMode) return
                  event.stopPropagation()
                onFocusSelection({ kind: 'asset', id: asset.id, name: asset.name, floorId: plan.floor.id, floorName: plan.floor.name, note: asset.type })
                  if (!allowSelect()) return
                  onSelect({
                    kind: 'asset',
                    id: asset.id,
                    name: asset.name,
                    floorId: plan.floor.id,
                    floorName: plan.floor.name,
                    note: asset.type,
                  })
                }}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter' && event.key !== ' ') return
                  event.preventDefault()
                  onSelect({
                    kind: 'asset',
                    id: asset.id,
                    name: asset.name,
                    floorId: plan.floor.id,
                    floorName: plan.floor.name,
                    note: asset.type,
                  })
                }}
              >
                <title>{asset.name}</title>
                <rect x={-width / 2} y={-depth / 2} width={Math.max(width, 0.35)} height={Math.max(depth, 0.35)} />
              </g>
            )
          })}
          {showAssets && orderedAssets.map((asset) => {
            const layer = layers.get(asset.id) ?? 0
            if (layer < 1 || fadedIds.has(asset.id)) return null
            return <StackBadge key={`badge-${asset.id}`} x={asset.position[0] + Math.max(asset.footprint.width_m, 0.35) / 2} y={asset.position[1] + Math.max(asset.footprint.depth_m, 0.35) / 2} layer={layer} />
          })}
          {previewAssets.map((asset) => (
            <g key={`preview-${asset.id}`} className={['asset', 'ghost', 'preview', asset.category].join(' ')} transform={`translate(${asset.position[0]} ${asset.position[1]}) rotate(${asset.footprint.rotation_deg})`} aria-hidden="true">
              <rect x={-asset.footprint.width_m / 2} y={-asset.footprint.depth_m / 2} width={Math.max(asset.footprint.width_m, 0.35)} height={Math.max(asset.footprint.depth_m, 0.35)} />
            </g>
          ))}
          {previewOpenings.map((opening) => <circle key={`preview-${opening.id}`} className="opening ghost" cx={opening.position[0]} cy={opening.position[1]} r={0.55} aria-hidden="true" />)}
          {floorGhosts.map(({ asset, layer }, index) => {
            const x = asset.position[0] + dragDelta[0]
            const y = asset.position[1] + dragDelta[1]
            const primary = index === 0
            return (
              <g key={`ghost-${asset.id}`}>
                <g
                  className={['asset', 'ghost', asset.category, primary && editor?.invalid ? 'invalid' : '', primary && editor?.draggable ? 'draggable' : '', dragPoint ? 'dragging' : ''].filter(Boolean).join(' ')}
                  transform={`translate(${x} ${y}) rotate(${asset.footprint.rotation_deg})`}
                  onPointerDown={primary ? startDrag : undefined}
                  aria-hidden="true"
                >
                  <rect x={-asset.footprint.width_m / 2} y={-asset.footprint.depth_m / 2} width={Math.max(asset.footprint.width_m, 0.35)} height={Math.max(asset.footprint.depth_m, 0.35)} />
                  {primary && <circle className="ghost-centre" r={0.12} />}
                </g>
                {layer > 0 && <StackBadge x={x + Math.max(asset.footprint.width_m, 0.35) / 2} y={y + Math.max(asset.footprint.depth_m, 0.35) / 2} layer={layer} />}
              </g>
            )
          })}
          {editor?.ghostOpening && editor.ghostOpening.floor_id === plan.floor.id && (
            <circle className={['opening', 'ghost', editor.invalid ? 'invalid' : ''].filter(Boolean).join(' ')} cx={editor.ghostOpening.position[0]} cy={editor.ghostOpening.position[1]} r={0.55} aria-hidden="true" />
          )}
          {cursorPoint && editor?.cursor && (
            <g className={['asset', 'ghost', 'cursor', editor.cursor.category].join(' ')} transform={`translate(${cursorPoint[0]} ${cursorPoint[1]}) rotate(${editor.cursor.rotation})`} aria-hidden="true">
              <rect x={-editor.cursor.width / 2} y={-editor.cursor.depth / 2} width={Math.max(editor.cursor.width, 0.35)} height={Math.max(editor.cursor.depth, 0.35)} />
            </g>
          )}
          {wallPoint && <circle className="wall-cursor" cx={wallPoint[0]} cy={wallPoint[1]} r={0.45} aria-hidden="true" />}
          {forkliftRoute?.reachable && forkliftRoute.legs.filter((leg) => leg.floor_id === plan.floor.id).map((leg, index) => (
            <polyline key={`forklift-route-${index}`} points={leg.points.map(([x, y]) => `${x},${y}`).join(' ')} className="route-forklift" />
          ))}
          {previousRoute?.reachable && previousRoute.legs.filter((leg) => leg.floor_id === plan.floor.id).map((leg, index) => (
            <polyline key={`previous-route-${index}`} points={leg.points.map(([x, y]) => `${x},${y}`).join(' ')} className="route-previous" />
          ))}
          {route?.reachable && previousRoute?.reachable && route.legs.filter((leg) => leg.floor_id === plan.floor.id).map((leg, index) => {
            const oldLeg = previousRoute.legs.find((candidate) => candidate.floor_id === leg.floor_id)
            const point = leg.points.find((candidate) => !oldLeg?.points.some((oldPoint) => Math.hypot(candidate[0] - oldPoint[0], candidate[1] - oldPoint[1]) < 1.5))
            return point ? <circle key={`route-change-${index}`} className="route-change-node" cx={point[0]} cy={point[1]} r={0.7}><title>Route changed here</title></circle> : null
          })}
          {legs.map(({ leg, index }) => {
            const previous = route?.legs[index - 1]
            const next = route?.legs[index + 1]
            const handoffs = [
              ...(previous && previous.floor_id !== leg.floor_id ? [{ point: leg.points[0], label: 'Arrive from another floor' }] : []),
              ...(next && next.floor_id !== leg.floor_id ? [{ point: leg.points.at(-1)!, label: 'Continue on another floor' }] : []),
            ]
            // The whole route is always drawn; the step player only highlights the part already told.
            const told = route?.directions[storyIndex]
            const progress = storyIndex > 0 && told?.floor_id === plan.floor.id ? prefixTo(leg.points, told.at) : null
            const points = leg.points.map(([x, y]) => `${x},${y}`).join(' ')
            return (
              <g key={index}>
                {/* Keep each backend leg separate, including gaps in validated geometry. */}
                <polyline points={points} className="route-underlay" />
                <polyline points={points} className="route" />
                {progress && <polyline points={progress.map(([x, y]) => `${x},${y}`).join(' ')} className="route-progress" />}
                {handoffs.map(({ point, label }) => (
                  <g key={label} className="handoff" transform={`translate(${point[0]} ${point[1]})`}>
                    <circle r={1.15} />
                    <title>{label}</title>
                  </g>
                ))}
              </g>
            )
          })}
          {route?.reachable && route.directions.map((direction, index) => direction.at && direction.floor_id === plan.floor.id && index > 0 && (
            <circle key={`step-${index}`} className="route-step" cx={direction.at[0]} cy={direction.at[1]} r={0.45}><title>{direction.text}</title></circle>
          ))}
          {firstLeg && firstLeg.floor_id === plan.floor.id && firstLeg.points.length > 0 && (
            <circle className="start" cx={firstLeg.points[0][0]} cy={firstLeg.points[0][1]} r={0.72} />
          )}
          {lastLeg && lastLeg.floor_id === plan.floor.id && lastLeg.points.length > 0 && (
            <circle className="destination" cx={lastLeg.points.at(-1)![0]} cy={lastLeg.points.at(-1)![1]} r={0.9} />
          )}
          {stepPoint && <circle className="step-marker" cx={stepPoint[0]} cy={stepPoint[1]} r={1.05} />}
          {guidanceTarget && <circle className="guidance-ring" cx={guidanceTarget[0]} cy={guidanceTarget[1]} r={3} />}
          {mockPoint && <circle className="mock-marker" cx={mockPoint[0]} cy={mockPoint[1]} r={1.3} />}
        </g>
      </svg>
      <WalkPad svgRef={svgRef} containerRef={planWrap} plan={plan} route={route} closedIds={closedIds} stepFree={stepFree} keysPaused={Boolean(editor)} walkerHere={walkerHere} onMove={onWalkerMove} onChangeFloor={onChangeFloor} />
      {hovered && <MapTooltip item={hovered} x={hoverPosition.x} y={hoverPosition.y} />}
    </div>
      <div className="map-tools">
      <div
        className="map-controls"
        role="group"
        aria-label="Map view"
        onKeyDown={(event) => {
          if (event.key === '+' || event.key === '=') setZoomAroundCenter(zoom * 1.25)
          if (event.key === '-' || event.key === '_') setZoomAroundCenter(zoom / 1.25)
          if (event.key === '0') resetView()
        }}
      >
        <button type="button" aria-label="Zoom out" onClick={() => setZoomAroundCenter(zoom / 1.25)} disabled={zoom <= MIN_ZOOM}>-</button>
        <span>{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label="Zoom in" onClick={() => setZoomAroundCenter(zoom * 1.25)} disabled={zoom >= MAX_ZOOM}>+</button>
        {route?.reachable && <button type="button" onClick={() => { setFitRoute(true); resetView() }}>Fit route</button>}
        <button type="button" onClick={() => { setFitRoute(false); resetView() }}>Fit floor</button>
      </div>
      <div className="map-display-mode segmented" role="group" aria-label="Map detail">
        <button type="button" aria-pressed={showItems} onClick={() => setShowItems((value) => !value)}>Items</button>
        <button type="button" aria-pressed={showNumbers} onClick={() => setShowNumbers((value) => !value)}>Room numbers</button>
      </div>
      <div className="map-legend-wrap">
        <button type="button" className="map-legend-toggle" aria-expanded={legendOpen} aria-controls={legendOpen ? `${plan.floor.id}-legend` : undefined} onClick={() => setLegendOpen((value) => !value)}>Legend</button>
        {legendOpen && (
          <div id={`${plan.floor.id}-legend`} className="map-legend" role="group" aria-label="Map legend">
            <span><i className="legend-sample sample-room" /><b>Room</b></span>
            <span><i className="legend-sample sample-stairs" /><b>Stairs</b></span>
            <span><i className="legend-sample sample-lift" /><b>Lift</b></span>
            <span><i className="legend-sample sample-escape" /><b>Escape route</b></span>
            <span><i className="legend-sample sample-equipment" /><b>Equipment</b></span>
            <span><i className="legend-sample sample-opening" /><b>Door / connector</b></span>
            <span><i className="legend-sample sample-route" /><b>Current route</b></span>
            {forkliftCompare && <span><i className="legend-sample sample-forklift" /><b>Forklift route</b></span>}
            <span><i className="legend-sample sample-previous-route" /><b>Previous route</b></span>
            <span><i className="legend-sample sample-change" /><b>Reroute point</b></span>
            <span><i className="legend-sample sample-closed" /><b>Closed / blocked</b></span>
          </div>
        )}
      </div>
      </div>
      </div>
          </div>
  )
}






