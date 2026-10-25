import type { Point } from '../../domain/types.ts'
import { perimeterSegments } from './perimeter.ts'

function fail(message: string): never {
  throw new Error(message)
}

function rect(x: number, y: number, w: number, h: number, clockwise = false): Point[] {
  const ring: Point[] = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
  return clockwise ? ring.reverse() : ring
}

const total = (segments: ReturnType<typeof perimeterSegments>) =>
  segments.reduce((sum, { a, b }) => sum + Math.hypot(b[0] - a[0], b[1] - a[1]), 0)

// Two rooms sharing a wall: the shared edge is interior, the outline is the 20 x 10 box.
const pair = perimeterSegments([rect(0, 0, 10, 10), rect(10, 0, 10, 10, true)])
if (Math.abs(total(pair) - 60) > 1e-6) fail(`shared wall should be interior, outline was ${total(pair)}`)

// A corridor along three small rooms: partial overlaps along one long edge still cancel.
const strip = perimeterSegments([rect(0, 0, 30, 4), rect(0, 4, 10, 6), rect(10, 4, 10, 6), rect(20, 4, 10, 6)])
if (Math.abs(total(strip) - 80) > 1e-6) fail(`corridor strip outline should be 80, was ${total(strip)}`)

// A thin interior wall gap (0.2 m) between rooms is not mistaken for the outline.
const gapped = perimeterSegments([rect(0, 0, 10, 10), rect(10.2, 0, 10, 10)])
if (Math.abs(total(gapped) - 60) > 1e-6) fail(`gap walls should be interior, outline was ${total(gapped)}`)

// Outward normals point away from the room regardless of winding.
for (const segment of perimeterSegments([rect(0, 0, 4, 4, true)])) {
  const mid: Point = [(segment.a[0] + segment.b[0]) / 2 + segment.normal[0], (segment.a[1] + segment.b[1]) / 2 + segment.normal[1]]
  if (mid[0] > 0 && mid[0] < 4 && mid[1] > 0 && mid[1] < 4) fail('normal points inward')
}

console.log('perimeter checks passed')
