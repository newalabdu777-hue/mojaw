/**
 * Browser-side durable outbox primitives. Queue persistence is separate from transport;
 * Attendance and draft assessment score submissions can be queued from the UI when offline.
 */
export const OUTBOX_DB_NAME = 'school-management-outbox-v1';
export const OUTBOX_STORE_NAME = 'mutations';
export const OUTBOX_PROTOCOL_VERSION = 1;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ENTITY_TYPES = new Set(['attendance_record', 'student_profile', 'guardian_link', 'draft_assessment_result']);
const OPERATIONS = new Set(['create', 'update', 'delete']);

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function assertJsonValue(value, depth = 0) {
  if (depth > 32) throw new TypeError('Payload nesting exceeds 32 levels');
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('Payload numbers must be finite');
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) assertJsonValue(item, depth + 1);
    return;
  }
  if (!isPlainObject(value)) throw new TypeError('Payload must contain JSON-compatible values only');
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'prototype', 'constructor'].includes(key)) throw new TypeError('Unsafe payload key');
    assertJsonValue(item, depth + 1);
  }
}

/** Build a stable client envelope. IDs must be generated once and reused on retry. */
export function createMutationEnvelope(input) {
  if (!isPlainObject(input)) throw new TypeError('Mutation input must be an object');
  const { mutationId, organizationId, deviceId, actorId, entityType, entityId, operation, baseVersion = null, payload } = input;
  if (typeof mutationId !== 'string' || !UUID_RE.test(mutationId)) throw new TypeError('mutationId must be a UUID');
  for (const [name, value] of Object.entries({ organizationId, deviceId, actorId, entityId })) {
    if (typeof value !== 'string' || value.trim().length === 0 || value.length > 128) throw new TypeError(`${name} must be a non-empty string up to 128 characters`);
  }
  if (!ENTITY_TYPES.has(entityType)) throw new TypeError('Unsupported offline entity type');
  if (!OPERATIONS.has(operation)) throw new TypeError('Unsupported mutation operation');
  if (baseVersion !== null && (!Number.isSafeInteger(baseVersion) || baseVersion < 0)) throw new TypeError('baseVersion must be a non-negative safe integer or null');
  if (!isPlainObject(payload)) throw new TypeError('payload must be a plain object');
  assertJsonValue(payload);
  // Clone now so later UI edits cannot mutate the queued command in memory.
  const stablePayload = JSON.parse(JSON.stringify(payload));
  return Object.freeze({
    protocol_version: OUTBOX_PROTOCOL_VERSION,
    mutation_id: mutationId.toLowerCase(),
    organization_id: organizationId.trim(),
    device_id: deviceId.trim(),
    actor_id: actorId.trim(),
    entity_type: entityType,
    entity_id: entityId.trim(),
    operation,
    base_version: baseVersion,
    schema_version: 1,
    created_at_device: new Date().toISOString(),
    payload: stablePayload,
    status: 'pending',
    attempts: 0,
  });
}


/**
 * Prepare a human-approved replacement for a conflicted mutation.
 * The original conflict is never modified; a fresh mutation ID prevents the
 * server's idempotency record for the old conflict from being replayed.
 */
export function createConflictRetryEnvelope(original, { mutationId, payload }) {
  if (!isPlainObject(original) || original.status !== 'conflict') {
    throw new TypeError('Only a conflicted mutation can be prepared for retry');
  }
  if (!original.server_details || !Number.isSafeInteger(original.server_details.current_version) || original.server_details.current_version < 1) {
    throw new Error('Conflict retry requires the current server version; refresh and review the record first');
  }
  if (typeof mutationId !== 'string' || !UUID_RE.test(mutationId) || mutationId.toLowerCase() === String(original.mutation_id).toLowerCase()) {
    throw new TypeError('Conflict retry requires a fresh mutation UUID');
  }
  return createMutationEnvelope({
    mutationId,
    organizationId: original.organization_id,
    deviceId: original.device_id,
    actorId: original.actor_id,
    entityType: original.entity_type,
    entityId: original.entity_id,
    operation: original.operation,
    baseVersion: original.server_details.current_version,
    payload,
  });
}


const SYNC_OUTCOMES = new Set(['accepted', 'duplicate', 'conflict', 'rejected', 'retry']);
const MAX_SYNC_BATCH_ITEMS = 100;
const MAX_SYNC_BATCH_BYTES = 256 * 1024;

