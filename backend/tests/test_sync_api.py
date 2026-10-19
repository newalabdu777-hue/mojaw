import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

class SyncProtocolApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {"SCHOOL_DEV_DB_PATH": str(Path(self.tmp.name) / "sync.sqlite3")})
        self.env_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.headers = {"X-Organization-ID": "org-test"}
        student_response = self.client.post("/api/v1/students", headers=self.headers, json={
            "given_name": "Sync", "family_name": "Student", "branch_id": "branch-1"
        })
        self.assertEqual(student_response.status_code, 201, student_response.text)
        self.student_id = student_response.json()["student_id"]
        self.payload = {
            "protocol_version": 1, "organization_id": "org-test", "device_id": "device-a",
            "mutations": [{
                "protocol_version": 1, "mutation_id": "b7e23d82-5d0c-4a9d-8c3c-bb8a8d99b46e",
                "organization_id": "org-test", "device_id": "device-a", "actor_id": "actor-a",
                "entity_type": "attendance_record", "entity_id": "attendance-1", "operation": "create",
                "base_version": None, "schema_version": 1, "created_at_device": "2026-10-19T10:00:00Z",
                "payload": {"student_id": self.student_id, "attendance_date": "2026-10-19", "status": "present", "note": "offline register"}
            }]
        }

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_attendance_create_is_applied_durably(self):
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["mode"], "student-attendance-draft-assessment-result-mutations-prototype")
        self.assertTrue(body["business_mutations_applied"])
        self.assertEqual(body["items"][0]["outcome"], "accepted")
        self.assertTrue(body["items"][0]["durable"])
        records = self.client.get("/api/v1/attendance", headers=self.headers, params={"attendance_date": "2026-10-19"})
        self.assertEqual(records.status_code, 200, records.text)
        self.assertEqual(records.json()["total"], 1)

    def test_exact_retry_returns_duplicate_outcome(self):
        first = self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        second = self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["items"][0]["outcome"], "duplicate")
        records = self.client.get("/api/v1/attendance", headers=self.headers, params={"attendance_date": "2026-10-19"})
        self.assertEqual(records.json()["total"], 1, "retry must not create a second attendance record")

    def test_attendance_update_uses_optimistic_version_and_records_history(self):
        created = self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        self.assertEqual(created.json()["items"][0]["outcome"], "accepted")
        update = {
            **self.payload,
            "mutations": [{
                **self.payload["mutations"][0],
                "mutation_id": "d8d2a6c2-bc6e-4b40-96b8-5c12c44c8c0a",
                "entity_id": "attendance-1",
                "operation": "update",
                "base_version": 1,
                "payload": {"status": "absent", "note": "corrected after review", "reason": "Teacher confirmed register"},
            }],
        }
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=update)
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertEqual(item["outcome"], "accepted")
        self.assertEqual(item["entity_version"], 2)
        history = self.client.get("/api/v1/attendance/attendance-1/history", headers=self.headers)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()["total"], 1)
        records = self.client.get("/api/v1/attendance", headers=self.headers, params={"attendance_date": "2026-10-19"})
        self.assertEqual(records.json()["items"][0]["status"], "absent")

    def test_stale_attendance_update_is_conflict_without_overwriting(self):
        self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        update = {**self.payload, "mutations": [{
            **self.payload["mutations"][0], "mutation_id": "f5b7b8c7-0a83-45f2-9b0d-7d0b3b6d2a09",
            "entity_id": "attendance-1", "operation": "update", "base_version": 0,
            "payload": {"status": "absent", "note": None, "reason": "Teacher confirmed register"},
        }]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=update)
        item = response.json()["items"][0]
        self.assertEqual(item["outcome"], "conflict")
        self.assertEqual(item["reason"], "base_version_mismatch")
        self.assertEqual(item["current_version"], 1)
        records = self.client.get("/api/v1/attendance", headers=self.headers, params={"attendance_date": "2026-10-19"})
        self.assertEqual(records.json()["items"][0]["status"], "present")

    def test_attendance_update_requires_base_version(self):
        self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        update = {**self.payload, "mutations": [{
            **self.payload["mutations"][0], "mutation_id": "8c5d5f67-5a24-4e7a-8f4b-4cc2f9c66d73",
            "entity_id": "attendance-1", "operation": "update", "base_version": None,
            "payload": {"status": "absent", "note": None, "reason": "Teacher confirmed register"},
        }]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=update)
        self.assertEqual(response.json()["items"][0]["reason"], "base_version_required_for_update")

    def test_reusing_mutation_id_with_different_payload_is_conflict(self):
        self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        changed = {**self.payload, "mutations": [{**self.payload["mutations"][0], "payload": {**self.payload["mutations"][0]["payload"], "status": "absent"}}]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=changed)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["outcome"], "conflict")

    def test_unsupported_domain_operation_is_durably_rejected(self):
        changed = {**self.payload, "mutations": [{**self.payload["mutations"][0], "entity_type": "guardian_link"}]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=changed)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"][0]["outcome"], "rejected")
        self.assertEqual(response.json()["items"][0]["reason"], "only_student_create_update_draft_assessment_result_and_attendance_mutations_are_supported")

    def test_student_profile_create_is_applied_durably_and_retry_is_idempotent(self):
        mutation = {
            **self.payload["mutations"][0],
            "mutation_id": "4f1a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
            "entity_type": "student_profile", "entity_id": "offline-student-001",
            "operation": "create", "base_version": None,
            "payload": {"given_name": "Offline", "middle_name": "Sync", "family_name": "Learner",
                        "branch_id": "branch-1", "sex_at_registration": "unspecified",
                        "date_of_birth": "2014-05-06", "external_reference": "LOCAL-001"},
        }
        body = {**self.payload, "mutations": [mutation]}
        first = self.client.post("/api/v1/sync/batch", headers=self.headers, json=body)
        second = self.client.post("/api/v1/sync/batch", headers=self.headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["items"][0]["outcome"], "accepted")
        self.assertEqual(first.json()["items"][0]["entity_version"], 1)
        self.assertEqual(second.json()["items"][0]["outcome"], "duplicate")
        student = self.client.get("/api/v1/students/offline-student-001", headers=self.headers)
        self.assertEqual(student.status_code, 200, student.text)
        self.assertEqual(student.json()["given_name"], "Offline")
        self.assertEqual(student.json()["external_reference"], "LOCAL-001")

    def test_student_profile_create_rejects_invalid_payload_and_id_collision(self):
        mutation = {
            **self.payload["mutations"][0], "mutation_id": "5f1a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
            "entity_type": "student_profile", "entity_id": "offline-student-002",
            "operation": "create", "base_version": None,
            "payload": {"given_name": "", "family_name": "Learner", "branch_id": "branch-1"},
        }
        invalid = self.client.post("/api/v1/sync/batch", headers=self.headers, json={**self.payload, "mutations": [mutation]})
        self.assertEqual(invalid.json()["items"][0]["outcome"], "rejected")
        self.assertEqual(invalid.json()["items"][0]["reason"], "invalid_student_profile_payload")
        collision = {**mutation, "mutation_id": "6f1a0f7d-7b6d-4e32-9a9b-2f71d75a2b83", "entity_id": self.student_id,
                     "payload": {"given_name": "Offline", "family_name": "Learner", "branch_id": "branch-1"}}
        conflict = self.client.post("/api/v1/sync/batch", headers=self.headers, json={**self.payload, "mutations": [collision]})
        self.assertEqual(conflict.json()["items"][0]["outcome"], "conflict")
        self.assertEqual(conflict.json()["items"][0]["reason"], "student_id_already_exists")

    def test_student_profile_update_uses_optimistic_version_and_audit_history(self):
        mutation = {
            **self.payload["mutations"][0],
            "mutation_id": "7f1a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
            "entity_type": "student_profile", "entity_id": self.student_id,
            "operation": "update", "base_version": 1,
            "payload": {"given_name": "Updated", "external_reference": "SYNC-UPDATED"},
        }
        body = {**self.payload, "mutations": [mutation]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertEqual(item["outcome"], "accepted")
        self.assertEqual(item["entity_version"], 2)
        student = self.client.get(f"/api/v1/students/{self.student_id}", headers=self.headers)
        self.assertEqual(student.json()["given_name"], "Updated")
        self.assertEqual(student.json()["external_reference"], "SYNC-UPDATED")
        history = self.client.get(f"/api/v1/students/{self.student_id}/history", headers=self.headers)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertTrue(any(event["event_type"] == "student.updated" for event in history.json()["items"]))

    def test_student_profile_stale_update_conflicts_without_overwriting(self):
        mutation = {
            **self.payload["mutations"][0],
            "mutation_id": "8f1a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
            "entity_type": "student_profile", "entity_id": self.student_id,
            "operation": "update", "base_version": 0,
            "payload": {"given_name": "Stale update"},
        }
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json={**self.payload, "mutations": [mutation]})
        item = response.json()["items"][0]
        self.assertEqual(item["outcome"], "conflict")
        self.assertEqual(item["reason"], "base_version_mismatch")
        self.assertEqual(item["current_version"], 1)
        student = self.client.get(f"/api/v1/students/{self.student_id}", headers=self.headers)
        self.assertEqual(student.json()["given_name"], "Sync")

    def test_attendance_delete_is_durably_rejected_and_retry_is_idempotent(self):
        self.client.post("/api/v1/sync/batch", headers=self.headers, json=self.payload)
        delete_mutation = {
            **self.payload["mutations"][0],
            "mutation_id": "2f1a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
            "operation": "delete",
            "base_version": 1,
            "payload": {"reason": "mistaken entry"},
        }
        request_body = {**self.payload, "mutations": [delete_mutation]}
        first = self.client.post("/api/v1/sync/batch", headers=self.headers, json=request_body)
        second = self.client.post("/api/v1/sync/batch", headers=self.headers, json=request_body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["items"][0]["outcome"], "rejected")
        self.assertEqual(first.json()["items"][0]["reason"], "attendance_delete_is_not_supported")
        self.assertEqual(second.json()["items"][0]["outcome"], "duplicate")
        records = self.client.get("/api/v1/attendance", headers=self.headers, params={"attendance_date": "2026-10-19"})
        self.assertEqual(records.json()["total"], 1, "unsupported delete must not remove the attendance record")

    def test_attendance_create_for_unknown_student_is_rejected(self):
        changed = {**self.payload, "mutations": [{**self.payload["mutations"][0], "payload": {**self.payload["mutations"][0]["payload"], "student_id": "not-a-student"}}]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=changed)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"][0]["outcome"], "rejected")
        self.assertEqual(response.json()["items"][0]["reason"], "student_not_found_in_organization")

    def test_tenant_mismatch_is_forbidden(self):
        response = self.client.post("/api/v1/sync/batch", headers={"X-Organization-ID": "other-org"}, json=self.payload)
        self.assertEqual(response.status_code, 403)

    def test_duplicate_ids_inside_batch_are_rejected(self):
        changed = {**self.payload, "mutations": [self.payload["mutations"][0], self.payload["mutations"][0]]}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json=changed)
        self.assertEqual(response.status_code, 422)

    def test_draft_assessment_result_sync_create_update_and_retry(self):
        assessment = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "subject": "Mathematics", "title": "Quiz 1", "term": "Term 1", "max_score": "20"
        })
        self.assertEqual(assessment.status_code, 201, assessment.text)
        assessment_id = assessment.json()["assessment_id"]
        mutation = {
            **self.payload["mutations"][0], "mutation_id": "a71a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
            "entity_type": "draft_assessment_result", "entity_id": "result-offline-1", "operation": "create", "base_version": None,
            "payload": {"assessment_id": assessment_id, "student_id": self.student_id, "score": "16", "comment": "offline score"},
        }
        body = {**self.payload, "mutations": [mutation]}
        first = self.client.post("/api/v1/sync/batch", headers=self.headers, json=body)
        retry = self.client.post("/api/v1/sync/batch", headers=self.headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["items"][0]["outcome"], "accepted")
        self.assertEqual(first.json()["items"][0]["entity_version"], 1)
        self.assertEqual(retry.json()["items"][0]["outcome"], "duplicate")
        update = {**mutation, "mutation_id": "b71a0f7d-7b6d-4e32-9a9b-2f71d75a2b83", "operation": "update", "base_version": 1,
                  "payload": {"assessment_id": assessment_id, "student_id": self.student_id, "score": "18", "comment": "reviewed"}}
        updated = self.client.post("/api/v1/sync/batch", headers=self.headers, json={**self.payload, "mutations": [update]})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["items"][0]["outcome"], "accepted")
        self.assertEqual(updated.json()["items"][0]["entity_version"], 2)
        results = self.client.get(f"/api/v1/academics/assessments/{assessment_id}/results", headers=self.headers)
        self.assertEqual(results.status_code, 200, results.text)
        self.assertEqual(results.json()["items"][0]["score"], "18")
        history = self.client.get(f"/api/v1/academics/assessments/{assessment_id}/results/{self.student_id}/history", headers=self.headers)
        self.assertEqual(history.json()["total"], 2)

    def test_draft_assessment_result_sync_rejects_published_assessment_and_high_score(self):
        assessment = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "subject": "Mathematics", "title": "Quiz 2", "term": "Term 1", "max_score": "10"
        })
        assessment_id = assessment.json()["assessment_id"]
        too_high = {**self.payload["mutations"][0], "mutation_id": "c71a0f7d-7b6d-4e32-9a9b-2f71d75a2b83",
                    "entity_type": "draft_assessment_result", "entity_id": "result-high", "operation": "create", "base_version": None,
                    "payload": {"assessment_id": assessment_id, "student_id": self.student_id, "score": "11"}}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json={**self.payload, "mutations": [too_high]})
        self.assertEqual(response.json()["items"][0]["reason"], "score_exceeds_assessment_max_score")
        seeded_result = self.client.post(f"/api/v1/academics/assessments/{assessment_id}/results", headers=self.headers,
                                         json={"student_id": self.student_id, "score": "5"})
        self.assertEqual(seeded_result.status_code, 200, seeded_result.text)
        published = self.client.post(f"/api/v1/academics/assessments/{assessment_id}/publish", headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        after_publish = {**too_high, "mutation_id": "d71a0f7d-7b6d-4e32-9a9b-2f71d75a2b83", "payload": {"assessment_id": assessment_id, "student_id": self.student_id, "score": "5"}}
        response = self.client.post("/api/v1/sync/batch", headers=self.headers, json={**self.payload, "mutations": [after_publish]})
        self.assertEqual(response.json()["items"][0]["reason"], "published_assessment_is_immutable")

if __name__ == "__main__":
    unittest.main()
