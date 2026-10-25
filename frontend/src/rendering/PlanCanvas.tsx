import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { Asset, FloorPlan, Opening, Point, Route, Selection } from '../domain/types'
import type { Connector } from '../domain/types'
import { interiorPoint, spaceAt } from '../domain/editor'
import { connectorNoteFromPlan, landmarkIds } from '../domain/live'
import type { PreviewObjects } from '../domain/presentation'
import { MapTooltip, assetTip, openingTip, spaceTip } from './MapTooltip'
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
  route: Route | null
  spaceReasons: Map<string, string>
  assetIds: Set<string>
  closedIds: string[]
  focusPoint: Point | null
  stepPoint: Point | null
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
  /** Emergency mode: people still inside on this floor, drawn with their names during an alarm. */
  people?: PlanPerson[]
  /** Person picked in the emergency list; gets a ring. */
  focusedPersonId?: string | null
}

export type PlanPerson = { id: string; label: string; status: 'inside' | 'outside' | 'outside_manual'; stale: boolean; position: Point }

function polygonArea(polygon: Point[]): number {
  let sum = 0
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index]
    const [x2, y2] = polygon[(index + 1) % polygon.length]
    sum += x1 * y2 - x2 * y1
  }
  return Math.abs(sum) / 2
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

function centroid(polygon: Point[]): Point {
  const total = polygon.reduce(([x, y], [px, py]) => [x + px, y + py], [0, 0])
  return [total[0] / polygon.length, total[1] / polygon.length]
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
      <div className="plan-wrap plan-empty" role="status" data-floor="missing">
        <strong>{props.floorName}</strong>
        <p>No plan fixture for this floor.</p>
      </div>
    )
  }
  return <InteractivePlan {...props} plan={props.plan} />
}