/** Build a bounded batch from one organization/device/actor only. */
export function buildSyncBatch(envelopes) {
  if (!Array.isArray(envelopes) || envelopes.length < 1 || envelopes.length > MAX_SYNC_BATCH_ITEMS) {
    throw new RangeError(`Sync batch must contain between 1 and ${MAX_SYNC_BATCH_ITEMS} mutations`);
  }
  const first = envelopes[0];
  if (!first || first.status !== 'pending' || !UUID_RE.test(first.mutation_id || '')) {
    throw new TypeError('Sync batch contains an invalid pending mutation');
  }
  const seen = new Set();
  for (const item of envelopes) {
    if (!item || item.status !== 'pending' || !UUID_RE.test(item.mutation_id || '')) {
      throw new TypeError('Sync batch contains an invalid pending mutation');
    }
    if (seen.has(item.mutation_id.toLowerCase())) throw new TypeError('Sync batch contains duplicate mutation IDs');
    seen.add(item.mutation_id.toLowerCase());
    for (const key of ['organization_id', 'device_id', 'actor_id']) {
      if (item[key] !== first[key]) throw new TypeError(`Sync batch cannot mix ${key} values`);
    }
  }
  const body = {
    protocol_version: OUTBOX_PROTOCOL_VERSION,
    organization_id: first.organization_id,
    device_id: first.device_id,
    mutations: envelopes.map(({ status, attempts, server_outcome, acknowledged_at, ...wire }) => wire),
  };
  const encoded = JSON.stringify(body);
  if (new TextEncoder().encode(encoded).byteLength > MAX_SYNC_BATCH_BYTES) {
    throw new RangeError(`Sync batch exceeds ${MAX_SYNC_BATCH_BYTES} bytes`);
  }
  return body;
}

/** Validate the complete response before acknowledging any queued item. */
export function validateSyncResponse(batch, response) {
  if (!batch || !Array.isArray(batch.mutations) || !response || typeof response !== 'object') {
    throw new TypeError('Invalid sync request or response');
  }
  if (response.protocol_version !== OUTBOX_PROTOCOL_VERSION ||
      response.organization_id !== batch.organization_id || response.device_id !== batch.device_id ||
      !Array.isArray(response.items)) {
    throw new Error('Sync response identity or protocol version does not match the request');
  }
  const expected = new Set(batch.mutations.map(item => item.mutation_id.toLowerCase()));
  if (expected.size !== batch.mutations.length || response.items.length !== expected.size) {
    throw new Error('Sync response must contain exactly one outcome per mutation');
  }
  const received = new Set();
  for (const item of response.items) {
    if (!item || typeof item.mutation_id !== 'string' || !UUID_RE.test(item.mutation_id) || !SYNC_OUTCOMES.has(item.outcome)) {
      throw new Error('Sync response contains an invalid outcome');
    }
    const id = item.mutation_id.toLowerCase();
    if (!expected.has(id) || received.has(id)) throw new Error('Sync response contains an unknown or duplicate mutation ID');
    received.add(id);
    if (['accepted', 'duplicate'].includes(item.outcome) && item.durable !== true) {
      throw new Error('Successful sync outcomes must confirm durable server commit');
    }
    if (item.outcome === 'retry' && item.durable === true) {
      throw new Error('Retry outcome cannot claim a durable business commit');
    }
  }
  return response.items;
}

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'));
  });
}
function transactionDone(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = transaction.onerror = () => reject(transaction.error || new Error('IndexedDB transaction failed'));
  });
}

