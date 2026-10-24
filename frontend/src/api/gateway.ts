import { catalog, labelFor, planFor } from './fixtures'
import type { FloorPlan, FloorSummary, Reply, ReplyId, Route, Space, Asset, Connector } from '../domain/types'

export type DataMode = 'fixture' | 'http'
export type GatewayConfig = { mode: DataMode; baseUrl: string }
export type BuildingSummary = { id: string; name: string; floors: number; has_lift: boolean; has_step_free_entrance: boolean }
export type Session = { id: string; building_id: string; building_name: string; revision: number; preferences: { step_free: boolean } }
export type Place = { id: string; kind: string; name: string; floor_id: string; floor_level: number; space_id: string | null; position: [number, number] | null }
export type RouteRequest = { start_space_id: string; destination_space_id: string; step_free?: boolean; via?: string[] }
export type ActionResult = { summary: string; closed_ids: string[] }

export interface BuildingGateway {
  readonly mode: DataMode
  listBuildings(): Promise<BuildingSummary[]>
  createSession(buildingId: string): Promise<Session>
  listFloors(sessionId: string): Promise<FloorSummary[]>
  getFloorPlan(sessionId: string, floorId: string): Promise<FloorPlan>
  searchPlaces(sessionId: string, query: string): Promise<Place[]>
  createRoute(sessionId: string, input: RouteRequest): Promise<Route>
  sendMessage(sessionId: string, text: string): Promise<Reply>
  confirmAction(sessionId: string, actionId: string): Promise<ActionResult>
  cancelAction(sessionId: string, actionId: string): Promise<ActionResult>
}

const fixtureBuilding: BuildingSummary = { id: 'proc-factory-dev-003', name: catalog.buildingName, floors: catalog.floors.length, has_lift: true, has_step_free_entrance: true }

function fixturePlaces(query: string): Place[] {
  const needle = query.trim().toLowerCase()
  const places: Place[] = []
  for (const space of catalog.spaces.values()) {
    if (!needle || space.name.toLowerCase().includes(needle) || space.room_type.toLowerCase().includes(needle)) places.push({ id: space.id, kind: 'space', name: space.name, floor_id: space.floor_id, floor_level: catalog.floors.find((floor) => floor.id === space.floor_id)?.level ?? 0, space_id: space.id, position: space.polygon[0] ?? null })
  }
  for (const asset of catalog.assets.values()) {
    if (!needle || asset.name.toLowerCase().includes(needle) || asset.type.toLowerCase().includes(needle)) places.push({ id: asset.id, kind: 'asset', name: asset.name, floor_id: asset.floor_id, floor_level: catalog.floors.find((floor) => floor.id === asset.floor_id)?.level ?? 0, space_id: asset.space_id, position: asset.position })
  }
  return places.slice(0, 20)
}

export const fixtureGateway: BuildingGateway = {
  mode: 'fixture',
  async listBuildings() { return [fixtureBuilding] },
  async createSession(buildingId) { if (buildingId !== fixtureBuilding.id) throw new Error('Fixture building not found'); return { id: '11111111-1111-4111-8111-111111111111', building_id: buildingId, building_name: catalog.buildingName, revision: 2, preferences: { step_free: true } } },
  async listFloors() { return catalog.floors },
  async getFloorPlan(_sessionId, floorId) { const plan = planFor(floorId); if (!plan) throw new Error(`Floor not found: ${floorId}`); return plan },
  async searchPlaces(_sessionId, query) { return fixturePlaces(query) },
  async createRoute() { const route = catalog.replies.accepted.routes[0]; if (!route) throw new Error('Fixture route missing'); return route },
  async sendMessage(_sessionId, text) { const normalized = text.trim().toLowerCase(); const replyId: ReplyId = normalized.includes('desk') ? 'clarify' : normalized.includes('closed') ? 'unreachable' : 'accepted'; return catalog.replies[replyId] },
  async confirmAction() { return { summary: catalog.confirmedText, closed_ids: catalog.confirmedClosedIds } },
  async cancelAction() { return { summary: 'Change cancelled.', closed_ids: [] } },
}

async function request<T>(config: GatewayConfig, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${config.baseUrl.replace(/\/$/, '')}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  if (!response.ok) throw new Error(`API request failed (${response.status})`)
  return response.json() as Promise<T>
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
    async listBuildings() { const result = await request<{ items?: BuildingSummary[] }>(config, '/buildings'); return result.items ?? [] },
    async createSession(buildingId) { return request<Session>(config, '/sessions', json({ building_id: buildingId })) },
    async listFloors(sessionId) { const result = await request<{ floors: FloorSummary[] }>(config, `/sessions/${sessionId}/floors`); return result.floors },
    async getFloorPlan(sessionId, floorId) { return request<FloorPlan>(config, `/sessions/${sessionId}/floors/${floorId}/plan`) },
    async searchPlaces(sessionId, query) { const result = await request<{ places: Place[] }>(config, `/sessions/${sessionId}/places?q=${encodeURIComponent(query)}`); return result.places },
    async createRoute(sessionId, input) { return request<Route>(config, `/sessions/${sessionId}/routes`, json(input)) },
    async sendMessage(sessionId, text) { const result = await request<unknown>(config, `/sessions/${sessionId}/messages`, json({ text, input_mode: 'text' })); return normalizeReply(result) },
    async confirmAction(sessionId, actionId) { return request<ActionResult>(config, `/sessions/${sessionId}/actions/${actionId}/confirmations`, json({})) },
    async cancelAction(sessionId, actionId) { return request<ActionResult>(config, `/sessions/${sessionId}/actions/${actionId}/cancellations`, json({})) },
  }
}

export function createGateway(): BuildingGateway {
  const mode = (import.meta.env.VITE_DATA_MODE ?? 'fixture') as DataMode
  if (mode === 'http') return createHttpGateway({ mode, baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api/v1' })
  return fixtureGateway
}

export const gateway = createGateway()
export { labelFor }