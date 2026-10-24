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
  const [width, setWidth] = useState('')
  const [elevation, setElevation] = useState('')

  const readFile = async (file: File) => {
    setName(file.name)
    setNeedsScale(false)
    if (!file.name.toLowerCase().endsWith('.json')) {
      setDraft(null)
      setIssues([copy.calibrate])
      setNeedsScale(true)
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
    const missing = REQUIRED.filter((key) => !(key in record))
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
        </div>
      )}
      {name && <p>{name}</p>}
      {issues.length > 0 && <ul>{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
      {draft && <button type="button" onClick={() => onApply(draft)}>{copy.applyPlan}</button>}
    </details>
  )
}
