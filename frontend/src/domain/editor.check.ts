import {
  buildProposal,
  catalogHeight,
  clampToSupports,
  describeEditError,
  descendantsOf,
  draftFromAsset,
  editedFloors,
  effectiveHeight,
  findObjectEntry,
  flattenCatalog,
  interiorPoint,
  isDirty,
  newConnectorDraft,
  newObjectDraft,
  newOpeningDraft,
  nudge,
  placementHint,
  pointInFootprint,
  pushRecent,
  rotateBy,
  searchCatalog,
  spaceAt,
  stackingIndex,
  supportCentre,
  supportCandidates,
  supportLevel,
  toggleStop,
  wallAt,
} from './editor.ts'
import type { Asset, ObjectCatalog, Space, StackingEntry } from './types.ts'

let checks = 0
function expect(condition: unknown, message: string): void {
  checks += 1
  if (!condition) throw new Error(message)
}
/** JSON with sorted object keys, so field order does not matter. */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)))
    : item)
}
function same(actual: unknown, expected: unknown, message: string): void {
  expect(canonical(actual) === canonical(expected), `${message}: got ${canonical(actual)}, want ${canonical(expected)}`)
}

const catalog: ObjectCatalog = {
  schema_version: 1,
  groups: [
    { id: 'items', label: 'Items', categories: [
      { id: 'furniture', label: 'Furniture', types: [
        { id: 'desk', label: 'Desk', action: 'add_object', width_m: 1.4, depth_m: 0.7, height_m: 0.75, count: 2453 },
        { id: 'reception_desk', label: 'Reception desk', action: 'add_object', width_m: 2, depth_m: 0.8, height_m: null, count: 10 },
        { id: 'washing_machine', label: 'Washing machine', action: 'add_object', width_m: 0.6, depth_m: 0.6, height_m: 0.85, count: 3 },
      ] },
      { id: 'equipment', label: 'Equipment', types: [
        { id: 'printer', label: 'Printer', action: 'add_object', width_m: 0.6, depth_m: 0.5, height_m: 0.5, count: 14 },
        { id: 'washing_machine', label: 'Washing machine', action: 'add_object', width_m: 0.6, depth_m: 0.6, height_m: 0.9, count: 38 },
      ] },
    ] },
    { id: 'connections', label: 'Connections', categories: [
      { id: 'same_floor', label: 'Same floor', types: [
        { id: 'door', label: 'Door', action: 'add_opening', width_m: 0.9, depth_m: null, height_m: null, count: 0 },
        { id: 'opening', label: 'Passage', action: 'add_opening', width_m: 1.25, depth_m: null, height_m: null, count: 0 },
      ] },
      { id: 'between_floors', label: 'Between floors', types: [
        { id: 'lift', label: 'Lift', action: 'add_connector', width_m: null, depth_m: null, height_m: null, count: 0 },
      ] },
    ] },
  ],
}

/* Catalog flatten and search */
const entries = flattenCatalog(catalog)
same(entries.length, 8, 'flatten keeps every type in every category')
same(searchCatalog(entries, 'desk').map((entry) => entry.key), ['items/furniture/desk', 'items/furniture/reception_desk'], 'exact label first, then other matches')
same(searchCatalog(entries, 'DESK ').map((entry) => entry.type.id)[0], 'desk', 'search ignores case and spaces')
same(searchCatalog(entries, 'equipment').map((entry) => entry.type.id), ['washing_machine', 'printer'], 'category label matches its types, common first')
same(searchCatalog(entries, 'passage').map((entry) => entry.key), ['connections/same_floor/opening'], 'connections are searchable by label')
same(searchCatalog(entries, 'washing_machine').length, 2, 'type ids with underscores match')
same(searchCatalog(entries, 'furniture wash').map((entry) => entry.key), ['items/furniture/washing_machine'], 'all words must match across levels')
same(searchCatalog(entries, '   '), [], 'blank query has no results')
same(findObjectEntry(entries, 'washing_machine')?.categoryId, 'equipment', 'without category the larger count wins')
same(findObjectEntry(entries, 'washing_machine', 'furniture')?.categoryId, 'furniture', 'given category wins')
same(pushRecent(['a', 'b', 'c', 'd', 'e'], 'c'), ['c', 'a', 'b', 'd', 'e'], 'recent moves a repeat to the front')
same(pushRecent(['a', 'b', 'c', 'd', 'e'], 'f'), ['f', 'a', 'b', 'c', 'd'], 'recent keeps five')

