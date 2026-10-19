import type { MutationEnvelope, SyncOutcome } from './offlineOutbox.mjs';
export interface SyncSummary {
  considered: number;
  selected: number;
  acknowledged: number;
  conflicts: number;
  blocked: number;
  retries: number;
  remaining: number;
}
export function syncPendingOutbox(options: {
  organizationId: string;
  deviceId: string;
  actorId: string;
  endpoint: string;
  token?: string;
  fetchImpl?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  db?: IDBDatabase;
  listPending?: (options?: { db?: IDBDatabase; limit?: number; organizationId?: string }) => Promise<MutationEnvelope[]>;
  acknowledge?: (mutationId: string, outcome: SyncOutcome['outcome'], db?: IDBDatabase) => Promise<{ status: string }>;
  validateResponse?: (batch: import('./offlineOutbox.mjs').SyncBatch, response: unknown) => SyncOutcome[];
  buildBatch?: (envelopes: MutationEnvelope[]) => import('./offlineOutbox.mjs').SyncBatch;
}): Promise<SyncSummary>;
