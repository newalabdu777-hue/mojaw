import test from 'node:test';
import assert from 'node:assert/strict';
import { mergePendingAssessmentResults } from '../src/assessmentOffline.mjs';

const student = { student_id: 'student-1', given_name: 'Alem', middle_name: null, family_name: 'Bekele' };
const row = (overrides = {}) => ({
  status: 'pending', entity_type: 'draft_assessment_result', actor_id: 'user-1',
  entity_id: 'result-1', base_version: null,
  payload: { assessment_id: 'assessment-1', student_id: 'student-1', score: '88', comment: null },
  ...overrides,
});

test('restores a pending offline score over server data after reload', () => {
  const merged = mergePendingAssessmentResults(
    [{ result_id: 'server-result', student_id: 'student-1', score: '70', comment: 'old', given_name: 'Alem', middle_name: null, family_name: 'Bekele', version: 2 }],
    [student], [row()], 'assessment-1', 'user-1',
  );
  assert.equal(merged.length, 1);
  assert.equal(merged[0].score, '88');
  assert.equal(merged[0].result_id, 'result-1');
  assert.equal(merged[0].locally_queued, true);
});

test('does not overlay other assessments, actors, or conflicted mutations', () => {
  const merged = mergePendingAssessmentResults([], [student], [
    row({ payload: { ...row().payload, assessment_id: 'other-assessment' } }),
    row({ actor_id: 'other-user' }),
    row({ status: 'conflict', payload: { ...row().payload, score: '99' } }),
  ], 'assessment-1', 'user-1');
  assert.deepEqual(merged, []);
});

test('uses the newest pending mutation for each student and preserves unrelated server rows', () => {
  const merged = mergePendingAssessmentResults(
    [{ result_id: 'server-2', student_id: 'student-2', score: '50' }],
    [student], [row({ payload: { ...row().payload, score: '91' } }), row({ payload: { ...row().payload, score: '80' } })],
    'assessment-1', 'user-1');
  assert.equal(merged.find(item => item.student_id === 'student-1').score, '91');
  assert.equal(merged.find(item => item.student_id === 'student-2').score, '50');
});
