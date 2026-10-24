import { catalog, labelFor, planFor } from './fixtures'
import { currentLocation, interpretMessage } from './interpret'
import { ApiError } from './errors'
import type { FloorPlan, FloorSummary, Reply, ReplyId, Route } from '../domain/types'

export type InputMode = 'text' | 'transcript'

export type DataMode = 'fixture' | 'http'
export type GatewayConfig = { mode: DataMode; baseUrl: string }
export type BuildingSummary = { id: string; name: string; floors: number; has_lift: boolean; has_step_free_entrance: boolean }
export type Session = { id: string; building_id: string; building_name: string; revision: number; preferences: { step_free: boolean }; closed_ids?: string[]; last_route_id?: string | null; pending_action_id?: string | null }
export type Place = { id: string; kind: string; name: string; floor_id: string; floor_level: number; space_id: string | null; position: [number, number] | null }
export type RouteRequest = { start_space_id: string; destination_space_id: string; step_free?: boolean; via?: string[] }
export type ActionResult = { summary: string; closed_ids: string[]; id?: string; status?: string; proposal?: { kind: string; element_ref?: string; closed?: boolean } }
function requestId(): string {
  const browserCrypto = globalThis.crypto
  if (typeof browserCrypto?.randomUUID === 'function') return browserCrypto.randomUUID()
  if (typeof browserCrypto?.getRandomValues === 'function') {
    const bytes = browserCrypto.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
    const value = Math.random() * 16 | 0
    const replacement = character === 'x' ? value : (value & 0x3) | 0x8
    return replacement.toString(16)
  })
}
export interface BuildingGateway {
  readonly mode: DataMode
  listBuildings(): Promise<BuildingSummary[]>
  createSession(buildingId: string): Promise<Session>
  getSession(sessionId: string): Promise<Session>
  listFloors(sessionId: string): Promise<FloorSummary[]>
  getFloorPlan(sessionId: string, floorId: string): Promise<FloorPlan>
  searchPlaces(sessionId: string, query: string, page?: number): Promise<{ items: Place[]; total: number }>
  createRoute(sessionId: string, input: RouteRequest): Promise<Route>
  getRoute(sessionId: string, routeId: string): Promise<Route>
  updatePreferences(sessionId: string, preferences: { step_free: boolean }): Promise<Session>
  sendMessage(sessionId: string, text: string, inputMode?: InputMode): Promise<Reply>
  confirmAction(sessionId: string, actionId: string): Promise<ActionResult>
  cancelAction(sessionId: string, actionId: string): Promise<ActionResult>
  getAction(sessionId: string, actionId: string): Promise<ActionResult & { id: string; status: string }>
}

const fixtureBuilding: BuildingSummary = { id: 'proc-factory-dev-003', name: catalog.buildingName, floors: catalog.floors.length, has_lift: true, has_step_free_entrance: true }
let fixtureStepFree = true
let fixtureRevision = 2
let fixtureLastRouteId: string | null = null
let fixturePendingActionId: string | null = null
let fixturePendingElement: string | null = null
let fixtureClosedIds: string[] = []

function fixtureSession(buildingId = fixtureBuilding.id): Session & { closed_ids: string[]; last_route_id: string | null; pending_action_id: string | null } {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    building_id: buildingId,
    building_name: catalog.buildingName,
    revision: fixtureRevision,
    preferences: { step_free: fixtureStepFree },
    closed_ids: fixtureClosedIds,
    last_route_id: fixtureLastRouteId,
    pending_action_id: fixturePendingActionId,
  }
}

function unreachableRoute(input: RouteRequest): Route {
  return {
    id: 'fixture-no-route',
    reachable: false,
    length_m: null,
    step_free: input.step_free ?? fixtureStepFree,
    via: input.via ?? [],
    closed_ids: [],
    start_space_id: input.start_space_id,
    destination_space_id: input.destination_space_id,
    directions: [],
    legs: [],
  }
}

function fixturePlaces(query: string): Place[] {
  const needle = query.trim().toLowerCase()
  const places: Place[] = []
  for (const space of catalog.spaces.values()) {
    if (!needle || space.name.toLowerCase().includes(needle) || space.room_type.toLowerCase().includes(needle)) places.push({ id: space.id, kind: 'space', name: space.name, floor_id: space.floor_id, floor_level: catalog.floors.find((floor) => floor.id === space.floor_id)?.level ?? 0, space_id: space.id, position: space.polygon[0] ?? null })
  }
  for (const asset of catalog.assets.values()) {
    if (!needle || asset.name.toLowerCase().includes(needle) || asset.type.toLowerCase().includes(needle)) places.push({ id: asset.id, kind: 'asset', name: asset.name, floor_id: asset.floor_id, floor_level: catalog.floors.find((floor) => floor.id === asset.floor_id)?.level ?? 0, space_id: asset.space_id, position: asset.position })
  }
  return places
}

