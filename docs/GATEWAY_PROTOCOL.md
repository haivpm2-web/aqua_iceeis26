# PC/gateway HTTP contract

This document specifies the implemented gateway-to-Django API for `aqua_iceeis26`. The acquisition gateway decodes the existing STM32/FPGA transport, preserves supplied values and uploads JSON. This release does not define or implement an FPGA serial framing, register, baud-rate or CRC algorithm; those details must come from the actual firmware.

## Transport and authentication

Use the service's canonical HTTPS origin in production, with trailing slashes on API paths. Send `Content-Type: application/json`, `Accept: application/json` and `Authorization: Bearer <INGEST_API_TOKEN>` for writes. Obtain the token through the deployment's environment/secret configuration; never place it in a URL, source file, exported dataset or browser screenshot. The token permits research writes, including finalization, so it belongs on a trusted gateway. Authenticated staff sessions can also write, with Django CSRF protection. Explicit unlocking requires an authenticated superuser and a reason; the ingestion token alone cannot unlock evidence.

Read endpoints, including research exports, are public by design in this release. Do not upload confidential participant data or private device credentials in experiment metadata.

## Experiment lifecycle

1. Create a run with `POST /api/v1/runs/`. Explicitly supply `source`, `run_type` and reproducibility metadata. The response is HTTP 201 with its `id`.
2. Set `status` to `RUNNING` through `PATCH /api/v1/runs/<id>/` and upload samples with that `run_id`.
3. Flush pending uploads and set `status` to `COMPLETED` with an actual `ended_at` value.
4. Finalize with `POST /api/v1/runs/<id>/lock/` and body `{}`. This issues canonical SHA256 hashes and sets `LOCKED`.
5. Download `GET /api/v1/runs/<id>/research-package/`. Its `X-Research-Package-SHA256` header identifies the downloaded ZIP bytes. The run's `dataset_sha256` identifies the package's canonical `samples.csv`.

Ordinary API/ORM/admin writes cannot modify locked samples, references, events, run metadata or a shared FPGA implementation used by a locked run. A completed run remains editable until explicitly locked. A protected superuser unlock records the prior hashes and reason in an immutable audit entry, returns the run to `COMPLETED`, and clears current integrity fields. Re-finalize after any approved correction.

For an unlocked completed run, `POST /api/v1/runs/<id>/research-package/` generates and records the package hashes; `GET` downloads without recording new hashes. A locked export verifies its stored hashes and returns HTTP 409 if evidence no longer matches. `LOCKED` must be requested through the lock action, never by ordinary run creation/PATCH.

## Source and units

| Value | Meaning |
| --- | --- |
| `REAL` | Supplied measurements from the physical sensor experiment. Never generate these automatically. |
| `HIL` | Supplied hardware-in-the-loop experiment; distinct from a real sensor experiment. |
| `SYNTHETIC` | Supplied synthetic signal experiment with documented provenance. |
| `SIMULATED` | Software demonstration/application verification only; never measured FPGA performance. |

The sample's source must equal its run's source. Omitted sample source inherits the run source, but gateways should send it explicitly. Source cannot change after samples or independent HIL references have been logged. `run_type` describes the experimental procedure and is separate from source: for example, a demonstration may use `run_type: "SYNTHETIC"` with `source: "SIMULATED"`.

Units are DO in mg/L, pH as pH, TDS in ppm and temperature in degrees Celsius. Upload calibrated engineering values and record calibration/scaling in the run metadata. Raw channel fields refer to values before filtering, not necessarily raw ADC integer codes. Supply actual FPGA integer output separately when verifying fixed-point behavior.

## Sample fields

