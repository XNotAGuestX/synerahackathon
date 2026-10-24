import actionConfirmedJson from '../../../docs/api/examples/action-confirmed.json'
import floorIndexJson from '../../../docs/api/examples/floor-index.json'
import floorPlanJson from '../../../docs/api/examples/floor-plan.json'
import floorPlanF1Json from '../../../docs/api/examples/floor-plan-f1.json'
import acceptedJson from '../../../docs/api/examples/message-accepted.json'
import clarifyJson from '../../../docs/api/examples/message-clarify.json'
import pendingJson from '../../../docs/api/examples/message-pending-action.json'
import routeJson from '../../../docs/api/examples/route.json'
import unreachableJson from '../../../docs/api/examples/route-unreachable.json'
import type {
  Asset,
  Connector,
  FloorPlan,
  FloorSummary,
  Opening,
  PendingAction,
  Reply,
  ReplyId,
  Route,
  Space,
  Understood,
  ViewEffect,
} from '../domain/types'

type Catalog = {
  buildingName: string
  floors: FloorSummary[]
  plans: Map<string, FloorPlan>
  spaces: Map<string, Space>
  assets: Map<string, Asset>
  connectors: Map<string, Connector>
  replies: Record<ReplyId, Reply>
  confirmedEffects: ViewEffect[]
  confirmedClosedIds: string[]
  confirmedText: string
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} fixture is not an object`)
  }
  return value as Record<string, unknown>
}

function asString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${label} is missing`)
  return value
}

function asPoint(value: unknown, label: string): [number, number] | null {
  if (value == null) return null
  if (!Array.isArray(value) || value.length < 2) throw new Error(`${label} is not a point`)
  const x = value[0]
  const y = value[1]
  if (typeof x !== 'number' || typeof y !== 'number') throw new Error(`${label} is not a point`)
  return [x, y]
}

function readFloorPlan(value: unknown): FloorPlan {
  const plan = asRecord(value, 'floor plan')
  const floor = asRecord(plan.floor, 'floor')
  return {
    floor: {
      id: asString(floor.id, 'floor id'),
      level: Number(floor.level),
      name: asString(floor.name, 'floor name'),
      elevation_m: Number(floor.elevation_m),
      height_m: Number(floor.height_m),
      space_count: Number(floor.space_count),
    },
    spaces: (plan.spaces as Space[]) ?? [],
    openings: (plan.openings as Opening[]) ?? [],
    assets: (plan.assets as Asset[]) ?? [],
    connectors: (plan.connectors as Connector[]) ?? [],
    closed_ids: (plan.closed_ids as string[]) ?? [],
    bounds: plan.bounds as FloorPlan['bounds'],
  }
}

function readEffects(value: unknown): ViewEffect[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ViewEffect => {
    return Boolean(item) && typeof item === 'object' && typeof (item as { type?: unknown }).type === 'string'
  })
}

function readRoute(value: unknown): Route {
  const route = asRecord(value, 'route')
  return {
    id: asString(route.id, 'route id'),
    reachable: Boolean(route.reachable),
    length_m: typeof route.length_m === 'number' ? route.length_m : null,
    step_free: Boolean(route.step_free),
    via: (route.via as string[]) ?? [],
    closed_ids: (route.closed_ids as string[]) ?? [],
    start_space_id: typeof route.start_space_id === 'string' ? route.start_space_id : null,
    destination_space_id: typeof route.destination_space_id === 'string' ? route.destination_space_id : null,
    directions: (route.directions as Route['directions']) ?? [],
    legs: (route.legs as Route['legs']) ?? [],
  }
}

function readUnderstood(value: unknown): Understood | null {
  if (!value || typeof value !== 'object') return null
  const understood = value as Understood
  if (!understood.summary || !understood.constraints || !understood.resolved) return null
  return understood
}

function readPending(value: unknown): PendingAction | null {
  if (!value || typeof value !== 'object') return null
  const action = value as PendingAction
  if (!action.summary || !action.proposal) return null
  return action
}

function readMessage(value: unknown, id: ReplyId): Reply {
  const message = asRecord(value, id)
  const guide = asRecord(message.guide_message, 'guide message')
  const user = asRecord(message.user_message, 'user message')
  return {
    id,
    userText: asString(user.text, 'user text'),
    guideText: asString(guide.text, 'guide text'),
    understood: readUnderstood(guide.understood),
    effects: readEffects(guide.effects),
    routes: Array.isArray(message.routes) ? message.routes.map(readRoute) : [],
    pending: readPending(message.pending_action),
  }
}