export const fixtureGateway: BuildingGateway = {
  mode: 'fixture',
  async listBuildings() { return [fixtureBuilding, { id: 'other-building', name: 'Other building', floors: 1, has_lift: false, has_step_free_entrance: true }] },
  async createSession(buildingId) { if (buildingId !== fixtureBuilding.id) throw new ApiError('Fixture building not found', '30001_building_not_found', 'fixture', null, 404); return fixtureSession(buildingId) },
  async getSession(sessionId) { if (sessionId !== fixtureSession().id) throw new ApiError('Session was not found.', '30002_session_not_found', 'fixture', null, 404); return fixtureSession() },
  async listFloors() { return catalog.floors },
  async getFloorPlan(_sessionId, floorId) { const plan = planFor(floorId); if (!plan) throw new Error(`Floor not found: ${floorId}`); return plan },
  async searchPlaces(_sessionId, query, page = 1) { const all = fixturePlaces(query); const start = (page - 1) * 15; return { items: all.slice(start, start + 15), total: all.length } },
  async createRoute(_sessionId, input) {
    const saved = catalog.replies.accepted.routes[0]
    if (!saved) throw new Error('Fixture route missing')
    const wantsStepFree = input.step_free ?? fixtureStepFree
    const destinationMatches = input.destination_space_id === saved.destination_space_id || input.destination_space_id === 'proc-factory-dev-003-A00001'
    const startMatches = input.start_space_id === saved.start_space_id
    if (startMatches && destinationMatches && wantsStepFree === saved.step_free) {
      fixtureLastRouteId = saved.id
      return saved
    }
    const missed = unreachableRoute(input)
    fixtureLastRouteId = missed.id
    return missed
  },
  async getRoute(_sessionId, routeId) {
    const routes = [catalog.replies.accepted.routes[0], catalog.replies.unreachable.routes[0]].filter(Boolean)
    const route = routes.find((item) => item.id === routeId)
    if (!route) throw new ApiError('Route was not found.', '30004_place_not_found', 'fixture', null, 404)
    return route
  },
  async updatePreferences(_sessionId, preferences) {
    fixtureStepFree = preferences.step_free
    fixtureRevision += 1
    return fixtureSession()
  },
  async sendMessage(_sessionId, text) {
    const exact = text.trim().toLowerCase()
    if (exact.includes('closed') && !exact.includes('reopen')) {
      fixturePendingActionId = catalog.replies.pending.pending?.id ?? null
      return catalog.replies.pending
    }
    const reply = interpretMessage(text, {
      hereId: currentLocation(),
      destinationId: null,
      stepFree: fixtureStepFree,
      closedIds: fixtureClosedIds,
      buildingName: catalog.buildingName,
    })
    if (reply.pending) {
      fixturePendingActionId = reply.pending.id
      fixturePendingElement = reply.pending.proposal.element_ref ?? null
    }
    return reply
  },
  async confirmAction() {
    const pending = fixturePendingActionId
    const reopening = pending === '55555555-5555-4555-8555-555555555556'
    if (reopening) fixtureClosedIds = []
    else if (pending === '55555555-5555-4555-8555-555555555557' && fixturePendingElement) fixtureClosedIds = [...new Set([...fixtureClosedIds, fixturePendingElement])]
    else fixtureClosedIds = catalog.confirmedClosedIds
    fixturePendingActionId = null
    fixturePendingElement = null
    fixtureRevision += 1
    return {
      summary: reopening ? 'The closed place is open.' : 'The place is closed. No replacement route is saved.',
      closed_ids: fixtureClosedIds,
      id: pending ?? '55555555-5555-4555-8555-555555555555',
      status: 'confirmed',
    }
  },
  async cancelAction() { fixturePendingActionId = null; return { summary: 'Change cancelled.', closed_ids: [], id: '55555555-5555-4555-8555-555555555555', status: 'cancelled' } },
  async getAction(_sessionId, actionId) {
    if (actionId !== catalog.replies.pending.pending?.id) throw new ApiError('Action was not found.', '30008_action_not_found', 'fixture', null, 404)
    return { summary: catalog.replies.pending.pending.summary, closed_ids: [], id: actionId, status: fixturePendingActionId ? 'pending' : 'cancelled', proposal: catalog.replies.pending.pending.proposal }
  },
}

async function request<T>(config: GatewayConfig, path: string, init?: RequestInit, idempotencyKey?: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${config.baseUrl.replace(/\/$/, '')}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}), ...(init?.headers ?? {}) } })
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : 'API is unavailable.', '00001_internal', 'network', null, 0)
  }
  if (!response.ok) {
    const requestId = response.headers.get('X-Request-Id')
    const payload = await response.json().catch(() => null) as { code?: string; message?: string; trace_id?: string } | null
    throw new ApiError(payload?.message ?? `API request failed (${response.status})`, payload?.code ?? '00001_internal', payload?.trace_id ?? 'unknown', requestId, response.status)
  }
  return response.json() as Promise<T>
}

