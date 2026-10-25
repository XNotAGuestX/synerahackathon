import assert from 'node:assert/strict'
import { encodeWav } from './wav.ts'

const buffer = encodeWav(new Float32Array([0, 1, -1, 0.5]), 16000)
const view = new DataView(buffer)
const tag = (o: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(o + i)))
assert.equal(buffer.byteLength, 44 + 8)
assert.equal(tag(0), 'RIFF'); assert.equal(tag(8), 'WAVE'); assert.equal(tag(12), 'fmt '); assert.equal(tag(36), 'data')
assert.equal(view.getUint32(4, true), 36 + 8)
assert.equal(view.getUint16(20, true), 1); assert.equal(view.getUint16(22, true), 1)
assert.equal(view.getUint32(24, true), 16000); assert.equal(view.getUint32(28, true), 32000)
assert.equal(view.getUint16(34, true), 16); assert.equal(view.getUint32(40, true), 8)
assert.equal(view.getInt16(46, true), 32767); assert.equal(view.getInt16(48, true), -32768)
console.log('wav ok')
