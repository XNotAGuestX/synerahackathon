/**
 * Object editor: pure helpers. No React, no fetch, no runtime imports, so
 * `node --experimental-strip-types src/domain/editor.check.ts` can run them.
 * The server decides validity (spec 4.3); the hints here only guide the user.
 */
import type {
  Action,
  AddConnectorProposal,
  AddObjectProposal,
  AddOpeningProposal,
  Asset,
  ConnectorKind,
  EditKind,
  EditProposal,
  ObjectCatalog,
  ObjectType,
  Opening,
  OpeningKind,
  Point,
  Space,
  StackingEntry,
  UpdateObjectProposal,
} from './types'

export const EDIT_KINDS: readonly EditKind[] = ['add_object', 'update_object', 'remove_object', 'add_opening', 'add_connector', 'undo_edit']
export const NUDGE_M = 0.1
export const NUDGE_FAST_M = 1
export const ROTATE_STEP_DEG = 15
export const PLACEMENT_TOLERANCE_M = 0.15
export const WALL_TOLERANCE_M = 0.35
export const RECENT_LIMIT = 5
export const UNKNOWN_SIZE_M = 0.5
export const DOOR_WIDTH_M = 0.9
const DEFAULT_HEIGHT_M = 1
/** Same fallbacks as the catalog script (spec 3.3). */
const CATEGORY_HEIGHT_M: Record<string, number> = { furniture: 0.8, equipment: 1, fixture: 0.9, machine: 1.8 }
const EPSILON = 0.0005

/* ------------------------------------------------------------------------
   Catalog
   ------------------------------------------------------------------------ */

export type CatalogEntry = {
  key: string
  groupId: string
  groupLabel: string
  categoryId: string
  categoryLabel: string
  type: ObjectType
}

export function catalogKey(groupId: string, categoryId: string, typeId: string): string {
  return `${groupId}/${categoryId}/${typeId}`
}

export function flattenCatalog(catalog: ObjectCatalog): CatalogEntry[] {
  const entries: CatalogEntry[] = []
  for (const group of catalog.groups) {
    for (const category of group.categories) {
      for (const type of category.types) {
        entries.push({ key: catalogKey(group.id, category.id, type.id), groupId: group.id, groupLabel: group.label, categoryId: category.id, categoryLabel: category.label, type })
      }
    }
  }
  return entries
}

function normalise(text: string): string {
  return text.toLowerCase().replace(/[_\-/]+/g, ' ').replace(/\s+/g, ' ').trim()
}

/** Search across all levels: type label and id, category and group. Best label matches first. */
export function searchCatalog(entries: CatalogEntry[], query: string, limit = 40): CatalogEntry[] {
  const phrase = normalise(query)
  if (!phrase) return []
  const words = phrase.split(' ')
  const scored: { entry: CatalogEntry; score: number }[] = []
  for (const entry of entries) {
    const label = normalise(entry.type.label)
    const id = normalise(entry.type.id)
    const haystack = `${label} ${id} ${normalise(entry.categoryLabel)} ${normalise(entry.groupLabel)}`
    if (!words.every((word) => haystack.includes(word))) continue
    let score = 5
    if (label === phrase || id === phrase) score = 0
    else if (label.startsWith(phrase) || id.startsWith(phrase)) score = 1
    else if (` ${label}`.includes(` ${words[0]}`)) score = 2
    else if (label.includes(phrase) || id.includes(phrase)) score = 3
    else if (words.some((word) => label.includes(word) || id.includes(word))) score = 4
    scored.push({ entry, score })
  }
  scored.sort((left, right) => left.score - right.score
    || right.entry.type.count - left.entry.type.count
    || left.entry.type.label.localeCompare(right.entry.type.label))
  return scored.slice(0, limit).map((item) => item.entry)
}

