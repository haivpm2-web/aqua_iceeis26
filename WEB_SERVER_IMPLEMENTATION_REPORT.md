# Web Server Implementation Report

Project: FPGA-Accelerated Edge Denoising of High-Frequency Water-Quality Sensor Data for Aquaculture Monitoring — IEEE ICEEIS 2026.

Date: 2026-09-09. Status: implementation and local integrated verification completed. **Railway configuration is prepared; deployment has not been performed or verified.**

## 1. Existing-system audit

The original audit is preserved in `IMPLEMENTATION_PLAN.md`: the workspace contained a Django project, WSGI/ASGI entry points, a monitoring placeholder, a static health response and backend dependency choices. It had no existing models, migrations, templates, serial/MQTT adapters, automated tests or deployment manifests to preserve. The implementation retained the `config` project and `monitoring` app and expanded them in place. No framework migration was made.

No `AGENTS.md` was found in the initial audit. The workspace has no Git history available for an independent original diff, so original-file classification below follows the initial inventory.

## 2. Files modified and created

Modified existing project files: `config/settings.py`, `config/urls.py`, `monitoring/views.py`, `monitoring/urls.py`, and `requirements.txt`. Project entry points `manage.py`, `config/wsgi.py` and `config/asgi.py` received formatting changes and remain in use.

Added implementation files:

- `monitoring/models.py`, `serializers.py`, `api.py`, `services.py`, `analysis.py`, `tables.py`, and `admin.py`.
- `monitoring/migrations/0001_initial.py` and package initializers.
- `monitoring/templates/monitoring/dashboard.html` and `monitoring/static/monitoring/dashboard.{js,css}`.
- Vendored Chart.js under `monitoring/static/monitoring/vendor/`, including its license and source map.
- `monitoring/management/commands/simulate_sensor.py` and command package initializers.
- `monitoring/tests.py`, `monitoring/test_api_review.py`, `monitoring/test_science_review.py`, and `scripts/verify_browser.py`.
- `Dockerfile`, `.dockerignore`, `railway.json`, `.env.example`, `.gitignore`, `IMPLEMENTATION_PLAN.md`, `README.md`, this report and `WEB_SERVER_TEST_REPORT.md`.

`db.sqlite3`, `.venv/`, `staticfiles/` and validation logs/artifacts are local/generated runtime material, not application source. Direct production dependency versions are pinned to the installed versions used for local verification. The Dockerfile and legacy Railway start command agree and send access/error logs to container streams.

## 3. Database schema

| Entity | Stored information |
| --- | --- |
| `ExperimentRun` | Name/type/status, source, start/end/create timestamps, description/notes, sensor configuration JSON, filter/bitstream/firmware versions, optional FPGA implementation |
| `SensorSample` | Run and timestamps, sequence, four channels with raw/filtered/sensor-reference/software-reference fields, integer verification codes, quality/state flags, detector labels, latency/cycles, adaptive values, validity/CRC, source, per-sensor health, extra sensors and reference provenance |
| `FPGAImplementation` | Report provenance, clock/max clock, slack, power and optional LUT/FF/DSP/BRAM used/available values |
| `EventMarker` | Run/time/sensor, event type/state, optional raw/filtered/threshold values, JSON ground-truth metadata |

Samples index timestamps, receipt timestamps, `(run, timestamp)` and `(run, sequence_number)`. Repeated sequence numbers are retained as evidence. Deleting a run cascades to its samples/events only through protected administration. Source checks prevent API ingestion from mixing REAL, SIMULATED and HIL samples in one run. Optional measurements remain nullable.

## 4. API endpoints and authentication

Implemented API surface:

- POST `/api/v1/samples/` and `/api/v1/samples/batch/`.
- GET `/api/v1/latest/`, `/api/v1/history/`, `/api/v1/status/` and `/health/`.
- GET/POST `/api/v1/runs/`; GET/PATCH `/api/v1/runs/<id>/`.
- GET run `/samples/`, `/stats/`, `/summary/`, `/export/`, and `/tables/` endpoints.
- POST `/api/v1/runs/<id>/import/`.
- GET/POST `/api/v1/implementations/` and `/api/v1/events/`.

Read access is public. Writes require a configured Bearer token or staff-session authentication with CSRF. Destructive operations use Django admin permissions. Single/batch ingestion uses serializer validation and atomic bulk storage, including generated quality events. Sample history is bounded and supports run, channel, time interval, quality/state, pagination and downsampling. CSV export streams all available sample fields; import reports successes/failures and row-level errors rather than silently discarding bad records.

The complete field contract, limits, example requests, source distinctions and import mapping are documented in `README.md`.

## 5. Dashboard pages

