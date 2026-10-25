import { catalog, matchUserText } from './fixtures'
import type { Asset, Reply, Route, Space } from '../domain/types'

export type TalkContext = {
  hereId: string | null
  destinationId: string | null
  stepFree: boolean
  closedIds: string[]
  buildingName: string
}

let hereId: string | null = null
let destinationId: string | null = null

export function currentLocation(): string | null {
  return hereId
}

export function setCurrentLocation(spaceId: string | null): void {
  hereId = spaceId
}

export function currentDestination(): string | null {
  return destinationId
}

function constraints(stepFree: boolean, closedIds: string[]) {
  return { step_free: stepFree, via: [] as string[], closed_ids: closedIds }
}

function emptyResolved() {
  return { start_space_id: null, destination_space_id: null, space_ids: [] as string[], asset_ids: [] as string[], count: null as number | null }
}

function notFound(text: string): Reply {
  return {
    id: 'clarify',
    userText: text,
    guideText: `No place in this building matches “${text.trim()}”.`,
    understood: {
      intent: 'clarify',
      summary: 'Place not found',
      constraints: constraints(true, []),
      resolved: { ...emptyResolved(), count: 0 },
      missing: ['place'],
    },
    effects: [{ type: 'clear_route' }],
    routes: [],
    pending: null,
  }
}

function ask(text: string, question: string, options: { id: string; label: string }[]): Reply {
  return {
    id: 'clarify',
    userText: text,
    guideText: question,
    understood: {
      intent: 'clarify',
      summary: question,
      constraints: constraints(true, []),
      resolved: emptyResolved(),
      missing: ['place'],
    },
    effects: [{ type: 'ask', question, options }],
    routes: [],
    pending: null,
  }
}

function matches(query: string): { spaces: Space[]; assets: Asset[] } {
  const needle = query.trim().toLowerCase().replace(/^the /, '')
  if (!needle) return { spaces: [], assets: [] }
  const spaces = [...catalog.spaces.values()].filter((space) => {
    const ref = (space.ref ?? '').toLowerCase()
    return space.name.toLowerCase().includes(needle) || ref === needle
  })
  const assets = [...catalog.assets.values()].filter((asset) => asset.name.toLowerCase().includes(needle))
  return { spaces, assets }
}

function locationReply(text: string, space: Space): Reply {
  hereId = space.id
  const floor = catalog.floors.find((item) => item.id === space.floor_id)
  return {
    id: 'accepted',
    userText: text,
    guideText: `You are at ${space.name}.`,
    understood: {
      intent: 'context',
      summary: `You are at ${space.name}`,
      constraints: constraints(true, []),
      resolved: { ...emptyResolved(), start_space_id: space.id, space_ids: [space.id] },
      missing: [],
    },
    effects: [
      { type: 'clear_route' },
      { type: 'focus', floor_id: space.floor_id, floor_level: floor?.level ?? 0, point: null },
      { type: 'highlight_spaces', space_ids: [space.id], reason: 'selected' },
    ],
    routes: [],
    pending: null,
  }
}

function placeLabel(name: string, buildingName: string): string {
  return `${name} · ${buildingName}`
}

function savedRoute(start: string, destination: string, stepFree: boolean, closedIds: string[]): Route | null {
  const route = catalog.replies.accepted.routes[0]
  if (!route || stepFree !== route.step_free) return null
  const destinationMatches = destination === route.destination_space_id || destination === 'proc-factory-dev-003-A00001'
  if (start !== route.start_space_id || !destinationMatches) return null
  const blocked = route.space_path?.some((id) => closedIds.includes(id))
  return blocked ? null : route
}

function findElement(query: string): { id: string; name: string; spaceIds: string[] } | null {
  const needle = query.trim().toLowerCase()
  const connector = [...catalog.connectors.values()].find((item) => item.name.toLowerCase().includes(needle) || item.id === query)
  if (connector) return { id: connector.id, name: connector.name, spaceIds: connector.space_ids }
  const space = [...catalog.spaces.values()].find((item) => item.name.toLowerCase().includes(needle) || item.ref?.toLowerCase() === needle)
  if (space) return { id: space.id, name: space.name, spaceIds: [space.id] }
  const opening = [...catalog.plans.values()].flatMap((plan) => plan.openings).find((item) => item.id === query)
  if (opening) return { id: opening.id, name: opening.kind, spaceIds: opening.space_ids }
  return null
}

