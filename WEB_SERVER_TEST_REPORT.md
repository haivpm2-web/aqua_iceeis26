# Web Server Test Report

Date: 2026-09-09. Environment: Windows, Python 3.14.6, Django 5.2.17, local SQLite, Chromium through Playwright 1.62.0. All recorded numerical demonstration data are **SIMULATED**, not physical FPGA results.

## Executed checks

| Check | Result | Evidence |
| --- | --- | --- |
| `python manage.py check` | PASS | No issues, zero silenced |
| `python manage.py makemigrations --check` | PASS | No changes detected |
| `python manage.py migrate --noinput` | PASS | Initial migrations applied; final check found no unapplied migrations |
| `python manage.py collectstatic --noinput` | PASS | WhiteNoise manifest and compressed assets generated |
| `python manage.py test --verbosity 1` | PASS | 47 tests across three modules; zero failures/errors |
| `python manage.py check --deploy` with `DEBUG=false` and a generated ephemeral strong key | PASS | No issues, zero silenced |
| `python -m pip check` | PASS | No broken requirements |
| `node --check monitoring/static/monitoring/dashboard.js` | PASS | Valid JavaScript syntax |
| Local `/health/` HTTP request | PASS | HTTP 200, server/database `ok` |
| Demo ingestion | PASS | Two isolated SIMULATED runs, IDs 1 and 2, 1,000 samples each |
| Browser page checks | PASS | Eleven main routes returned HTTP 200 with no visible application errors |
| Chart rendering | PASS | Four sensor charts and diagnostics have 500 points by default; paper mode displays all 1,000 demo points |
| Configurable visible window | PASS | Changing to 100 samples updates rendered chart datasets |
| Run comparison | PASS | Runs 1 and 2 produced four sensor comparison rows |
| Sample CSV download | PASS | Browser download saved; API tests check headers, values, source and malformed-row reports |
| Chart PNG download | PASS | Browser download saved |
| Paper mode | PASS | No navigation sidebar; SIMULATED source retained; screenshot and PDF generated |
| Mobile layout | PASS | 390 × 844 viewport, no horizontal document overflow |
| JavaScript runtime | PASS | No page errors across browser checks |

## Automated coverage

`monitoring/tests.py`: 21 tests covering statistical formulas, aligned reductions, error/SNR prerequisites, latency percentiles, integer fixed-point requirements, sequence gaps/duplicates/reordering, outlier labels, STEP timing/dwell, ingestion/authentication, atomic batch validation, invalid-packet retention/exclusion, optional fields, range validation, history/latest/downsampling, run creation/statistics, CSV export/import reports, all pages, database-failing health behavior, event/synthesis validation and production simulation blocking.

`monitoring/test_api_review.py`: 16 regressions covering exact bounded downsampling with endpoints, empty sets/page rules, receipt-order latest, bounded IDs, nonexistent runs, validation before CSV streaming, source labels in projections/exports, malformed mappings, atomic file-level failures, row-level partial-import reporting, bounded run-lookup query count, unsupported HTTP methods, malformed bearer tokens, shared table/time filters and pagination.

`monitoring/test_science_review.py`: 10 regressions covering malformed object/configuration inputs, nested invalid numeric values, future clocks, explicit reference timestamp mismatch, source immutability, cache invalidation after edits, transient episodes versus flagged samples, raw-only reference errors, missing threshold crossings and validation through admin forms.

## Errors fixed during implementation

- First test run: 20 tests passed and one failed because the collected static manifest did not yet exist. Static collection is now documented before a clean-install test run.
- First static collection: Chart.js referenced a missing source map. Added the matching vendored source map and license; collection now succeeds.
- Replaced cache keys containing dictionary whitespace with stable fingerprints and invalidation for edits.
- Corrected history downsampling to retain both interval endpoints and return the requested bounded count.
- Made latest-packet selection use receipt order, preventing device clock skew from pinning an older packet.
- Validated CSV filters before streaming; malformed mappings/file-level parse failures cannot partially commit data.
- Added scientific guards for misaligned references, missing dynamic-response observations and source changes.
- Fixed a regression-test fixture to attach an authenticated-context-compatible user object to an admin request.

## Reproducible browser evidence

Run `python scripts/verify_browser.py` with the local server listening and demo runs 1 and 2 available. Install the optional browser tooling with `python -m pip install playwright==1.62.0` and `python -m playwright install chromium`.

- `evidence/browser-checks.json`: per-route status and chart point counts.
- `evidence/dashboard-simulated.png`, `mobile-simulated.png`: desktop/mobile screenshots.
- `evidence/paper-simulated.png`, `paper-simulated.pdf`: paper view output.
- `evidence/simulated-do-chart.png`: downloaded chart.
- `evidence/run-2-simulated.csv`: downloaded sample data.

These files demonstrate application behavior only. The simulated latency and synthetic signal metrics must not be cited as physical FPGA performance.

## Not executed

Railway remote deployment, live PostgreSQL migrations/queries, a Docker image build, Linux Gunicorn runtime, production load/capacity testing, real gateway/serial/MQTT ingestion, FPGA board experiments and Vivado verification were not executed. No corresponding PASS claim is made. PostgreSQL/Gunicorn/Railway configuration and input infrastructure are supplied for those steps.

Final Django check: **PASS — no issues (0 silenced)**.

## 2026-09-10 final release addendum

The sections above preserve the 2026-09-09 milestone and its 47-test baseline. They do not describe the current deployment status. The final suite now contains **82 tests**, all passing locally on SQLite and in [GitHub Actions run 34486127629](https://github.com/haivpm2-web/aqua_iceeis26/actions/runs/34486127629) on PostgreSQL 17. CI also executed a real Docker build, Linux Gunicorn startup, database-backed health check and production configuration checks successfully.

Local final acceptance passed with separate SIMULATED runs 3/4/5 containing 1,000/10,000/50,000 samples. Checks cover HTTP ingestion, original-data statistics, history/downsampling, comparison, CSV/research ZIP exports, every package member checksum, repeated ZIP equality and write refusal after locking. Final Chromium verification passed routes, charts, export downloads, paper output and 390 × 844 mobile layout without JavaScript/API errors. Evidence is retained in `evidence/final-local-release-checks.json` and `evidence/final-local-browser-checks.json`.

The application is now published at [haivpm2-web/aqua_iceeis26](https://github.com/haivpm2-web/aqua_iceeis26) and deployed at [aquaiceeis26-production.up.railway.app](https://aquaiceeis26-production.up.railway.app/). Railway PostgreSQL migrations, static collection and Gunicorn startup succeeded; public health returned HTTP 200 and the status API identified PostgreSQL and application commit `7679b9991d968ec62495ee9c3212d11b706b633a`. Remote API/browser acceptance passed and is tracked in [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md) and [RAILWAY_DEPLOYMENT_REPORT.md](RAILWAY_DEPLOYMENT_REPORT.md), which are authoritative for its final outcome.

All release acceptance data remain SIMULATED. The older “Not executed” paragraph is historical: PostgreSQL, Docker/Linux/Gunicorn and Railway deployment have now been executed as described here. Physical gateway/FPGA/Vivado experiments, sustained concurrent capacity testing and backup/restore testing remain unexecuted.