Dashboard `/`, Experiments `/runs/`, detail `/runs/<id>/`, Live Data `/live/`, Analysis `/analysis/`, Compare `/compare/`, FPGA `/fpga/`, Events `/events/`, Paper `/paper/` and `/runs/<id>/paper/`, System `/system/`, and Admin `/admin/` are routed through Django templates.

The responsive interface includes four sensor plots and adaptive-filter diagnostics, automatically refreshed data without a page reload, a selected run/window, raw/filtered labels and units, source identification, sensor health, FPGA and packet summaries. Detailed analysis uses server-calculated metrics. Comparison supports 2–5 runs. Paper view offers white/print layouts, exportable PNG plots and tables A–E. Missing evidence appears as N/A or awaiting experimental data, and simulated captions are preserved.

## 6. Scientific metrics

The independent analysis service computes population statistics, unscaled MAD, aligned raw/filtered reductions, reference error, defined reference-power SNR, labelled outlier classification/removal, fixed-point comparison, explicit STEP response, latency percentiles and receipt-order communication metrics. Formula details are in the README.

Scientific safeguards:

- Invalid packet/CRC rows remain in communication analysis and are excluded from signal metrics.
- Sensor/reference-meter values and software algorithm output are stored separately.
- MAE/RMSE/SNR require supplied aligned references. No automatic time alignment is inferred from a reference timestamp.
- Precision/recall/F1 require true spike labels; rejection/false-removal rates additionally require observed removal labels.
- Bit-exact percentages require paired integer codes; float equality is not used as bit evidence.
- STEP response requires a supplied event timestamp and declared initial/target/tolerance/hold metadata.
- Latency uses transmitted measurements; observed sample timestamp rate is labelled separately from FPGA maximum capacity.
- Sequence gaps cover observed min/max IDs under one monotonic sequence per run. They are not labelled proven loss; dropped packets remain unknown.
- Vivado resource/frequency/power fields have no invented defaults.

## 7. Paper tables

| Table | Available content |
| --- | --- |
| A — Denoising | Sensor/method, raw/filtered SD and MAD, SD reduction, Δ-SNR and reference RMSE |
| B — Dynamic response | Method/sensor, delay, rise/fall, settling and overshoot for defined STEP events |
| C — FPGA | Method, supplied LUT/FF/DSP/BRAM, measured mean latency and observed rate |
| D — Fixed point | Method/sensor, paired count, MAE, RMSE, max error and integer-code agreement |
| E — Communication | Received/valid/invalid, unknown dropped count, sequence gaps and received-denominator success |

Tables are shared between browser rendering and downloadable CSV. Undefined values remain N/A. Actual paper results still require physical or clearly declared synthetic experiments.

## 8. Testing results

Executed locally on Windows with Python 3.14.6, Django 5.2.17 and SQLite:

- Django `check`, `makemigrations --check`, `migrate --noinput`, and `collectstatic --noinput`: PASS.
- All 47 automated tests: PASS, with no failures or errors.
- Production settings `check --deploy` with a generated ephemeral strong secret: PASS, no issues.
- Dependency consistency and JavaScript syntax checks: PASS.
- Local server is running at `http://127.0.0.1:8000/`; `/health/` returned HTTP 200 and database `ok`.
- Two isolated SIMULATED experiments were created, IDs 1 and 2, each with 1,000 samples. Run 2 includes a simulated STEP marker. No real data were generated or substituted.
- Chromium verified eleven main routes, populated charts, two-run comparison, a 100-sample display window, PNG/CSV downloads, paper screenshot/PDF output and mobile layout with no JavaScript errors.

See `WEB_SERVER_TEST_REPORT.md` for test coverage and earlier errors fixed. Machine-readable browser evidence and explicitly labelled demonstration screenshots/exports are in `evidence/`. Real PostgreSQL, Docker/Linux/Gunicorn and Railway remote runtime checks remain unexecuted.

## 9. Railway deployment status

Not deployed. No remote service URL, PostgreSQL migration execution, Docker build, Linux Gunicorn runtime, TLS routing, or remote smoke test is claimed without the final evidence report.

Prepared components: Python 3.12 Dockerfile with non-root user, pinned direct requirements, PostgreSQL adapter/`DATABASE_URL`, strong production secret requirements, secure proxy/cookie settings, static collection/WhiteNoise, Gunicorn port binding, database readiness endpoint, migration pre-deploy command and restart/health configuration.

