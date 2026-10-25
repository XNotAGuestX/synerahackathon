import { escapeSpaceIds, wayfindingRole } from './live.ts'
import type { FloorPlan, Space } from './types.ts'

function space(partial: Pick<Space, 'id' | 'type' | 'room_type'>): Space {
  return { floor_id: 'f0', name: partial.id, ref: null, polygon: [[0, 0], [1, 0], [1, 1]], synthetic: false, ...partial }
}

const stairwell = space({ id: 'stair', type: 'corridor', room_type: 'stairwell' })
const staircase = space({ id: 'staircase', type: 'stair', room_type: 'staircase' })
const lift = space({ id: 'lift', type: 'lift', room_type: 'lift' })
const corridor = space({ id: 'hall', type: 'corridor', room_type: 'corridor' })
const office = space({ id: 'office', type: 'room', room_type: 'office' })

if (wayfindingRole(stairwell) !== 'stair') throw new Error('stairwell must be stairs even when stored as a corridor')
if (wayfindingRole(staircase) !== 'stair') throw new Error('staircase must be stairs')
if (wayfindingRole(lift) !== 'lift') throw new Error('lift must stay a lift')
if (wayfindingRole(corridor) !== null) throw new Error('a plain corridor is not circulation equipment')
if (wayfindingRole(space({ id: 'exit', type: 'corridor', room_type: 'emergency-exit' })) !== 'escape') throw new Error('emergency exit type must be an escape route')

const plan: FloorPlan = {
  floor: { id: 'f0', level: 0, name: 'Ground', elevation_m: 0, height_m: 3, space_count: 4 },
  spaces: [stairwell, lift, corridor, office],
  openings: [
    { id: 'door', floor_id: 'f0', space_ids: ['stair', 'outside'], kind: 'entrance', position: [0, 0], width_m: 1, step_free: true, synthetic: false },
    { id: 'main', floor_id: 'f0', space_ids: ['hall', 'outside'], kind: 'entrance', position: [1, 0], width_m: 1, step_free: true, synthetic: false },
    { id: 'inner', floor_id: 'f0', space_ids: ['office', 'hall'], kind: 'door', position: [2, 0], width_m: 0.9, step_free: true, synthetic: false },
  ],
  assets: [],
  connectors: [],
  closed_ids: [],
  bounds: { min: [0, 0], max: [1, 1] },
}

const exits = escapeSpaceIds(plan)
if (exits.has('stair') || exits.has('lift') || exits.has('office')) throw new Error('escape colour must not replace stairs, lifts or ordinary rooms')
if (!exits.has('hall')) throw new Error('a corridor with an entrance is an escape route')
console.log('wayfinding check ok')
