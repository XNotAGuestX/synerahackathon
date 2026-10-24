import type { FloorPlan, Opening, Point, Route } from './types'

/** Shoulder radius. Fits the narrowest sampled door (0.54 m) with 0.04 m spare. */
export const BODY_RADIUS_M = 0.16
/** Stick-figure width in metres. Screen size is this times the current map scale. */
export const FIGURE_WIDTH_M = 1.5
export const FIGURE_HEIGHT_M = FIGURE_WIDTH_M * (64 / 48)
/** Openings sit up to 0.91 m off the nearest listed edge in the sampled plans. */
export const OPENING_SNAP_M = 1.05
export const MIN_PASS_WIDTH_M = BODY_RADIUS_M * 2 + 0.04
export const WALK_SPEED_M_S = 1.35
export const ARRIVE_RADIUS_M = 0.6

const SUBSTEP_M = 0.05
const EPS = 1e-4

export type BlockCause = 'wall' | 'closed-door' | 'step' | 'narrow' | 'equipment' | 'outside'

type Edge = { a: Point; b: Point; spaceId: string; length: number }
type Mark = { start: number; end: number; kind: 'gap' | BlockCause }
type Segment = { a: Point; b: Point; cause: BlockCause }
type Portal = { a: Point; b: Point; halfClear: number }
type Solid = { center: Point; width: number; depth: number; rotationRad: number }

export type WalkField = {
  spaces: Point[][]
  blocking: Segment[]
  portals: Portal[]
  solids: Solid[]
}

export type Travel = { point: Point; cause: BlockCause | null; reached: boolean }

export type WalkerMarks = {
  origin: Point | null
  destination: Point | null
  leg: Point[]
}

type Projection = { edge: Edge; distance: number; metres: number; at: Point }

function edgesOf(spaces: FloorPlan['spaces']): Edge[] {
  const edges: Edge[] = []
  for (const space of spaces) {
    const polygon = space.polygon
    for (let index = 0; index < polygon.length; index += 1) {
      const a = polygon[index]
      const b = polygon[(index + 1) % polygon.length]
      const length = Math.hypot(b[0] - a[0], b[1] - a[1])
      if (length < EPS) continue
      edges.push({ a, b, spaceId: space.id, length })
    }
  }
  return edges
}

function nearestEdge(edges: Edge[], point: Point, spaceId: string): Projection | null {
  let best: Projection | null = null
  for (const edge of edges) {
    if (edge.spaceId !== spaceId) continue
    const dx = edge.b[0] - edge.a[0]
    const dy = edge.b[1] - edge.a[1]
    const raw = ((point[0] - edge.a[0]) * dx + (point[1] - edge.a[1]) * dy) / (edge.length * edge.length)
    const u = Math.min(1, Math.max(0, raw))
    const at: Point = [edge.a[0] + dx * u, edge.a[1] + dy * u]
    const distance = Math.hypot(point[0] - at[0], point[1] - at[1])
    if (!best || distance < best.distance) best = { edge, distance, metres: u * edge.length, at }
  }
  return best
}

function pointOnEdge(edge: Edge, metres: number): Point {
  const u = metres / edge.length
  return [edge.a[0] + (edge.b[0] - edge.a[0]) * u, edge.a[1] + (edge.b[1] - edge.a[1]) * u]
}

function clipInterval(center: number, half: number, length: number): [number, number] | null {
  const start = Math.max(0, center - half)
  const end = Math.min(length, center + half)
  if (end - start < EPS) return null
  return [start, end]
}

function openingKind(opening: Opening, closed: Set<string>, stepFree: boolean): 'pass' | BlockCause {
  const interior = opening.space_ids.filter((id) => id !== 'outside')
  if (closed.has(opening.id) || interior.some((id) => closed.has(id))) return 'closed-door'
  if (stepFree && !opening.step_free) return 'step'
  if (!Number.isFinite(opening.width_m) || opening.width_m < MIN_PASS_WIDTH_M) return 'narrow'
  return 'pass'
}