/** Entry for an object type. The given category wins, otherwise the most common one. */
export function findObjectEntry(entries: CatalogEntry[], typeId: string, categoryId?: string | null): CatalogEntry | null {
  const matches = entries.filter((entry) => entry.type.id === typeId && entry.type.action === 'add_object')
  if (matches.length === 0) return null
  return matches.find((entry) => entry.categoryId === categoryId)
    ?? [...matches].sort((left, right) => right.type.count - left.type.count)[0]
}

/** Default height of a type: catalog type in category, then type anywhere, then category fallback. */
export function catalogHeight(entries: CatalogEntry[], typeId: string, categoryId: string): number {
  const exact = entries.find((entry) => entry.type.id === typeId && entry.categoryId === categoryId && entry.type.action === 'add_object')
  if (exact?.type.height_m != null && exact.type.height_m > 0) return exact.type.height_m
  const any = findObjectEntry(entries, typeId, categoryId)
  if (any?.type.height_m != null && any.type.height_m > 0) return any.type.height_m
  return CATEGORY_HEIGHT_M[categoryId] ?? DEFAULT_HEIGHT_M
}

export function catalogSize(entry: CatalogEntry | null): { width: number; depth: number } {
  return { width: entry?.type.width_m ?? UNKNOWN_SIZE_M, depth: entry?.type.depth_m ?? UNKNOWN_SIZE_M }
}

export function parseRecent(raw: string | null): string[] {
  if (!raw) return []
  try {
    const value: unknown = JSON.parse(raw)
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').slice(0, RECENT_LIMIT) : []
  } catch {
    return []
  }
}

export function pushRecent(recent: string[], key: string, limit = RECENT_LIMIT): string[] {
  return [key, ...recent.filter((item) => item !== key)].slice(0, limit)
}

/* ------------------------------------------------------------------------
   Heights and stacks (spec 3.2)
   ------------------------------------------------------------------------ */

export type StackingIndex = Map<string, StackingEntry>

export function stackingIndex(entries: Iterable<StackingEntry>): StackingIndex {
  const index: StackingIndex = new Map()
  for (const entry of entries) index.set(entry.object_id, entry)
  return index
}

export type HeightInfo = { height: number; source: 'override' | 'catalog'; elevation: number; layer: number; onTopOf: string[] }

/** Effective height: the floor plan's stacking row wins, otherwise the catalog default. */
export function effectiveHeight(asset: Pick<Asset, 'id' | 'type' | 'category'>, stacking: StackingIndex, entries: CatalogEntry[]): HeightInfo {
  const row = stacking.get(asset.id)
  if (row) return { height: row.height_m, source: row.height_source, elevation: row.elevation_m, layer: row.layer, onTopOf: [...row.on_top_of] }
  return { height: catalogHeight(entries, asset.type, asset.category), source: 'catalog', elevation: 0, layer: 0, onTopOf: [] }
}

/** Where an object on these supports sits: top of the highest support, one layer above it. */
export function supportLevel(supportIds: string[], assets: Map<string, Asset>, stacking: StackingIndex, entries: CatalogEntry[]): { elevation: number; layer: number } {
  let elevation = 0
  let layer = 0
  for (const id of supportIds) {
    const support = assets.get(id)
    if (!support) continue
    const info = effectiveHeight(support, stacking, entries)
    elevation = Math.max(elevation, info.elevation + info.height)
    layer = Math.max(layer, info.layer + 1)
  }
  return { elevation: round(elevation), layer }
}

/** Everything standing on `objectId`, transitively, sorted. */
export function descendantsOf(stacking: StackingIndex, objectId: string): string[] {
  const children = new Map<string, string[]>()
  for (const row of stacking.values()) {
    for (const support of row.on_top_of) children.set(support, [...(children.get(support) ?? []), row.object_id])
  }
  const found = new Set<string>()
  const queue = [...(children.get(objectId) ?? [])]
  while (queue.length) {
    const id = queue.shift()!
    if (found.has(id) || id === objectId) continue
    found.add(id)
    queue.push(...(children.get(id) ?? []))
  }
  return [...found].sort()
}

/* ------------------------------------------------------------------------
   Geometry
   ------------------------------------------------------------------------ */

