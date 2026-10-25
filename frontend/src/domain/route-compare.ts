/** Forklift eligibility shown on the plan. Lengths still come from the route API. */
export const FORKLIFT_MIN_WIDTH_M = 3
const DESTINATION_ONLY = new Set(['production_zone', 'additive_zone', 'assembly_zone'])

export function openingAccessNote(opening: { width_m: number; step_free: boolean }, forklift: boolean): string {
  const access = opening.step_free ? 'Step-free' : 'Has a step'
  if (!forklift) return access
  if (opening.width_m < FORKLIFT_MIN_WIDTH_M) {
    return `${access}. Open for people. Too narrow for a forklift (${opening.width_m} m).`
  }
  return `${access}. Wide enough for a forklift.`
}

export function spaceAccessNote(roomType: string, base: string | null, forklift: boolean): string | null {
  if (!forklift || !DESTINATION_ONLY.has(roomType.toLowerCase())) return base
  const bay = 'A forklift can start or stop here. It cannot cross this bay.'
  return base ? `${base}. ${bay}` : bay
}