| Field | JSON type / interpretation |
| --- | --- |
| `run_id` | Required positive existing experiment ID. |
| `timestamp` | Acquisition timestamp; use an ISO 8601 timezone, preferably UTC `Z`. Always supply this for research. If omitted, the server assigns its current time. |
| `sequence_number` | Optional nonnegative integer, up to signed 64-bit database range. Strongly recommended for communication and HIL alignment. |
| `do_raw`, `ph_raw`, `tds_raw`, `temperature_raw` | Required finite numbers for `packet_valid: true`. May be omitted/null for a retained invalid packet. |
| `do_filtered`, `ph_filtered`, `tds_filtered`, `temperature_filtered` | Optional finite supplied filter outputs. The server does not infer missing FPGA outputs. |
| `noise_estimate`, `adaptive_threshold` | Optional nonnegative finite values in documented device/algorithm units. |
| `alpha_value` | Optional finite coefficient in [0, 1]. |
| `alpha_code` | Optional nonnegative integer coefficient code. Record its Q format in the run. |
| `signal_state` | `STABLE`, `NORMAL`, `NOISY`, `TRANSIENT`, `OUTLIER` or `UNKNOWN` (default). |
| `quality_flag` | `NORMAL` (default), `SPIKE`, `OUT_OF_RANGE`, `SENSOR_FAULT`, `TRANSIENT` or `NOISY`. |
| `outlier_detected`, `transient_detected` | Boolean device/algorithm flags; default false. These are not ground-truth labels. |
| `fpga_cycles` | Optional nonnegative integer measured processing cycles. |
| `fpga_latency_us` | Optional nonnegative finite supplied processing latency in microseconds. Omit when unmeasured. |
| `packet_valid` | Boolean; default true. Explicitly false for retained malformed/invalid packets. |
| `packet_crc_ok` | Boolean or null; null means the CRC result is unavailable, not verified success. |
| `source` | `REAL`, `HIL`, `SYNTHETIC` or `SIMULATED`; must match the run. |
| `sensor_status` | Optional object keyed by `do`, `ph`, `tds`, `temperature`; values `OK`, `NOISY`, `OUTLIER`, `OUT_OF_RANGE`, `SENSOR_FAULT`, `OFFLINE`. |
| `extra_sensors` | Optional JSON object preserving additional named measurements and their documented units. |

All numerical values must be finite with magnitude at most `1e100`; individual field limits can be narrower. Do not send NaN or Infinity. Unknown top-level fields are rejected. `id` and `received_at` are server-managed response fields; `received_at` is receipt time and must not be treated as FPGA processing latency. Acquisition clocks over `MAX_SAMPLE_FUTURE_SECONDS` (default 300) ahead of the server are rejected. No timestamp interpolation or device clock correction is performed.

Invalid packets and CRC failures are retained as communication evidence and excluded from signal analysis. Quality/range checks do not overwrite supplied channel values. Per-sensor validity ranges can be configured in the run's `sensor_configuration.validity_ranges`, for example `{"do": [0, 30], "ph": [0, 14]}`.

## Single-sample endpoint

`POST /api/v1/samples/` accepts one sample object and returns HTTP 201 with `{"created": 1, "ids": [<database_id>]}`.

The following is a **SIMULATED software example**, with no FPGA timing or integer-code measurement. Replace run ID 123 with an existing dedicated SIMULATED run. Use the actual acquisition timestamp when connecting a real gateway.

```json
{
  "run_id": 123,
  "timestamp": "2026-09-10T03:00:00.000000Z",
  "sequence_number": 0,
  "do_raw": 6.54,
  "do_filtered": 6.51,
  "ph_raw": 7.43,
  "ph_filtered": 7.41,
  "tds_raw": 422.0,
  "tds_filtered": 420.5,
  "temperature_raw": 27.53,
  "temperature_filtered": 27.51,
  "noise_estimate": 0.05,
  "adaptive_threshold": 0.2,
  "alpha_value": 0.125,
  "alpha_code": null,
  "signal_state": "STABLE",
  "quality_flag": "NORMAL",
  "outlier_detected": false,
  "transient_detected": false,
  "fpga_cycles": null,
  "fpga_latency_us": null,
  "packet_valid": true,
  "packet_crc_ok": null,
  "source": "SIMULATED"
}
```

## Batch endpoint and delivery behavior

`POST /api/v1/samples/batch/` accepts either a JSON array of sample objects or an object containing only the `samples` array. Prefer batches of **50–200 samples per HTTP transaction** when acquisition rate, latency and connection capacity allow. The implemented hard limit is 5,000 samples per request; the request body limit is 12 MiB. Use smaller batches when the connection/proxy imposes a tighter limit.

```json
{
  "samples": [
    {"run_id": 123, "timestamp": "2026-09-10T03:00:00.000000Z", "sequence_number": 0, "do_raw": 6.54, "ph_raw": 7.43, "tds_raw": 422.0, "temperature_raw": 27.53, "source": "SIMULATED"},
    {"run_id": 123, "timestamp": "2026-09-10T03:00:00.010000Z", "sequence_number": 1, "do_raw": 6.52, "ph_raw": 7.42, "tds_raw": 421.0, "temperature_raw": 27.52, "source": "SIMULATED"}
  ]
}
```

Success is HTTP 201 with `created` equal to the requested count and `ids` listing inserted records. Sample validation and database insertion are atomic for the whole request. If any sample is invalid, HTTP 400 is returned and no samples from that request are committed. Locked-run writes are also rejected with HTTP 400. Authentication failure returns 401; insufficient authenticated permission can return 403. Invalid URLs or nonexistent resources may return 404, unsupported methods 405, and infrastructure/body limits may return other errors.

