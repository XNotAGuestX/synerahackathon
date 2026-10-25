import type { EmergencyPerson } from '../api/gateway.ts'
import { clockLabel, markersOnFloor, personName, placeLabel, secondsSince } from './emergency.ts'

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message)
}

function person(values: Partial<EmergencyPerson>): EmergencyPerson {
  return {
    id: 'P01', name: 'Ada', kind: 'simulated', status: 'inside', auto_status: 'inside', floor_id: 'F0', position: [1, 2],
    space_id: 'S1', space_name: 'Lab', last_seen_at: '2026-10-25T12:00:00Z', stale: false, manual: null, ...values,
  }
}

assert(personName(person({ name: null, id: 'D02' })) === 'Unnamed phone D02', 'unnamed phones keep their id')
assert(placeLabel(person({})) === 'Lab', 'inside shows the room')
assert(placeLabel(person({ space_name: null })) === 'Inside, between rooms', 'inside without a room stays inside')
assert(placeLabel(person({ auto_status: 'outside', status: 'outside', space_name: null })) === 'Outside the building', 'outside')
const markers = markersOnFloor([person({}), person({ id: 'P02', floor_id: 'F1' }), person({ id: 'D01', position: null })], 'F0')
assert(markers.length === 1 && markers[0].id === 'P01', 'only people with a position on this floor are drawn')
assert(clockLabel(125) === '2:05' && clockLabel(-3) === '0:00', 'clock label')
assert(secondsSince('2026-10-25T12:00:00Z', Date.parse('2026-10-25T12:00:20Z')) === 20, 'seconds since')
console.log('emergency check ok')
