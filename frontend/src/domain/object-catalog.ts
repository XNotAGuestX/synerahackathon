import catalog from '../../../final_agent/object_catalog.json'
import type { Asset } from './types'

export type ObjectVisual = {
  height_m: number
  model_path: string
  placeholder: boolean
}

type CatalogEntry = { height_m: number; model_path: string; model_kind: string }
const entries: Record<string, CatalogEntry> = catalog.objects

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

export function objectVisual(asset: Pick<Asset, 'type' | 'category' | 'height_m'>): ObjectVisual {
  const type = asset.type.trim().toLowerCase().split(/[-_\s]+/).filter(Boolean).join('_')
  const entry = Object.hasOwn(entries, type) ? entries[type] : undefined
  const tokens = type.split('_')
  const rule = catalog.estimation_rules.find((item) => item.tokens.some((token) => tokens.includes(token)))
  const categories: Record<string, number> = catalog.defaults.category_heights_m
  const categoryHeight = Object.hasOwn(categories, asset.category) ? categories[asset.category] : undefined
  return {
    height_m: positive(asset.height_m) ? asset.height_m : entry?.height_m ?? rule?.height_m ?? categoryHeight ?? catalog.defaults.height_m,
    model_path: entry?.model_path ?? catalog.defaults.model_path,
    placeholder: !entry || entry.model_kind === 'placeholder',
  }
}
