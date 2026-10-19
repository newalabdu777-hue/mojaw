import { useEffect, useMemo, useRef, useState } from 'react';
import { CloudOff, RefreshCw, ShieldCheck, Wifi } from 'lucide-react';
import { apiFetch, getAccessToken } from './api';
import { createConflictRetryEnvelope, enqueueMutation, listOutboxMutations, summarizeOutboxRows } from './offlineOutbox.mjs';
import type { MutationEnvelope } from './offlineOutbox.mjs';
import { syncPendingOutbox } from './offlineSync.mjs';

type SyncSummary = { considered: number; selected: number; acknowledged: number; conflicts: number; blocked: number; retries: number; remaining: number };
type OutboxRow = MutationEnvelope & { server_outcome?: string; server_details?: { reason?: string; current_version?: number; entity_version?: number } };

function ConflictReviewItem({ item, isAm, onQueued }: { item: OutboxRow; isAm: boolean; onQueued: () => void }) {
  const [payloadText, setPayloadText] = useState(() => JSON.stringify(item.payload, null, 2));
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState('');
  const canRebase = item.status === 'conflict' && item.operation === 'update' && Number.isSafeInteger(item.server_details?.current_version) && (item.server_details?.current_version ?? 0) >= 1;

  async function prepareRetry() {
    setSaving(true); setLocalError('');
    try {
      const parsed: unknown = JSON.parse(payloadText);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(isAm ? 'Payload የJSON object መሆን አለበት።' : 'Payload must be a JSON object.');
      const mutationId = globalThis.crypto?.randomUUID?.();
      if (!mutationId) throw new Error(isAm ? 'ይህ አሳሪ አዲስ UUID ማመንጨት አልቻለም።' : 'This browser cannot generate a fresh UUID.');
      const envelope = createConflictRetryEnvelope(item, { mutationId, payload: parsed as Record<string, unknown> });
      await enqueueMutation(envelope);
      onQueued();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : (isAm ? 'ዳግም ሙከራው አልተዘጋጀም።' : 'Could not prepare retry.'));
    } finally { setSaving(false); }
  }

  return <li className="sync-review-item">
    <div className="sync-review-row"><span><strong>{item.entity_type}</strong> · {item.operation} · <code>{item.mutation_id.slice(0, 8)}</code></span><span className={`outbox-state outbox-${item.status}`}>{item.status}</span></div>
    {(item.server_details?.reason || item.server_details?.current_version) && <small className="sync-review-detail">{item.server_details.reason ? item.server_details.reason.replaceAll('_', ' ') : ''}{item.server_details.current_version ? ` · ${isAm ? 'የServer ስሪት' : 'server version'} ${item.server_details.current_version}` : ''}</small>}
    {canRebase && <details className="sync-conflict-editor"><summary>{isAm ? 'መረጃውን ገምግምና እንደገና አዘጋጅ' : 'Review payload and prepare retry'}</summary><p className="muted-copy">{isAm ? 'ይህ አዲስ ሙከራ ያዘጋጃል፤ የመጀመሪያው ግጭት ይቀመጣል። ከመቀጠልዎ በፊት JSON ይመርምሩ።' : 'This creates a separate mutation and preserves the original conflict. Review the JSON before continuing.'}</p><label className="sync-payload-label">{isAm ? 'የመረጃ Payload (JSON)' : 'Mutation payload (JSON)'}<textarea value={payloadText} onChange={e => setPayloadText(e.target.value)} rows={7} spellCheck={false} /></label><button className="subtle-button" onClick={() => void prepareRetry()} disabled={saving}>{saving ? (isAm ? 'በማዘጋጀት ላይ…' : 'Preparing…') : (isAm ? `በስሪት ${item.server_details?.current_version} አዲስ ሙከራ አዘጋጅ` : `Prepare retry on version ${item.server_details?.current_version}`)}</button>{localError && <small role="alert" className="error-message">{localError}</small>}</details>}
  </li>;
}