export function round(value: number, step = 0.001): number {
  const digits = Math.max(0, Math.round(-Math.log10(step)))
  return Number((Math.round(value / step) * step).toFixed(digits))
}

export function nudge(point: Point, dx: number, dy: number): Point {
  return [round(point[0] + dx), round(point[1] + dy)]
}

export function normaliseRotation(degrees: number): number {
  const value = round(((degrees % 360) + 360) % 360)
  return value === 360 ? 0 : value
}

export function rotateBy(rotation: number, delta: number): number {
  return normaliseRotation(rotation + delta)
}

export type Footprint = { position: Point; width: number; depth: number; rotation: number }

export function assetFootprint(asset: Asset): Footprint {
  return { position: asset.position, width: asset.footprint.width_m, depth: asset.footprint.depth_m, rotation: asset.footprint.rotation_deg }
}

/** Corners counter-clockwise; rotation is counter-clockwise in plan coordinates (y up). */
export function footprintCorners(footprint: Footprint): Point[] {
  const radians = (footprint.rotation * Math.PI) / 180
  const cos = Math.cos(radians)
  const sin = Math.sin(radians)
  const halfW = footprint.width / 2
  const halfD = footprint.depth / 2
  return ([[-halfW, -halfD], [halfW, -halfD], [halfW, halfD], [-halfW, halfD]] as Point[]).map(([x, y]) => [
    footprint.position[0] + x * cos - y * sin,
    footprint.position[1] + x * sin + y * cos,
  ])
}

function toLocal(footprint: Footprint, point: Point): Point {
  const radians = (-footprint.rotation * Math.PI) / 180
  const dx = point[0] - footprint.position[0]
  const dy = point[1] - footprint.position[1]
  return [dx * Math.cos(radians) - dy * Math.sin(radians), dx * Math.sin(radians) + dy * Math.cos(radians)]
}

function fromLocal(footprint: Footprint, local: Point): Point {
  const radians = (footprint.rotation * Math.PI) / 180
  return [
    footprint.position[0] + local[0] * Math.cos(radians) - local[1] * Math.sin(radians),
    footprint.position[1] + local[0] * Math.sin(radians) + local[1] * Math.cos(radians),
  ]
}

export function pointInFootprint(footprint: Footprint, point: Point): boolean {
  const [x, y] = toLocal(footprint, point)
  return Math.abs(x) <= footprint.width / 2 + EPSILON && Math.abs(y) <= footprint.depth / 2 + EPSILON
}

export function clampToFootprint(footprint: Footprint, point: Point): Point {
  const [x, y] = toLocal(footprint, point)
  const local: Point = [Math.max(-footprint.width / 2, Math.min(footprint.width / 2, x)), Math.max(-footprint.depth / 2, Math.min(footprint.depth / 2, y))]
  return fromLocal(footprint, local)
}

/** Keep a stacked object's centre on its supports: unchanged inside, else the nearest support point. */
export function clampToSupports(point: Point, supports: Footprint[]): Point {
  if (supports.length === 0 || supports.some((support) => pointInFootprint(support, point))) return point
  let best = point
  let bestDistance = Number.POSITIVE_INFINITY
  for (const support of supports) {
    const candidate = clampToFootprint(support, point)
    const distance = Math.hypot(candidate[0] - point[0], candidate[1] - point[1])
    if (distance < bestDistance) {
      best = candidate
      bestDistance = distance
    }
  }
  return [round(best[0]), round(best[1])]
}

/** Area-weighted centre of the supports (the centre of their union when they do not overlap). */
export function supportCentre(supports: Footprint[]): Point | null {
  if (supports.length === 0) return null
  let total = 0
  let x = 0
  let y = 0
  for (const support of supports) {
    const area = Math.max(support.width * support.depth, 1e-6)
    total += area
    x += support.position[0] * area
    y += support.position[1] * area
  }
  return [round(x / total), round(y / total)]
}

