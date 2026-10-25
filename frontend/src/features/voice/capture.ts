import { copy } from '../../i18n/en'

export const SAMPLE_RATE = 16000
const FRAME_SAMPLES = 320 // 20 ms

const WORKLET = `class Tap extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true }
}
registerProcessor('tap', Tap)`

export class MicrophoneError extends Error {}

export function microphoneMessage(error: unknown): string {
  if (error instanceof MicrophoneError) return error.message
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') return copy.speechPermissionDenied
  if (name === 'NotFoundError') return copy.speechMicrophoneUnavailable
  return copy.speechPermissionFailed
}

// Mono 16 kHz frames of 20 ms via an AudioWorklet. Resamples by block averaging.
export function createCapture(onFrame: (frame: Float32Array) => void) {
  let stream: MediaStream | null = null
  let context: AudioContext | null = null
  let node: AudioWorkletNode | null = null
  return {
    async start() {
      if (!window.isSecureContext) throw new MicrophoneError(copy.speechSecureContext)
      if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') throw new MicrophoneError(copy.speechMicrophoneUnavailable)
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      // Native rate: Firefox refuses to connect a 48 kHz microphone to a 16 kHz context; we downsample below.
      context = new AudioContext()
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
      try { await context.audioWorklet.addModule(url) } finally { URL.revokeObjectURL(url) }
      const ratio = context.sampleRate / SAMPLE_RATE
      let pending = new Float32Array(FRAME_SAMPLES)
      let filled = 0
      let position = 0
      let sum = 0
      let count = 0
      node = new AudioWorkletNode(context, 'tap')
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        for (const sample of event.data) {
          sum += sample; count += 1; position += 1
          if (position >= ratio) {
            position -= ratio
            pending[filled] = sum / count
            sum = 0; count = 0
            filled += 1
            if (filled === FRAME_SAMPLES) { onFrame(pending); pending = new Float32Array(FRAME_SAMPLES); filled = 0 }
          }
        }
      }
      context.createMediaStreamSource(stream).connect(node)
      // Keep the graph pulled without audible output.
      const mute = context.createGain()
      mute.gain.value = 0
      node.connect(mute).connect(context.destination)
      await context.resume()
    },
    stop() {
      if (node) node.port.onmessage = null
      node?.disconnect()
      stream?.getTracks().forEach((track) => track.stop())
      void context?.close().catch(() => undefined)
      node = null; stream = null; context = null
    },
  }
}
