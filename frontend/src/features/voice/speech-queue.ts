export type SpeechItem = { kind: 'reply' | 'instruction' | 'wrong_way' | 'arrived' | 'stopped'; clipId: string; text: string }

// Replies play before guidance; a newer instruction replaces an unplayed older one.
export function createSpeechQueue() {
  let items: SpeechItem[] = []
  return {
    enqueue(item: SpeechItem) {
      if (item.kind === 'instruction') items = items.filter((existing) => existing.kind !== 'instruction')
      if (item.kind === 'reply') {
        const at = items.findIndex((existing) => existing.kind !== 'reply')
        if (at === -1) items.push(item)
        else items.splice(at, 0, item)
      } else items.push(item)
    },
    next(): SpeechItem | null { return items.shift() ?? null },
    // Clears everything; the caller stops the item that is playing.
    interrupt() { items = [] },
    size(): number { return items.length },
  }
}