/* Heights */
same(catalogHeight(entries, 'desk', 'furniture'), 0.75, 'catalog height of a type')
same(catalogHeight(entries, 'washing_machine', 'equipment'), 0.9, 'catalog height per category')
same(catalogHeight(entries, 'reception_desk', 'furniture'), 0.8, 'missing type height falls back to the category')
same(catalogHeight(entries, 'unknown', 'machine'), 1.8, 'unknown type falls back to the category')
same(catalogHeight(entries, 'unknown', 'other'), 1, 'unknown category falls back to 1 m')

function asset(id: string, position: [number, number], width: number, depth: number, rotation = 0, type = 'desk', category = 'furniture'): Asset {
  return { id, name: id, category, type, space_id: 's1', floor_id: 'f0', position, footprint: { width_m: width, depth_m: depth, rotation_deg: rotation }, source: 'user_edit' }
}
const desk = asset('desk', [2, 2], 1.4, 0.7)
const laptop = asset('laptop', [2.2, 2], 0.3, 0.2, 0, 'laptop', 'equipment')
const mug = asset('mug', [2.25, 2], 0.1, 0.1, 0, 'mug', 'equipment')
const rows: StackingEntry[] = [
  { object_id: 'desk', layer: 0, on_top_of: [], height_m: 0.9, height_source: 'override', elevation_m: 0 },
  { object_id: 'laptop', layer: 1, on_top_of: ['desk'], height_m: 0.03, height_source: 'catalog', elevation_m: 0.9 },
  { object_id: 'mug', layer: 2, on_top_of: ['laptop'], height_m: 0.1, height_source: 'catalog', elevation_m: 0.93 },
]
const stacking = stackingIndex(rows)
same(effectiveHeight(desk, stacking, entries), { height: 0.9, source: 'override', elevation: 0, layer: 0, onTopOf: [] }, 'override height comes from stacking')
same(effectiveHeight(laptop, stacking, entries).elevation, 0.9, 'stacked object keeps its elevation')
same(effectiveHeight(asset('chair', [0, 0], 0.5, 0.5, 0, 'desk'), stacking, entries), { height: 0.75, source: 'catalog', elevation: 0, layer: 0, onTopOf: [] }, 'unlisted object uses catalog height')
const assets = new Map([desk, laptop, mug].map((item) => [item.id, item]))
same(supportLevel(['desk'], assets, stacking, entries), { elevation: 0.9, layer: 1 }, 'sits on top of the override height')
same(supportLevel(['laptop'], assets, stacking, entries), { elevation: 0.93, layer: 2 }, 'sits on top of a stacked support')
same(supportLevel([], assets, stacking, entries), { elevation: 0, layer: 0 }, 'no supports = on the floor')
same(descendantsOf(stacking, 'desk'), ['laptop', 'mug'], 'descendants are transitive and sorted')

/* Nudge, rotate, clamp */
same(nudge([1, 1], 0.1, 0), [1.1, 1], 'nudge rounds float noise')
same(nudge([0.3, 0.2], -0.1, -0.1), [0.2, 0.1], 'nudge in both axes')
same(rotateBy(350, 15), 5, 'rotation wraps above 360')
same(rotateBy(0, -15), 345, 'rotation wraps below 0')
const deskPrint = { position: desk.position, width: 1.4, depth: 0.7, rotation: 0 }
same(clampToSupports([2.1, 2.1], [deskPrint]), [2.1, 2.1], 'a point on the support stays')
same(clampToSupports([5, 2], [deskPrint]), [2.7, 2], 'a point off the support snaps to its edge')
same(clampToSupports([5, 5], []), [5, 5], 'no supports = no clamp')
const turned = { position: [0, 0] as [number, number], width: 2, depth: 1, rotation: 90 }
expect(pointInFootprint(turned, [0, 0.9]) && !pointInFootprint(turned, [0.9, 0]), 'rotation turns the footprint counter-clockwise')
same(clampToSupports([3, 0], [turned]), [0.5, 0], 'clamp respects rotation')
same(supportCentre([deskPrint, { position: [6, 2], width: 1.4, depth: 0.7, rotation: 0 }]), [4, 2], 'centre of two equal supports')

