export type Point = [number, number]

export type FloorSummary = {
  id: string
  level: number
  name: string
  elevation_m: number
  height_m: number
  space_count: number
}

export type Space = {
  id: string
  floor_id: string
  type: string
  room_type: string
  name: string
  ref: string | null
  polygon: Point[]
  synthetic: boolean
}

export type Opening = {
  id: string
  floor_id: string
  space_ids: string[]
  kind: string
  position: Point
  width_m: number
  step_free: boolean
  synthetic: boolean
}

export type Asset = {
  id: string
  name: string
  category: string
  type: string
  space_id: string
  floor_id: string
  position: Point
  footprint: { width_m: number; depth_m: number; rotation_deg: number }
  source: string
}

export type Connector = {
  id: string
  kind: string
  name: string
  floor_ids: string[]
  space_ids: string[]
  step_free: boolean
  synthetic: boolean
}

export type FloorPlan = {
  floor: FloorSummary
  spaces: Space[]
  openings: Opening[]
  assets: Asset[]
  connectors: Connector[]
  closed_ids: string[]
  bounds: { min: Point; max: Point }
}

export type Direction = { text: string; floor_id: string; at: Point }

export type Route = {
  id: string
  reachable: boolean
  length_m: number | null
  step_free: boolean
  via: string[]
  closed_ids: string[]
  start_space_id: string | null
  destination_space_id: string | null
  space_path?: string[]
  directions: Direction[]
  legs: { floor_id: string; floor_level: number; points: Point[] }[]
}

export type Understood = {
  intent: string
  summary: string
  constraints: { step_free: boolean; via: string[]; closed_ids: string[] }
  resolved: {
    start_space_id: string | null
    destination_space_id: string | null
    space_ids: string[]
    asset_ids: string[]
    count: number | null
  }
  missing: string[]
}

export type AskOption = { id: string; label: string; place_id?: string | null }

export type AskEffect = { type: 'ask'; question: string; options: AskOption[] }

export type ViewEffect =
  | { type: 'highlight_spaces'; space_ids: string[]; reason: string }
  | { type: 'highlight_assets'; asset_ids: string[] }
  | { type: 'focus'; floor_id: string; floor_level: number; point: Point | null }
  | { type: 'draw_route'; route_id: string }
  | { type: 'clear_route' }
  | { type: 'set_closures'; closed_ids: string[] }
  | AskEffect
  | { type: 'building_patched'; floor_ids: string[] }
  | { type: string; [key: string]: unknown }

export type PendingAction = {
  id: string
  status: string
  summary: string
  proposal: { kind: string; element_ref?: string; closed?: boolean }
}

export type Selection = {
  kind: 'space' | 'asset' | 'opening'
  id: string
  name: string
  floorId: string
  floorName: string
  note: string | null
}

export type ReplyId = 'accepted' | 'clarify' | 'pending' | 'unreachable'

export type Reply = {
  id: ReplyId
  userText: string | null
  guideText: string
  understood: Understood | null
  effects: ViewEffect[]
  routes: Route[]
  pending: PendingAction | null
}

export type PositionSource = 'simulated' | 'wifi' | 'manual'
export type PositionFix = { floor_id: string; x_m: number; y_m: number; accuracy_m: number | null; measured_at: string; source: PositionSource }
export type LivePosition = {
  floor_id: string
  floor_level: number | null
  x_m: number
  y_m: number
  accuracy_m: number | null
  measured_at: string
  received_at: string
  source: PositionSource
  space_id: string | null
  space_name: string | null
  tracking: 'live' | 'stale'
}
export type GuidanceWaypoint = { index: number; kind: string; floor_id: string; at: Point; text: string }
export type Guidance = {
  status: 'idle' | 'active' | 'arrived' | 'stopped'
  route_id: string | null
  destination_space_id: string | null
  destination_name: string | null
  target_index: number | null
  waypoints: GuidanceWaypoint[]
  remaining_m: number | null
  tracking: 'none' | 'live' | 'stale'
}
export type GuidanceEvent = {
  seq: number
  kind: 'instruction' | 'wrong_way' | 'arrived' | 'stopped'
  text: string
  route_id: string | null
  waypoint_index: number | null
  speech_clip_id: string | null
  created_at: string
}
export type GuidanceFeed = { schema_version: number; guidance: Guidance; events: GuidanceEvent[]; cursor: number }
export type PositionAccepted = { schema_version: number; position: LivePosition; applied: boolean; guidance: Guidance | Record<string, unknown> | null }
