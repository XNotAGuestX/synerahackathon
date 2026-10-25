import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import type { FloorPlan, Point, Route, Space } from '../../domain/types'
import { copy } from '../../i18n/en'

type FloorStack3DProps = {
  plans: FloorPlan[]
  route: Route | null
  activeFloorId: string
  onSelectFloor?: (floorId: string) => void
}

type Tone = 'room' | 'office' | 'corridor' | 'restroom' | 'lift' | 'stair'
const tones: Tone[] = ['room', 'office', 'corridor', 'restroom', 'lift', 'stair']

type Palette = Record<Tone, THREE.Color> & {
  slab: THREE.Color
  slabEdge: THREE.Color
  wall: THREE.Color
  wallTop: THREE.Color
  primary: THREE.Color
  start: THREE.Color
  destination: THREE.Color
  danger: THREE.Color
  background: THREE.Color
}

type FloorRecord = {
  id: string
  group: THREE.Group
  compactY: number
  explodedY: number
  y: number
  rooms: Map<Tone, THREE.MeshBasicMaterial>
  wall: THREE.MeshLambertMaterial
  wallTop: THREE.LineBasicMaterial
  slab: THREE.MeshLambertMaterial
  slabEdge: THREE.LineBasicMaterial
  halo: THREE.MeshBasicMaterial
  label: HTMLDivElement
}

type View = { position: THREE.Vector3; target: THREE.Vector3; zoom: number }

