import type { FloorPlan, PendingAction, Point, Reply, Selection, ViewEffect } from './types'

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
