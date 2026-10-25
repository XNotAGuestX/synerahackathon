import type { ReactNode } from 'react'

/**
 * Minimal, safe rendering for guide replies: **bold** and `code` only.
 * Everything else stays plain text; no HTML is ever interpreted.
 */
export function RichText({ text }: { text: string }) {
  const parts: ReactNode[] = []
  const pattern = /\*\*([^*\n]+)\*\*|`([^`\n]+)`/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > last) parts.push(text.slice(last, index))
    parts.push(match[1] !== undefined ? <strong key={index}>{match[1]}</strong> : <code key={index}>{match[2]}</code>)
    last = index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

/** True when the reply text already lists numbered steps, so a second list would repeat them. */
export function hasNumberedSteps(text: string): boolean {
  return (text.match(/^\s*\d+\.\s+\S/gm) ?? []).length >= 2
}
