import csv
import io
from datetime import timedelta
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from .models import ExperimentRun, SensorSample, EventMarker
from .analysis import *


class AnalysisTests(SimpleTestCase):
    def test_basic_stats(self):
        s = compute_basic_stats([1, 2, 3, None])
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["mean"], 2)
        self.assertEqual(s["median"], 2)
        self.assertEqual(s["mad"], 1)
        self.assertAlmostEqual(s["variance"], 2 / 3)
        self.assertAlmostEqual(s["rms"], math.sqrt(14 / 3))
        self.assertIsNone(compute_basic_stats([])["mean"])
        self.assertIsNone(compute_basic_stats([-1, 1])["cv_percent"])

    def test_noise_reduction_uses_pairs(self):
        s = compute_noise_reduction([0, 2, 100], [1, 1, None])
        self.assertEqual(s["paired_count"], 2)
        self.assertEqual(s["sd_reduction_percent"], 100)
        self.assertIsNone(s["filtered_error"]["rmse"])
        self.assertIsNone(s["snr"]["raw"])

    def test_error_and_snr(self):
        self.assertEqual(compute_error_metrics([2, 4], [1, 3])["rmse"], 1)
        s = compute_snr_metrics([2, 2], [1.5, 1.5], [1, 1])
        self.assertEqual(s["raw"], 0)
        self.assertAlmostEqual(s["improvement_db"], 6.020599913)
        self.assertIsNone(compute_snr_metrics([1], [1], [1])["raw"])

    def test_latency(self):
        t = timezone.now()
        s = compute_latency_metrics([1, 2, 3, 4, 5], [t, t + timedelta(seconds=2)])
        self.assertEqual(s["p50"], 3)
        self.assertAlmostEqual(s["p95"], 4.8)
        self.assertAlmostEqual(s["p99"], 4.96)
        self.assertEqual(s["throughput_samples_s"], 0.5)

    def test_fixed_point_requires_integer_codes(self):
        s = compute_fixed_point_metrics([1, 2], [1, 2])
        self.assertEqual(s["rmse"], 0)
        self.assertIsNone(s["bit_exact_percent"])
        s = compute_fixed_point_metrics([1, 3], [1, 2], [100, 300], [100, 200])
        self.assertEqual(s["bit_exact_percent"], 50)
        self.assertEqual(s["mismatch_count"], 1)

    def test_packet_reordering_duplicates_and_missing(self):
        s = compute_packet_metrics(
            [dict(sequence_number=n, packet_valid=True) for n in [10, 12, 11, 12, 15]]
        )
        self.assertEqual(s["sequence_gaps"], 2)
        self.assertEqual(s["duplicates"], 1)
        self.assertEqual(s["out_of_order"], 1)
        self.assertIsNone(s["dropped"])
        self.assertEqual(s["denominator"], "received packets")
        self.assertIsNone(compute_packet_metrics([])["sequence_gaps"])

    def test_outlier_labels(self):
        s = compute_outlier_metrics([True, False], [None, None])
        self.assertIsNone(s["f1"])
        s = compute_outlier_metrics(
            [True, True, False, False], [True, False, True, False]
        )
        self.assertEqual(s["f1"], 0.5)
        self.assertIsNone(s["spike_rejection_rate"])

    def test_transient_requires_event_and_dwell(self):
        self.assertIsNone(compute_transient_metrics([])["settling_time_s"])
        t = timezone.now()
        rows = [
            dict(
                timestamp=t + timedelta(seconds=i),
                do_filtered=v,
                transient_detected=i == 1,
            )
            for i, v in enumerate([0, 1, 5, 9, 10, 10, 10])
        ]
        event = dict(
            timestamp=t,
            sensor="do",
            metadata=dict(initial=0, target=10, settling_band=0.2, hold_seconds=2),
        )
        s = compute_transient_metrics(rows, event)
        self.assertEqual(s["response_delay_s"], 1)
        self.assertEqual(s["rise_time_s"], 2)
        self.assertEqual(s["settling_time_s"], 4)
        self.assertIsNone(
            compute_transient_metrics(rows[:-1], event)["settling_time_s"]
        )


