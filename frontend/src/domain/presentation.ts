import type { AskEffect, Asset, Connector, Opening, Point, Route, Understood, ViewEffect } from './types'

const KNOWN_EFFECTS = new Set([
  'highlight_spaces',
  'highlight_assets',
  'focus',
  'draw_route',
  'clear_route',
  'set_closures',
  'ask',
  'building_patched',
  'preview_objects',
])

export type Decision = 'pending' | 'confirmed' | 'cancelled'

/** Ghosts for a proposed edit: the state after the change for new or changed elements. */
export type PreviewObjects = {
  floorIds: string[]
  assets: Asset[]
  openings: Opening[]
  connectors: Connector[]
  removedIds: string[]
}

export type Presentation = {
  guideText: string
  understood: Understood | null
  asks: AskEffect[]
  pendingSummary: string | null
  showDecision: boolean
  route: Route | null
  focusFloorId: string | null
  focusPoint: Point | null
  spaceReasons: Map<string, string>
  assetIds: Set<string>
  closedIds: string[]
  effectTypes: string[]
  unknownEffectTypes: string[]
  patchedFloorIds: string[]
  previewObjects: PreviewObjects | null
  alert: { tone: 'amber' | 'red' | 'green'; text: string } | null
}

type BuildInput = {
  guideText: string
  understood: Understood | null
  effects: ViewEffect[]
  routes: Route[]
  pendingSummary: string | null
  decision: Decision | null
  confirmedEffects: ViewEffect[]
  confirmedClosedIds: string[]
  confirmedText: string
  cancelledText: string
  /** Closures confirm in red; map edits confirm in green. */
  confirmedTone?: 'red' | 'green'
}

function isAsk(effect: ViewEffect): effect is AskEffect {
  return effect.type === 'ask' && Array.isArray(effect.options)
}

function stringList(value: unknown): string[] | null {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) return null
  return value
}

function records<T>(value: unknown, valid: (item: Record<string, unknown>) => boolean): T[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is T => Boolean(item) && typeof item === 'object' && valid(item as Record<string, unknown>))
}

function isPoint(value: unknown): boolean {
  return Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number'
}

function readPreviewObjects(effect: Record<string, unknown>): PreviewObjects {
  return {
    floorIds: stringList(effect.floor_ids) ?? [],
    assets: records<Asset>(effect.assets, (item) => typeof item.id === 'string' && typeof item.floor_id === 'string' && isPoint(item.position) && Boolean(item.footprint)),
    openings: records<Opening>(effect.openings, (item) => typeof item.id === 'string' && typeof item.floor_id === 'string' && isPoint(item.position)),
    connectors: records<Connector>(effect.connectors, (item) => typeof item.id === 'string'),
    removedIds: stringList(effect.removed_ids) ?? [],
  }
}

function pointOrNull(value: unknown): Point | null {
  if (value == null) return null
  if (!Array.isArray(value) || value.length < 2) return null
  const x = value[0]
  const y = value[1]
  if (typeof x !== 'number' || typeof y !== 'number') return null
  return [x, y]
}