function blockingFromEdge(edge: Edge, marks: Mark[]): Segment[] {
  const cuts = [0, edge.length]
  for (const mark of marks) cuts.push(mark.start, mark.end)
  cuts.sort((left, right) => left - right)
  const unique = cuts.filter((value, index) => index === 0 || value - cuts[index - 1] > EPS)
  const segments: Segment[] = []
  for (let index = 0; index < unique.length - 1; index += 1) {
    const start = unique[index]
    const end = unique[index + 1]
    const mid = (start + end) / 2
    const covering = marks.filter((mark) => mid >= mark.start - EPS && mid <= mark.end + EPS)
    if (covering.some((mark) => mark.kind === 'gap')) continue
    const seal = covering.find((mark) => mark.kind !== 'gap')
    const cause: BlockCause = seal && seal.kind !== 'gap' ? seal.kind : 'wall'
    segments.push({
      a: pointOnEdge(edge, start),
      b: pointOnEdge(edge, end),
      cause,
    })
  }
  return segments
}

function isCcw(polygon: Point[]): boolean {
  let sum = 0
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index]
    const [x2, y2] = polygon[(index + 1) % polygon.length]
    sum += x1 * y2 - x2 * y1
  }
  return sum > 0
}

function inwardNormal(edge: Edge, ccw: boolean): Point {
  const dx = (edge.b[0] - edge.a[0]) / edge.length
  const dy = (edge.b[1] - edge.a[1]) / edge.length
  return ccw ? [-dy, dx] : [dy, -dx]
}

function containsPoint(polygon: Point[], point: Point): boolean {
  let inside = false
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index, index += 1) {
    const [x, y] = polygon[index]
    const [previousX, previousY] = polygon[previous]
    const intersects = ((y > point[1]) !== (previousY > point[1]))
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x
    if (intersects) inside = !inside
  }
  return inside
}

function distanceToSegment(point: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const len2 = dx * dx + dy * dy
  if (len2 < EPS) return Math.hypot(point[0] - a[0], point[1] - a[1])
  const u = Math.min(1, Math.max(0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / len2))
  return Math.hypot(point[0] - (a[0] + dx * u), point[1] - (a[1] + dy * u))
}

function hitsSolid(point: Point, solid: Solid): boolean {
  const dx = point[0] - solid.center[0]
  const dy = point[1] - solid.center[1]
  const cos = Math.cos(-solid.rotationRad)
  const sin = Math.sin(-solid.rotationRad)
  const localX = dx * cos - dy * sin
  const localY = dx * sin + dy * cos
  const halfW = solid.width / 2
  const halfD = solid.depth / 2
  const clampX = Math.min(halfW, Math.max(-halfW, localX))
  const clampY = Math.min(halfD, Math.max(-halfD, localY))
  return Math.hypot(localX - clampX, localY - clampY) < BODY_RADIUS_M - EPS
}

function rangesOverlap(a1: number, a2: number, b1: number, b2: number): boolean {
  return Math.max(a1, a2) >= Math.min(b1, b2) - 1e-6 && Math.max(b1, b2) >= Math.min(a1, a2) - 1e-6
}

function intersectionT(a: Point, b: Point, c: Point, d: Point): number | null {
  const rx = b[0] - a[0]
  const ry = b[1] - a[1]
  const sx = d[0] - c[0]
  const sy = d[1] - c[1]
  const denom = rx * sy - ry * sx
  const qpx = c[0] - a[0]
  const qpy = c[1] - a[1]
  if (Math.abs(denom) < 1e-9) {
    if (Math.abs(qpx * ry - qpy * rx) > 1e-6) return null
    if (!rangesOverlap(a[0], b[0], c[0], d[0]) || !rangesOverlap(a[1], b[1], c[1], d[1])) return null
    return 0
  }
  const t = (qpx * sy - qpy * sx) / denom
  const u = (qpx * ry - qpy * rx) / denom
  if (t < -1e-6 || t > 1 + 1e-6 || u < -1e-6 || u > 1 + 1e-6) return null
  return Math.min(1, Math.max(0, t))
}

function firstHit(field: WalkField, from: Point, to: Point): BlockCause | null {
  let bestT = Infinity
  let cause: BlockCause | null = null
  for (const segment of field.blocking) {
    const t = intersectionT(from, to, segment.a, segment.b)
    if (t != null && t < bestT) {
      bestT = t
      cause = segment.cause
    }
  }
  return cause
}