@override_settings(INGEST_API_TOKEN="test-ingestion-token", SECURE_SSL_REDIRECT=False)
class APITests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer test-ingestion-token")
        self.run = ExperimentRun.objects.create(run_name="Test run")
        self.payload = dict(
            run_id=self.run.pk, do_raw=6.5, ph_raw=7.4, tds_raw=420, temperature_raw=27
        )

    def post(self, payload=None):
        return self.client.post(
            "/api/v1/samples/", payload or self.payload, format="json"
        )

    def test_ingestion_optional_fields(self):
        self.assertEqual(self.post().status_code, 201)
        self.assertIsNone(SensorSample.objects.get().do_filtered)

    def test_authentication(self):
        self.client.credentials()
        self.assertEqual(self.post().status_code, 401)
        self.assertEqual(self.client.get("/api/v1/latest/").status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer wrong")
        self.assertEqual(self.post().status_code, 401)

    def test_batch_atomic_and_bounded(self):
        good = self.payload
        bad = {**good, "alpha_value": 2}
        self.assertEqual(
            self.client.post(
                "/api/v1/samples/batch/", [good, bad], format="json"
            ).status_code,
            400,
        )
        self.assertEqual(SensorSample.objects.count(), 0)
        self.assertEqual(
            self.client.post(
                "/api/v1/samples/batch/", [good] * 100, format="json"
            ).status_code,
            201,
        )
        self.assertEqual(SensorSample.objects.count(), 100)
        self.assertEqual(
            self.client.post("/api/v1/samples/batch/", [], format="json").status_code,
            400,
        )

    def test_invalid_packet_retained_excluded_from_stats(self):
        self.assertEqual(
            self.post(dict(run_id=self.run.pk, packet_valid=False)).status_code, 201
        )
        self.assertEqual(EventMarker.objects.get().event_type, "PACKET_FAULT")
        s = self.client.get(f"/api/v1/runs/{self.run.pk}/summary/").json()
        self.assertEqual(s["communication"]["invalid"], 1)
        self.assertEqual(s["sensors"]["do"]["raw"]["count"], 0)

    def test_validation(self):
        for update in (
            {"do_raw": None},
            {"quality_flag": "bogus"},
            {"fpga_latency_us": -1},
            {"source": "SIMULATED"},
            {"unknown": 1},
            {"do_raw": "NaN"},
            {"alpha_value": 2},
        ):
            self.assertEqual(
                self.post({**self.payload, **update}).status_code, 400, update
            )

    def test_latest_history_downsampling(self):
        t = timezone.now()
        payloads = [
            {
                **self.payload,
                "sequence_number": i,
                "timestamp": (t + timedelta(milliseconds=i)).isoformat(),
            }
            for i in range(101)
        ]
        self.client.post("/api/v1/samples/batch/", payloads, format="json")
        self.assertEqual(
            self.client.get("/api/v1/latest/").json()["sample"]["sequence_number"], 100
        )
        data = self.client.get(
            f"/api/v1/history/?run_id={self.run.pk}&downsample=10"
        ).json()
        self.assertLessEqual(len(data["results"]), 10)
        self.assertEqual(data["count"], 101)
        self.assertEqual(data["results"][0]["sequence_number"], 0)
        for query in (
            "limit=-1",
            "limit=oops",
            "start=bad",
            "sensor=bad",
            "state=bad",
            "run_id=bad",
        ):
            self.assertEqual(
                self.client.get("/api/v1/history/?" + query).status_code, 400
            )

    def test_run_creation_and_summary(self):
        r = self.client.post(
            "/api/v1/runs/",
            {"run_name": "New", "run_type": "HIL", "source": "HIL"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.post({**self.payload, "do_filtered": 6.4})
        data = self.client.get(f"/api/v1/runs/{self.run.pk}/stats/").json()
        self.assertEqual(data["sensors"]["do"]["raw"]["mean"], 6.5)
        self.assertIsNone(data["sensors"]["do"]["filtered_error"]["rmse"])

    def test_csv_export_import_report(self):
        self.post()
        response = self.client.get(f"/api/v1/runs/{self.run.pk}/export/")
        text = b"".join(response.streaming_content).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(float(rows[0]["do_raw"]), 6.5)
        data = (
            b"do_raw,ph_raw,tds_raw,temperature_raw\n6.5,7.4,420,27\nbad,7.4,420,27\n"
        )
        report = self.client.post(
            f"/api/v1/runs/{self.run.pk}/import/",
            {"file": SimpleUploadedFile("data.csv", data)},
        ).json()
        self.assertEqual(report["successful_rows"], 1)
        self.assertEqual(report["failed_rows"], 1)
        self.assertEqual(report["conversion_errors"][0]["row"], 3)

    def test_pages_health_tables(self):
        for url in (
            "/",
            "/runs/",
            "/live/",
            "/analysis/",
            "/compare/",
            "/fpga/",
            "/events/",
            "/paper/",
            "/system/",
            "/health/",
            f"/runs/{self.run.pk}/",
            f"/runs/{self.run.pk}/paper/",
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(
            self.client.get(f"/api/v1/runs/{self.run.pk}/tables/").status_code, 200
        )
        response = self.client.get(f"/api/v1/runs/{self.run.pk}/tables/?download=csv")
        self.assertIn(b"Denoising", b"".join(response.streaming_content))

    def test_health_database_failure(self):
        with patch("monitoring.views.connection.cursor", side_effect=DatabaseError):
            self.assertEqual(self.client.get("/health/").status_code, 503)

    def test_event_input(self):
        event = dict(
            run=self.run.pk,
            timestamp=timezone.now().isoformat(),
            sensor="do",
            event_type="STEP",
            metadata={},
        )
        self.assertEqual(
            self.client.post("/api/v1/events/", event, format="json").status_code, 400
        )
        event["metadata"] = dict(
            initial=6, target=7, settling_band=0.02, hold_seconds=2
        )
        self.assertEqual(
            self.client.post("/api/v1/events/", event, format="json").status_code, 201
        )

    def test_synthesis_validation(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/implementations/",
                {"name": "Real report", "lut_used": 100, "lut_available": 50},
                format="json",
            ).status_code,
            400,
        )

    @override_settings(DEBUG=False)
    def test_simulation_blocked_in_production(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("simulate_sensor", count=1)
