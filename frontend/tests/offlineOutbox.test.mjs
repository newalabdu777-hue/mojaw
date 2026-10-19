import test from 'node:test';
import assert from 'node:assert/strict';
import { createMutationEnvelope, createConflictRetryEnvelope, enqueueMutation, listPendingMutations, acknowledgeMutation, buildSyncBatch, validateSyncResponse, retryDelayMs } from '../src/offlineOutbox.mjs';

const validInput = (overrides = {}) => ({
  mutationId: '123e4567-e89b-42d3-a456-426614174000',
  organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1',
  entityType: 'attendance_record', entityId: 'attendance-1', operation: 'create',
  payload: { student_id: 'student-1', date: '2026-10-19', status: 'present' },
  ...overrides,
});

test('creates a versioned pending envelope and clones payload', () => {
  const payload = { status: 'present' };
  const envelope = createMutationEnvelope(validInput({ payload }));
  payload.status = 'absent';
  assert.equal(envelope.protocol_version, 1);
  assert.equal(envelope.status, 'pending');
  assert.equal(envelope.payload.status, 'present');
  assert.equal(envelope.mutation_id, '123e4567-e89b-42d3-a456-426614174000');
});

test('prepares a conflict retry with a fresh ID and current server version without mutating the original', () => {
  const original = {
    ...createMutationEnvelope(validInput()),
    status: 'conflict',
    server_outcome: 'conflict',
    server_details: { reason: 'base_version_mismatch', current_version: 3 },
  };
  const retry = createConflictRetryEnvelope(original, {
    mutationId: '123e4567-e89b-42d3-b456-426614174099',
    payload: { student_id: 'student-1', date: '2026-10-19', status: 'absent' },
  });
  assert.equal(retry.mutation_id, '123e4567-e89b-42d3-b456-426614174099');
  assert.equal(retry.base_version, 3);
  assert.equal(retry.status, 'pending');
  assert.equal(retry.payload.status, 'absent');
  assert.equal(original.status, 'conflict');
  assert.equal(original.mutation_id, '123e4567-e89b-42d3-a456-426614174000');
  assert.throws(() => createConflictRetryEnvelope(original, { mutationId: original.mutation_id, payload: {} }), /fresh mutation UUID/);
  assert.throws(() => createConflictRetryEnvelope({ ...original, server_details: {} }, { mutationId: '123e4567-e89b-42d3-b456-426614174099', payload: {} }), /current server version/);
  assert.throws(() => createConflictRetryEnvelope({ ...original, status: 'blocked' }, { mutationId: '123e4567-e89b-42d3-b456-426614174099', payload: {} }), /conflicted mutation/);
});

test('rejects malformed IDs, unknown entities, invalid versions and unsafe JSON values', () => {
  assert.throws(() => createMutationEnvelope(validInput({ mutationId: 'not-a-uuid' })), /UUID/);
  assert.throws(() => createMutationEnvelope(validInput({ entityType: 'payment' })), /Unsupported/);
  assert.throws(() => createMutationEnvelope(validInput({ baseVersion: -1 })), /baseVersion/);
  assert.throws(() => createMutationEnvelope(validInput({ payload: { amount: Infinity } })), /finite/);
  assert.throws(() => createMutationEnvelope(validInput({ payload: new Date() })), /plain object/);
});

test('requires IndexedDB instead of silently pretending a mutation was saved', async () => {
  await assert.rejects(() => enqueueMutation(createMutationEnvelope(validInput()), null), /IndexedDB is unavailable/);
  await assert.rejects(() => listPendingMutations({ db: null }), /IndexedDB is unavailable/);
});

test('validates acknowledgement outcomes and batch limits', async () => {
  await assert.rejects(() => acknowledgeMutation('not-a-uuid', 'accepted', {}), /Invalid mutation acknowledgement/);
  await assert.rejects(() => listPendingMutations({ db: {}, limit: 501 }), /limit/);
});


