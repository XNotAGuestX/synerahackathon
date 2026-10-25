import type { TranscriptionToken } from '../../api/gateway'

const FINISH_TIMEOUT_MS = 4000
// The provider's "no speech in this audio" error; the utterance was noise, so the transcript is empty.
const NO_SPEECH = 'insufficient_audio_activity'

export type TranscriptStream = {
  push(frame: Float32Array): void
  // Commits the utterance and resolves with its text. Rejects on any socket failure; the caller then uploads the WAV.
  finish(): Promise<string>
  close(): void
}

export function pcm16Base64(frame: Float32Array): string {
  const bytes = new Uint8Array(frame.length * 2)
  const view = new DataView(bytes.buffer)
  frame.forEach((sample, index) => view.setInt16(index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true))
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

// Streams one utterance to the realtime speech-to-text socket while the user is still talking.
// Frames pushed before the socket opens are queued, so no audio is lost while it connects.
export function openTranscriptStream(token: Promise<TranscriptionToken>): TranscriptStream {
  const queue: string[] = []
  let socket: WebSocket | null = null
  let closed = false
  let failure: Error | null = null
  let settle: { resolve: (text: string) => void; reject: (error: Error) => void } | null = null
  let sampleRate = 16000

  const fail = (error: Error) => {
    failure ??= error
    settle?.reject(failure)
    settle = null
  }
  const send = (message: string) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(message)
    else queue.push(message)
  }
  const chunk = (audio: string, commit: boolean) =>
    JSON.stringify({ message_type: 'input_audio_chunk', audio_base_64: audio, commit, sample_rate: sampleRate })

  token.then((granted) => {
    if (closed) return
    sampleRate = granted.sample_rate
    const ws = new WebSocket(`${granted.url}&token=${encodeURIComponent(granted.token)}`)
    socket = ws
    ws.onopen = () => { for (const message of queue.splice(0)) ws.send(message) }
    ws.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as { message_type: string; text?: string; error?: string }
      if (message.message_type === 'committed_transcript') { settle?.resolve((message.text ?? '').trim()); settle = null }
      else if (message.message_type === NO_SPEECH) { settle?.resolve(''); settle = null }
      else if (message.error) fail(new Error(`${message.message_type}: ${message.error}`))
    }
    ws.onerror = () => fail(new Error('Transcription socket failed.'))
    ws.onclose = () => fail(new Error('Transcription socket closed.'))
  }, (error: unknown) => fail(error instanceof Error ? error : new Error('No transcription token.')))

  const close = () => {
    closed = true
    settle = null
    socket?.close()
    socket = null
  }
  return {
    push(frame) { if (!closed) send(chunk(pcm16Base64(frame), false)) },
    finish() {
      const result = new Promise<string>((resolve, reject) => {
        if (failure) { reject(failure); return }
        settle = { resolve, reject }
        send(chunk('', true))
      })
      const timeout = new Promise<string>((_, reject) => window.setTimeout(() => reject(new Error('Transcription timed out.')), FINISH_TIMEOUT_MS))
      return Promise.race([result, timeout]).finally(close)
    },
    close,
  }
}