type SceneApi = {
  paint: (activeId: string) => void
  setHovered: (floorId: string | null) => void
  resetView: () => void
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

/** Keeps the previous array when its items are the same objects, so a parent's fresh `[...map.values()]` does not rebuild the scene. */
function useStableItems<T>(items: T[]): T[] {
  const previous = useRef(items)
  if (previous.current.length !== items.length || previous.current.some((item, index) => item !== items[index])) previous.current = items
  return previous.current
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

export function FloorStack3D({ plans: incomingPlans, route: incomingRoute, activeFloorId, onSelectFloor }: FloorStack3DProps) {
  const plans = useStableItems(incomingPlans)
  const route = useStableRoute(incomingRoute)
  const host = useRef<HTMLDivElement>(null)
  const api = useRef<SceneApi | null>(null)
  const savedView = useRef<{ key: string; view: View; atHome: boolean } | null>(null)
  const activeRef = useRef(activeFloorId)
  const selectRef = useRef(onSelectFloor)
  const expandButton = useRef<HTMLButtonElement>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  activeRef.current = activeFloorId
  selectRef.current = onSelectFloor

  const ordered = useMemo(() => [...plans].sort((left, right) => left.floor.elevation_m - right.floor.elevation_m), [plans])
  const routeFloors = useMemo(() => new Set((route?.legs ?? []).filter((leg) => leg.points.length > 0).map((leg) => leg.floor_id)), [route])

  useEffect(() => {
    const element = host.current
    if (!element || ordered.length === 0) return
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
    const halfX = (maxX - minX) / 2 + pad
    const halfZ = (maxY - minY) / 2 + pad
    const slabDepth = Math.max(span * 0.014, 0.3)
    const maxStorey = Math.max(...ordered.map((plan) => plan.floor.height_m || 3), 3)
    const wallHeight = Math.min(Math.max(span * 0.016, 0.9), maxStorey * 0.5)
    const gap = Math.max(span * (ordered.length <= 3 ? 0.55 : 0.42), maxStorey * 2, 5)
    const lift = gap * 0.12
    const baseElevation = ordered[0].floor.elevation_m
    const topY = gap * (ordered.length - 1)
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
    const pickables: THREE.Object3D[] = []
    const floorIndex = new Map<string, number>()

    ordered.forEach((plan, index) => {
      floorIndex.set(plan.floor.id, index)
      const group = new THREE.Group()
      const compactY = plan.floor.elevation_m - baseElevation
      const explodedY = gap * index
      const y = animateIn ? compactY : explodedY
      group.position.y = y
      scene.add(group)

      // Each slab hugs its own floor, so a smaller upper storey does not hide the one below.
      const own = plan.spaces.flatMap((space) => space.polygon).map(toWorld)
      const x0 = own.length ? Math.min(...own.map(([x]) => x)) - pad : -halfX
      const x1 = own.length ? Math.max(...own.map(([x]) => x)) + pad : halfX
      const z0 = own.length ? Math.min(...own.map(([, z]) => z)) - pad : -halfZ
      const z1 = own.length ? Math.max(...own.map(([, z]) => z)) + pad : halfZ
      const slabShape = new THREE.Shape()
      slabShape.moveTo(x0, -z1)
      slabShape.lineTo(x1, -z1)
      slabShape.lineTo(x1, -z0)
      slabShape.lineTo(x0, -z0)
      slabShape.closePath()
      const slabGeometry = new THREE.ExtrudeGeometry(slabShape, { depth: slabDepth, bevelEnabled: false })
      slabGeometry.rotateX(-Math.PI / 2)
      slabGeometry.translate(0, -slabDepth - 0.01, 0)
      const slab = new THREE.MeshLambertMaterial({ transparent: true })
      const slabMesh = new THREE.Mesh(slabGeometry, slab)
      slabMesh.userData.floorId = plan.floor.id
      pickables.push(slabMesh)
      const slabEdge = new THREE.LineBasicMaterial({ transparent: true })
      group.add(slabMesh, new THREE.LineSegments(new THREE.EdgesGeometry(slabGeometry), slabEdge))

      const halo = new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false })
      const haloMesh = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0 + pad * 2, z1 - z0 + pad * 2), halo)
      haloMesh.rotation.x = -Math.PI / 2
      haloMesh.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2)
      haloMesh.position.y = -slabDepth - 0.06
      group.add(haloMesh)

      const rooms = new Map<Tone, THREE.MeshBasicMaterial>()
      const walls: Point[][] = []
      for (const space of plan.spaces) {
        if (space.polygon.length < 3) continue
        const tone = toneOf(space)
        let material = rooms.get(tone)
        if (!material) {
          material = new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 })
          rooms.set(tone, material)
        }
        const shape = new THREE.Shape(space.polygon.map((point) => {
          const [x, z] = toWorld(point)
          return new THREE.Vector2(x, -z)
        }))
        const geometry = new THREE.ShapeGeometry(shape)
        geometry.rotateX(-Math.PI / 2)
        const mesh = new THREE.Mesh(geometry, material)
        mesh.position.y = 0.02
        mesh.userData.floorId = plan.floor.id
        pickables.push(mesh)
        group.add(mesh)
        walls.push(space.polygon)
      }
      const wall = new THREE.MeshLambertMaterial({ transparent: true, side: THREE.DoubleSide, depthWrite: false })
      const wallTop = new THREE.LineBasicMaterial({ transparent: true })
      group.add(new THREE.Mesh(wallGeometry(walls, wallHeight, toWorld), wall))
      group.add(new THREE.LineSegments(outlineGeometry(walls, wallHeight, toWorld), wallTop))
      group.add(new THREE.LineSegments(outlineGeometry(walls, 0.03, toWorld), wallTop))

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

      floors.push({ id: plan.floor.id, group, compactY, explodedY, y, rooms, wall, wallTop, slab, slabEdge, halo, label })
    })

    // Vertical links: lift and stair shafts, and the route's floor changes. Both follow the floors as they move.
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
      lift: new THREE.LineDashedMaterial({ dashSize: span * 0.012, gapSize: span * 0.008, transparent: true, opacity: 0.9 }),
      stair: new THREE.LineDashedMaterial({ dashSize: span * 0.012, gapSize: span * 0.008, transparent: true, opacity: 0.9 }),
    }
    const shaftLines = (['lift', 'stair'] as const).map((kind) => {
      const geometry = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(shaftLinks[kind].length * 6), 3))
      const line = new THREE.LineSegments(geometry, shaftMaterials[kind])
      line.frustumCulled = false
      scene.add(line)
      return { links: shaftLinks[kind], line }
    })

    // The route layer ignores depth so cutaway walls never chop it into dashes.
    const overlay = { depthTest: false, depthWrite: false, transparent: true }
    const routeMaterial = new THREE.MeshBasicMaterial(overlay)
    const startMaterial = new THREE.MeshBasicMaterial(overlay)
    const destinationMaterial = new THREE.MeshBasicMaterial(overlay)
    const legs = (route?.legs ?? [])
      .filter((leg) => leg.points.length > 0 && floorIndex.has(leg.floor_id))
      .map((leg) => ({ index: floorIndex.get(leg.floor_id)!, points: leg.points.map((point) => { const [x, z] = toWorld(point); return new THREE.Vector3(x, 0.35, z) }) }))
    for (const leg of legs) {
      if (leg.points.length < 2) continue
      const path = new THREE.CurvePath<THREE.Vector3>()
      for (let index = 1; index < leg.points.length; index += 1) path.add(new THREE.LineCurve3(leg.points[index - 1], leg.points[index]))
      floors[leg.index].group.add(new THREE.Mesh(new THREE.TubeGeometry(path, Math.max(leg.points.length * 6, 12), tubeRadius, 8, false), routeMaterial))
    }
    const transfers: { link: Link; mesh: THREE.Mesh }[] = []
    const transferGeometry = new THREE.CylinderGeometry(tubeRadius, tubeRadius, 1, 8, 1, true)
    for (let index = 1; index < legs.length; index += 1) {
      const previous = legs[index - 1]
      const next = legs[index]
      if (previous.index === next.index) continue
      const mesh = new THREE.Mesh(transferGeometry, routeMaterial)
      scene.add(mesh)
      transfers.push({ link: { from: [previous.index, previous.points[previous.points.length - 1]], to: [next.index, next.points[0]] }, mesh })
    }
    let pulse: THREE.Mesh | null = null
    if (legs.length > 0) {
      const first = legs[0]
      const last = legs[legs.length - 1]
      const startMarker = new THREE.Mesh(new THREE.SphereGeometry(tubeRadius * 3, 20, 12), startMaterial)
      startMarker.position.copy(first.points[0]).setY(tubeRadius * 3)
      floors[first.index].group.add(startMarker)
      const pin = new THREE.Mesh(new THREE.ConeGeometry(tubeRadius * 3, tubeRadius * 9, 20), destinationMaterial)
      pin.rotation.x = Math.PI
      pin.position.copy(last.points[last.points.length - 1]).setY(tubeRadius * 6)
      floors[last.index].group.add(pin)
      const ring = new THREE.Mesh(new THREE.RingGeometry(tubeRadius * 3.5, tubeRadius * 5, 32), destinationMaterial)
      ring.rotation.x = -Math.PI / 2
      ring.position.copy(last.points[last.points.length - 1]).setY(0.08)
      floors[last.index].group.add(ring)
      if (!reducedMotion) {
        pulse = new THREE.Mesh(new THREE.SphereGeometry(tubeRadius * 2.2, 16, 10), startMaterial)
        scene.add(pulse)
      }
    }

    let activeId = activeRef.current
    let hoveredFloor: string | null = null
    const paint = (nextActive: string) => {
      activeId = nextActive
      const palette = readPalette(element)
      hemisphere.groundColor.copy(palette.background)
      for (const floor of floors) {
        const active = floor.id === activeId
        const focused = active || floor.id === hoveredFloor
        for (const tone of tones) {
          const material = floor.rooms.get(tone)
          if (!material) continue
          material.color.copy(palette[tone])
          material.opacity = focused ? 1 : 0.42
        }
        floor.wall.color.copy(palette.wall)
        floor.wall.opacity = focused ? 0.82 : 0.22
        floor.wallTop.color.copy(palette.wallTop)
        floor.wallTop.opacity = focused ? 1 : 0.4
        floor.slab.color.copy(palette.slab)
        floor.slab.emissive.copy(active ? palette.primary : palette.background).multiplyScalar(active ? 0.12 : 0)
        floor.slab.opacity = focused ? 1 : 0.38
        floor.slabEdge.color.copy(active ? palette.primary : palette.slabEdge)
        floor.slabEdge.opacity = focused ? 1 : 0.55
        floor.halo.color.copy(palette.primary)
        floor.halo.opacity = active ? 0.16 : 0
        floor.label.classList.toggle('active', active)
        floor.label.classList.toggle('hovered', floor.id === hoveredFloor)
      }
      shaftMaterials.lift.color.copy(palette.start)
      shaftMaterials.stair.color.copy(palette.danger)
      routeMaterial.color.copy(palette.primary)
      startMaterial.color.copy(palette.start)
      destinationMaterial.color.copy(palette.destination)
    }
    paint(activeId)

    const home: View = { position: new THREE.Vector3(), target: new THREE.Vector3(), zoom: 1 }
    const fitHome = (width: number, height: number) => {
      const target = new THREE.Vector3(0, topY / 2, 0)
      const probe = new THREE.OrthographicCamera(-width / height, width / height, 1, -1, -span * 40, span * 40)
      probe.position.copy(target).addScaledVector(isoDirection, span * 4)
      probe.lookAt(target)
      probe.updateMatrixWorld()
      let extentX = 0
      let extentY = 0
      for (const x of [-halfX, halfX]) for (const y of [-slabDepth, topY + lift + wallHeight]) for (const z of [-halfZ, halfZ]) {
        const local = new THREE.Vector3(x, y, z).applyMatrix4(probe.matrixWorldInverse)
        extentX = Math.max(extentX, Math.abs(local.x))
        extentY = Math.max(extentY, Math.abs(local.y))
      }
      // Leave room on the left for floor labels and at the edges for the overlay chrome.
      const labelRoom = Math.min(180, width * 0.3)
      const zoom = Math.max(Math.min((width - labelRoom - 48) / (extentX * height), (height - 140) / (extentY * height)), 0.01)
      const worldPerPixel = 2 / (zoom * height)
      const right = new THREE.Vector3().crossVectors(isoDirection.clone().negate(), up).normalize()
      target.addScaledVector(right, -labelRoom * 0.5 * worldPerPixel)
      home.target.copy(target)
      home.position.copy(target).addScaledVector(isoDirection, span * 4)
      home.zoom = zoom
      controls.minZoom = zoom * 0.35
      controls.maxZoom = zoom * 8
    }

    let size = { width: 0, height: 0 }
    // While the camera sits at its home view, a resize (Expand, rotation) refits instead of cropping.
    let atHome = savedView.current?.key !== sceneKey || savedView.current.atHome
    const applyHome = () => {
      camera.position.copy(home.position)
      controls.target.copy(home.target)
      camera.zoom = home.zoom
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
      if (atHome) applyHome()
      else if (first && savedView.current) {
        camera.position.copy(savedView.current.view.position)
        controls.target.copy(savedView.current.view.target)
        camera.zoom = savedView.current.view.zoom
      }
      camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)

    const themeObserver = new MutationObserver(() => paint(activeId))
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-system-theme', 'class'] })

    let tween: { from: View; start: number } | null = null
    const resetView = () => {
      atHome = true
      if (reducedMotion) {
        applyHome()
        return
      }
      tween = { from: { position: camera.position.clone(), target: controls.target.clone(), zoom: camera.zoom }, start: performance.now() }
    }
    controls.addEventListener('start', () => { tween = null; atHome = false })

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    let downAt: { x: number; y: number } | null = null
    const pick = (event: PointerEvent): string | null => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(pointer, camera)
      const hit = raycaster.intersectObjects(pickables, false)[0]
      return (hit?.object.userData.floorId as string | undefined) ?? null
    }
    const setHovered = (floorId: string | null) => {
      if (floorId === hoveredFloor) return
      hoveredFloor = floorId
      renderer.domElement.style.cursor = floorId && selectRef.current ? 'pointer' : ''
      setHoveredId(floorId)
      paint(activeId)
    }
    const onPointerMove = (event: PointerEvent) => { if (event.buttons === 0) setHovered(pick(event)) }
    const onPointerDown = (event: PointerEvent) => { downAt = { x: event.clientX, y: event.clientY } }
    const onPointerUp = (event: PointerEvent) => {
      if (!downAt || Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 5) { downAt = null; return }
      downAt = null
      const floorId = pick(event)
      if (floorId) selectRef.current?.(floorId)
    }
    const onPointerLeave = () => setHovered(null)
    const canvas = renderer.domElement
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointerleave', onPointerLeave)
    canvas.addEventListener('dblclick', resetView)

    const worldOf = ([index, local]: [number, THREE.Vector3], target: THREE.Vector3) => target.copy(local).setY(local.y + floors[index].y)
    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    const routeWorld: THREE.Vector3[] = legs.flatMap((leg) => leg.points.map(() => new THREE.Vector3()))
    const born = performance.now()
    let last = born
    let frame = 0
    const animate = (now: number) => {
      frame = requestAnimationFrame(animate)
      const delta = Math.min((now - last) / 1000, 0.1)
      last = now
      const explode = !animateIn ? 1 : 1 - Math.pow(1 - Math.min((now - born) / 1100, 1), 3)
      for (const floor of floors) {
        const goal = floor.compactY + (floor.explodedY - floor.compactY) * explode + (floor.id === hoveredFloor || floor.id === activeId ? lift : 0)
        floor.y = reducedMotion ? goal : floor.y + (goal - floor.y) * Math.min(1, delta * 9)
        floor.group.position.y = floor.y
      }
      for (const { links, line } of shaftLines) {
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
        worldOf(link.from, a)
        worldOf(link.to, b)
        const length = a.distanceTo(b)
        mesh.position.copy(a).add(b).multiplyScalar(0.5)
        mesh.scale.set(1, Math.max(length, 0.001), 1)
        if (length > 0) mesh.quaternion.setFromUnitVectors(up, b.clone().sub(a).normalize())
      }
      if (pulse && routeWorld.length > 1) {
        let cursor = 0
        for (const leg of legs) for (const point of leg.points) worldOf([leg.index, point], routeWorld[cursor++])
        let total = 0
        for (let index = 1; index < routeWorld.length; index += 1) total += routeWorld[index - 1].distanceTo(routeWorld[index])
        let travelled = ((now - born) / 5200 % 1) * total
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
        const t = Math.min((now - tween.start) / 650, 1)
        const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
        camera.position.lerpVectors(tween.from.position, home.position, eased)
        controls.target.lerpVectors(tween.from.target, home.target, eased)
        camera.zoom = tween.from.zoom + (home.zoom - tween.from.zoom) * eased
        camera.updateProjectionMatrix()
        if (t >= 1) tween = null
      }
      controls.update()
      renderer.render(scene, camera)
      labels.render(scene, camera)
    }
    frame = requestAnimationFrame(animate)

    scene.traverse((object) => {
      const material = (object as THREE.Mesh).material
      if (material === routeMaterial || material === startMaterial || material === destinationMaterial) object.renderOrder = 10
    })
    api.current = { paint, setHovered, resetView }
    return () => {
      savedView.current = { key: sceneKey, view: { position: camera.position.clone(), target: controls.target.clone(), zoom: camera.zoom }, atHome }
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
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh
        mesh.geometry?.dispose()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((item) => item.dispose())
        else material?.dispose()
      })
      renderer.dispose()
      element.replaceChildren()
      setHoveredId(null)
    }
  }, [ordered, route])

  useEffect(() => { api.current?.paint(activeFloorId) }, [activeFloorId])

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

  const focus = ordered.find((plan) => plan.floor.id === hoveredId) ?? ordered.find((plan) => plan.floor.id === activeFloorId) ?? ordered[0]
  const focusCounts = useMemo(() => {
    const counts = new Map<Tone, number>()
    for (const space of focus?.spaces ?? []) counts.set(toneOf(space), (counts.get(toneOf(space)) ?? 0) + 1)
    return counts
  }, [focus])
  const active = ordered.find((plan) => plan.floor.id === activeFloorId)
  const summary = [
    `${ordered.length} ${ordered.length === 1 ? copy.stackFloor : copy.stackFloorsCount}`,
    route?.length_m != null ? `${copy.route} ${Math.round(route.length_m)} m` : null,
    routeFloors.size > 1 ? `${copy.stackRouteSpans} ${routeFloors.size} ${copy.stackFloorsCount}` : null,
  ].filter(Boolean).join(' · ')

  return (
    <>
      {expanded && <div className="floor-stack-backdrop" aria-hidden="true" onClick={() => setExpanded(false)} />}
      <section className={expanded ? 'floor-stack-3d is-expanded' : 'floor-stack-3d'} aria-label={copy.stackTitle}>
        <div
          ref={host}
          className="stack-viewport"
          role="img"
          aria-label={`${copy.stackTitle}: ${summary}${active ? `. ${copy.stackActive} ${active.floor.name}` : ''}`}
        />
        <header className="stack-head">
          <div>
            <span className="eyebrow">{copy.stackTitle}</span>
            <p className="stack-summary mono">{summary}</p>
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
        <p className="stack-hint">{onSelectFloor ? `${copy.stackHint} · ${copy.stackHintSelect}` : copy.stackHint}</p>
      </section>
    </>
  )
}
