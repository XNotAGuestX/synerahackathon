import type { Asset, FloorPlan, Opening, Point, Space } from './types.ts'
import { buildWalkField, moveWalker, spawnPoint, standCause } from './walk-field.ts'

function fail(message: string): never {
  throw new Error(message)
}

function rect(id: string, x: number, y: number, w: number, h: number): Space {
  return {
    id,
    floor_id: 'f',
    type: 'room',
    room_type: 'room',
    name: id,
    ref: null,
    polygon: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
    synthetic: true,
  }
}

function door(id: string, at: Point, width: number, spaces: string[], extra: Partial<Opening> = {}): Opening {
  return {
    id,
    floor_id: 'f',
    space_ids: spaces,
    kind: 'door',
    position: at,
    width_m: width,
    step_free: true,
    synthetic: false,
    ...extra,
  }
}

function plan(spaces: Space[], openings: Opening[], assets: Asset[] = []): FloorPlan {
  const xs = spaces.flatMap((space) => space.polygon.map((point) => point[0]))
  const ys = spaces.flatMap((space) => space.polygon.map((point) => point[1]))
  return {
    floor: { id: 'f', level: 0, name: 'Floor', elevation_m: 0, height_m: 3, space_count: spaces.length },
    spaces,
    openings,
    assets,
    connectors: [],
    closed_ids: [],
    bounds: { min: [Math.min(...xs), Math.min(...ys)], max: [Math.max(...xs), Math.max(...ys)] },
  }
}

function assetAt(id: string, at: Point): Asset {
  return {
    id,
    name: id,
    category: 'equipment',
    type: 'machine',
    space_id: 'a',
    floor_id: 'f',
    position: at,
    footprint: { width_m: 1, depth_m: 1, rotation_deg: 0 },
    source: 'test',
  }
}

const shared = plan(
  [rect('a', 0, 0, 4, 4), rect('b', 4, 0, 4, 4)],
  [door('door-1', [4, 2], 1, ['a', 'b'])],
)

function assert(condition: boolean, message: string) {
  if (!condition) fail(message)
}

const openField = buildWalkField(shared, [], false)
let crossed: Point = [3.2, 2]
for (let step = 0; step < 20; step += 1) crossed = moveWalker(openField, crossed, [0.15, 0]).point
assert(crossed[0] > 4.2, 'FR-W2 door should let the figure into the next room')

const beside = moveWalker(openField, [3.2, 0.3], [2, 0])
assert(beside.point[0] < 4, 'FR-W2 wall beside the door should hold the figure')
const jammed = moveWalker(openField, [3.84, 0.3], [0.4, 0])
assert(jammed.cause === 'wall', `FR-W2 expected wall, got ${jammed.cause}`)

const closedField = buildWalkField(shared, ['door-1'], false)
const closedMove = moveWalker(closedField, [3.84, 2], [0.5, 0])
assert(closedMove.point[0] < 4, 'FR-W3 closed door should not be crossed')
assert(closedMove.cause === 'closed-door', `FR-W3 expected closed-door, got ${closedMove.cause}`)

const stepped = plan(
  [rect('a', 0, 0, 4, 4), rect('b', 4, 0, 4, 4)],
  [door('step-1', [4, 2], 1, ['a', 'b'], { step_free: false })],
)
const stepField = buildWalkField(stepped, [], true)
const stepMove = moveWalker(stepField, [3.84, 2], [0.5, 0])
assert(stepMove.cause === 'step', `FR-W3 expected step, got ${stepMove.cause}`)
const stepOff = buildWalkField(stepped, [], false)
let stepPassed: Point = [3.2, 2]
for (let step = 0; step < 20; step += 1) stepPassed = moveWalker(stepOff, stepPassed, [0.15, 0]).point
assert(stepPassed[0] > 4.2, 'FR-W3 a stepped door is passable when step-free is off')

const narrow = plan(
  [rect('a', 0, 0, 4, 4), rect('b', 4, 0, 4, 4)],
  [door('thin', [4, 2], 0.3, ['a', 'b'])],
)
const narrowMove = moveWalker(buildWalkField(narrow, [], false), [3.84, 2], [0.5, 0])
assert(narrowMove.cause === 'narrow', `FR-W3 expected narrow, got ${narrowMove.cause}`)

const fitted = plan(
  [rect('a', 0, 0, 4, 4)],
  [],
  [assetAt('mill', [2, 2])],
)
const fittedField = buildWalkField(fitted, [], false)
assert(standCause(fittedField, [2, 2]) === 'equipment', 'FR-W4 equipment footprint should reject its center')
assert(standCause(fittedField, [0.4, 0.4]) == null, 'FR-W4 open floor beside equipment should accept a stand')
const around = moveWalker(fittedField, [0.4, 2], [3, 0])
assert(around.point[0] < 1.5, 'FR-W4 figure should stop before the machine')

const split = plan(
  [rect('a', 0, 0, 4, 4), rect('b', 5.6, 0, 4, 4)],
  [door('gap', [4.8, 2], 1, ['a', 'b'])],
)
const splitField = buildWalkField(split, [], false)
let portal: Point = [3.2, 2]
for (let step = 0; step < 30; step += 1) portal = moveWalker(splitField, portal, [0.15, 0]).point
assert(portal[0] > 5.8, 'FR-W2 portal should cross a gap between rooms')
const portalWall = moveWalker(splitField, [3.84, 0.3], [0.5, 0])
assert(portalWall.point[0] < 4, 'FR-W2 portal should not open the wall beside the gap')

const tunnel = moveWalker(openField, [2, 0.3], [20, 0])
assert(tunnel.point[0] < 4 && tunnel.point[0] > 3, 'FR-W5 a long step must not tunnel through the wall')

const slide = moveWalker(openField, [2, 0.2], [1.2, -1])
assert(slide.point[0] > 2.4, 'FR-W2 diagonal contact should slide along the wall')
assert(slide.point[1] > 0.1, 'FR-W2 slide should stay inside the room')

const entrance = plan(
  [rect('a', 0, 0, 4, 4)],
  [door('entry', [2, 0], 1, ['a', 'outside'], { kind: 'entrance' })],
)
const entranceField = buildWalkField(entrance, [], false)
assert(standCause(entranceField, [2, 0.1]) == null, 'FR-W2 entrance gap should allow standing inside the doorway')
assert(standCause(entranceField, [2, -0.3]) === 'outside', 'FR-W2 entrance should not open the outdoors')

const spawned = spawnPoint(shared, openField, null)
assert(spawned != null && standCause(openField, spawned) == null, 'FR-W1 spawn should be a standable point')

const wide = plan(
  [rect('a', 0, 0, 4, 4), rect('b', 4, 0, 4, 4)],
  [door('wide', [4, 2], 4.2, ['a', 'b'])],
)
let wideCross: Point = [2, 3.6]
for (let step = 0; step < 20; step += 1) wideCross = moveWalker(buildWalkField(wide, [], false), wideCross, [0.2, 0]).point
assert(wideCross[0] > 4.2, 'FR-W2 a door wider than the shared edge should open that edge')

console.log('walk field check ok')
