import type { Asset, FloorPlan, Opening, Selection, Space } from '../domain/types'
import { connectorNoteFromPlan } from '../domain/live'

/** Hover details for a room, shared by the flat plan and the 3D stack. */
export function spaceTip(plan: FloorPlan, space: Space): Selection {
  return { kind: 'space', id: space.id, name: space.name, floorId: plan.floor.id, floorName: plan.floor.name, note: connectorNoteFromPlan(plan, space.id) }
}

/** Hover details for an item; stacked items name their layer. */
export function assetTip(plan: FloorPlan, asset: Asset): Selection {
  const layer = (plan.stacking ?? []).find((row) => row.object_id === asset.id)?.layer ?? 0
  return { kind: 'asset', id: asset.id, name: asset.name, floorId: plan.floor.id, floorName: plan.floor.name, note: `${asset.type} - ${asset.category}${layer > 0 ? ` - Layer ${layer}` : ''}` }
}

export function openingTip(plan: FloorPlan, opening: Opening): Selection {
  return { kind: 'opening', id: opening.id, name: opening.kind, floorId: plan.floor.id, floorName: plan.floor.name, note: `${opening.width_m} m - ${opening.step_free ? 'Step-free' : 'Has a step'}` }
}

/** Floating card next to the pointer. `x`/`y` are pixels inside the positioned map container. */
export function MapTooltip({ item, x, y }: { item: Selection; x: number; y: number }) {
  return (
    <div className="map-tooltip" role="status" style={{ left: x, top: y }}>
      <strong>{item.name}</strong>
      <dl>
        <dt>Type</dt><dd>{item.kind === 'space' ? 'Room / area' : item.kind === 'asset' ? 'Equipment / item' : 'Opening / connector'}</dd>
        <dt>Floor</dt><dd>{item.floorName}</dd>
        <dt>Details</dt><dd>{item.note || 'No additional details'}</dd>
      </dl>
    </div>
  )
}
