export interface OfflineAssessmentResult {
  result_id: string;
  student_id: string;
  score: string;
  comment: string | null;
  given_name: string;
  middle_name: string | null;
  family_name: string;
  version?: number;
  locally_queued?: boolean;
  [key: string]: unknown;
}

export interface OfflineAssessmentStudent {
  student_id: string;
  given_name?: string;
  middle_name?: string | null;
  family_name?: string;
}

export interface OfflineAssessmentOutboxRow {
  status: string;
  entity_type: string;
  actor_id: string;
  entity_id: string;
  base_version?: number | null;
  payload?: {
    assessment_id?: string;
    student_id?: string;
    score?: string | number | null;
    comment?: string | null;
  };
}

export function mergePendingAssessmentResults(
  serverResults: OfflineAssessmentResult[],
  students: OfflineAssessmentStudent[],
  outboxRows: OfflineAssessmentOutboxRow[],
  assessmentId: string,
  actorId: string,
): OfflineAssessmentResult[];