export function interpretMessage(text: string, context: TalkContext): Reply {
  const exact = matchUserText(text)
  if (exact) {
    const reply = catalog.replies[exact]
    if (exact === 'accepted' && reply.understood?.resolved.start_space_id) hereId = reply.understood.resolved.start_space_id
    if (exact === 'pending') return reply
    return reply
  }
  const normalized = text.trim()
  const lower = normalized.toLowerCase()
  const stepFree = /no stairs|without stairs|step-free|wheelchair/.test(lower) ? true : context.stepFree
  if (lower.includes('reopen') && context.closedIds.length > 0) {
    const connector = catalog.connectors.get(context.closedIds[0])
    return {
      id: 'pending',
      userText: text,
      guideText: `I can reopen ${connector?.name ?? 'the closed connector'}. Confirm before I change the map.`,
      understood: {
        intent: 'reopen',
        summary: `Reopen ${connector?.name ?? 'connector'}`,
        constraints: constraints(stepFree, context.closedIds),
        resolved: emptyResolved(),
        missing: [],
      },
      effects: [{ type: 'highlight_spaces', space_ids: connector?.space_ids ?? [], reason: 'preview' }],
      routes: [],
      pending: {
        id: '55555555-5555-4555-8555-555555555556',
        status: 'pending',
        summary: `Reopen ${connector?.name ?? 'connector'}`,
        proposal: { kind: 'set_closed', element_ref: context.closedIds[0], closed: false },
      },
    }
  }
  const at = normalized.match(/i am (?:now )?at (.+)/i)
  if (at) {
    const found = matches(at[1])
    const places = [...found.spaces, ...found.assets]
    if (places.length === 0) return notFound(at[1])
    if (places.length > 1) {
      return ask(text, 'Which place?', places.slice(0, 4).map((place) => ({ id: place.id, label: placeLabel(place.name, context.buildingName) })))
    }
    const space = found.spaces[0] ?? catalog.spaces.get(found.assets[0].space_id)
    if (!space) return notFound(at[1])
    return locationReply(text, space)
  }
  const looking = normalized.match(/(?:where is|find|how do i reach|how do i get to) (.+?)(?:\?|$)/i)
  if (looking) {
    const found = matches(looking[1])
    const places = [...found.assets, ...found.spaces]
    if (places.length === 0) return notFound(looking[1])
    if (places.length > 1) {
      return ask(text, `Which ${looking[1].trim()}?`, places.slice(0, 4).map((place) => ({ id: place.id, label: placeLabel(place.name, context.buildingName) })))
    }
    const place = places[0]
    const floorId = 'floor_id' in place ? place.floor_id : ''
    const floor = catalog.floors.find((item) => item.id === floorId)
    const start = hereId ?? context.hereId
    if (!start) return ask(text, 'Where are you now?', [])
    destinationId = place.id
    const route = savedRoute(start, place.id, stepFree, context.closedIds)
    return {
      id: route ? 'accepted' : 'unreachable',
      userText: text,
      guideText: route ? `Route is ${route.length_m} m. Follow the tape on the plan.` : 'No saved route to that place from your current location. The map is unchanged.',
      understood: {
        intent: route ? 'route' : 'clarify',
        summary: `${catalog.spaces.get(start)?.name ?? 'Start'} to ${place.name}`,
        constraints: constraints(stepFree, context.closedIds),
        resolved: {
          ...emptyResolved(),
          start_space_id: start,
          destination_space_id: 'space_id' in place ? place.space_id : place.id,
          asset_ids: 'space_id' in place ? [place.id] : [],
          space_ids: [start, 'space_id' in place ? place.space_id : place.id].filter((id): id is string => Boolean(id)),
        },
        missing: route ? [] : ['route'],
      },
      effects: route
        ? [
            { type: 'draw_route', route_id: route.id },
            { type: 'focus', floor_id: floorId, floor_level: floor?.level ?? 0, point: 'position' in place ? place.position : null },
            { type: 'highlight_assets', asset_ids: 'space_id' in place ? [place.id] : [] },
          ]
        : [{ type: 'clear_route' }, { type: 'highlight_spaces', space_ids: ['space_id' in place ? place.space_id : place.id], reason: 'selected' }],
      routes: route ? [route] : [],
      pending: null,
    }
  }
  const instead = normalized.match(/now go to (.+?)(?: instead)?$/i)
    ?? normalized.match(/change destination to (.+)/i)
    ?? normalized.match(/(.+) instead$/i)
  if (instead) {
    const found = matches(instead[1])
    const places = [...found.assets, ...found.spaces]
    if (places.length === 0) return notFound(instead[1])
    if (places.length > 1) return ask(text, 'Which destination?', places.slice(0, 4).map((place) => ({ id: place.id, label: placeLabel(place.name, context.buildingName) })))
    destinationId = places[0].id
    const start = hereId ?? context.hereId
    return {
      id: 'accepted',
      userText: text,
      guideText: start ? `Destination is now ${places[0].name}. You are still at ${catalog.spaces.get(start)?.name ?? 'the saved start'}.` : `Destination is now ${places[0].name}.`,
      understood: {
        intent: 'context',
        summary: `Destination changed to ${places[0].name}`,
        constraints: constraints(stepFree, context.closedIds),
        resolved: { ...emptyResolved(), start_space_id: start, destination_space_id: places[0].id },
        missing: start ? [] : ['start'],
      },
      effects: [{ type: 'clear_route' }],
      routes: [],
      pending: null,
    }
  }
  const closing = normalized.match(/(?:close|closed) (.+)/i)
  if (closing) {
    const element = findElement(closing[1])
    if (!element) return notFound(closing[1])
    return {
      id: 'pending',
      userText: text,
      guideText: `I can close ${element.name}. Confirm before I change the map. The previous route will not be reused if it crosses this place.`,
      understood: {
        intent: 'close',
        summary: `Close ${element.name}`,
        constraints: constraints(stepFree, context.closedIds),
        resolved: emptyResolved(),
        missing: [],
      },
      effects: [{ type: 'highlight_spaces', space_ids: element.spaceIds, reason: 'preview' }],
      routes: [],
      pending: {
        id: '55555555-5555-4555-8555-555555555557',
        status: 'pending',
        summary: `Close ${element.name}`,
        proposal: { kind: 'set_closed', element_ref: element.id, closed: true },
      },
    }
  }
  const tour = normalized.match(/visit (.+?) then (.+?)(?: then (.+))?(?:\.|$)/i)
  if (tour) {
    const stops = [tour[1], tour[2], tour[3]].filter((item): item is string => Boolean(item))
    const resolved = stops.map((stop) => matches(stop))
    if (resolved.some((item) => item.spaces.length + item.assets.length === 0)) return notFound(stops.join(', '))
    const names = resolved.map((item, index) => item.spaces[0]?.name ?? item.assets[0]?.name ?? stops[index])
    return {
      id: 'clarify',
      userText: text,
      guideText: `Order kept: ${names.join(' → ')}. No saved multi-stop route, so no distance is shown.`,
      understood: {
        intent: 'tour',
        summary: names.join(' → '),
        constraints: { ...constraints(stepFree, context.closedIds), via: names },
        resolved: emptyResolved(),
        missing: ['route'],
      },
      effects: [{ type: 'clear_route' }],
      routes: [],
      pending: null,
    }
  }
  if (/no stairs|without stairs|step-free|wheelchair/.test(lower)) {
    return {
      id: 'accepted',
      userText: text,
      guideText: 'Step-free is on for later routes.',
      understood: {
        intent: 'context',
        summary: 'Step-free is on',
        constraints: constraints(true, context.closedIds),
        resolved: { ...emptyResolved(), start_space_id: hereId ?? context.hereId, destination_space_id: destinationId ?? context.destinationId },
        missing: [],
      },
      effects: [],
      routes: [],
      pending: null,
    }
  }
  return notFound(normalized)
}
