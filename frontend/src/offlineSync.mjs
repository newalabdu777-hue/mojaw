/** Transport and acknowledgement orchestration for the durable browser outbox. */
import { buildSyncBatch, validateSyncResponse, listPendingMutations, acknowledgeMutation, deferMutationRetry } from './offlineOutbox.mjs';

/**
 * Push one bounded batch for a single organization/device/actor.
 * Dependencies are injectable so transport and failure behavior can be tested without a browser.
 * Network/protocol failures deliberately leave all mutations pending for safe retry.
 */
export async function syncPendingOutbox({
  organizationId,
  deviceId,
  actorId,
  endpoint,
  token,
  fetchImpl = globalThis.fetch,
  db,
  listPending = listPendingMutations,
  acknowledge = acknowledgeMutation,
  deferRetry = deferMutationRetry,
  validateResponse = validateSyncResponse,
  buildBatch = buildSyncBatch,
} = {}) {
  for (const [name, value] of Object.entries({ organizationId, deviceId, actorId, endpoint })) {
    if (typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} is required`);
  }
  if (typeof fetchImpl !== 'function') throw new TypeError('fetch is unavailable');

  const pending = await listPending({ db, limit: 500, organizationId });
  const now = Date.now();
  const eligible = pending.filter(item => item.device_id === deviceId && item.actor_id === actorId && (!item.next_attempt_at || !Number.isFinite(Date.parse(item.next_attempt_at)) || Date.parse(item.next_attempt_at) <= now));
  if (eligible.length === 0) {
    return { considered: pending.length, selected: 0, acknowledged: 0, conflicts: 0, blocked: 0, retries: 0, remaining: pending.length };
  }

  // The protocol requires each batch to contain one actor/device/org. Keep the batch bounded.
  const batch = buildBatch(eligible.slice(0, 100));
  const headers = new Headers({ 'Content-Type': 'application/json', 'X-Organization-ID': organizationId });
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetchImpl(endpoint, { method: 'POST', headers, body: JSON.stringify(batch) });
  if (!response || !response.ok) {
    const status = response && Number.isInteger(response.status) ? response.status : 0;
    throw new Error(status ? `Sync request failed with HTTP ${status}` : 'Sync request failed before receiving a response');
  }
  const responseBody = await response.json();
  // Validate every outcome before changing any local queue state.
  const outcomes = validateResponse(batch, responseBody);
  const summary = { considered: pending.length, selected: batch.mutations.length, acknowledged: 0, conflicts: 0, blocked: 0, retries: 0, remaining: pending.length - batch.mutations.length };
  for (const outcome of outcomes) {
    // Retry outcomes remain pending, but a durable deadline prevents rapid repeated requests.
    if (outcome.outcome === 'retry') { await deferRetry(outcome.mutation_id, db); summary.retries += 1; summary.remaining += 1; continue; }
    const result = await acknowledge(outcome.mutation_id, outcome.outcome, db, outcome);
    if (result.status === 'acknowledged') summary.acknowledged += 1;
    else if (result.status === 'conflict') summary.conflicts += 1;
    else if (result.status === 'blocked') summary.blocked += 1;
  }
  return summary;
}
