import { useRef } from 'react'
import type { FormEvent, RefObject } from 'react'
import { labelFor } from '../../api/fixtures'
import { assumptionLines, formatMetres } from '../../domain/presentation'
import type { Presentation } from '../../domain/presentation'
import { copy } from '../../i18n/en'

type GuidePanelProps = {
  query: string
  presentation: Presentation
  directionIndex: number
  onQuery: (value: string) => void
  onSubmit: (event: FormEvent) => void
  onChoose: (label: string) => void
  onConfirm: () => void
  onCancel: () => void
  onReplay: () => void
  inputRef: RefObject<HTMLInputElement | null>
}

export function GuidePanel({
  query,
  presentation,
  directionIndex,
  onQuery,
  onSubmit,
  onChoose,
  onConfirm,
  onCancel,
  onReplay,
  inputRef,
}: GuidePanelProps) {
  const assumptions = presentation.understood ? assumptionLines(presentation.understood, labelFor) : null
  const route = presentation.route
  const routePreview = !route
    ? null
    : route.reachable
      ? `${formatMetres(route.length_m)} · ${route.step_free ? 'Step-free' : 'Stairs allowed'}`
      : 'Unreachable'
  const localRef = useRef<HTMLInputElement>(null)
  const fieldRef = inputRef ?? localRef

  return (
    <aside className="guide-panel" aria-label="Navigation guide">
      <div className="guide-heading">
        <span className="eyebrow">{copy.guideEyebrow}</span>
        <div className="guide-orbit" aria-hidden="true"><span /></div>
      </div>
      <h2>{copy.prompt}</h2>
      <form onSubmit={onSubmit} className="composer">
        <input
          ref={fieldRef}
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder={copy.placeholder}
          aria-label={copy.prompt}
        />
        <button type="submit" aria-label={copy.findRoute}>→</button>
      </form>
      <div className="guide-content" aria-live="polite">
        {presentation.alert && (
          <div role="alert" className={`notice ${presentation.alert.tone}`}>
            <span>{presentation.alert.tone === 'red' ? '!' : '?'}</span>
            <div>
              <strong>{presentation.alert.text}</strong>
              {presentation.guideText !== presentation.alert.text && <p>{presentation.guideText}</p>}
            </div>
          </div>
        )}
        {presentation.understood && (
          <div className="understood">
            <span className="check" aria-hidden="true">✓</span>
            <div>
              <span className="eyebrow">{copy.understood}</span>
              <strong>{presentation.understood.summary}</strong>
            </div>
          </div>
        )}
        {presentation.guideText && presentation.guideText !== presentation.alert?.text && !presentation.alert && (
          <p className="guide-text">{presentation.guideText}</p>
        )}
        {assumptions && (
          <details className="fold">
            <summary>
              <span>
                <span className="eyebrow">{copy.assumptions}</span>
                <span className="fold-preview">{assumptions.preview}</span>
              </span>
            </summary>
            <ol className="assumption-list" start={2}>
              {assumptions.details.map((line) => <li key={line}>{line}</li>)}
            </ol>
          </details>
        )}
        {routePreview && (
          <details className="fold">
            <summary>
              <span>
                <span className="eyebrow">{copy.route}</span>
                <span className="fold-preview">{routePreview}</span>
              </span>
            </summary>
            {route && route.directions.length > 0 && (
              <ol className="directions">
                {route.directions.map((direction, index) => (
                  <li key={direction.text} className={index === directionIndex ? 'current-step' : undefined}>{direction.text}</li>
                ))}
              </ol>
            )}
            {route?.reachable && (
              <button type="button" className="secondary-action" onClick={onReplay}>{copy.replay} <span>↗</span></button>
            )}
          </details>
        )}
        {presentation.asks.map((ask) => (
          <div key={ask.question} className="ask-block">
            <div className="notice amber">
              <span>?</span>
              <div>
                <strong>{ask.question}</strong>
                <p>{copy.choosePlace}</p>
              </div>
            </div>
            <div className="choice-list">
              {ask.options.map((option) => (
                <button type="button" key={option.id} onClick={() => onChoose(option.label)}>
                  {option.label}
                  <span>→</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {presentation.showDecision && (
          <div className="confirm-row">
            <button type="button" className="primary-action" onClick={onConfirm}>{copy.confirm}</button>
            <button type="button" className="secondary-action" onClick={onCancel}>{copy.cancel}</button>
          </div>
        )}
      </div>
    </aside>
  )
}
