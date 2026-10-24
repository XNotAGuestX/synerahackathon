import { formatMetres } from '../../domain/presentation'
import type { Presentation } from '../../domain/presentation'
import type { ReplyId, Selection, ViewEffect } from '../../domain/types'
import { copy } from '../../i18n/en'

type DebugPanelProps = {
  selection: Selection | null
  presentation: Presentation
  effects: ViewEffect[]
  onLoad: (id: ReplyId) => void
}

const samples: { id: ReplyId; label: string }[] = [
  { id: 'accepted', label: 'Main entrance to CNC mill' },
  { id: 'clarify', label: 'Where is the desk?' },
  { id: 'pending', label: 'Close the office lift' },
  { id: 'unreachable', label: 'Unreachable step-free route' },
]

export function DebugPanel({ selection, presentation, effects, onLoad }: DebugPanelProps) {
  const route = presentation.route
  return (
    <section className="debug-panel" aria-label={copy.debugTitle}>
      <span className="eyebrow">{copy.debugTitle}</span>
      <dl className="debug-facts">
        <div>
          <dt>{copy.selected}</dt>
          <dd>{selection ? selection.name : copy.none}</dd>
        </div>
        <div>
          <dt>Id</dt>
          <dd className="mono">{selection ? selection.id : copy.none}</dd>
        </div>
        <div>
          <dt>Floor</dt>
          <dd>{selection ? selection.floorName : copy.none}</dd>
        </div>
        <div>
          <dt>Route</dt>
          <dd>{route ? formatMetres(route.length_m) : copy.none}</dd>
        </div>
      </dl>
      {selection?.note && <p className="debug-note">{selection.note}</p>}
      {!selection && <p className="debug-note">{copy.clickHint}</p>}
      <details className="fold">
        <summary>
          <span>
            <span className="eyebrow">{copy.effects}</span>
            <span className="fold-preview">{presentation.effectTypes.join(', ') || copy.none}</span>
          </span>
        </summary>
        <pre>{JSON.stringify(effects, null, 2)}</pre>
      </details>
      <p className="debug-note">{copy.samples}</p>
      <div className="choice-list">
        {samples.map((sample) => (
          <button type="button" key={sample.id} onClick={() => onLoad(sample.id)}>{sample.label}<span>→</span></button>
        ))}
      </div>
    </section>
  )
}
