"""Versioned, reproducible research exports and verification of locked evidence.

The run/implementation locks are shared with ordinary evidence writers. ZIP
members are streamed, while the existing analysis service has its configured
sample limit. The returned bytes are suitable for a Django HttpResponse.
"""

import csv
import hashlib
import io
import json
import math
import tempfile
import zipfile
from datetime import date, datetime, timezone as datetime_timezone

from .models import EventMarker, SensorSample
from .services import run_summary
from .tables import paper_tables

PACKAGE_SCHEMA_VERSION = 1
INTEGRITY_FIELDS = {
    "dataset_sha256",
    "research_package_sha256",
    "integrity_generated_at",
}
TABLE_FILENAMES = {
    "A": "table_A_denoising.csv",
    "B": "table_B_dynamic_response.csv",
    "C": "table_C_fpga.csv",
    "D": "table_D_fixed_point.csv",
    "E": "table_E_communication.csv",
}
FPGA_FIELDS = (
    "sampling_rate_hz",
    "input_q_format",
    "output_q_format",
    "accumulator_q_format",
    "coefficient_q_format",
    "rounding_mode",
    "saturation_mode",
    "fpga_clock_hz",
    "alpha_stable",
    "alpha_normal",
    "alpha_noisy",
    "alpha_transient",
    "beta_noise",
    "threshold_base",
    "threshold_multiplier",
    "median_window",
    "persistence_samples",
    "filter_version",
    "firmware_version",
    "fpga_bitstream_version",
    "software_git_commit",
    "fpga_git_commit",
    "stm32_git_commit",
    "gateway_git_commit",
)


class PackageStateError(ValueError):
    """A run must be finalized before a research package can be issued."""


class PackageIntegrityError(ValueError):
    """Evidence no longer matches the hashes recorded for a locked run."""