function project(corners: Point[], axis: Point): [number, number] {
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY
  for (const [x, y] of corners) {
    const value = x * axis[0] + y * axis[1]
    min = Math.min(min, value)
    max = Math.max(max, value)
  }
  return [min, max]
}

/** Separating-axis test for two rotated rectangles. Touching edges do not count. */
export function footprintsOverlap(left: Footprint, right: Footprint): boolean {
  const a = footprintCorners(left)
  const b = footprintCorners(right)
  for (const corners of [a, b]) {
    for (let index = 0; index < 2; index += 1) {
      const [x1, y1] = corners[index]
      const [x2, y2] = corners[index + 1]
      const axis: Point = [y1 - y2, x2 - x1]
      const [minA, maxA] = project(a, axis)
      const [minB, maxB] = project(b, axis)
      if (maxA <= minB + 1e-9 || maxB <= minA + 1e-9) return false
    }
  }
  return true
}

export function polygonArea(polygon: Point[]): number {
  let sum = 0
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index]
    const [x2, y2] = polygon[(index + 1) % polygon.length]
    sum += x1 * y2 - x2 * y1
  }
  return Math.abs(sum) / 2
}

export function pointInPolygon(polygon: Point[], point: Point): boolean {
  let inside = false
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const [x, y] = polygon[index]
    const [previousX, previousY] = polygon[previous]
    const crosses = (y > point[1]) !== (previousY > point[1])
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x
    if (crosses) inside = !inside
  }
  return inside
}

function closestOnSegment(point: Point, start: Point, end: Point): Point {
  const dx = end[0] - start[0]
  const dy = end[1] - start[1]
  const length = dx * dx + dy * dy
  const t = length === 0 ? 0 : Math.max(0, Math.min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length))
  return [start[0] + t * dx, start[1] + t * dy]
}

export function closestOnBoundary(polygon: Point[], point: Point): { point: Point; distance: number } {
  let best: Point = polygon[0] ?? point
  let bestDistance = Number.POSITIVE_INFINITY
  for (let index = 0; index < polygon.length; index += 1) {
    const candidate = closestOnSegment(point, polygon[index], polygon[(index + 1) % polygon.length])
    const distance = Math.hypot(candidate[0] - point[0], candidate[1] - point[1])
    if (distance < bestDistance) {
      best = candidate
      bestDistance = distance
    }
  }
  return { point: best, distance: bestDistance }
}

/** The room that owns a point: the smallest-area room that contains it (spec 4.3 rule 1). */
export function spaceAt(spaces: Space[], point: Point): Space | null {
  let best: Space | null = null
  let bestArea = Number.POSITIVE_INFINITY
  for (const space of spaces) {
    if (space.polygon.length < 3 || !pointInPolygon(space.polygon, point)) continue
    const area = polygonArea(space.polygon)
    if (area < bestArea) {
      best = space
      bestArea = area
    }
  }
  return best
}

/** A point inside the polygon: the area centroid, or the middle of the widest horizontal chord. */
export function interiorPoint(polygon: Point[]): Point {
  if (polygon.length === 0) return [0, 0]
  let area = 0
  let cx = 0
  let cy = 0
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index]
    const [x2, y2] = polygon[(index + 1) % polygon.length]
    const cross = x1 * y2 - x2 * y1
    area += cross
    cx += (x1 + x2) * cross
    cy += (y1 + y2) * cross
  }
  const centroid: Point = Math.abs(area) < 1e-9
    ? [polygon.reduce((sum, [x]) => sum + x, 0) / polygon.length, polygon.reduce((sum, [, y]) => sum + y, 0) / polygon.length]
    : [cx / (3 * area), cy / (3 * area)]
  if (pointInPolygon(polygon, centroid)) return [round(centroid[0]), round(centroid[1])]
  const y = centroid[1]
  const crossings: number[] = []
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index]
    const [x2, y2] = polygon[(index + 1) % polygon.length]
    if ((y1 > y) !== (y2 > y)) crossings.push(x1 + ((y - y1) * (x2 - x1)) / (y2 - y1))
  }
  crossings.sort((left, right) => left - right)
  let best: Point = centroid
  let widest = -1
  for (let index = 0; index + 1 < crossings.length; index += 2) {
    const width = crossings[index + 1] - crossings[index]
    if (width > widest) {
      widest = width
      best = [(crossings[index] + crossings[index + 1]) / 2, y]
    }
  }
  return [round(best[0]), round(best[1])]
}

