import { useEffect, useRef, useState } from 'react'
import type { FloorPlan, Point, Route, Selection } from '../domain/types'
import type { Connector } from '../domain/types'
import { connectorNoteFromPlan, landmarkIds } from '../domain/live'
import { WalkPad } from './WalkPad'

type PlanCanvasProps = {
  plan: FloorPlan | null
  floorName: string
  route: Route | null
  spaceReasons: Map<string, string>
  assetIds: Set<string>
  closedIds: string[]
  focusPoint: Point | null
  stepPoint: Point | null
  selectionId: string | null
  onSelect: (selection: Selection) => void
  onFocusSelection: (selection: Selection | null) => void
  mockPoint?: Point | null
  markerArmed?: boolean
  onPlaceMarker?: (point: Point) => void
  stepFree?: boolean
  simulation?: boolean
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
  selectionId,
  onSelect,
  onFocusSelection,
  mockPoint = null,
  markerArmed = false,
  onPlaceMarker,
  stepFree = false,
  simulation = false,
}: PlanCanvasProps & { plan: FloorPlan }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>([0, 0])
  const [fitRoute, setFitRoute] = useState(true)
  const [hovered, setHovered] = useState<Selection | null>(null)
  const [hoverPosition, setHoverPosition] = useState({ x: 0, y: 0 })
  const [displayMode, setDisplayMode] = useState<'rooms' | 'items' | 'labels'>('labels')
  const gesture = useRef({ pointerId: -1, x: 0, y: 0, panX: 0, panY: 0, moved: false })
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<{ startDistance: number; startZoom: number; anchorX: number; anchorY: number } | null>(null)
  const suppressClick = useRef(false)
  const planWrap = useRef<HTMLDivElement>(null)
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

  const reasons = new Map(spaceReasons)
  if (route?.start_space_id && !reasons.has(route.start_space_id)) reasons.set(route.start_space_id, 'selected')
  if (route?.destination_space_id && !reasons.has(route.destination_space_id)) reasons.set(route.destination_space_id, 'selected')
  for (const spaceId of closedSpaceIds(closedIds, plan.connectors)) {
    if (reasons.get(spaceId) !== 'preview') reasons.set(spaceId, 'closed')
  }

  const routePoints = route?.reachable && fitRoute ? route.legs.filter((leg) => leg.floor_id === plan.floor.id).flatMap((leg) => leg.points) : []
  const routeBounds = routePoints.length > 0 ? {
    min: [Math.min(...routePoints.map(([x]) => x)), Math.min(...routePoints.map(([, y]) => y))],
    max: [Math.max(...routePoints.map(([x]) => x)), Math.max(...routePoints.map(([, y]) => y))],
  } : null
  const bounds = routeBounds ?? plan.bounds
  const minX = bounds.min[0] - (routeBounds ? 2 : 0)
  const minY = bounds.min[1] - (routeBounds ? 2 : 0)
  const maxX = bounds.max[0] + (routeBounds ? 2 : 0)
  const maxY = bounds.max[1] + (routeBounds ? 2 : 0)
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
      <details className="map-legend"><summary>Map key</summary><div className="legend-items"><span><i className="legend-sample sample-room" />Room</span><span><i className="legend-sample sample-equipment" />Equipment</span><span><i className="legend-sample sample-opening" />Door / connector</span><span><i className="legend-sample sample-route" />Current route</span><span><i className="legend-sample sample-closed" />Closed / blocked</span></div></details>
      <div className="map-canvas-region">
      <div ref={planWrap} className="plan-wrap" aria-label={`${floorName} plan`} data-floor={plan.floor.id}>
      <svg
        ref={svgRef}
        className={`plan${gesture.current.pointerId >= 0 ? ' panning' : ''}`}
        viewBox={viewBox}
        data-zoom={zoom}
        onClick={(event) => {
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
            if (interactive instanceof SVGElement) interactive.focus()
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
        onPointerUp={(event) => {
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
                  className={['space', `room-type-${roomType}`, reason ? `reason-${reason}` : '', picked ? 'picked' : ''].filter(Boolean).join(' ')}
                  role="button"
                  tabIndex={0}
                  aria-label={space.name}
                  aria-pressed={picked}
                  onMouseEnter={(event) => updateHover(event, { kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note: connectorNoteFromPlan(plan, space.id) })}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => onFocusSelection({ kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note: connectorNoteFromPlan(plan, space.id) })}
                  onBlur={(event) => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.ownerSVGElement?.contains(event.relatedTarget)) onFocusSelection(null) }}
                  onClick={() => selectSpace(space)}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return
                    event.preventDefault()
                    selectSpace(space)
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
              onMouseEnter={(event) => updateHover(event, { kind: 'opening', id: opening.id, name: opening.kind, floorId: plan.floor.id, floorName: plan.floor.name, note: `${opening.width_m} m - ${opening.step_free ? 'Step-free' : 'Has a step'}` })}
              onMouseLeave={() => setHovered(null)}
              aria-label={`${opening.kind}, ${opening.width_m} m`}
              onClick={(event) => {
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
          {displayMode === 'items' && plan.assets.map((asset) => {
            const landmark = landmarkIds(plan, stepPoint).includes(asset.id)
            const highlighted = assetIds.has(asset.id) || landmark
            const picked = selectionId === asset.id
            const { width_m: width, depth_m: depth, rotation_deg: rotation } = asset.footprint
            return (
              <g
                key={asset.id}
                transform={`translate(${asset.position[0]} ${asset.position[1]}) rotate(${rotation})`}
                className={['asset', asset.category, highlighted ? 'highlighted' : '', landmark ? 'landmark' : '', picked ? 'picked' : ''].filter(Boolean).join(' ')}
                role="button"
                tabIndex={highlighted ? 0 : -1}
                onMouseEnter={(event) => updateHover(event, { kind: 'asset', id: asset.id, name: asset.name, floorId: plan.floor.id, floorName: plan.floor.name, note: `${asset.type} - ${asset.category}` })}
                onMouseLeave={() => setHovered(null)}
                aria-label={asset.name}
                aria-pressed={picked}
                onClick={(event) => {
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
          {legs.map(({ leg, index }) => {
            const previous = route?.legs[index - 1]
            const next = route?.legs[index + 1]
            const handoffs = [
              ...(previous && previous.floor_id !== leg.floor_id ? [{ point: leg.points[0], label: 'Arrive from another floor' }] : []),
              ...(next && next.floor_id !== leg.floor_id ? [{ point: leg.points.at(-1)!, label: 'Continue on another floor' }] : []),
            ]
            const points = leg.points.map(([x, y]) => `${x},${y}`).join(' ')
            return (
              <g key={index}>
                {/* Keep each backend leg separate, including gaps in validated geometry. */}
                <polyline points={points} className="route-underlay" />
                <polyline points={points} className="route" />
                {handoffs.map(({ point, label }) => (
                  <g key={label} className="handoff" transform={`translate(${point[0]} ${point[1]})`}>
                    <circle r={1.15} />
                    <title>{label}</title>
                  </g>
                ))}
              </g>
            )
          })}
          {firstLeg && firstLeg.floor_id === plan.floor.id && firstLeg.points.length > 0 && (
            <g><circle className="start" cx={firstLeg.points[0][0]} cy={firstLeg.points[0][1]} r={0.55}><title>Route start</title></circle><g transform={`translate(${firstLeg.points[0][0]} ${firstLeg.points[0][1]}) scale(1 -1)`}><text className="route-endpoint-label" textAnchor="middle" dominantBaseline="central" fontSize={0.6}>A</text></g></g>
          )}
          {lastLeg && lastLeg.floor_id === plan.floor.id && lastLeg.points.length > 0 && (
            <g><circle className="destination" cx={lastLeg.points.at(-1)![0]} cy={lastLeg.points.at(-1)![1]} r={0.55}><title>Route destination</title></circle><g transform={`translate(${lastLeg.points.at(-1)![0]} ${lastLeg.points.at(-1)![1]}) scale(1 -1)`}><text className="route-endpoint-label" textAnchor="middle" dominantBaseline="central" fontSize={0.6}>B</text></g></g>
          )}
          {stepPoint && <circle className="step-marker" cx={stepPoint[0]} cy={stepPoint[1]} r={1.05} />}
          {mockPoint && <circle className="mock-marker" cx={mockPoint[0]} cy={mockPoint[1]} r={1.3} />}
        </g>
      </svg>
      {simulation && <WalkPad svgRef={svgRef} plan={plan} route={route} closedIds={closedIds} stepFree={stepFree} />}
      {hovered && <div className="map-tooltip" role="status" style={{ left: hoverPosition.x, top: hoverPosition.y }}><strong>{hovered.name}</strong><dl><dt>Type</dt><dd>{hovered.kind === 'space' ? 'Room / area' : hovered.kind === 'asset' ? 'Equipment / item' : 'Opening / connector'}</dd><dt>Floor</dt><dd>{hovered.floorName}</dd><dt>Details</dt><dd>{hovered.note || 'No additional details'}</dd></dl></div>}
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
        {route?.reachable && <button type="button" aria-label="Fit route" onClick={() => { setFitRoute(true); resetView() }}>Route</button>}
        <button type="button" aria-label="Fit floor" onClick={() => { setFitRoute(false); resetView() }}>Floor</button>
      </div>
      <details className="map-display-mode"><summary>Details</summary><div role="group" aria-label="Map detail level"><button type="button" aria-pressed={displayMode === 'labels'} onClick={() => setDisplayMode('labels')}>Rooms</button><button type="button" aria-pressed={displayMode === 'items'} onClick={() => setDisplayMode('items')}>Rooms + items</button><button type="button" aria-pressed={displayMode === 'rooms'} onClick={() => setDisplayMode('rooms')}>Rooms + numbers</button></div></details>
      </div>
          </div>
  )
}






