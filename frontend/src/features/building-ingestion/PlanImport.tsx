import { useState } from 'react'
import type { FloorPlan } from '../../domain/types'
import { copy } from '../../i18n/en'

const REQUIRED = ['schema_version', 'floor', 'spaces', 'openings', 'assets', 'connectors', 'bounds'] as const

type PlanImportProps = {
  onApply: (plan: FloorPlan) => void
}

export function PlanImport({ onApply }: PlanImportProps) {
  const [issues, setIssues] = useState<string[]>([])
  const [draft, setDraft] = useState<FloorPlan | null>(null)
  const [name, setName] = useState('')
  const [needsScale, setNeedsScale] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [pixelWidth, setPixelWidth] = useState<number | null>(null)
  const [width, setWidth] = useState('')
  const [elevation, setElevation] = useState('')

  const readFile = async (file: File) => {
    setName(file.name)
    setNeedsScale(false)
    if (!file.name.toLowerCase().endsWith('.json')) {
      setDraft(null)
      setIssues([copy.calibrate])
      setNeedsScale(true)
      if (file.type.startsWith('image/')) {
        const url = URL.createObjectURL(file)
        setPreviewUrl(url)
        const image = new Image()
        image.onload = () => setPixelWidth(image.naturalWidth)
        image.src = url
      }
      return
    }
    const text = await file.text()
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      setDraft(null)
      setIssues(['File is not JSON.'])
      return
    }
    if (!parsed || typeof parsed !== 'object') {
      setDraft(null)
      setIssues(['Root value must be an object.'])
      return
    }
    const record = parsed as Record<string, unknown>
    const missing: string[] = REQUIRED.filter((key) => !(key in record))
    const ids = new Set<string>()
    for (const space of Array.isArray(record.spaces) ? record.spaces as Array<Record<string, unknown>> : []) {
      const id = String(space.id ?? '')
      if (!id || ids.has(id)) missing.push(`duplicate:${id || 'missing'}`)
      ids.add(id)
      const polygon = space.polygon
      if (!Array.isArray(polygon) || polygon.length < 3) missing.push(`polygon:${id}`)
    }
    const spaces = Array.isArray(record.spaces) ? record.spaces.length : 0
    setIssues(missing.map((key) => `Missing ${key}.`))
    setDraft(missing.length === 0 && spaces > 0 ? parsed as FloorPlan : null)
  }

  return (
    <details className="plan-import">
      <summary>{copy.importPlan}</summary>
      <input type="file" accept="application/json,image/*,.pdf" aria-label={copy.importPlan} onChange={(event) => { const file = event.target.files?.[0]; if (file) void readFile(file) }} />
      {needsScale && (
        <div className="calibrate">
          <label>{copy.knownWidth}<input value={width} onChange={(event) => setWidth(event.target.value)} inputMode="decimal" /></label>
          <label>{copy.floorElevation}<input value={elevation} onChange={(event) => setElevation(event.target.value)} inputMode="decimal" /></label>
          {previewUrl && <img src={previewUrl} alt="Plan to calibrate" className="plan-preview" />}
          {previewUrl && pixelWidth && Number(width) > 0 && <p>Check: 1 m = {(pixelWidth / Number(width)).toFixed(1)} px across this image.</p>}
        </div>
      )}
      {name && <p>{name}</p>}
      {issues.length > 0 && <ul>{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
      {draft && <button type="button" onClick={() => onApply(draft)}>{copy.applyPlan}</button>}
    </details>
  )
}
