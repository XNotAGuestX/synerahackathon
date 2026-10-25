import { buildPresentation } from './presentation.ts'
import type { ViewEffect } from './types.ts'

const effects: ViewEffect[] = [
  { type: 'highlight_spaces', space_ids: ['s1'], reason: 'match' },
  { type: 'highlight_assets', asset_ids: ['a1'] },
  { type: 'focus', floor_id: 'f0', floor_level: 0, point: [1, 2] },
  { type: 'draw_route', route_id: 'r1' },
  { type: 'set_closures', closed_ids: ['v1'] },
  { type: 'ask', question: 'Which desk?', options: [{ id: 'a', label: 'Desk' }] },
  { type: 'building_patched', floor_ids: ['f0'] },
  { type: 'clear_route' },
  { type: 'preview_objects', floor_ids: ['f0'], assets: [{ id: 'a9', name: 'Desk', category: 'furniture', type: 'desk', space_id: 's1', floor_id: 'f0', position: [1, 2], footprint: { width_m: 1.4, depth_m: 0.7, rotation_deg: 0 }, source: 'user_edit' }, { id: 'broken' }], openings: [], connectors: [], removed_ids: ['a2'] },
  { type: 'unknown_widget', note: 'ignore me' },
]

const shown = buildPresentation({
  guideText: 'Shown',
  understood: null,
  effects,
  routes: [{ id: 'r1', reachable: true, length_m: 10, step_free: true, via: [], closed_ids: [], start_space_id: 's', destination_space_id: 'd', directions: [], legs: [] }],
  pendingSummary: null,
  decision: null,
  confirmedEffects: [],
  confirmedClosedIds: [],
  confirmedText: '',
  cancelledText: '',
})

if (shown.route !== null) throw new Error('clear_route should remove the route')
if (!shown.spaceReasons.has('s1') || !shown.assetIds.has('a1')) throw new Error('highlights were dropped')
if (shown.focusFloorId !== 'f0' || shown.asks.length !== 1) throw new Error('focus or ask was dropped')
if (shown.patchedFloorIds.join() !== 'f0') throw new Error('building_patched was dropped')
if (!shown.unknownEffectTypes.includes('unknown_widget')) throw new Error('unknown effect should be recorded and skipped')
if (shown.closedIds.join() !== 'v1') throw new Error('closures were dropped')
if (shown.previewObjects?.assets.map((asset) => asset.id).join() !== 'a9') throw new Error('preview_objects ghosts were dropped or not validated')
if (shown.previewObjects?.removedIds.join() !== 'a2' || shown.unknownEffectTypes.includes('preview_objects')) throw new Error('preview_objects removals were dropped')
console.log('effects check ok')