There is **no ingestion idempotency key or unique sample sequence constraint**. Repeated sequence numbers are intentionally retained so duplicate/reordered packets can be analyzed. After a timeout or disconnected response, the transaction may already have committed. Keep a durable local upload log and reconcile observed run history before retrying an uncertain batch. Do not blindly retry writes. HTTP errors should be logged without tokens; retry only known transient failures after accounting for this ambiguity. Start a new run for a sequence reset/wrap when deterministic HIL matching is required.

`GET /api/v1/latest/?run_id=<id>` selects the latest received packet, guarding against device clock skew. `GET /api/v1/history/?run_id=<id>&limit=200&page=1` returns a bounded window ordered by acquisition timestamp then database ID. Page 1 contains the newest window; each window is returned in chronological order. `downsample=500` evenly selects the full filtered interval and retains both endpoints when at least two points are requested; it is for display, not statistical inference. These reads also support explicit aware `start`/`end` bounds. Sequence gaps are observations, not proof of packet loss.

## References and HIL alignment

For sensor-reference error metrics, supply `<sensor>_reference`, `reference_source`, and an aligned `reference_timestamp` where available. A mismatched explicit reference timestamp excludes that reference from error calculations. Ground truth is never created from the filtered output. Supply `ground_truth_spike` only when independently labelled; leave it null otherwise.

Per-sample fixed-point comparison fields are `<sensor>_software_reference`, `<sensor>_software_code`, and `<sensor>_fpga_code`, where `<sensor>` is `do`, `ph`, `tds` or `temperature`. The supplied FPGA floating output is `<sensor>_filtered`. Integer codes use signed 64-bit values, sent as exact JSON integers, with numerical/Q-format settings recorded on the run. No generic top-level `fpga_output` field is accepted: use the channel-specific filtered value.

Independent software outputs can arrive through `POST /api/v1/runs/<id>/hil-references/`, as one object or an array of 1–5,000 objects:

```json
{
  "sensor": "do",
  "sequence_number": 10,
  "software_reference": 6.5,
  "software_integer_code": 1664,
  "reference_source": "SIMULATED Q8 fractional-bit example; replace with actual reference provenance"
}
```

This numerical example describes software only; it is not a claim of an actual FPGA match. The actual reference endpoint permits HIL, SYNTHETIC and SIMULATED runs. At least one of `software_reference` or `software_integer_code` is required. `(run, sensor, sequence_number)` is unique for independent references, and duplicate-key batches are rejected atomically. Pairing uses sequence number and sensor; timestamp interpolation is not implemented. Ambiguous duplicate received sample sequences are excluded from independent pairing, with counts reported in fixed-point metrics. Bit-exact agreement requires paired integer codes and is never inferred from floating-point equality.

## Run reproducibility metadata

Record sampling frequency, `input_q_format`, `output_q_format`, `accumulator_q_format`, `coefficient_q_format`, `rounding_mode`, `saturation_mode` and `fpga_clock_hz` when known. Record applicable `alpha_stable`, `alpha_normal`, `alpha_noisy`, `alpha_transient`, `beta_noise`, `threshold_base`, `threshold_multiplier`, `median_window` and `persistence_samples`. Do not infer hardware configuration from the demonstration generator.

Keep `filter_version`, `firmware_version`, `fpga_bitstream_version`, `software_git_commit`, `fpga_git_commit`, `stm32_git_commit`, `gateway_git_commit`, `sensor_configuration`, `sensor_model`, `calibration_date`, `calibration_method`, `calibration_coefficients`, `reference_instrument` and `experiment_notes` with each experiment. Optional metadata remains optional for historical runs; unknown values should stay missing. FPGA resource entries must be traceable to supplied Vivado reports. HTTP upload duration and measured server request capacity are application metrics, never FPGA throughput.

## Reproducible application verification

Supply the write token through `INGEST_API_TOKEN` (or another variable named by `--token-env`) and run:

```text
python scripts/verify_release.py --base-url http://127.0.0.1:8000 --counts 1000 10000 50000 --batch-size 200 --output-dir evidence/release-local
python scripts/verify_browser.py --base-url http://127.0.0.1:8000 --run-ids 3 4 5 --output-dir evidence/browser-local
```

Use the actual run IDs printed by the first command. On Railway, substitute the actual public HTTPS origin and use `--run-prefix SIMULATED_RAILWAY_TEST`; the same HTTP tests can use `--counts 1000 10000`. Every release verification invocation creates new explicitly SIMULATED runs and locks only those new runs. It does not generate REAL/HIL evidence. Browser verification uses existing COMPLETED/LOCKED SIMULATED runs and checks charts, comparison, mobile, PNG/CSV/PDF and research ZIP downloads.
