from datetime import timedelta
from django.contrib import admin
from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from .admin import ImplementationAdmin, EventAdmin
from .analysis import compute_noise_reduction, compute_transient_metrics
from .models import ExperimentRun, SensorSample, FPGAImplementation, EventMarker
from .services import run_summary


@override_settings(INGEST_API_TOKEN="scientific-test-token", SECURE_SSL_REDIRECT=False)
class ScienceReviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.run = ExperimentRun.objects.create(run_name="Validation")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer scientific-test-token")
        self.payload = dict(
            run_id=self.run.pk,
            do_raw=6,
            do_filtered=6.1,
            ph_raw=7,
            tds_raw=400,
            temperature_raw=27,
        )

    def test_non_object_payloads_return_validation_errors(self):
        for value in ([], [1], "invalid", 3):
            response = self.client.post("/api/v1/samples/", value, format="json")
            self.assertEqual(response.status_code, 400)

    def test_nested_nonfinite_and_malformed_configuration(self):
        for config in (
            [],
            {"validity_ranges": []},
            {"validity_ranges": {"do": [0, True]}},
        ):
            response = self.client.post(
                "/api/v1/runs/",
                {"run_name": "Bad", "sensor_configuration": config},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/v1/samples/",
            {**self.payload, "extra_sensors": {"bad": 1e101}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_far_future_sample_is_rejected(self):
        response = self.client.post(
            "/api/v1/samples/",
            {
                **self.payload,
                "timestamp": (timezone.now() + timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_misaligned_meter_reference_does_not_enter_error(self):
        stamp = timezone.now()
        SensorSample.objects.create(
            run=self.run,
            timestamp=stamp,
            do_raw=6,
            do_filtered=6.1,
            do_reference=6,
            do_software_reference=6.1,
            reference_timestamp=stamp - timedelta(seconds=1),
        )
        summary = run_summary(self.run)
        self.assertEqual(summary["reference_alignment"]["excluded_rows"], 1)
        self.assertIsNone(summary["sensors"]["do"]["filtered_error"]["rmse"])
        self.assertEqual(summary["fixed_point"]["do"]["rmse"], 0)

    def test_source_immutable_after_logging(self):
        SensorSample.objects.create(run=self.run)
        response = self.client.patch(
            f"/api/v1/runs/{self.run.pk}/", {"source": "SIMULATED"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_cache_changes_after_sample_and_event_edits(self):
        sample = SensorSample.objects.create(run=self.run, do_raw=6)
        self.assertEqual(run_summary(self.run)["sensors"]["do"]["raw"]["mean"], 6)
        sample.do_raw = 7
        sample.save()
        self.assertEqual(run_summary(self.run)["sensors"]["do"]["raw"]["mean"], 7)
        event = EventMarker.objects.create(
            run=self.run,
            timestamp=timezone.now(),
            sensor="do",
            event_type="STEP",
            metadata={},
        )
        self.assertEqual(len(run_summary(self.run)["dynamic"]), 1)
        event.event_type = "NOTE"
        event.save()
        self.assertEqual(run_summary(self.run)["dynamic"], [])

    def test_transient_samples_and_episodes_are_distinct(self):
        for i, flag in enumerate([False, True, True, False, True]):
            SensorSample.objects.create(
                run=self.run,
                timestamp=timezone.now() + timedelta(milliseconds=i),
                transient_detected=flag,
            )
        summary = run_summary(self.run)
        self.assertEqual(summary["transient_count"], 2)
        self.assertEqual(summary["transient_flagged_samples"], 3)

    def test_reference_error_available_without_filtered_output(self):
        metrics = compute_noise_reduction([1, 3], [None, None], [1, 2])
        self.assertEqual(metrics["raw_error"]["mae"], 0.5)
        self.assertIsNone(metrics["rmse_improvement_percent"])

    def test_missing_threshold_crossings_are_not_inferred(self):
        stamp = timezone.now()
        event = dict(
            timestamp=stamp,
            sensor="do",
            metadata=dict(initial=0, target=10, settling_band=0.1, hold_seconds=1),
        )
        rows = [
            dict(timestamp=stamp + timedelta(seconds=i), do_filtered=10)
            for i in (5, 6, 7)
        ]
        result = compute_transient_metrics(rows, event)
        self.assertIsNone(result["rise_time_s"])
        self.assertIsNone(result["settling_time_s"])

    def test_admin_rejects_invalid_synthesis_and_step(self):
        from django.contrib.auth.models import AnonymousUser

        request = RequestFactory().get("/admin/")
        request.user = AnonymousUser()
        form_class = ImplementationAdmin(FPGAImplementation, admin.site).get_form(
            request
        )
        self.assertFalse(
            form_class(
                data={"name": "Invalid", "lut_used": 100, "lut_available": 50}
            ).is_valid()
        )
        valid = form_class(data={"name": "Valid", "lut_used": 10, "lut_available": 50})
        self.assertTrue(valid.is_valid(), valid.errors)
        event_form = EventAdmin(EventMarker, admin.site).get_form(request)
        self.assertFalse(
            event_form(
                data={
                    "run": self.run.pk,
                    "timestamp_0": "2026-09-09",
                    "timestamp_1": "00:00:00",
                    "sensor": "do",
                    "event_type": "STEP",
                    "metadata": "{}",
                }
            ).is_valid()
        )