export function buildWalkField(plan: FloorPlan, closedIds: readonly string[], stepFree: boolean): WalkField {
  const closed = new Set(closedIds)
  const edges = edgesOf(plan.spaces)
  const marks = new Map<Edge, Mark[]>()
  const portals: Portal[] = []
  for (const opening of plan.openings) {
    if (opening.floor_id !== plan.floor.id) continue
    const kind = openingKind(opening, closed, stepFree)
    const interior = opening.space_ids.filter((id) => id !== 'outside' && plan.spaces.some((space) => space.id === id))
    const projections: Projection[] = []
    for (const spaceId of interior) {
      const nearest = nearestEdge(edges, opening.position, spaceId)
      if (!nearest || nearest.distance > OPENING_SNAP_M) continue
      projections.push(nearest)
      const interval = clipInterval(nearest.metres, opening.width_m / 2, nearest.edge.length)
      if (!interval) continue
      const list = marks.get(nearest.edge) ?? []
      list.push({ start: interval[0], end: interval[1], kind: kind === 'pass' ? 'gap' : kind })
      marks.set(nearest.edge, list)
    }
    if (kind === 'pass' && projections.length >= 2) {
      const halfClear = opening.width_m / 2 - BODY_RADIUS_M
      if (halfClear > 0) {
        portals.push({ a: projections[0].at, b: opening.position, halfClear })
        portals.push({ a: opening.position, b: projections[1].at, halfClear })
      }
    }
  }
  const blocking = edges.flatMap((edge) => blockingFromEdge(edge, marks.get(edge) ?? []))
  const spaces = plan.spaces.filter((space) => !closed.has(space.id)).map((space) => space.polygon)
  const solids = plan.assets
    .filter((asset) => asset.floor_id === plan.floor.id)
    .map((asset) => ({
      center: asset.position,
      width: Math.max(asset.footprint.width_m, 0.35),
      depth: Math.max(asset.footprint.depth_m, 0.35),
      rotationRad: (asset.footprint.rotation_deg * Math.PI) / 180,
    }))
  return { spaces, blocking, portals, solids }
}

export function standCause(field: WalkField, point: Point): BlockCause | null {
  for (const solid of field.solids) {
    if (hitsSolid(point, solid)) return 'equipment'
  }
  let nearest = Infinity
  let cause: BlockCause = 'wall'
  for (const segment of field.blocking) {
    const distance = distanceToSegment(point, segment.a, segment.b)
    if (distance < nearest) {
      nearest = distance
      cause = segment.cause
    }
  }
  if (nearest < BODY_RADIUS_M - EPS) return cause
  if (field.spaces.some((polygon) => containsPoint(polygon, point))) return null
  for (const portal of field.portals) {
    if (distanceToSegment(point, portal.a, portal.b) <= portal.halfClear + EPS) return null
  }
  return 'outside'
}

export function nearestStand(field: WalkField, point: Point): Point | null {
  if (!standCause(field, point)) return point
  for (const radius of [0.2, 0.45, 0.8, 1.2, 1.8, 2.6]) {
    for (let step = 0; step < 16; step += 1) {
      const angle = (Math.PI * 2 * step) / 16
      const candidate: Point = [point[0] + Math.cos(angle) * radius, point[1] + Math.sin(angle) * radius]
      if (!standCause(field, candidate)) return candidate
    }
  }
  return null
}

function travel(field: WalkField, from: Point, delta: Point): Travel {
  const distance = Math.hypot(delta[0], delta[1])
  if (distance < EPS) return { point: from, cause: null, reached: true }
  const steps = Math.ceil(distance / SUBSTEP_M)
  let cursor = from
  let cause: BlockCause | null = null
  for (let step = 1; step <= steps; step += 1) {
    const t = step / steps
    const next: Point = [from[0] + delta[0] * t, from[1] + delta[1] * t]
    const crossed = firstHit(field, cursor, next)
    const stood = standCause(field, next)
    if (crossed || stood) {
      cause = crossed ?? stood
      break
    }
    cursor = next
  }
  const reached = !cause && Math.hypot(cursor[0] - (from[0] + delta[0]), cursor[1] - (from[1] + delta[1])) < EPS
  return { point: cursor, cause, reached }
}

export function moveWalker(field: WalkField, from: Point, delta: Point): Travel {
  const direct = travel(field, from, delta)
  if (direct.reached) return direct
  const alongX = travel(field, from, [delta[0], 0])
  const alongY = travel(field, from, [0, delta[1]])
  const candidates = [direct, alongX, alongY]
  let best = direct
  let bestMoved = -1
  for (const candidate of candidates) {
    const moved = Math.hypot(candidate.point[0] - from[0], candidate.point[1] - from[1])
    if (moved > bestMoved + EPS) {
      best = candidate
      bestMoved = moved
    }
  }
  if (bestMoved <= EPS) return { point: from, cause: direct.cause ?? 'wall', reached: false }
  return { point: best.point, cause: null, reached: best.reached }
}

