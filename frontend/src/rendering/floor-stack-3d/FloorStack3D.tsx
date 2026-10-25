import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import type { Asset, FloorPlan, Point, Route, Selection, Space } from '../../domain/types'
import { copy } from '../../i18n/en'
import { MapTooltip, assetTip, spaceTip } from '../MapTooltip'
import { perimeterSegments } from './perimeter'
import { addObjectModels, objectPlacements, updateObjectModels } from './object-models'

type FloorStack3DProps = {
  plans: FloorPlan[]
  /** Unsaved editor state; transforms update immediately and revert when the draft is cancelled. */
  previewPlans?: FloorPlan[] | null
  route: Route | null
  activeFloorId: string
  onSelectFloor?: (floorId: string) => void
  /** Clicked items, and clicked rooms of the single-floor view. */
  onSelect?: (selection: Selection) => void
  /** The selected element; an item gets an outline. */
  selectedId?: string | null
}

/** `single` shows only the viewed floor; `all` is the exploded overview of every floor. */
type StackMode = 'single' | 'all'

type Tone = 'room' | 'office' | 'corridor' | 'restroom' | 'lift' | 'stair'
const tones: Tone[] = ['room', 'office', 'corridor', 'restroom', 'lift', 'stair']

type Palette = Record<Tone, THREE.Color> & {
  slab: THREE.Color
  slabEdge: THREE.Color
  wall: THREE.Color
  wallTop: THREE.Color
  exterior: THREE.Color
  exteriorEdge: THREE.Color
  primary: THREE.Color
  start: THREE.Color
  destination: THREE.Color
  danger: THREE.Color
  background: THREE.Color
}

/** A material whose opacity is `base` (set by the palette) times the floor's fade. */
type Fader = { material: THREE.Material; base: number }

/** Exterior walls are grouped by facing so walls between the camera and the floor can turn see-through. */
type Facade = { normal: THREE.Vector2; fill: Fader; edge: Fader; facing: number }

type FloorRecord = {
  id: string
  index: number
  group: THREE.Group
  compactY: number
  explodedY: number
  y: number
  fade: number
  box: { x0: number; x1: number; z0: number; z1: number }
  contentHeight: number
  structureHeight: number
  objects: THREE.Group
  rooms: Map<Tone, Fader>
  wall: Fader
  wallTop: Fader
  slab: Fader & { material: THREE.MeshLambertMaterial }
  slabEdge: Fader
  halo: Fader
  facades: Facade[]
  route: Fader[]
  models: { material: THREE.Material; opacity: number; depthWrite: boolean }[]
  /** What hover and click resolve against: rooms and, once loaded, items. The slab only blocks floors below. */
  targets: THREE.Object3D[]
  label: HTMLDivElement
}

type View = { position: THREE.Vector3; target: THREE.Vector3; zoom: number }

type SceneApi = {
  focus: (floorId: string, mode: StackMode) => void
  resetView: () => void
  select: (id: string | null) => void
  updateModels: (plans: FloorPlan[]) => void
}

// About 23° above the horizon: lower than true isometric so the gaps between floors read clearly.
const isoDirection = new THREE.Vector3(1, 0.6, 1).normalize()
const up = new THREE.Vector3(0, 1, 0)

function toneOf(space: Space): Tone {
  const type = (space.room_type || space.type || 'other').toLowerCase().replace(/[^a-z0-9]+/g, '-')
  if (['stair', 'stairs', 'emergency-exit', 'emergency-corridor'].includes(type)) return 'stair'
  if (type === 'lift' || type === 'elevator') return 'lift'
  if (type === 'corridor' || type === 'hallway') return 'corridor'
  if (type === 'restroom' || type === 'toilet') return 'restroom'
  if (type === 'office') return 'office'
  return 'room'
}

function centroid(polygon: Point[]): Point {
  const sum = polygon.reduce<Point>((total, [x, y]) => [total[0] + x, total[1] + y], [0, 0])
  return [sum[0] / polygon.length, sum[1] / polygon.length]
}

/** Mixes in sRGB so the stack matches the CSS `color-mix(in srgb, …)` room fills of the flat plan. */
function mix(base: THREE.Color, accent: THREE.Color, amount: number): THREE.Color {
  const a = base.getRGB({ r: 0, g: 0, b: 0 }, THREE.SRGBColorSpace)
  const b = accent.getRGB({ r: 0, g: 0, b: 0 }, THREE.SRGBColorSpace)
  return new THREE.Color().setRGB(
    a.r + (b.r - a.r) * amount,
    a.g + (b.g - a.g) * amount,
    a.b + (b.b - a.b) * amount,
    THREE.SRGBColorSpace,
  )
}

function readPalette(element: Element): Palette {
  const style = getComputedStyle(element)
  const read = (name: string, fallback: string) => {
    const value = style.getPropertyValue(name).trim()
    const color = new THREE.Color(fallback)
    if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value) || /^rgb/i.test(value)) color.setStyle(value)
    return color
  }
  const space = read('--map-space', '#171e27')
  const stroke = read('--map-space-stroke', '#53616c')
  const surface = read('--color-surface-raised', '#171e27')
  const border = read('--color-border-strong', '#41505c')
  const text = read('--color-text-primary', '#f3f6f1')
  const primary = read('--color-primary', '#c2f44b')
  const start = read('--color-start', '#9182ff')
  const danger = read('--color-danger', '#ff8a7a')
  return {
    room: space,
    office: mix(space, primary, 0.22),
    corridor: mix(space, read('--color-warning', '#f2bd4e'), 0.26),
    restroom: mix(space, read('--color-restroom', '#4db6d6'), 0.32),
    lift: mix(space, start, 0.34),
    stair: mix(space, danger, 0.34),
    slab: mix(surface, border, 0.4),
    slabEdge: border,
    wall: mix(space, stroke, 0.45),
    wallTop: stroke,
    exterior: mix(surface, stroke, 0.55),
    exteriorEdge: mix(stroke, text, 0.35),
    primary,
    start,
    destination: read('--color-destination', '#ff765b'),
    danger,
    background: read('--color-background', '#0a0d12'),
  }
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function approach(current: number, goal: number, rate: number): number {
  return current + (goal - current) * Math.min(1, rate)
}

