import assert from 'node:assert/strict'
import { createVad } from './vad.ts'

function run(vad: ReturnType<typeof createVad>, rms: number, ms: number, playback = false): string[] {
  const out: string[] = []
  for (let t = 0; t < ms; t += 20) { const e = vad.push(rms, 20, playback); if (e) out.push(e) }
  return out
}
{
  const vad = createVad()
  assert.deepEqual(run(vad, 0.003, 2000), [])
  assert.deepEqual(run(vad, 0.1, 200), [])
  assert.deepEqual(run(vad, 0.1, 100), ['start'])
  assert.deepEqual(run(vad, 0.1, 500), [])
  assert.deepEqual(run(vad, 0.002, 1000), ['end'])
}
{
  // Echo guard: moderate energy that starts a normal turn does not during playback.
  assert.deepEqual(run(createVad(), 0.03, 1000, true), [])
  assert.deepEqual(run(createVad(), 0.03, 300), ['start'])
  const loud = createVad()
  assert.deepEqual(run(loud, 0.2, 380, true), [])
  assert.deepEqual(run(loud, 0.2, 40, true), ['start'])
}
assert.deepEqual(run(createVad(), 0.1, 15500), ['start', 'end'])
console.log('vad ok')
