import { useState } from 'react'
import { gateway, type CampusDemo } from '../../api/gateway'

export function CampusWalkway() {
  const [demo, setDemo] = useState<CampusDemo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setDemo(await gateway.runCampusDemo())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Campus walkway failed.')
    } finally {
      setBusy(false)
    }
  }

  return <div className="campus-walkway">
    <button type="button" className="location-chip" onClick={run} disabled={busy}>
      {busy ? 'Routing…' : 'Campus walkway'}
    </button>
    {error && <p className="app-status" role="alert">{error}</p>}
    {demo && <section className="campus-report" aria-label="Campus walkway">
      <p>{demo.lengths_m.map((length) => `${length} m`).join(' → ')}</p>
      {demo.stages.map((stage) => <article key={stage.id}>
        <h2>{stage.title}</h2>
        <p>{stage.length_m} m</p>
        {stage.images.map((image) => <img key={image.name} src={gateway.campusImageUrl(image.name)} alt={`${stage.title}, ${image.label}`} />)}
      </article>)}
    </section>}
  </div>
}