function wallGeometry(polygons: Point[][], height: number, toWorld: (point: Point) => [number, number]): THREE.BufferGeometry {
  const positions: number[] = []
  for (const polygon of polygons) {
    for (let index = 0; index < polygon.length; index += 1) {
      const [ax, az] = toWorld(polygon[index])
      const [bx, bz] = toWorld(polygon[(index + 1) % polygon.length])
      positions.push(ax, 0, az, bx, 0, bz, bx, height, bz, ax, 0, az, bx, height, bz, ax, height, az)
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.computeVertexNormals()
  return geometry
}

function outlineGeometry(polygons: Point[][], height: number, toWorld: (point: Point) => [number, number]): THREE.BufferGeometry {
  const positions: number[] = []
  for (const polygon of polygons) {
    for (let index = 0; index < polygon.length; index += 1) {
      const [ax, az] = toWorld(polygon[index])
      const [bx, bz] = toWorld(polygon[(index + 1) % polygon.length])
      positions.push(ax, height, az, bx, height, bz)
    }
  }
  return new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
}

/** Thick exterior wall prisms (outer, inner, end, and top faces), pushed outward from the room edge. */
function prismPositions(positions: number[], a: [number, number], b: [number, number], normal: [number, number], thickness: number, height: number) {
  const corners = [a, b, [b[0] + normal[0] * thickness, b[1] + normal[1] * thickness], [a[0] + normal[0] * thickness, a[1] + normal[1] * thickness]]
  const low = corners.map(([x, z]) => [x, 0, z])
  const high = corners.map(([x, z]) => [x, height, z])
  const quad = (p: number[], q: number[], r: number[], t: number[]) => positions.push(...p, ...q, ...r, ...p, ...r, ...t)
  for (let side = 0; side < 4; side += 1) {
    const next = (side + 1) % 4
    quad(low[side], low[next], high[next], high[side])
  }
  quad(high[0], high[1], high[2], high[3])
}

/** Keeps the previous array when its items are the same objects, so a parent's fresh `[...map.values()]` does not rebuild the scene. */
function useStableItems<T>(items: T[]): T[] {
  const previous = useRef(items)
  if (previous.current.length !== items.length || previous.current.some((item, index) => item !== items[index])) previous.current = items
  return previous.current
}

/** Dimension/position edits reuse the scene; adding an object or changing its model rebuilds it. */
function useScenePlans(plans: FloorPlan[], preview: FloorPlan[] | null): FloorPlan[] {
  const shown = preview ?? plans
  const key = useMemo(() => JSON.stringify(shown.map((plan) => [plan.floor.id, plan.assets.map((asset) => [asset.id, asset.type, asset.category])])), [shown])
  const previous = useRef({ plans, key, shown })
  if (previous.current.plans !== plans || previous.current.key !== key) previous.current = { plans, key, shown }
  return previous.current.shown
}

function useStableRoute(route: Route | null): Route | null {
  const previous = useRef<{ key: string; route: Route | null }>({ key: '', route: null })
  const key = route ? JSON.stringify([route.id, route.length_m, route.legs]) : ''
  if (previous.current.key !== key) previous.current = { key, route }
  return previous.current.route
}

function ResetIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
    </svg>
  )
}

function ExpandIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {expanded
        ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" />
        : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
    </svg>
  )
}

function LayersIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 13 9 5 9-5" />
    </svg>
  )
}

