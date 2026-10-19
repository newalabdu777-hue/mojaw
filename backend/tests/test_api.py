import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app, ensure_non_production_runtime
from app.services import student_store
from app.schemas.students import StudentCreate
from pydantic import ValidationError


class ApiFoundationTests(unittest.TestCase):
    def test_production_runtime_is_blocked_for_unfinished_prototype(self):
        for environment in ("production", "PROD", " prod "):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(RuntimeError, "not production-ready"):
                    ensure_non_production_runtime(environment)

    def test_development_runtime_is_allowed(self):
        ensure_non_production_runtime("development")
        ensure_non_production_runtime("test")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        self.env_patch = patch.dict(os.environ, {"SCHOOL_DEV_DB_PATH": self.db_path})
        self.env_patch.start()
        # Each test gets an isolated database; TestClient starts the app lifespan.
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_root_discloses_prototype_mode(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "prototype")

    def test_request_id_is_generated_when_missing(self):
        response = self.client.get("/health/live")
        request_id = response.headers.get("x-request-id")
        self.assertTrue(request_id)
        self.assertRegex(request_id, r"^[0-9a-f-]{36}$")

    def test_safe_request_id_is_preserved(self):
        response = self.client.get("/health/live", headers={"X-Request-ID": "support.case-17:retry_2"})
        self.assertEqual(response.headers.get("x-request-id"), "support.case-17:retry_2")

    def test_invalid_request_id_is_replaced(self):
        response = self.client.get("/health/live", headers={"X-Request-ID": "not a safe id"})
        request_id = response.headers.get("x-request-id")
        self.assertNotEqual(request_id, "not a safe id")
        self.assertRegex(request_id, r"^[0-9a-f-]{36}$")

    def test_liveness(self):
        response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_readiness_discloses_no_production_persistence(self):
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "starter-no-persistence")

    def test_openapi_documents_students(self):
        response = self.client.get("/api/v1/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/v1/students", response.json()["paths"])

    def test_student_contract_rejects_blank_name(self):
        with self.assertRaises(ValidationError):
            StudentCreate(given_name="  ", family_name="Abebe", branch_id="branch-1")

    def test_student_contract_rejects_extra_fields(self):
        with self.assertRaises(ValidationError):
            StudentCreate(given_name="Mimi", family_name="Abebe", branch_id="branch-1", admission_number="A-1")

    def test_create_and_list_students_scoped_by_organization(self):
        headers = {"X-Organization-ID": "org-a"}
        response = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        })
        self.assertEqual(response.status_code, 201, response.text)
        student = response.json()
        self.assertEqual(student["organization_id"], "org-a")
        self.assertTrue(student["student_id"])
        self.assertEqual(response.headers.get("x-prototype-only"), "true")
        own = self.client.get("/api/v1/students", headers=headers)
        other = self.client.get("/api/v1/students", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(own.json()["total"], 1)
        self.assertEqual(other.json()["total"], 0)

    def test_student_search_is_case_insensitive_and_supports_branch_and_pagination(self):
        headers = {"X-Organization-ID": "org-search"}
        for given, family, branch, external in [
            ("Mimi", "Abebe", "north", "REG-100"),
            ("Mimi", "Bekele", "south", "REG-200"),
            ("Dawit", "Abebe", "north", "REG-300"),
        ]:
            response = self.client.post("/api/v1/students", headers=headers, json={
                "given_name": given, "family_name": family, "branch_id": branch,
                "external_reference": external,
            })
            self.assertEqual(response.status_code, 201, response.text)
        searched = self.client.get("/api/v1/students?q=mImI&limit=1&offset=0", headers=headers)
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()["total"], 2)
        self.assertEqual(len(searched.json()["items"]), 1)
        branch_search = self.client.get("/api/v1/students?q=abebe&branch_id=north", headers=headers)
        self.assertEqual(branch_search.json()["total"], 2)
        external_search = self.client.get("/api/v1/students?q=REG-200", headers=headers)
        self.assertEqual(external_search.json()["total"], 1)

    def test_student_search_is_tenant_scoped_and_escapes_like_wildcards(self):
        headers = {"X-Organization-ID": "org-a"}
        self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Percent%Name", "family_name": "Test", "branch_id": "branch-1"
        })
        self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-b"}, json={
            "given_name": "PercentXName", "family_name": "Test", "branch_id": "branch-1"
        })
        literal = self.client.get("/api/v1/students?q=%25", headers=headers)
        self.assertEqual(literal.status_code, 200, literal.text)
        self.assertEqual(literal.json()["total"], 1)
        other_tenant = self.client.get("/api/v1/students?q=Percent", headers=headers)
        self.assertEqual(other_tenant.json()["total"], 1)

    def test_patch_student_updates_fields_but_keeps_branch_immutable(self):
        headers = {"X-Organization-ID": "org-a"}
        created = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.patch(f"/api/v1/students/{created['student_id']}", headers=headers, json={
            "family_name": "Kebede", "external_reference": "EXT-7"
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["family_name"], "Kebede")
        self.assertEqual(response.json()["external_reference"], "EXT-7")
        self.assertEqual(response.json()["branch_id"], "branch-1")

    def test_patch_student_is_tenant_scoped(self):
        created = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.patch(f"/api/v1/students/{created['student_id']}", headers={"X-Organization-ID": "org-b"}, json={"family_name": "Changed"})
        self.assertEqual(response.status_code, 404)

    def test_patch_student_rejects_empty_update(self):
        created = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.patch(f"/api/v1/students/{created['student_id']}", headers={"X-Organization-ID": "org-a"}, json={})
        self.assertEqual(response.status_code, 422)

    def test_student_deactivation_requires_reason_and_records_audit_atomically(self):
        headers = {"X-Organization-ID": "org-a"}
        created = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        url = f"/api/v1/students/{created['student_id']}/deactivate"
        missing_reason = self.client.post(url, headers=headers, json={"reason": "  "})
        self.assertEqual(missing_reason.status_code, 422)
        deactivated = self.client.post(url, headers=headers, json={"reason": "Left the school"})
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        self.assertEqual(deactivated.json()["status"], "inactive")
        audit = self.client.get("/api/v1/finance/audit-events", headers=headers, params={
            "entity_type": "student", "entity_id": created["student_id"], "event_type": "student.deactivated"
        })
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertEqual(audit.json()["total"], 1)
        self.assertEqual(audit.json()["items"][0]["details"]["reason"], "Left the school")
        repeated = self.client.post(url, headers=headers, json={"reason": "Repeated attempt"})
        self.assertEqual(repeated.status_code, 409)

    def test_student_history_returns_only_that_students_audit_events(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        other = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Sami", "family_name": "Kebede", "branch_id": "branch-1"
        }).json()
        self.client.post(f"/api/v1/students/{student['student_id']}/deactivate", headers=headers,
                         json={"reason": "Left the school"})
        response = self.client.get(f"/api/v1/students/{student['student_id']}/history", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["student_id"], student["student_id"])
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["entity_id"], student["student_id"])
        self.assertEqual(response.json()["items"][0]["event_type"], "student.deactivated")
        missing = self.client.get(f"/api/v1/students/{other['student_id']}/history",
                                  headers={"X-Organization-ID": "org-b"})
        self.assertEqual(missing.status_code, 404)

    def test_student_deactivation_is_tenant_scoped(self):
        created = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.post(
            f"/api/v1/students/{created['student_id']}/deactivate",
            headers={"X-Organization-ID": "org-b"}, json={"reason": "Wrong organization"},
        )
        self.assertEqual(response.status_code, 404)

    def test_create_and_list_guardians_for_student(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        created = self.client.post(f"/api/v1/students/{student['student_id']}/guardians", headers=headers, json={
            "given_name": "Almaz", "family_name": "Abebe", "relationship": "mother", "phone": "+251900000000", "is_primary": True
        })
        self.assertEqual(created.status_code, 201, created.text)
        guardian = created.json()
        self.assertEqual(guardian["organization_id"], "org-a")
        self.assertEqual(guardian["student_id"], student["student_id"])
        self.assertTrue(guardian["is_primary"])
        self.assertFalse(guardian["portal_access"])
        listed = self.client.get(f"/api/v1/students/{student['student_id']}/guardians", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

    def test_guardian_directory_finds_shared_identity_and_counts_links(self):
        headers = {"X-Organization-ID": "org-a"}
        student_one = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        student_two = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Dawit", "family_name": "Kebede", "branch_id": "branch-1"
        }).json()
        guardian = self.client.post(f"/api/v1/students/{student_one['student_id']}/guardians", headers=headers, json={
            "given_name": "Almaz", "family_name": "Abebe", "relationship": "mother", "phone": "+251900000000"
        }).json()
        linked = self.client.post(
            f"/api/v1/students/{student_two['student_id']}/guardians/{guardian['guardian_id']}/link",
            headers=headers, json={"relationship": "mother"}
        )
        self.assertEqual(linked.status_code, 201, linked.text)
        directory = self.client.get("/api/v1/guardians?q=Almaz", headers=headers)
        self.assertEqual(directory.status_code, 200, directory.text)
        body = directory.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["guardian_id"], guardian["guardian_id"])
        self.assertEqual(body["items"][0]["linked_student_count"], 2)
        self.assertNotIn("student_id", body["items"][0])

    def test_guardian_directory_is_tenant_scoped_and_paged(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        self.client.post(f"/api/v1/students/{student['student_id']}/guardians", headers=headers, json={
            "given_name": "Almaz", "family_name": "Abebe", "relationship": "mother"
        })
        other_org = self.client.get("/api/v1/guardians", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(other_org.status_code, 200, other_org.text)
        self.assertEqual(other_org.json()["total"], 0)
        invalid = self.client.get("/api/v1/guardians?limit=201", headers=headers)
        self.assertEqual(invalid.status_code, 422)

    def test_guardians_are_tenant_scoped(self):
        student = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.get(f"/api/v1/students/{student['student_id']}/guardians", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(response.status_code, 404)

    def test_guardian_requires_relationship(self):
        student = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.post(f"/api/v1/students/{student['student_id']}/guardians", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Almaz", "family_name": "Abebe"
        })
        self.assertEqual(response.status_code, 422)

    def test_organization_header_required(self):
        response = self.client.get("/api/v1/students")
        self.assertEqual(response.status_code, 400)

    def test_student_not_visible_across_organizations(self):
        created = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.get(f"/api/v1/students/{created['student_id']}", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(response.status_code, 404)


    def test_attendance_create_list_and_correct_with_audit_history(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        created = self.client.post("/api/v1/attendance", headers=headers, json={
            "student_id": student["student_id"], "attendance_date": "2026-10-19", "status": "present", "note": "Morning check"
        })
        self.assertEqual(created.status_code, 201, created.text)
        record = created.json()
        self.assertEqual(record["branch_id"], "branch-1")
        self.assertEqual(record["version"], 1)
        listed = self.client.get("/api/v1/attendance?attendance_date=2026-10-19", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        corrected = self.client.patch(f"/api/v1/attendance/{record['attendance_id']}", headers=headers, json={
            "status": "late", "reason": "Teacher confirmed late arrival", "note": "Arrived at 08:20"
        })
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()["status"], "late")
        self.assertEqual(corrected.json()["version"], 2)
        history = self.client.get(f"/api/v1/attendance/{record['attendance_id']}/history", headers=headers)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["total"], 1)
        self.assertEqual(history.json()["items"][0]["old_status"], "present")

    def test_attendance_duplicate_student_date_is_rejected(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        body = {"student_id": student["student_id"], "attendance_date": "2026-10-19", "status": "absent"}
        self.assertEqual(self.client.post("/api/v1/attendance", headers=headers, json=body).status_code, 201)
        duplicate = self.client.post("/api/v1/attendance", headers=headers, json=body)
        self.assertEqual(duplicate.status_code, 409)

    def test_attendance_is_tenant_scoped_and_unknown_student_rejected(self):
        student = self.client.post("/api/v1/students", headers={"X-Organization-ID": "org-a"}, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.post("/api/v1/attendance", headers={"X-Organization-ID": "org-b"}, json={
            "student_id": student["student_id"], "attendance_date": "2026-10-19", "status": "present"
        })
        self.assertEqual(response.status_code, 404)

    def test_attendance_summary_counts_statuses_and_excludes_excused_from_rate_denominator(self):
        headers = {"X-Organization-ID": "org-a"}
        student_ids = []
        for branch in ("branch-1", "branch-1", "branch-1", "branch-2"):
            student = self.client.post("/api/v1/students", headers=headers, json={
                "given_name": "Test", "family_name": "Student", "branch_id": branch
            }).json()
            student_ids.append(student["student_id"])
        statuses = [("present", "branch-1"), ("late", "branch-1"), ("excused", "branch-1"), ("absent", "branch-2")]
        for student_id, (attendance_status, _) in zip(student_ids, statuses):
            response = self.client.post("/api/v1/attendance", headers=headers, json={
                "student_id": student_id, "attendance_date": "2026-10-18", "status": attendance_status
            })
            self.assertEqual(response.status_code, 201, response.text)
        summary = self.client.get("/api/v1/attendance/summary?start_date=2026-10-18&end_date=2026-10-19", headers=headers)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["total_recorded"], 4)
        self.assertEqual(summary.json()["present"], 1)
        self.assertEqual(summary.json()["late"], 1)
        self.assertEqual(summary.json()["excused"], 1)
        self.assertEqual(summary.json()["attendance_rate_pct"], 66.67)
        branch_summary = self.client.get("/api/v1/attendance/summary?start_date=2026-10-18&end_date=2026-10-19&branch_id=branch-1", headers=headers)
        self.assertEqual(branch_summary.json()["total_recorded"], 3)
        other_org = self.client.get("/api/v1/attendance/summary?start_date=2026-10-18&end_date=2026-10-19", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(other_org.json()["total_recorded"], 0)

    def test_bulk_attendance_creates_all_records(self):
        headers = {"X-Organization-ID": "org-a"}
        ids = []
        for name in ("Aster", "Bekele", "Chaltu"):
            student = self.client.post("/api/v1/students", headers=headers, json={
                "given_name": name, "family_name": "Student", "branch_id": "branch-1"
            }).json()
            ids.append(student["student_id"])
        response = self.client.post("/api/v1/attendance/bulk", headers=headers, json={
            "attendance_date": "2026-10-19",
            "records": [
                {"student_id": ids[0], "status": "present"},
                {"student_id": ids[1], "status": "absent", "note": "Not in class"},
                {"student_id": ids[2], "status": "late"},
            ]
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["created"], 3)
        self.assertEqual({r["student_id"] for r in response.json()["items"]}, set(ids))

    def test_bulk_attendance_is_atomic_when_student_missing(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Aster", "family_name": "Student", "branch_id": "branch-1"
        }).json()
        response = self.client.post("/api/v1/attendance/bulk", headers=headers, json={
            "attendance_date": "2026-10-19",
            "records": [
                {"student_id": student["student_id"], "status": "present"},
                {"student_id": "not-a-student", "status": "absent"},
            ]
        })
        self.assertEqual(response.status_code, 404, response.text)
        records = self.client.get("/api/v1/attendance?attendance_date=2026-10-19", headers=headers)
        self.assertEqual(records.json()["total"], 0)

    def test_bulk_attendance_conflict_rolls_back_all_records(self):
        headers = {"X-Organization-ID": "org-a"}
        students = []
        for name in ("Aster", "Bekele"):
            students.append(self.client.post("/api/v1/students", headers=headers, json={
                "given_name": name, "family_name": "Student", "branch_id": "branch-1"
            }).json()["student_id"])
        self.client.post("/api/v1/attendance", headers=headers, json={
            "student_id": students[1], "attendance_date": "2026-10-19", "status": "present"
        })
        response = self.client.post("/api/v1/attendance/bulk", headers=headers, json={
            "attendance_date": "2026-10-19", "records": [
                {"student_id": students[0], "status": "present"},
                {"student_id": students[1], "status": "absent"},
            ]
        })
        self.assertEqual(response.status_code, 409, response.text)
        records = self.client.get("/api/v1/attendance?attendance_date=2026-10-19", headers=headers)
        self.assertEqual(records.json()["total"], 1)

    def test_bulk_attendance_rejects_duplicate_student_ids(self):
        response = self.client.post("/api/v1/attendance/bulk", headers={"X-Organization-ID": "org-a"}, json={
            "attendance_date": "2026-10-19", "records": [
                {"student_id": "student-1", "status": "present"},
                {"student_id": "student-1", "status": "absent"},
            ]
        })
        self.assertEqual(response.status_code, 422)

    def test_student_attendance_report_counts_statuses_and_includes_students_without_records(self):
        headers = {"X-Organization-ID": "org-a"}
        first = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Aster", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        second = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Bekele", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        for day, status in (("2026-10-17", "present"), ("2026-10-18", "late"), ("2026-10-19", "absent"), ("2026-10-20", "excused")):
            response = self.client.post("/api/v1/attendance", headers=headers, json={
                "student_id": first["student_id"], "attendance_date": day, "status": status
            })
            self.assertEqual(response.status_code, 201, response.text)
        report = self.client.get("/api/v1/attendance/reports/students?start_date=2026-10-17&end_date=2026-10-20", headers=headers)
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["total"], 2)
        by_id = {item["student_id"]: item for item in report.json()["items"]}
        self.assertEqual(by_id[first["student_id"]]["total_recorded"], 4)
        self.assertEqual(by_id[first["student_id"]]["present"], 1)
        self.assertEqual(by_id[first["student_id"]]["late"], 1)
        self.assertEqual(by_id[first["student_id"]]["absent"], 1)
        self.assertEqual(by_id[first["student_id"]]["excused"], 1)
        self.assertEqual(by_id[first["student_id"]]["attendance_rate_pct"], 66.67)
        self.assertEqual(by_id[second["student_id"]]["total_recorded"], 0)
        self.assertIsNone(by_id[second["student_id"]]["attendance_rate_pct"])

    def test_student_attendance_report_is_tenant_scoped_and_paginated(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Aster", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        response = self.client.get("/api/v1/attendance/reports/students?start_date=2026-10-01&end_date=2026-10-31&limit=1&offset=0", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(len(response.json()["items"]), 1)
        foreign = self.client.get("/api/v1/attendance/reports/students?start_date=2026-10-01&end_date=2026-10-31", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(foreign.json()["total"], 0)

    def test_student_attendance_report_csv_exports_tenant_scoped_paginated_rows(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Aster", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        self.client.post("/api/v1/attendance", headers=headers, json={
            "student_id": student["student_id"], "attendance_date": "2026-10-19", "status": "present"
        })
        response = self.client.get(
            "/api/v1/attendance/reports/students.csv?start_date=2026-10-01&end_date=2026-10-31&limit=1",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("attachment; filename=", response.headers["content-disposition"])
        self.assertEqual(response.headers["x-report-total"], "1")
        self.assertEqual(response.headers["x-report-exported"], "1")
        self.assertIn("student_id,branch_id,full_name,total_recorded,present,absent,late,excused,attendance_rate_pct", response.text)
        self.assertIn(student["student_id"], response.text)
        foreign = self.client.get(
            "/api/v1/attendance/reports/students.csv?start_date=2026-10-01&end_date=2026-10-31",
            headers={"X-Organization-ID": "org-b"},
        )
        self.assertEqual(foreign.headers["x-report-total"], "0")
        self.assertNotIn(student["student_id"], foreign.text)

    def test_student_attendance_csv_neutralizes_spreadsheet_formula_names(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "=1+1", "family_name": "Example", "branch_id": "branch-1"
        }).json()
        response = self.client.get(
            "/api/v1/attendance/reports/students.csv?start_date=2026-10-01&end_date=2026-10-31",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("'=1+1 Example", response.text)
        self.assertNotIn(",=1+1 Example,", response.text)

    def test_student_attendance_report_csv_rejects_reversed_dates(self):
        response = self.client.get(
            "/api/v1/attendance/reports/students.csv?start_date=2026-10-20&end_date=2026-10-19",
            headers={"X-Organization-ID": "org-a"},
        )
        self.assertEqual(response.status_code, 422)

    def test_student_attendance_report_rejects_reversed_date_range(self):
        response = self.client.get("/api/v1/attendance/reports/students?start_date=2026-10-20&end_date=2026-10-19", headers={"X-Organization-ID": "org-a"})
        self.assertEqual(response.status_code, 422)

    def test_attendance_summary_rejects_reversed_date_range(self):
        response = self.client.get("/api/v1/attendance/summary?start_date=2026-10-20&end_date=2026-10-19", headers={"X-Organization-ID": "org-a"})
        self.assertEqual(response.status_code, 422)

    def test_attendance_correction_requires_reason(self):
        headers = {"X-Organization-ID": "org-a"}
        student = self.client.post("/api/v1/students", headers=headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()
        record = self.client.post("/api/v1/attendance", headers=headers, json={
            "student_id": student["student_id"], "attendance_date": "2026-10-19", "status": "present"
        }).json()
        response = self.client.patch(f"/api/v1/attendance/{record['attendance_id']}", headers=headers, json={"status": "absent"})
        self.assertEqual(response.status_code, 422)



if __name__ == "__main__":
    unittest.main()

class AcademicAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "academic.sqlite3")
        self.env_patch = patch.dict(os.environ, {"SCHOOL_DEV_DB_PATH": self.db_path})
        self.env_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.headers = {"X-Organization-ID": "org-a"}
        self.student = self.client.post("/api/v1/students", headers=self.headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def create_assessment(self):
        return self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "subject": "Mathematics", "title": "Quiz 1", "term": "Term 1", "assessment_date": "2026-10-19", "max_score": "20.000"
        })

    def test_create_assessment_save_result_and_publish_locks_changes(self):
        assessment_response = self.create_assessment()
        self.assertEqual(assessment_response.status_code, 201, assessment_response.text)
        assessment = assessment_response.json()
        saved = self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers=self.headers, json={"student_id": self.student["student_id"], "score": "17.500"})
        self.assertEqual(saved.status_code, 200, saved.text)
        results = self.client.get(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers=self.headers)
        self.assertEqual(results.json()["total"], 1)
        published = self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/publish", headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["status"], "published")
        blocked = self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers=self.headers, json={"student_id": self.student["student_id"], "score": "18"})
        self.assertEqual(blocked.status_code, 409)

    def test_result_changes_are_recorded_in_history(self):
        assessment = self.create_assessment().json()
        url = f"/api/v1/academics/assessments/{assessment['assessment_id']}/results"
        first = self.client.post(url, headers=self.headers, json={"student_id": self.student["student_id"], "score": "12.5", "comment": "Initial"})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(url, headers=self.headers, json={"student_id": self.student["student_id"], "score": "14", "comment": "Rechecked"})
        self.assertEqual(second.status_code, 200, second.text)
        history_url = f"/api/v1/academics/assessments/{assessment['assessment_id']}/results/{self.student['student_id']}/history"
        history_response = self.client.get(history_url, headers=self.headers)
        self.assertEqual(history_response.status_code, 200, history_response.text)
        history = history_response.json()["items"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["change_type"], "created")
        self.assertIsNone(history[0]["previous_score"])
        self.assertEqual(history[0]["new_score"], "12.5")
        self.assertEqual(history[1]["change_type"], "updated")
        self.assertEqual(history[1]["previous_score"], "12.5")
        self.assertEqual(history[1]["new_score"], "14")
        foreign = self.client.get(history_url, headers={"X-Organization-ID": "org-b"})
        self.assertEqual(foreign.status_code, 404)

    def test_result_score_cannot_exceed_maximum(self):
        assessment = self.create_assessment().json()
        response = self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers=self.headers, json={"student_id": self.student["student_id"], "score": "20.001"})
        self.assertEqual(response.status_code, 422)

    def test_cannot_publish_empty_assessment(self):
        assessment = self.create_assessment().json()
        response = self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/publish", headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_assessment_is_tenant_scoped(self):
        assessment = self.create_assessment().json()
        response = self.client.get(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(response.status_code, 404)

    def test_report_card_aggregates_only_published_results(self):
        section, _ = self._section_with_student()
        first = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "Math", "title": "Quiz", "term": "Term 1", "max_score": "20"
        }).json()
        second = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "Science", "title": "Test", "term": "Term 1", "max_score": "10"
        }).json()
        draft = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "English", "title": "Draft", "term": "Term 1", "max_score": "10"
        }).json()
        self.client.post(f"/api/v1/academics/assessments/{first['assessment_id']}/results", headers=self.headers, json={"student_id": self.student["student_id"], "score": "18"})
        self.client.post(f"/api/v1/academics/assessments/{second['assessment_id']}/results", headers=self.headers, json={"student_id": self.student["student_id"], "score": "7.5"})
        self.client.post(f"/api/v1/academics/assessments/{first['assessment_id']}/publish", headers=self.headers)
        self.client.post(f"/api/v1/academics/assessments/{second['assessment_id']}/publish", headers=self.headers)
        response = self.client.get(f"/api/v1/academics/reports/students/{self.student['student_id']}?section_id={section['section_id']}&term=Term%201", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["summary"]["published_assessment_count"], 2)
        self.assertEqual(report["summary"]["scored_assessment_count"], 2)
        self.assertEqual(report["summary"]["total_score"], "25.5")
        self.assertEqual(report["summary"]["total_max_score"], "30")
        self.assertEqual(report["summary"]["percentage"], "85.00")
        self.assertNotIn(draft["assessment_id"], [item["assessment_id"] for item in report["assessments"]])

    def test_report_card_missing_scores_are_not_zero(self):
        section, _ = self._section_with_student()
        assessment = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "Math", "title": "Quiz", "term": "Term 1", "max_score": "20"
        }).json()
        other = self.client.post("/api/v1/students", headers=self.headers, json={"given_name": "Bekele", "family_name": "Student", "branch_id": "branch-1"}).json()
        self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={"student_id": other["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"})
        self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers=self.headers, json={"student_id": self.student["student_id"], "score": "15"})
        self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/publish", headers=self.headers)
        response = self.client.get(f"/api/v1/academics/reports/students/{other['student_id']}?section_id={section['section_id']}&term=Term%201", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["summary"]["missing_score_count"], 1)
        self.assertIsNone(report["summary"]["percentage"])
        self.assertIsNone(report["assessments"][0]["score"])

    def test_report_card_is_tenant_and_enrollment_scoped(self):
        section, outsider = self._section_with_student(second_student=True)
        response = self.client.get(f"/api/v1/academics/reports/students/{outsider['student_id']}?section_id={section['section_id']}&term=Term%201", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        foreign = self.client.get(f"/api/v1/academics/reports/students/{self.student['student_id']}?section_id={section['section_id']}&term=Term%201", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(foreign.status_code, 404)

    def _section_with_student(self, second_student=False):
        year = self.client.post("/api/v1/classrooms/academic-years", headers=self.headers, json={
            "name": "2026/2027", "start_date": "2026-09-01", "end_date": "2027-06-30"
        }).json()
        level = self.client.post("/api/v1/classrooms/class-levels", headers=self.headers, json={
            "name": "Grade 1", "sort_order": 1
        }).json()
        section = self.client.post("/api/v1/classrooms/sections", headers=self.headers, json={
            "branch_id": "branch-1", "year_id": year["year_id"], "level_id": level["level_id"], "name": "A"
        }).json()
        enrollment = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": self.student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        })
        self.assertEqual(enrollment.status_code, 201, enrollment.text)
        outsider = None
        if second_student:
            outsider = self.client.post("/api/v1/students", headers=self.headers, json={
                "given_name": "Outside", "family_name": "Student", "branch_id": "branch-1"
            }).json()
        return section, outsider

    def test_section_assessment_lists_only_enrolled_students(self):
        section, outsider = self._section_with_student(second_student=True)
        assessment = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "Math", "title": "Quiz", "term": "Term 1", "max_score": "20"
        })
        self.assertEqual(assessment.status_code, 201, assessment.text)
        students = self.client.get(f"/api/v1/academics/students?branch_id=branch-1&section_id={section['section_id']}", headers=self.headers).json()["items"]
        self.assertEqual([s["student_id"] for s in students], [self.student["student_id"]])
        self.assertNotIn(outsider["student_id"], [s["student_id"] for s in students])

    def test_section_assessment_rejects_unenrolled_student_result(self):
        section, outsider = self._section_with_student(second_student=True)
        assessment = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "Math", "title": "Quiz", "term": "Term 1", "max_score": "20"
        }).json()
        response = self.client.post(f"/api/v1/academics/assessments/{assessment['assessment_id']}/results", headers=self.headers, json={
            "student_id": outsider["student_id"], "score": "12"
        })
        self.assertEqual(response.status_code, 422, response.text)

    def test_assessment_section_must_match_branch_and_tenant(self):
        section, _ = self._section_with_student()
        mismatch = self.client.post("/api/v1/academics/assessments", headers=self.headers, json={
            "branch_id": "branch-2", "section_id": section["section_id"], "subject": "Math", "title": "Quiz", "term": "Term 1", "max_score": "20"
        })
        self.assertEqual(mismatch.status_code, 422)
        foreign = self.client.post("/api/v1/academics/assessments", headers={"X-Organization-ID": "org-b"}, json={
            "branch_id": "branch-1", "section_id": section["section_id"], "subject": "Math", "title": "Quiz", "term": "Term 1", "max_score": "20"
        })
        self.assertEqual(foreign.status_code, 404)

class ClassroomStructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {"SCHOOL_DEV_DB_PATH": str(Path(self.tmp.name) / "classrooms.sqlite3")})
        self.env_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.headers = {"X-Organization-ID": "org-a"}
        self.student = self.client.post("/api/v1/students", headers=self.headers, json={
            "given_name": "Aster", "family_name": "Student", "branch_id": "branch-1"
        }).json()
        self.year = self.client.post("/api/v1/classrooms/academic-years", headers=self.headers, json={
            "name": "2026/2027", "start_date": "2026-09-01", "end_date": "2027-06-30"
        }).json()
        self.level = self.client.post("/api/v1/classrooms/class-levels", headers=self.headers, json={
            "name": "Grade 1", "sort_order": 1
        }).json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def create_section(self, capacity=None, branch_id="branch-1"):
        payload = {"branch_id": branch_id, "year_id": self.year["year_id"], "level_id": self.level["level_id"], "name": "A"}
        if capacity is not None:
            payload["capacity"] = capacity
        return self.client.post("/api/v1/classrooms/sections", headers=self.headers, json=payload)

    def test_create_year_level_section_and_enrollment(self):
        section_response = self.create_section(capacity=20)
        self.assertEqual(section_response.status_code, 201, section_response.text)
        section = section_response.json()
        self.assertEqual(section["academic_year"], "2026/2027")
        self.assertEqual(section["class_level"], "Grade 1")
        enrollment = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": self.student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        })
        self.assertEqual(enrollment.status_code, 201, enrollment.text)
        self.assertEqual(enrollment.json()["status"], "active")
        listed = self.client.get("/api/v1/classrooms/enrollments", headers=self.headers)
        self.assertEqual(len(listed.json()["items"]), 1)

    def test_one_active_enrollment_per_student(self):
        first = self.create_section().json()
        second = self.client.post("/api/v1/classrooms/sections", headers=self.headers, json={
            "branch_id": "branch-1", "year_id": self.year["year_id"], "level_id": self.level["level_id"], "name": "B"
        }).json()
        body = {"student_id": self.student["student_id"], "section_id": first["section_id"], "enrolled_on": "2026-09-01"}
        self.assertEqual(self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json=body).status_code, 201)
        body["section_id"] = second["section_id"]
        duplicate = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json=body)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

    def test_student_and_section_must_match_branch(self):
        section = self.create_section(branch_id="branch-2").json()
        response = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": self.student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        })
        self.assertEqual(response.status_code, 422)

    def test_section_capacity_is_enforced(self):
        section = self.create_section(capacity=1).json()
        self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": self.student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        })
        second_student = self.client.post("/api/v1/students", headers=self.headers, json={
            "given_name": "Bekele", "family_name": "Student", "branch_id": "branch-1"
        }).json()
        response = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": second_student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        })
        self.assertEqual(response.status_code, 409)

    def test_academic_year_dates_and_tenant_scope(self):
        invalid = self.client.post("/api/v1/classrooms/academic-years", headers=self.headers, json={
            "name": "Invalid", "start_date": "2027-06-30", "end_date": "2026-09-01"
        })
        self.assertEqual(invalid.status_code, 422)
        foreign = self.client.get("/api/v1/classrooms/academic-years", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(foreign.json()["items"], [])

    def test_section_roster_contains_only_active_enrolled_students(self):
        section = self.create_section().json()
        response = self.client.get(f"/api/v1/classrooms/sections/{section['section_id']}/students", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"], [])
        enrollment = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": self.student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        })
        self.assertEqual(enrollment.status_code, 201, enrollment.text)
        roster = self.client.get(f"/api/v1/classrooms/sections/{section['section_id']}/students", headers=self.headers)
        self.assertEqual(roster.json()["total"], 1)
        self.assertEqual(roster.json()["items"][0]["student_id"], self.student["student_id"])

    def test_section_attendance_only_accepts_currently_enrolled_students_atomically(self):
        section = self.create_section().json()
        enrolled = self.client.post("/api/v1/classrooms/enrollments", headers=self.headers, json={
            "student_id": self.student["student_id"], "section_id": section["section_id"], "enrolled_on": "2026-09-01"
        }).json()
        outsider = self.client.post("/api/v1/students", headers=self.headers, json={
            "given_name": "Bekele", "family_name": "Outside", "branch_id": "branch-1"
        }).json()
        url = f"/api/v1/attendance/sections/{section['section_id']}/bulk"
        rejected = self.client.post(url, headers=self.headers, json={
            "attendance_date": "2026-10-19", "records": [
                {"student_id": enrolled["student_id"], "status": "present"},
                {"student_id": outsider["student_id"], "status": "absent"},
            ]
        })
        self.assertEqual(rejected.status_code, 404, rejected.text)
        self.assertEqual(self.client.get("/api/v1/attendance?attendance_date=2026-10-19", headers=self.headers).json()["total"], 0)
        accepted = self.client.post(url, headers=self.headers, json={
            "attendance_date": "2026-10-19", "records": [{"student_id": enrolled["student_id"], "status": "present"}]
        })
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertEqual(accepted.json()["created"], 1)
        self.assertEqual(accepted.json()["items"][0]["branch_id"], "branch-1")

    def test_section_roster_is_tenant_scoped(self):
        section = self.create_section().json()
        response = self.client.get(f"/api/v1/classrooms/sections/{section['section_id']}/students", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(response.status_code, 404)

    def test_class_levels_are_tenant_scoped_and_duplicate_names_conflict(self):
        duplicate = self.client.post("/api/v1/classrooms/class-levels", headers=self.headers, json={"name": "Grade 1"})
        self.assertEqual(duplicate.status_code, 409)
        other = self.client.get("/api/v1/classrooms/class-levels", headers={"X-Organization-ID": "org-b"})
        self.assertEqual(other.json()["items"], [])


class FinancePrototypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "finance.sqlite3")
        self.env_patch = patch.dict(os.environ, {"SCHOOL_DEV_DB_PATH": self.db_path})
        self.env_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.headers = {"X-Organization-ID": "finance-org"}
        self.student = self.client.post("/api/v1/students", headers=self.headers, json={
            "given_name": "Mimi", "family_name": "Abebe", "branch_id": "branch-1"
        }).json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def create_bill(self, amount=10000, currency="ETB"):
        response = self.client.post("/api/v1/finance/bills", headers=self.headers, json={
            "student_id": self.student["student_id"], "description": "Tuition", "amount_minor": amount, "currency": currency
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_foreign_keys_are_enabled_on_every_new_database_connection(self):
        first = student_store.connect()
        second = student_store.connect()
        try:
            self.assertEqual(first.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(second.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            first.close()
            second.close()

    def test_composite_foreign_key_rejects_cross_organization_fee_bill(self):
        conn = student_store.connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO prototype_fee_bills "
                    "(bill_id, organization_id, student_id, description, amount_minor, currency) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("cross-tenant-bill", "another-org", self.student["student_id"], "Tuition", 10000, "ETB"),
                )
            conn.rollback()
        finally:
            conn.close()

    def test_bill_idempotency_replays_same_bill_and_rejects_payload_mismatch(self):
        headers = {**self.headers, "Idempotency-Key": "cashier-device:bill-001"}
        payload = {"student_id": self.student["student_id"], "description": "Tuition", "amount_minor": 12500, "currency": "ETB"}
        first = self.client.post("/api/v1/finance/bills", headers=headers, json=payload)
        replay = self.client.post("/api/v1/finance/bills", headers=headers, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(first.json()["bill_id"], replay.json()["bill_id"])
        self.assertEqual(len(self.client.get("/api/v1/finance/bills", headers=self.headers).json()["items"]), 1)
        changed = {**payload, "amount_minor": 13000}
        conflict = self.client.post("/api/v1/finance/bills", headers=headers, json=changed)
        self.assertEqual(conflict.status_code, 409)

    def test_concurrent_bill_retries_with_same_key_create_only_one_bill(self):
        headers = {**self.headers, "Idempotency-Key": "cashier-device:bill-concurrent"}
        payload = {"student_id": self.student["student_id"], "description": "Concurrent tuition", "amount_minor": 24500, "currency": "ETB"}

        def submit(_):
            return self.client.post("/api/v1/finance/bills", headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, range(6)))

        self.assertTrue(all(response.status_code == 201 for response in responses), [response.text for response in responses])
        bill_ids = {response.json()["bill_id"] for response in responses}
        self.assertEqual(len(bill_ids), 1)
        bills = self.client.get("/api/v1/finance/bills", headers=self.headers).json()["items"]
        self.assertEqual(len(bills), 1)
        account = self.client.get(f"/api/v1/finance/students/{self.student['student_id']}/account", headers=self.headers).json()
        self.assertEqual(account["balances"], [{"currency": "ETB", "balance_minor": 24500}])

    def test_idempotency_key_validation_is_consistent_across_finance_writes(self):
        student = self.student["student_id"]
        invalid_keys = ["   ", "k" * 129]
        bill_payload = {"student_id": student, "description": "Validation bill", "amount_minor": 1000, "currency": "ETB"}
        payment_payload = {"student_id": student, "amount_minor": 1000, "currency": "ETB", "payment_method": "cash", "allocations": []}
        cash_response = self.client.post("/api/v1/finance/ledger/accounts", headers=self.headers, json={"code": "1000", "name": "Cash", "account_type": "asset", "currency": "ETB"})
        revenue_response = self.client.post("/api/v1/finance/ledger/accounts", headers=self.headers, json={"code": "4000", "name": "Validation revenue", "account_type": "revenue", "currency": "ETB"})
        self.assertEqual(cash_response.status_code, 201, cash_response.text)
        self.assertEqual(revenue_response.status_code, 201, revenue_response.text)
        cash, revenue = cash_response.json(), revenue_response.json()
        journal_payload = {"description": "Validation journal", "currency": "ETB", "lines": [
            {"account_id": cash["account_id"], "debit_minor": 1000},
            {"account_id": revenue["account_id"], "credit_minor": 1000},
        ]}
        for key in invalid_keys:
            with self.subTest(key_length=len(key), endpoint="bill"):
                response = self.client.post("/api/v1/finance/bills", headers={**self.headers, "Idempotency-Key": key}, json=bill_payload)
                self.assertEqual(response.status_code, 422)
            with self.subTest(key_length=len(key), endpoint="payment"):
                response = self.client.post("/api/v1/finance/payments", headers={**self.headers, "Idempotency-Key": key}, json=payment_payload)
                self.assertEqual(response.status_code, 422)
            with self.subTest(key_length=len(key), endpoint="journal"):
                response = self.client.post("/api/v1/finance/ledger/journals", headers={**self.headers, "Idempotency-Key": key}, json=journal_payload)
                self.assertEqual(response.status_code, 422)

    def test_payment_idempotency_replays_same_payment(self):
        bill = self.create_bill(10000)
        headers = {**self.headers, "Idempotency-Key": "cashier-device:payment-001"}
        payload = {"student_id": self.student["student_id"], "amount_minor": 5000, "currency": "ETB", "payment_method": "cash", "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 5000}]}
        first = self.client.post("/api/v1/finance/payments", headers=headers, json=payload)
        replay = self.client.post("/api/v1/finance/payments", headers=headers, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(first.json()["payment_id"], replay.json()["payment_id"])
        self.assertEqual(len(self.client.get("/api/v1/finance/payments", headers=self.headers).json()["items"]), 1)
        conflict = self.client.post("/api/v1/finance/payments", headers=headers, json={**payload, "amount_minor": 6000})
        self.assertEqual(conflict.status_code, 409)

    def test_concurrent_payment_retries_with_same_key_create_only_one_payment(self):
        bill = self.create_bill(30000)
        headers = {**self.headers, "Idempotency-Key": "cashier-device:payment-concurrent"}
        payload = {"student_id": self.student["student_id"], "amount_minor": 7000, "currency": "ETB", "payment_method": "cash", "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 7000}]}

        def submit(_):
            return self.client.post("/api/v1/finance/payments", headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, range(6)))

        self.assertTrue(all(response.status_code == 201 for response in responses), [response.text for response in responses])
        payment_ids = {response.json()["payment_id"] for response in responses}
        self.assertEqual(len(payment_ids), 1)
        payments = self.client.get("/api/v1/finance/payments", headers=self.headers).json()["items"]
        self.assertEqual(len(payments), 1)
        self.assertEqual(sum(item["amount_minor"] for item in payments), 7000)

    def test_bill_creates_journal_charge_in_integer_minor_units(self):
        bill = self.create_bill(12550)
        self.assertEqual(bill["amount_minor"], 12550)
        account = self.client.get(f"/api/v1/finance/students/{self.student['student_id']}/account", headers=self.headers).json()
        self.assertEqual(account["balances"], [{"currency": "ETB", "balance_minor": 12550}])
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertTrue(balance["is_balanced"])
        self.assertEqual(balance["total_debit_minor"], 12550)
        self.assertEqual(balance["total_credit_minor"], 12550)
        self.assertEqual({row["code"] for row in balance["items"]}, {"1000", "1100", "2100", "4000"})

    def test_payment_is_provisional_until_reconciled_then_posts_once(self):
        bill = self.create_bill(10000)
        payment = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 7000,
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 7000}]
        })
        self.assertEqual(payment.status_code, 201, payment.text)
        body = payment.json()
        self.assertEqual(body["status"], "pending_reconciliation")
        self.assertIsNone(body["official_receipt_number"])
        before = self.client.get(f"/api/v1/finance/students/{self.student['student_id']}/account", headers=self.headers).json()
        self.assertEqual(before["balances"][0]["balance_minor"], 10000)
        reconcile_url = f"/api/v1/finance/payments/{body['payment_id']}/reconcile"
        first = self.client.post(reconcile_url, headers=self.headers)
        second = self.client.post(reconcile_url, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        bills = self.client.get("/api/v1/finance/bills", headers=self.headers).json()["items"]
        self.assertEqual(bills[0]["outstanding_minor"], 3000)
        account = self.client.get(f"/api/v1/finance/students/{self.student['student_id']}/account", headers=self.headers).json()
        self.assertEqual(account["balances"][0]["balance_minor"], 3000)
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertTrue(balance["is_balanced"])
        self.assertEqual(balance["total_debit_minor"], 17000)
        self.assertEqual(balance["total_credit_minor"], 17000)
        # A repeated reconcile must not duplicate the automatic general-ledger posting.
        self.client.post(reconcile_url, headers=self.headers)
        repeated = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertEqual(repeated["total_debit_minor"], 17000)
        self.assertEqual(repeated["total_credit_minor"], 17000)

    def test_overpayment_becomes_student_credit(self):
        bill = self.create_bill(4000)
        payment = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 6000,
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 4000}]
        }).json()
        self.client.post(f"/api/v1/finance/payments/{payment['payment_id']}/reconcile", headers=self.headers)
        account = self.client.get(f"/api/v1/finance/students/{self.student['student_id']}/account", headers=self.headers).json()
        self.assertEqual(account["balances"][0]["balance_minor"], -2000)
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertTrue(balance["is_balanced"])
        by_code = {row["code"]: row for row in balance["items"]}
        self.assertEqual(by_code["2100"]["credit_minor"], 2000)
        self.assertEqual(balance["total_debit_minor"], balance["total_credit_minor"])

    def test_payment_allocation_cannot_exceed_bill_remaining_amount(self):
        bill = self.create_bill(5000)
        response = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 6000,
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 6000}]
        })
        self.assertEqual(response.status_code, 409, response.text)

    def test_currency_mismatch_is_rejected(self):
        bill = self.create_bill(5000, "ETB")
        response = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 1000, "currency": "USD",
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 1000}]
        })
        self.assertEqual(response.status_code, 409)

    def test_finance_audit_events_are_tenant_scoped_and_append_only(self):
        bill = self.create_bill(3150)
        response = self.client.get("/api/v1/finance/audit-events?entity_type=fee_bill", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 1)
        event = body["items"][0]
        self.assertEqual(event["event_type"], "finance.bill.created")
        self.assertEqual(event["entity_id"], bill["bill_id"])
        self.assertEqual(event["details"], {"amount_minor": 3150, "currency": "ETB"})
        self.assertIsNone(event["actor_id"], "Prototype must not invent an authenticated actor")
        foreign = self.client.get("/api/v1/finance/audit-events", headers={"X-Organization-ID": "other-org"})
        self.assertEqual(foreign.json()["total"], 0)

        import sqlite3
        from app.services.student_store import database_path
        conn = sqlite3.connect(database_path())
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE prototype_audit_events SET event_type='tampered'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM prototype_audit_events")
        finally:
            conn.close()

    def test_finance_business_write_rolls_back_if_audit_insert_fails(self):
        import sqlite3
        from app.services.student_store import database_path, create_fee_bill
        conn = sqlite3.connect(database_path())
        try:
            conn.execute("CREATE TRIGGER test_reject_audit BEFORE INSERT ON prototype_audit_events BEGIN SELECT RAISE(ABORT, 'simulated audit failure'); END")
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(sqlite3.IntegrityError):
            create_fee_bill("finance-org", {
                "student_id": self.student["student_id"], "description": "Atomicity test",
                "amount_minor": 777, "currency": "ETB", "due_date": None,
            })

        conn = sqlite3.connect(database_path())
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM prototype_fee_bills WHERE description='Atomicity test'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM prototype_audit_events WHERE event_type='finance.bill.created'").fetchone()[0], 0)
        finally:
            conn.close()

    def test_repeated_payment_reconciliation_does_not_duplicate_audit_event(self):
        bill = self.create_bill(5000)
        payment = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 2000,
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 2000}]
        }).json()
        path = f"/api/v1/finance/payments/{payment['payment_id']}/reconcile"
        first = self.client.post(path, headers=self.headers)
        second = self.client.post(path, headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json().get("idempotent_replay", False))
        self.assertTrue(second.json().get("idempotent_replay", False))
        events = self.client.get("/api/v1/finance/audit-events?event_type=finance.payment.reconciled", headers=self.headers).json()
        self.assertEqual(events["total"], 1)

    def test_student_statement_has_running_balance_and_pagination(self):
        bill = self.create_bill(5000)
        payment = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 2000,
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 2000}]
        }).json()
        self.client.post(f"/api/v1/finance/payments/{payment['payment_id']}/reconcile", headers=self.headers)

        url = f"/api/v1/finance/students/{self.student['student_id']}/statement"
        response = self.client.get(url, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 2)
        by_type = {entry["entry_type"]: entry for entry in body["items"]}
        self.assertEqual(by_type["fee_charge"]["running_balance_minor"], 5000)
        self.assertEqual(by_type["payment_allocation"]["running_balance_minor"], 3000)
        self.assertEqual(by_type["payment_allocation"]["payment_status"], "reconciled")
        self.assertEqual(by_type["payment_allocation"]["bill_id"], bill["bill_id"])

        page = self.client.get(url + "?limit=1&offset=1", headers=self.headers)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["total"], 2)
        self.assertEqual(len(page.json()["items"]), 1)
        self.assertEqual(page.json()["items"][0]["running_balance_minor"], 5000)

    def test_student_statement_is_tenant_scoped(self):
        url = f"/api/v1/finance/students/{self.student['student_id']}/statement"
        response = self.client.get(url, headers={"X-Organization-ID": "other-org"})
        self.assertEqual(response.status_code, 404)

    def test_student_account_journal_rejects_updates(self):
        self.create_bill(3000)
        import sqlite3
        from app.services.student_store import database_path
        conn = sqlite3.connect(database_path())
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE prototype_student_account_entries SET amount_minor=0")
        finally:
            conn.close()

    def test_foreign_organization_cannot_read_or_reconcile_payment(self):
        bill = self.create_bill(5000)
        payment = self.client.post("/api/v1/finance/payments", headers=self.headers, json={
            "student_id": self.student["student_id"], "amount_minor": 1000,
            "allocations": [{"bill_id": bill["bill_id"], "amount_minor": 1000}]
        }).json()
        foreign = {"X-Organization-ID": "other-org"}
        self.assertEqual(self.client.get("/api/v1/finance/bills", headers=foreign).json()["items"], [])
        self.assertEqual(self.client.post(f"/api/v1/finance/payments/{payment['payment_id']}/reconcile", headers=foreign).status_code, 404)

class GeneralLedgerPrototypeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "ledger.sqlite3")
        self.env_patch = patch.dict(os.environ, {"SCHOOL_DEV_DB_PATH": self.db_path})
        self.env_patch.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.headers = {"X-Organization-ID": "ledger-org"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def create_account(self, code, name, account_type):
        response = self.client.post("/api/v1/finance/ledger/accounts", headers=self.headers, json={
            "code": code, "name": name, "account_type": account_type, "currency": "ETB"
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_posted_journal_is_balanced_and_appears_in_trial_balance(self):
        cash = self.create_account("1000", "Cash", "asset")
        tuition = self.create_account("4000", "Tuition revenue", "revenue")
        response = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
            "description": "Recognize tuition receipt", "currency": "ETB", "lines": [
                {"account_id": cash["account_id"], "debit_minor": 25000, "credit_minor": 0},
                {"account_id": tuition["account_id"], "debit_minor": 0, "credit_minor": 25000}
            ]
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["total_debit_minor"], 25000)
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertTrue(balance["is_balanced"])
        self.assertEqual(balance["total_debit_minor"], balance["total_credit_minor"])
        self.assertEqual(len(balance["items"]), 2)

    def test_unbalanced_journal_is_rejected_before_posting(self):
        cash = self.create_account("1000", "Cash", "asset")
        tuition = self.create_account("4000", "Tuition revenue", "revenue")
        response = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
            "description": "Invalid journal", "lines": [
                {"account_id": cash["account_id"], "debit_minor": 25000},
                {"account_id": tuition["account_id"], "credit_minor": 24000}
            ]
        })
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()["total_debit_minor"], 0)

    def test_journal_cannot_use_account_from_another_organization(self):
        cash = self.create_account("1000", "Cash", "asset")
        other = {"X-Organization-ID": "other-org"}
        response = self.client.post("/api/v1/finance/ledger/journals", headers=other, json={
            "description": "Cross-tenant attempt", "lines": [
                {"account_id": cash["account_id"], "debit_minor": 1000},
                {"account_id": "some-account", "credit_minor": 1000}
            ]
        })
        self.assertEqual(response.status_code, 404)

    def test_journal_browse_returns_lines_and_supports_pagination(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        for amount, description in [(1000, "First receipt"), (2000, "Second receipt")]:
            response = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
                "description": description, "currency": "ETB", "lines": [
                    {"account_id": cash["account_id"], "debit_minor": amount},
                    {"account_id": revenue["account_id"], "credit_minor": amount},
                ]
            })
            self.assertEqual(response.status_code, 201, response.text)
        page = self.client.get("/api/v1/finance/ledger/journals?limit=1&offset=0", headers=self.headers)
        self.assertEqual(page.status_code, 200, page.text)
        body = page.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(len(body["items"][0]["lines"]), 2)
        self.assertEqual(body["items"][0]["total_debit_minor"], 2000)
        filtered = self.client.get(f"/api/v1/finance/ledger/journals?account_id={cash['account_id']}", headers=self.headers).json()
        self.assertEqual(filtered["total"], 2)

    def test_account_activity_has_running_balance_and_is_tenant_scoped(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        for amount, description in [(1000, "Receipt one"), (2500, "Receipt two")]:
            response = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
                "description": description, "currency": "ETB", "lines": [
                    {"account_id": cash["account_id"], "debit_minor": amount},
                    {"account_id": revenue["account_id"], "credit_minor": amount},
                ]
            })
            self.assertEqual(response.status_code, 201, response.text)
        activity = self.client.get(f"/api/v1/finance/ledger/accounts/{cash['account_id']}/activity", headers=self.headers).json()
        self.assertEqual(activity["total_debit_minor"], 3500)
        self.assertEqual(activity["closing_net_debit_minor"], 3500)
        self.assertEqual([x["running_net_debit_minor"] for x in activity["items"]], [1000, 3500])
        paged = self.client.get(f"/api/v1/finance/ledger/accounts/{cash['account_id']}/activity?limit=1&offset=1", headers=self.headers).json()
        self.assertEqual(len(paged["items"]), 1)
        self.assertEqual(paged["items"][0]["running_net_debit_minor"], 3500)
        foreign = self.client.get(f"/api/v1/finance/ledger/accounts/{cash['account_id']}/activity", headers={"X-Organization-ID": "another-org"})
        self.assertEqual(foreign.status_code, 404)

    def test_reversal_posts_exact_opposite_lines_and_preserves_original(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        original_response = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
            "description": "Incorrect tuition posting", "currency": "ETB", "lines": [
                {"account_id": cash["account_id"], "debit_minor": 4200},
                {"account_id": revenue["account_id"], "credit_minor": 4200},
            ]
        })
        self.assertEqual(original_response.status_code, 201, original_response.text)
        original = original_response.json()
        reversed_response = self.client.post(f"/api/v1/finance/ledger/journals/{original['journal_id']}/reverse", headers=self.headers, json={"reason": "Wrong student account"})
        self.assertEqual(reversed_response.status_code, 201, reversed_response.text)
        reversal = reversed_response.json()
        self.assertEqual(reversal["reversal_of_id"], original["journal_id"])
        self.assertEqual(reversal["total_debit_minor"], 4200)
        self.assertEqual(reversal["total_credit_minor"], 4200)
        self.assertEqual(reversal["lines"][0]["debit_minor"], 0)
        self.assertEqual(reversal["lines"][0]["credit_minor"], 4200)
        journals = self.client.get("/api/v1/finance/ledger/journals", headers=self.headers).json()
        self.assertEqual(journals["total"], 2)
        by_id = {entry["journal_id"]: entry for entry in journals["items"]}
        self.assertEqual(by_id[original["journal_id"]]["reversed_by_id"], reversal["journal_id"])
        self.assertIsNone(by_id[original["journal_id"]]["reversal_of_id"])
        self.assertEqual(by_id[reversal["journal_id"]]["reversal_of_id"], original["journal_id"])
        self.assertIsNone(by_id[reversal["journal_id"]]["reversed_by_id"])
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertTrue(balance["is_balanced"])
        self.assertEqual(balance["total_debit_minor"], balance["total_credit_minor"])

    def test_journal_cannot_be_reversed_twice_or_reverse_a_reversal(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        original = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
            "description": "Posting", "lines": [
                {"account_id": cash["account_id"], "debit_minor": 900},
                {"account_id": revenue["account_id"], "credit_minor": 900},
            ]
        }).json()
        path = f"/api/v1/finance/ledger/journals/{original['journal_id']}/reverse"
        first = self.client.post(path, headers=self.headers, json={"reason": "Correction"})
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(path, headers=self.headers, json={"reason": "Another correction"})
        self.assertEqual(second.status_code, 409)
        reverse_path = f"/api/v1/finance/ledger/journals/{first.json()['journal_id']}/reverse"
        reverse_reverse = self.client.post(reverse_path, headers=self.headers, json={"reason": "Try reverse reversal"})
        self.assertEqual(reverse_reverse.status_code, 409)

    def test_journal_reversal_is_tenant_scoped(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        original = self.client.post("/api/v1/finance/ledger/journals", headers=self.headers, json={
            "description": "Tenant journal", "lines": [
                {"account_id": cash["account_id"], "debit_minor": 700},
                {"account_id": revenue["account_id"], "credit_minor": 700},
            ]
        }).json()
        response = self.client.post(f"/api/v1/finance/ledger/journals/{original['journal_id']}/reverse", headers={"X-Organization-ID": "other-org"}, json={"reason": "Cross-tenant attempt"})
        self.assertEqual(response.status_code, 404)

    def test_journal_pagination_bounds_are_validated(self):
        response = self.client.get("/api/v1/finance/ledger/journals?limit=201", headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_duplicate_account_code_is_rejected(self):
        self.create_account("1000", "Cash", "asset")
        response = self.client.post("/api/v1/finance/ledger/accounts", headers=self.headers, json={
            "code": "1000", "name": "Cash duplicate", "account_type": "asset"
        })
        self.assertEqual(response.status_code, 409)

    def test_idempotency_key_replay_returns_same_journal_without_duplicate_posting(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        headers = {**self.headers, "Idempotency-Key": "device-7:journal-001"}
        payload = {"description": "Offline retry receipt", "currency": "ETB", "lines": [
            {"account_id": cash["account_id"], "debit_minor": 12345},
            {"account_id": revenue["account_id"], "credit_minor": 12345},
        ]}
        first = self.client.post("/api/v1/finance/ledger/journals", headers=headers, json=payload)
        second = self.client.post("/api/v1/finance/ledger/journals", headers=headers, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(first.json()["journal_id"], second.json()["journal_id"])
        self.assertFalse(first.json()["idempotent_replay"])
        self.assertTrue(second.json()["idempotent_replay"])
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertEqual(balance["total_debit_minor"], 12345)
        self.assertEqual(balance["total_credit_minor"], 12345)

    def test_concurrent_journal_retries_with_same_key_post_only_once(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        headers = {**self.headers, "Idempotency-Key": "device-7:journal-concurrent"}
        payload = {"description": "Concurrent journal retry", "currency": "ETB", "lines": [
            {"account_id": cash["account_id"], "debit_minor": 8800},
            {"account_id": revenue["account_id"], "credit_minor": 8800},
        ]}

        def submit(_):
            return self.client.post("/api/v1/finance/ledger/journals", headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(submit, range(6)))

        self.assertTrue(all(response.status_code == 201 for response in responses), [response.text for response in responses])
        journal_ids = {response.json()["journal_id"] for response in responses}
        self.assertEqual(len(journal_ids), 1)
        self.assertEqual(sum(response.json()["idempotent_replay"] for response in responses), 5)
        journals = self.client.get("/api/v1/finance/ledger/journals", headers=self.headers).json()["items"]
        self.assertEqual(len(journals), 1)
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertEqual(balance["total_debit_minor"], 8800)
        self.assertEqual(balance["total_credit_minor"], 8800)

    def test_idempotency_key_cannot_be_reused_for_different_payload(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        headers = {**self.headers, "Idempotency-Key": "device-7:journal-002"}
        def payload(amount, description):
            return {"description": description, "currency": "ETB", "lines": [
                {"account_id": cash["account_id"], "debit_minor": amount},
                {"account_id": revenue["account_id"], "credit_minor": amount},
            ]}
        first = self.client.post("/api/v1/finance/ledger/journals", headers=headers, json=payload(1000, "First"))
        conflict = self.client.post("/api/v1/finance/ledger/journals", headers=headers, json=payload(2000, "Different"))
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(conflict.status_code, 409)
        balance = self.client.get("/api/v1/finance/ledger/trial-balance", headers=self.headers).json()
        self.assertEqual(balance["total_debit_minor"], 1000)

    def test_idempotency_keys_are_scoped_to_organization(self):
        cash = self.create_account("1000", "Cash", "asset")
        revenue = self.create_account("4000", "Tuition revenue", "revenue")
        payload = {"description": "Tenant scoped key", "currency": "ETB", "lines": [
            {"account_id": cash["account_id"], "debit_minor": 500},
            {"account_id": revenue["account_id"], "credit_minor": 500},
        ]}
        first = self.client.post("/api/v1/finance/ledger/journals", headers={**self.headers, "Idempotency-Key": "same-key"}, json=payload)
        second = self.client.post("/api/v1/finance/ledger/journals", headers={"X-Organization-ID": "another-org", "Idempotency-Key": "same-key"}, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 404)

class AuthenticationApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "auth-test.sqlite3")
        self.env_patch = patch.dict(os.environ, {
            "SCHOOL_DEV_DB_PATH": self.db_path,
            "SCHOOL_AUTH_SECRET": "test-only-secret-that-is-longer-than-thirty-two-bytes",
            "SCHOOL_BOOTSTRAP_TOKEN": "test-bootstrap-token-longer-than-thirty-two-bytes",
        })
        self.env_patch.start()
        from app.config import get_settings
        self.settings = get_settings()
        self.old_auth_required = self.settings.auth_required
        self.settings.auth_required = False
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.settings.auth_required = self.old_auth_required
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_bootstrap_login_me_and_admin_user_creation(self):
        bootstrap = self.client.post("/api/v1/auth/bootstrap-admin", headers={
            "X-Bootstrap-Token": os.environ["SCHOOL_BOOTSTRAP_TOKEN"]
        }, json={"organization_id": "org-auth", "email": "admin@example.com", "password": "Correct-Horse-Battery-9!"})
        self.assertEqual(bootstrap.status_code, 201, bootstrap.text)
        self.assertEqual(bootstrap.json()["user"]["role"], "organization_admin")
        closed = self.client.post("/api/v1/auth/bootstrap-admin", headers={
            "X-Bootstrap-Token": os.environ["SCHOOL_BOOTSTRAP_TOKEN"]
        }, json={"organization_id": "org-auth", "email": "other@example.com", "password": "Correct-Horse-Battery-9!"})
        self.assertEqual(closed.status_code, 409)
        login = self.client.post("/api/v1/auth/login", json={
            "organization_id": "org-auth", "email": "admin@example.com", "password": "Correct-Horse-Battery-9!"
        })
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["access_token"]
        me = self.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["organization_id"], "org-auth")
        created = self.client.post("/api/v1/auth/users", headers={"Authorization": f"Bearer {token}"}, json={
            "email": "teacher@example.com", "password": "Another-Strong-Password-3!", "role": "teacher"
        })
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["organization_id"], "org-auth")

    def test_authenticated_tenant_is_derived_from_token_and_conflicting_header_is_denied(self):
        from app.services import auth_service
        user = auth_service.create_user(
            "org-auth", "admin@example.com", "Correct-Horse-Battery-9!", "organization_admin"
        )
        token = auth_service.create_access_token(user)
        self.settings.auth_required = True

        # The verified tenant claim is authoritative; callers need not provide a tenant header.
        own = self.client.get("/api/v1/students", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.json()["total"], 0)

        wrong_tenant = self.client.get("/api/v1/students", headers={
            "Authorization": f"Bearer {token}", "X-Organization-ID": "other-org"
        })
        self.assertEqual(wrong_tenant.status_code, 403, wrong_tenant.text)

    def test_teacher_role_is_denied_finance_mutations(self):
        from app.services import auth_service
        user = auth_service.create_user(
            "org-auth", "teacher@example.com", "Correct-Horse-Battery-9!", "teacher"
        )
        token = auth_service.create_access_token(user)
        self.settings.auth_required = True
        response = self.client.post("/api/v1/finance/bills", headers={
            "Authorization": f"Bearer {token}"
        }, json={})
        self.assertEqual(response.status_code, 403, response.text)

    def test_api_responses_include_basic_security_headers_and_disable_caching(self):
        response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
        self.assertTrue(response.headers.get("X-Request-ID"))
        # API responses must not be cached; health probes outside /api/v1 are exempt.
        api_response = self.client.get("/api/v1/auth/me")
        self.assertEqual(api_response.headers.get("Cache-Control"), "no-store")

    def test_invalid_credentials_and_missing_token_are_rejected(self):
        from app.services import auth_service
        auth_service.create_user("org-auth", "admin@example.com", "Correct-Horse-Battery-9!", "organization_admin")
        bad = self.client.post("/api/v1/auth/login", json={
            "organization_id": "org-auth", "email": "admin@example.com", "password": "wrong-password"
        })
        self.assertEqual(bad.status_code, 401)
        missing = self.client.get("/api/v1/auth/me")
        self.assertEqual(missing.status_code, 401)

    def test_login_rate_limit_returns_429_after_ten_failed_attempts(self):
        from app.services import auth_service
        auth_service.create_user("org-auth", "admin@example.com", "Correct-Horse-Battery-9!", "organization_admin")
        payload = {"organization_id": "org-auth", "email": "admin@example.com", "password": "incorrect-password"}
        responses = [self.client.post("/api/v1/auth/login", json=payload) for _ in range(auth_service.LOGIN_FAILURE_LIMIT)]
        self.assertTrue(all(response.status_code == 401 for response in responses[:-1]))
        self.assertEqual(responses[-1].status_code, 429, responses[-1].text)
        self.assertGreater(int(responses[-1].headers.get("Retry-After", "0")), 0)
        blocked = self.client.post("/api/v1/auth/login", json={**payload, "password": "Correct-Horse-Battery-9!"})
        self.assertEqual(blocked.status_code, 429)

    def test_login_rate_limit_expires_and_starts_a_fresh_window(self):
        from app.services import auth_service
        start = 1_000_000
        for offset in range(auth_service.LOGIN_FAILURE_LIMIT):
            blocked_for = auth_service.record_login_failure("org-auth", "Admin@Example.com", now=start + offset)
        self.assertGreater(blocked_for, 0)
        self.assertGreater(
            auth_service.login_block_seconds("org-auth", "admin@example.com", now=start + 20),
            0,
        )
        self.assertEqual(
            auth_service.login_block_seconds(
                "org-auth", "admin@example.com",
                now=start + auth_service.LOGIN_FAILURE_WINDOW_SECONDS + 1,
            ),
            0,
        )
        # The expired record is removed; a new failure starts at count one, not eleven.
        self.assertEqual(
            auth_service.record_login_failure(
                "org-auth", "ADMIN@example.com",
                now=start + auth_service.LOGIN_FAILURE_WINDOW_SECONDS + 2,
            ),
            0,
        )

    def test_login_cooldown_is_bounded_if_system_clock_moves_backwards(self):
        from app.services import auth_service
        start = 2_000_000
        for offset in range(auth_service.LOGIN_FAILURE_LIMIT):
            auth_service.record_login_failure("org-auth", "admin@example.com", now=start + offset)
        self.assertEqual(
            auth_service.login_block_seconds("org-auth", "admin@example.com", now=start - 100),
            auth_service.LOGIN_FAILURE_WINDOW_SECONDS,
        )

    def test_successful_login_clears_prior_failures(self):
        from app.services import auth_service
        auth_service.create_user("org-auth", "admin@example.com", "Correct-Horse-Battery-9!", "organization_admin")
        auth_service.record_login_failure("org-auth", "admin@example.com")
        response = self.client.post("/api/v1/auth/login", json={
            "organization_id": "org-auth", "email": "admin@example.com", "password": "Correct-Horse-Battery-9!"
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(auth_service.login_block_seconds("org-auth", "admin@example.com"), 0)

    def test_auth_enforcement_protects_domain_routes_and_matches_tenant(self):
        from app.services import auth_service
        user = auth_service.create_user("org-auth", "admin@example.com", "Correct-Horse-Battery-9!", "organization_admin")
        token = auth_service.create_access_token(user)
        self.settings.auth_required = True
        unauthenticated = self.client.get("/api/v1/students", headers={"X-Organization-ID": "org-auth"})
        self.assertEqual(unauthenticated.status_code, 401)
        mismatch = self.client.get("/api/v1/students", headers={
            "Authorization": f"Bearer {token}", "X-Organization-ID": "other-org"
        })
        self.assertEqual(mismatch.status_code, 403)
        authenticated = self.client.get("/api/v1/students", headers={
            "Authorization": f"Bearer {token}", "X-Organization-ID": "org-auth"
        })
        self.assertEqual(authenticated.status_code, 200, authenticated.text)
        token_scoped = self.client.get("/api/v1/students", headers={
            "Authorization": f"Bearer {token}"
        })
        self.assertEqual(token_scoped.status_code, 200, token_scoped.text)

    def test_token_signature_and_expiry_are_checked(self):
        from app.services.auth_service import create_access_token, verify_access_token
        user = {"user_id": "u1", "organization_id": "org-auth", "role": "viewer"}
        token = create_access_token(user, secret=b"a-secret-long-enough-for-tests-123", now=1000)
        claims = verify_access_token(token, secret=b"a-secret-long-enough-for-tests-123", now=1001)
        self.assertEqual(claims["sub"], "u1")
        with self.assertRaises(ValueError):
            verify_access_token(token, secret=b"a-different-secret-long-enough-123", now=1001)
        with self.assertRaises(ValueError):
            verify_access_token(token, secret=b"a-secret-long-enough-for-tests-123", now=1000 + 15 * 60)

    def test_role_policy_denies_teacher_finance_access_and_viewer_writes(self):
        from app.services import auth_service
        teacher = auth_service.create_user("org-auth", "teacher@example.com", "Correct-Horse-Battery-9!", "teacher")
        viewer = auth_service.create_user("org-auth", "viewer@example.com", "Correct-Horse-Battery-9!", "viewer")
        self.settings.auth_required = True
        teacher_token = auth_service.create_access_token(teacher)
        finance_denied = self.client.get("/api/v1/finance/ledger/accounts", headers={
            "Authorization": f"Bearer {teacher_token}", "X-Organization-ID": "org-auth"
        })
        self.assertEqual(finance_denied.status_code, 403)
        attendance_allowed = self.client.get("/api/v1/attendance", headers={
            "Authorization": f"Bearer {teacher_token}", "X-Organization-ID": "org-auth"
        })
        self.assertNotEqual(attendance_allowed.status_code, 403)
        viewer_token = auth_service.create_access_token(viewer)
        branch_admin = auth_service.create_user("org-auth", "branch@example.com", "Correct-Horse-Battery-9!", "branch_admin")
        branch_token = auth_service.create_access_token(branch_admin)
        branch_denied = self.client.get("/api/v1/students", headers={
            "Authorization": f"Bearer {branch_token}", "X-Organization-ID": "org-auth"
        })
        self.assertEqual(branch_denied.status_code, 403)
        write_denied = self.client.post("/api/v1/students", headers={
            "Authorization": f"Bearer {viewer_token}", "X-Organization-ID": "org-auth"
        }, json={"given_name": "Mimi", "family_name": "Abebe", "branch_id": "b1"})
        self.assertEqual(write_denied.status_code, 403)

class AuthRolePolicyHardeningTests(unittest.TestCase):
    def test_role_policy_uses_conservative_route_allowlists(self):
        from app.services.auth_service import role_allows
        cases = [
            ("cashier", "POST", "/api/v1/finance/payments", True),
            ("cashier", "POST", "/api/v1/finance/bills", False),
            ("cashier", "POST", "/api/v1/finance/ledger/journals", False),
            ("cashier", "GET", "/api/v1/finance/students/stu-1/statement", True),
            ("cashier", "POST", "/api/v1/finance/payments/pay-1/reconcile", False),
            ("finance_manager", "POST", "/api/v1/finance/ledger/journals", True),
            ("finance_manager", "POST", "/api/v1/finance/ledger/journals/j-1/reverse", False),
            ("finance_manager", "DELETE", "/api/v1/finance/bills", False),
            ("teacher", "POST", "/api/v1/academics/assessments/a-1/results", True),
            ("teacher", "POST", "/api/v1/academics/assessments/a-1/publish", False),
            ("teacher", "POST", "/api/v1/academics/assessments", False),
            ("registrar", "POST", "/api/v1/students/stu-1/deactivate", False),
            ("registrar", "PATCH", "/api/v1/students/stu-1", True),
            ("branch_admin", "GET", "/api/v1/students", False),
            ("viewer", "GET", "/api/v1/finance/ledger/accounts", True),
            ("viewer", "POST", "/api/v1/finance/payments", False),
        ]
        for role, method, path, expected in cases:
            with self.subTest(role=role, method=method, path=path):
                self.assertEqual(role_allows(role, method, path), expected)
