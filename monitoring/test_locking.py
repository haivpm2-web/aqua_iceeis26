"""Regression coverage for the scientific evidence finalization boundary."""

from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Value
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .admin import RunAdmin, SampleAdmin
from .hil_models import HILReference
from .locking import lock_run, unlock_run
from .models import (
    EventMarker,
    ExperimentRun,
    ExperimentUnlockAudit,
    FPGAImplementation,
    SensorSample,
)
from .serializers import RunSerializer
from .services import run_summary


@override_settings(INGEST_API_TOKEN="locking-test-token", SECURE_SSL_REDIRECT=False)
class ExperimentLockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(
            username="release-admin", is_staff=True, is_superuser=True
        )
        self.staff = get_user_model().objects.create(
            username="research-staff", is_staff=True
        )
        self.implementation = FPGAImplementation.objects.create(
            name="Supplied research configuration"
        )
        self.run = ExperimentRun.objects.create(
            run_name="SIMULATED lock regression",
            source="SIMULATED",
            status="COMPLETED",
            implementation=self.implementation,
        )
        self.sample = SensorSample.objects.create(
            run=self.run, source="SIMULATED", sequence_number=1, do_raw=6
        )
        self.event = EventMarker.objects.create(
            run=self.run, timestamp=timezone.now(), event_type="NOTE"
        )
        self.reference = HILReference.objects.create(
            run=self.run, sensor="do", sequence_number=1, software_reference=6
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer locking-test-token")

    def lock(self):
        self.run = lock_run(self.run.pk, self.user)

    def test_lock_records_identity_time_and_integrity_atomically(self):
        self.lock()
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, "LOCKED")
        self.assertEqual(self.run.locked_by, self.user)
        self.assertIsNotNone(self.run.locked_at)
        self.assertIsNotNone(self.run.integrity_generated_at)
        self.assertEqual(len(self.run.dataset_sha256), 64)
        self.assertEqual(len(self.run.research_package_sha256), 64)

    def test_lock_requires_completed_and_cannot_be_repeated(self):
        for status in ("CREATED", "RUNNING", "FAILED"):
            self.run.status = status
            self.run.save()
            with self.assertRaises(ValidationError):
                lock_run(self.run.pk, self.user)
        self.run.status = "COMPLETED"
        self.run.save()
        self.lock()
        with self.assertRaises(ValidationError):
            lock_run(self.run.pk, self.user)

    def test_package_failure_rolls_back_lock_and_hashes(self):
        with patch(
            "monitoring.research_package.generate_package",
            side_effect=ValueError("invalid evidence"),
        ):
            with self.assertRaises(ValueError):
                lock_run(self.run.pk, self.user)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, "COMPLETED")
        self.assertIsNone(self.run.locked_at)
        self.assertEqual(self.run.research_package_sha256, "")

    def test_ordinary_create_save_update_and_expression_cannot_issue_lock(self):
        operations = [
            lambda: ExperimentRun.objects.create(run_name="Direct", status="LOCKED"),
            lambda: ExperimentRun.objects.bulk_create(
                [ExperimentRun(run_name="Bulk", status="LOCKED")]
            ),
            lambda: ExperimentRun.objects.filter(pk=self.run.pk).update(
                status="LOCKED"
            ),
            lambda: ExperimentRun.objects.filter(pk=self.run.pk).update(
                status=Value("LOCKED")
            ),
            lambda: ExperimentRun.objects.filter(pk=self.run.pk).update(
                dataset_sha256="0" * 64
            ),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                operation()
        self.run.status = "LOCKED"
        with self.assertRaises(ValidationError):
            self.run.save()
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, "COMPLETED")

    def test_locked_run_rejects_metadata_changes_and_deletion(self):
        self.lock()
        self.run.filter_version = "changed"
        for operation in (
            lambda: self.run.save(),
            lambda: self.run.save(update_fields=["filter_version"]),
            lambda: self.run.delete(),
            lambda: ExperimentRun.objects.filter(pk=self.run.pk).update(
                filter_version="changed"
            ),
            lambda: ExperimentRun.objects.filter(pk=self.run.pk).delete(),
            lambda: ExperimentRun.objects.bulk_update([self.run], ["filter_version"]),
            lambda: ExperimentRun.objects.update_or_create(
                pk=self.run.pk, defaults={"filter_version": "changed"}
            ),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                operation()
        self.run.refresh_from_db()
        self.assertEqual(self.run.filter_version, "")

    def test_all_evidence_models_reject_save_delete_bulk_and_reassignment(self):
        editable = ExperimentRun.objects.create(
            run_name="Separate editable run", source="SIMULATED"
        )
        self.lock()
        for record, field, value in (
            (self.sample, "do_raw", 8),
            (self.event, "event_type", "CHANGED"),
            (self.reference, "software_reference", 8),
        ):
            cls = type(record)
            setattr(record, field, value)
            for operation in (
                lambda: record.save(),
                lambda: record.delete(),
                lambda: cls.objects.filter(pk=record.pk).update(**{field: value}),
                lambda: cls.objects.filter(pk=record.pk).delete(),
                lambda: cls.objects.bulk_update([record], [field]),
                lambda: cls.objects.filter(pk=record.pk).update(run=editable),
            ):
                with self.subTest(
                    model=cls.__name__, operation=operation
                ), self.assertRaises(ValidationError):
                    operation()
            record.run = editable
            with self.assertRaises(ValidationError):
                record.save()
            record.refresh_from_db()
            self.assertEqual(record.run_id, self.run.pk)
        for cls, values in (
            (SensorSample, {"source": "SIMULATED"}),
            (EventMarker, {"timestamp": timezone.now(), "event_type": "NOTE"}),
            (HILReference, {"sensor": "do", "sequence_number": 2}),
        ):
            for operation in (
                lambda: cls.objects.create(run=self.run, **values),
                lambda: cls.objects.bulk_create([cls(run=self.run, **values)]),
            ):
                with self.subTest(
                    model=cls.__name__, operation=operation
                ), self.assertRaises(ValidationError):
                    operation()
        sample = SensorSample.objects.create(run=editable, source="SIMULATED")
        sample.run = self.run
        with self.assertRaises(ValidationError):
            sample.save()
        with self.assertRaises(ValidationError):
            SensorSample.objects.filter(pk=sample.pk).update(run_id=self.run.pk)

    def test_shared_fpga_configuration_is_frozen_without_blocking_separate_runs(self):
        editable = ExperimentRun.objects.create(
            run_name="Another run", implementation=self.implementation
        )
        self.lock()
        self.implementation.clock_mhz = 100
        for operation in (
            lambda: self.implementation.save(),
            lambda: self.implementation.delete(),
            lambda: FPGAImplementation.objects.filter(pk=self.implementation.pk).update(
                clock_mhz=100
            ),
            lambda: FPGAImplementation.objects.filter(
                pk=self.implementation.pk
            ).delete(),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                operation()
        editable.notes = "Independent mutable notes"
        editable.save()
        editable.implementation = FPGAImplementation.objects.create(
            name="New configuration"
        )
        editable.save()
        self.assertEqual(editable.notes, "Independent mutable notes")

    def test_only_active_superuser_with_reason_can_unlock(self):
        self.lock()
        for user in (None, self.staff):
            with self.assertRaises(PermissionDenied):
                unlock_run(self.run.pk, user, "Correction required")
        for reason in (None, 12, {}, "", "  "):
            with self.assertRaises(ValidationError):
                unlock_run(self.run.pk, self.user, reason)
        self.user.is_active = False
        with self.assertRaises(PermissionDenied):
            unlock_run(self.run.pk, self.user, "Correction required")
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, "LOCKED")
        self.assertFalse(ExperimentUnlockAudit.objects.exists())

    def test_unlock_preserves_old_hashes_in_immutable_audit_and_requires_reissue(self):
        self.lock()
        old_hash = self.run.research_package_sha256
        old_lock = self.run.locked_at
        self.run = unlock_run(
            self.run.pk, self.user, "  Correct supplied calibration  "
        )
        self.assertEqual(self.run.status, "COMPLETED")
        self.assertIsNone(self.run.locked_at)
        self.assertEqual(self.run.dataset_sha256, "")
        self.assertEqual(self.run.research_package_sha256, "")
        audit = self.run.unlock_audit.get()
        self.assertEqual(audit.reason, "Correct supplied calibration")
        self.assertEqual(audit.user, self.user)
        self.assertEqual(audit.research_package_sha256, old_hash)
        self.assertEqual(audit.locked_at, old_lock)
        audit.reason = "Altered audit"
        for operation in (
            lambda: audit.save(),
            lambda: audit.delete(),
            lambda: ExperimentUnlockAudit.objects.update(reason="changed"),
            lambda: ExperimentUnlockAudit.objects.all().delete(),
            lambda: ExperimentUnlockAudit.objects.bulk_update([audit], ["reason"]),
            lambda: ExperimentUnlockAudit.objects.bulk_create(
                [audit],
                update_conflicts=True,
                update_fields=["reason"],
                unique_fields=["pk"],
            ),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                operation()
        self.sample.do_raw = 7
        self.sample.save()
        self.lock()
        self.assertNotEqual(self.run.research_package_sha256, old_hash)
        self.assertEqual(self.run.unlock_audit.count(), 1)

    def test_source_cannot_change_after_samples_or_independent_references(self):
        run = ExperimentRun.objects.create(run_name="HIL reference only", source="HIL")
        HILReference.objects.create(
            run=run, sensor="do", sequence_number=1, software_reference=2
        )
        for evidence_run in (self.run, run):
            with self.assertRaises(ValidationError):
                ExperimentRun.objects.filter(pk=evidence_run.pk).update(source="REAL")
            evidence_run.source = "REAL"
            with self.assertRaises(ValidationError):
                evidence_run.save()

    def test_bulk_reassignment_invalidates_both_run_summaries(self):
        destination = ExperimentRun.objects.create(
            run_name="SIMULATED destination", source="SIMULATED"
        )
        self.assertEqual(run_summary(self.run)["sensors"]["do"]["raw"]["mean"], 6)
        self.assertIsNone(run_summary(destination)["sensors"]["do"]["raw"]["mean"])
        SensorSample.objects.filter(run=self.run).update(run=destination)
        self.assertIsNone(run_summary(self.run)["sensors"]["do"]["raw"]["mean"])
        self.assertEqual(run_summary(destination)["sensors"]["do"]["raw"]["mean"], 6)

    def test_lock_api_requires_write_auth_and_rejects_direct_state_changes(self):
        url = f"/api/v1/runs/{self.run.pk}/lock/"
        unauthenticated = APIClient()
        self.assertIn(unauthenticated.post(url).status_code, (401, 403))
        for payload in (
            {"status": "LOCKED"},
            {"dataset_sha256": "0" * 64},
            {"locked_at": timezone.now().isoformat()},
        ):
            self.assertEqual(
                self.client.patch(
                    f"/api/v1/runs/{self.run.pk}/", payload, format="json"
                ).status_code,
                400,
            )
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "LOCKED")
        self.assertIsNone(response.data["locked_by"])
        self.assertEqual(
            self.client.post(
                f"/api/v1/runs/{self.run.pk}/unlock/",
                {"reason": "Token request"},
                format="json",
            ).status_code,
            403,
        )

    def test_locked_api_run_sample_event_reference_and_csv_writes_fail(self):
        self.lock()
        self.assertEqual(
            self.client.patch(
                f"/api/v1/runs/{self.run.pk}/", {"notes": "changed"}, format="json"
            ).status_code,
            400,
        )
        payload = dict(
            run_id=self.run.pk, do_raw=6, ph_raw=7, tds_raw=400, temperature_raw=27
        )
        for url, data in (
            ("/api/v1/samples/", payload),
            ("/api/v1/samples/batch/", [payload]),
        ):
            self.assertEqual(
                self.client.post(url, data, format="json").status_code, 400
            )
        response = self.client.post(
            "/api/v1/events/",
            {
                "run": self.run.pk,
                "timestamp": timezone.now().isoformat(),
                "event_type": "NOTE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/v1/runs/{self.run.pk}/hil-references/",
            {"sensor": "do", "sequence_number": 2, "software_reference": 6},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/v1/runs/{self.run.pk}/import/",
            {"csv": "do_raw,ph_raw,tds_raw,temperature_raw\n6,7,400,27\n"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.run.samples.count(), 1)

    def test_superuser_unlock_api_validates_reason_and_unknown_run(self):
        self.lock()
        self.client.force_authenticate(user=self.user)
        url = f"/api/v1/runs/{self.run.pk}/unlock/"
        for reason in (None, 5, {}, " "):
            self.assertEqual(
                self.client.post(url, {"reason": reason}, format="json").status_code,
                400,
            )
        response = self.client.post(
            url, {"reason": "Explicit test correction"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        for action in ("lock", "unlock"):
            response = self.client.post(
                f"/api/v1/runs/999999/{action}/",
                {"reason": "Missing experiment"},
                format="json",
            )
            self.assertEqual(response.status_code, 404, response.data)

    def test_admin_readonly_permissions_and_protected_bulk_delete(self):
        self.lock()
        request = RequestFactory().post(
            "/admin/monitoring/experimentrun/", {"post": "yes"}
        )
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        run_admin = RunAdmin(ExperimentRun, admin.site)
        sample_admin = SampleAdmin(SensorSample, admin.site)
        self.assertFalse(run_admin.has_change_permission(request, self.run))
        self.assertFalse(run_admin.has_delete_permission(request, self.run))
        self.assertFalse(sample_admin.has_change_permission(request, self.sample))
        self.assertTrue(run_admin.has_view_permission(request, self.run))
        run_admin.delete_selected(request, ExperimentRun.objects.filter(pk=self.run.pk))
        self.assertTrue(ExperimentRun.objects.filter(pk=self.run.pk).exists())
        self.assertTrue(list(request._messages))
        request.user = self.staff
        self.assertNotIn("unlock_experiments", run_admin.get_actions(request))

    def test_optional_research_metadata_roundtrips_without_requiring_old_runs(self):
        self.assertTrue(
            RunSerializer(data={"run_name": "Legacy compatible"}).is_valid()
        )
        payload = dict(
            run_name="SIMULATED reproducible metadata",
            source="SIMULATED",
            sampling_rate_hz=100,
            input_q_format="Q16.16",
            output_q_format="Q16.16",
            accumulator_q_format="Q32.32",
            coefficient_q_format="Q1.15",
            rounding_mode="nearest-even",
            saturation_mode="saturate",
            fpga_clock_hz=100000000,
            alpha_stable=0.1,
            alpha_normal=0.2,
            alpha_noisy=0.05,
            alpha_transient=0.8,
            beta_noise=0.1,
            threshold_base=0.1,
            threshold_multiplier=3,
            median_window=5,
            persistence_samples=3,
            software_git_commit="a" * 40,
            fpga_git_commit="b" * 40,
            stm32_git_commit="c" * 40,
            gateway_git_commit="d" * 40,
            sensor_model="Documented model",
            calibration_date="2026-09-09",
            calibration_method="Two-point",
            calibration_coefficients={"do": [1, 0]},
            reference_instrument="Supplied instrument",
            experiment_notes="SIMULATED validation",
        )
        response = self.client.post("/api/v1/runs/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        for key, value in payload.items():
            self.assertEqual(response.data[key], value, key)

    def test_invalid_metadata_is_rejected_at_api_boundary(self):
        for field, value in (
            ("sampling_rate_hz", 0),
            ("fpga_clock_hz", -1),
            ("alpha_stable", 1.1),
            ("beta_noise", -0.1),
            ("median_window", 0),
            ("persistence_samples", 0),
            ("threshold_base", -1),
            ("calibration_coefficients", []),
            ("calibration_coefficients", {"bad": 1e101}),
            ("calibration_date", "invalid"),
        ):
            with self.subTest(field=field):
                response = self.client.post(
                    "/api/v1/runs/",
                    {"run_name": "Invalid metadata", field: value},
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.data)
