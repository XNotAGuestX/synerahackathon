import type { DiscoveryPlace } from './discovery'
import type { AskOption, FloorPlan, FloorSummary, Reply } from './types'

// The guide asks with options but reads only text back. These helpers turn a
// picked option into a sentence the guide already understands, and fill start
// options from the plan when the guide asks "Where are you now?" without any.

export type ChoiceRole = 'start' | 'destination'

const START_LIMIT = 4

/** "Coffee machine 0.08 · Lehrgebäude 030" -> "Coffee machine 0.08" */
export function optionName(label: string): string {
  return label.split(' · ')[0].trim()
}

export function asksForStart(reply: Reply | null): boolean {
  return Boolean(reply?.understood?.missing.includes('start'))
}

export function choiceRole(reply: Reply | null): ChoiceRole {
  if (asksForStart(reply)) return 'start'
  return /^\s*i am (?:now )?at\b/i.test(reply?.userText ?? '') ? 'start' : 'destination'
}

export function choiceMessage(role: ChoiceRole, name: string): string {
  return role === 'start' ? `I am at ${name}` : `Where is ${name}?`
}

/** Spaces behind an entrance door, ground floor first. */
export function entranceOptions(plans: FloorPlan[]): AskOption[] {
  const ordered = [...plans].sort((left, right) => Math.abs(left.floor.level) - Math.abs(right.floor.level))
  const options: AskOption[] = []
  const seen = new Set<string>()
  for (const plan of ordered) {
    const inside = new Map(plan.spaces.filter((space) => space.type !== 'outside').map((space) => [space.id, space]))
    for (const opening of plan.openings) {
      if (opening.kind !== 'entrance') continue
      for (const spaceId of opening.space_ids) {
        const space = inside.get(spaceId)
        if (!space || seen.has(space.id)) continue
        seen.add(space.id)
        options.push({ id: space.id, label: `${space.name} · ${plan.floor.name}` })
        if (options.length >= START_LIMIT) return options
      }
    }
  }
  return options
}

/** Adds entrance options to an empty start question. Other replies pass through. */
export function withStartOptions(reply: Reply, plans: FloorPlan[]): Reply {
  if (!asksForStart(reply)) return reply
  const effects = reply.effects.map((effect) => {
    if (effect.type !== 'ask' || !Array.isArray(effect.options) || effect.options.length > 0) return effect
    const options = entranceOptions(plans)
    return options.length > 0 ? { ...effect, options } : effect
  })
  return { ...reply, effects }
}

export function placeById(plans: FloorPlan[], floors: FloorSummary[], id: string): DiscoveryPlace | null {
  for (const plan of plans) {
    const floor = floors.find((item) => item.id === plan.floor.id) ?? plan.floor
    const asset = plan.assets.find((item) => item.id === id)
    if (asset) {
      return { id, kind: 'asset', name: asset.name, floorId: asset.floor_id, floorLevel: floor.level, floorName: floor.name, type: asset.type, position: asset.position }
    }
    const space = plan.spaces.find((item) => item.id === id)
    if (space) {
      const [x, y] = space.polygon.reduce(([sx, sy], [px, py]) => [sx + px, sy + py], [0, 0])
      const position = space.polygon.length > 0 ? [x / space.polygon.length, y / space.polygon.length] as [number, number] : null
      return { id, kind: 'space', name: space.name, floorId: space.floor_id, floorLevel: floor.level, floorName: floor.name, type: space.room_type, position }
    }
  }
  return null
}

/** Display name of a space or asset in the loaded plans. */
export function nameInPlans(plans: FloorPlan[], id: string): string | null {
  for (const plan of plans) {
    const found = plan.spaces.find((item) => item.id === id) ?? plan.assets.find((item) => item.id === id)
    if (found) return found.name
  }
  return null
}
