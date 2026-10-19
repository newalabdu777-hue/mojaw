import test from 'node:test';
import assert from 'node:assert/strict';
import { saveSnapshot, readSnapshot } from '../src/offlineSnapshots.mjs';

test('snapshot cache requires IndexedDB rather than pretending persistence succeeded', async () => {
  await assert.rejects(saveSnapshot({ organizationId: 'org', actorId: 'user', key: 'students', data: [] }, null), /IndexedDB is unavailable/);
  await assert.rejects(readSnapshot({ organizationId: 'org', actorId: 'user', key: 'students' }, null), /IndexedDB is unavailable/);
});

test('snapshot cache validates scope keys and rejects oversized values before opening IndexedDB', async () => {
  await assert.rejects(readSnapshot({ organizationId: '', actorId: 'user', key: 'students' }), /non-empty/);
  await assert.rejects(saveSnapshot({ organizationId: 'org', actorId: 'user', key: 'students', data: 'x'.repeat(2_000_001) }), /under 2 MB/);
});
