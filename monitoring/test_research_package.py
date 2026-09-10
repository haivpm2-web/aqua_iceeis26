"""Research archive provenance, reproducibility and tamper-detection regressions."""

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from .models import EventMarker, ExperimentRun, FPGAImplementation, SensorSample
from .research_package import (
    INTEGRITY_FIELDS,
    PackageIntegrityError,
    PackageStateError,
    canonical_json,
    generate_package,
)


class ResearchPackageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.run = ExperimentRun.objects.create(
            run_name="SIMULATED package regression",
            source="SIMULATED",
            status="COMPLETED",
            sensor_configuration={"z": 1, "a": {"units": "mg/L"}},
        )
        self.sample = SensorSample.objects.create(
            run=self.run,
            source=self.run.source,
            sequence_number=1,
            timestamp=timezone.now(),
            do_raw=6.1,
            do_filtered=6.0,
        )

    @staticmethod
    def archive(payload):
        return zipfile.ZipFile(io.BytesIO(payload))

    def lock(self):
        from .locking import lock_run

        lock_run(self.run.pk)
        self.run.refresh_from_db()

    @staticmethod
    def tamper(model, pk, column, value):
        """Emulate external database corruption, deliberately bypassing ORM guards."""
        table = connection.ops.quote_name(model._meta.db_table)
        field = connection.ops.quote_name(model._meta.get_field(column).column)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {field} = %s WHERE id = %s", [value, pk]
            )

    def test_repeated_export_is_identical_and_manifest_hashes_every_member(self):
        first = generate_package(self.run)
        issued = self.run.integrity_generated_at
        self.assertEqual(first, generate_package(self.run))
        self.assertEqual(issued, self.run.integrity_generated_at)
        with self.archive(first) as archive:
            names = archive.namelist()
            self.assertEqual(
                names,
                [
                    "samples.csv",
                    "events.csv",
                    "metadata.json",
                    "metrics.json",
                    "fpga_config.json",
                    "table_A_denoising.csv",
                    "table_B_dynamic_response.csv",
                    "table_C_fpga.csv",
                    "table_D_fixed_point.csv",
                    "table_E_communication.csv",
                    "README.txt",
                    "SHA256SUMS.txt",
                ],
            )
            manifest = dict(
                (name, digest)
                for digest, name in (
                    line.split("  ", 1)
                    for line in archive.read("SHA256SUMS.txt").decode().splitlines()
                )
            )
            self.assertEqual(set(manifest), set(names) - {"SHA256SUMS.txt"})
            for name, digest in manifest.items():
                self.assertEqual(digest, hashlib.sha256(archive.read(name)).hexdigest())
            self.assertEqual(self.run.dataset_sha256, manifest["samples.csv"])
            self.assertEqual(
                self.run.research_package_sha256, hashlib.sha256(first).hexdigest()
            )
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(entry.create_system, 3)
                text = archive.read(entry).decode("utf-8")
                self.assertTrue(text.endswith("\n"))
                self.assertNotIn("\r\n", text)

    def test_bookkeeping_excluded_and_persist_false_is_read_only(self):
        preview = generate_package(self.run, persist=False)
        self.run.refresh_from_db()
        self.assertFalse(self.run.dataset_sha256)
        self.assertFalse(self.run.research_package_sha256)
        self.assertIsNone(self.run.integrity_generated_at)
        self.assertEqual(preview, generate_package(self.run))
        with self.archive(preview) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            self.assertFalse(INTEGRITY_FIELDS & metadata.keys())
            self.assertEqual(metadata["source"], "SIMULATED")
            self.assertEqual(metadata["status"], "COMPLETED")
            self.assertEqual(metadata["id"], self.run.pk)
            self.assertNotIn(
                self.run.research_package_sha256.encode(), archive.read("README.txt")
            )

    def test_only_finalized_runs_can_generate_packages(self):
        for state in ("CREATED", "RUNNING", "FAILED"):
            self.run.status = state
            self.run.save()
            with self.assertRaises(PackageStateError):
                generate_package(self.run)

    def test_locked_repeat_export_verifies_without_changing_digest_or_time(self):
        self.lock()
        issued = self.run.integrity_generated_at
        expected = self.run.research_package_sha256
        first = generate_package(self.run)
        self.assertEqual(first, generate_package(self.run, persist=False))
        self.run.refresh_from_db()
        self.assertEqual(self.run.integrity_generated_at, issued)
        self.assertEqual(self.run.research_package_sha256, expected)
        with self.archive(first) as archive:
            metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["status"], "LOCKED")
            self.assertIsNotNone(metadata["locked_at"])

    def test_tampered_sample_is_detected_without_overwriting_locked_hashes(self):
        from .services import run_summary

        self.lock()
        run_summary(self.run)  # A cached summary must not hide an external edit.
        previous = self.run.research_package_sha256
        self.tamper(SensorSample, self.sample.pk, "do_raw", 9.0)
        for persist in (True, False):
            with self.assertRaises(PackageIntegrityError):
                generate_package(self.run, persist=persist)
        self.run.refresh_from_db()
        self.assertEqual(previous, self.run.research_package_sha256)

    def test_tampered_event_is_detected(self):
        event = EventMarker.objects.create(
            run=self.run,
            timestamp=self.sample.timestamp,
            event_type="NOTE",
            metadata={"note": "Original intervention record"},
        )
        self.lock()
        self.tamper(EventMarker, event.pk, "event_type", "SPIKE")
        with self.assertRaises(PackageIntegrityError):
            generate_package(self.run)

    def test_tampered_run_configuration_is_detected(self):
        self.lock()
        self.tamper(ExperimentRun, self.run.pk, "filter_version", "corrupted")
        with self.assertRaises(PackageIntegrityError):
            generate_package(self.run)

    def test_tampered_shared_fpga_implementation_is_detected(self):
        implementation = FPGAImplementation.objects.create(
            name="Supplied configuration"
        )
        self.run.implementation = implementation
        self.run.save()
        self.lock()
        self.tamper(FPGAImplementation, implementation.pk, "clock_mhz", 123.0)
        with self.assertRaises(PackageIntegrityError):
            generate_package(self.run)

    def test_locked_missing_integrity_record_is_not_reissued(self):
        self.lock()
        self.tamper(ExperimentRun, self.run.pk, "research_package_sha256", "")
        with self.assertRaises(PackageIntegrityError):
            generate_package(self.run)
        self.run.refresh_from_db()
        self.assertEqual(self.run.research_package_sha256, "")

    def test_no_reference_or_hardware_results_are_fabricated(self):
        with self.archive(generate_package(self.run)) as archive:
            self.assertNotIn("hil_references.csv", archive.namelist())
            metrics = json.loads(archive.read("metrics.json"))
            self.assertIsNone(metrics["sensors"]["do"]["filtered_error"]["rmse"])
            self.assertIsNone(metrics["sensors"]["do"]["snr"]["improvement_db"])
            self.assertIsNone(metrics["fixed_point"]["do"]["bit_exact_percent"])
            self.assertIsNone(metrics["latency"]["mean"])
            self.assertIsNone(metrics["implementation"])
            self.assertIsNone(metrics["communication"]["dropped"])

    def test_hil_reference_records_are_hashed_and_tampering_detected(self):
        from .hil_models import HILReference

        run = ExperimentRun.objects.create(
            run_name="Supplied HIL reference export",
            source="HIL",
            run_type="HIL",
            status="COMPLETED",
        )
        SensorSample.objects.create(
            run=run, source="HIL", sequence_number=1, do_filtered=2.0
        )
        reference = HILReference.objects.create(
            run=run,
            sensor="do",
            sequence_number=1,
            software_reference=2.0,
            software_integer_code=123,
        )
        self.run = run
        self.lock()
        with self.archive(generate_package(run)) as archive:
            self.assertIn("hil_references.csv", archive.namelist())
            rows = list(
                csv.DictReader(io.StringIO(archive.read("hil_references.csv").decode()))
            )
            self.assertEqual(rows[0]["source"], "HIL")
            self.assertEqual(rows[0]["sequence_number"], "1")
            self.assertEqual(rows[0]["software_integer_code"], "123")
            self.assertIn("hil_references.csv", archive.read("SHA256SUMS.txt").decode())
        self.tamper(HILReference, reference.pk, "software_reference", 3.0)
        with self.assertRaises(PackageIntegrityError):
            generate_package(run)

    def test_all_sources_remain_labelled_including_empty_result_tables(self):
        for source in ("REAL", "SIMULATED", "HIL", "SYNTHETIC"):
            run = ExperimentRun.objects.create(
                run_name="Explicit source fixture", source=source, status="COMPLETED"
            )
            with self.archive(generate_package(run)) as archive:
                self.assertIn(
                    f"DATA SOURCE: {source}", archive.read("README.txt").decode()
                )
                self.assertEqual(
                    json.loads(archive.read("metadata.json"))["source"], source
                )
                self.assertEqual(
                    json.loads(archive.read("metrics.json"))["source"], source
                )
                self.assertEqual(
                    json.loads(archive.read("fpga_config.json"))["source"], source
                )
                self.assertIn(
                    f"Source ({source})",
                    archive.read("table_B_dynamic_response.csv").decode(),
                )

    def test_csv_iterator_preserves_all_rows_across_chunks_and_orders_timestamps(self):
        stamp = self.sample.timestamp
        SensorSample.objects.bulk_create(
            [
                SensorSample(
                    run=self.run,
                    source=self.run.source,
                    sequence_number=i + 2,
                    timestamp=stamp - timedelta(microseconds=i + 1),
                    do_raw=6.0,
                )
                for i in range(2001)
            ],
            batch_size=500,
        )
        with self.archive(generate_package(self.run)) as archive:
            rows = list(
                csv.DictReader(io.StringIO(archive.read("samples.csv").decode()))
            )
            self.assertEqual(len(rows), 2002)
            self.assertEqual(rows[-1]["sequence_number"], "1")
            self.assertEqual(rows[0]["sequence_number"], "2002")
            self.assertTrue(all(row["source"] == "SIMULATED" for row in rows))

    def test_canonical_json_normalizes_timezone_and_rejects_nonfinite_values(self):
        stamp = datetime(2026, 9, 9, 7, 0, tzinfo=datetime_timezone(timedelta(hours=7)))
        self.assertEqual(
            canonical_json({"z": stamp, "a": [0.1, None, True]}),
            b'{"a":[0.1,null,true],"z":"2026-09-09T00:00:00.000000Z"}\n',
        )
        self.assertEqual(
            canonical_json({"z": 1, "a": 2}), canonical_json({"a": 2, "z": 1})
        )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(PackageIntegrityError):
                canonical_json({"bad": value})
        with self.assertRaises(PackageIntegrityError):
            canonical_json({"naive": datetime(2026, 9, 9)})