export function FloorStack3D({ plans: incomingPlans, previewPlans = null, route: incomingRoute, activeFloorId, onSelectFloor, onSelect, selectedId = null }: FloorStack3DProps) {
  const plans = useStableItems(incomingPlans)
  const scenePlans = useScenePlans(plans, previewPlans)
  const shownPlans = previewPlans ?? plans
  const shownPlansRef = useRef(shownPlans)
  shownPlansRef.current = shownPlans
  const route = useStableRoute(incomingRoute)
  const host = useRef<HTMLDivElement>(null)
  const api = useRef<SceneApi | null>(null)
  const savedView = useRef<{ key: string; view: View; atHome: boolean } | null>(null)
  const expandButton = useRef<HTMLButtonElement>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [tip, setTip] = useState<{ item: Selection; x: number; y: number } | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [mode, setMode] = useState<StackMode>('all')
  // The floor shown in the stack. It follows the plan's floor, and picking a floor here updates the plan too.
  const [viewedId, setViewedId] = useState(activeFloorId)
  useEffect(() => setViewedId(activeFloorId), [activeFloorId])
  const viewedRef = useRef(viewedId)
  const modeRef = useRef(mode)
  viewedRef.current = viewedId
  modeRef.current = mode

  const selectFloor = (floorId: string) => {
    setViewedId(floorId)
    setMode('single')
    onSelectFloor?.(floorId)
  }
  const selectRef = useRef(selectFloor)
  selectRef.current = selectFloor
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const selectedRef = useRef(selectedId)
  selectedRef.current = selectedId

  const ordered = useMemo(() => [...scenePlans].sort((left, right) => left.floor.elevation_m - right.floor.elevation_m), [scenePlans])
  const routeFloors = useMemo(() => new Set((route?.legs ?? []).filter((leg) => leg.points.length > 0).map((leg) => leg.floor_id)), [route])

  useEffect(() => {
    const element = host.current
    if (!element || ordered.length === 0) return
    element.dataset.modelsReady = 'false'
    element.dataset.objectCount = '0'
    const reducedMotion = prefersReducedMotion()
    const sceneKey = ordered.map((plan) => plan.floor.id).join('|')
    // Only the first build of a building animates the floors apart; route updates keep the current view.
    const animateIn = !reducedMotion && savedView.current?.key !== sceneKey

    const points = ordered.flatMap((plan) => plan.spaces.flatMap((space) => space.polygon))
    if (points.length === 0) return
    const xs = points.map(([x]) => x)
    const ys = points.map(([, y]) => y)
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)
    const centerX = (minX + maxX) / 2
    const centerY = (minY + maxY) / 2
    const span = Math.max(maxX - minX, maxY - minY, 1)
    // Plan y grows north; world -z is away from the camera, so north stays at the back.
    const toWorld = ([x, y]: Point): [number, number] => [x - centerX, -(y - centerY)]

    const pad = span * 0.035
    const slabDepth = Math.max(span * 0.014, 0.3)
    const maxStorey = Math.max(...ordered.map((plan) => plan.floor.height_m || 3), 3)
    const wallHeight = Math.min(Math.max(span * 0.016, 0.9), maxStorey * 0.5)
    const gap = Math.max(span * (ordered.length <= 3 ? 0.55 : 0.42), maxStorey * 2, 5)
    const lift = gap * 0.12
    const away = gap * 0.7
    const wallThickness = Math.max(span * 0.004, 0.25)
    const baseElevation = ordered[0].floor.elevation_m
    const tubeRadius = Math.max(span * 0.0045, 0.14)

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000, 0)
    const labels = new CSS2DRenderer()
    labels.domElement.className = 'stack-labels'
    element.replaceChildren(renderer.domElement, labels.domElement)

    const scene = new THREE.Scene()
    const hemisphere = new THREE.HemisphereLight(0xffffff, 0x808080, 1.6)
    const sun = new THREE.DirectionalLight(0xffffff, 1.4)
    sun.position.set(-span * 0.6, span * 1.4, span * 0.9)
    scene.add(hemisphere, sun)

    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -span * 40, span * 40)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.screenSpacePanning = true
    controls.zoomToCursor = true
    controls.minPolarAngle = 0.08
    controls.maxPolarAngle = Math.PI * 0.49

    const floors: FloorRecord[] = []
    const removeModels: (() => void)[] = []
    let pendingModels = ordered.length
    let objectCount = 0
    const pickables: THREE.Object3D[] = []
    const floorIndex = new Map<string, number>()
    const spaces = new Map<string, { plan: FloorPlan; space: Space }>()
    const assets = new Map<string, { plan: FloorPlan; asset: Asset }>()
    for (const plan of ordered) {
      for (const space of plan.spaces) spaces.set(space.id, { plan, space })
      for (const asset of plan.assets) assets.set(asset.id, { plan, asset })
    }
    // Highlight: a box outline around the hovered and the selected item model.
    const instances = new Map<string, { mesh: THREE.InstancedMesh; index: number }>()
    const boxEdges = new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0))
    const outline = (opacity: number) => {
      const line = new THREE.LineSegments(boxEdges, new THREE.LineBasicMaterial({ transparent: true, opacity, depthTest: false }))
      line.matrixAutoUpdate = false
      line.renderOrder = 12
      return line
    }
    const hoverOutline = outline(0.55)
    const selectOutline = outline(1)
    // The instance matrix maps the unit box onto the model's footprint and height; the object group carries the floor's animation.
    const outlineItem = (line: ReturnType<typeof outline>, id: string | null) => {
      const found = id ? instances.get(id) : undefined
      if (!found) { line.removeFromParent(); return }
      found.mesh.getMatrixAt(found.index, line.matrix)
      line.matrixWorldNeedsUpdate = true
      found.mesh.parent?.add(line)
    }
    const fader = <M extends THREE.Material>(material: M) => ({ material, base: 1 })

    // The route layer ignores depth so walls never chop it into dashes.
    const overlay = () => new THREE.MeshBasicMaterial({ depthTest: false, depthWrite: false, transparent: true })

    ordered.forEach((plan, index) => {
      floorIndex.set(plan.floor.id, index)
      const group = new THREE.Group()
      group.name = `floor:${plan.floor.id}`
      const compactY = plan.floor.elevation_m - baseElevation
      const explodedY = gap * index
      const y = animateIn ? compactY : explodedY
      group.position.y = y
      scene.add(group)

      // Each slab hugs its own floor, so a smaller upper storey does not hide the one below.
      const own = plan.spaces.flatMap((space) => space.polygon).map(toWorld)
      const x0 = Math.min(...own.map(([x]) => x)) - pad
      const x1 = Math.max(...own.map(([x]) => x)) + pad
      const z0 = Math.min(...own.map(([, z]) => z)) - pad
      const z1 = Math.max(...own.map(([, z]) => z)) + pad
      const slabShape = new THREE.Shape()
      slabShape.moveTo(x0, -z1)
      slabShape.lineTo(x1, -z1)
      slabShape.lineTo(x1, -z0)
      slabShape.lineTo(x0, -z0)
      slabShape.closePath()
      const slabGeometry = new THREE.ExtrudeGeometry(slabShape, { depth: slabDepth, bevelEnabled: false })
      slabGeometry.rotateX(-Math.PI / 2)
      slabGeometry.translate(0, -slabDepth - 0.01, 0)
      const slab = fader(new THREE.MeshLambertMaterial({ transparent: true }))
      const slabMesh = new THREE.Mesh(slabGeometry, slab.material)
      slabMesh.userData.floorId = plan.floor.id
      pickables.push(slabMesh)
      const targets: THREE.Object3D[] = [slabMesh]
      const slabEdge = fader(new THREE.LineBasicMaterial({ transparent: true }))
      group.add(slabMesh, new THREE.LineSegments(new THREE.EdgesGeometry(slabGeometry), slabEdge.material))

      const halo = fader(new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }))
      const haloMesh = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0 + pad * 2, z1 - z0 + pad * 2), halo.material)
      haloMesh.rotation.x = -Math.PI / 2
      haloMesh.position.set((x0 + x1) / 2, -slabDepth - 0.06, (z0 + z1) / 2)
      group.add(haloMesh)

      const rooms = new Map<Tone, Fader>()
      const polygons: Point[][] = []
      for (const space of plan.spaces) {
        if (space.polygon.length < 3) continue
        const tone = toneOf(space)
        let material = rooms.get(tone)
        if (!material) {
          material = fader(new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 }))
          rooms.set(tone, material)
        }
        const shape = new THREE.Shape(space.polygon.map((point) => {
          const [x, z] = toWorld(point)
          return new THREE.Vector2(x, -z)
        }))
        const geometry = new THREE.ShapeGeometry(shape)
        geometry.rotateX(-Math.PI / 2)
        const mesh = new THREE.Mesh(geometry, material.material)
        mesh.position.y = 0.02
        mesh.userData.floorId = plan.floor.id
        mesh.userData.spaceId = space.id
        pickables.push(mesh)
        targets.push(mesh)
        group.add(mesh)
        polygons.push(space.polygon)
      }
      const wall = fader(new THREE.MeshLambertMaterial({ transparent: true, side: THREE.DoubleSide, depthWrite: false }))
      const wallTop = fader(new THREE.LineBasicMaterial({ transparent: true }))
      group.add(new THREE.Mesh(wallGeometry(polygons, wallHeight, toWorld), wall.material))
      group.add(new THREE.LineSegments(outlineGeometry(polygons, wallHeight, toWorld), wallTop.material))
      group.add(new THREE.LineSegments(outlineGeometry(polygons, 0.03, toWorld), wallTop.material))

      // Storey-high exterior walls around the floor's outline, bucketed into eight facings.
      const exteriorHeight = Math.min(Math.max(Math.min(plan.floor.height_m || 3, 4.5), span * 0.03), gap * 0.6)
      const buckets = new Map<number, number[]>()
      for (const segment of perimeterSegments(polygons, Math.max(span / 240, 0.25), Math.max(span * 0.006, 0.6))) {
        const normal: [number, number] = [segment.normal[0], -segment.normal[1]]
        const key = (Math.round(Math.atan2(normal[1], normal[0]) / (Math.PI / 4)) + 8) % 8
        const positions = buckets.get(key) ?? []
        prismPositions(positions, toWorld(segment.a), toWorld(segment.b), normal, wallThickness, exteriorHeight)
        buckets.set(key, positions)
      }
      const facades: Facade[] = []
      for (const [key, positions] of buckets) {
        const geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
        geometry.computeVertexNormals()
        const fill = fader(new THREE.MeshLambertMaterial({ transparent: true, side: THREE.DoubleSide }))
        const edge = fader(new THREE.LineBasicMaterial({ transparent: true }))
        const mesh = new THREE.Mesh(geometry, fill.material)
        mesh.userData.floorId = plan.floor.id
        pickables.push(mesh)
        group.add(mesh, new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), edge.material))
        const angle = (key * Math.PI) / 4
        facades.push({ normal: new THREE.Vector2(Math.cos(angle), Math.sin(angle)), fill, edge, facing: 1 })
      }

      const label = document.createElement('div')
      label.className = 'stack-label'
      const level = document.createElement('span')
      level.className = 'stack-label-level'
      level.textContent = `L${plan.floor.level}`
      const name = document.createElement('span')
      name.className = 'stack-label-name'
      name.textContent = plan.floor.name
      const meta = document.createElement('span')
      meta.className = 'stack-label-meta mono'
      meta.textContent = `${plan.floor.elevation_m} m`
      label.append(level, name, meta)
      const labelObject = new CSS2DObject(label)
      labelObject.center.set(1, 0.5)
      labelObject.position.set(x0, -slabDepth / 2, z1)
      group.add(labelObject)

      // The loader uses dataset metre coordinates. Translate into this floor's
      // centred frame; the parent owns the animated elevation, never object scale.
      const objectGroup = new THREE.Group()
      objectGroup.name = `objects:${plan.floor.id}`
      objectGroup.position.set(-centerX, -plan.floor.elevation_m, centerY)
      group.add(objectGroup)
      const models: FloorRecord['models'] = []
      removeModels.push(addObjectModels(objectGroup, [plan], (count) => {
        const materials = new Set<THREE.Material>()
        objectGroup.traverse((object) => {
          if (!(object instanceof THREE.InstancedMesh)) return
          targets.push(object)
          for (const [index, id] of ((object.userData.assetIds ?? []) as string[]).entries()) if (!instances.has(id)) instances.set(id, { mesh: object, index })
          for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material)
        })
        api.current?.updateModels(shownPlansRef.current)
        for (const material of materials) {
          models.push({ material, opacity: material.opacity, depthWrite: material.depthWrite })
          material.transparent = true
          material.needsUpdate = true
        }
        objectCount += count
        pendingModels -= 1
        element.dataset.objectCount = String(objectCount)
        element.dataset.modelsReady = String(pendingModels === 0)
      }))

      floors.push({
        id: plan.floor.id, index, group, compactY, explodedY, y, fade: 1,
        box: { x0, x1, z0, z1 },
        contentHeight: Math.max(exteriorHeight, ...objectPlacements(plan).map(({ elevation, height }) => elevation - plan.floor.elevation_m + height)),
        structureHeight: exteriorHeight, objects: objectGroup,
        rooms, wall, wallTop, slab, slabEdge, halo, facades, models, targets,
        route: [fader(overlay()), fader(overlay()), fader(overlay())],
        label,
      })
    })

    // Vertical links: lift and stair shafts, and the route's floor changes. They only appear in the overview.
    type Link = { from: [number, THREE.Vector3]; to: [number, THREE.Vector3] }
    const shaftLinks: Record<'lift' | 'stair', Link[]> = { lift: [], stair: [] }
    const connectors = new Map(ordered.flatMap((plan) => plan.connectors).map((connector) => [connector.id, connector]))
    for (const connector of connectors.values()) {
      const stops: [number, THREE.Vector3][] = []
      ordered.forEach((plan, index) => {
        const space = plan.spaces.find((item) => connector.space_ids.includes(item.id) && item.polygon.length > 0)
        if (!space) return
        const [x, z] = toWorld(centroid(space.polygon))
        stops.push([index, new THREE.Vector3(x, 0.05, z)])
      })
      const kind = connector.kind === 'lift' || connector.kind === 'elevator' ? 'lift' : 'stair'
      for (let index = 1; index < stops.length; index += 1) shaftLinks[kind].push({ from: stops[index - 1], to: stops[index] })
    }
    const shaftMaterials = {
      lift: new THREE.LineDashedMaterial({ dashSize: span * 0.012, gapSize: span * 0.008, transparent: true }),
      stair: new THREE.LineDashedMaterial({ dashSize: span * 0.012, gapSize: span * 0.008, transparent: true }),
    }
    const shaftLines = (['lift', 'stair'] as const).map((kind) => {
      const geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(shaftLinks[kind].length * 6), 3))
      const line = new THREE.LineSegments(geometry, shaftMaterials[kind])
      line.frustumCulled = false
      scene.add(line)
      return { links: shaftLinks[kind], line }
    })

    const legs = (route?.legs ?? [])
      .filter((leg) => leg.points.length > 0 && floorIndex.has(leg.floor_id))
      .map((leg) => ({ index: floorIndex.get(leg.floor_id)!, points: leg.points.map((point) => { const [x, z] = toWorld(point); return new THREE.Vector3(x, 0.35, z) }) }))
    for (const leg of legs) {
      if (leg.points.length < 2) continue
      const path = new THREE.CurvePath<THREE.Vector3>()
      for (let index = 1; index < leg.points.length; index += 1) path.add(new THREE.LineCurve3(leg.points[index - 1], leg.points[index]))
      const tube = new THREE.Mesh(new THREE.TubeGeometry(path, Math.max(leg.points.length * 6, 12), tubeRadius, 8, false), floors[leg.index].route[0].material)
      tube.renderOrder = 10
      floors[leg.index].group.add(tube)
    }
    const linkMaterial = overlay()
    const transfers: { link: Link; mesh: THREE.Mesh }[] = []
    const transferGeometry = new THREE.CylinderGeometry(tubeRadius, tubeRadius, 1, 8, 1, true)
    for (let index = 1; index < legs.length; index += 1) {
      const previous = legs[index - 1]
      const next = legs[index]
      if (previous.index === next.index) continue
      const mesh = new THREE.Mesh(transferGeometry, linkMaterial)
      mesh.renderOrder = 10
      scene.add(mesh)
      transfers.push({ link: { from: [previous.index, previous.points[previous.points.length - 1]], to: [next.index, next.points[0]] }, mesh })
    }
    let pulse: THREE.Mesh | null = null
    const pulseMaterial = overlay()
    if (legs.length > 0) {
      const first = legs[0]
      const last = legs[legs.length - 1]
      const end = last.points[last.points.length - 1]
      const startMarker = new THREE.Mesh(new THREE.SphereGeometry(tubeRadius * 3, 20, 12), floors[first.index].route[1].material)
      startMarker.position.copy(first.points[0]).setY(tubeRadius * 3)
      const pin = new THREE.Mesh(new THREE.ConeGeometry(tubeRadius * 3, tubeRadius * 9, 20), floors[last.index].route[2].material)
      pin.rotation.x = Math.PI
      pin.position.copy(end).setY(tubeRadius * 6)
      const ring = new THREE.Mesh(new THREE.RingGeometry(tubeRadius * 3.5, tubeRadius * 5, 32), floors[last.index].route[2].material)
      ring.rotation.x = -Math.PI / 2
      ring.position.copy(end).setY(0.08)
      for (const marker of [startMarker, pin, ring]) marker.renderOrder = 10
      floors[first.index].group.add(startMarker)
      floors[last.index].group.add(pin, ring)
      if (!reducedMotion) {
        pulse = new THREE.Mesh(new THREE.SphereGeometry(tubeRadius * 2.2, 16, 10), pulseMaterial)
        pulse.renderOrder = 11
        scene.add(pulse)
      }
    }

    let viewedFloor = viewedRef.current
    let stackMode = modeRef.current
    let hoveredFloor: string | null = null
    let linkFade = stackMode === 'all' ? 1 : 0
    const shown = (floor: FloorRecord) => stackMode === 'all' || floor.id === viewedFloor
    for (const floor of floors) floor.fade = shown(floor) ? 1 : 0

    const paint = () => {
      const palette = readPalette(element)
      hemisphere.groundColor.copy(palette.background)
      for (const floor of floors) {
        const viewed = floor.id === viewedFloor
        // In the overview the viewed or hovered floor is solid and the rest are ghosted; a single floor is always solid.
        const focused = stackMode === 'single' || viewed || floor.id === hoveredFloor
        for (const tone of tones) {
          const room = floor.rooms.get(tone)
          if (!room) continue
          ;(room.material as THREE.MeshBasicMaterial).color.copy(palette[tone])
          room.base = focused ? 1 : 0.42
        }
        ;(floor.wall.material as THREE.MeshLambertMaterial).color.copy(palette.wall)
        floor.wall.base = focused ? 0.82 : 0.22
        ;(floor.wallTop.material as THREE.LineBasicMaterial).color.copy(palette.wallTop)
        floor.wallTop.base = focused ? 1 : 0.4
        floor.slab.material.color.copy(palette.slab)
        floor.slab.material.emissive.copy(palette.primary).multiplyScalar(viewed ? 0.12 : 0)
        floor.slab.base = focused ? 1 : 0.38
        ;(floor.slabEdge.material as THREE.LineBasicMaterial).color.copy(viewed ? palette.primary : palette.slabEdge)
        floor.slabEdge.base = focused ? 1 : 0.55
        ;(floor.halo.material as THREE.MeshBasicMaterial).color.copy(palette.primary)
        floor.halo.base = viewed ? 0.16 : 0
        for (const facade of floor.facades) {
          ;(facade.fill.material as THREE.MeshLambertMaterial).color.copy(palette.exterior)
          facade.fill.base = focused ? 1 : 0.3
          ;(facade.edge.material as THREE.LineBasicMaterial).color.copy(palette.exteriorEdge)
          facade.edge.base = focused ? 1 : 0.45
        }
        const [tube, start, destination] = floor.route
        ;(tube.material as THREE.MeshBasicMaterial).color.copy(palette.primary)
        ;(start.material as THREE.MeshBasicMaterial).color.copy(palette.start)
        ;(destination.material as THREE.MeshBasicMaterial).color.copy(palette.destination)
        floor.label.classList.toggle('active', viewed)
        floor.label.classList.toggle('hovered', floor.id === hoveredFloor)
      }
      shaftMaterials.lift.color.copy(palette.start)
      shaftMaterials.stair.color.copy(palette.danger)
      linkMaterial.color.copy(palette.primary)
      pulseMaterial.color.copy(palette.start)
      hoverOutline.material.color.copy(palette.primary)
      selectOutline.material.color.copy(palette.primary)
    }
    paint()

    const home: View = { position: new THREE.Vector3(), target: new THREE.Vector3(), zoom: 1 }
    const fitHome = (width: number, height: number) => {
      const visible = floors.filter(shown)
      const x0 = Math.min(...visible.map((floor) => floor.box.x0))
      const x1 = Math.max(...visible.map((floor) => floor.box.x1))
      const z0 = Math.min(...visible.map((floor) => floor.box.z0))
      const z1 = Math.max(...visible.map((floor) => floor.box.z1))
      const y0 = Math.min(...visible.map((floor) => floor.explodedY)) - slabDepth
      const y1 = Math.max(...visible.map((floor) => floor.explodedY + floor.contentHeight)) + (stackMode === 'all' ? lift : 0)
      const target = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
      const probe = new THREE.OrthographicCamera(-width / height, width / height, 1, -1, -span * 40, span * 40)
      probe.position.copy(target).addScaledVector(isoDirection, span * 4)
      probe.lookAt(target)
      probe.updateMatrixWorld()
      let extentX = 0
      let extentY = 0
      for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) {
        const local = new THREE.Vector3(x, y, z).applyMatrix4(probe.matrixWorldInverse)
        extentX = Math.max(extentX, Math.abs(local.x))
        extentY = Math.max(extentY, Math.abs(local.y))
      }
      // Leave room on the left for floor labels and at the edges for the overlay chrome.
      const labelRoom = Math.min(180, width * 0.3)
      const zoom = Math.max(Math.min((width - labelRoom - 48) / (extentX * height), (height - 170) / (extentY * height)), 0.01)
      const worldPerPixel = 2 / (zoom * height)
      const right = new THREE.Vector3().crossVectors(isoDirection.clone().negate(), up).normalize()
      target.addScaledVector(right, -labelRoom * 0.5 * worldPerPixel)
      home.target.copy(target)
      home.position.copy(target).addScaledVector(isoDirection, span * 4)
      home.zoom = zoom
      controls.minZoom = zoom * 0.3
      controls.maxZoom = zoom * 10
    }

    let size = { width: 0, height: 0 }
    // While the camera sits at its home view, a resize (Expand, rotation) refits instead of cropping.
    let atHome = savedView.current?.key !== sceneKey || savedView.current.atHome
    let tween: { from: View; to: View | null; start: number } | null = null
    const applyView = (view: View) => {
      camera.position.copy(view.position)
      controls.target.copy(view.target)
      camera.zoom = view.zoom
      camera.updateProjectionMatrix()
    }
    const resize = () => {
      const width = Math.max(element.clientWidth, 280)
      const height = Math.max(element.clientHeight, 280)
      if (width === size.width && height === size.height) return
      const first = size.width === 0
      size = { width, height }
      renderer.setSize(width, height)
      labels.setSize(width, height)
      camera.left = -width / height
      camera.right = width / height
      camera.top = 1
      camera.bottom = -1
      fitHome(width, height)
      if (atHome) applyView(home)
      else if (first && savedView.current) applyView(savedView.current.view)
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)

    const themeObserver = new MutationObserver(paint)
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-system-theme', 'class'] })

    const current = (): View => ({ position: camera.position.clone(), target: controls.target.clone(), zoom: camera.zoom })
    const moveTo = (to: View | null) => {
      if (reducedMotion) { applyView(to ?? home); tween = null; return }
      tween = { from: current(), to, start: performance.now() }
    }
    const resetView = () => {
      atHome = true
      moveTo(null)
    }
    // Switching floors keeps the user's orbit and zoom, and only slides the camera to the new floor.
    const focus = (floorId: string, nextMode: StackMode) => {
      if (floorId === viewedFloor && nextMode === stackMode) return
      const before = home.target.clone()
      viewedFloor = floorId
      stackMode = nextMode
      paint()
      fitHome(size.width, size.height)
      if (atHome) { moveTo(null); return }
      const shift = home.target.clone().sub(before)
      shift.x = 0
      shift.z = 0
      const view = current()
      moveTo({ position: view.position.add(shift), target: view.target.add(shift), zoom: view.zoom })
    }
    controls.addEventListener('start', () => { tween = null; atHome = false })

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    let downAt: { x: number; y: number } | null = null
    let tipKey = ''
    const aim = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
      return rect
    }
    const pick = (): string | null => {
      for (const hit of raycaster.intersectObjects(pickables, false)) {
        const floorId = hit.object.userData.floorId as string | undefined
        if (floorId && floors[floorIndex.get(floorId)!].fade > 0.5) return floorId
      }
      return null
    }
    // The nearest room or item on a shown floor. Facades never block it (those facing the camera are cutaways).
    const thingAt = (): Selection | null => {
      const [hit] = raycaster.intersectObjects(floors.filter((floor) => floor.fade > 0.5).flatMap((floor) => floor.targets), false)
      if (!hit) return null
      const assetIds = hit.object.userData.assetIds as string[] | undefined
      const item = assetIds && hit.instanceId !== undefined ? assets.get(assetIds[hit.instanceId]) : undefined
      if (item) return assetTip(item.plan, item.asset)
      const room = spaces.get(hit.object.userData.spaceId as string)
      return room ? spaceTip(room.plan, room.space) : null
    }
    // Only re-renders when the hovered thing or its pixel position changes.
    const showTip = (item: Selection | null, x = 0, y = 0) => {
      const key = item ? `${item.kind}:${item.id}:${x}:${y}` : ''
      if (key === tipKey) return
      tipKey = key
      setTip(item && { item, x, y })
    }
    const setHovered = (floorId: string | null) => {
      if (floorId === hoveredFloor) return
      hoveredFloor = floorId
      setHoveredId(floorId)
      paint()
    }
    let hoverId: string | null = null
    const hoverItem = (id: string | null) => {
      if (id === hoverId) return
      hoverId = id
      outlineItem(hoverOutline, id)
    }
    const onPointerMove = (event: PointerEvent) => {
      // A held button orbits or pans the camera, so the tooltip waits until the pointer moves freely.
      if (event.buttons !== 0) { showTip(null); hoverItem(null); return }
      const rect = aim(event)
      const thing = thingAt()
      hoverItem(thing?.kind === 'asset' ? thing.id : null)
      setHovered(pick())
      showTip(thing, Math.round(event.clientX - rect.left) + 14, Math.round(event.clientY - rect.top) + 14)
      renderer.domElement.style.cursor = thing?.kind === 'asset' || (hoveredFloor && stackMode === 'all') ? 'pointer' : ''
    }
    const onPointerDown = (event: PointerEvent) => { downAt = { x: event.clientX, y: event.clientY } }
    const onPointerUp = (event: PointerEvent) => {
      if (!downAt || Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 5) { downAt = null; return }
      downAt = null
      aim(event)
      const thing = thingAt()
      if (thing?.kind === 'asset') {
        // The editor panel opens beside the stack, so a full-screen stack steps aside for it.
        setExpanded(false)
        if (stackMode === 'all') selectRef.current(thing.floorId)
        onSelectRef.current?.(thing)
        return
      }
      if (thing?.kind === 'space' && stackMode === 'single') { onSelectRef.current?.(thing); return }
      const floorId = pick()
      if (floorId && stackMode === 'all') selectRef.current(floorId)
    }
    const onPointerLeave = () => {
      setHovered(null)
      showTip(null)
      hoverItem(null)
      renderer.domElement.style.cursor = ''
    }
    // Zooming or orbiting moves the scene under a resting pointer, which would leave the tooltip stale.
    controls.addEventListener('start', () => showTip(null))
    const canvas = renderer.domElement
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointerleave', onPointerLeave)
    canvas.addEventListener('dblclick', resetView)

    const worldOf = ([index, local]: [number, THREE.Vector3], target: THREE.Vector3) => target.copy(local).setY(local.y + floors[index].y)
    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    const view = new THREE.Vector2()
    const routeWorld: THREE.Vector3[] = legs.flatMap((leg) => leg.points.map(() => new THREE.Vector3()))
    const born = performance.now()
    let last = born
    let frame = 0
    const animate = (now: number) => {
      frame = requestAnimationFrame(animate)
      const delta = Math.max(Math.min((now - last) / 1000, 0.1), 0)
      last = now
      const explode = !animateIn ? 1 : 1 - Math.pow(1 - Math.min(Math.max(now - born, 0) / 1100, 1), 3)
      const viewedIndex = floorIndex.get(viewedFloor) ?? 0
      view.set(camera.position.x - controls.target.x, camera.position.z - controls.target.z).normalize()
      for (const floor of floors) {
        const visible = shown(floor)
        floor.fade = reducedMotion ? (visible ? 1 : 0) : approach(floor.fade, visible ? 1 : 0, delta * 7)
        // Hidden floors slide away from the viewed one as they fade out.
        const offset = visible ? 0 : floor.index > viewedIndex ? away : -away
        const raise = stackMode === 'all' && (floor.id === hoveredFloor || floor.id === viewedFloor) ? lift : 0
        const goal = floor.compactY + (floor.explodedY - floor.compactY) * explode + offset + raise
        floor.y = reducedMotion ? goal : approach(floor.y, goal, delta * 9)
        floor.group.position.y = floor.y
        floor.group.visible = floor.fade > 0.01
        floor.label.style.opacity = String(floor.fade)
        floor.label.style.visibility = floor.fade > 0.01 ? 'visible' : 'hidden'
        const faders = [...floor.rooms.values(), floor.wall, floor.wallTop, floor.slab, floor.slabEdge, floor.halo, ...floor.route]
        for (const item of faders) item.material.opacity = item.base * floor.fade
        const focused = stackMode === 'single' || floor.id === viewedFloor || floor.id === hoveredFloor
        const modelOpacity = floor.fade * (focused ? 1 : 0.42)
        for (const item of floor.models) {
          item.material.opacity = item.opacity * modelOpacity
          item.material.depthWrite = item.depthWrite && modelOpacity > 0.99
        }
        for (const facade of floor.facades) {
          // Walls facing the camera would hide the rooms, so they thin out like a cutaway.
          const facing = facade.normal.dot(view) > 0.35 ? 0.16 : 1
          facade.facing = reducedMotion ? facing : approach(facade.facing, facing, delta * 8)
          facade.fill.material.opacity = facade.fill.base * facade.facing * floor.fade
          facade.fill.material.depthWrite = facade.facing > 0.9
          facade.edge.material.opacity = facade.edge.base * Math.max(facade.facing, 0.35) * floor.fade
        }
      }
      linkFade = reducedMotion ? (stackMode === 'all' ? 1 : 0) : approach(linkFade, stackMode === 'all' ? 1 : 0, delta * 7)
      shaftMaterials.lift.opacity = 0.9 * linkFade
      shaftMaterials.stair.opacity = 0.9 * linkFade
      linkMaterial.opacity = linkFade
      for (const { links, line } of shaftLines) {
        line.visible = linkFade > 0.01
        const attribute = line.geometry.getAttribute('position') as THREE.BufferAttribute
        links.forEach((link, index) => {
          worldOf(link.from, a)
          worldOf(link.to, b)
          attribute.setXYZ(index * 2, a.x, a.y, a.z)
          attribute.setXYZ(index * 2 + 1, b.x, b.y, b.z)
        })
        attribute.needsUpdate = true
        line.computeLineDistances()
      }
      for (const { link, mesh } of transfers) {
        mesh.visible = linkFade > 0.01
        worldOf(link.from, a)
        worldOf(link.to, b)
        const length = a.distanceTo(b)
        mesh.position.copy(a).add(b).multiplyScalar(0.5)
        mesh.scale.set(1, Math.max(length, 0.001), 1)
        if (length > 0) mesh.quaternion.setFromUnitVectors(up, b.clone().sub(a).normalize())
      }
      if (pulse && routeWorld.length > 1) {
        // The pulse runs the whole route, so it only shows when every floor it crosses is visible.
        pulse.visible = legs.every((leg) => floors[leg.index].fade > 0.99)
        let cursor = 0
        for (const leg of legs) for (const point of leg.points) worldOf([leg.index, point], routeWorld[cursor++])
        let total = 0
        for (let index = 1; index < routeWorld.length; index += 1) total += routeWorld[index - 1].distanceTo(routeWorld[index])
        let travelled = ((Math.max(now - born, 0) / 5200) % 1) * total
        for (let index = 1; index < routeWorld.length; index += 1) {
          const piece = routeWorld[index - 1].distanceTo(routeWorld[index])
          if (travelled <= piece || index === routeWorld.length - 1) {
            pulse.position.lerpVectors(routeWorld[index - 1], routeWorld[index], piece > 0 ? Math.min(travelled / piece, 1) : 0)
            break
          }
          travelled -= piece
        }
      }
      if (tween) {
        const to = tween.to ?? home
        const t = Math.min((now - tween.start) / 650, 1)
        const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
        camera.position.lerpVectors(tween.from.position, to.position, eased)
        controls.target.lerpVectors(tween.from.target, to.target, eased)
        camera.zoom = tween.from.zoom + (to.zoom - tween.from.zoom) * eased
        camera.updateProjectionMatrix()
        if (t >= 1) tween = null
      }
      controls.update()
      renderer.render(scene, camera)
      labels.render(scene, camera)
    }
    frame = requestAnimationFrame(animate)

    const updateModels = (nextPlans: FloorPlan[]) => {
      for (const plan of nextPlans) {
        const floor = floors.find((item) => item.id === plan.floor.id)
        if (!floor) continue
        updateObjectModels(floor.objects, [plan])
        for (const asset of plan.assets) assets.set(asset.id, { plan, asset })
        floor.contentHeight = Math.max(floor.structureHeight, ...objectPlacements(plan).map(({ elevation, height }) => elevation - plan.floor.elevation_m + height))
      }
      outlineItem(selectOutline, selectedRef.current)
      outlineItem(hoverOutline, hoverId)
      fitHome(size.width, size.height)
      if (atHome && !tween) applyView(home)
    }
    api.current = { focus, resetView, select: (id) => outlineItem(selectOutline, id), updateModels }
    updateModels(shownPlansRef.current)
    return () => {
      savedView.current = { key: sceneKey, view: current(), atHome }
      api.current = null
      cancelAnimationFrame(frame)
      observer.disconnect()
      themeObserver.disconnect()
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointerleave', onPointerLeave)
      canvas.removeEventListener('dblclick', resetView)
      controls.dispose()
      for (const remove of removeModels) remove()
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh
        mesh.geometry?.dispose()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((item) => item.dispose())
        else material?.dispose()
      })
      // Detached outlines are not in the scene graph.
      boxEdges.dispose()
      hoverOutline.material.dispose()
      selectOutline.material.dispose()
      renderer.dispose()
      element.replaceChildren()
      setHoveredId(null)
      setTip(null)
    }
  }, [ordered, route])

  useEffect(() => { api.current?.focus(viewedId, mode) }, [viewedId, mode])
  useEffect(() => { api.current?.select(selectedId) }, [selectedId])
  useEffect(() => { api.current?.updateModels(shownPlans) }, [shownPlans])

  useEffect(() => {
    if (!expanded) return
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const toggleExpanded = () => {
    setExpanded((open) => !open)
    requestAnimationFrame(() => expandButton.current?.focus())
  }

  const viewed = ordered.find((plan) => plan.floor.id === viewedId) ?? ordered[0]
  const focus = (mode === 'all' ? ordered.find((plan) => plan.floor.id === hoveredId) : null) ?? viewed
  const focusCounts = useMemo(() => {
    const counts = new Map<Tone, number>()
    for (const space of focus?.spaces ?? []) counts.set(toneOf(space), (counts.get(toneOf(space)) ?? 0) + 1)
    return counts
  }, [focus])
  const summary = [
    mode === 'single' && viewed ? `${copy.stackShowing} ${viewed.floor.name}` : `${ordered.length} ${ordered.length === 1 ? copy.stackFloor : copy.stackFloorsCount}`,
    route?.length_m != null ? `${copy.route} ${Math.round(route.length_m)} m` : null,
    routeFloors.size > 1 ? `${copy.stackRouteSpans} ${routeFloors.size} ${copy.stackFloorsCount}` : null,
  ].filter(Boolean).join(' · ')

  return (
    <>
      {expanded && <div className="floor-stack-backdrop" aria-hidden="true" onClick={() => setExpanded(false)} />}
      <section className={expanded ? 'floor-stack-3d is-expanded' : 'floor-stack-3d'} aria-label={copy.stackTitle}>
        <div ref={host} className="stack-viewport" role="img" aria-label={`${copy.stackTitle}: ${summary}`} />
        {tip && <MapTooltip item={tip.item} x={tip.x} y={tip.y} />}
        <header className="stack-head">
          <div className="stack-heading">
            <span className="eyebrow">{copy.stackTitle}</span>
            <p className="stack-summary mono">{summary}</p>
            {ordered.length > 1 && (
              <div className="stack-floors" role="group" aria-label={copy.stackFloorsGroup}>
                {[...ordered].reverse().map((plan) => (
                  <button
                    key={plan.floor.id}
                    type="button"
                    aria-pressed={mode === 'single' && plan.floor.id === viewedId}
                    aria-label={`${copy.showFloor} ${plan.floor.name}`}
                    title={plan.floor.name}
                    onClick={() => selectFloor(plan.floor.id)}
                  >
                    L{plan.floor.level}
                  </button>
                ))}
                <button type="button" className="stack-floors-all" aria-pressed={mode === 'all'} aria-label={copy.stackAllFloors} onClick={() => setMode(mode === 'all' ? 'single' : 'all')}>
                  <LayersIcon /><span>{copy.stackAllFloors}</span>
                </button>
              </div>
            )}
          </div>
          <div className="stack-actions">
            <button type="button" onClick={() => api.current?.resetView()} title={copy.stackResetHint} aria-label={copy.stackReset}>
              <ResetIcon /><span>{copy.stackReset}</span>
            </button>
            <button ref={expandButton} type="button" aria-pressed={expanded} aria-label={copy.stackExpand} onClick={toggleExpanded}>
              <ExpandIcon expanded={expanded} /><span>{expanded ? copy.stackCollapse : copy.stackExpand}</span>
            </button>
          </div>
        </header>
        <ul className="stack-legend" aria-label={copy.stackLegend}>
          <li><span className="stack-swatch tone-exterior" />{copy.stackToneExterior}</li>
          <li><span className="stack-swatch tone-office" />{copy.stackToneOffice}</li>
          <li><span className="stack-swatch tone-corridor" />{copy.stackToneCorridor}</li>
          <li><span className="stack-swatch tone-restroom" />{copy.stackToneRestroom}</li>
          <li><span className="stack-swatch tone-lift" />{copy.stackToneLift}</li>
          <li><span className="stack-swatch tone-stair" />{copy.stackToneStair}</li>
          {route && <li><span className="stack-swatch tone-route" />{copy.route}</li>}
        </ul>
        {focus && (
          <aside className="stack-info" aria-live="polite">
            <div className="stack-info-title">
              <span className="stack-label-level">L{focus.floor.level}</span>
              <strong>{focus.floor.name}</strong>
              {focus.floor.id === activeFloorId && <span className="stack-info-badge">{copy.stackActive}</span>}
            </div>
            <dl>
              <div><dt>{copy.stackElevation}</dt><dd className="mono">{focus.floor.elevation_m} m</dd></div>
              <div><dt>{copy.stackHeight}</dt><dd className="mono">{focus.floor.height_m} m</dd></div>
              <div><dt>{copy.stackSpaces}</dt><dd className="mono">{focus.spaces.length}</dd></div>
              <div><dt>{copy.stackShafts}</dt><dd className="mono">{(focusCounts.get('lift') ?? 0) + (focusCounts.get('stair') ?? 0)}</dd></div>
            </dl>
            {routeFloors.has(focus.floor.id) && <p className="stack-info-route">{copy.stackOnRoute}</p>}
          </aside>
        )}
        <p className="stack-hint">{mode === 'all' ? `${copy.stackHint} · ${copy.stackHintSelect}` : copy.stackHint}</p>
      </section>
    </>
  )
}