/** Every corner and edge midpoint lies in the room, or within the tolerance of its outline. */
export function footprintInside(polygon: Point[], footprint: Footprint, tolerance = PLACEMENT_TOLERANCE_M): boolean {
  const corners = footprintCorners(footprint)
  const samples = [...corners, ...corners.map((corner, index) => {
    const next = corners[(index + 1) % corners.length]
    return [(corner[0] + next[0]) / 2, (corner[1] + next[1]) / 2] as Point
  })]
  return samples.every((sample) => pointInPolygon(polygon, sample) || closestOnBoundary(polygon, sample).distance <= tolerance)
}

/** Two different rooms whose outlines are both near the point: a wall between them. */
export function wallAt(spaces: Space[], point: Point, tolerance = WALL_TOLERANCE_M): { spaces: [Space, Space]; snapped: Point } | null {
  const near = spaces
    .filter((space) => space.polygon.length >= 3)
    .map((space) => ({ space, ...closestOnBoundary(space.polygon, point) }))
    .filter((item) => item.distance <= tolerance)
    .sort((left, right) => left.distance - right.distance)
  if (near.length < 2) return null
  const [first, second] = near
  return { spaces: [first.space, second.space], snapped: [round((first.point[0] + second.point[0]) / 2), round((first.point[1] + second.point[1]) / 2)] }
}

/* ------------------------------------------------------------------------
   Drafts and proposals (spec 4.2)
   ------------------------------------------------------------------------ */

export type ObjectDraft = {
  target: 'object'
  objectId: string | null
  type: string
  category: string
  name: string
  floorId: string
  position: Point | null
  rotation: number
  width: number
  depth: number
  /** null = no override, the catalog default applies. */
  height: number | null
  onTopOf: string[]
}

export type OpeningDraft = {
  target: 'opening'
  openingId: string | null
  kind: OpeningKind
  floorId: string
  position: Point | null
  /** Keyboard path: two rooms instead of a wall click. */
  firstSpace: string | null
  secondSpace: string | null
  width: number
  stepFree: boolean
}

export type ConnectorStop = { id: string; floorId: string }

export type ConnectorDraft = {
  target: 'connector'
  connectorId: string | null
  kind: ConnectorKind
  name: string
  stepFree: boolean
  spaces: ConnectorStop[]
}

export type Draft = ObjectDraft | OpeningDraft | ConnectorDraft

export function newObjectDraft(entry: CatalogEntry, floorId: string, position: Point | null): ObjectDraft {
  const size = catalogSize(entry)
  return { target: 'object', objectId: null, type: entry.type.id, category: entry.categoryId, name: '', floorId, position, rotation: 0, width: size.width, depth: size.depth, height: null, onTopOf: [] }
}

export function draftFromAsset(asset: Asset, stacking: StackingIndex): ObjectDraft {
  const row = stacking.get(asset.id)
  return {
    target: 'object',
    objectId: asset.id,
    type: asset.type,
    category: asset.category,
    name: asset.name,
    floorId: asset.floor_id,
    position: [asset.position[0], asset.position[1]],
    rotation: asset.footprint.rotation_deg,
    width: asset.footprint.width_m,
    depth: asset.footprint.depth_m,
    height: row?.height_source === 'override' ? row.height_m : null,
    onTopOf: [...(row?.on_top_of ?? [])].sort(),
  }
}

