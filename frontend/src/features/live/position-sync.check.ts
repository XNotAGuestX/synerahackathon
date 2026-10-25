import assert from 'node:assert/strict'
import { shouldSend } from './shouldSend.ts'

const base = { floorId: 'f0', point: [0, 0] as [number, number], jumpSeq: 0, at: 0 }
assert.equal(shouldSend(null, base, 0), 'simulated')
assert.equal(shouldSend(base, { ...base, point: [1, 0] }, 500), null, 'throttled under 1 s')
assert.equal(shouldSend(base, { ...base, point: [1, 0] }, 1000), 'simulated')
assert.equal(shouldSend(base, { ...base, point: [0.1, 0] }, 2000), null, 'moved under 0.3 m')
assert.equal(shouldSend(base, base, 5000), 'simulated', 'heartbeat')
assert.equal(shouldSend(base, { ...base, jumpSeq: 1 }, 10), 'manual', 'jump is immediate')
assert.equal(shouldSend(base, { ...base, floorId: 'f1' }, 10), 'manual')
console.log('position-sync checks passed')