export default function SyncPanel({ isAm, organizationId, actorId }: { isAm: boolean; organizationId: string; actorId: string }) {
  const [pending, setPending] = useState(0);
  const [outboxSummary, setOutboxSummary] = useState({ pending: 0, acknowledged: 0, conflict: 0, blocked: 0, other: 0 });
  const [reviewItems, setReviewItems] = useState<OutboxRow[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [lastSummary, setLastSummary] = useState<SyncSummary | null>(null);
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const syncLock = useRef(false);
  const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
  const deviceId = useMemo(() => {
    const key = 'school_device_id';
    try {
      const saved = window.localStorage.getItem(key);
      if (saved) return saved;
      const generated = globalThis.crypto?.randomUUID?.();
      if (generated) { window.localStorage.setItem(key, generated); return generated; }
    } catch { /* storage may be blocked */ }
    return 'temporary-device-session';
  }, []);

  async function refreshPending() {
    try {
      const rows = await listOutboxMutations({ organizationId, limit: 500 }) as OutboxRow[];
      const summary = summarizeOutboxRows(rows);
      setPending(summary.pending);
      setOutboxSummary(summary);
      setReviewItems(rows.filter(row => row.status === 'conflict' || row.status === 'blocked').slice(0, 8));
      setError('');
    } catch (e) {
      setPending(0);
      setOutboxSummary({ pending: 0, acknowledged: 0, conflict: 0, blocked: 0, other: 0 });
      setReviewItems([]);
      setError(e instanceof Error ? e.message : 'Unable to read offline queue');
    }
  }
  useEffect(() => { void refreshPending(); }, [organizationId]);
  useEffect(() => {
    const online = () => {
      setIsOnline(true);
      // Retry the durable outbox when connectivity returns; the server validates
      // each result before a local mutation can be acknowledged.
      if (pending > 0) void runSync();
    };
    const offline = () => setIsOnline(false);
    window.addEventListener('online', online);
    window.addEventListener('offline', offline);
    return () => { window.removeEventListener('online', online); window.removeEventListener('offline', offline); };
  }, [pending, organizationId, actorId, deviceId, apiBase, isAm]);

  async function runSync() {
    if (syncLock.current) return;
    syncLock.current = true;
    setSyncing(true); setError(''); setMessage('');
    try {
      const summary = await syncPendingOutbox({
        organizationId, deviceId, actorId, endpoint: `${apiBase}/api/v1/sync/batch`, token: getAccessToken() || undefined,
        fetchImpl: (input, init) => apiFetch(input, init),
      });
      setLastSummary(summary);
      setMessage(isAm
        ? `ተልኳል: ${summary.acknowledged}፣ ግጭት: ${summary.conflicts}፣ የታገደ: ${summary.blocked}፣ ዳግም ሙከራ: ${summary.retries}፣ ቀሪ: ${summary.remaining}`
        : `Acknowledged: ${summary.acknowledged}; conflicts: ${summary.conflicts}; blocked: ${summary.blocked}; retries: ${summary.retries}; remaining: ${summary.remaining}`);
      await refreshPending();
    } catch (e) {
      setError(e instanceof Error ? e.message : (isAm ? 'ማመሳሰል አልተሳካም' : 'Sync failed'));
    } finally { syncLock.current = false; setSyncing(false); }
  }

  return <div className="panel sync-panel">
    <div className="panel-heading"><div><h2>{isAm ? 'የመረጃ ማመሳሰል' : 'Offline sync'}</h2><p>{isAm ? 'የዚህ ኮምፒውተር የማመሳሰል ወረፋ' : 'This device’s synchronization queue'}</p></div><span className="status-chip"><span /> {isOnline ? (isAm ? 'ኦንላይን' : 'Online') : (isAm ? 'ኦፍላይን' : 'Offline')}</span></div>
    <div className="sync-summary"><div className="sync-big-icon"><Wifi size={20} /></div><div><strong>{pending} {isAm ? 'በመጠባበቅ ላይ' : 'pending mutations'}</strong><span>{isAm ? 'የServer ምላሽ ከተረጋገጠ ብቻ ይሰረዛሉ፤ ኢንተርኔት ሲመለስ ዳግም ይሞከራሉ' : 'Items are cleared only after validated server responses; reconnect triggers a retry'}</span></div><CloudOff size={19} /></div>
    <div className="sync-bottom-note"><ShieldCheck size={14} /> {isAm ? 'የሙከራ ፕሮቶታይፕ፤ አሁን የመገኘት መዝገብ ብቻ በServer ይደገፋል።' : 'Prototype only: the server supports attendance, student profile create/update, and draft assessment result create/update mutations.'}</div>
    <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
      <button className="subtle-button" onClick={() => void refreshPending()} disabled={syncing}><RefreshCw size={15} /> {isAm ? 'ወረፋውን አድስ' : 'Refresh queue'}</button>
      <button className="primary-button" onClick={() => void runSync()} disabled={syncing || pending === 0 || !isOnline}><RefreshCw size={15} className={syncing ? 'spin' : ''} /> {syncing ? (isAm ? 'በማመሳሰል ላይ…' : 'Syncing…') : (isAm ? 'አሁን አመሳስል' : 'Sync now')}</button>
    </div>
    {message && <p role="status" className="success-message">{message}</p>}
    {error && <p role="alert" className="error-message">{error}</p>}
    <div className="sync-status-grid" aria-label={isAm ? 'የወረፋ ሁኔታ' : 'Outbox status summary'}>
      <div><strong>{outboxSummary.acknowledged}</strong><span>{isAm ? 'ተሳክተዋል' : 'Acknowledged'}</span></div>
      <div><strong>{outboxSummary.conflict}</strong><span>{isAm ? 'ግጭት' : 'Conflicts'}</span></div>
      <div><strong>{outboxSummary.blocked}</strong><span>{isAm ? 'ታግደዋል' : 'Blocked'}</span></div>
    </div>
    {reviewItems.length > 0 && <div className="sync-review-list"><h3>{isAm ? 'እንደገና መታየት የሚጠይቁ መዝገቦች' : 'Items needing review'}</h3><p className="muted-copy">{isAm ? 'እነዚህ መዝገቦች አልተሰረዙም፤ በእጅ መፍትሄ ይፈልጋሉ።' : 'These records are retained locally and need manual resolution.'}</p><ul>{reviewItems.map(item => <ConflictReviewItem key={item.mutation_id} item={item} isAm={isAm} onQueued={() => { setMessage(isAm ? 'አዲሱ ሙከራ በወረፋው ተጨምሯል። ዋናው ግጭት ተጠብቋል።' : 'A separate retry was added to the queue; the original conflict is preserved.'); void refreshPending(); }} />)}</ul></div>}
    {lastSummary && <p className="muted-copy">{isAm ? 'በዚህ ሙከራ የታዩ መዝገቦች' : 'Mutations considered'}: {lastSummary.considered}; {isAm ? 'የተመረጡ' : 'selected'}: {lastSummary.selected}</p>}
  </div>;
}