export function newOpeningDraft(kind: OpeningKind, entries: CatalogEntry[], floorId: string): OpeningDraft {
  const entry = entries.find((item) => item.type.action === 'add_opening' && item.type.id === kind)
  return { target: 'opening', openingId: null, kind, floorId, position: null, firstSpace: null, secondSpace: null, width: entry?.type.width_m ?? (kind === 'door' ? DOOR_WIDTH_M : 1.2), stepFree: true }
}

export function draftFromOpening(opening: Opening): OpeningDraft {
  const kind: OpeningKind = opening.kind === 'opening' ? 'opening' : 'door'
  return { target: 'opening', openingId: opening.id, kind, floorId: opening.floor_id, position: opening.position, firstSpace: opening.space_ids[0] ?? null, secondSpace: opening.space_ids[1] ?? null, width: opening.width_m, stepFree: opening.step_free }
}

export function newConnectorDraft(kind: ConnectorKind): ConnectorDraft {
  return { target: 'connector', connectorId: null, kind, name: '', stepFree: kind === 'lift', spaces: [] }
}

/** Add a stop, or remove it when picked again. One stop per floor: a new pick replaces that floor's stop. */
export function toggleStop(stops: ConnectorStop[], stop: ConnectorStop): ConnectorStop[] {
  if (stops.some((item) => item.id === stop.id)) return stops.filter((item) => item.id !== stop.id)
  return [...stops.filter((item) => item.floorId !== stop.floorId), stop]
}

function changed(left: number, right: number): boolean {
  return Math.abs(left - right) > EPSILON
}

function sameIds(left: string[], right: string[]): boolean {
  const a = [...left].sort()
  const b = [...right].sort()
  return a.length === b.length && a.every((id, index) => id === b[index])
}

function roundPoint(point: Point): Point {
  return [round(point[0]), round(point[1])]
}

function addObjectProposal(draft: ObjectDraft): AddObjectProposal | null {
  if (!draft.position && draft.onTopOf.length === 0) return null
  const proposal: AddObjectProposal = {
    kind: 'add_object',
    type: draft.type,
    category: draft.category,
    rotation_deg: normaliseRotation(draft.rotation),
    width_m: round(draft.width),
    depth_m: round(draft.depth),
    on_top_of: [...draft.onTopOf].sort(),
  }
  if (draft.name.trim()) proposal.name = draft.name.trim()
  if (draft.position) {
    proposal.floor_id = draft.floorId
    proposal.position = roundPoint(draft.position)
  }
  if (draft.height != null) proposal.height_m = round(draft.height)
  return proposal
}

function updateObjectProposal(original: ObjectDraft, draft: ObjectDraft): UpdateObjectProposal | null {
  const proposal: UpdateObjectProposal = { kind: 'update_object', object_ref: original.objectId ?? '' }
  const name = draft.name.trim()
  if (name && name !== original.name) proposal.name = name
  if (draft.type !== original.type || draft.category !== original.category) {
    proposal.type = draft.type
    proposal.category = draft.category
  }
  if (draft.floorId !== original.floorId) proposal.floor_id = draft.floorId
  if (draft.position && (!original.position || changed(draft.position[0], original.position[0]) || changed(draft.position[1], original.position[1]))) {
    proposal.position = roundPoint(draft.position)
    proposal.floor_id = draft.floorId
  }
  if (changed(normaliseRotation(draft.rotation), normaliseRotation(original.rotation))) proposal.rotation_deg = normaliseRotation(draft.rotation)
  if (changed(draft.width, original.width)) proposal.width_m = round(draft.width)
  if (changed(draft.depth, original.depth)) proposal.depth_m = round(draft.depth)
  if (draft.height != null && (original.height == null || changed(draft.height, original.height))) proposal.height_m = round(draft.height)
  if (!sameIds(draft.onTopOf, original.onTopOf)) proposal.on_top_of = [...draft.onTopOf].sort()
  return Object.keys(proposal).length > 2 ? proposal : null
}

