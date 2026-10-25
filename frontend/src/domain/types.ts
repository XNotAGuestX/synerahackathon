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
  height_m?: number
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

/** One row of `stacking_adapter.json` for this floor. Objects not listed have the catalog height. */
export type StackingEntry = {
  object_id: string
  layer: number
  on_top_of: string[]
  height_m: number
  height_source: 'override' | 'catalog'
  elevation_m: number
}

export type FloorPlan = {
  floor: FloorSummary
  spaces: Space[]
  openings: Opening[]
  assets: Asset[]
  connectors: Connector[]
  closed_ids: string[]
  bounds: { min: Point; max: Point }
  /** Always sent by the editor-aware API. Optional for imported plans and older fixtures. */
  stacking?: StackingEntry[]
}

export type Direction = { text: string; floor_id: string; at: Point }

export type Session = {
  id: string; building_id: string; building_name: string; revision: number
  preferences: { step_free: boolean }; current_space_id?: string | null
  closed_ids?: string[]; last_route_id?: string | null; pending_action_id?: string | null
}

export type TranscriptMessage = {
  id: string; role: 'user' | 'guide'; text: string; created_at: string
  understood: Understood | null; effects: ViewEffect[]; pending_action_id: string | null
}

export type ChatMessage = TranscriptMessage & {
  delivery?: 'sending' | 'sent' | 'failed'; error?: string; reply?: Reply
  request?: { key: string; text: string; inputMode: 'text' | 'transcript' | 'voice'; context: ClientContext; sessionId: string }
}

export type Route = {
  id: string
  reachable: boolean
  length_m: number | null
  step_free: boolean
  /** Omitted by older snapshots. kit-1.1.0 is the walking route; synera-industrial is the forklift route. */
  profile?: 'kit-1.1.0' | 'synera-industrial'
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
  | PreviewObjectsEffect
  | { type: string; [key: string]: unknown }

/** State after a proposed edit, for every new or changed element. Drawn as ghosts. */
export type PreviewObjectsEffect = {
  type: 'preview_objects'
  floor_ids: string[]
  assets: Asset[]
  openings: Opening[]
  connectors: Connector[]
  removed_ids: string[]
}

export type ActionProposal = { kind: string; element_ref?: string; closed?: boolean; [key: string]: unknown }

export type PendingAction = {
  id: string
  status: string
  summary: string
  proposal: ActionProposal
}

/* Object editor: catalog, proposals and results (spec 3.3, 4.2, 4.4). */

export type CatalogAction = 'add_object' | 'add_opening' | 'add_connector'

export type ObjectType = {
  id: string
  label: string
  action: CatalogAction
  width_m: number | null
  depth_m: number | null
  height_m?: number | null
  count: number
}

export type ObjectCategory = { id: string; label: string; types: ObjectType[] }
export type ObjectGroup = { id: string; label: string; categories: ObjectCategory[] }
export type ObjectCatalog = { schema_version: number; groups: ObjectGroup[] }

export type EditKind = 'add_object' | 'update_object' | 'remove_object' | 'add_opening' | 'add_connector' | 'undo_edit'
export type OpeningKind = 'door' | 'opening'
export type ConnectorKind = 'stairs' | 'escalator' | 'lift'

export type AddObjectProposal = {
  kind: 'add_object'
  type: string
  category?: string | null
  name?: string | null
  space?: string | null
  floor_id?: string | null
  position?: Point | null
  rotation_deg?: number | null
  width_m?: number | null
  depth_m?: number | null
  height_m?: number | null
  on_top_of?: string[] | null
}

export type UpdateObjectProposal = {
  kind: 'update_object'
  object_ref: string
  name?: string | null
  type?: string | null
  category?: string | null
  space?: string | null
  floor_id?: string | null
  position?: Point | null
  rotation_deg?: number | null
  width_m?: number | null
  depth_m?: number | null
  height_m?: number | null
  on_top_of?: string[] | null
  step_free?: boolean | null
  opening_kind?: OpeningKind | null
}

export type RemoveObjectProposal = { kind: 'remove_object'; object_ref: string }

export type AddOpeningProposal = {
  kind: 'add_opening'
  opening_kind?: OpeningKind
  first_space?: string | null
  second_space?: string | null
  floor_id?: string | null
  position?: Point | null
  width_m?: number | null
  step_free?: boolean
}

export type AddConnectorProposal = {
  kind: 'add_connector'
  connector_kind: ConnectorKind
  spaces: string[]
  name?: string | null
  step_free?: boolean | null
}

export type UndoEditProposal = { kind: 'undo_edit' }

export type EditProposal =
  | AddObjectProposal
  | UpdateObjectProposal
  | RemoveObjectProposal
  | AddOpeningProposal
  | AddConnectorProposal
  | UndoEditProposal

export type EditResult = {
  kind: EditKind
  summary: string
  changed_ids: string[]
  removed_ids: string[]
  floor_ids: string[]
}

export type Action = {
  id: string
  session_id?: string
  status: string
  summary: string
  proposal: ActionProposal
  preview_effects: ViewEffect[]
  result: ({ kind: string; [key: string]: unknown }) | null
  created_at?: string
  expires_at?: string
  resolved_at?: string | null
}

/** Sent with each chat message so the guide can resolve "here", "it" and a picked destination. */
export type ClientContext = {
  floor_level?: number | null
  selected_space_id?: string | null
  selected_object_id?: string | null
  current_space_id?: string | null
  destination_place_id?: string | null
  preferences?: { step_free: boolean }
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
  speechClipId?: string | null
  messages?: TranscriptMessage[]
  session?: Session
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
