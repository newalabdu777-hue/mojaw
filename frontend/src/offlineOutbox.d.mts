export type MutationOutcome = 'accepted' | 'duplicate' | 'conflict' | 'rejected' | 'retry';
export type MutationStatus = 'pending' | 'acknowledged' | 'conflict' | 'blocked';
export interface MutationEnvelope {
  protocol_version: 1;
  mutation_id: string;
  organization_id: string;
  device_id: string;
  actor_id: string;
  entity_type: 'attendance_record' | 'student_profile' | 'guardian_link' | 'draft_assessment_result';
  entity_id: string;
  operation: 'create' | 'update' | 'delete';
  base_version: number | null;
  schema_version: 1;
  created_at_device: string;
  payload: Record<string, unknown>;
  status: MutationStatus;
  attempts: number;
  server_outcome?: MutationOutcome;
  server_details?: { reason?: string; current_version?: number; entity_version?: number };
  acknowledged_at?: string;
}
export interface SyncBatch {
  protocol_version: 1;
  organization_id: string;
  device_id: string;
  mutations: Array<Omit<MutationEnvelope, 'status' | 'attempts' | 'server_outcome' | 'acknowledged_at'>>;
}
export interface SyncOutcome {
  mutation_id: string;
  outcome: MutationOutcome;
  durable?: boolean;
  reason?: string;
  entity_id?: string;
  entity_version?: number;
}
export const OUTBOX_DB_NAME: string;
export const OUTBOX_STORE_NAME: string;
export const OUTBOX_PROTOCOL_VERSION: 1;
export function createMutationEnvelope(input: Record<string, unknown>): MutationEnvelope;
export function createConflictRetryEnvelope(original: MutationEnvelope, input: { mutationId: string; payload: Record<string, unknown> }): MutationEnvelope;
export function buildSyncBatch(envelopes: MutationEnvelope[]): SyncBatch;
export function validateSyncResponse(batch: SyncBatch, response: unknown): SyncOutcome[];
export function openOutbox(indexedDBImpl?: IDBFactory): Promise<IDBDatabase>;
export function enqueueMutation(envelope: MutationEnvelope, db?: IDBDatabase): Promise<{ inserted: boolean; mutationId: string }>;
export function listPendingMutations(options?: { db?: IDBDatabase; limit?: number; organizationId?: string }): Promise<MutationEnvelope[]>;
export function acknowledgeMutation(mutationId: string, outcome: Exclude<MutationOutcome, 'retry'>, db?: IDBDatabase, serverDetails?: { reason?: string; current_version?: number; entity_version?: number }): Promise<{ mutationId: string; status: MutationStatus }>;
export function listOutboxMutations(options?: { db?: IDBDatabase; limit?: number; organizationId?: string }): Promise<MutationEnvelope[]>;
export function summarizeOutboxRows(rows: Array<{ status?: string } | null | undefined>): { pending: number; acknowledged: number; conflict: number; blocked: number; other: number };