function addOpeningProposal(draft: OpeningDraft): AddOpeningProposal | null {
  const proposal: AddOpeningProposal = { kind: 'add_opening', opening_kind: draft.kind, width_m: round(draft.width), step_free: draft.stepFree }
  if (draft.firstSpace && draft.secondSpace && draft.firstSpace !== draft.secondSpace && !draft.position) {
    proposal.first_space = draft.firstSpace
    proposal.second_space = draft.secondSpace
    return proposal
  }
  if (!draft.position) return null
  proposal.floor_id = draft.floorId
  proposal.position = roundPoint(draft.position)
  return proposal
}

function updateOpeningProposal(original: OpeningDraft, draft: OpeningDraft): UpdateObjectProposal | null {
  const proposal: UpdateObjectProposal = { kind: 'update_object', object_ref: original.openingId ?? '' }
  if (draft.kind !== original.kind) proposal.opening_kind = draft.kind
  if (changed(draft.width, original.width)) proposal.width_m = round(draft.width)
  if (draft.stepFree !== original.stepFree) proposal.step_free = draft.stepFree
  return Object.keys(proposal).length > 2 ? proposal : null
}

function addConnectorProposal(draft: ConnectorDraft): AddConnectorProposal | null {
  if (draft.spaces.length < 2) return null
  const proposal: AddConnectorProposal = { kind: 'add_connector', connector_kind: draft.kind, spaces: draft.spaces.map((stop) => stop.id) }
  if (draft.name.trim()) proposal.name = draft.name.trim()
  // Stairs and escalators are never step-free; only a lift takes the flag.
  if (draft.kind === 'lift') proposal.step_free = draft.stepFree
  return proposal
}

function updateConnectorProposal(original: ConnectorDraft, draft: ConnectorDraft): UpdateObjectProposal | null {
  const proposal: UpdateObjectProposal = { kind: 'update_object', object_ref: original.connectorId ?? '' }
  const name = draft.name.trim()
  if (name && name !== original.name) proposal.name = name
  if (draft.kind === 'lift' && draft.stepFree !== original.stepFree) proposal.step_free = draft.stepFree
  return Object.keys(proposal).length > 2 ? proposal : null
}

/** Proposal for a draft. With an original only changed fields are sent; null = nothing to save. */
export function buildProposal(draft: Draft, original: Draft | null): EditProposal | null {
  if (draft.target === 'object') return original?.target === 'object' ? updateObjectProposal(original, draft) : addObjectProposal(draft)
  if (draft.target === 'opening') return original?.target === 'opening' ? updateOpeningProposal(original, draft) : addOpeningProposal(draft)
  return original?.target === 'connector' ? updateConnectorProposal(original, draft) : addConnectorProposal(draft)
}

export function removeProposal(objectRef: string): EditProposal {
  return { kind: 'remove_object', object_ref: objectRef }
}

export function undoProposal(): EditProposal {
  return { kind: 'undo_edit' }
}

/** A new draft is always unsaved; an existing one only when a field differs. */
export function isDirty(draft: Draft | null, original: Draft | null): boolean {
  if (!draft) return false
  if (!original) return true
  return buildProposal(draft, original) !== null
}

/** Only openings and connectors added in this session can be removed (spec 4.3 rule 12). */
export function isRemovableConnection(element: { id: string; synthetic: boolean }): boolean {
  return element.synthetic && element.id.includes('-new')
}

export type SupportOption = { asset: Asset; distance: number | null }

/**
 * "Stands on" options: objects on the draft's floor matching name or type, nearest first.
 * The object itself and everything standing on it are excluded (no cycles).
 */
export function supportCandidates(assets: Asset[], draft: ObjectDraft, excluded: Set<string>, query: string, limit = 8): SupportOption[] {
  const words = normalise(query).split(' ').filter(Boolean)
  const options: SupportOption[] = []
  for (const asset of assets) {
    if (asset.floor_id !== draft.floorId || asset.id === draft.objectId || excluded.has(asset.id)) continue
    const haystack = normalise(`${asset.name} ${asset.type}`)
    if (!words.every((word) => haystack.includes(word))) continue
    const distance = draft.position ? Math.hypot(asset.position[0] - draft.position[0], asset.position[1] - draft.position[1]) : null
    options.push({ asset, distance })
  }
  options.sort((left, right) => (left.distance ?? 0) - (right.distance ?? 0) || left.asset.name.localeCompare(right.asset.name))
  return options.slice(0, limit)
}

