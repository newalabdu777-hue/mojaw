/** Small, organization/actor-scoped IndexedDB cache for read-only academic reference data. */
export const SNAPSHOT_DB_NAME = 'school-management-snapshots-v1';
const STORE = 'snapshots';

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Snapshot database request failed'));
  });
}
function transactionDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onabort = tx.onerror = () => reject(tx.error || new Error('Snapshot transaction failed'));
  });
}
export function openSnapshotDb(indexedDBImpl = globalThis.indexedDB) {
  if (!indexedDBImpl) return Promise.reject(new Error('IndexedDB is unavailable'));
  return new Promise((resolve, reject) => {
    const req = indexedDBImpl.open(SNAPSHOT_DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error('Unable to open snapshot database'));
    req.onblocked = () => reject(new Error('Snapshot database upgrade is blocked'));
  });
}
function makeKey(organizationId, actorId, key) {
  for (const value of [organizationId, actorId, key]) {
    if (typeof value !== 'string' || !value.trim() || value.length > 256) throw new TypeError('Snapshot identity fields must be non-empty strings up to 256 characters');
  }
  return `${organizationId}::${actorId}::${key}`;
}
export async function saveSnapshot({ organizationId, actorId, key, data }, db) {
  const snapshotKey = makeKey(organizationId, actorId, key);
  const serialized = JSON.stringify(data);
  if (serialized === undefined || serialized.length > 2_000_000) throw new TypeError('Snapshot must be JSON data under 2 MB');
  const ownDb = !db;
  const database = db || await openSnapshotDb();
  try {
    const tx = database.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).put({ key: snapshotKey, organization_id: organizationId, actor_id: actorId, cache_key: key, data: JSON.parse(serialized), saved_at: new Date().toISOString() });
    await transactionDone(tx);
  } finally { if (ownDb) database.close(); }
}
export async function readSnapshot({ organizationId, actorId, key }, db) {
  const snapshotKey = makeKey(organizationId, actorId, key);
  const ownDb = !db;
  const database = db || await openSnapshotDb();
  try {
    const tx = database.transaction(STORE, 'readonly');
    const result = await requestResult(tx.objectStore(STORE).get(snapshotKey));
    await transactionDone(tx);
    return result ? { data: result.data, savedAt: result.saved_at } : null;
  } finally { if (ownDb) database.close(); }
}
