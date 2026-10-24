import type { FloorPlan } from '../../domain/types'

type FloorStackProps = {
  plans: FloorPlan[]
}

function points(plan: FloorPlan): string {
  const [minX, minY] = plan.bounds.min
  const [maxX, maxY] = plan.bounds.max
  const width = Math.max(maxX - minX, 1)
  const height = Math.max(maxY - minY, 1)
  return plan.spaces.slice(0, 24).map((space) => {
    const polygon = space.polygon.map(([x, y]) => `${((x - minX) / width) * 100},${100 - ((y - minY) / height) * 100}`).join(' ')
    return polygon
  }).join('|')
}

export function FloorStack({ plans }: FloorStackProps) {
  const ordered = [...plans].sort((left, right) => left.floor.elevation_m - right.floor.elevation_m)
  return (
    <div className="floor-stack" aria-label="Floor stack">
      {ordered.map((plan) => (
        <figure key={plan.floor.id} style={{ transform: `translateY(${-plan.floor.elevation_m * 8}px)` }}>
          <svg viewBox="0 0 100 100" aria-hidden="true">
            {points(plan).split('|').filter(Boolean).map((polygon) => <polygon key={polygon} points={polygon} />)}
          </svg>
          <figcaption>{plan.floor.name} · {plan.floor.elevation_m} m</figcaption>
        </figure>
      ))}
    </div>
  )
}
