import { expect, test } from 'claude-code/testing'

import { fold } from './transcript'

const assistant = (at: string, cache: number, model = 'claude-opus-5-5') =>
  JSON.stringify({ type: 'assistant', timestamp: at, message: { model, usage: { input_tokens: 5, cache_read_input_tokens: cache, cache_creation_input_tokens: 0, output_tokens: 90 } } })

test('a transcript gives calls, now, peak, minutes and the model', async () => {
  const f = fold([assistant('2026-10-09T10:00:00Z', 40_000), 'not json', JSON.stringify({ type: 'user', timestamp: '2026-10-09T10:01:00Z' }), assistant('2026-10-09T10:03:00Z', 90_000)].join('\n'))
  expect(f).toMatchObject({ calls: 2, now: 90_005, peak: 90_005, compactions: 0, model: 'claude-opus-5-5' })
  expect(f.last - f.first).toBe(180_000)
})

test('a compact_boundary entry and a fill that halves each count as a compaction', async () => {
  const f = fold([assistant('2026-10-09T10:00:00Z', 200_000), JSON.stringify({ type: 'system', subtype: 'compact_boundary' }), assistant('2026-10-09T10:01:00Z', 50_000)].join('\n'))
  expect(f.compactions).toBe(2)
  expect(f.now).toBe(50_005)
})
