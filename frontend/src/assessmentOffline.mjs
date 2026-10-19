/** Overlay locally queued draft scores on a fresh server result list after reload. */
export function mergePendingAssessmentResults(serverResults, students, outboxRows, assessmentId, actorId) {
  if (!Array.isArray(serverResults) || !Array.isArray(students) || !Array.isArray(outboxRows)) {
    throw new TypeError('Results, students and outbox rows must be arrays');
  }
  const merged = new Map(serverResults.map(result => [result.student_id, result]));
  const seen = new Set();
  // Outbox rows are expected newest-first. Only pending items may optimistically
  // override server state; conflicts must be reviewed rather than silently applied.
  for (const row of outboxRows) {
    if (!row || row.status !== 'pending' || row.entity_type !== 'draft_assessment_result' ||
        row.actor_id !== actorId || !row.payload || row.payload.assessment_id !== assessmentId ||
        typeof row.payload.student_id !== 'string') continue;
    const studentId = row.payload.student_id;
    if (seen.has(studentId)) continue;
    seen.add(studentId);
    const existing = merged.get(studentId);
    const student = students.find(item => item.student_id === studentId);
    merged.set(studentId, {
      result_id: row.entity_id,
      student_id: studentId,
      score: String(row.payload.score ?? ''),
      comment: row.payload.comment ?? existing?.comment ?? null,
      given_name: existing?.given_name ?? student?.given_name ?? '',
      middle_name: existing?.middle_name ?? student?.middle_name ?? null,
      family_name: existing?.family_name ?? student?.family_name ?? '',
      version: row.base_version == null ? 1 : row.base_version + 1,
      locally_queued: true,
    });
  }
  return [...merged.values()];
}
