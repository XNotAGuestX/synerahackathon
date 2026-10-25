import type { FloorPlan, Reply, Route } from './types'

export type SharedRoute = {
  building_id: string
  start_space_id: string
  destination_space_id: string
  step_free: boolean
  via: string[]
  closed_ids: string[]
  travel_mode: 'walking' | 'forklift'
  min_width_m: number
}

function reference(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= 200
}

function references(value: unknown, limit: number): value is string[] {
  return Array.isArray(value) && value.length <= limit && value.every(reference)
}

export function readRouteLink(hash: string): { route: SharedRoute | null; error: string | null } {
  const encoded = new URLSearchParams(hash.replace(/^#/, '')).get('route')
  if (encoded === null) return { route: null, error: null }
  try {
    if (encoded.length > 16000) throw new Error()
    const value = JSON.parse(encoded) as SharedRoute
    if (!value || typeof value.building_id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value.building_id)
      || !reference(value.start_space_id) || !reference(value.destination_space_id)
      || typeof value.step_free !== 'boolean' || !references(value.via, 8) || !references(value.closed_ids, 100)
      || !['walking', 'forklift'].includes(value.travel_mode)
      || typeof value.min_width_m !== 'number' || !Number.isFinite(value.min_width_m) || value.min_width_m < 0) throw new Error()
    return { route: value, error: null }
  } catch {
    return { route: null, error: 'This route link is invalid. Ask the sender to share it again.' }
  }
}

export function createRouteLink(href: string, buildingId: string, route: Route): string | null {
  if (!route.reachable || !route.start_space_id || !route.destination_space_id) return null
  const shared: SharedRoute = {
    building_id: buildingId, start_space_id: route.start_space_id, destination_space_id: route.destination_space_id,
    step_free: route.step_free, via: route.via, closed_ids: route.closed_ids,
    travel_mode: route.travel_mode ?? 'walking', min_width_m: route.min_width_m ?? 0,
  }
  const url = new URL(href)
  url.hash = new URLSearchParams({ route: JSON.stringify(shared) }).toString()
  return readRouteLink(url.hash).route ? url.href : null
}

export function sharedRouteReply(route: Route, plans: FloorPlan[]): Reply {
  const spaces = plans.flatMap((plan) => plan.spaces)
  const name = (id: string | null) => spaces.find((space) => space.id === id)?.name ?? id ?? ''
  const firstLeg = route.legs[0]
  return {
    id: route.reachable ? 'accepted' : 'unreachable', userText: null,
    guideText: route.reachable ? 'Shared route ready. Follow the tape on the plan.' : 'This shared route is no longer reachable with its constraints.',
    understood: {
      intent: 'route', summary: `${name(route.start_space_id)} to ${name(route.destination_space_id)}`,
      constraints: { step_free: route.step_free, travel_mode: route.travel_mode, via: route.via, closed_ids: route.closed_ids },
      resolved: { start_space_id: route.start_space_id, destination_space_id: route.destination_space_id,
        space_ids: [route.start_space_id, route.destination_space_id].filter((id): id is string => Boolean(id)), asset_ids: [], count: null },
      missing: [],
    },
    effects: [
      { type: 'draw_route', route_id: route.id },
      { type: 'set_closures', closed_ids: route.closed_ids },
      ...(firstLeg ? [{ type: 'focus', floor_id: firstLeg.floor_id, floor_level: firstLeg.floor_level, point: firstLeg.points[0] }] : []),
    ],
    routes: [route], pending: null,
  }
}
