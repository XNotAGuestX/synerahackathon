import type { EmergencyPerson } from '../api/gateway'

/** Emergency mode (FR-17): pure helpers for the admin list and map markers. The server already sorts the list. */

export type PersonMarker = { id: string; label: string; status: EmergencyPerson['status']; stale: boolean; position: [number, number] }

export function personName(person: Pick<EmergencyPerson, 'id' | 'name'>): string {
  return person.name?.trim() || `Unnamed phone ${person.id}`
}

/** Where the person is, in words: the room, or outside, or an imprecise fix between rooms. */
export function placeLabel(person: Pick<EmergencyPerson, 'status' | 'auto_status' | 'space_name'>): string {
  if (person.auto_status === 'outside') return 'Outside the building'
  return person.space_name ?? 'Inside, between rooms'
}

/** Markers for one floor; people without a known floor are listed but not drawn. */
export function markersOnFloor(people: EmergencyPerson[], floorId: string): PersonMarker[] {
  return people
    .filter((person) => person.floor_id === floorId && person.position)
    .map((person) => ({
      id: person.id,
      label: `${personName(person)}: ${statusLabel(person.status)}`,
      status: person.status,
      stale: person.stale,
      position: person.position!,
    }))
}

export function statusLabel(status: EmergencyPerson['status']): string {
  return status === 'inside' ? 'Inside' : status === 'outside' ? 'Outside' : 'Marked outside'
}

/** Seconds as m:ss, e.g. 125 -> "2:05". */
export function clockLabel(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/** Seconds since an RFC 3339 time, never negative. */
export function secondsSince(time: string, now: number): number {
  return Math.max(0, Math.round((now - Date.parse(time)) / 1000))
}