test('builds bounded batches without local-only fields and refuses mixed identities', () => {
  const first = createMutationEnvelope(validInput());
  const batch = buildSyncBatch([first]);
  assert.equal(batch.protocol_version, 1);
  assert.equal(batch.mutations[0].mutation_id, first.mutation_id);
  assert.equal('status' in batch.mutations[0], false);
  assert.throws(() => buildSyncBatch([first, createMutationEnvelope(validInput({
    mutationId: '123e4567-e89b-42d3-b456-426614174001', deviceId: 'device-2'
  }))]), /cannot mix device_id/);
  assert.throws(() => buildSyncBatch([first, first]), /duplicate mutation IDs/);
  assert.throws(() => buildSyncBatch([]), /between 1 and 100/);
});

test('accepts only complete, matching, durable sync outcomes', () => {
  const envelope = createMutationEnvelope(validInput());
  const batch = buildSyncBatch([envelope]);
  const valid = {
    protocol_version: 1, organization_id: 'org-1', device_id: 'device-1',
    items: [{ mutation_id: envelope.mutation_id, outcome: 'accepted', durable: true }],
  };
  assert.equal(validateSyncResponse(batch, valid)[0].outcome, 'accepted');
  assert.throws(() => validateSyncResponse(batch, { ...valid, organization_id: 'org-other' }), /does not match/);
  assert.throws(() => validateSyncResponse(batch, { ...valid, items: [] }), /exactly one outcome/);
  assert.throws(() => validateSyncResponse(batch, { ...valid, items: [{ ...valid.items[0], durable: false }] }), /durable server commit/);
  assert.throws(() => validateSyncResponse(batch, { ...valid, items: [{ ...valid.items[0], outcome: 'retry', durable: true }] }), /cannot claim/);
});

import { syncPendingOutbox } from '../src/offlineSync.mjs';

test('sync transport acknowledges only after a fully validated durable response', async () => {
  const envelope = createMutationEnvelope(validInput());
  const acknowledged = [];
  const summary = await syncPendingOutbox({
    organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1', endpoint: 'https://example.invalid/api/v1/sync/batch',
    listPending: async () => [envelope],
    acknowledge: async (id, outcome, _db, details) => { acknowledged.push({ id, outcome, details }); return { status: 'acknowledged' }; },
    fetchImpl: async (_url, init) => {
      assert.equal(init.method, 'POST');
      assert.equal(JSON.parse(init.body).mutations.length, 1);
      return { ok: true, status: 200, json: async () => ({ protocol_version: 1, organization_id: 'org-1', device_id: 'device-1', items: [{ mutation_id: envelope.mutation_id, outcome: 'accepted', durable: true, entity_version: 2 }] }) };
    },
  });
  assert.equal(summary.acknowledged, 1);
  assert.equal(acknowledged.length, 1);
  assert.equal(acknowledged[0].outcome, 'accepted');
  assert.equal(acknowledged[0].details.entity_version, 2);
});

test('sync transport leaves queue untouched on HTTP and malformed-response failures', async () => {
  const envelope = createMutationEnvelope(validInput());
  let ackCount = 0;
  const common = {
    organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1', endpoint: '/api/v1/sync/batch',
    listPending: async () => [envelope], acknowledge: async () => { ackCount += 1; return { status: 'acknowledged' }; },
  };
  await assert.rejects(() => syncPendingOutbox({ ...common, fetchImpl: async () => ({ ok: false, status: 503 }) }), /HTTP 503/);
  await assert.rejects(() => syncPendingOutbox({ ...common, fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }) }), /does not match/);
  assert.equal(ackCount, 0);
});

