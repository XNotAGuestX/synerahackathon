import { ApiError } from './errors'
import type { ErrorDetail } from './errors'
import type { Action, ClientContext, EditProposal, FloorPlan, FloorSummary, Guidance, GuidanceFeed, ObjectCatalog, PositionAccepted, PositionFix, Reply, ReplyId, Route } from '../domain/types'

export type InputMode = 'text' | 'transcript' | 'voice'

export type GatewayConfig = { baseUrl: string }
export type BuildingSummary = { id: string; name: string; floors: number; has_lift: boolean; has_step_free_entrance: boolean }
export type Session = { id: string; building_id: string; building_name: string; revision: number; object_revision?: number; preferences: { step_free: boolean }; closed_ids?: string[]; last_route_id?: string | null; pending_action_id?: string | null }
export type Place = { id: string; kind: string; name: string; floor_id: string; floor_level: number; space_id: string | null; position: [number, number] | null }
type CursorPage<T> = { items: T[]; next_cursor?: string | null }
export type RouteRequest = { start_space_id: string; destination_space_id: string; step_free?: boolean; via?: string[] }
/** Full action as the API returns it, plus `closed_ids` lifted from a closure result for older callers. */
export type ActionResult = Action & { closed_ids: string[] }
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
  readonly mode: 'http'
  listBuildings(): Promise<BuildingSummary[]>
  createSession(buildingId: string): Promise<Session>
  getSession(sessionId: string): Promise<Session>
  listFloors(sessionId: string): Promise<FloorSummary[]>
  getFloorPlan(sessionId: string, floorId: string): Promise<FloorPlan>
  searchPlaces(sessionId: string, query: string, page?: number): Promise<{ items: Place[]; total: number }>
  createRoute(sessionId: string, input: RouteRequest): Promise<Route>
  getRoute(sessionId: string, routeId: string): Promise<Route>
  updatePreferences(sessionId: string, preferences: { step_free: boolean }): Promise<Session>
  sendMessage(sessionId: string, text: string, inputMode?: InputMode, clientContext?: ClientContext): Promise<Reply>
  listObjectTypes(): Promise<ObjectCatalog>
  createAction(sessionId: string, proposal: EditProposal, revision?: number): Promise<ActionResult>
  confirmAction(sessionId: string, actionId: string): Promise<ActionResult>
  cancelAction(sessionId: string, actionId: string): Promise<ActionResult>
  getAction(sessionId: string, actionId: string): Promise<ActionResult>
  putPosition(sessionId: string, fix: PositionFix): Promise<PositionAccepted>
  getGuidance(sessionId: string, after: number, waitS: number, signal?: AbortSignal): Promise<GuidanceFeed>
  startGuidance(sessionId: string, routeId: string): Promise<Guidance | null>
  stopGuidance(sessionId: string): Promise<void>
  transcribe(sessionId: string, wav: Blob, signal?: AbortSignal): Promise<{ text: string }>
  fetchSpeechClip(sessionId: string, clipId: string, signal?: AbortSignal): Promise<Blob>
}

export type RequestOptions = { idempotencyKey?: string; signal?: AbortSignal; responseType?: 'json' | 'blob' }

export async function request<T>(config: GatewayConfig, path: string, init?: RequestInit, options: RequestOptions | string = {}): Promise<T> {
  const { idempotencyKey, signal, responseType = 'json' } = typeof options === 'string' ? { idempotencyKey: options } : options
  const rawBody = init?.body
  const binary = rawBody instanceof Blob || rawBody instanceof ArrayBuffer
  let response: Response
  try {
    response = await fetch(`${config.baseUrl.replace(/\/$/, '')}${path}`, { ...init, ...(signal ? { signal } : {}), headers: { ...(binary ? {} : { 'Content-Type': 'application/json' }), ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}), ...(init?.headers ?? {}) } })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError(error instanceof Error ? error.message : 'API is unavailable.', '00001_internal', 'network', null, 0)
  }
  if (!response.ok) {
    const requestId = response.headers.get('X-Request-Id')
    const payload = await response.json().catch(() => null) as { code?: string; message?: string; trace_id?: string; details?: unknown } | null
    const details = Array.isArray(payload?.details) ? payload.details.filter((item): item is ErrorDetail => Boolean(item) && typeof item === 'object') : []
    throw new ApiError(payload?.message ?? `API request failed (${response.status})`, payload?.code ?? '00001_internal', payload?.trace_id ?? 'unknown', requestId, response.status, details)
  }
  if (responseType === 'blob') return response.blob() as Promise<T>
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function mapBuilding(item: BuildingSummary & { level_count?: number }): BuildingSummary {
  return { id: item.id, name: item.name, floors: item.floors ?? item.level_count ?? 0, has_lift: Boolean(item.has_lift), has_step_free_entrance: Boolean(item.has_step_free_entrance) }
}

function mapPlace(item: Place & { asset_type?: string | null }): Place {
  return { id: item.id, kind: item.kind, name: item.name, floor_id: item.floor_id, floor_level: item.floor_level, space_id: item.space_id, position: item.position }
}