function entranceInset(plan: FloorPlan, opening: Opening, edges: Edge[]): Point | null {
  const spaceId = opening.space_ids.find((id) => id !== 'outside')
  if (!spaceId) return null
  const space = plan.spaces.find((item) => item.id === spaceId)
  const nearest = nearestEdge(edges, opening.position, spaceId)
  if (!space || !nearest || nearest.distance > OPENING_SNAP_M) return null
  const normal = inwardNormal(nearest.edge, isCcw(space.polygon))
  return [nearest.at[0] + normal[0] * (BODY_RADIUS_M + 0.12), nearest.at[1] + normal[1] * (BODY_RADIUS_M + 0.12)]
}

export function routeMarks(plan: FloorPlan, route: Route | null): WalkerMarks {
  const empty: WalkerMarks = { origin: null, destination: null, leg: [] }
  if (!route?.reachable) return empty
  const legs = route.legs.filter((leg) => leg.floor_id === plan.floor.id && leg.points.length > 0)
  if (legs.length === 0) return empty
  const startHere = route.start_space_id != null && plan.spaces.some((space) => space.id === route.start_space_id)
  const destHere = route.destination_space_id != null && plan.spaces.some((space) => space.id === route.destination_space_id)
  return {
    origin: startHere ? legs[0].points[0] : null,
    destination: destHere ? legs[legs.length - 1].points.at(-1) ?? null : null,
    leg: legs.flatMap((leg) => leg.points),
  }
}

export function spawnPoint(plan: FloorPlan, field: WalkField, route: Route | null): Point | null {
  const marks = routeMarks(plan, route)
  const edges = edgesOf(plan.spaces)
  const candidates: Point[] = []
  if (marks.origin) candidates.push(marks.origin)
  else if (marks.leg[0]) candidates.push(marks.leg[0])
  const entrance = plan.openings.find((opening) => opening.kind === 'entrance')
  if (entrance) {
    const inset = entranceInset(plan, entrance, edges)
    if (inset) candidates.push(inset)
  }
  const largest = plan.spaces
    .filter((space) => field.spaces.includes(space.polygon))
    .sort((left, right) => polygonArea(right.polygon) - polygonArea(left.polygon))[0]
  if (largest) candidates.push(centroid(largest.polygon))
  for (const candidate of candidates) {
    const stood = nearestStand(field, candidate)
    if (stood) return stood
  }
  return null
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
  const total = polygon.reduce<[number, number]>(([x, y], [px, py]) => [x + px, y + py], [0, 0])
  return [total[0] / polygon.length, total[1] / polygon.length]
}

export function arcLength(points: Point[]): number {
  let total = 0
  for (let index = 1; index < points.length; index += 1) {
    total += Math.hypot(points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
  }
  return total
}

export function pointAtArc(points: Point[], arc: number): Point {
  if (points.length === 0) return [0, 0]
  if (arc <= 0 || points.length === 1) return points[0]
  let remaining = arc
  for (let index = 1; index < points.length; index += 1) {
    const dx = points[index][0] - points[index - 1][0]
    const dy = points[index][1] - points[index - 1][1]
    const length = Math.hypot(dx, dy)
    if (remaining <= length || index === points.length - 1) {
      const t = length < EPS ? 0 : Math.min(1, remaining / length)
      return [points[index - 1][0] + dx * t, points[index - 1][1] + dy * t]
    }
    remaining -= length
  }
  return points[points.length - 1]
}

export function closestArc(points: Point[], from: Point): number {
  if (points.length < 2) return 0
  let best = 0
  let bestDistance = Infinity
  let traveled = 0
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1]
    const b = points[index]
    const dx = b[0] - a[0]
    const dy = b[1] - a[1]
    const len2 = dx * dx + dy * dy
    const length = Math.sqrt(len2)
    const u = len2 < EPS ? 0 : Math.min(1, Math.max(0, ((from[0] - a[0]) * dx + (from[1] - a[1]) * dy) / len2))
    const distance = Math.hypot(from[0] - (a[0] + dx * u), from[1] - (a[1] + dy * u))
    if (distance < bestDistance) {
      bestDistance = distance
      best = traveled + length * u
    }
    traveled += length
  }
  return best
}