export function buildPresentation(input: BuildInput): Presentation {
  const effects = input.decision === 'confirmed'
    ? input.confirmedEffects
    : input.decision === 'cancelled'
      ? []
      : input.effects
  const spaceReasons = new Map<string, string>()
  const assetIds = new Set<string>()
  const asks: AskEffect[] = []
  const effectTypes: string[] = []
  const unknownEffectTypes: string[] = []
  let route: Route | null = null
  let focusFloorId: string | null = null
  let focusPoint: Point | null = null
  let closedIds: string[] = []
  let patchedFloorIds: string[] = []
  let previewObjects: PreviewObjects | null = null

  for (const effect of effects) {
    effectTypes.push(effect.type)
    if (!KNOWN_EFFECTS.has(effect.type)) {
      unknownEffectTypes.push(effect.type)
      continue
    }
    const fields = effect as { space_ids?: unknown; asset_ids?: unknown; closed_ids?: unknown; reason?: unknown; floor_id?: unknown; floor_ids?: unknown; point?: unknown; route_id?: unknown }
    const spaceIds = stringList(fields.space_ids)
    const highlightedAssets = stringList(fields.asset_ids)
    const closureIds = stringList(fields.closed_ids)
    if (effect.type === 'highlight_spaces' && spaceIds && typeof fields.reason === 'string') {
      for (const id of spaceIds) spaceReasons.set(id, fields.reason)
    } else if (effect.type === 'highlight_assets' && highlightedAssets) {
      for (const id of highlightedAssets) assetIds.add(id)
    } else if (effect.type === 'focus' && typeof fields.floor_id === 'string') {
      focusFloorId = fields.floor_id
      focusPoint = pointOrNull(fields.point)
    } else if (effect.type === 'draw_route' && typeof fields.route_id === 'string') {
      route = input.routes.find((item) => item.id === fields.route_id) ?? null
    } else if (effect.type === 'clear_route') {
      route = null
    } else if (effect.type === 'set_closures' && closureIds) {
      closedIds = closureIds
    } else if (effect.type === 'building_patched') {
      patchedFloorIds = stringList(fields.floor_ids) ?? patchedFloorIds
    } else if (effect.type === 'preview_objects') {
      previewObjects = readPreviewObjects(effect as Record<string, unknown>)
    } else if (isAsk(effect)) {
      asks.push(effect)
    }
  }

  if (input.decision === 'confirmed') closedIds = input.confirmedClosedIds
  if (route && !route.reachable) closedIds = route.closed_ids

  let guideText = input.guideText
  let alert: Presentation['alert'] = null
  if (input.decision === 'confirmed') {
    guideText = input.confirmedText
    alert = { tone: input.confirmedTone ?? 'red', text: input.confirmedText }
  } else if (input.decision === 'cancelled') {
    guideText = input.cancelledText
    alert = { tone: 'amber', text: input.cancelledText }
  } else if (route && !route.reachable) {
    alert = { tone: 'red', text: input.guideText }
  }

  return {
    guideText,
    understood: input.understood,
    asks,
    pendingSummary: input.pendingSummary,
    showDecision: Boolean(input.pendingSummary) && input.decision === 'pending',
    route,
    focusFloorId,
    focusPoint,
    spaceReasons,
    assetIds,
    closedIds,
    effectTypes,
    unknownEffectTypes,
    patchedFloorIds,
    previewObjects,
    alert,
  }
}

export function assumptionLines(
  understood: Understood,
  label: (id: string | null) => string,
): { preview: string; details: string[] } {
  const firstMissing = understood.missing[0]
  const preview = firstMissing
    ? `1. Missing ${firstMissing.replaceAll('_', ' ')}`
    : `1. ${understood.summary}`
  const details = [
    `Step-free is ${understood.constraints.step_free ? 'on' : 'off'}`,
    `Start: ${label(understood.resolved.start_space_id)}`,
    `Destination: ${label(understood.resolved.destination_space_id)}`,
  ]
  if (understood.constraints.via.length > 0) {
    details.push(`Via: ${understood.constraints.via.map((id) => label(id)).join(', ')}`)
  }
  if (understood.constraints.closed_ids.length > 0) {
    details.push(`Closed: ${understood.constraints.closed_ids.map((id) => label(id)).join(', ')}`)
  }
  for (const slot of understood.missing.slice(firstMissing ? 1 : 0)) {
    details.push(`Missing ${slot.replaceAll('_', ' ')}`)
  }
  if (understood.resolved.count != null) details.push(`Count: ${understood.resolved.count}`)
  return { preview, details }
}

export function formatMetres(value: number | null): string {
  if (value == null) return 'Unreachable'
  return `${Number.isInteger(value) ? value : value.toFixed(1)} m`
}
