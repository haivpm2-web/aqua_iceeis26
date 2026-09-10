"""Regression coverage for bounded history, streaming, and scientific CSV imports."""

import csv
import io
import json
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ExperimentRun, SensorSample


@override_settings(INGEST_API_TOKEN="review-token", SECURE_SSL_REDIRECT=False)
class APIReviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer review-token")
        self.run = ExperimentRun.objects.create(
            run_name="CSV and history regression", source="SIMULATED"
        )
        self.stamp = timezone.now()

    def samples(self, count):
        return SensorSample.objects.bulk_create(
            [
                SensorSample(
                    run=self.run,
                    source=self.run.source,
                    timestamp=self.stamp + timedelta(seconds=i),
                    sequence_number=i,
                    do_raw=i,
                    ph_raw=7,
                    tds_raw=400,
                    temperature_raw=27,
                )
                for i in range(count)
            ]
        )

    def import_csv(self, content, mapping=None):
        data = {"file": SimpleUploadedFile("measurements.csv", content.encode())}
        if mapping is not None:
            data["mapping"] = json.dumps(mapping)
        return self.client.post(f"/api/v1/runs/{self.run.pk}/import/", data)

    def test_downsampling_keeps_both_endpoints_and_exact_target(self):
        self.samples(101)
        for target in (1, 2, 10, 50, 101, 200):
            with self.subTest(target=target):
                response = self.client.get(
                    "/api/v1/history/", {"run_id": self.run.pk, "downsample": target}
                )
                self.assertEqual(response.status_code, 200)
                rows = response.json()["results"]
                self.assertEqual(len(rows), min(target, 101))
                self.assertEqual(rows[-1]["sequence_number"], 100)
                if target > 1:
                    self.assertEqual(rows[0]["sequence_number"], 0)
                self.assertEqual(len({r["id"] for r in rows}), len(rows))

    def test_empty_downsample_and_invalid_pagination(self):
        self.assertEqual(
            self.client.get("/api/v1/history/?downsample=10").json()["results"], []
        )
        self.assertEqual(
            self.client.get("/api/v1/history/?downsample=10&page=2").status_code, 400
        )

    def test_latest_uses_receipt_order_despite_device_clock_skew(self):
        rows = self.samples(2)
        SensorSample.objects.filter(pk=rows[0].pk).update(
            timestamp=self.stamp + timedelta(days=30)
        )
        latest = self.client.get("/api/v1/latest/", {"run_id": self.run.pk}).json()
        self.assertEqual(latest["sample"]["id"], rows[-1].pk)

    def test_query_ids_are_bounded_on_all_collections(self):
        for endpoint in ("history", "latest", "events"):
            for invalid in ("0", "-1", "9223372036854775808", "9" * 100, "", "abc"):
                with self.subTest(endpoint=endpoint, value=invalid):
                    self.assertEqual(
                        self.client.get(
                            f"/api/v1/{endpoint}/", {"run_id": invalid}
                        ).status_code,
                        400,
                    )

    def test_run_history_requires_existing_run(self):
        self.assertEqual(
            self.client.get("/api/v1/runs/99999999/samples/").status_code, 404
        )

    def test_csv_validates_filters_before_streaming(self):
        for query in (
            {"start": "invalid"},
            {"state": "INVALID"},
            {
                "start": self.stamp.isoformat(),
                "end": (self.stamp - timedelta(seconds=1)).isoformat(),
            },
        ):
            response = self.client.get(f"/api/v1/runs/{self.run.pk}/export/", query)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.streaming)

    def test_csv_export_and_sensor_projection_retain_source(self):
        self.samples(1)
        history = self.client.get("/api/v1/history/", {"sensor": "do"}).json()[
            "results"
        ]
        self.assertEqual(history[0]["source"], "SIMULATED")
        self.assertIn("packet_valid", history[0])
        exported = self.client.get(f"/api/v1/runs/{self.run.pk}/export/")
        rows = list(
            csv.DictReader(
                io.StringIO(b"".join(exported.streaming_content).decode("utf-8-sig"))
            )
        )
        self.assertEqual(rows[0]["source"], "SIMULATED")

    def test_malformed_mapping_is_rejected_without_importing(self):
        content = "do_raw,ph_raw,tds_raw,temperature_raw\n6,7,400,27\n"
        for mapping in (
            [],
            {"do_raw": []},
            {"do_raw": None},
            {"do_raw": ""},
            {"missing": "do_raw"},
            {"do_raw": "ph_raw"},
        ):
            with self.subTest(mapping=mapping):
                self.assertEqual(self.import_csv(content, mapping).status_code, 400)
                self.assertEqual(SensorSample.objects.count(), 0)

    @override_settings(MAX_IMPORT_ROWS=2)
    def test_import_row_limit_is_atomic(self):
        content = "do_raw,ph_raw,tds_raw,temperature_raw\n" + "6,7,400,27\n" * 3
        response = self.import_csv(content)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SensorSample.objects.count(), 0)

    def test_malformed_csv_after_valid_row_is_atomic(self):
        content = (
            'do_raw,ph_raw,tds_raw,temperature_raw\n6,7,400,27\n"broken,7,400,27\n'
        )
        response = self.import_csv(content)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(SensorSample.objects.count(), 0)

    def test_import_reports_bad_rows_and_inherits_source(self):
        content = "oxygen,ph_raw,tds_raw,temperature_raw\n6,7,400,27\nbad,7,400,27\n"
        response = self.import_csv(content, {"oxygen": "do_raw"})
        self.assertEqual(response.status_code, 201)
        report = response.json()
        self.assertEqual((report["successful_rows"], report["failed_rows"]), (1, 1))
        self.assertEqual(report["conversion_errors"][0]["row"], 3)
        self.assertEqual(SensorSample.objects.get().source, "SIMULATED")

    def test_import_run_validation_does_not_query_per_row(self):
        content = "do_raw,ph_raw,tds_raw,temperature_raw\n" + "6,7,400,27\n" * 40
        with CaptureQueriesContext(connection) as queries:
            response = self.import_csv(content)
        self.assertEqual(response.status_code, 201)
        run_reads = [
            q
            for q in queries.captured_queries
            if q["sql"].lstrip().upper().startswith("SELECT")
            and "monitoring_experimentrun" in q["sql"]
        ]
        # A third constant lookup protects the run against concurrent finalization.
        self.assertLessEqual(len(run_reads), 3)

    def test_unsupported_run_methods_return_405(self):
        self.assertEqual(
            self.client.post(
                f"/api/v1/runs/{self.run.pk}/", {}, format="json"
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.patch("/api/v1/runs/", {}, format="json").status_code, 405
        )

    def test_unicode_bearer_returns_401(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-\u0111")
        self.assertEqual(self.client.get("/api/v1/latest/").status_code, 401)

    def test_tables_respect_the_same_interval_as_history(self):
        self.samples(3)
        response = self.client.get(
            f"/api/v1/runs/{self.run.pk}/tables/", {"end": self.stamp.isoformat()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["E"]["rows"][0][0], 1)
        self.assertEqual(
            self.client.get(
                f"/api/v1/runs/{self.run.pk}/tables/?start=bad&download=csv"
            ).status_code,
            400,
        )

    def test_collection_pagination_exposes_next_page(self):
        ExperimentRun.objects.create(run_name="Second run")
        first = self.client.get("/api/v1/runs/?limit=1").json()
        second = self.client.get("/api/v1/runs/?limit=1&page=2").json()
        self.assertEqual(first["next_page"], 2)
        self.assertIsNone(second["next_page"])
        self.assertNotEqual(first["results"][0]["id"], second["results"][0]["id"])
