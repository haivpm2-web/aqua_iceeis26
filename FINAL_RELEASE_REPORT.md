# Final release report — aqua_iceeis26

Release version: research schema 1, application release 1.0.0. Date: 2026-09-10.

## Current release gate

Local implementation and browser validation are complete. GitHub publication, Railway deployment and remote validation will be recorded below only after they actually succeed. This file must not be read as a remote deployment success claim while these entries remain pending.

| Item | Result |
| --- | --- |
| Repository name | aqua_iceeis26 |
| Git commit / repository URL | Pending publication |
| Railway URL / PostgreSQL | Pending remote deployment |
| Migrations | 0001 and additive 0002 created; local SQLite migrated |
| Automated tests | 82 PASS, no failures/errors |
| Local stress | PASS: SIMULATED runs 3/4/5 contain 1,000 / 10,000 / 50,000 samples |
| Ingestion timing | 0.944 / 10.029 / 47.835 seconds respectively, 200 samples per batch; application HTTP timing only |
| Dataset exports | PASS: history/downsampling/statistics/tables/CSV/research ZIP and SHA256, mutation refusal after lock |
| Local browser | PASS: all routes, charts, comparison, CSV/PNG/PDF/ZIP, mobile 390 x 844, no JavaScript errors; `evidence/final-local-browser-checks.json` |
| Remote API/browser/health | Not executed yet |

## Implementation

The original Django/DRF architecture and scientific analysis are retained. Added nullable reproducibility/Q-format/filter/calibration/Git metadata; LOCKED state and protected superuser unlock with immutable audit; deterministic research ZIP and stored SHA256 integrity; unique sequence-keyed HIL references and ambiguity reporting; UI package/lock actions; gateway protocol documentation and reproducible local/remote stress/browser drivers. The existing 47 tests remain; 35 further tests cover HIL, package integrity and locking.

Scientific guards preserve supplied-data provenance, exclude invalid packet/CRC rows from signal metrics, require aligned references or true labels for error/classification metrics, require STEP definitions for dynamic metrics, and require integer codes for bit-exact agreement. Sequence gaps never establish proven packet loss. No REAL/HIL measurements, Vivado results or FPGA latency were fabricated by the release verification.

## Validation scope and limitations

Local Windows tests use Python 3.14.6, Django 5.2.17 and SQLite. GitHub Actions is configured to execute PostgreSQL tests and a Linux Gunicorn Docker build/runtime check; its actual result will be recorded after publication. Docker is not installed locally, so no local Docker PASS is claimed.

Analysis is bounded at 200,000 samples and computed synchronously; downsampling is for display and can omit brief events. Shared ingestion tokens permit research API writes but cannot unlock. Direct database administrators/private ORM internals remain trusted; SHA256 is change detection, not a digital signature. Preserve downloaded archives with the software commit because future analysis changes may alter a recomputed metrics file.

Physical work remains: STM32/SPI/gateway wire contract confirmation, clock synchronization and sequence reset rules, sensor calibration, measured raw/FPGA outputs and latency, labelled faults and interventions, independent references, software/FPGA integer trace validation and genuine Vivado utilization/timing/power reports.