function InteractivePlan({
  plan,
  floorName,
  route,
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
  people = [],
  focusedPersonId = null,
}: PlanCanvasProps & { plan: FloorPlan }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>([0, 0])
  const [hovered, setHovered] = useState<Selection | null>(null)
  const [hoverPosition, setHoverPosition] = useState({ x: 0, y: 0 })
  const [displayMode, setDisplayMode] = useState<'rooms' | 'items' | 'labels'>('items')
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
    pointers.current.clear()
    pinch.current = null
    gesture.current.pointerId = -1
  }, [plan.floor.id])

  const reasons = new Map(spaceReasons)
  if (route?.start_space_id && !reasons.has(route.start_space_id)) reasons.set(route.start_space_id, 'selected')
  if (route?.destination_space_id && !reasons.has(route.destination_space_id)) reasons.set(route.destination_space_id, 'selected')
  for (const spaceId of closedSpaceIds(closedIds, plan.connectors)) {
    if (reasons.get(spaceId) !== 'preview') reasons.set(spaceId, 'closed')
  }

  const [minX, minY] = plan.bounds.min
  const [maxX, maxY] = plan.bounds.max
  // Room for the entrance aprons: the walker and emergency markers can stand 2.5 m outside.
  const pad = 3.2
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
  const legs = route?.reachable ? route.legs.filter((leg) => leg.floor_id === plan.floor.id && leg.points.length > 1) : []
  const firstLeg = route?.legs[0]
  const lastLeg = route?.legs.at(-1)
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
  const showAssets = displayMode === 'items' || Boolean(editor) || previewAssets.length > 0 || removedIds.size > 0
  const orderedAssets = [...plan.assets].sort((left, right) => (layers.get(left.id) ?? 0) - (layers.get(right.id) ?? 0))
  const cursorPoint = editor?.mode === 'place' ? hoverPoint : null
  const wallPoint = editor?.mode === 'wall' ? hoverPoint : null

  const updateHover = (event: React.MouseEvent<SVGElement>, selection: Selection) => { const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect(); if (rect) setHoverPosition({ x: event.clientX - rect.left + 14, y: event.clientY - rect.top + 14 }); setHovered(selection) }

  const selectSpace = (space: FloorPlan['spaces'][number]) => {
    onFocusSelection({ kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note: connectorNoteFromPlan(plan, space.id) })
    if (!allowSelect()) return
    onSelect({
      kind: 'space',
      id: space.id,
      name: space.name,
      floorId: plan.floor.id,
      floorName: plan.floor.name,
      note: connectorNoteFromPlan(plan, space.id),
    })
  }

  return (
    <div className="plan-shell">
      <div className="map-legend" aria-label="Map legend"><strong>Map legend</strong><span><i className="legend-sample sample-room" /><b>Room</b></span><span><i className="legend-sample sample-equipment" /><b>Equipment</b></span><span><i className="legend-sample sample-opening" /><b>Door / connector</b></span><span><i className="legend-sample sample-route" /><b>Current route</b></span><span><i className="legend-sample sample-closed" /><b>Closed / blocked</b></span><small>Shapes and colors match the map.</small></div>
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
          {plan.spaces.map((space) => {
            const reason = reasons.get(space.id)
            const roomType = (space.room_type || space.type || 'other').toLowerCase().replace(/[^a-z0-9]+/g, '-')
            const picked = selectionId === space.id
            const [cx, cy] = centroid(space.polygon)
            const showLabel = displayMode === 'rooms' && polygonArea(space.polygon) >= 28
            return (
              <g key={space.id}>
                <polygon
                  points={space.polygon.map(([x, y]) => `${x},${y}`).join(' ')}
                  className={['space', `room-type-${roomType}`, reason ? `reason-${reason}` : '', picked ? 'picked' : '', pickedSpaces.has(space.id) ? 'editor-picked' : ''].filter(Boolean).join(' ')}
                  role="button"
                  tabIndex={0}
                  aria-label={space.name}
                  aria-pressed={picked}
                  onMouseEnter={(event) => updateHover(event, spaceTip(plan, space))}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => onFocusSelection({ kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note: connectorNoteFromPlan(plan, space.id) })}
                  onBlur={(event) => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.ownerSVGElement?.contains(event.relatedTarget)) onFocusSelection(null) }}
                  onClick={() => { if (!pointerMode) selectSpace(space) }}
                  onKeyDown={(event) => {
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
          {plan.openings.map((opening) => (
            <circle
              key={opening.id}
              cx={opening.position[0]}
              cy={opening.position[1]}
              r={opening.kind === 'entrance' ? 0.72 : 0.42}
              className={['opening', opening.kind, selectionId === opening.id ? 'picked' : '', opening.step_free ? '' : 'stepped'].filter(Boolean).join(' ')}
              role="button"
              tabIndex={-1}
              onMouseEnter={(event) => updateHover(event, openingTip(plan, opening))}
              onMouseLeave={() => setHovered(null)}
              aria-label={`${opening.kind}, ${opening.width_m} m`}
              onClick={(event) => {
                if (pointerMode) return
                event.stopPropagation()
                onFocusSelection({ kind: 'opening', id: opening.id, name: `${opening.kind}, ${opening.width_m} m`, floorId: plan.floor.id, floorName: plan.floor.name, note: opening.step_free ? 'Step-free' : 'Has a step' })
                if (!allowSelect()) return
                onSelect({
                  kind: 'opening',
                  id: opening.id,
                  name: `${opening.kind}, ${opening.width_m} m`,
                  floorId: plan.floor.id,
                  floorName: plan.floor.name,
                  note: opening.step_free ? 'Step-free' : 'Has a step',
                })
              }}
            >
              <title>{`${opening.kind}, ${opening.width_m} m`}</title>
            </circle>
          ))}
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
          {legs.map((leg) => {
            // The whole route is always drawn; the step player only highlights the part already told.
            const told = route?.directions[storyIndex]
            const progress = storyIndex > 0 && told?.floor_id === plan.floor.id ? prefixTo(leg.points, told.at) : null
            const continues = route ? route.legs.slice(route.legs.indexOf(leg) + 1).some((later) => later.floor_id !== plan.floor.id) : false
            const handoff = continues ? leg.points.at(-1)! : null
            const connector = handoff
              ? plan.connectors.find((item) => item.space_ids.some((spaceId) => {
                const space = plan.spaces.find((candidate) => candidate.id === spaceId)
                return space ? containsPoint(space.polygon, handoff) : false
              }))
              : null
            return (
              <g key={`${leg.floor_id}-${leg.points.length}`}>
                <polyline points={leg.points.map(([x, y]) => `${x},${y}`).join(' ')} className="route" />
                {progress && <polyline points={progress.map(([x, y]) => `${x},${y}`).join(' ')} className="route-progress" />}
                {handoff && (
                  <g className="handoff" transform={`translate(${handoff[0]} ${handoff[1]})`}>
                    <circle r={1.15} />
                    <title>{connector?.name ?? 'Change floor'}</title>
                  </g>
                )}
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
          {people.length > 0 && <g className="emergency-people">
            {people.map((person) => (
              <g key={person.id} className={`emergency-person ${person.status}${person.stale ? ' stale' : ''}`}>
                {person.id === focusedPersonId && <circle className="emergency-person-focus" cx={person.position[0]} cy={person.position[1]} r={2.2} />}
                <circle cx={person.position[0]} cy={person.position[1]} r={0.75}><title>{person.label}</title></circle>
                <g transform={`translate(${person.position[0] + 1.05} ${person.position[1]}) scale(1 -1)`} className="emergency-person-label" aria-hidden="true">
                  <text dominantBaseline="middle" fontSize={1.1}>{person.label}</text>
                </g>
              </g>
            ))}
          </g>}
        </g>
      </svg>
      <WalkPad svgRef={svgRef} plan={plan} route={route} closedIds={closedIds} stepFree={stepFree} keysPaused={Boolean(editor)} walkerHere={walkerHere} onMove={onWalkerMove} onChangeFloor={onChangeFloor} />
      {hovered && <MapTooltip item={hovered} x={hoverPosition.x} y={hoverPosition.y} />}
    </div>
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
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label="Zoom in" onClick={() => setZoomAroundCenter(zoom * 1.25)} disabled={zoom >= MAX_ZOOM}>+</button>
        <button type="button" aria-label="Reset map to 100 percent" onClick={resetView}>Reset</button>
      </div>
      <div className="map-display-mode" role="group" aria-label="Map detail level"><button type="button" aria-pressed={displayMode === 'labels'} onClick={() => setDisplayMode('labels')}>Rooms</button><button type="button" aria-pressed={displayMode === 'items'} onClick={() => setDisplayMode('items')}>Rooms + items</button><button type="button" aria-pressed={displayMode === 'rooms'} onClick={() => setDisplayMode('rooms')}>Rooms + numbers</button></div>
      </div>
          </div>
  )
}






