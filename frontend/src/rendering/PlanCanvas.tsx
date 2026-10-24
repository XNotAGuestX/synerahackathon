import type { FloorPlan, Point, Route, Selection } from '../domain/types'
import type { Connector } from '../domain/types'
import { connectorNote } from '../api/fixtures'

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

export function PlanCanvas({
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
}: PlanCanvasProps) {
  if (!plan) {
    return (
      <div className="plan-wrap plan-empty" role="status" data-floor="missing">
        <strong>{floorName}</strong>
        <p>No plan fixture for this floor.</p>
      </div>
    )
  }

  const reasons = new Map(spaceReasons)
  if (route?.start_space_id && !reasons.has(route.start_space_id)) reasons.set(route.start_space_id, 'selected')
  if (route?.destination_space_id && !reasons.has(route.destination_space_id)) reasons.set(route.destination_space_id, 'selected')
  for (const spaceId of closedSpaceIds(closedIds, plan.connectors)) {
    if (reasons.get(spaceId) !== 'preview') reasons.set(spaceId, 'closed')
  }

  const [minX, minY] = plan.bounds.min
  const [maxX, maxY] = plan.bounds.max
  const pad = 1.2
  // Building coordinates are metres with y up. SVG y grows down, so the plan
  // group is flipped and the viewBox origin sits at the top of the plan.
  const viewBox = `${minX - pad} ${-(maxY + pad)} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`
  const legs = route?.reachable ? route.legs.filter((leg) => leg.floor_id === plan.floor.id && leg.points.length > 1) : []
  const firstLeg = route?.legs[0]
  const lastLeg = route?.legs.at(-1)

  const selectSpace = (space: FloorPlan['spaces'][number]) => {
    onSelect({
      kind: 'space',
      id: space.id,
      name: space.name,
      floorId: plan.floor.id,
      floorName: plan.floor.name,
      note: connectorNote(space.id),
    })
  }

  return (
    <div className="plan-wrap" aria-label={`${floorName} plan`} data-floor={plan.floor.id}>
      <svg className="plan" viewBox={viewBox}>
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
            const highlighted = assetIds.has(asset.id)
            const picked = selectionId === asset.id
            const { width_m: width, depth_m: depth, rotation_deg: rotation } = asset.footprint
            return (
              <g
                key={asset.id}
                transform={`translate(${asset.position[0]} ${asset.position[1]}) rotate(${rotation})`}
                className={['asset', asset.category, highlighted ? 'highlighted' : '', picked ? 'picked' : ''].filter(Boolean).join(' ')}
                role="button"
                tabIndex={highlighted ? 0 : -1}
                aria-label={asset.name}
                aria-pressed={picked}
                onClick={(event) => {
                  event.stopPropagation()
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
                <circle r={Math.max(0.55, Math.hypot(width, depth) / 2)} className="asset-hit" />
              </g>
            )
          })}
          {legs.map((leg) => (
            <polyline key={`${leg.floor_id}-${leg.points.length}`} points={leg.points.map(([x, y]) => `${x},${y}`).join(' ')} className="route" />
          ))}
          {firstLeg && firstLeg.floor_id === plan.floor.id && firstLeg.points.length > 0 && (
            <circle className="start" cx={firstLeg.points[0][0]} cy={firstLeg.points[0][1]} r={0.72} />
          )}
          {lastLeg && lastLeg.floor_id === plan.floor.id && lastLeg.points.length > 0 && (
            <circle className="destination" cx={lastLeg.points.at(-1)![0]} cy={lastLeg.points.at(-1)![1]} r={0.9} />
          )}
          {focusPoint && <circle className="focus-ring" cx={focusPoint[0]} cy={focusPoint[1]} r={1.15} />}
          {stepPoint && <circle className="step-marker" cx={stepPoint[0]} cy={stepPoint[1]} r={1.05} />}
        </g>
      </svg>
    </div>
  )
}
