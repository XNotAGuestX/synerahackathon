import { useState } from 'react'

export function RouteShare({ url }: { url: string }) {
  const [copied, setCopied] = useState(false)
  const [manual, setManual] = useState(false)
  const share = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setManual(false)
    } catch {
      // Clipboard access can be denied, including on HTTP phones on the demo LAN.
      setManual(true)
    }
  }
  return <div>
    <button type="button" className="secondary-action" onClick={() => { void share() }}>Share route <span aria-hidden="true">↗</span></button>
    {copied && <p className="guide-text" role="status">Route link copied.</p>}
    {manual && <label className="guide-text">Copy route link
      <input aria-label="Route link" type="text" value={url} readOnly onFocus={(event) => event.currentTarget.select()} style={{ width: '100%', minWidth: 0 }} />
    </label>}
  </div>
}
