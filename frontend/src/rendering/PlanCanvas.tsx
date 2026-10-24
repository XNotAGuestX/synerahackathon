import { useEffect, useRef, useState } from 'react'
import type { FloorPlan, Point, Route, Selection } from '../domain/types'
import type { Connector } from '../domain/types'
import { connectorNoteFromPlan, landmarkIds } from '../domain/live'

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
}: PlanCanvasProps & { plan: FloorPlan }) {
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>([0, 0])
  const gesture = useRef({ pointerId: -1, x: 0, y: 0, panX: 0, panY: 0, moved: false })
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinch = useRef<{ startDistance: number; startZoom: number; anchorX: number; anchorY: number } | null>(null)
  const suppressClick = useRef(false)
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
  const legs = route?.reachable ? route.legs.filter((leg) => leg.floor_id === plan.floor.id && leg.points.length > 1) : []
  const firstLeg = route?.legs[0]
  const lastLeg = route?.legs.at(-1)
  const focusedSpaceId = focusPoint ? plan.spaces.find((space) => containsPoint(space.polygon, focusPoint))?.id ?? null : null
  if (focusedSpaceId && !reasons.has(focusedSpaceId)) reasons.set(focusedSpaceId, 'selected')

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
    <div className="plan-wrap" aria-label={`${floorName} plan`} data-floor={plan.floor.id}>
      <svg
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
            const picked = selectionId === space.id
            const [cx, cy] = centroid(space.polygon)
            const showLabel = polygonArea(space.polygon) >= 28
            return (
              <g key={space.id}>
                <polygon
                  points={space.polygon.map(([x, y]) => `${x},${y}`).join(' ')}
                  className={['space', reason ? `reason-${reason}` : '', picked ? 'picked' : ''].filter(Boolean).join(' ')}
                  role="button"
                  tabIndex={0}
                  aria-label={space.name}
                  aria-pressed={picked}
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
          {plan.assets.map((asset) => {
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
          {legs.map((leg) => {
            const told = route?.directions[storyIndex]
            const revealed = told?.floor_id === plan.floor.id ? prefixTo(leg.points, told.at) : leg.points
            const laterFloor = route?.directions.slice(storyIndex + 1).find((direction) => direction.floor_id !== plan.floor.id)
            const handoff = laterFloor && revealed.length > 0 ? revealed.at(-1)! : null
            const connector = handoff
              ? plan.connectors.find((item) => item.space_ids.some((spaceId) => {
                const space = plan.spaces.find((candidate) => candidate.id === spaceId)
                return space ? containsPoint(space.polygon, handoff) : false
              }))
              : null
            return (
              <g key={`${leg.floor_id}-${leg.points.length}`}>
                <polyline points={revealed.map(([x, y]) => `${x},${y}`).join(' ')} className="route" />
                {handoff && (
                  <g className="handoff" transform={`translate(${handoff[0]} ${handoff[1]})`}>
                    <circle r={1.15} />
                    <title>{connector?.name ?? 'Change floor'}</title>
                  </g>
                )}
              </g>
            )
          })}
          {firstLeg && firstLeg.floor_id === plan.floor.id && firstLeg.points.length > 0 && (
            <circle className="start" cx={firstLeg.points[0][0]} cy={firstLeg.points[0][1]} r={0.72} />
          )}
          {lastLeg && lastLeg.floor_id === plan.floor.id && lastLeg.points.length > 0 && (
            <circle className="destination" cx={lastLeg.points.at(-1)![0]} cy={lastLeg.points.at(-1)![1]} r={0.9} />
          )}
          {stepPoint && <circle className="step-marker" cx={stepPoint[0]} cy={stepPoint[1]} r={1.05} />}
          {mockPoint && <circle className="mock-marker" cx={mockPoint[0]} cy={mockPoint[1]} r={1.3} />}
        </g>
      </svg>
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
        <button type="button" aria-label="Zoom out" onClick={() => setZoomAroundCenter(zoom / 1.25)} disabled={zoom <= MIN_ZOOM}>−</button>
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label="Zoom in" onClick={() => setZoomAroundCenter(zoom * 1.25)} disabled={zoom >= MAX_ZOOM}>+</button>
        <button type="button" aria-label="Reset map to 100 percent" onClick={resetView}>Reset</button>
      </div>
    </div>
  )
}