/** Floors to reload after a confirmed action, or null when it did not change the building. */
export function editedFloors(action: Pick<Action, 'result'>): { summary: string | null; floorIds: string[] } | null {
  const result = action.result
  if (!result) return null
  if (Array.isArray(result.floor_ids)) {
    return { summary: typeof result.summary === 'string' ? result.summary : null, floorIds: result.floor_ids.filter((id): id is string => typeof id === 'string') }
  }
  const opening = result.opening as { floor_id?: unknown } | undefined
  if (result.kind === 'add_door' && typeof opening?.floor_id === 'string') return { summary: null, floorIds: [opening.floor_id] }
  return null
}

/* ------------------------------------------------------------------------
   Validity hints and error copy
   ------------------------------------------------------------------------ */

export type PlacementHint =
  | 'invalid_size'
  | 'no_position'
  | 'outside_space'
  | 'crosses_wall'
  | 'floating'
  | 'support_other_space'
  | 'exceeds_ceiling'

export type HintContext = {
  spaces: Space[]
  assets: Map<string, Asset>
  floorHeight: number | null
  /** Bottom of the object above the floor. */
  elevation: number
  /** Effective height of the object. */
  height: number
}

/** Client-side hint in the server's rule order. The server still decides. */
export function placementHint(draft: ObjectDraft, context: HintContext): PlacementHint | null {
  const sizes = [draft.width, draft.depth, context.height]
  if (sizes.some((value) => !Number.isFinite(value) || value <= 0)) return 'invalid_size'
  if (!draft.position) return 'no_position'
  const space = spaceAt(context.spaces, draft.position)
  if (!space) return 'outside_space'
  const footprint: Footprint = { position: draft.position, width: draft.width, depth: draft.depth, rotation: draft.rotation }
  if (!footprintInside(space.polygon, footprint)) return 'crosses_wall'
  if (draft.onTopOf.length > 0) {
    const supports = draft.onTopOf.map((id) => context.assets.get(id)).filter((item): item is Asset => Boolean(item))
    if (supports.length !== draft.onTopOf.length) return 'floating'
    if (supports.some((support) => support.floor_id !== draft.floorId || spaceAt(context.spaces, support.position)?.id !== space.id)) return 'support_other_space'
    const prints = supports.map(assetFootprint)
    if (!prints.some((print) => pointInFootprint(print, draft.position!))) return 'floating'
    if (!prints.every((print) => footprintsOverlap(print, footprint))) return 'floating'
  }
  if (context.floorHeight != null && context.floorHeight > 0 && context.elevation + context.height > context.floorHeight + EPSILON) return 'exceeds_ceiling'
  return null
}

export type ErrorTexts = {
  codes: Record<string, string>
  placement: Record<string, string>
  fields: Record<string, string>
  checkField: string
  fallback: string
}

export type EditError = { code: string | null; message?: string; details?: { field?: string; code?: string }[] }

/** One clear sentence for an API error: placement reason first, then the error code. */
export function describeEditError(error: EditError, texts: ErrorTexts): string {
  const details = error.details ?? []
  if (error.code === '30014_invalid_placement') {
    const reason = details.map((detail) => detail.code).find((code): code is string => Boolean(code && texts.placement[code]))
    return reason ? texts.placement[reason] : texts.codes[error.code]
  }
  if (error.code === '20001_validation_failed') {
    const field = details.map((detail) => detail.field).find((item): item is string => Boolean(item))
    if (field) {
      const key = field.split('.').at(-1) ?? field
      return texts.checkField.replace('{field}', texts.fields[key] ?? key.replaceAll('_', ' '))
    }
  }
  if (error.code && texts.codes[error.code]) return texts.codes[error.code]
  return error.message || texts.fallback
}
