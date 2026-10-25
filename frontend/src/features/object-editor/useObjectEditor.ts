import { useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { toUiError } from '../../api/errors'
import { sampleObjectCatalog } from '../../api/fixtures'
import { gateway } from '../../api/gateway'
import type { ActionResult } from '../../api/gateway'
import {
  ROTATE_STEP_DEG,
  NUDGE_FAST_M,
  NUDGE_M,
  assetFootprint,
  buildProposal,
  catalogHeight,
  catalogSize,
  clampToSupports,
  describeEditError,
  descendantsOf,
  draftFromAsset,
  draftFromOpening,
  editedFloors,
  findObjectEntry,
  flattenCatalog,
  interiorPoint,
  isDirty,
  isRemovableConnection,
  newConnectorDraft,
  newObjectDraft,
  newOpeningDraft,
  nudge,
  parseRecent,
  placementHint,
  pushRecent,
  removeProposal,
  rotateBy,
  round,
  spaceAt,
  stackingIndex,
  supportCentre,
  supportLevel,
  toggleStop,
  undoProposal,
  wallAt,
} from '../../domain/editor'
import type { CatalogEntry, ConnectorDraft, Draft, ObjectDraft, OpeningDraft, PlacementHint, StackingIndex } from '../../domain/editor'
import type { Asset, ConnectorKind, EditProposal, FloorPlan, FloorSummary, ObjectCatalog, ObjectGroup, Opening, OpeningKind, Point, Selection, Space } from '../../domain/types'
import { copy, fill } from '../../i18n/en'
import type { EditorOverlay, GhostAsset } from '../../rendering/PlanCanvas'

const RECENT_KEY = 'wayfinder-recent-object-types'
const text = copy.editor

export type EditorStep = 'pick' | 'place' | 'form'
export type FocusTarget = 'search' | 'heading' | 'confirm'
type DiscardIntent = 'close' | 'back' | 'revert'

type Options = {
  sessionId: string
  plans: Map<string, FloorPlan>
  floors: FloorSummary[]
  floorId: string
  selection: Selection | null
  onSelect: (selection: Selection | null) => void
  /** Reload these floors and the session revision. Resolves with the fresh plans. */
  refreshFloors: (floorIds: string[]) => Promise<Map<string, FloorPlan>>
  buttonRef: RefObject<HTMLButtonElement | null>
}

export type StopLabel = { id: string; name: string; floorName: string }

export type ObjectEditor = ReturnType<typeof useObjectEditor>

function typingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

function findAsset(plans: Map<string, FloorPlan>, id: string | null): Asset | null {
  if (!id) return null
  for (const plan of plans.values()) {
    const asset = plan.assets.find((item) => item.id === id)
    if (asset) return asset
  }
  return null
}

function findOpening(plans: Map<string, FloorPlan>, id: string | null): Opening | null {
  if (!id) return null
  for (const plan of plans.values()) {
    const opening = plan.openings.find((item) => item.id === id)
    if (opening) return opening
  }
  return null
}

function findSpace(plans: Map<string, FloorPlan>, id: string): Space | null {
  for (const plan of plans.values()) {
    const space = plan.spaces.find((item) => item.id === id)
    if (space) return space
  }
  return null
}

function stackingOf(plans: Map<string, FloorPlan>): StackingIndex {
  return stackingIndex([...plans.values()].flatMap((plan) => plan.stacking ?? []))
}

function readRecent(): string[] {
  try { return parseRecent(window.localStorage.getItem(RECENT_KEY)) } catch { return [] }
}

function openingKindOf(id: string): OpeningKind {
  return id === 'opening' ? 'opening' : 'door'
}

function connectorKindOf(id: string): ConnectorKind {
  return id === 'escalator' || id === 'lift' ? id : 'stairs'
}

export function useObjectEditor({ sessionId, plans, floors, floorId, selection, onSelect, refreshFloors, buttonRef }: Options) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<EditorStep>('pick')
  const [changingType, setChangingType] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [original, setOriginal] = useState<Draft | null>(null)
  const [catalog, setCatalog] = useState<ObjectCatalog>(sampleObjectCatalog)
  const [catalogOffline, setCatalogOffline] = useState(false)
  const [recent, setRecent] = useState<string[]>(readRecent)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<'remove' | 'discard' | null>(null)
  const [discardIntent, setDiscardIntent] = useState<DiscardIntent>('close')
  const [announcement, setAnnouncement] = useState({ id: 0, text: '' })
  const [focusRequest, setFocusRequest] = useState<{ id: number; target: FocusTarget }>({ id: 0, target: 'heading' })
  const plansRef = useRef(plans)
  plansRef.current = plans

  useEffect(() => {
    let cancelled = false
    gateway.listObjectTypes()
      .then((loaded) => {
        if (cancelled) return
        if (Array.isArray(loaded?.groups) && loaded.groups.length > 0) setCatalog(loaded)
        else setCatalogOffline(true)
      })
      .catch(() => { if (!cancelled) setCatalogOffline(true) })
    return () => { cancelled = true }
  }, [])

  const entries = useMemo(() => flattenCatalog(catalog), [catalog])
  const stacking = useMemo(() => stackingOf(plans), [plans])
  const allAssets = useMemo(() => new Map([...plans.values()].flatMap((plan) => plan.assets.map((asset) => [asset.id, asset] as const))), [plans])
  const dirty = isDirty(draft, original)
  const isLocal = sessionId.startsWith('local-')
  const currentPlan = plans.get(floorId) ?? null
  const currentSpaces = useMemo(() => [...(currentPlan?.spaces ?? [])].sort((left, right) => left.name.localeCompare(right.name, undefined, { numeric: true })), [currentPlan])

  const announce = (message: string) => setAnnouncement((current) => ({ id: current.id + 1, text: message }))
  const focus = (target: FocusTarget) => setFocusRequest((current) => ({ id: current.id + 1, target }))
  const floorName = (id: string) => floors.find((floor) => floor.id === id)?.name ?? id

  const typeLabel = (value: Draft | null): string => {
    if (!value) return ''
    if (value.target === 'object') return findObjectEntry(entries, value.type, value.category)?.type.label ?? value.type.replaceAll('_', ' ')
    return entries.find((entry) => entry.type.id === value.kind && entry.type.action !== 'add_object')?.type.label
      ?? (value.target === 'opening' ? (value.kind === 'door' ? text.door : text.passage) : value.kind)
  }

  /** Load the details of an existing object or opening into the form. */
  const loadDetails = (target: Selection | null, source: Map<string, FloorPlan>): string | null => {
    if (!target) return null
    if (target.kind === 'asset') {
      const asset = findAsset(source, target.id)
      if (!asset) return null
      const next = draftFromAsset(asset, stackingOf(source))
      setDraft(next)
      setOriginal(next)
      setStep('form')
      setChangingType(false)
      return asset.name
    }
    if (target.kind === 'opening') {
      const opening = findOpening(source, target.id)
      if (!opening) return null
      const next = draftFromOpening(opening)
      setDraft(next)
      setOriginal(next)
      setStep('form')
      setChangingType(false)
      return target.name
    }
    return null
  }

  const startPicking = () => {
    setDraft(null)
    setOriginal(null)
    setStep('pick')
    setChangingType(false)
    focus('search')
  }

  const openEditor = (target: Selection | null = selection) => {
    setOpen(true)
    setError(null)
    setConfirming(null)
    const name = loadDetails(target, plans)
    if (name) {
      focus('heading')
      announce(fill(text.opened, { name }))
    } else {
      startPicking()
    }
  }

  const closeNow = () => {
    setOpen(false)
    setDraft(null)
    setOriginal(null)
    setStep('pick')
    setChangingType(false)
    setConfirming(null)
    setError(null)
    announce(text.closed)
    window.requestAnimationFrame(() => buttonRef.current?.focus())
  }

  const askDiscard = (intent: DiscardIntent) => {
    setDiscardIntent(intent)
    setConfirming('discard')
    focus('confirm')
  }

  const requestClose = () => {
    if (saving) return
    if (dirty) askDiscard('close')
    else closeNow()
  }

  const toggle = () => (open ? requestClose() : openEditor())

  /** Clicking an item on the map opens it in the editor. Once open, the selection effect below switches the form. */
  const editItem = (target: Selection) => {
    if (!open) openEditor(target)
  }

  const confirmDiscard = () => {
    setConfirming(null)
    setError(null)
    if (discardIntent === 'close') closeNow()
    else if (discardIntent === 'back') startPicking()
    else {
      setDraft(original)
      focus('heading')
    }
  }

  const dismissConfirm = () => {
    setConfirming(null)
    focus('heading')
  }

  /** Esc cancels the current mode, one level at a time. */
  const escape = () => {
    if (saving) return
    if (confirming) return dismissConfirm()
    if (step === 'pick' && changingType) {
      setChangingType(false)
      setStep('form')
      focus('heading')
      return
    }
    if (step === 'pick') return closeNow()
    if (step === 'place') return startPicking()
    if (!original) {
      const started = draft?.target === 'object'
        || (draft?.target === 'opening' && Boolean(draft.position || draft.firstSpace || draft.secondSpace))
        || (draft?.target === 'connector' && draft.spaces.length > 0)
      if (started) askDiscard('back')
      else startPicking()
      return
    }
    if (dirty) askDiscard('revert')
    else closeNow()
  }

  const chooseType = (entry: CatalogEntry) => {
    const nextRecent = pushRecent(recent, entry.key)
    setRecent(nextRecent)
    try { window.localStorage.setItem(RECENT_KEY, JSON.stringify(nextRecent)) } catch { /* private mode */ }
    setError(null)
    if (changingType && draft?.target === 'object' && entry.type.action === 'add_object') {
      const size = catalogSize(entry)
      // A new object takes the new type's size; an existing one keeps its measured size.
      setDraft({ ...draft, type: entry.type.id, category: entry.categoryId, ...(original ? {} : { width: size.width, depth: size.depth }) })
      setChangingType(false)
      setStep('form')
      focus('heading')
      return
    }
    setOriginal(null)
    setChangingType(false)
    if (entry.type.action === 'add_object') {
      setDraft(newObjectDraft(entry, floorId, null))
      setStep('place')
    } else if (entry.type.action === 'add_opening') {
      setDraft(newOpeningDraft(openingKindOf(entry.type.id), entries, floorId))
      setStep('form')
    } else {
      setDraft(newConnectorDraft(connectorKindOf(entry.type.id)))
      setStep('form')
    }
    focus('heading')
  }

  const startChangeType = () => {
    setChangingType(true)
    setStep('pick')
    focus('search')
  }

  const placeAt = (point: Point) => {
    if (draft?.target !== 'object') return
    const space = currentPlan ? spaceAt(currentPlan.spaces, point) : null
    setDraft({ ...draft, floorId, position: [round(point[0]), round(point[1])], onTopOf: draft.floorId === floorId ? draft.onTopOf : [] })
    setStep('form')
    announce(space ? fill(text.placed, { room: space.name }) : text.placedOutside)
    focus('heading')
  }

  const placeInSpace = (spaceId: string) => {
    const space = currentPlan?.spaces.find((item) => item.id === spaceId)
    if (space) placeAt(interiorPoint(space.polygon))
  }

  const wallClick = (point: Point) => {
    if (draft?.target !== 'opening' || !currentPlan) return
    const wall = wallAt(currentPlan.spaces, point)
    setDraft({ ...draft, floorId, position: wall ? wall.snapped : [round(point[0]), round(point[1])], firstSpace: null, secondSpace: null })
    announce(wall ? fill(text.wallBetween, { first: wall.spaces[0].name, second: wall.spaces[1].name }) : text.wallMissing)
  }

  const chooseOpeningRooms = (first: string | null, second: string | null) => {
    if (draft?.target !== 'opening') return
    setDraft({ ...draft, floorId, firstSpace: first, secondSpace: second, position: null })
  }

  const pickStop = (spaceId: string) => {
    if (draft?.target !== 'connector') return
    const space = findSpace(plans, spaceId)
    if (!space) return
    const removing = draft.spaces.some((stop) => stop.id === spaceId)
    setDraft({ ...draft, spaces: toggleStop(draft.spaces, { id: space.id, floorId: space.floor_id }) })
    announce(fill(removing ? text.stopRemoved : text.stopAdded, { name: space.name }))
  }

  const supportPrints = (value: ObjectDraft) => value.onTopOf.map((id) => allAssets.get(id)).filter((item): item is Asset => Boolean(item)).map(assetFootprint)

  /** A stacked object stays on its supports while it moves. */
  const constrain = (point: Point): Point => (draft?.target === 'object' && draft.onTopOf.length > 0 ? clampToSupports(point, supportPrints(draft)) : point)

  const updateObject = (patch: Partial<ObjectDraft>) => setDraft((current) => (current?.target === 'object' ? { ...current, ...patch } : current))
  const updateOpening = (patch: Partial<OpeningDraft>) => setDraft((current) => (current?.target === 'opening' ? { ...current, ...patch } : current))
  const updateConnector = (patch: Partial<ConnectorDraft>) => setDraft((current) => (current?.target === 'connector' ? { ...current, ...patch } : current))

  const moveTo = (point: Point) => {
    if (draft?.target !== 'object') return
    updateObject({ position: constrain(point) })
  }

  const nudgeBy = (dx: number, dy: number) => {
    if (draft?.target !== 'object' || !draft.position) return
    updateObject({ position: constrain(nudge(draft.position, dx, dy)) })
  }

  const rotate = (delta: number) => {
    if (draft?.target !== 'object') return
    updateObject({ rotation: rotateBy(draft.rotation, delta) })
  }

  /** "Stands on" changed: the draft snaps to the centre of its supports. */
  const setSupports = (ids: string[]) => {
    if (draft?.target !== 'object') return
    const supports = ids.map((id) => allAssets.get(id)).filter((item): item is Asset => Boolean(item))
    const centre = supportCentre(supports.map(assetFootprint))
    setDraft({ ...draft, onTopOf: [...ids].sort(), ...(centre && supports[0] ? { position: centre, floorId: supports[0].floor_id } : {}) })
  }

  /** Propose, then confirm at once: in the editor, Save is the confirmation. */
  const run = async (proposal: EditProposal, after: (action: ActionResult, fresh: Map<string, FloorPlan>) => void) => {
    if (saving) return
    if (!sessionId || isLocal) {
      setError(text.localSession)
      return
    }
    setSaving(true)
    setError(null)
    let created: ActionResult | null = null
    let confirmed = false
    try {
      created = await gateway.createAction(sessionId, proposal)
      const action = await gateway.confirmAction(sessionId, created.id)
      confirmed = true
      const edited = editedFloors(action)
      const floorIds = edited?.floorIds.length ? edited.floorIds : [floorId]
      const fresh = await refreshFloors(floorIds).catch(() => new Map<string, FloorPlan>())
      const merged = new Map(plansRef.current)
      fresh.forEach((plan, id) => merged.set(id, plan))
      after(action, merged)
    } catch (failure: unknown) {
      const ui = toUiError(failure)
      setError(describeEditError(ui, text.errors))
      // Only the confirmation failed: do not leave a pending action that blocks the guide.
      if (created && !confirmed) void gateway.cancelAction(sessionId, created.id).catch(() => undefined)
      if (ui.code === '30013_element_not_found') void refreshFloors([floorId]).catch(() => undefined)
    } finally {
      setSaving(false)
    }
  }

  const summaryOf = (action: ActionResult) => editedFloors(action)?.summary ?? action.summary

  const selectAsset = (asset: Asset) => onSelect({ kind: 'asset', id: asset.id, name: asset.name, floorId: asset.floor_id, floorName: floorName(asset.floor_id), note: asset.type })

  /** After a save the object stays selected and its details show the saved state. */
  const reopen = (action: ActionResult, fresh: Map<string, FloorPlan>, previous: Draft) => {
    const changedIds = Array.isArray(action.result?.changed_ids) ? action.result.changed_ids.filter((id): id is string => typeof id === 'string') : []
    if (previous.target === 'object') {
      const id = previous.objectId ?? changedIds.find((item) => findAsset(fresh, item)) ?? null
      const asset = findAsset(fresh, id)
      if (asset) {
        const next = draftFromAsset(asset, stackingOf(fresh))
        setDraft(next)
        setOriginal(next)
        setStep('form')
        selectAsset(asset)
        return
      }
    }
    if (previous.target === 'opening') {
      const id = previous.openingId ?? changedIds.find((item) => findOpening(fresh, item)) ?? null
      const opening = findOpening(fresh, id)
      if (opening) {
        const next = draftFromOpening(opening)
        setDraft(next)
        setOriginal(next)
        setStep('form')
        onSelect({ kind: 'opening', id: opening.id, name: `${opening.kind}, ${opening.width_m} m`, floorId: opening.floor_id, floorName: floorName(opening.floor_id), note: opening.step_free ? 'Step-free' : 'Has a step' })
        return
      }
    }
    startPicking()
  }

  const save = () => {
    if (!draft || saving) return
    const proposal = buildProposal(draft, original)
    if (!proposal) return
    const previous = draft
    void run(proposal, (action, fresh) => {
      announce(fill(text.saved, { summary: summaryOf(action) }))
      setConfirming(null)
      reopen(action, fresh, previous)
    })
  }

  const targetId = draft?.target === 'object' ? draft.objectId : draft?.target === 'opening' ? draft.openingId : null

  const askRemove = () => {
    if (!targetId) return
    setConfirming('remove')
    focus('confirm')
  }

  const remove = () => {
    if (!targetId) return
    void run(removeProposal(targetId), (action) => {
      announce(fill(text.removed, { summary: summaryOf(action) }))
      setConfirming(null)
      onSelect(null)
      startPicking()
    })
  }

  const undo = () => {
    if (dirty && original) {
      setError(text.undoBlocked)
      return
    }
    const previous = draft
    void run(undoProposal(), (action, fresh) => {
      announce(fill(text.undone, { summary: summaryOf(action) }))
      setConfirming(null)
      // An unsaved new draft stays; an edited object shows its state after the undo.
      if (previous && original) reopen(action, fresh, previous)
    })
  }

  /** Cancel button in the form: same as Esc there. */
  const cancelForm = () => escape()

  /** From an object's details back to the type picker, to add something new. */
  const addNew = () => {
    if (saving) return
    if (dirty && original) askDiscard('back')
    else {
      setError(null)
      startPicking()
    }
  }

  // A new session (other building, expired session) starts the editor over.
  useEffect(() => {
    setDraft(null)
    setOriginal(null)
    setStep('pick')
    setChangingType(false)
    setConfirming(null)
    setError(null)
  }, [sessionId])

  // Picking another object on the map shows its details, unless the draft has unsaved changes.
  useEffect(() => {
    if (!open || !selection || selection.kind === 'space' || saving) return
    if (selection.id === targetId) return
    if (step === 'place' || (draft && !original && draft.target !== 'object')) return
    if (dirty) {
      announce(text.switchBlocked)
      return
    }
    const name = loadDetails(selection, plans)
    if (name) announce(fill(text.opened, { name }))
    // Only a new selection switches the form, not every draft change.
  }, [selection?.id])

  /* Derived view state */

  const objectDraft = draft?.target === 'object' ? draft : null
  const defaultHeight = objectDraft ? catalogHeight(entries, objectDraft.type, objectDraft.category) : 0
  const level = objectDraft ? supportLevel(objectDraft.onTopOf, allAssets, stacking, entries) : { elevation: 0, layer: 0 }
  const height = objectDraft ? objectDraft.height ?? defaultHeight : 0
  const draftPlan = objectDraft ? plans.get(objectDraft.floorId) ?? null : draft?.target === 'opening' ? plans.get(draft.floorId) ?? null : null
  const hintCode: PlacementHint | null = objectDraft && step === 'form' && draftPlan
    ? placementHint(objectDraft, { spaces: draftPlan.spaces, assets: allAssets, floorHeight: floors.find((floor) => floor.id === objectDraft.floorId)?.height_m ?? null, elevation: level.elevation, height })
    : null
  const wall = draft?.target === 'opening' && !original && draft.position && draftPlan ? wallAt(draftPlan.spaces, draft.position) : null
  const wallText = draft?.target === 'opening' && !original
    ? draft.position ? (wall ? fill(text.wallBetween, { first: wall.spaces[0].name, second: wall.spaces[1].name }) : text.wallMissing) : null
    : null
  const hint = hintCode ? text.hints[hintCode] ?? null : null
  const invalid = Boolean(hintCode && hintCode !== 'no_position') || Boolean(draft?.target === 'opening' && !original && draft.position && !wall)
  const draftRoom = objectDraft?.position && draftPlan ? spaceAt(draftPlan.spaces, objectDraft.position) : null
  const descendants = objectDraft?.objectId ? descendantsOf(stacking, objectDraft.objectId) : []
  const removeCount = draft?.target === 'object' ? descendants.length : 0
  const openingTarget = draft?.target === 'opening' ? findOpening(plans, draft.openingId) : null
  const canRemove = draft?.target === 'object' ? Boolean(draft.objectId) : Boolean(openingTarget && isRemovableConnection(openingTarget))
  const proposal = draft ? buildProposal(draft, original) : null
  const canSave = Boolean(proposal) && !saving && !isLocal && step === 'form'
  const stops: StopLabel[] = draft?.target === 'connector'
    ? draft.spaces.map((stop) => ({ id: stop.id, name: findSpace(plans, stop.id)?.name ?? stop.id, floorName: floorName(stop.floorId) }))
    : []
  const selectedSupports = objectDraft ? objectDraft.onTopOf.map((id) => allAssets.get(id)).filter((item): item is Asset => Boolean(item)) : []
  const floorAssets = objectDraft ? plans.get(objectDraft.floorId)?.assets ?? [] : []
  const layerOf = (id: string) => stacking.get(id)?.layer ?? 0

  const mapMode: EditorOverlay['mode'] = step === 'pick' ? 'pick'
    : step === 'place' ? 'place'
      : draft?.target === 'opening' && !original ? 'wall'
        : draft?.target === 'connector' && !original ? 'rooms'
          : 'form'

  const ghosts: GhostAsset[] = []
  let fadedIds: string[] = []
  if (objectDraft?.position && step === 'form') {
    ghosts.push({
      asset: { id: objectDraft.objectId ?? 'draft', name: objectDraft.name || typeLabel(objectDraft), category: objectDraft.category, type: objectDraft.type, space_id: draftRoom?.id ?? '', floor_id: objectDraft.floorId, position: objectDraft.position, footprint: { width_m: objectDraft.width, depth_m: objectDraft.depth, rotation_deg: objectDraft.rotation }, source: 'user_edit' },
      layer: level.layer,
    })
    const before = original?.target === 'object' ? original : null
    if (before?.objectId && before.position) {
      // A support drags its stack along by the same vector.
      const dx = objectDraft.position[0] - before.position[0]
      const dy = objectDraft.position[1] - before.position[1]
      for (const id of descendants) {
        const child = allAssets.get(id)
        if (!child) continue
        ghosts.push({ asset: { ...child, floor_id: objectDraft.floorId, position: [child.position[0] + dx, child.position[1] + dy] }, layer: layerOf(id) })
      }
      fadedIds = [before.objectId, ...descendants]
    }
  }
  const ghostOpening: Opening | null = draft?.target === 'opening' && !original && draft.position
    ? { id: 'draft-opening', floor_id: draft.floorId, space_ids: wall ? wall.spaces.map((space) => space.id) : [], kind: draft.kind, position: draft.position, width_m: draft.width, step_free: draft.stepFree, synthetic: true }
    : null

  const overlay: EditorOverlay | null = open
    ? {
        mode: mapMode,
        ghosts,
        ghostOpening,
        cursor: objectDraft && step === 'place' ? { width: objectDraft.width, depth: objectDraft.depth, rotation: objectDraft.rotation, category: objectDraft.category } : null,
        fadedIds,
        pickedSpaceIds: draft?.target === 'connector' ? draft.spaces.map((stop) => stop.id) : draft?.target === 'opening' ? [draft.firstSpace, draft.secondSpace].filter((id): id is string => Boolean(id)) : [],
        invalid,
        draggable: Boolean(objectDraft?.position) && step === 'form' && !saving,
        constrain,
        onPoint: (point) => (mapMode === 'place' ? placeAt(point) : mapMode === 'wall' ? wallClick(point) : undefined),
        onPickSpace: pickStop,
        onDragEnd: moveTo,
      }
    : null

  const caption = !open ? null
    : mapMode === 'pick' ? text.captionPick
      : mapMode === 'place' ? fill(text.captionPlace, { type: typeLabel(draft) })
        : mapMode === 'wall' ? (wallText ?? text.captionWall)
          : mapMode === 'rooms' ? text.captionRooms
            : `${fill(text.captionForm, { name: objectDraft?.name || typeLabel(draft) })}${hint ? ` ${hint}` : ''}`

  // Keyboard: E toggles; with the editor open, Esc cancels, arrows nudge, R rotates.
  const latest = useRef({ open, step, saving, toggle, escape, nudgeBy, rotate, movable: false })
  latest.current = { open, step, saving, toggle, escape, nudgeBy, rotate, movable: Boolean(objectDraft?.position) && step === 'form' }
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const api = latest.current
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return
      const typing = typingTarget(event.target)
      if ((event.key === 'e' || event.key === 'E') && !typing && !event.repeat) {
        event.preventDefault()
        api.toggle()
        return
      }
      if (!api.open) return
      if (event.key === 'Escape') {
        event.preventDefault()
        api.escape()
        return
      }
      if (typing || !api.movable || api.saving) return
      const stepSize = event.shiftKey ? NUDGE_FAST_M : NUDGE_M
      const moves: Record<string, Point> = { ArrowUp: [0, stepSize], ArrowDown: [0, -stepSize], ArrowLeft: [-stepSize, 0], ArrowRight: [stepSize, 0] }
      const move = moves[event.key]
      if (move) {
        event.preventDefault()
        api.nudgeBy(move[0], move[1])
        return
      }
      if (event.key === 'r' || event.key === 'R') {
        event.preventDefault()
        api.rotate(event.shiftKey ? -ROTATE_STEP_DEG : ROTATE_STEP_DEG)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const groups: ObjectGroup[] = catalog.groups

  return {
    open,
    step,
    changingType,
    draft,
    original,
    dirty,
    saving,
    error,
    confirming,
    discardIntent,
    announcement,
    focusRequest,
    isLocal,
    entries,
    groups,
    recent,
    catalogOffline,
    overlay,
    caption,
    hint,
    hintCode,
    invalid,
    wallText,
    typeLabel: typeLabel(draft),
    draftRoomName: draftRoom?.name ?? null,
    currentSpaces,
    floorId,
    floorName,
    height: { value: height, custom: objectDraft?.height != null, canReset: objectDraft?.height != null && (original?.target !== 'object' || original.height == null), elevation: level.elevation, layer: level.layer, defaultHeight },
    floorAssets,
    selectedSupports,
    descendants,
    layerOf,
    stops,
    removeCount,
    canRemove,
    canSave,
    toggle,
    editItem,
    requestClose,
    escape,
    chooseType,
    startChangeType,
    backToTypes: startPicking,
    placeInSpace,
    chooseOpeningRooms,
    pickStop,
    updateObject,
    updateOpening,
    updateConnector,
    setSupports,
    rotate,
    save,
    askRemove,
    remove,
    undo,
    cancelForm,
    addNew,
    confirmDiscard,
    dismissConfirm,
  }
}
