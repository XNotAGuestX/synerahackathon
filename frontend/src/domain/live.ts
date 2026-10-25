import type { FloorPlan, PendingAction, Point, Reply, Selection, Space, ViewEffect } from './types'

export type WayfindingRole = 'stair' | 'lift' | 'escape'

const STAIR_TYPES = new Set(['stair', 'stairs', 'stairwell', 'staircase'])
const LIFT_TYPES = new Set(['lift', 'elevator'])
const ESCAPE_TYPES = new Set(['emergency-exit', 'emergency-corridor', 'escape', 'escape-route', 'fire-exit'])

function typeTokens(space: Pick<Space, 'type' | 'room_type'>): string[] {
  return [space.type, space.room_type]
    .map((value) => (value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-'))
    .filter(Boolean)
}

/** Stair, lift, or a space whose own type is an escape route. Exit corridors are separate. */
export function wayfindingRole(space: Pick<Space, 'type' | 'room_type'>): WayfindingRole | null {
  const tokens = typeTokens(space)
  if (tokens.some((token) => LIFT_TYPES.has(token))) return 'lift'
  if (tokens.some((token) => STAIR_TYPES.has(token))) return 'stair'
  if (tokens.some((token) => ESCAPE_TYPES.has(token))) return 'escape'
  return null
}

function isExitCirculation(space: Pick<Space, 'type' | 'room_type'>): boolean {
  const type = (space.type || '').toLowerCase()
  const room = (space.room_type || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
  return type === 'corridor' || room === 'corridor' || room === 'hallway' || room === 'lobby'
}

/** Corridors and lobbies that open directly outside. Stairs and lifts keep their own colour. */
export function escapeSpaceIds(plan: FloorPlan): Set<string> {
  const byId = new Map(plan.spaces.map((space) => [space.id, space]))
  const ids = new Set<string>()
  for (const opening of plan.openings) {
    if (opening.kind !== 'entrance') continue
    for (const spaceId of opening.space_ids) {
      const space = byId.get(spaceId)
      if (!space || wayfindingRole(space) || !isExitCirculation(space)) continue
      ids.add(space.id)
    }
  }
  return ids
}

export function labelFromPlans(plans: FloorPlan[], id: string | null): string {
  if (!id) return 'Not resolved'
  for (const plan of plans) {
    const space = plan.spaces.find((item) => item.id === id)
    if (space) return space.name
    const asset = plan.assets.find((item) => item.id === id)
    if (asset) return asset.name
    const connector = plan.connectors.find((item) => item.id === id)
    if (connector) return connector.name
    const opening = plan.openings.find((item) => item.id === id)
    if (opening) return `${opening.kind}, ${opening.width_m} m`
  }
  return id
}

export function connectorNoteFromPlan(plan: FloorPlan, spaceId: string): string | null {
  const connector = plan.connectors.find((item) => item.space_ids.includes(spaceId))
  return connector ? `${connector.name} · ${connector.kind}` : null
}

export function closureHighlights(plans: FloorPlan[], elementId: string | undefined): ViewEffect[] {
  if (!elementId) return []
  const spaceIds = new Set<string>()
  for (const plan of plans) {
    const connector = plan.connectors.find((item) => item.id === elementId)
    if (connector) connector.space_ids.forEach((id) => spaceIds.add(id))
    const opening = plan.openings.find((item) => item.id === elementId)
    if (opening) opening.space_ids.forEach((id) => spaceIds.add(id))
    if (plan.spaces.some((item) => item.id === elementId)) spaceIds.add(elementId)
  }
  if (spaceIds.size === 0) return []
  return [{ type: 'highlight_spaces', space_ids: [...spaceIds], reason: 'closed' }]
}

export function distance(left: Point, right: Point): number {
  return Math.hypot(left[0] - right[0], left[1] - right[1])
}

/** Assets close to the current step that are not repeated inside the outer radius. */
export function landmarkIds(plan: FloorPlan, point: Point | null, inner = 4, outer = 12): string[] {
  if (!point) return []
  const near = plan.assets.filter((asset) => distance(asset.position, point) <= inner)
  return near
    .filter((asset) => plan.assets.filter((other) => other.type === asset.type && distance(other.position, point) <= outer).length <= 2)
    .map((asset) => asset.id)
}

export function selectionFacts(plan: FloorPlan, selection: Selection): { position: string; width: string | null; stepFree: string | null } {
  if (selection.kind === 'asset') {
    const asset = plan.assets.find((item) => item.id === selection.id)
    return { position: asset ? formatPoint(asset.position) : 'None', width: null, stepFree: null }
  }
  if (selection.kind === 'opening') {
    const opening = plan.openings.find((item) => item.id === selection.id)
    return {
      position: opening ? formatPoint(opening.position) : 'None',
      width: opening ? `${opening.width_m} m` : null,
      stepFree: opening ? (opening.step_free ? 'Step-free' : 'Has a step') : null,
    }
  }
  const space = plan.spaces.find((item) => item.id === selection.id)
  return { position: space ? formatPoint(centroid(space.polygon)) : 'None', width: null, stepFree: null }
}

export function pendingReply(action: { id: string; summary: string; status?: string; proposal?: PendingAction['proposal'] }, highlights: ViewEffect[]): Reply {
  return {
    id: 'pending',
    userText: null,
    guideText: action.summary,
    understood: null,
    effects: highlights,
    routes: [],
    pending: {
      id: action.id,
      status: action.status ?? 'pending',
      summary: action.summary,
      proposal: action.proposal ?? { kind: 'set_closed' },
    },
  }
}

function formatPoint(point: Point): string {
  return `${point[0].toFixed(2)}, ${point[1].toFixed(2)}`
}

function centroid(polygon: Point[]): Point {
  if (polygon.length === 0) return [0, 0]
  const total = polygon.reduce(([x, y], [px, py]) => [x + px, y + py], [0, 0])
  return [total[0] / polygon.length, total[1] / polygon.length]
}
