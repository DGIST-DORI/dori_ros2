import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizePollLines } from './logUtils.js';

test('keeps identical lines across separate poll responses to preserve timeline', () => {
  const firstPoll = normalizePollLines(['[INFO] chunk-1 processed']);
  const secondPoll = normalizePollLines(['[INFO] chunk-1 processed']);

  const timeline = [...firstPoll, ...secondPoll];

  assert.deepEqual(timeline, ['[INFO] chunk-1 processed', '[INFO] chunk-1 processed']);
});

test('dedupes duplicates only within the same poll response', () => {
  const samePoll = normalizePollLines(['A', 'A', 'B', 'A']);

  assert.deepEqual(samePoll, ['A', 'B']);
});
