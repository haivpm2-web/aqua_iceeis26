# Final release report — aqua_iceeis26

Date: 2026-09-10. Application release: 1.0.0. Research package schema: 1.

The application is published on GitHub and deployed successfully on Railway with PostgreSQL. Local validation and the GitHub PostgreSQL/container checks passed. Remote API/export checks have been verified across the recorded attempts and independent package rechecks. Final browser acceptance and deployment of a mobile-layout correction are still in progress, so the complete release gate remains open.

## Published and deployed application

| Item | Verified result |
| --- | --- |
| Repository | [haivpm2-web/aqua_iceeis26](https://github.com/haivpm2-web/aqua_iceeis26), branch `main` |
| Verified application commit | `bba24ea7ffb9ae4c9bb6657e1923e7603c655756` |
| Public application | [aquaiceeis26-production.up.railway.app](https://aquaiceeis26-production.up.railway.app/) |
| Railway web deployment | `e8f6f08e-5921-4139-bd07-cb3e1d4c4cfd` — SUCCESS |
| PostgreSQL | Dedicated service from `ghcr.io/railwayapp-templates/postgres-ssl:18`; application reports `database_vendor=postgresql` |
| Public readiness | `/health/` HTTP 200, server/database `ok` |
| Deployed software identity | Status API reports the verified application commit above |
| Remote API/export acceptance | PASS: aggregate checks for runs 1/3; the two individual driver attempts retain their FAIL results |
| Final remote browser acceptance | Pending mobile-layout correction and redeployment |

The application commit identifies code exercised by CI and the initial verified deployment. Later evidence/report commits are separate publication records; no document embeds its own commit hash. See [Railway deployment report](RAILWAY_DEPLOYMENT_REPORT.md) for service identities, settings and evidence.

## Implemented release scope

The existing Django/DRF application, sensor dashboards, CSV workflows and scientific formulas are retained. This release adds optional sampling and FPGA clock frequencies; Q-formats, rounding and saturation settings; filter parameters; sensor/calibration/reference-instrument metadata; and software, FPGA, STM32 and gateway Git identifiers. Existing records remain valid with these optional fields absent. Migration `0002_experimentrun_accumulator_q_format_and_more` adds the release schema without replacing existing runs.

COMPLETED experiments can be finalized as LOCKED with dataset and research-package SHA256 hashes. Guarded API, admin and ORM writes protect the run, samples, events, HIL references and shared FPGA configuration. An active superuser may explicitly unlock with a required reason; the immutable audit retains prior hashes. Bearer credentials cannot unlock.

Canonical research ZIPs contain samples, events, metadata, metrics, FPGA/filter configuration, tables A–E, a provenance README and per-member SHA256 checksums. Independent HIL references are included when supplied. Fixed ordering, canonical serialization and fixed ZIP metadata make repeated exports of unchanged finalized evidence identical. Locked exports verify their stored hashes and refuse mismatches. The dataset hash covers canonical `samples.csv`; the package hash covers the complete ZIP and is stored outside it.

HIL software outputs align by run, sensor and sequence number. Duplicate reference keys are rejected; duplicate packet sequences are reported as ambiguous and excluded from matched results. Error statistics and integer-code agreement use available matched evidence. Float equality never establishes bit-exact agreement. See [research integrity contract](docs/RESEARCH_INTEGRITY.md) and [gateway HTTP protocol](docs/GATEWAY_PROTOCOL.md).

## Executed validation

| Check | Result and evidence |
| --- | --- |
| Local Django suite | PASS: 82 tests, no failures/errors, Windows/Python 3.14.6/Django 5.2.17/SQLite |
| Schema and dependencies | PASS: Django check, migration consistency, migrations, static collection, dependency consistency and JavaScript syntax |
| Production settings | PASS: `check --deploy` under `DEBUG=false` with an ephemeral strong secret |
| PostgreSQL CI | PASS: 82-test suite and migrations on PostgreSQL 17/Python 3.12 in [Actions run 34441801870](https://github.com/haivpm2-web/aqua_iceeis26/actions/runs/34441801870) |
| Actual Linux container | PASS: CI built the Docker image, started Gunicorn against PostgreSQL and received a successful database health response |
| Railway build/runtime | PASS: GitHub-source deployment, PostgreSQL migrations, static collection, Gunicorn startup and public HTTPS health |
| Local HTTP acceptance | PASS: SIMULATED runs 3/4/5 with 1,000/10,000/50,000 samples; APIs, exports, canonical checksums, repeated ZIP equality and mutation refusal after locking |
| Local browser | PASS: routes, charts, comparison, 100-sample window, CSV/PNG/PDF/ZIP downloads, paper layout, mobile 390 × 844 and no JavaScript/API errors |
| Remote HTTP acceptance | PASS: aggregate 1,000/10,000-sample API/statistics/CSV/locking/ZIP checks in `evidence/final-remote-api-verification.json`; individual client timeouts and recovery are detailed below |
| Remote browser | Routes, charts, CSV/PNG/PDF/ZIP passed; mobile overflow requires a correction and final rerun |

The original 47 tests remain. The additional 35 tests cover HIL alignment, canonical packages, integrity verification, lock protection and unlock audit behavior. Docker is unavailable on the local Windows machine; the Docker/Linux PASS refers to actual GitHub Actions execution, with a separate actual Railway deployment.

Local ingestion used sequential 200-sample batches. Runs 3, 4 and 5 took 0.944181, 10.028599 and 47.834919 seconds respectively for HTTP ingestion. These are observed application timings, not FPGA latency, hardware throughput, a concurrent load test or a production capacity guarantee.

The first remote attempt passed its 1,000-sample run (ID 1), with ingestion taking 3.195889 seconds in five 200-sample batches. Its next run (ID 2) stopped after 400 samples when the client timed out during an SSL handshake; independent health/read requests continued to succeed. Run 2 was marked FAILED and its 400 samples retained. The separate SIMULATED retry (ID 3) ingested all 10,000 samples in 38.331178 seconds over fifty 200-sample batches. Statistics, history, tables, pages, CSV and locking checks passed before that driver's ZIP read timed out.

Two independent curl downloads subsequently returned the identical 4,487,329-byte ZIP for locked run 3. All eleven member checksums passed, the ZIP matched its stored SHA256 `c1867b8f0fbde7eb5ce2033294bbfe748a5e03bbf239eed57dad8be530d84830`, and `samples.csv` matched dataset SHA256 `961c126e2c5b2dfe01cab5ee113b6d1634fdb4d815396461c41b67ef8a1dae79`. These successful checks are recorded separately; both original driver reports remain FAIL. Browser routes, charts and CSV/PNG/PDF/ZIP downloads subsequently passed, but a longer run name exposed mobile overflow. A layout correction, redeployment and final browser rerun remain pending.

`evidence/final-remote-api-verification.json` records aggregate PASS for the required API/export checks on runs 1 and 3 across the recorded attempts and independent recovery. Supporting evidence includes `evidence/final-remote-initial-attempt.json`, `evidence/final-remote-retry-attempt.json` and `evidence/final-remote-package-recheck.json`. Neither individual driver report is relabelled PASS. The request failures are observations of the client operations; no unverified root cause or service capacity claim is inferred from them.

Committed evidence includes `evidence/final-local-release-checks.json`, `evidence/final-local-browser-checks.json`, `evidence/final-ci-verification.json`, `evidence/final-remote-health.json`, `evidence/final-railway-web-deployment.json`, `evidence/final-railway-postgres-deployment.json` and `evidence/final-railway-startup.json`. Generated bulk CSV/ZIP/PDF outputs, databases, environments, logs and credentials are excluded from Git. The release tree check scans staged paths and recognizable credential patterns and generates `FINAL_SHA256SUMS.txt` from exact index bytes, excluding the manifest itself; no external secret-audit service PASS is claimed.

## Scientific and operational limits

All verification datasets are **SIMULATED**. No REAL/HIL measurements, Vivado results or measured FPGA latency were fabricated. Invalid packet/CRC rows are retained as communication evidence and excluded from signal metrics. Error/SNR and classification metrics require valid supplied references or labels; dynamic-response metrics require defined STEP observations; bit-exact agreement requires integer codes. Sequence gaps alone do not prove packet loss.

Analysis is synchronous and bounded at 200,000 samples. Display downsampling can omit brief events. Read pages/APIs are public; a shared ingestion token permits implemented research writes but cannot unlock evidence. Direct database administration and deliberately invoked private ORM internals remain trusted infrastructure. SHA256 detects changes relative to a retained digest and is not a digital signature. Retain exported archives with their software commit because subsequent analysis changes can alter recomputed metrics.

Remaining experimental work requires the actual STM32/SPI/gateway transport, clock synchronization and sequence-reset rules, calibrated sensor acquisitions, measured raw/FPGA outputs and latency, labelled faults/interventions, independent references, software/FPGA integer traces and genuine Vivado utilization/timing/power reports. Serial/MQTT integration, physical FPGA experiments, long-duration concurrent capacity tests and backup/restore exercises are not claimed as executed.
