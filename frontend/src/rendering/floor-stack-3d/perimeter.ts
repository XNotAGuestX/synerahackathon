import type { Point } from '../../domain/types'

/** A stretch of building outline with its outward unit normal, in plan coordinates. */
export type PerimeterSegment = { a: Point; b: Point; normal: Point }

type Box = [number, number, number, number]

function bounds(polygon: Point[]): Box {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const [x, y] of polygon) {
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
  }
  return [minX, minY, maxX, maxY]
}

function signedArea(polygon: Point[]): number {
  let area = 0
  for (let index = 0; index < polygon.length; index += 1) {
    const [ax, ay] = polygon[index]
    const [bx, by] = polygon[(index + 1) % polygon.length]
    area += ax * by - bx * ay
  }
  return area / 2
}

export function pointInPolygon([px, py]: Point, polygon: Point[]): boolean {
  let inside = false
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index, index += 1) {
    const [ax, ay] = polygon[index]
    const [bx, by] = polygon[previous]
    if ((ay > py) !== (by > py) && px < ((bx - ax) * (py - ay)) / (by - ay) + ax) inside = !inside
  }
  return inside
}

/**
 * Separates interior walls and the building outline without a polygon union.
 * Each room edge is cut into short pieces; a piece is exterior when the point `probe`
 * metres outside it lies in no room. `probe` should exceed the thickest interior wall gap.
 */
export function wallSegments(polygons: Point[][], step = 0.5, probe = 0.6): { interior: PerimeterSegment[]; exterior: PerimeterSegment[] } {
  const rooms = polygons.filter((polygon) => polygon.length >= 3)
  const boxes = rooms.map(bounds)
  const covered = (point: Point) => rooms.some((polygon, index) => {
    const [minX, minY, maxX, maxY] = boxes[index]
    return point[0] >= minX && point[0] <= maxX && point[1] >= minY && point[1] <= maxY && pointInPolygon(point, polygon)
  })
  const interior: PerimeterSegment[] = []
  const exterior: PerimeterSegment[] = []
  const seenInterior = new Set<string>()
  for (const polygon of rooms) {
    const clockwise = signedArea(polygon) < 0
    for (let index = 0; index < polygon.length; index += 1) {
      const [ax, ay] = polygon[index]
      const [bx, by] = polygon[(index + 1) % polygon.length]
      const length = Math.hypot(bx - ax, by - ay)
      if (length < 1e-6) continue
      const dx = (bx - ax) / length
      const dy = (by - ay) / length
      const normal: Point = clockwise ? [-dy, dx] : [dy, -dx]
      const pieces = Math.max(1, Math.ceil(length / step))
      let runStart = 0
      let runExterior: boolean | null = null
      for (let piece = 0; piece <= pieces; piece += 1) {
        let isExterior: boolean | null = null
        if (piece < pieces) {
          const t = ((piece + 0.5) / pieces) * length
          isExterior = !covered([ax + dx * t + normal[0] * probe, ay + dy * t + normal[1] * probe])
        }
        if (isExterior !== runExterior && runExterior !== null) {
          const from = (runStart / pieces) * length
          const end = (piece / pieces) * length
          const segment: PerimeterSegment = { a: [ax + dx * from, ay + dy * from], b: [ax + dx * end, ay + dy * end], normal }
          if (runExterior) exterior.push(segment)
          else {
            // Adjacent rooms often describe the same interior edge in opposite directions.
            const key = [segment.a.join(','), segment.b.join(',')].sort().join('|')
            if (!seenInterior.has(key)) interior.push(segment)
            seenInterior.add(key)
          }
        }
        if (isExterior !== runExterior) {
          runStart = piece
          runExterior = isExterior
        }
      }
    }
  }
  return { interior, exterior }
}

export function perimeterSegments(polygons: Point[][], step = 0.5, probe = 0.6): PerimeterSegment[] {
  return wallSegments(polygons, step, probe).exterior
}