function normalizeReply(value: unknown): Reply {
  const envelope = value as { user_message?: { id?: string; text?: string }; guide_message?: { id?: string; text?: string; understood?: Reply['understood']; effects?: Reply['effects']; pending_action_id?: string | null }; routes?: Route[]; pending_action?: Reply['pending']; speech_clip_id?: string | null; speech_text?: string | null }
  if (!envelope.guide_message) return value as Reply
  return {
    id: envelope.guide_message.effects?.some((effect) => effect.type === 'ask') ? 'clarify' : envelope.pending_action ? 'pending' : 'accepted',
    userText: envelope.user_message?.text ?? '',
    guideText: envelope.guide_message.text ?? '',
    understood: envelope.guide_message.understood ?? null,
    effects: envelope.guide_message.effects ?? [],
    routes: envelope.routes ?? [],
    pending: envelope.pending_action ?? null,
    speechClipId: envelope.speech_clip_id ?? null,
    speechText: envelope.speech_text ?? null,
  }
}

function normalizeAction(value: Partial<Action> & { id: string; closed_ids?: string[] }): ActionResult {
  const result = value.result ?? null
  const closed = Array.isArray(result?.closed_ids) ? result.closed_ids.filter((id): id is string => typeof id === 'string') : []
  return {
    ...value,
    status: value.status ?? 'pending',
    summary: value.summary ?? '',
    proposal: value.proposal ?? { kind: 'unknown' },
    preview_effects: value.preview_effects ?? [],
    result,
    closed_ids: value.closed_ids ?? closed,
  }
}

export function createHttpGateway(config: GatewayConfig): BuildingGateway {
  const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })
  return {
    mode: 'http',
    async listBuildings() {
      const items: BuildingSummary[] = []
      let cursor: string | null = null
      do {
        const path: string = `/buildings?split=dev&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
        const result: CursorPage<BuildingSummary & { level_count?: number }> = await request(config, path)
        items.push(...result.items.map(mapBuilding))
        cursor = result.next_cursor ?? null
      } while (cursor)
      return items
    },
    async createSession(buildingId) { return request<Session>(config, '/sessions', json({ building_id: buildingId }), requestId()) },
    async getSession(sessionId) { return request<Session>(config, `/sessions/${sessionId}`) },
    async listFloors(sessionId) { const result = await request<{ floors: FloorSummary[] }>(config, `/sessions/${sessionId}/floors`); return result.floors },
    async getFloorPlan(sessionId, floorId) { return request<FloorPlan>(config, `/sessions/${sessionId}/floors/${floorId}/plan`) },
    async searchPlaces(sessionId, query, page = 1) {
      const path = `/sessions/${sessionId}/places?q=${encodeURIComponent(query)}`
      const items: Place[] = []
      let cursor: string | null = null
      do {
        const result: CursorPage<Place> = await request(config, `${path}&limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`)
        items.push(...result.items.map(mapPlace))
        cursor = result.next_cursor ?? null
      } while (cursor)
      return { items: items.slice((page - 1) * 15, page * 15), total: items.length }
    },
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
    async sendMessage(sessionId, text, inputMode = 'text', clientContext) {
      const body = clientContext ? { text, input_mode: inputMode, client_context: clientContext } : { text, input_mode: inputMode }
      const result = await request<unknown>(config, `/sessions/${sessionId}/messages`, json(body), requestId())
      return normalizeReply(result)
    },
    async listObjectTypes() { return request<ObjectCatalog>(config, '/object-types') },
    async createAction(sessionId, proposal, revision) { return normalizeAction(await request<Action>(config, `/sessions/${sessionId}/actions`, { ...json(proposal), ...(revision == null ? {} : { headers: { 'If-Match': `"${revision}"` } }) }, requestId())) },
    async confirmAction(sessionId, actionId) { return normalizeAction(await request<Action>(config, `/sessions/${sessionId}/actions/${actionId}/confirmations`, json({}), requestId())) },
    async cancelAction(sessionId, actionId) { return normalizeAction(await request<Action>(config, `/sessions/${sessionId}/actions/${actionId}/cancellations`, json({}), requestId())) },
    async getAction(sessionId, actionId) { return normalizeAction(await request<Action>(config, `/sessions/${sessionId}/actions/${actionId}`)) },
    async putPosition(sessionId, fix) { return request<PositionAccepted>(config, `/sessions/${sessionId}/position`, { method: 'PUT', body: JSON.stringify(fix) }) },
    async getGuidance(sessionId, after, waitS, signal) { return request<GuidanceFeed>(config, `/sessions/${sessionId}/guidance?after=${after}&wait_s=${waitS}`, undefined, { signal }) },
    async startGuidance(sessionId, routeId) {
      const result = await request<{ guidance?: Guidance } | Guidance | undefined>(config, `/sessions/${sessionId}/guidance`, { method: 'PUT', body: JSON.stringify({ route_id: routeId }) })
      return result && 'guidance' in result ? result.guidance ?? null : (result as Guidance | undefined) ?? null
    },
    async stopGuidance(sessionId) { await request<unknown>(config, `/sessions/${sessionId}/guidance`, { method: 'DELETE' }) },
    async transcribe(sessionId, wav, signal) {
      const result = await request<{ text?: string }>(config, `/sessions/${sessionId}/transcriptions`, { method: 'POST', body: wav, headers: { 'Content-Type': 'audio/wav' } }, { idempotencyKey: requestId(), signal })
      return { text: result.text ?? '' }
    },
    async fetchSpeechClip(sessionId, clipId, signal) { return request<Blob>(config, `/sessions/${sessionId}/speech-clips/${clipId}`, undefined, { responseType: 'blob', signal }) },
  }
}

export const gateway = createHttpGateway({ baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api/v1' })