export function openOutbox(indexedDBImpl = globalThis.indexedDB) {
  if (!indexedDBImpl) return Promise.reject(new Error('IndexedDB is unavailable in this environment'));
  return new Promise((resolve, reject) => {
    const request = indexedDBImpl.open(OUTBOX_DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(OUTBOX_STORE_NAME)) {
        const store = db.createObjectStore(OUTBOX_STORE_NAME, { keyPath: 'mutation_id' });
        store.createIndex('status_created', ['status', 'created_at_device'], { unique: false });
        store.createIndex('organization_id', 'organization_id', { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Unable to open offline outbox'));
    request.onblocked = () => reject(new Error('Offline outbox upgrade is blocked by another open tab'));
  });
}

export async function enqueueMutation(envelope, db) {
  if (!envelope || envelope.protocol_version !== OUTBOX_PROTOCOL_VERSION || envelope.status !== 'pending' || !UUID_RE.test(envelope.mutation_id || '')) {
    throw new TypeError('Invalid outbox mutation envelope');
  }
  const ownDb = !db;
  const database = db || await openOutbox();
  try {
    const transaction = database.transaction(OUTBOX_STORE_NAME, 'readwrite', { durability: 'strict' });
    const store = transaction.objectStore(OUTBOX_STORE_NAME);
    const existing = await requestResult(store.get(envelope.mutation_id));
    if (existing) {
      if (JSON.stringify(existing.payload) !== JSON.stringify(envelope.payload) || existing.entity_type !== envelope.entity_type || existing.operation !== envelope.operation) {
        transaction.abort();
        throw new Error('Mutation ID already exists with a different command');
      }
      await transactionDone(transaction);
      return { inserted: false, mutationId: envelope.mutation_id };
    }
    store.add(envelope);
    await transactionDone(transaction);
    return { inserted: true, mutationId: envelope.mutation_id };
  } finally {
    if (ownDb) database.close();
  }
}

export async function listOutboxMutations({ db, limit = 100, organizationId } = {}) {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 500) throw new RangeError('limit must be between 1 and 500');
  const ownDb = !db;
  const database = db || await openOutbox();
  try {
    const transaction = database.transaction(OUTBOX_STORE_NAME, 'readonly');
    const rows = await requestResult(transaction.objectStore(OUTBOX_STORE_NAME).getAll());
    await transactionDone(transaction);
    return rows.filter(row => !organizationId || row.organization_id === organizationId)
      .sort((a, b) => b.created_at_device.localeCompare(a.created_at_device)).slice(0, limit);
  } finally {
    if (ownDb) database.close();
  }
}

export async function listPendingMutations(options = {}) {
  return (await listOutboxMutations(options)).filter(row => row.status === 'pending')
    .sort((a, b) => a.created_at_device.localeCompare(b.created_at_device));
}

/** Compact status counts for the UI; unknown statuses are surfaced as other. */
export function summarizeOutboxRows(rows) {
  if (!Array.isArray(rows)) throw new TypeError('Outbox rows must be an array');
  const summary = { pending: 0, acknowledged: 0, conflict: 0, blocked: 0, other: 0 };
  for (const row of rows) {
    if (!row || typeof row.status !== 'string' || !(row.status in summary)) summary.other += 1;
    else summary[row.status] += 1;
  }
  return summary;
}

/** Exponential retry delay, capped to avoid hammering a server during prolonged outages. */
export function retryDelayMs(attempts) {
  if (!Number.isSafeInteger(attempts) || attempts < 0) throw new TypeError('attempts must be a non-negative safe integer');
  return Math.min(6 * 60 * 60 * 1000, 2000 * (2 ** Math.min(attempts, 20)));
}

/** Persist a retry deadline without acknowledging or removing the mutation. */
export async function deferMutationRetry(mutationId, db, now = Date.now()) {
  if (typeof mutationId !== 'string' || !UUID_RE.test(mutationId) || !Number.isFinite(now)) {
    throw new TypeError('Invalid mutation retry request');
  }
  const ownDb = !db;
  const database = db || await openOutbox();
  try {
    const transaction = database.transaction(OUTBOX_STORE_NAME, 'readwrite', { durability: 'strict' });
    const store = transaction.objectStore(OUTBOX_STORE_NAME);
    const row = await requestResult(store.get(mutationId.toLowerCase()));
    if (!row || row.status !== 'pending') {
      transaction.abort();
      throw new Error('Only a pending mutation can be deferred for retry');
    }
    const attempts = Number.isSafeInteger(row.attempts) && row.attempts >= 0 ? row.attempts : 0;
    row.attempts = attempts + 1;
    row.last_attempt_at = new Date(now).toISOString();
    row.next_attempt_at = new Date(now + retryDelayMs(attempts)).toISOString();
    store.put(row);
    await transactionDone(transaction);
    return { mutationId: row.mutation_id, attempts: row.attempts, nextAttemptAt: row.next_attempt_at };
  } finally {
    if (ownDb) database.close();
  }
}

/** Acknowledge only after the caller validates a durable server outcome. */
export async function acknowledgeMutation(mutationId, outcome, db, serverDetails = {}) {
  if (typeof mutationId !== 'string' || !UUID_RE.test(mutationId) || !['accepted', 'duplicate', 'conflict', 'rejected'].includes(outcome)) {
    throw new TypeError('Invalid mutation acknowledgement');
  }
  const ownDb = !db;
  const database = db || await openOutbox();
  try {
    const transaction = database.transaction(OUTBOX_STORE_NAME, 'readwrite', { durability: 'strict' });
    const store = transaction.objectStore(OUTBOX_STORE_NAME);
    const row = await requestResult(store.get(mutationId.toLowerCase()));
    if (!row) { transaction.abort(); throw new Error('Cannot acknowledge an unknown mutation'); }
    row.status = outcome === 'conflict' ? 'conflict' : outcome === 'rejected' ? 'blocked' : 'acknowledged';
    row.server_outcome = outcome;
    // Preserve bounded, non-sensitive protocol diagnostics for conflict review.
    if (serverDetails && typeof serverDetails === 'object') {
      const details = {};
      if (typeof serverDetails.reason === 'string') details.reason = serverDetails.reason.slice(0, 200);
      if (Number.isSafeInteger(serverDetails.current_version) && serverDetails.current_version >= 1) details.current_version = serverDetails.current_version;
      if (Number.isSafeInteger(serverDetails.entity_version) && serverDetails.entity_version >= 1) details.entity_version = serverDetails.entity_version;
      if (Object.keys(details).length) row.server_details = details;
    }
    row.acknowledged_at = new Date().toISOString();
    store.put(row);
    await transactionDone(transaction);
    return { mutationId: row.mutation_id, status: row.status };
  } finally {
    if (ownDb) database.close();
  }
}