/* Rooms and walls */
const office: Space = { id: 's1', floor_id: 'f0', type: 'room', room_type: 'office', name: 'Office', ref: null, polygon: [[0, 0], [5, 0], [5, 4], [0, 4]], synthetic: false }
const corridor: Space = { id: 's2', floor_id: 'f0', type: 'room', room_type: 'corridor', name: 'Corridor', ref: null, polygon: [[5, 0], [8, 0], [8, 4], [5, 4]], synthetic: false }
const closet: Space = { id: 's3', floor_id: 'f0', type: 'room', room_type: 'storage', name: 'Closet', ref: null, polygon: [[0, 0], [1, 0], [1, 1], [0, 1]], synthetic: false }
const lShape: Point[] = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4]]
type Point = [number, number]
same(spaceAt([office, corridor, closet], [0.5, 0.5])?.id, 's3', 'smallest containing room wins')
same(spaceAt([office, corridor], [9, 9]), null, 'outside every room')
const inside = interiorPoint(lShape)
expect(spaceAt([{ ...office, polygon: lShape }], inside) !== null, 'interior point of an L-shaped room is inside it')
same(wallAt([office, corridor], [5.1, 2])?.spaces.map((space) => space.id).sort(), ['s1', 's2'], 'wall click finds both rooms')
same(wallAt([office, corridor], [5.1, 2])?.snapped, [5, 2], 'wall click snaps onto the wall')
same(wallAt([office, corridor], [2.5, 2]), null, 'room middle is no wall')

/* Placement hints */
const context = { spaces: [office, corridor], assets, floorHeight: 3, elevation: 0, height: 0.75 }
const fresh = newObjectDraft(entries[0], 'f0', [2, 2])
same(placementHint(fresh, context), null, 'desk inside the office is fine')
same(placementHint({ ...fresh, position: [4.8, 2] }, context), 'crosses_wall', 'desk over the wall')
same(placementHint({ ...fresh, position: [9, 9] }, context), 'outside_space', 'desk outside')
same(placementHint({ ...fresh, position: null }, context), 'no_position', 'unplaced')
same(placementHint({ ...fresh, width: 0 }, context), 'invalid_size', 'zero width')
const onDesk = { ...newObjectDraft(entries[3], 'f0', [2.2, 2]), onTopOf: ['desk'] }
same(placementHint(onDesk, { ...context, elevation: 0.9, height: 0.5 }), null, 'printer on the desk')
same(placementHint({ ...onDesk, position: [4, 3] }, { ...context, elevation: 0.9, height: 0.5 }), 'floating', 'printer beside the desk floats')
same(placementHint(onDesk, { ...context, elevation: 0.9, height: 2.5 }), 'exceeds_ceiling', 'too tall for the floor')

