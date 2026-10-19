export interface SnapshotScope {
  organizationId: string;
  actorId: string;
  key: string;
}
export interface SnapshotInput extends SnapshotScope { data: unknown; }
export interface SnapshotResult { data: unknown; savedAt: string; }
export function openSnapshotDb(indexedDBImpl?: IDBFactory): Promise<IDBDatabase>;
export function saveSnapshot(input: SnapshotInput, db?: IDBDatabase): Promise<void>;
export function readSnapshot(scope: SnapshotScope, db?: IDBDatabase): Promise<SnapshotResult | null>;
