import { copy } from '../../i18n/en'

export const SAMPLE_RATE = 16000
const FRAME_SAMPLES = 320 // 20 ms

const WORKLET = `class Tap extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0] && inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true }
}
registerProcessor('tap', Tap)`

const modules = new WeakMap<AudioContext, Promise<void>>()

function loadWorklet(context: AudioContext): Promise<void> {
  let loaded = modules.get(context)
  if (!loaded) {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
    loaded = context.audioWorklet.addModule(url).finally(() => URL.revokeObjectURL(url))
    modules.set(context, loaded)
    loaded.catch(() => modules.delete(context))
  }
  return loaded
}

export class MicrophoneError extends Error {}

export function microphoneMessage(error: unknown): string {
  if (error instanceof MicrophoneError) return error.message
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') return copy.speechPermissionDenied
  if (name === 'NotFoundError') return copy.speechMicrophoneUnavailable
  return copy.speechPermissionFailed
}

// Mono 16 kHz frames of 20 ms via an AudioWorklet. Resamples by block averaging.
export function createCapture(context: AudioContext, onFrame: (frame: Float32Array) => void) {
  let stream: MediaStream | null = null
  let node: AudioWorkletNode | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let mute: GainNode | null = null
  let stopped = false
  return {
    async start() {
      if (!window.isSecureContext) throw new MicrophoneError(copy.speechSecureContext)
      if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') throw new MicrophoneError(copy.speechMicrophoneUnavailable)
      const acquired = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      if (stopped) { acquired.getTracks().forEach((track) => track.stop()); return }
      stream = acquired
      await loadWorklet(context)
      if (stopped) return
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
      source = context.createMediaStreamSource(stream)
      source.connect(node)
      // Keep the graph pulled without audible output.
      mute = context.createGain()
      mute.gain.value = 0
      node.connect(mute).connect(context.destination)
    },
    stop() {
      stopped = true
      if (node) node.port.onmessage = null
      node?.port.close()
      node?.disconnect()
      source?.disconnect()
      mute?.disconnect()
      stream?.getTracks().forEach((track) => track.stop())
      node = null; stream = null; source = null; mute = null
    },
  }
}