function normalize(text: string): string {
  return text.trim().toLowerCase().replace(/[’‘]/g, "'").replace(/\s+/g, ' ')
}

function buildCatalog(): Catalog {
  const ground = readFloorPlan(floorPlanJson)
  const upper = readFloorPlan(floorPlanF1Json)
  const plans = new Map<string, FloorPlan>([
    [ground.floor.id, ground],
    [upper.floor.id, upper],
  ])
  const spaces = new Map<string, Space>()
  const assets = new Map<string, Asset>()
  const connectors = new Map<string, Connector>()
  for (const plan of plans.values()) {
    for (const space of plan.spaces) spaces.set(space.id, space)
    for (const asset of plan.assets) assets.set(asset.id, asset)
    for (const connector of plan.connectors) connectors.set(connector.id, connector)
  }
  const index = asRecord(floorIndexJson, 'floor index')
  const floors = (index.floors as FloorSummary[]) ?? [ground.floor, upper.floor]
  const accepted = asRecord(acceptedJson, 'accepted message')
  const session = asRecord(accepted.session, 'session')
  const unreachable = readRoute(unreachableJson)
  const start = spaces.get(unreachable.start_space_id ?? '')
  const destination = spaces.get(unreachable.destination_space_id ?? '')
  const closedNames = unreachable.closed_ids.map((id) => connectors.get(id)?.name ?? id)
  const confirmed = asRecord(actionConfirmedJson, 'confirmed action')
  const result = asRecord(confirmed.result, 'confirmed result')
  const elementId = asString(result.element_id, 'closed element')
  const closedName = connectors.get(elementId)?.name ?? elementId
  return {
    buildingName: asString(session.building_name, 'building name'),
    floors: [...floors].sort((a, b) => b.level - a.level),
    plans,
    spaces,
    assets,
    connectors,
    replies: {
      accepted: readMessage(acceptedJson, 'accepted'),
      clarify: readMessage(clarifyJson, 'clarify'),
      pending: readMessage(pendingJson, 'pending'),
      unreachable: {
        id: 'unreachable',
        userText: null,
        guideText: closedNames.length
          ? `No step-free route. ${closedNames.join(', ')} is closed.`
          : 'No step-free route.',
        understood: {
          intent: 'route',
          summary: `${start?.name ?? 'Start'} to ${destination?.name ?? 'destination'}, no stairs`,
          constraints: {
            step_free: unreachable.step_free,
            via: unreachable.via,
            closed_ids: unreachable.closed_ids,
          },
          resolved: {
            start_space_id: unreachable.start_space_id,
            destination_space_id: unreachable.destination_space_id,
            space_ids: [unreachable.start_space_id, unreachable.destination_space_id].filter((id): id is string => Boolean(id)),
            asset_ids: [],
            count: null,
          },
          missing: [],
        },
        effects: [{ type: 'draw_route', route_id: unreachable.id }],
        routes: [unreachable],
        pending: null,
      },
    },
    confirmedEffects: readEffects(confirmed.preview_effects),
    confirmedClosedIds: (result.closed_ids as string[]) ?? [],
    confirmedText: `${closedName} is closed.`,
  }
}

export const catalog = buildCatalog()

export function planFor(floorId: string): FloorPlan | null {
  return catalog.plans.get(floorId) ?? null
}

export function labelFor(id: string | null): string {
  if (!id) return 'Not resolved'
  return catalog.spaces.get(id)?.name
    ?? catalog.assets.get(id)?.name
    ?? catalog.connectors.get(id)?.name
    ?? id
}

export function matchUserText(text: string): ReplyId | null {
  const key = normalize(text)
  if (!key) return null
  for (const reply of Object.values(catalog.replies)) {
    if (reply.userText && normalize(reply.userText) === key) return reply.id
  }
  return null
}

export function connectorNote(spaceId: string): string | null {
  for (const connector of catalog.connectors.values()) {
    if (connector.space_ids.includes(spaceId)) return `${connector.name} · ${connector.kind}`
  }
  return null
}
