import assert from 'node:assert/strict'
import { createSpeechQueue } from './speech-queue.ts'

const item = (kind: 'reply' | 'instruction' | 'wrong_way', clipId: string) => ({ kind, clipId, text: clipId })
{
  const q = createSpeechQueue()
  q.enqueue(item('instruction', 'i1')); q.enqueue(item('wrong_way', 'w1')); q.enqueue(item('reply', 'r1'))
  assert.deepEqual([q.next()?.clipId, q.next()?.clipId, q.next()?.clipId, q.next()], ['r1', 'i1', 'w1', null])
}
{
  const q = createSpeechQueue()
  q.enqueue(item('instruction', 'i1')); q.enqueue(item('wrong_way', 'w1')); q.enqueue(item('instruction', 'i2'))
  assert.deepEqual([q.next()?.clipId, q.next()?.clipId, q.next()], ['w1', 'i2', null])
}
{
  const q = createSpeechQueue()
  q.enqueue(item('reply', 'r1')); q.enqueue(item('reply', 'r2')); q.enqueue(item('instruction', 'i1'))
  q.interrupt()
  assert.equal(q.next(), null); assert.equal(q.size(), 0)
}
console.log('queue ok')