def _canonical(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise PackageIntegrityError("Canonical export requires aware timestamps.")
        return (
            value.astimezone(datetime_timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise PackageIntegrityError("JSON object keys must be strings.")
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise PackageIntegrityError("Nonfinite values cannot enter a research package.")
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise PackageIntegrityError(
        f"Unsupported canonical data type: {type(value).__name__}."
    )


def canonical_json(value):
    """UTF-8 canonical JSON: sorted keys, no spaces/BOM, finite values, final LF."""
    return (
        json.dumps(
            _canonical(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _csv_cell(value):
    value = _canonical(value)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return canonical_json(value).decode("utf-8").rstrip("\n")
    if isinstance(value, bool):
        return "true" if value else "false"
    # Python's float repr is the shortest round-trip decimal representation.
    return repr(value) if isinstance(value, float) else value


def _csv_chunks(headers, rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for row in (headers,):
        writer.writerow(row)
        yield buffer.getvalue().encode("utf-8")
    for row in rows:
        buffer.seek(0)
        buffer.truncate(0)
        writer.writerow([_csv_cell(value) for value in row])
        yield buffer.getvalue().encode("utf-8")


def _model_values(instance):
    return {
        field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields
        if field.attname not in INTEGRITY_FIELDS
    }


def _write_member(archive, name, chunks):
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    # Stored members avoid compression-library differences across deployments.
    entry.compress_type = zipfile.ZIP_STORED
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    entry.extra = b""
    entry.comment = b""
    digest = hashlib.sha256()
    with archive.open(entry, "w") as member:
        for chunk in chunks:
            member.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def _readme(run, include_hil):
    return (
        f"ICEEIS 2026 canonical research package, schema {PACKAGE_SCHEMA_VERSION}\n"
        f"Run ID: {run.pk}\n"
        f"DATA SOURCE: {run.source}\n"
        f"EXPERIMENT TYPE: {run.run_type}\n"
        f"STATUS: {run.status}\n\n"
        "REAL denotes supplied physical sensor evidence; it is never generated by this export.\n"
        "SIMULATED demonstration data are not measured FPGA or sensor results.\n"
        "HIL is hardware-in-the-loop evidence, distinct from REAL sensor experiments.\n"
        "SYNTHETIC denotes supplied synthetic signals, distinct from REAL measurements.\n"
        "The source label applies to every file and numerical result in this package.\n\n"
        "Canonical representation\n"
        "Text uses UTF-8 without BOM, LF record terminators, and a final LF.\n"
        "CSV preserves supplied text (including quoted embedded newlines); missing values are empty.\n"
        "CSV is machine-readable research data: import textual cells as text in spreadsheet software.\n"
        "Booleans are true/false; floats use Python shortest round-trip decimal representation.\n"
        "JSON keys are sorted with compact separators; missing values are null; nonfinite values are rejected.\n"
        "Datetimes are UTC ISO 8601 with six fractional digits and Z; dates use YYYY-MM-DD.\n"
        "Samples/events are ordered by timestamp then database ID. Sample IDs and receipt times are retained.\n"
        "ZIP members have a fixed order, stored compression, fixed permissions and 1980-01-01 timestamps.\n"
        "metadata.json includes scientific configuration and lifecycle provenance.\n"
        "dataset_sha256, research_package_sha256 and integrity_generated_at are omitted from metadata\n"
        "to avoid circularity. No current export time is inserted.\n\n"
        "Integrity\n"
        "SHA256SUMS.txt hashes every other archive member, including this README.\n"
        "dataset_sha256 stored on the run equals SHA256(samples.csv).\n"
        "research_package_sha256 stored on the run equals SHA256(the complete ZIP bytes).\n"
        "The ZIP's own hash is stored outside the ZIP and is never embedded in the archive.\n"
        "Repeated exports of unchanged finalized evidence are byte-for-byte identical.\n"
        "Locking changes lifecycle metadata and issues the locked package's hashes.\n"
        "A locked export verifies existing hashes and refuses evidence that differs.\n"
        "Hashes detect changes relative to the stored digest; they are not digital signatures.\n\n"
        "Scientific interpretation\n"
        "Signal analysis excludes invalid packets/CRC failures and mismatched source rows.\n"
        "samples.csv retains those rows as communication evidence.\n"
        "RMSE/MAE and SNR require the explicitly supplied, valid references defined in metrics.json.\n"
        "Precision/recall/F1 require supplied labels; dynamic metrics require valid STEP observations.\n"
        "Bit-exact percentages require integer codes and are never inferred from float equality.\n"
        "Sequence gaps are not proven packet loss; observed sample rate is not FPGA maximum throughput.\n"
        "FPGA resources/latency are supplied values; unavailable values remain empty/null.\n"
        + (
            "hil_references.csv contains independent software references ordered by sequence, sensor and ID.\n"
            "HIL references align by sequence_number and sensor without timestamp interpolation.\n"
            if include_hil
            else "No independent HIL reference records were supplied; no reference file is fabricated.\n"
        )
    ).encode("utf-8")


def _build_package(run):
    # Explicit queryset bypasses the interactive summary cache, including after
    # an out-of-band edit that bypassed normal model invalidation signals.
    summary = run_summary(run, run.samples.all())
    metadata = _model_values(run)
    metadata["research_package_schema_version"] = PACKAGE_SCHEMA_VERSION
    configuration = {
        "source": run.source,
        "run_id": run.pk,
        "filter": {name: getattr(run, name, None) for name in FPGA_FIELDS},
        "implementation": (
            _model_values(run.implementation) if run.implementation else None
        ),
    }
    references = getattr(run, "hil_references", None)
    include_hil = references is not None and references.exists()
    tables = paper_tables(summary)
    hashes = {}
    # Spool larger output to disk instead of retaining independent CSVs and ZIP
    # buffers simultaneously. Analysis itself uses the existing bounded service.
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as spool:
        with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_STORED) as archive:

            def write(name, chunks):
                hashes[name] = _write_member(archive, name, chunks)

            fields = [field.attname for field in SensorSample._meta.concrete_fields]
            write(
                "samples.csv",
                _csv_chunks(
                    fields,
                    run.samples.order_by("timestamp", "id")
                    .values_list(*fields)
                    .iterator(chunk_size=2000),
                ),
            )
            fields = [field.attname for field in EventMarker._meta.concrete_fields]
            write(
                "events.csv",
                _csv_chunks(
                    ["source", *fields],
                    (
                        (run.source, *row)
                        for row in run.events.order_by("timestamp", "id")
                        .values_list(*fields)
                        .iterator(chunk_size=2000)
                    ),
                ),
            )
            write("metadata.json", [canonical_json(metadata)])
            write("metrics.json", [canonical_json(summary)])
            write("fpga_config.json", [canonical_json(configuration)])
            for key, filename in TABLE_FILENAMES.items():
                table = tables[key]
                write(
                    filename,
                    _csv_chunks(
                        [f"Source ({run.source})", *table["headers"]],
                        ((run.source, *row) for row in table["rows"]),
                    ),
                )
            if include_hil:
                fields = [
                    field.attname for field in references.model._meta.concrete_fields
                ]
                write(
                    "hil_references.csv",
                    _csv_chunks(
                        ["source", *fields],
                        (
                            (run.source, *row)
                            for row in references.order_by(
                                "sequence_number", "sensor", "id"
                            )
                            .values_list(*fields)
                            .iterator(chunk_size=2000)
                        ),
                    ),
                )
            write("README.txt", [_readme(run, include_hil)])
            _write_member(
                archive,
                "SHA256SUMS.txt",
                [
                    "".join(
                        f"{digest}  {name}\n" for name, digest in hashes.items()
                    ).encode("utf-8")
                ],
            )
        spool.seek(0)
        data = spool.read()
    return data, hashes["samples.csv"], hashlib.sha256(data).hexdigest()


def generate_package(run, persist=True, *, _initial_lock=False):
    """Return a canonical ZIP, recording or verifying its integrity digests.

    Only the protected lock action uses ``_initial_lock`` after recording the
    lifecycle transition inside its existing transaction. HTTP callers must
    never expose that internal argument. Locked verification never reissues
    missing/mismatched hashes, even when ``persist=False``.
    """
    from .locking import protected_snapshot, update_integrity

    with protected_snapshot(run.pk) as current:
        if current.status not in ("COMPLETED", "LOCKED"):
            raise PackageStateError(
                "Complete the experiment before generating its research package."
            )
        if _initial_lock and (current.status != "LOCKED" or not persist):
            raise PackageStateError(
                "Initial lock issuance requires a locked run and persistence."
            )
        data, dataset_digest, package_digest = _build_package(current)
        if current.status == "LOCKED" and not _initial_lock:
            if (
                current.dataset_sha256 != dataset_digest
                or current.research_package_sha256 != package_digest
                or current.integrity_generated_at is None
            ):
                raise PackageIntegrityError(
                    "Locked research evidence does not match its stored SHA256 integrity record. "
                    "The stored record was not overwritten."
                )
        elif persist and (
            current.dataset_sha256 != dataset_digest
            or current.research_package_sha256 != package_digest
            or current.integrity_generated_at is None
        ):
            update_integrity(
                current,
                dataset_sha256=dataset_digest,
                research_package_sha256=package_digest,
            )
        for name in INTEGRITY_FIELDS:
            setattr(run, name, getattr(current, name))
        return data