/* Proposals */
same(buildProposal(fresh, null), { kind: 'add_object', type: 'desk', category: 'furniture', rotation_deg: 0, width_m: 1.4, depth_m: 0.7, on_top_of: [], floor_id: 'f0', position: [2, 2] }, 'add_object leaves out name and height by default')
same(buildProposal({ ...fresh, name: ' Desk A ', height: 0.9, rotation: 375 }, null), { kind: 'add_object', type: 'desk', category: 'furniture', rotation_deg: 15, width_m: 1.4, depth_m: 0.7, on_top_of: [], name: 'Desk A', floor_id: 'f0', position: [2, 2], height_m: 0.9 }, 'add_object sends name and custom height')
same(buildProposal({ ...fresh, position: null }, null), null, 'unplaced add has no proposal')
const original = draftFromAsset(laptop, stacking)
same(original.onTopOf, ['desk'], 'edit draft reads supports')
same(original.height, null, 'catalog height is no override')
same(draftFromAsset(desk, stacking).height, 0.9, 'override height is kept')
same(buildProposal(original, original), null, 'unchanged edit has no proposal')
expect(!isDirty(original, original) && isDirty({ ...original, rotation: 15 }, original), 'dirty only after a change')
same(buildProposal({ ...original, position: [2.3, 2.0000001], onTopOf: [] }, original), { kind: 'update_object', object_ref: 'laptop', floor_id: 'f0', position: [2.3, 2], on_top_of: [] }, 'update sends only changed fields')
same(buildProposal({ ...original, height: 0.04, width: 0.35 }, original), { kind: 'update_object', object_ref: 'laptop', width_m: 0.35, height_m: 0.04 }, 'update sends a new height override')
same(buildProposal({ ...draftFromAsset(desk, stacking), height: 0.9 }, draftFromAsset(desk, stacking)), null, 'same override height is unchanged')
same(buildProposal({ ...newOpeningDraft('door', entries, 'f0'), position: [5.04, 2] }, null), { kind: 'add_opening', opening_kind: 'door', width_m: 0.9, step_free: true, floor_id: 'f0', position: [5.04, 2] }, 'door from a wall click')
same(buildProposal({ ...newOpeningDraft('opening', entries, 'f0'), firstSpace: 's1', secondSpace: 's2' }, null), { kind: 'add_opening', opening_kind: 'opening', width_m: 1.25, step_free: true, first_space: 's1', second_space: 's2' }, 'passage between two chosen rooms')
same(buildProposal(newOpeningDraft('door', entries, 'f0'), null), null, 'door without wall or rooms')
const stairs = { ...newConnectorDraft('stairs'), spaces: [{ id: 'a', floorId: 'f0' }, { id: 'b', floorId: 'f1' }] }
same(buildProposal(stairs, null), { kind: 'add_connector', connector_kind: 'stairs', spaces: ['a', 'b'] }, 'stairs never send step_free')
same(buildProposal({ ...stairs, kind: 'lift', stepFree: true, name: 'Lift East' }, null), { kind: 'add_connector', connector_kind: 'lift', spaces: ['a', 'b'], name: 'Lift East', step_free: true }, 'lift sends step_free and name')
same(buildProposal({ ...stairs, spaces: stairs.spaces.slice(0, 1) }, null), null, 'one stop is not enough')
same(toggleStop([{ id: 'a', floorId: 'f0' }], { id: 'c', floorId: 'f0' }), [{ id: 'c', floorId: 'f0' }], 'one stop per floor')
same(toggleStop([{ id: 'a', floorId: 'f0' }], { id: 'a', floorId: 'f0' }), [], 'picking a stop again removes it')

/* Support options */
const chair = asset('chair', [9, 9], 0.5, 0.5, 0, 'chair')
const options = supportCandidates([desk, laptop, mug, chair, { ...chair, id: 'upstairs', floor_id: 'f1' }], { ...original, position: [2.2, 2] }, new Set(descendantsOf(stacking, 'laptop')), '')
same(options.map((option) => option.asset.id), ['desk', 'chair'], 'supports exclude self, things on top and other floors; nearest first')
same(supportCandidates([desk, chair], fresh, new Set(), 'CHA').map((option) => option.asset.id), ['chair'], 'supports filter by name or type')

/* Results and errors */
same(editedFloors({ result: { kind: 'add_object', summary: 'Add Desk.', changed_ids: ['x'], removed_ids: [], floor_ids: ['f0', 'f1'] } }), { summary: 'Add Desk.', floorIds: ['f0', 'f1'] }, 'edit result floors')
same(editedFloors({ result: { kind: 'add_door', opening: { floor_id: 'f2' } } }), { summary: null, floorIds: ['f2'] }, 'legacy door result floor')
same(editedFloors({ result: { kind: 'set_closed', closed_ids: ['v'] } }), null, 'closures are no edit')
const texts = {
  codes: { '30014_invalid_placement': 'Not here.', '30015_nothing_to_undo': 'Nothing to undo.', '20001_validation_failed': 'Invalid.' },
  placement: { crosses_wall: 'It crosses a wall.' },
  fields: { height_m: 'Height' },
  checkField: 'Check {field}.',
  fallback: 'Failed.',
}
same(describeEditError({ code: '30014_invalid_placement', details: [{ code: 'crosses_wall' }] }, texts), 'It crosses a wall.', 'placement reason wins')
same(describeEditError({ code: '30014_invalid_placement', details: [] }, texts), 'Not here.', 'placement without reason')
same(describeEditError({ code: '20001_validation_failed', details: [{ field: 'body.height_m', code: 'greater_than' }] }, texts), 'Check Height.', 'validation names the field')
same(describeEditError({ code: '30015_nothing_to_undo' }, texts), 'Nothing to undo.', 'known code')
same(describeEditError({ code: '99999_new', message: 'Server says no.' }, texts), 'Server says no.', 'unknown code keeps the server message')

console.log(`editor check ok (${checks} checks)`)