test('sync transport only sends mutations belonging to the requested device and actor', async () => {
  const matching = createMutationEnvelope(validInput());
  const other = createMutationEnvelope(validInput({ mutationId: '123e4567-e89b-42d3-b456-426614174001', actorId: 'other-user' }));
  let sentCount = 0;
  const result = await syncPendingOutbox({
    organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1', endpoint: '/api/v1/sync/batch',
    listPending: async () => [matching, other],
    acknowledge: async () => ({ status: 'acknowledged' }),
    fetchImpl: async (_url, init) => {
      sentCount = JSON.parse(init.body).mutations.length;
      return { ok: true, status: 200, json: async () => ({ protocol_version: 1, organization_id: 'org-1', device_id: 'device-1', items: [{ mutation_id: matching.mutation_id, outcome: 'accepted', durable: true }] }) };
    },
  });
  assert.equal(sentCount, 1);
  assert.equal(result.selected, 1);
});

test('sync transport defers retry outcomes instead of acknowledging them', async () => {
  const envelope = createMutationEnvelope(validInput());
  let ackCount = 0;
  const deferred = [];
  const summary = await syncPendingOutbox({
    organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1', endpoint: '/api/v1/sync/batch',
    listPending: async () => [envelope],
    acknowledge: async () => { ackCount += 1; return { status: 'acknowledged' }; },
    deferRetry: async (id) => { deferred.push(id); },
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({
      protocol_version: 1, organization_id: 'org-1', device_id: 'device-1',
      items: [{ mutation_id: envelope.mutation_id, outcome: 'retry', durable: false }],
    }) }),
  });
  assert.equal(ackCount, 0);
  assert.deepEqual(deferred, [envelope.mutation_id]);
  assert.equal(summary.retries, 1);
  assert.equal(summary.remaining, 1);
});

test('summarizes all outbox states so conflicts and blocked items remain visible', async () => {
  const { summarizeOutboxRows } = await import('../src/offlineOutbox.mjs');
  assert.deepEqual(summarizeOutboxRows([
    { status: 'pending' }, { status: 'pending' }, { status: 'acknowledged' },
    { status: 'conflict' }, { status: 'blocked' }, { status: 'unexpected' }, null,
  ]), { pending: 2, acknowledged: 1, conflict: 1, blocked: 1, other: 2 });
  assert.throws(() => summarizeOutboxRows({}), /array/);
});


test('retry delay grows exponentially and is capped at six hours', () => {
  assert.equal(retryDelayMs(0), 2000);
  assert.equal(retryDelayMs(1), 4000);
  assert.equal(retryDelayMs(4), 32000);
  assert.equal(retryDelayMs(20), 6 * 60 * 60 * 1000);
  assert.equal(retryDelayMs(100), 6 * 60 * 60 * 1000);
  assert.throws(() => retryDelayMs(-1), /non-negative/);
});

test('sync transport skips pending items whose retry deadline has not arrived', async () => {
  const envelope = { ...createMutationEnvelope(validInput()), next_attempt_at: new Date(Date.now() + 60_000).toISOString() };
  let fetchCount = 0;
  const summary = await syncPendingOutbox({
    organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1', endpoint: '/api/v1/sync/batch',
    listPending: async () => [envelope],
    fetchImpl: async () => { fetchCount += 1; throw new Error('should not send before retry deadline'); },
  });
  assert.equal(fetchCount, 0);
  assert.equal(summary.selected, 0);
  assert.equal(summary.remaining, 1);
});


test('sync transport passes conflict diagnostics through for local review', async () => {
  const envelope = createMutationEnvelope(validInput());
  let storedDetails;
  const summary = await syncPendingOutbox({
    organizationId: 'org-1', deviceId: 'device-1', actorId: 'user-1', endpoint: '/api/v1/sync/batch',
    listPending: async () => [envelope],
    acknowledge: async (_id, outcome, _db, details) => { storedDetails = { outcome, ...details }; return { status: 'conflict' }; },
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({
      protocol_version: 1, organization_id: 'org-1', device_id: 'device-1',
      items: [{ mutation_id: envelope.mutation_id, outcome: 'conflict', durable: true, reason: 'base_version_mismatch', current_version: 3 }],
    }) }),
  });
  assert.equal(summary.conflicts, 1);
  assert.equal(storedDetails.reason, 'base_version_mismatch');
  assert.equal(storedDetails.current_version, 3);
});
