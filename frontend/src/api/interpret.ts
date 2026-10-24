import { catalog, matchUserText } from './fixtures'
import type { Asset, Reply, Route, Space } from '../domain/types'

let hereId: string | null = null

export function currentLocation(): string | null {
  return hereId
}

export function setCurrentLocation(spaceId: string | null): void {
  hereId = spaceId
}

function constraints(closedIds: string[]) {
  return { step_free: true, via: [] as string[], closed_ids: closedIds }
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
      constraints: constraints([]),
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
      constraints: constraints([]),
      resolved: emptyResolved(),
      missing: ['place'],
    },
    effects: [{ type: 'ask', question, options }],
    routes: [],
    pending: null,
  }
}

function matches(query: string): { spaces: Space[]; assets: Asset[] } {
  const needle = query.trim().toLowerCase()
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
      constraints: constraints([]),
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

function savedRoute(start: string, destination: string): Route | null {
  const route = catalog.replies.accepted.routes[0]
  if (!route) return null
  const destinationMatches = destination === route.destination_space_id || destination === 'proc-factory-dev-003-A00001'
  if (start === route.start_space_id && destinationMatches && route.step_free) return route
  return null
}

export function interpretMessage(text: string, closedIds: string[]): Reply {
  const exact = matchUserText(text)
  if (exact) {
    const reply = catalog.replies[exact]
    if (exact === 'pending') return reply
    return reply
  }
  const normalized = text.trim()
  const lower = normalized.toLowerCase()
  if (lower.includes('reopen') && closedIds.length > 0) {
    const connector = catalog.connectors.get(closedIds[0])
    return {
      id: 'pending',
      userText: text,
      guideText: `I can reopen ${connector?.name ?? 'the closed connector'}. Confirm before I change the map.`,
      understood: {
        intent: 'reopen',
        summary: `Reopen ${connector?.name ?? 'connector'}`,
        constraints: constraints(closedIds),
        resolved: emptyResolved(),
        missing: [],
      },
      effects: [{ type: 'highlight_spaces', space_ids: connector?.space_ids ?? [], reason: 'preview' }],
      routes: [],
      pending: {
        id: '55555555-5555-4555-8555-555555555556',
        status: 'pending',
        summary: `Reopen ${connector?.name ?? 'connector'}`,
        proposal: { kind: 'set_closed', element_ref: closedIds[0], closed: false },
      },
    }
  }
  const at = normalized.match(/i am (?:now )?at (.+)/i)
  if (at) {
    const found = matches(at[1])
    const places = [...found.spaces, ...found.assets]
    if (places.length === 0) return notFound(at[1])
    if (places.length > 1) {
      return ask(text, 'Which place?', places.slice(0, 4).map((place) => ({ id: place.id, label: place.name })))
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
      return ask(text, `Which ${looking[1].trim()}?`, places.slice(0, 4).map((place) => ({ id: place.id, label: place.name })))
    }
    const place = places[0]
    const floorId = 'floor_id' in place ? place.floor_id : ''
    const floor = catalog.floors.find((item) => item.id === floorId)
    const start = hereId ?? catalog.replies.accepted.routes[0]?.start_space_id ?? null
    const route = start ? savedRoute(start, place.id) : null
    return {
      id: route ? 'accepted' : 'unreachable',
      userText: text,
      guideText: route ? `Route is ${route.length_m} m. Follow the tape on the plan.` : 'No saved route to that place from your current location.',
      understood: {
        intent: route ? 'route' : 'clarify',
        summary: `${start ? catalog.spaces.get(start)?.name ?? 'Start' : 'Start'} to ${place.name}`,
        constraints: constraints(closedIds),
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
  return notFound(normalized)
}
