import type { Asset, FloorPlan, FloorSummary, Point, Space } from './types'

export type DiscoveryPlace = {
  id: string
  kind: 'space' | 'asset'
  name: string
  floorId: string
  floorLevel: number
  floorName: string
  type: string
  position: Point | null
}

export type DiscoveryType = {
  id: string
  label: string
  count: number
  places: DiscoveryPlace[]
}

export type DiscoveryCategory = {
  id: string
  label: string
  count: number
  types: DiscoveryType[]
}

const RESULT_LIMIT = 15

const FOOD_TYPES = new Set([
  'coffee_machine',
  'vending_machine',
  'fridge',
  'microwave',
  'dishwasher',
  'stove',
  'dining_table',
  'kitchen_counter',
])

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function clusterFor(asset: Asset): { id: string; label: string } {
  if (FOOD_TYPES.has(asset.type)) return { id: 'food', label: 'Food and drink' }
  if (asset.category === 'machine') return { id: 'machines', label: 'Machines' }
  if (asset.category === 'fixture') return { id: 'fixtures', label: 'Fixtures' }
  if (asset.category === 'equipment') return { id: 'equipment', label: 'Equipment' }
  if (asset.category === 'furniture') return { id: 'furniture', label: 'Furniture' }
  return { id: asset.category || 'other', label: humanize(asset.category || 'other') }
}

function floorMeta(floors: FloorSummary[], floorId: string): { level: number; name: string } {
  const floor = floors.find((item) => item.id === floorId)
  return { level: floor?.level ?? 0, name: floor?.name ?? floorId }
}

export function buildDiscovery(plans: FloorPlan[], floors: FloorSummary[]): DiscoveryCategory[] {
  const groups = new Map<string, { label: string; types: Map<string, DiscoveryPlace[]> }>()
  const ensure = (id: string, label: string) => {
    const existing = groups.get(id)
    if (existing) return existing
    const created = { label, types: new Map<string, DiscoveryPlace[]>() }
    groups.set(id, created)
    return created
  }

  for (const plan of plans) {
    for (const asset of plan.assets) {
      const cluster = clusterFor(asset)
      const group = ensure(cluster.id, cluster.label)
      const floor = floorMeta(floors, asset.floor_id)
      const place: DiscoveryPlace = {
        id: asset.id,
        kind: 'asset',
        name: asset.name,
        floorId: asset.floor_id,
        floorLevel: floor.level,
        floorName: floor.name,
        type: asset.type,
        position: asset.position,
      }
      const bucket = group.types.get(asset.type) ?? []
      bucket.push(place)
      group.types.set(asset.type, bucket)
    }
    for (const space of plan.spaces) {
      if (!space.room_type || space.type === 'outside') continue
      const group = ensure('rooms', 'Rooms')
      const floor = floorMeta(floors, space.floor_id)
      const place = placeFromSpace(space, floor)
      const bucket = group.types.get(space.room_type) ?? []
      bucket.push(place)
      group.types.set(space.room_type, bucket)
    }
  }

  return [...groups.entries()]
    .map(([id, group]) => {
      const types = [...group.types.entries()]
        .filter(([, places]) => places.length > 0)
        .map(([type, places]) => ({
          id: type,
          label: humanize(type),
          count: places.length,
          places: [...places].sort((left, right) => left.name.localeCompare(right.name)),
        }))
        .sort((left, right) => left.label.localeCompare(right.label))
      return {
        id,
        label: group.label,
        count: types.reduce((sum, type) => sum + type.count, 0),
        types,
      }
    })
    .filter((category) => category.types.length > 0)
    .sort((left, right) => left.label.localeCompare(right.label))
}

function placeFromSpace(space: Space, floor: { level: number; name: string }): DiscoveryPlace {
  const [x, y] = space.polygon.reduce(([sx, sy], [px, py]) => [sx + px, sy + py], [0, 0])
  return {
    id: space.id,
    kind: 'space',
    name: space.name,
    floorId: space.floor_id,
    floorLevel: floor.level,
    floorName: floor.name,
    type: space.room_type,
    position: space.polygon.length > 0 ? [x / space.polygon.length, y / space.polygon.length] : null,
  }
}

export function limitPlaces(places: DiscoveryPlace[]): DiscoveryPlace[] {
  return places.slice(0, RESULT_LIMIT)
}

export function searchDiscovery(categories: DiscoveryCategory[], query: string): DiscoveryPlace[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  const matches: DiscoveryPlace[] = []
  for (const category of categories) {
    for (const type of category.types) {
      for (const place of type.places) {
        if (place.name.toLowerCase().includes(needle) || type.label.toLowerCase().includes(needle) || category.label.toLowerCase().includes(needle)) {
          matches.push(place)
        }
      }
    }
  }
  return matches.sort((left, right) => left.name.localeCompare(right.name)).slice(0, RESULT_LIMIT)
}

export const discoveryResultLimit = RESULT_LIMIT