function mapBuilding(item: BuildingSummary & { level_count?: number }): BuildingSummary {
  return { id: item.id, name: item.name, floors: item.floors ?? item.level_count ?? 0, has_lift: Boolean(item.has_lift), has_step_free_entrance: Boolean(item.has_step_free_entrance) }
}

function mapPlace(item: Place & { asset_type?: string | null }): Place {
  return { id: item.id, kind: item.kind, name: item.name, floor_id: item.floor_id, floor_level: item.floor_level, space_id: item.space_id, position: item.position }
}

function normalizeReply(value: unknown): Reply {
  const envelope = value as { user_message?: { id?: string; text?: string }; guide_message?: { id?: string; text?: string; understood?: Reply['understood']; effects?: Reply['effects']; pending_action_id?: string | null }; routes?: Route[]; pending_action?: Reply['pending'] }
  if (!envelope.guide_message) return value as Reply
  return {
    id: envelope.guide_message.effects?.some((effect) => effect.type === 'ask') ? 'clarify' : envelope.pending_action ? 'pending' : 'accepted',
    userText: envelope.user_message?.text ?? '',
    guideText: envelope.guide_message.text ?? '',
    understood: envelope.guide_message.understood ?? null,
    effects: envelope.guide_message.effects ?? [],
    routes: envelope.routes ?? [],
    pending: envelope.pending_action ?? null,
  }
}

export function createHttpGateway(config: GatewayConfig): BuildingGateway {
  const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })
  return {
    mode: 'http',
    async listBuildings() { const result = await request<{ items?: Array<BuildingSummary & { level_count?: number }> }>(config, '/buildings?computed=1'); return (result.items ?? []).map(mapBuilding) },
    async createSession(buildingId) { return request<Session>(config, '/sessions', json({ building_id: buildingId, engine: 'computed' }), requestId()) },
    async getSession(sessionId) { return request<Session>(config, `/sessions/${sessionId}`) },
    async listFloors(sessionId) { const result = await request<{ floors: FloorSummary[] }>(config, `/sessions/${sessionId}/floors`); return result.floors },
    async getFloorPlan(sessionId, floorId) { return request<FloorPlan>(config, `/sessions/${sessionId}/floors/${floorId}/plan`) },
    async searchPlaces(sessionId, query, page = 1) { const result = await request<{ items?: Place[]; places?: Place[]; total?: number }>(config, `/sessions/${sessionId}/places?q=${encodeURIComponent(query)}&page=${page}`); return { items: (result.items ?? result.places ?? []).map(mapPlace), total: result.total ?? (result.items ?? result.places ?? []).length } },
    async createRoute(sessionId, input) {
      return request<Route>(config, `/sessions/${sessionId}/routes`, json({
        start: input.start_space_id,
        destination: input.destination_space_id,
        step_free: input.step_free,
        via: input.via ?? [],
      }), requestId())
    },
    async getRoute(sessionId, routeId) { return request<Route>(config, `/sessions/${sessionId}/routes/${routeId}`) },
    async updatePreferences(sessionId, preferences) {
      return request<Session>(config, `/sessions/${sessionId}/preferences`, { method: 'PUT', body: JSON.stringify(preferences) })
    },
    async sendMessage(sessionId, text, inputMode = 'text') { const result = await request<unknown>(config, `/sessions/${sessionId}/messages`, json({ text, input_mode: inputMode }), requestId()); return normalizeReply(result) },
    async confirmAction(sessionId, actionId) { return request<ActionResult>(config, `/sessions/${sessionId}/actions/${actionId}/confirmations`, json({}), requestId()) },
    async cancelAction(sessionId, actionId) { return request<ActionResult>(config, `/sessions/${sessionId}/actions/${actionId}/cancellations`, json({}), requestId()) },
    async getAction(sessionId, actionId) { return request<ActionResult & { id: string; status: string }>(config, `/sessions/${sessionId}/actions/${actionId}`) },
  }
}

export function createGateway(): BuildingGateway {
  const mode = (import.meta.env.VITE_DATA_MODE ?? 'fixture') as DataMode
  if (mode === 'http') return createHttpGateway({ mode, baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api/v1' })
  return fixtureGateway
}

let activeGateway = createGateway()
export const gateway: BuildingGateway = new Proxy({} as BuildingGateway, {
  get(_target, property: string) {
    return activeGateway[property as keyof BuildingGateway]
  },
})

export async function connectComputedApi(): Promise<boolean> {
  try {
    const response = await fetch('/api/v1/health', { headers: { Accept: 'application/json' } })
    if (!response.ok) return false
    const body = await response.json() as { status?: string }
    if (body.status !== 'ok') return false
    activeGateway = createHttpGateway({ mode: 'http', baseUrl: '/api/v1' })
    return true
  } catch {
    return false
  }
}
export { labelFor }