Current Railway documentation says legacy `railway.json` configuration is deprecated for new services and existing support ends 2026-12-01. The README supplies equivalent dashboard settings for a new service while retaining the existing manifest. References: [Railway config](https://docs.railway.com/guides/config-as-code), [health checks](https://docs.railway.com/guides/healthchecks), [pre-deploy commands](https://docs.railway.com/guides/pre-deploy-command).

## 10. Known limitations

- Physical STM32/SPI/FPGA/gateway integration cannot be validated without hardware and a wire protocol. No serial/MQTT adapter previously existed.
- Public dashboard/read access and a shared write token are the implemented access model. There is no per-device token lifecycle, tenant isolation or external identity provider.
- Full-run analyses are bounded in memory (default 200,000 samples) with a short process-local cache. There is no background worker/materialized analysis pipeline. Chart downsampling is a display subset and may omit short events.
- References must already be aligned to rows; no meter-log timestamp matching/interpolation is implemented.
- Additional channels are preserved in JSON; automatic plots/statistics for new sensors need explicit registration.
- Packet-loss claims require a known sender count/protocol; resets and wraps require run separation or protocol-aware future analysis.
- STEP metrics use sampled records and reported transient flags. Instrument synchronization and sufficient observation duration remain experimental prerequisites.
- Direct dependencies are pinned, but the base Docker image/transitive dependency graph are not completely locked. Remote deployment, PostgreSQL-specific runtime and capacity remain unverified unless the final test report records them.
- A simulated demonstration is interface validation and cannot substantiate measured FPGA latency, synthesis, denoising or communication claims.

## 11. Local operation and deployment instructions

See `README.md` for complete PowerShell setup, environment variables, migration/admin/simulation/server commands, test commands, staff/Bearer authentication, CSV import and Railway dashboard setup. No automatic `.env` loader or default admin credential is supplied. SQLite is local-only; use Railway PostgreSQL and database backups for durable records.

## 12. Example API payload

Illustrative payload only; replace the ID/timestamp and all numbers with actual acquisition values:

```json
{
  "run_id": 12,
  "timestamp": "2026-09-09T10:20:30.123Z",
  "sequence_number": 15234,
  "do_raw": 6.72,
  "do_filtered": 6.65,
  "ph_raw": 7.43,
  "ph_filtered": 7.39,
  "tds_raw": 420.5,
  "temperature_raw": 27.6,
  "fpga_latency_us": 1.24,
  "quality_flag": "NORMAL",
  "signal_state": "STABLE",
  "packet_valid": true
}
```

Optional ground-truth, software reference, code verification, STEP event and synthesis examples are documented in the README. Missing filtered, latency and reference fields remain unknown.

## 13. Missing physical/Vivado inputs

Needed to produce publication evidence: real packet/gateway specifications and clock/sequence behavior; instrument calibration and actual sensor data; filter/firmware/bitstream/software versions; independent aligned references; labelled faults and measured removal outcomes; externally defined step events and settling protocol; matched software and FPGA integer outputs with Q-format/rounding/saturation definitions; measured cycle/latency data and clock frequency; actual Vivado utilization, timing, power and report provenance; and a real Railway account/service/database deployment with end-to-end gateway verification.

## 2026-09-10 final release addendum

This document's earlier sections preserve the initial 2026-09-09 implementation milestone. The current release adds optional reproducibility/filter/Q-format/calibration/Git metadata; migration 0002; protected LOCKED experiments and superuser unlock audits; canonical research ZIPs with dataset/package/per-member SHA256 integrity; independent HIL software references aligned by run, sensor and sequence; package/finalization UI actions; and gateway/acceptance documentation. The original scientific prerequisites and SIMULATED provenance remain in force.

The application is published at [haivpm2-web/aqua_iceeis26](https://github.com/haivpm2-web/aqua_iceeis26) and deployed at [aquaiceeis26-production.up.railway.app](https://aquaiceeis26-production.up.railway.app/) from verified application commit `7679b9991d968ec62495ee9c3212d11b706b633a`. A dedicated Railway PostgreSQL service is connected. Actual migrations, static collection, Gunicorn startup and public database-backed health passed. The 82-test suite passed on local SQLite and CI PostgreSQL 17; CI also built and ran the Linux Docker/Gunicorn application successfully. Local final browser and 1,000/10,000/50,000-sample SIMULATED acceptance passed, as did final remote API and browser acceptance with 1,000/10,000-sample SIMULATED runs.

The earlier statements that deployment, PostgreSQL and Docker runtime are unexecuted are superseded by this addendum and the final evidence reports. The earlier broad Railway configuration-deprecation statement should not be relied upon: this release archives the old file at `docs/railway.legacy.json` and configures its actual service through supported API settings. This is a project configuration choice, not a general claim that Railway config-as-code is unavailable or deprecated.

See [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md) and [RAILWAY_DEPLOYMENT_REPORT.md](RAILWAY_DEPLOYMENT_REPORT.md) for the final remote API/browser result, deployment identities and reproducible evidence. Physical acquisition/gateway integration, sensor calibration, hardware integer traces, FPGA latency and actual Vivado reports still require experiments and supplied measurements.
