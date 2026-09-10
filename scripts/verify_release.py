"""Exercise a running local/remote server with isolated SIMULATED datasets.

Uses only Python's standard library. Supply INGEST_API_TOKEN in the environment.
Every invocation creates new runs; existing REAL/HIL/SYNTHETIC data is untouched.
Recorded timings describe HTTP/application behavior, never FPGA performance.
"""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACKAGE_FILES = {
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
    "SHA256SUMS.txt",
    "README.txt",
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def validated_base_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise argparse.ArgumentTypeError(
            "Use an HTTP(S) origin without credentials, path, or query."
        )
    return value.rstrip("/")


def csv_evidence(stream, expected_count=None):
    rows = csv.DictReader(stream)
    check(
        rows.fieldnames and "source" in rows.fieldnames, "CSV source column is missing"
    )
    count, sources = 0, Counter()
    for row in rows:
        count += 1
        sources[row["source"]] += 1
    if expected_count is not None:
        check(count == expected_count, f"CSV count {count} != {expected_count}")
    check(set(sources) == {"SIMULATED"}, f"Unexpected CSV sources: {dict(sources)}")
    return {"rows": count, "sources": dict(sources)}


def verify_package(path, expected_count=None):
    """Validate the actual downloaded ZIP and each manifest entry, without extraction."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        check(len(members) == len(set(members)), "ZIP contains duplicate filenames")
        check(
            PACKAGE_FILES <= set(members),
            f"Missing ZIP entries: {PACKAGE_FILES - set(members)}",
        )
        manifest = {}
        for line in archive.read("SHA256SUMS.txt").decode("utf-8").splitlines():
            if not line.strip():
                continue
            digest, filename = line.split(maxsplit=1)
            filename = filename.lstrip(" *")
            check(filename not in manifest, f"Duplicate SHA256 entry: {filename}")
            check(
                len(digest) == 64 and all(c in "0123456789abcdef" for c in digest),
                f"Invalid SHA256 digest for {filename}",
            )
            manifest[filename] = digest
        check(
            set(members) - {"SHA256SUMS.txt"} == set(manifest),
            "SHA256SUMS must cover every other ZIP member exactly once",
        )
        for name, expected in manifest.items():
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            check(actual == expected, f"SHA256 mismatch: {name}")
        check(
            "SIMULATED" in archive.read("README.txt").decode("utf-8"),
            "Package README lost its SIMULATED source label",
        )
        metadata = json.loads(archive.read("metadata.json"))
        run_metadata = metadata.get("run", metadata)
        check(
            run_metadata.get("source") == "SIMULATED",
            "Metadata source is not SIMULATED",
        )
        metrics = json.loads(archive.read("metrics.json"))
        configuration = json.loads(archive.read("fpga_config.json"))
        check(metrics.get("source") == "SIMULATED", "Metrics source is not SIMULATED")
        check(
            configuration.get("source") == "SIMULATED",
            "FPGA configuration lost its source",
        )
        for filename in sorted(
            name for name in PACKAGE_FILES if name.startswith("table_")
        ):
            table = list(
                csv.reader(io.StringIO(archive.read(filename).decode("utf-8")))
            )
            check(
                table and "SIMULATED" in table[0][0],
                f"Table source header missing: {filename}",
            )
            check(
                all(row[0] == "SIMULATED" for row in table[1:]),
                f"Table row source missing: {filename}",
            )
        with archive.open("samples.csv") as raw:
            samples = csv_evidence(
                io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), expected_count
            )
    with path.open("rb") as package:
        digest = hashlib.file_digest(package, "sha256").hexdigest()
    return {
        "sha256": digest,
        "dataset_sha256": manifest["samples.csv"],
        "members": len(members),
        "verified_hashes": len(manifest),
        "samples": samples,
        "bytes": path.stat().st_size,
    }


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the ingestion credential to a different origin."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        original = urllib.parse.urlsplit(request.full_url)
        target = urllib.parse.urlsplit(new_url)
        if (original.scheme, original.netloc) != (target.scheme, target.netloc):
            raise RuntimeError(
                "Cross-origin redirect refused; supply the canonical public --base-url."
            )
        if request.method not in ("GET", "HEAD"):
            raise RuntimeError(
                "Write redirect refused; supply the canonical public --base-url."
            )
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


class Client:
    def __init__(self, base_url, token, timeout, report):
        self.base_url, self.token = base_url, token
        self.timeout, self.report = timeout, report
        self.opener = urllib.request.build_opener(SameOriginRedirect())

    def request(
        self, method, path, payload=None, *, output=None, expected=200, label=None
    ):
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "aqua-iceeis26-release-verification",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if method not in ("GET", "HEAD"):
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(
            self.base_url + path, data=body, headers=headers, method=method
        )
        start = time.perf_counter()
        entry = {"check": label or f"{method} {path}", "method": method, "path": path}
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code != expected:
                    raise
                response = exc
            with response:
                entry["status"] = response.status
                encoding = response.headers.get("Content-Encoding", "identity").lower()
                entry["content_encoding"] = encoding
                check(
                    encoding in ("identity", "gzip"),
                    f"Unsupported HTTP content encoding: {encoding}",
                )
                content = (
                    gzip.GzipFile(fileobj=response) if encoding == "gzip" else response
                )
                if output is not None:
                    size = 0
                    with Path(output).open("wb") as target:
                        while chunk := content.read(1024 * 1024):
                            size += target.write(chunk)
                    data = None
                    entry["bytes"] = size
                else:
                    raw = content.read()
                    entry["bytes"] = len(raw)
                    data = (
                        json.loads(raw)
                        if "json" in response.headers.get("Content-Type", "")
                        else raw
                    )
                check(
                    response.status == expected,
                    f"{method} {path}: HTTP {response.status}, expected {expected}",
                )
            entry["result"] = "PASS"
            return data
        except urllib.error.HTTPError as exc:
            entry.update(status=exc.code, result="FAIL")
            detail = (
                exc.read(3000)
                .decode("utf-8", errors="replace")
                .replace(self.token, "[REDACTED]")
            )
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {detail}") from None
        except Exception:
            entry["result"] = "FAIL"
            raise
        finally:
            entry["seconds"] = round(time.perf_counter() - start, 6)
            self.report["requests"].append(entry)


def simulated_samples(run_id, count, seed, start, sample_rate=100):
    """Deterministic software fixture; intentionally supplies no FPGA measurements."""
    rng = random.Random(seed)
    channels = {
        "do": (6.5, 0.05),
        "ph": (7.4, 0.02),
        "tds": (420.0, 2.0),
        "temperature": (27.5, 0.03),
    }
    previous = {sensor: base for sensor, (base, _) in channels.items()}
    for index in range(count):
        sample = {
            "run_id": run_id,
            "sequence_number": index,
            "source": "SIMULATED",
            "timestamp": (start + timedelta(seconds=index / sample_rate)).isoformat(),
            "packet_valid": True,
            "packet_crc_ok": True,
            "signal_state": "STABLE",
            "quality_flag": "NORMAL",
            "noise_estimate": 0.05,
            "adaptive_threshold": 0.2,
            "alpha_value": 0.125,
            "reference_source": "SIMULATED deterministic software fixture; no physical reference instrument",
        }
        for sensor, (base, noise) in channels.items():
            reference = base + noise * math.sin(index / 100)
            raw = reference + rng.gauss(0, noise)
            filtered = previous[sensor] + 0.125 * (raw - previous[sensor])
            previous[sensor] = filtered
            sample.update(
                {
                    sensor + "_raw": raw,
                    sensor + "_filtered": filtered,
                    sensor + "_reference": reference,
                }
            )
        yield sample


def verify_run(client, count, seed, batch_size, prefix, out, report):
    started = datetime.now(timezone.utc) - timedelta(seconds=count / 100 + 1)
    name = f"{prefix}_{count}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{seed}"
    run = client.request(
        "POST",
        "/api/v1/runs/",
        {
            "run_name": name,
            "run_type": "SYNTHETIC",
            "source": "SIMULATED",
            "status": "CREATED",
            "started_at": started.isoformat(),
            "sampling_rate_hz": 100,
            "filter_version": "SIMULATED software IIR fixture (not measured FPGA output)",
            "sensor_configuration": {
                "seed": seed,
                "sample_rate_hz": 100,
                "purpose": "HTTP application release verification",
            },
            "notes": "SIMULATED application verification only. No physical FPGA, sensor, latency or throughput claims.",
        },
        expected=201,
    )
    run_id = run["id"]
    record = {
        "id": run_id,
        "name": name,
        "sample_count": count,
        "source": "SIMULATED",
        "seed": seed,
        "result": "RUNNING",
    }
    report["runs"].append(record)
    check(
        run["source"] == "SIMULATED" and run["status"] == "CREATED",
        "New run source/status mismatch",
    )
    client.request("PATCH", f"/api/v1/runs/{run_id}/", {"status": "RUNNING"})
    begin, batch, batch_count = time.perf_counter(), [], 0
    for sample in simulated_samples(run_id, count, seed, started):
        batch.append(sample)
        if len(batch) == batch_size:
            result = client.request(
                "POST",
                "/api/v1/samples/batch/",
                {"samples": batch},
                expected=201,
                label=f"Run {run_id}: batch {batch_count + 1}",
            )
            check(result["created"] == len(batch), "Batch created count mismatch")
            batch, batch_count = [], batch_count + 1
    if batch:
        result = client.request(
            "POST",
            "/api/v1/samples/batch/",
            {"samples": batch},
            expected=201,
            label=f"Run {run_id}: batch {batch_count + 1}",
        )
        check(result["created"] == len(batch), "Final batch created count mismatch")
        batch_count += 1
    record["http_ingestion"] = {
        "seconds": round(time.perf_counter() - begin, 6),
        "batches": batch_count,
        "batch_size": batch_size,
        "meaning": "HTTP/application timing only; not FPGA throughput",
    }
    ended = started + timedelta(seconds=(count - 1) / 100)
    completed = client.request(
        "PATCH",
        f"/api/v1/runs/{run_id}/",
        {"status": "COMPLETED", "ended_at": ended.isoformat()},
    )
    check(completed["status"] == "COMPLETED", "Run was not completed")
    latest = client.request("GET", f"/api/v1/latest/?run_id={run_id}")["sample"]
    check(
        latest["sequence_number"] == count - 1 and latest["source"] == "SIMULATED",
        "Latest sample mismatch",
    )
    history = client.request("GET", f"/api/v1/history/?run_id={run_id}&limit=100")
    check(
        history["count"] == count and len(history["results"]) == min(100, count),
        "History count/window mismatch",
    )
    check(
        all(row["source"] == "SIMULATED" for row in history["results"]),
        "History source label missing",
    )
    history = client.request("GET", f"/api/v1/history/?run_id={run_id}&downsample=500")
    check(
        history["count"] == count and len(history["results"]) == min(500, count),
        "Downsample size mismatch",
    )
    check(
        history["results"][0]["sequence_number"] == 0
        and history["results"][-1]["sequence_number"] == count - 1,
        "Downsample failed to preserve endpoints",
    )
    summary = client.request("GET", f"/api/v1/runs/{run_id}/stats/")
    check(
        summary["sample_count"] == count and summary["analysis_count"] == count,
        "Statistics count mismatch",
    )
    check(summary["source"] == "SIMULATED", "Statistics lost source")
    check(
        summary["latency"]["mean"] is None,
        "Fixture unexpectedly has measured FPGA latency",
    )
    check(
        summary["implementation"] is None,
        "Fixture unexpectedly has FPGA synthesis evidence",
    )
    record["statistics"] = {
        "sample_count": summary["sample_count"],
        "analysis_count": summary["analysis_count"],
        "source": summary["source"],
    }
    tables = client.request("GET", f"/api/v1/runs/{run_id}/tables/")
    check(set("ABCDE") <= set(tables), "One or more paper tables are missing")
    for route in (
        f"/runs/{run_id}/",
        f"/runs/{run_id}/paper/",
        f"/compare/?run_id={run_id}",
        "/system/",
    ):
        client.request("GET", route)
    csv_path = out / f"run-{run_id}-simulated.csv"
    client.request("GET", f"/api/v1/runs/{run_id}/export/", output=csv_path)
    with csv_path.open(encoding="utf-8-sig", newline="") as samples:
        record["csv"] = csv_evidence(samples, count)
    lock = client.request("POST", f"/api/v1/runs/{run_id}/lock/", {})
    check(lock["status"] == "LOCKED", "Run was not locked")
    client.request(
        "PATCH",
        f"/api/v1/runs/{run_id}/",
        {"notes": "SIMULATED rejection probe"},
        expected=400,
        label=f"Run {run_id}: locked metadata modification rejected",
    )
    rejected_sample = next(simulated_samples(run_id, 1, seed, started))
    client.request(
        "POST",
        "/api/v1/samples/",
        rejected_sample,
        expected=400,
        label=f"Run {run_id}: locked sample ingestion rejected",
    )
    package_path = out / f"run_{run_id}_research_package.zip"
    client.request(
        "GET", f"/api/v1/runs/{run_id}/research-package/", output=package_path
    )
    record["research_package"] = verify_package(package_path, count)
    repeated = client.request(
        "GET",
        f"/api/v1/runs/{run_id}/research-package/",
        label=f"Run {run_id}: repeated canonical package export",
    )
    check(
        hashlib.sha256(repeated).hexdigest() == record["research_package"]["sha256"],
        "Repeated package export is not byte-for-byte deterministic",
    )
    run = client.request("GET", f"/api/v1/runs/{run_id}/")
    check(
        run["research_package_sha256"] == record["research_package"]["sha256"],
        "Stored package digest differs from downloaded ZIP",
    )
    check(
        len(run["dataset_sha256"]) == 64 and run["integrity_generated_at"],
        "Dataset integrity metadata missing",
    )
    check(
        run["dataset_sha256"] == record["research_package"]["dataset_sha256"],
        "Stored dataset hash differs from the canonical samples.csv",
    )
    record.update(
        status=run["status"], dataset_sha256=run["dataset_sha256"], result="PASS"
    )
    print(
        json.dumps(
            {
                "run_id": run_id,
                "sample_count": count,
                "source": "SIMULATED",
                "result": "PASS",
                "http_ingestion_seconds": record["http_ingestion"]["seconds"],
            }
        ),
        flush=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", type=validated_base_url, default="http://127.0.0.1:8000"
    )
    parser.add_argument("--counts", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--run-prefix", default="SIMULATED_RELEASE_TEST")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("evidence/release-local")
    )
    parser.add_argument(
        "--timeout", type=float, default=300, help="HTTP timeout in seconds"
    )
    parser.add_argument(
        "--token-env",
        default="INGEST_API_TOKEN",
        help="Environment variable containing the write token",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 5000 or any(
        not 100 <= n <= 100000 for n in args.counts
    ):
        parser.error("Use batch size 1-5000 and counts 100-100000.")
    if not args.run_prefix.startswith("SIMULATED") or len(args.run_prefix) > 100:
        parser.error(
            "--run-prefix must start with SIMULATED and be at most 100 characters."
        )
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number.")
    token = os.environ.get(args.token_env, "")
    if not token:
        parser.error(f"{args.token_env} must be supplied through the environment.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "base_url": args.base_url,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": "SIMULATED",
        "notice": "Application verification only. No measured sensor/FPGA results.",
        "runs": [],
        "requests": [],
        "result": "RUNNING",
    }
    client = Client(args.base_url, token, args.timeout, report)
    try:
        health = client.request("GET", "/health/")
        check(
            health.get("status") == "ok" and health.get("database") == "ok",
            "Health check failed",
        )
        report["health"] = health
        client.request("GET", "/api/v1/runs/?limit=1")
        for index, count in enumerate(args.counts):
            verify_run(
                client,
                count,
                args.seed + index,
                args.batch_size,
                args.run_prefix,
                args.output_dir,
                report,
            )
        report["result"] = "PASS"
    except Exception as exc:
        report.update(result="FAIL", error=str(exc).replace(token, "[REDACTED]"))
        print(report["error"], file=sys.stderr)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (args.output_dir / "release-checks.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "result": report["result"],
                "run_ids": [run["id"] for run in report["runs"]],
                "evidence": str(args.output_dir / "release-checks.json"),
            }
        ),
        flush=True,
    )
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
